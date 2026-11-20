"""ECS clusters, services, tasks and containers: one walk, four node types.

Spec: specs/spec-aws-core-collector-v0.md (req-aws-collector-ecs).

A manifest entry yields one node type, but the four ECS types come from one fan-out: ``ListClusters`` /
``DescribeClusters``, then per cluster ``ListServices`` / ``DescribeServices`` (10 per call) and
``ListTasks`` / ``DescribeTasks`` (100 per call), the Describe calls with ``include=["TAGS"]``.
:func:`shared_walk` makes those calls once per (run, region) and the four ``custom_fn`` wrappers in
:mod:`.customfns` each take their slice, so the calls are not made four times.

The digest ECS reports per container (``imageDigest``) is the join key to a build's SBOM and findings. It is
stored as ECS reports it. This module makes no registry call and never resolves a tag (``-4``); a container
with no ``imageDigest`` has none in its item, which projects to null, never an empty string (``-5``).

The image a container runs (``-20``..``-23``). computing_core's image is a ``computing_core__host`` of realm
``oci-digest`` keyed by the digest, and a container points at it with ``RUNS_IMAGE__computing_core``. ECS
reported the digest, so :func:`image_writes` stages that host and edge for every container the batch carries
with a well-formed ``imageDigest``, and, where the container's ``image`` names a registry, repository and tag,
the ``computing_core__image_tag`` ECS resolved and its ``TAGS_IMAGE__computing_core`` edge. A host the grid
already holds is sent with its key and kind only, so a name or operating system another producer wrote (Anchore)
is left as it is. This is not a manifest edge rule: the target is another plugin's type, which the rule fence
drops, and core never mints an edge's missing endpoint, so the host has to be staged in the same batch.

Task definitions (``-25``). :func:`describe_task_definitions` describes the ACTIVE revisions and, beside them,
every revision a task or service of the region's walk names that the ACTIVE list lacks (a deregistered revision
a task still runs), so ``USES_TASK_DEFINITION`` never dangles for a task this run wrote.

A denied or failed sub-call never reads as an empty result (``-10``): the node it concerns carries a
``_hydrate`` slot with status ``denied`` / ``error`` (the collector records each as ``HYDRATE_GAP``), and a
service or task is still yielded from the ARN the listing gave when its Describe call failed. A failure of
``ListClusters`` itself raises, so the entry is skipped with a warning rather than reported as a region with
no clusters.

Stopped tasks (``-15``, ``-16``). Each cluster is also listed with ``desiredStatus="STOPPED"``, which returns
the tasks ECS still shows after they stopped (at least an hour, per the ``DescribeTasks`` reference). Only a
stopped task the grid already holds is described and yielded: it records its ``lastStatus`` and stop fields,
and asserts no ``RUNS_TASK`` / ``RUNS_CONTAINER`` edge, with those reads ``partial`` so nothing is claimed
absent. A task that started and stopped between two runs is never created, because without a ``RUNS_TASK``
edge it would be held by nothing and could never be reconciled.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any
from weakref import WeakKeyDictionary

from botocore.exceptions import BotoCoreError, ClientError

from .authority import COMPLETE, PARTIAL, with_edge_reads
from .edges import edge_envelope
from .envelope import jsonable, without_response_metadata
from .hydrate import _classify
from .identity import composite_natural_key, node_ref
from .listing import ListingWalk, error_code, page_says_more
from .source import SourceError

#: The most each Describe call accepts (the ECS API reference).
CLUSTERS_PER_CALL = 100
SERVICES_PER_CALL = 10
TASKS_PER_CALL = 100

#: The ``group`` ECS sets on a task a service launched.
_SERVICE_GROUP_PREFIX = "service:"

_ARN_KEYS = {"clusters": "clusterArn", "services": "serviceArn", "tasks": "taskArn"}

CLUSTER_TYPE = "aws_core__aws_ecs_cluster"
TASK_TYPE = "aws_core__aws_ecs_task"
CONTAINER_TYPE = "aws_core__aws_ecs_container"
RUNS_TASK = "RUNS_TASK__aws_core"
RUNS_CONTAINER = "RUNS_CONTAINER__aws_core"

#: Every (parent type, containment edge) this reader records a surface for. It mirrors the models'
#: ``CONTAINMENT_EDGES`` (``req-aws-core-contained-type-triple-1``; a test holds the two equal).
CONTAINMENT_SURFACES: dict[str, tuple[str, ...]] = {CLUSTER_TYPE: (RUNS_TASK,), TASK_TYPE: (RUNS_CONTAINER,)}
_RELATIONS = {RUNS_TASK: "ecs_cluster.tasks", RUNS_CONTAINER: "ecs_task.containers"}
_NATURAL_KEY_FIELD = {TASK_TYPE: "task_arn", CONTAINER_TYPE: "container_arn"}

#: ``held(entity_type, arn)``: whether the grid already holds a live node for that ARN.
Held = Callable[[str, str], bool]


def held_on_grid(entity_type: str, arn: str) -> bool:
    """The production :data:`Held`: a live row for the ARN, by the type's natural key (never creates one)."""
    from tap_grid.services import find_by_natural_key

    return find_by_natural_key(entity_type, {_NATURAL_KEY_FIELD[entity_type]: arn}) is not None


