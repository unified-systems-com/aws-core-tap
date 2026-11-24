"""SSM managed instances, their patch state, the patches they report, and their compliance: one walk, four node types.

Spec: specs/spec-aws-core-v0.md (req-aws-core-ssm-patch-state), aws-core-tap#281. George's rulings Q116b and Q137a
(build it), Q124a (collect everything, no cap), the SSM design rulings A1 and B2 (2026-11-22), and Q147 option 3
(only the patches that need action are edges).

A manifest entry yields one node type, but the four types come from one fan-out per region, so :func:`shared_walk`
makes the calls once per (run, region) and the four ``custom_fn`` wrappers in :mod:`.customfns` each take their slice:

- ``DescribeInstanceInformation``: every managed instance, EC2 or hybrid (``mi-``). A failure here raises, so all four
  entries are skipped for the region rather than read as a region with nothing managed.
- ``ListTagsForResource`` (``ManagedInstance``) for a hybrid node; an EC2 node's tags are on the EC2 instance.
- ``DescribeInstancePatchStates``, 50 instances per call: each instance's last patch operation, held on the instance
  (A1). ``OwnerInformation``, which botocore marks sensitive, is dropped as the response is read and never reaches an
  item.
- ``DescribePatchBaselines`` with no filter, read only when some instance has a patch state: which operating system
  each baseline patches, so a patch can be keyed by operating system. Nothing from it is emitted here; the baselines
  themselves are the baseline walk's (:mod:`.ssm_baselines`, Q139a).
- ``DescribeInstancePatches`` per instance with a patch state, read to its end. A row whose state needs action
  (:data:`GAP_STATES`) is a ``REPORTS_PATCH`` from the instance, carrying its state, severity and install time, to a
  shared ``aws_ssm_patch`` node keyed (partition, operating system, KBId) (B2). Any other row (``INSTALLED``,
  ``INSTALLED_OTHER``, ``NOT_APPLICABLE``) is neither an edge nor a node: the instance's count fields carry it, and
  its stored ``_patch_list`` note names this call as where AWS lists every patch (Q147 option 3). The edge list is
  ``edge_only`` in the manifest, so it is not in the instance's stored configuration. The read stays ``complete``,
  so the authority claim retires the edge of a gap that closed (the patch now installed) as a complete-surface
  absence.
- ``ListResourceComplianceSummaries``: one ``aws_ssm_compliance_summary`` node per (resource, compliance type).
- ``ListComplianceItems`` per instance, ``ComplianceType`` not ``Patch``: the Association and Custom items, each an
  ``aws_ssm_compliance_item`` node. Patch items are not read twice: ``DescribeInstancePatches`` is their source.

The patch, summary and item entries build their batch refs with ``derive`` from the run's scope, so the walk needs
no account and makes no STS call; a summary and an item name their managed instance by ``ResourceId`` (an inbound
edge rule), and the walk names each patch with the patch entry's own template (:data:`PATCH_KEY_TEMPLATE`).

A denied or failed per-instance call never reads as an empty answer: the instance's item carries a ``_hydrate`` slot
(the collector records it as ``HYDRATE_GAP``), and the edge reads it fed are ``failed`` (authority.py), so no claim is
made over edges the run could not see. A gap row that cannot be keyed (its baseline's operating system is unknown,
or it has no KBId) makes that instance's ``REPORTS_PATCH`` read ``partial``; a row that is not a gap is never an edge,
so it does not.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from weakref import WeakKeyDictionary

from botocore.exceptions import BotoCoreError, ClientError

from .authority import COMPLETE, FAILED, PARTIAL, with_edge_reads, worst
from .envelope import jsonable, without_response_metadata
from .hydrate import _classify
from .listing import error_code
from .source import SourceError

MANAGED_INSTANCE_TYPE = "aws_core__aws_ssm_managed_instance"
PATCH_TYPE = "aws_core__aws_ssm_patch"
SUMMARY_TYPE = "aws_core__aws_ssm_compliance_summary"
ITEM_TYPE = "aws_core__aws_ssm_compliance_item"

#: The most instance ids ``DescribeInstancePatchStates`` accepts in one call (botocore ``InstanceIds`` max 50).
PATCH_STATES_PER_CALL = 50
#: The compliance type whose items ``DescribeInstancePatches`` reads; ``ListComplianceItems`` reads every other one.
PATCH_COMPLIANCE_TYPE = "Patch"
#: The compliance type whose item id is an association id (AWS Systems Manager, "Association compliance").
ASSOCIATION_COMPLIANCE_TYPE = "Association"
#: The ``ResourceType`` ``DescribeInstanceInformation`` gives an EC2 instance (the other is ``ManagedInstance``).
EC2_RESOURCE_TYPE = "EC2Instance"
#: The ``ResourceTypes`` value ``ListComplianceItems`` takes for a managed node.
COMPLIANCE_RESOURCE_TYPE = "ManagedInstance"

#: The ``DescribeInstancePatches`` states that need action on the instance, the only rows that are a ``REPORTS_PATCH``
#: edge and the only patches that are nodes (ruling Q147 option 3). ``INSTALLED``, ``INSTALLED_OTHER`` and
#: ``NOT_APPLICABLE`` rows are counted by the instance's fields and listed by AWS, not stored.
GAP_STATES: frozenset[str] = frozenset(
    {"MISSING", "FAILED", "INSTALLED_PENDING_REBOOT", "INSTALLED_REJECTED", "AVAILABLE_SECURITY_UPDATE"}
)
#: The note stored on every instance with a patch state, in place of the per-patch list (Q147 option 3).
PATCH_LIST_NOTE: dict[str, str] = {
    "op": "DescribeInstancePatches",
    "note": (
        "Only patches that need action (MISSING, FAILED, INSTALLED_PENDING_REBOOT, INSTALLED_REJECTED, "
        "AVAILABLE_SECURITY_UPDATE) are REPORTS_PATCH edges, and the per-patch list is not stored. The patch_*_count "
        "fields count every state; DescribeInstancePatches with this InstanceId lists every patch AWS holds for it."
    ),
}

_SPLIT = re.compile(r"[\s,]+")


def _slot(op: str, exc: BaseException) -> dict[str, Any]:
    code = error_code(exc) or type(exc).__name__
    return {"status": _classify(code), "op": op, "error_code": code}


def _pages(client: Any, method: str, key: str, **kwargs: Any) -> list[dict[str, Any]]:
    """Every ``key`` entry of a paginated SSM listing, read to its end; raises when a call fails."""
    out: list[dict[str, Any]] = []
    for page in client.get_paginator(method).paginate(**kwargs):
        out.extend(jsonable(without_response_metadata(page)).get(key) or [])
    return out


def _instant(value: Any) -> str | None:
    """An ISO 8601 instant, or None for AWS's "never" (absent, or the Unix epoch it reports for a patch not
    installed)."""
    if not value:
        return None
    text = str(value)
    try:
        if datetime.fromisoformat(text) <= datetime(1970, 1, 1, tzinfo=UTC):
            return None
    except ValueError:
        return text
    return text


def cve_ids(value: Any) -> list[str]:
    """``CVEIds`` as a list: AWS returns one string of comma-separated ids. Order kept, repeats dropped."""
    seen: list[str] = []
    for token in _SPLIT.split(str(value or "")):
        if token and token not in seen:
            seen.append(token)
    return seen


#: The patch entry's ``derive`` template for its batch ref, which the walk also uses to name the patch from each
#: instance's ``REPORTS_PATCH``; a test holds the two equal.
PATCH_KEY_TEMPLATE = "{partition}:{OperatingSystem}:{KBId}"


def patch_key(partition: str, operating_system: str, kb_id: str) -> str:
    """A patch's batch ref: the patch is the vendor's, not an account's, so it is keyed (partition, operating
    system, KBId) and one node serves every instance and account that reports it."""
    return PATCH_KEY_TEMPLATE.format(partition=partition, OperatingSystem=operating_system, KBId=kb_id)


@dataclass
class SsmWalk:
    """Everything one region's SSM fan-out read, as raw items ready for projection."""

    instances: list[dict[str, Any]] = field(default_factory=list)
    patches: dict[str, dict[str, Any]] = field(default_factory=dict)
    summaries: list[dict[str, Any]] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)


