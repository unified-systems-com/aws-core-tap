"""SSM patch baselines, each account's default baseline per operating system, and patch groups: one walk, three types.

Spec: specs/spec-aws-core-v0.md (req-aws-core-ssm-baselines), aws-core-tap#281. George's rulings Q139a option 2 and
Q139b (2026-11-24).

One region's reads, made once per run and region (:func:`shared_baselines`), as the SSM patch walk is
(:mod:`.ssm_patch`):

- ``DescribePatchBaselines`` with no filter, read to its end: the account's own baselines and AWS's. A failure raises,
  so the baseline and default entries are skipped for the region rather than read as a region with none.

  - An **AWS-owned** baseline (its ``BaselineId`` is an ARN under AWS's own account) is one node per region shared by
    every account that lists it, keyed by that ARN (Q139a option 2). The collector stamps ``aws.account`` from the
    key's own account segment (``containment.resource_owner``), so the node is AWS's, never the collecting account's.
    Its ``DefaultBaseline`` flag is the listing account's choice, not a fact of the shared baseline, so it is dropped
    from the item: the default node below carries it. Its tags are AWS's and are not read (null).
  - An **own** baseline (``pb-...``) keeps its flag, and its tags are read by ``ListTagsForResource``
    (``PatchBaseline``); a failed read leaves them unread and is a ``_hydrate`` slot.
- The same listing's ``DefaultBaseline`` rows: the account's default baseline for each operating system in the region,
  one ``aws_ssm_default_patch_baseline`` keyed (partition, account, region, operating system), with
  ``DEFAULTS_TO_PATCH_BASELINE`` to the baseline it names, AWS-owned or the account's own (Q139a). ``DescribePatchBaselines``
  states the flag per baseline, so this needs no ``GetDefaultPatchBaseline`` call per operating system.
- ``DescribePatchGroups``, read to its end: each patch group registered with a baseline, one ``aws_ssm_patch_group``
  keyed (partition, account, region, group), with ``REGISTERED_TO_PATCH_BASELINE`` to every baseline registered for it
  (one per operating system) (Q139b). The mapping names the baseline, so no ``GetPatchBaselineForPatchGroup`` call is
  made. A failure raises, so the group entry is skipped for the region.
- The members of a group come from the SSM patch walk: each managed instance whose last patch operation names the
  group (``PatchGroup``) has ``IN_PATCH_GROUP`` to it, written from the group's side (an inbound rule). A walk that
  failed reads ``failed`` and a group whose instances' patch states were not all read reads ``partial``, so no
  authority claim covers members the run could not see.

The default and group entries build their batch refs with ``derive`` from the run's scope; the walk makes no STS call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from weakref import WeakKeyDictionary

from botocore.exceptions import BotoCoreError, ClientError

from .authority import COMPLETE, FAILED, PARTIAL, with_edge_reads
from .envelope import jsonable, without_response_metadata
from .source import SourceError
from .ssm_patch import _pages, _slot, bare_baseline_id, shared_walk

DEFAULT_BASELINE_TYPE = "aws_core__aws_ssm_default_patch_baseline"
PATCH_GROUP_TYPE = "aws_core__aws_ssm_patch_group"
#: The ``ResourceType`` ``ListTagsForResource`` takes for a patch baseline.
BASELINE_RESOURCE_TYPE = "PatchBaseline"


def aws_owned(baseline_id: str) -> bool:
    """Whether a ``BaselineId`` is AWS's: AWS's baselines are named by an ARN under AWS's own account, an account's
    own by the ``pb-`` id SSM generates for it."""
    return baseline_id.startswith("arn:")


@dataclass
class BaselineWalk:
    """One region's baselines, defaults and patch groups, as raw items ready for projection."""

    baselines: list[dict[str, Any]] = field(default_factory=list)
    defaults: list[dict[str, Any]] = field(default_factory=list)
    #: The ``DescribePatchGroups`` failure, raised by the group entry only, so the baselines are still collected.
    groups_error: BaseException | None = None
    groups: list[dict[str, Any]] = field(default_factory=list)
    #: Bare ``pb-`` id -> the ``BaselineId`` the listing names the baseline by (its node's key).
    keys: dict[str, str] = field(default_factory=dict)


