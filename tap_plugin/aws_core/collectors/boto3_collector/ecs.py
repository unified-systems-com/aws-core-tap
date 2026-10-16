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

A denied or failed sub-call never reads as an empty result (``-10``): the node it concerns carries a
``_hydrate`` slot with status ``denied`` / ``error`` (the collector records each as ``HYDRATE_GAP``), and a
service or task is still yielded from the ARN the listing gave when its Describe call failed. A failure of
``ListClusters`` itself raises, so the entry is skipped with a warning rather than reported as a region with
no clusters.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from weakref import WeakKeyDictionary

from botocore.exceptions import BotoCoreError, ClientError

from .authority import COMPLETE, PARTIAL, with_edge_reads
from .envelope import jsonable, without_response_metadata
from .hydrate import _classify
from .listing import error_code, page_says_more
from .source import SourceError

#: The most each Describe call accepts (the ECS API reference).
CLUSTERS_PER_CALL = 100
SERVICES_PER_CALL = 10
TASKS_PER_CALL = 100

#: The ``group`` ECS sets on a task a service launched.
_SERVICE_GROUP_PREFIX = "service:"

_ARN_KEYS = {"clusters": "clusterArn", "services": "serviceArn", "tasks": "taskArn"}


@dataclass
class EcsWalk:
    """Everything one region's ECS fan-out read, as raw items ready for projection."""

    clusters: list[dict[str, Any]] = field(default_factory=list)
    services: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    containers: list[dict[str, Any]] = field(default_factory=list)


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
    op = _api_name(method)
    try:
        return _list_all(client, method, key, **kwargs), _slot(op)
    except _IncompleteListing:
        return [], _slot(op, code="IncompleteListing")
    except (BotoCoreError, ClientError) as exc:
        return [], _slot(op, exc=exc)


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
) -> dict[str, Any]:
    """One task item: the described task, or a minimal one from the listed ARN when Describe failed.

    ``_service_arn`` is the ``RUNS_TASK`` source from a service. Its edge read is ``complete`` when the task
    names no service, or names one found in the cluster's service listing; otherwise ``partial``, so a task
    whose service could not be resolved never claims to have no service.
    """
    item: dict[str, Any] = dict(described) if described is not None else {"taskArn": arn, "clusterArn": cluster_arn}
    item["_task_name"] = _last_segment(arn)
    started = item.get("startedAt")
    item["_started_at"] = jsonable(started) if started else None
    if gap is not None:
        item["_hydrate"] = {"describe": gap}
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
    return with_edge_reads(item, {"clusterArn": COMPLETE, "_service_arn": read})


def _container_items(task: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """``(container items, every container named itself)`` for one described task.

    The item is the container as ECS described it plus ``_task_arn`` (the ``RUNS_CONTAINER`` source). It
    does not carry the task's ``overrides``. An empty ``imageDigest`` is left out, so it projects to null.
    """
    items: list[dict[str, Any]] = []
    named = True
    for container in task.get("containers") or []:
        if not container.get("containerArn"):
            named = False
            continue
        item = dict(container)
        if not item.get("imageDigest"):
            item.pop("imageDigest", None)
        item["_task_arn"] = task["taskArn"]
        items.append(with_edge_reads(item, {"_task_arn": COMPLETE}))
    return items, named


def walk_ecs(client: Any) -> EcsWalk:
    """Read one region's clusters, services, tasks and containers (req-aws-collector-ecs-1, -2, -3).

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
        task_arns, tasks_slot = _listing(
            client, "list_tasks", "taskArns", cluster=cluster_arn, desiredStatus="RUNNING"
        )
        services, service_gaps = _describe(
            client, "describe_services", "services", "services", service_arns, SERVICES_PER_CALL,
            cluster=cluster_arn, include=["TAGS"],
        )  # fmt: skip
        tasks, task_gaps = _describe(
            client, "describe_tasks", "tasks", "tasks", task_arns, TASKS_PER_CALL,
            cluster=cluster_arn, include=["TAGS"],
        )  # fmt: skip

        cluster_item = dict(
            clusters.get(cluster_arn) or {"clusterArn": cluster_arn, "clusterName": _last_segment(cluster_arn)}
        )
        cluster_item["_hydrate"] = {
            **({"describe": cluster_gaps[cluster_arn]} if cluster_arn in cluster_gaps else {}),
            "services": services_slot,
            "tasks": tasks_slot,
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
        for arn in task_arns:
            if arn not in tasks and arn not in task_gaps:
                continue
            task_item = _task_item(arn, cluster_arn, tasks.get(arn), task_gaps.get(arn), by_name)
            walk.tasks.append(task_item)
            if arn in tasks:
                containers, named = _container_items(tasks[arn])
                walk.containers.extend(containers)
                if not named:
                    task_item.setdefault("_hydrate", {})["containers"] = _slot(
                        "DescribeTasks", code="ContainerWithoutArn"
                    )
    return walk


#: One walk per (session, region), so the four entries of a run share one set of ECS calls. A walk that
#: raised is kept too, so a denied ``ListClusters`` is not retried by each of the four entries.
_WALKS: WeakKeyDictionary[Any, dict[str, EcsWalk | BaseException]] = WeakKeyDictionary()


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
        walk = walk_ecs(client)
    except (BotoCoreError, ClientError, SourceError) as exc:
        if memo is not None:
            memo[region] = exc
        raise
    if memo is not None:
        memo[region] = walk
    return walk