def _held_by_none(_entity_type: str, _arn: str) -> bool:
    return False


@dataclass
class EcsListing:
    """One parent's containment listing: what the collector turns into a completeness surface.

    ``parent_key`` is the parent's ARN, its natural key, so the surface's subject is the parent's batch ref
    until the import resolves it (``req-aws-core-contained-type-triple``, aws-core-tap#211).
    """

    parent_type: str
    parent_key: str
    edge_type: str
    walk: ListingWalk

    @property
    def relation(self) -> str:
        return _RELATIONS[self.edge_type]


@dataclass
class EcsWalk:
    """Everything one region's ECS fan-out read, as raw items ready for projection."""

    clusters: list[dict[str, Any]] = field(default_factory=list)
    services: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    containers: list[dict[str, Any]] = field(default_factory=list)
    #: A cluster's running-task listing and each described task's containers, one per parent.
    listings: list[EcsListing] = field(default_factory=list)


class _IncompleteListing(Exception):
    """A listing whose final page still reported a continuation: read short, so not an answer."""


def _slot(op: str, *, exc: BaseException | None = None, code: str = "") -> dict[str, Any]:
    """A ``_hydrate`` slot: ``ok``, or what kept the call from answering (never lossy, see hydrate.py)."""
    if exc is None and not code:
        return {"status": "ok", "op": op}
    if exc is not None:
        code = error_code(exc) or type(exc).__name__
        return {"status": _classify(code), "op": op, "error_code": code}
    return {"status": "error", "op": op, "error_code": code}


def _api_name(method: str) -> str:
    """``list_clusters`` -> ``ListClusters`` (the name the manifest and the slots use)."""
    return "".join(part.capitalize() for part in method.split("_"))


def _last_segment(arn: str) -> str:
    return arn.rsplit("/", 1)[-1]