def _own_tags(client: Any, baseline_id: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    try:
        response = client.list_tags_for_resource(ResourceType=BASELINE_RESOURCE_TYPE, ResourceId=baseline_id)
    except (BotoCoreError, ClientError) as exc:
        return [], _slot("ListTagsForResource", exc)
    return list(jsonable(without_response_metadata(response)).get("TagList") or []), None


def _baselines(client: Any, walk: BaselineWalk) -> None:
    for identity in _pages(client, "describe_patch_baselines", "BaselineIdentities"):
        baseline_id = str(identity.get("BaselineId") or "")
        if not baseline_id:
            continue
        walk.keys[bare_baseline_id(baseline_id)] = baseline_id
        if identity.get("DefaultBaseline") is True and identity.get("OperatingSystem"):
            walk.defaults.append(
                with_edge_reads(
                    {
                        "OperatingSystem": identity["OperatingSystem"],
                        "BaselineId": baseline_id,
                        "BaselineName": identity.get("BaselineName"),
                        "_name": f"default {identity['OperatingSystem']}",
                        "_aws_owned": aws_owned(baseline_id),
                    },
                    {"BaselineId": COMPLETE},
                )
            )
        if aws_owned(baseline_id):
            # The listing account's default flag is no fact of AWS's shared baseline; the default node carries it.
            item = {k: v for k, v in identity.items() if k != "DefaultBaseline"}
            walk.baselines.append({**item, "_aws_owned": True, "_tags_unread": True})
            continue
        record: dict[str, Any] = {**identity, "_aws_owned": False}
        tags, slot = _own_tags(client, baseline_id)
        record["_tags"] = tags
        if slot:
            record["_tags_unread"] = True
            record["_hydrate"] = {"tags": slot}
        walk.baselines.append(record)


def _members(session: Any, client_for: Any, partition: str) -> tuple[dict[str, list[str]], str, dict[str, Any] | None]:
    """Patch group -> the managed instances whose last patch operation names it, how the read went, and the slot of a
    failed SSM walk."""
    try:
        ssm = shared_walk(session, client_for, partition=partition)
    except (BotoCoreError, ClientError, SourceError) as exc:
        return {}, FAILED, _slot("DescribeInstanceInformation", exc)
    members: dict[str, list[str]] = {}
    read = COMPLETE
    for instance in ssm.instances:
        if "patch_state" in (instance.get("_hydrate") or {}):
            read = PARTIAL  # this instance's group is unknown
        group = str((instance.get("_patch_state") or {}).get("PatchGroup") or "")
        if group:
            members.setdefault(group, []).append(str(instance["InstanceId"]))
    return members, read, None


def _groups(
    listed: list[dict[str, Any]], walk: BaselineWalk, members: tuple[dict[str, list[str]], str, dict[str, Any] | None]
) -> None:
    by_group: dict[str, list[dict[str, Any]]] = {}
    for mapping in listed:
        group = str(mapping.get("PatchGroup") or "")
        if group:
            by_group.setdefault(group, []).append(mapping.get("BaselineIdentity") or {})
    named, read, slot = members
    for group, identities in sorted(by_group.items()):
        record: dict[str, Any] = {
            "PatchGroup": group,
            "BaselineIdentities": identities,
            # Each baseline by its node's key, whichever spelling the mapping uses (a bare pb- id or the ARN).
            "_baseline_ids": sorted(
                {
                    walk.keys.get(bare_baseline_id(str(i["BaselineId"])), str(i["BaselineId"]))
                    for i in identities
                    if i.get("BaselineId")
                }
            ),
            "_members": sorted(named.get(group, [])),
        }
        if slot:
            record["_hydrate"] = {"members": slot}
        walk.groups.append(with_edge_reads(record, {"_baseline_ids": COMPLETE, "_members": read}))


def walk_baselines(client: Any, *, session: Any, client_for: Any, partition: str) -> BaselineWalk:
    """One region's walk. A failed baseline listing raises; a failed group listing is held for the group entry."""
    walk = BaselineWalk()
    _baselines(client, walk)
    try:
        listed = _pages(client, "describe_patch_groups", "Mappings")
    except (BotoCoreError, ClientError) as exc:
        walk.groups_error = exc
        return walk
    if listed:  # members are looked up only for a region with a group
        _groups(listed, walk, _members(session, client_for, partition))
    return walk


_WALKS: WeakKeyDictionary[Any, dict[str, BaselineWalk | BaseException]] = WeakKeyDictionary()


def shared_baselines(session: Any, client_for: Any, *, partition: str) -> BaselineWalk:
    """The region's :class:`BaselineWalk`, made once per session (a session is the run's own and never reused)."""
    client = client_for("ssm")
    region = str(getattr(getattr(client, "meta", None), "region_name", "") or "")
    memo: dict[str, BaselineWalk | BaseException] | None = None
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
        walk = walk_baselines(client, session=session, client_for=client_for, partition=partition)
    except (BotoCoreError, ClientError, SourceError) as exc:
        if memo is not None:
            memo[region] = exc
        raise
    if memo is not None:
        memo[region] = walk
    return walk


def patch_groups(walk: BaselineWalk) -> list[dict[str, Any]]:
    """The walk's patch groups; raises the group listing's failure, so the entry reads as not collected."""
    if walk.groups_error is not None:
        raise walk.groups_error
    return walk.groups


__all__ = [
    "DEFAULT_BASELINE_TYPE",
    "PATCH_GROUP_TYPE",
    "BaselineWalk",
    "aws_owned",
    "patch_groups",
    "shared_baselines",
    "walk_baselines",
]