def _hybrid_tags(client: Any, instance_id: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """A hybrid node's tags (ListTagsForResource, ResourceType ManagedInstance), or the slot of a failed read."""
    try:
        response = client.list_tags_for_resource(ResourceType=COMPLIANCE_RESOURCE_TYPE, ResourceId=instance_id)
    except (BotoCoreError, ClientError) as exc:
        return [], _slot("ListTagsForResource", exc)
    return list(jsonable(without_response_metadata(response)).get("TagList") or []), None


def _baseline_systems(client: Any) -> tuple[dict[str, str], dict[str, Any] | None]:
    """BaselineId -> OperatingSystem for every baseline the region lists, the account's and AWS's."""
    try:
        listed = _pages(client, "describe_patch_baselines", "BaselineIdentities")
    except (BotoCoreError, ClientError) as exc:
        return {}, _slot("DescribePatchBaselines", exc)
    return {str(b["BaselineId"]): str(b.get("OperatingSystem") or "") for b in listed if b.get("BaselineId")}, None


def _patch_states(client: Any, ids: list[str]) -> tuple[dict[str, dict[str, Any]], set[str], dict[str, Any] | None]:
    """InstanceId -> patch state, the ids whose chunk failed, and the failure's slot."""
    states: dict[str, dict[str, Any]] = {}
    failed: set[str] = set()
    slot: dict[str, Any] | None = None
    for start in range(0, len(ids), PATCH_STATES_PER_CALL):
        chunk = ids[start : start + PATCH_STATES_PER_CALL]
        try:
            for state in _pages(client, "describe_instance_patch_states", "InstancePatchStates", InstanceIds=chunk):
                state.pop("OwnerInformation", None)  # botocore-sensitive; never kept (ruling A1)
                if state.get("InstanceId"):
                    states[str(state["InstanceId"])] = state
        except (BotoCoreError, ClientError) as exc:
            failed.update(chunk)
            slot = _slot("DescribeInstancePatchStates", exc)
    return states, failed, slot


def _instance_patches(
    client: Any, instance_id: str, operating_system: str, partition: str, walk: SsmWalk
) -> tuple[list[dict[str, Any]], str, dict[str, Any] | None]:
    """The instance's ``REPORTS_PATCH`` values (its gap rows only), how the read went, and its slot when it failed."""
    try:
        reported = _pages(client, "describe_instance_patches", "Patches", InstanceId=instance_id)
    except (BotoCoreError, ClientError) as exc:
        return [], FAILED, _slot("DescribeInstancePatches", exc)
    edges: list[dict[str, Any]] = []
    read = COMPLETE
    for patch in reported:
        if patch.get("State") not in GAP_STATES:
            continue  # counted by the instance's fields, listed by AWS; not an edge (Q147 option 3)
        kb_id = str(patch.get("KBId") or "")
        if not kb_id or not operating_system:
            read = PARTIAL  # reported, but nothing to key it by
            continue
        key = patch_key(partition, operating_system, kb_id)
        walk.patches.setdefault(
            key,
            {
                "OperatingSystem": operating_system,
                "KBId": kb_id,
                "Title": patch.get("Title"),
                "Classification": patch.get("Classification"),
                "_cve_ids": cve_ids(patch.get("CVEIds")),
            },
        )
        edges.append(
            {
                "key": key,
                "properties": {
                    "state": patch.get("State"),
                    "severity": patch.get("Severity"),
                    "installed_time": _instant(patch.get("InstalledTime")),
                },
            }
        )
    return edges, read, None


def _compliance_items(client: Any, instance_id: str, walk: SsmWalk) -> dict[str, Any] | None:
    """The instance's non-Patch compliance items, as nodes; returns the slot of a failed read. The entry's ``derive``
    builds each key, and each item names its managed instance by ``ResourceId``. An item with neither an Id nor a
    Title cannot be keyed and is not sent."""
    try:
        listed = _pages(
            client,
            "list_compliance_items",
            "ComplianceItems",
            ResourceIds=[instance_id],
            ResourceTypes=[COMPLIANCE_RESOURCE_TYPE],
            Filters=[{"Key": "ComplianceType", "Values": [PATCH_COMPLIANCE_TYPE], "Type": "NOT_EQUAL"}],
        )
    except (BotoCoreError, ClientError) as exc:
        return _slot("ListComplianceItems", exc)
    for item in listed:
        compliance_type = str(item.get("ComplianceType") or "")
        if compliance_type == PATCH_COMPLIANCE_TYPE:
            continue  # the filter excludes them; DescribeInstancePatches is their source
        item_id = str(item.get("Id") or item.get("Title") or "")
        if not compliance_type or not item_id:
            continue
        walk.items.append(
            with_edge_reads(
                {
                    **item,
                    "ResourceType": item.get("ResourceType") or COMPLIANCE_RESOURCE_TYPE,
                    "ResourceId": item.get("ResourceId") or instance_id,
                    "_item_id": item_id,
                    "_execution_time": _instant((item.get("ExecutionSummary") or {}).get("ExecutionTime")),
                    "_association_id": item.get("Id") if compliance_type == ASSOCIATION_COMPLIANCE_TYPE else None,
                },
                {"ResourceId": COMPLETE, "_association_id": COMPLETE},
            )
        )
    return None


def _summaries(listed: list[dict[str, Any]], walk: SsmWalk) -> None:
    """Every compliance summary of the region, as nodes. The entry's ``derive`` builds the key; each summary names its
    managed instance by ``ResourceId``."""
    for summary in listed:
        if not (summary.get("ResourceType") and summary.get("ResourceId") and summary.get("ComplianceType")):
            continue
        walk.summaries.append(
            with_edge_reads(
                {
                    **summary,
                    "_name": f"{summary['ResourceId']} {summary['ComplianceType']}",
                    "_execution_time": _instant((summary.get("ExecutionSummary") or {}).get("ExecutionTime")),
                },
                {"ResourceId": COMPLETE},
            )
        )


def walk_ssm(client: Any, *, partition: str) -> SsmWalk:
    """One region's walk."""
    walk = SsmWalk()
    instances = _pages(client, "describe_instance_information", "InstanceInformationList")
    # A summary listing that did not answer raises: it is not a region with none.
    summaries_raw = _pages(client, "list_resource_compliance_summaries", "ResourceComplianceSummaryItems")
    if not instances and not summaries_raw:
        return walk
    _summaries(summaries_raw, walk)
    ids = [str(i["InstanceId"]) for i in instances if i.get("InstanceId")]
    states, state_failed, state_slot = _patch_states(client, ids) if ids else ({}, set(), None)
    systems: dict[str, str] = {}
    systems_slot: dict[str, Any] | None = None
    if states:
        systems, systems_slot = _baseline_systems(client)
    for info in instances:
        instance_id = str(info.get("InstanceId") or "")
        if not instance_id:
            continue
        hydrate: dict[str, Any] = {}
        state = states.get(instance_id)
        baseline_read = FAILED if instance_id in state_failed else COMPLETE
        if instance_id in state_failed and state_slot:
            hydrate["patch_state"] = state_slot
        patches: list[dict[str, Any]] = []
        patches_read = baseline_read
        if state:
            operating_system = systems.get(str(state.get("BaselineId") or ""), "")
            if not operating_system and systems_slot:
                hydrate["baseline_systems"] = systems_slot
            patches, read, slot = _instance_patches(client, instance_id, operating_system, partition, walk)
            patches_read = worst([patches_read, read])
            if slot:
                hydrate["patches"] = slot
        items_slot = _compliance_items(client, instance_id, walk)
        if items_slot:
            hydrate["compliance_items"] = items_slot

        record: dict[str, Any] = {
            **info,
            "_name": info.get("Name") or info.get("ComputerName") or instance_id,
            "_ec2_instance_id": instance_id if info.get("ResourceType") == EC2_RESOURCE_TYPE else None,
            "_patch_state": state or {},
            "_patch_baseline_id": (state or {}).get("BaselineId"),
            "_patch_operation_start_at": _instant((state or {}).get("OperationStartTime")),
            "_patch_operation_end_at": _instant((state or {}).get("OperationEndTime")),
            "_patch_last_no_reboot_install_at": _instant((state or {}).get("LastNoRebootInstallOperationTime")),
            "_patches": patches,
        }
        if state:
            record["_patch_list"] = dict(PATCH_LIST_NOTE)
        if info.get("ResourceType") == EC2_RESOURCE_TYPE:
            # An EC2 node's tags are the EC2 instance's, on that node; SSM has none of its own to read.
            record["_tags_unread"] = True
        else:
            tags, tags_slot = _hybrid_tags(client, instance_id)
            record["_tags"] = tags
            if tags_slot:
                record["_tags_unread"] = True
                hydrate["tags"] = tags_slot
        if hydrate:
            record["_hydrate"] = hydrate
        walk.instances.append(
            with_edge_reads(
                record,
                {
                    "_ec2_instance_id": COMPLETE,
                    "_patch_baseline_id": baseline_read,
                    "_patches": patches_read,
                },
            )
        )
    return walk


_WALKS: WeakKeyDictionary[Any, dict[str, SsmWalk | BaseException]] = WeakKeyDictionary()
#: Per run, the patch keys already yielded: a patch is the vendor's, so the second region that reports it does not
#: send it again (which would be a ``DUPLICATE_IDENTITY``); its edges from that region's instances still name it.
_YIELDED_PATCHES: WeakKeyDictionary[Any, set[str]] = WeakKeyDictionary()


def shared_walk(session: Any, client_for: Any, *, partition: str) -> SsmWalk:
    """The region's :class:`SsmWalk`, made once per session (a session is the run's own and never reused)."""
    client = client_for("ssm")
    region = str(getattr(getattr(client, "meta", None), "region_name", "") or "")
    memo: dict[str, SsmWalk | BaseException] | None = None
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
        walk = walk_ssm(client, partition=partition)
    except (BotoCoreError, ClientError, SourceError) as exc:
        if memo is not None:
            memo[region] = exc
        raise
    if memo is not None:
        memo[region] = walk
    return walk


def new_patches(session: Any, walk: SsmWalk) -> Iterator[dict[str, Any]]:
    """The walk's patches this run has not yielded yet."""
    yielded: set[str] | None = None
    if session is not None:
        try:
            yielded = _YIELDED_PATCHES.setdefault(session, set())
        except TypeError:
            yielded = None
    for key, patch in walk.patches.items():
        if yielded is not None:
            if key in yielded:
                continue
            yielded.add(key)
        yield patch