def _chunks(values: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _list_all(client: Any, method: str, key: str, **kwargs: Any) -> list[str]:
    """Every ``key`` entry of a list operation, read page by page to its end; raises when a call fails.

    Raising is deliberate: a listing that errored is not an empty listing, and the caller decides how the
    failure is recorded.
    """
    if client.can_paginate(method):
        pages: Any = client.get_paginator(method).paginate(**kwargs)
    else:
        pages = [getattr(client, method)(**kwargs)]
    out: list[str] = []
    last: Any = None
    for page in pages:
        last = without_response_metadata(page)
        out.extend(last.get(key) or [])
    if last is not None and page_says_more(last):
        raise _IncompleteListing(method)
    return out


def _listing(client: Any, method: str, key: str, **kwargs: Any) -> tuple[list[str], dict[str, Any]]:
    """``(arns, slot)`` for a per-cluster listing. On any failure the arns are empty and the slot says why."""
    arns, slot, _walk = _walked_listing(client, method, key, **kwargs)
    return arns, slot


def _walked_listing(client: Any, method: str, key: str, **kwargs: Any) -> tuple[list[str], dict[str, Any], ListingWalk]:
    """:func:`_listing` plus the :class:`ListingWalk` saying how far the listing got, for its surface."""
    op = _api_name(method)
    walk = ListingWalk()
    try:
        arns = _list_all(client, method, key, **kwargs)
    except _IncompleteListing:
        walk.stopped_short(0, f"{op}: the final page still reports a continuation")
        walk.count = None  # nothing was kept: the items read before the short page are not counted as listed
        walk.admitted = False
        walk.reasons["admitted"] = f"walk_capped: {op} stopped short, so nothing it listed was processed"
        return [], _slot(op, code="IncompleteListing"), walk
    except (BotoCoreError, ClientError) as exc:
        walk.fail(exc)
        return [], _slot(op, exc=exc), walk
    walk.reached_end(len(arns))
    return arns, _slot(op), walk


def _container_walk(
    task: dict[str, Any] | None, gap: dict[str, Any] | None, lookup_failed: str | None = None
) -> ListingWalk:
    """How completely one task's containers were read: from its own ``DescribeTasks`` entry.

    A task that was not described lists no containers, so its surface is not complete; a container that came
    back without an ARN was listed but could not be carried, so the surface is complete but not admitted. A
    stopped task whose container could not be looked up on the grid (``lookup_failed``) left that container out
    for a reason that is not AWS's answer, so the surface is not complete either: an omitted container must never
    read as one the source no longer lists.
    """
    walk = ListingWalk()
    if task is None:
        code = (gap or {}).get("error_code") or "NotDescribed"
        walk.finished = walk.started
        walk.complete = False
        walk.count = None
        walk.admitted = False
        walk.reasons["enumeration_complete"] = f"describe_failed: {code}: the task's containers were not read"
        walk.reasons["admitted"] = f"describe_failed: {code}: nothing to process"
        if (gap or {}).get("status") == "denied":
            walk.authorized = False
            walk.reasons["scope_authorized"] = f"access_denied: {code}"
        else:
            walk.authorized = None
        return walk
    containers = task.get("containers") or []
    walk.reached_end(len(containers))
    if any(not c.get("containerArn") for c in containers):
        walk.drop("a container came back without a containerArn")
    if lookup_failed:
        walk.complete = False
        walk.admitted = False
        walk.reasons["enumeration_complete"] = f"grid_lookup_failed: {lookup_failed}: a listed container was not looked up"
        walk.reasons["admitted"] = f"grid_lookup_failed: {lookup_failed}: a listed container was not processed"
    return walk


def _describe(
    client: Any, method: str, id_kwarg: str, result_key: str, arns: list[str], size: int, **kwargs: Any
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Describe ``arns`` ``size`` at a time. Returns ``(described by arn, failure slot by arn)``.

    An ARN in neither map was reported ``MISSING`` (gone between the list and the describe): it is not
    collected and not an error. A call that raised, or an entry in the response's ``failures`` with any other
    reason, puts a slot on every ARN it concerned, so that node can still be yielded from its ARN.
    """
    op = _api_name(method)
    arn_key = _ARN_KEYS[result_key]
    described: dict[str, dict[str, Any]] = {}
    failed: dict[str, dict[str, Any]] = {}
    for chunk in _chunks(arns, size):
        try:
            response = without_response_metadata(getattr(client, method)(**{id_kwarg: chunk}, **kwargs))
        except (BotoCoreError, ClientError) as exc:
            for arn in chunk:
                failed[arn] = _slot(op, exc=exc)
            continue
        for item in response.get(result_key) or []:
            described[item[arn_key]] = item
        for failure in response.get("failures") or []:
            reason = str(failure.get("reason") or "Unknown")
            if failure.get("arn") and reason != "MISSING":
                failed[failure["arn"]] = _slot(op, code=reason)
    return described, failed


def _task_item(
    arn: str,
    cluster_arn: str,
    described: dict[str, Any] | None,
    gap: dict[str, Any] | None,
    services_by_name: dict[str, str],
    *,
    stopped: bool = False,
) -> dict[str, Any]:
    """One task item: the described task, or a minimal one from the listed ARN when Describe failed.

    ``_cluster_arn_running`` and ``_service_arn`` are the two ``RUNS_TASK`` sources. The cluster one is the
    task's own ``clusterArn``, read ``complete``. ``_service_arn``'s read is ``complete`` when the task names no
    service, or names one found in the cluster's service listing; otherwise ``partial``, so a task whose service
    could not be resolved never claims to have no service.

    A ``stopped`` task (listed with ``desiredStatus="STOPPED"``) carries neither source and reads both
    ``partial``: no cluster or service runs it now, and a ``complete`` read would claim its old ``RUNS_TASK``
    edges absent, which would leave it held by nothing (``-16``).
    """
    item: dict[str, Any] = dict(described) if described is not None else {"taskArn": arn, "clusterArn": cluster_arn}
    item["_task_name"] = _last_segment(arn)
    started = item.get("startedAt")
    item["_started_at"] = jsonable(started) if started else None
    stopped_at = item.get("stoppedAt")
    item["_stopped_at"] = jsonable(stopped_at) if stopped_at else None
    if gap is not None:
        item["_hydrate"] = {"describe": gap}
    if stopped:
        item["_cluster_arn_running"] = None
        item["_service_arn"] = None
        return with_edge_reads(item, {"_cluster_arn_running": PARTIAL, "_service_arn": PARTIAL})
    item["_cluster_arn_running"] = item.get("clusterArn") or cluster_arn
    group = item.get("group")
    service_arn: str | None = None
    read = COMPLETE
    if described is None:
        read = PARTIAL  # the group was not read, so whether a service launched this task is unknown
    elif isinstance(group, str) and group.startswith(_SERVICE_GROUP_PREFIX):
        service_arn = services_by_name.get(group[len(_SERVICE_GROUP_PREFIX) :])
        if service_arn is None:
            read = PARTIAL  # named by the task but absent from the service listing (deleted, or it failed)
    item["_service_arn"] = service_arn
    return with_edge_reads(item, {"_cluster_arn_running": COMPLETE, "_service_arn": read})


def _container_items(
    task: dict[str, Any], *, stopped: bool = False, held: Held = _held_by_none
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """``(container items, every container named itself, the grid lookup failure if any)`` for one described task.

    The item is the container as ECS described it plus ``_task_arn`` (the ``RUNS_CONTAINER`` source). It
    does not carry the task's ``overrides``. An empty ``imageDigest`` is left out, so it projects to null.

    For a ``stopped`` task, only the containers the grid already holds are yielded, with no ``_task_arn`` and
    that read ``partial``: they record their stopped ``lastStatus`` and assert no ``RUNS_CONTAINER`` edge. A
    lookup that fails (an ambiguous key included) skips that container and is returned, so its task's container
    surface can say it is not complete.
    """
    items: list[dict[str, Any]] = []
    named = True
    lookup_failed: str | None = None
    for container in task.get("containers") or []:
        if not container.get("containerArn"):
            named = False
            continue
        if stopped:
            try:
                is_held = held(CONTAINER_TYPE, container["containerArn"])
            except Exception as exc:  # noqa: BLE001 — recorded on the surface, never a crash and never a guess
                lookup_failed = lookup_failed or type(exc).__name__
                continue
            if not is_held:
                continue
        item = dict(container)
        if not item.get("imageDigest"):
            item.pop("imageDigest", None)
        if stopped:
            item["_task_arn"] = None
            items.append(with_edge_reads(item, {"_task_arn": PARTIAL}))
            continue
        item["_task_arn"] = task["taskArn"]
        items.append(with_edge_reads(item, {"_task_arn": COMPLETE}))
    return items, named, lookup_failed


def _held_stopped(
    arns: list[str], running: set[str], held: Held
) -> tuple[list[str], dict[str, Any] | None]:
    """The stopped ARNs the grid already holds, and a slot when the grid could not answer for all of them.

    A grid read that fails yields no stopped task at all (the run records none, which is what it did before
    stopped tasks were listed) and a slot saying why, never a guess. An ARN with more than one live row is a
    grid defect (``AmbiguousIdentity``): that task is skipped, since an upsert on its key could not say which
    row it means, and the slot names the defect so it surfaces as a gap rather than being worked around.
    """
    from tap_grid.natural_key import AmbiguousIdentity

    kept: list[str] = []
    gap: dict[str, Any] | None = None
    for arn in arns:
        if arn in running:
            continue  # listed under both filters (it changed state between the calls): the running read wins
        try:
            if held(TASK_TYPE, arn):
                kept.append(arn)
        except AmbiguousIdentity:
            gap = _slot("FindByNaturalKey", code="AmbiguousIdentity")
        except Exception as exc:  # noqa: BLE001 — a failed grid read is recorded, and stopped tasks are skipped
            return [], _slot("FindByNaturalKey", code=type(exc).__name__)
    return kept, gap


def walk_ecs(client: Any, *, held: Held = _held_by_none) -> EcsWalk:
    """Read one region's clusters, services, tasks and containers (req-aws-collector-ecs-1, -2, -3, -15).

    ``held`` says whether the grid already holds a node for an ARN; only stopped tasks and their containers
    are filtered by it. The default holds nothing, so a walk without the grid yields no stopped task.

    Raises:
        BotoCoreError, ClientError, SourceError: ``ListClusters`` failed, was denied or stopped short; the
            caller records the entry as skipped, which is not the same as the region having no clusters.
    """
    walk = EcsWalk()
    try:
        cluster_arns = _list_all(client, "list_clusters", "clusterArns")
    except _IncompleteListing:
        raise SourceError("ListClusters: the final page still reports a continuation") from None
    clusters, cluster_gaps = _describe(
        client, "describe_clusters", "clusters", "clusters", cluster_arns, CLUSTERS_PER_CALL, include=["TAGS"]
    )
    for cluster_arn in cluster_arns:
        if cluster_arn not in clusters and cluster_arn not in cluster_gaps:
            continue  # MISSING: deleted between the list and the describe
        service_arns, services_slot = _listing(client, "list_services", "serviceArns", cluster=cluster_arn)
        task_arns, tasks_slot, tasks_walk = _walked_listing(
            client, "list_tasks", "taskArns", cluster=cluster_arn, desiredStatus="RUNNING"
        )
        walk.listings.append(EcsListing(CLUSTER_TYPE, cluster_arn, RUNS_TASK, tasks_walk))
        stopped_listed, stopped_slot = _listing(
            client, "list_tasks", "taskArns", cluster=cluster_arn, desiredStatus="STOPPED"
        )
        stopped_arns, held_gap = _held_stopped(stopped_listed, set(task_arns), held)
        services, service_gaps = _describe(
            client, "describe_services", "services", "services", service_arns, SERVICES_PER_CALL,
            cluster=cluster_arn, include=["TAGS"],
        )  # fmt: skip
        tasks, task_gaps = _describe(
            client, "describe_tasks", "tasks", "tasks", task_arns + stopped_arns, TASKS_PER_CALL,
            cluster=cluster_arn, include=["TAGS"],
        )  # fmt: skip

        cluster_item = dict(
            clusters.get(cluster_arn) or {"clusterArn": cluster_arn, "clusterName": _last_segment(cluster_arn)}
        )
        cluster_item["_hydrate"] = {
            **({"describe": cluster_gaps[cluster_arn]} if cluster_arn in cluster_gaps else {}),
            "services": services_slot,
            "tasks": tasks_slot,
            "stopped_tasks": held_gap or stopped_slot,
        }
        walk.clusters.append(cluster_item)

        for arn in service_arns:
            if arn not in services and arn not in service_gaps:
                continue
            service = dict(services.get(arn) or {"serviceArn": arn, "serviceName": _last_segment(arn)})
            service.setdefault("clusterArn", cluster_arn)
            if arn in service_gaps:
                service["_hydrate"] = {"describe": service_gaps[arn]}
            walk.services.append(with_edge_reads(service, {"clusterArn": COMPLETE}))

        by_name = {_last_segment(arn): arn for arn in service_arns}
        stopped_set = set(stopped_arns)
        for arn in task_arns + stopped_arns:
            if arn not in tasks and arn not in task_gaps:
                continue
            stopped = arn in stopped_set
            task_item = _task_item(arn, cluster_arn, tasks.get(arn), task_gaps.get(arn), by_name, stopped=stopped)
            walk.tasks.append(task_item)
            lookup_failed: str | None = None
            if arn in tasks:
                containers, named, lookup_failed = _container_items(tasks[arn], stopped=stopped, held=held)
                walk.containers.extend(containers)
                if not named:
                    task_item.setdefault("_hydrate", {})["containers"] = _slot(
                        "DescribeTasks", code="ContainerWithoutArn"
                    )
            walk.listings.append(
                EcsListing(
                    TASK_TYPE, arn, RUNS_CONTAINER, _container_walk(tasks.get(arn), task_gaps.get(arn), lookup_failed)
                )
            )
    return walk


#: One walk per (session, region), so the four entries of a run share one set of ECS calls. A walk that
#: raised is kept too, so a denied ``ListClusters`` is not retried by each of the four entries.
_WALKS: WeakKeyDictionary[Any, dict[str, EcsWalk | BaseException]] = WeakKeyDictionary()


def walks_of(session: Any) -> list[EcsWalk]:
    """Every region's completed :class:`EcsWalk` for this run's session (a walk that raised has no listings:
    its entries were skipped, and a parent that was not observed has no surface to record)."""
    try:
        memo = _WALKS.get(session) or {}
    except TypeError:
        return []
    return [walk for walk in memo.values() if isinstance(walk, EcsWalk)]


def shared_walk(session: Any, client_for: Any) -> EcsWalk:
    """The region's :class:`EcsWalk`, made once per session (a session is the run's own and never reused)."""
    client = client_for("ecs")
    region = str(getattr(getattr(client, "meta", None), "region_name", "") or "")
    memo: dict[str, EcsWalk | BaseException] | None = None
    if session is not None:
        try:
            memo = _WALKS.setdefault(session, {})
        except TypeError:  # a session that cannot be weakly referenced: no sharing, still correct
            memo = None
    if memo is not None and region in memo:
        cached = memo[region]
        if isinstance(cached, BaseException):
            raise cached
        return cached
    try:
        walk = walk_ecs(client, held=held_on_grid)
    except (BotoCoreError, ClientError, SourceError) as exc:
        if memo is not None:
            memo[region] = exc
        raise
    if memo is not None:
        memo[region] = walk
    return walk


# --- The image a container runs (req-aws-collector-ecs-20 .. -23) ---------------------------------------------------

HOST_TYPE = "computing_core__host"
IMAGE_TAG_TYPE = "computing_core__image_tag"
RUNS_IMAGE = "RUNS_IMAGE__computing_core"
TAGS_IMAGE = "TAGS_IMAGE__computing_core"
#: computing_core's realm for an image host: ``stable_id`` is the image manifest digest.
IMAGE_REALM = "oci-digest"
#: The ``stable_id`` shape computing_core accepts for that realm (``req-computing-core-host-4``); any other
#: ``imageDigest`` is refused on write, so it makes no host and no edge here.
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
#: The custom-reader name the image types' rows carry in ``reader_sensitivity.json``.
READER = "ecs"
#: computing_core's column limits: ``host.name`` 255; ``image_tag`` registry and repository 255, tag 128.
_MAX_HOST_NAME = 255
_MAX_REGISTRY = 255
_MAX_REPOSITORY = 255
#: An OCI tag: at most 128 characters, starting with a word character (the distribution specification).
_TAG_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}")

#: ``host_held(digest)``: whether the grid already holds a live image host for that digest.
HostHeld = Callable[[str], bool]


def host_held_on_grid(digest: str) -> bool:
    """The production :data:`HostHeld`: a live ``computing_core__host`` keyed ``(oci-digest, digest)``."""
    from tap_grid.services import find_by_natural_key

    return find_by_natural_key(HOST_TYPE, host_key(digest)) is not None


def host_key(digest: str) -> dict[str, str]:
    """An image host's natural key."""
    # TAP-KNOWN-DUPE(ecs-image-digest): the digest is also aws_ecs_container.image_digest (models/ecs_container.py),
    # ECS's verbatim observation, which stays on the container when no host can be made (req-aws-collector-ecs-23).
    return {"realm": IMAGE_REALM, "stable_id": digest}


def host_ref(digest: str) -> str:
    """The batch ref of an image host (its composite key, so an endpoint naming it can be split back)."""
    return node_ref(HOST_TYPE, composite_natural_key(host_key(digest)))


def well_formed_digest(value: Any) -> str | None:
    """``value`` when it is a digest computing_core accepts for an image host, else None."""
    return value if isinstance(value, str) and _DIGEST_RE.fullmatch(value) else None


def parse_image_tag(reference: Any) -> tuple[str, str, str] | None:
    """``(registry, repository, tag)`` from an image reference that writes all three, else None.

    computing_core keys a tag on its parts "as written in the reference" (``req-computing-core-image-tag``), so
    nothing is supplied that the reference does not write:

    - a reference with ``@`` names its image by digest; ECS pulled that digest, not a tag, so it makes no tag
      (``app@sha256:...``, and ``app:1.2@sha256:...`` too);
    - the registry is the first path component when it holds a ``.`` or a ``:``, or is ``localhost`` (the rule
      Docker reads a reference by). ``nginx:1.25`` and ``library/nginx:1.25`` write no registry and make no
      tag: Docker Hub is implied there, not written;
    - a reference with no ``:tag`` after its last ``/`` writes no tag (``latest`` is implied, not written).

    A part longer than the ``image_tag`` column, or a tag that is not an OCI tag, makes no tag.
    """
    if not isinstance(reference, str) or not reference or "@" in reference or reference != reference.strip():
        return None
    registry, slash, rest = reference.partition("/")
    if not slash or not ("." in registry or ":" in registry or registry == "localhost"):
        return None
    repository, colon, tag = rest.rpartition(":")
    if not colon or "/" in tag or not repository:
        return None
    if len(registry) > _MAX_REGISTRY or len(repository) > _MAX_REPOSITORY or not _TAG_RE.fullmatch(tag):
        return None
    return registry, repository, tag


@dataclass
class ImageWrites:
    """The image hosts, image tags and their edges one run stages, and what it could not decide."""

    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    #: ``(code, message)`` for the run log.
    notices: list[tuple[str, str]] = field(default_factory=list)


def _host_envelope(digest: str, references: set[str], held: bool) -> dict[str, Any]:
    """The image host node. A held host carries its key and kind only; a new one the reference it was seen as.

    A held host's envelope names no ``name``: the importer leaves the stored name as it is when the envelope
    omits one, and its keep-absent replace leaves every field the payload omits. ``kind`` is ``container``,
    what computing_core gives an image host and what every other producer of one writes.
    """
    fields: dict[str, Any] = {**host_key(digest), "kind": "container"}
    entity: dict[str, Any] = {"ref": host_ref(digest), "entity_type": HOST_TYPE, "dimensions": {}}
    if not held:
        # One stable choice when several containers name the digest differently: the first, sorted.
        name = next((r for r in sorted(references) if len(r) <= _MAX_HOST_NAME), None)
        if name:
            fields["name"] = name
        entity["name"] = name or digest
    return {"entity": entity, "node": fields}


def _tag_envelope(registry: str, repository: str, tag: str) -> dict[str, Any]:
    key = {"registry": registry, "repository": repository, "tag": tag}
    return {
        "entity": {
            "ref": node_ref(IMAGE_TAG_TYPE, composite_natural_key(key)),
            "entity_type": IMAGE_TAG_TYPE,
            "name": f"{registry}/{repository}:{tag}",
            "dimensions": {},
        },
        "node": key,
    }


def image_writes(
    walks: Iterable[EcsWalk],
    container_dimensions: Mapping[str, Mapping[str, str]],
    *,
    host_held: HostHeld = host_held_on_grid,
    sensitivity: Mapping[str, Mapping[str, Any]] | None = None,
) -> ImageWrites:
    """The image hosts, tags and edges for the containers this batch carries (``req-aws-collector-ecs-20``..``-23``).

    ``container_dimensions`` maps the ref of every container node the batch carries to the dimensions it was
    sent with; a container the batch does not carry (a selected run that left the type out) gets nothing, and
    its ``RUNS_IMAGE`` edge takes the container's dimensions, as its ``RUNS_CONTAINER`` edge does. The image
    nodes carry no dimension of their own: an image is not in an account or a region (one digest in two
    registries is one host), so they take their types' defaults.

    - Only a container whose ``imageDigest`` is a well-formed digest (:func:`well_formed_digest`) has an image
      host and a ``RUNS_IMAGE`` edge. Any other has neither and is never claimed to have none: no authority
      claim is made for ``RUNS_IMAGE``.
    - An image tag is staged where the container's ``image`` writes one (:func:`parse_image_tag`) and the
      digest is well-formed. Its ``TAGS_IMAGE`` edge carries ``detected_at``, the latest ``startedAt`` of the
      tasks that ran the pair, and none when no such task has started.
    - ``host_held`` decides how much of the host is written (:func:`_host_envelope`). A lookup that fails sends
      the key and kind only, the write that is safe either way, and says so.
    - A type whose ``reader_sensitivity.json`` row is missing, unreviewed or names a credential is not written
      (the custom-reader rule, :func:`.organizations.sensitivity_refusal`), and neither is any edge to it.
    """
    from .organizations import reader_sensitivity, sensitivity_refusal

    declared = dict(reader_sensitivity(READER) if sensitivity is None else sensitivity)
    out = ImageWrites()
    refused = {t: why for t in (HOST_TYPE, IMAGE_TAG_TYPE) if (why := sensitivity_refusal(t, declared)) is not None}
    for entity_type, why in sorted(refused.items()):
        out.notices.append(("ECS_IMAGE_TYPE_REFUSED", f"{entity_type}: not written, {why}"))
    if HOST_TYPE in refused:
        return out  # every edge here ends at a host

    references: dict[str, set[str]] = {}
    runs: dict[tuple[str, str], Mapping[str, str]] = {}
    tags: dict[tuple[tuple[str, str, str], str], str | None] = {}
    for walk in walks:
        started = {task["taskArn"]: task.get("_started_at") for task in walk.tasks if task.get("taskArn")}
        for container in walk.containers:
            ref = node_ref(CONTAINER_TYPE, str(container.get("containerArn") or ""))
            dimensions = container_dimensions.get(ref)
            digest = well_formed_digest(container.get("imageDigest"))
            if dimensions is None or digest is None:
                continue
            image = container.get("image")
            references.setdefault(digest, set())
            if isinstance(image, str) and image:
                references[digest].add(image)
            runs.setdefault((ref, digest), dimensions)
            parsed = parse_image_tag(image) if IMAGE_TAG_TYPE not in refused else None
            if parsed is not None:
                seen = started.get(str(container.get("taskArn") or container.get("_task_arn") or ""))
                prior = tags.get((parsed, digest))
                tags[(parsed, digest)] = max((t for t in (prior, seen) if t), default=None)

    for digest in sorted(references):
        try:
            held = bool(host_held(digest))
        except Exception as exc:  # noqa: BLE001 — recorded, and the write that is safe either way is sent
            held = True
            out.notices.append(
                (
                    "ECS_IMAGE_HOST_LOOKUP_FAILED",
                    f"image host {digest}: the grid lookup failed ({type(exc).__name__}); sent with its key and kind only",
                )
            )
        out.nodes.append(_host_envelope(digest, references[digest], held))
    for (container_ref, digest), dimensions in runs.items():
        out.edges.append(edge_envelope(RUNS_IMAGE, from_ref=container_ref, to_ref=host_ref(digest), dimensions=dict(dimensions)))
    staged_tags: set[str] = set()
    for ((registry, repository, tag), digest), detected_at in sorted(tags.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        envelope = _tag_envelope(registry, repository, tag)
        if envelope["entity"]["ref"] not in staged_tags:
            staged_tags.add(envelope["entity"]["ref"])
            out.nodes.append(envelope)
        out.edges.append(
            edge_envelope(
                TAGS_IMAGE,
                from_ref=envelope["entity"]["ref"],
                to_ref=host_ref(digest),
                dimensions={},
                properties={"detected_at": detected_at} if detected_at else None,
            )
        )
    return out
