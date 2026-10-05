"""Per-anchor read status for the edge readers, and the authority claims made from it.

Spec: specs/spec-aws-core-collector-v0.md (req-aws-collector-edge-authority); the consumer is tap's
``req-grid-reconcile-edge-authority`` (``edge_cases.authority`` in ``grift-document.schema.json``).

An authority claim says: for this edge type, at this anchor node, in this direction, the batch's
edges are the whole set. tap proposes removing every other live edge in that scope, so the claim is
only as honest as the read behind it. "Found nothing" and "could not look" must never be the same
value, and this module is where the collector decides which one it has.

A read is one of three values, never two:

- ``complete`` -- every source the scope draws on answered in full;
- ``partial`` -- something answered, but not all of it (a page that still said "more", a reference
  the collector could not turn into a target, a value it could not interpret);
- ``failed`` -- a call the scope depends on errored or was denied.

How a manifest edge rule's read is judged, per anchor (:func:`rule_read`):

- a rule reading a hydrate slot (``_hydrate.<slot>...``) is ``complete`` when the slot answered
  (``ok``) or AWS said the configuration does not exist (``absent``), else ``failed``;
- a rule reading a key that a ``custom_fn`` declared in the item's ``_edge_reads`` map takes that
  declaration;
- a rule reading any other key of a ``custom_fn`` item is ``partial``: a reader that did not say how
  it read a key is never trusted to have read it all (fail closed);
- a rule reading an ``aws_op`` item is ``complete``: the item is the API's own record of the resource;
- then, for a rule that is ``complete`` so far, a transform that returns nothing for a non-empty
  reference makes it ``partial`` (the relationship exists, the collector could not wire it), unless
  the transform is one that filters out-of-scope values on purpose (:data:`FILTERING_TRANSFORMS`);
- a rule whose target type the collector does not model is ``partial``: its edges are never emitted.

All rules of one edge type and direction at one anchor are folded into one read, the worst of them
(:func:`worst`), because tap accepts one claim per scope and a claim made from only some of the rules
would propose removing what the others assert.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import cache
from importlib import resources
from typing import Any

from .paths import eval_path
from .projection import ProjectedNode

COMPLETE = "complete"
PARTIAL = "partial"
FAILED = "failed"
#: The closed set tap's claim schema accepts, in order of severity.
READ_STATUSES: tuple[str, ...] = (COMPLETE, PARTIAL, FAILED)
_SEVERITY = {status: rank for rank, status in enumerate(READ_STATUSES)}

#: The reserved item key a ``custom_fn`` uses to say how it read each key an edge rule reads.
EDGE_READS = "_edge_reads"

#: Transforms whose ``None`` means "this value is not a target of this edge" (a non-S3 CloudFront
#: origin, an AWS-managed policy), so dropping it leaves the read complete. Every other transform's
#: ``None`` for a non-empty value means "a reference the collector could not map": ``partial``.
FILTERING_TRANSFORMS = frozenset({"s3_bucket_name_from_origin_domain", "customer_managed_policy_arn_or_none"})

_OPPOSITE = {"outbound": "inbound", "inbound": "outbound"}


def worst(statuses: Iterable[str]) -> str:
    """The most severe of ``statuses``; an unknown value counts as ``failed``.

    No statuses at all is ``partial``: a read nobody described is never complete.
    """
    ranked = [_SEVERITY.get(status, _SEVERITY[FAILED]) for status in statuses]
    if not ranked:
        return PARTIAL
    return READ_STATUSES[max(ranked)]


def with_edge_reads(item: Mapping[str, Any], reads: Mapping[str, str]) -> dict[str, Any]:
    """``item`` plus its ``_edge_reads`` declaration. Every value must be one of :data:`READ_STATUSES`."""
    for key, status in reads.items():
        if status not in _SEVERITY:
            raise ValueError(f"read status for {key!r} must be one of {READ_STATUSES}, not {status!r}")
    return {**item, EDGE_READS: dict(reads)}


def _segments(value_path: str) -> list[str]:
    return [part.removesuffix("[]") for part in value_path.split(".")]


def _declared_read(item: Any, value_path: str, *, from_custom_fn: bool) -> str:
    """How the source of ``value_path`` was read, before any transform is considered."""
    segments = _segments(value_path)
    root = segments[0]
    if root == "_hydrate":
        slot = segments[1] if len(segments) > 1 else ""
        record = ((item.get("_hydrate") if isinstance(item, dict) else None) or {}).get(slot)
        if isinstance(record, dict) and record.get("status") in ("ok", "absent"):
            return COMPLETE
        return FAILED
    declared = item.get(EDGE_READS) if isinstance(item, dict) else None
    if isinstance(declared, dict) and root in declared:
        status = declared[root]
        return status if status in _SEVERITY else FAILED
    return PARTIAL if from_custom_fn else COMPLETE


def _values(raw: Any) -> list[Any]:
    values = raw if isinstance(raw, list) else [raw]
    return [v for v in values if v is not None and v != ""]


def rule_read(
    node: ProjectedNode,
    entry: Mapping[str, Any],
    rule: Mapping[str, Any],
    *,
    modeled_types: set[str],
    transforms: Any,
) -> str:
    """The read status of one manifest edge rule at one anchor node (see the module docstring)."""
    if rule["target_type"] not in modeled_types:
        return PARTIAL
    item = node.raw_item
    status = _declared_read(item, rule["value_path"], from_custom_fn="custom_fn" in entry["source"])
    transform_name = rule.get("transform")
    if status != COMPLETE or not transform_name or transform_name in FILTERING_TRANSFORMS:
        return status
    transform = transforms.get(transform_name)
    source_aware = transforms.is_source_aware(str(transform_name))
    for value in _values(eval_path(item, rule["value_path"])):
        mapped = transform(value, source_key=node.natural_key) if source_aware else transform(value)
        if mapped is None:
            return PARTIAL
    return status


def anchor_reads(
    node: ProjectedNode,
    entry: Mapping[str, Any],
    *,
    modeled_types: set[str],
    transforms: Any,
) -> dict[tuple[str, str], str]:
    """``{(edge_type, direction): read}`` for every scope ``entry``'s edge rules cover at ``node``.

    Rules sharing an edge type and direction fold into one read, the worst of theirs.
    """
    reads: dict[tuple[str, str], list[str]] = {}
    for rule in entry.get("edges", []):
        status = rule_read(node, entry, rule, modeled_types=modeled_types, transforms=transforms)
        reads.setdefault((rule["edge_type"], rule["direction"]), []).append(status)
    return {scope: worst(statuses) for scope, statuses in reads.items()}


def shared_scopes(entries: Iterable[Mapping[str, Any]]) -> frozenset[tuple[str, str, str]]:
    """``(entity_type, edge_type, direction)`` scopes another entry's rules also write into.

    A rule on entry A that points at type B in direction D writes edges into B's scope in the
    opposite direction. A claim made at a B node from B's own rules would then propose removing
    edges A asserts, and if A's read of that node failed nothing in B's read can say so. Such a
    scope is never claimed. The current manifest has none; this keeps a future rule from creating
    one silently.
    """
    return frozenset(
        (rule["target_type"], rule["edge_type"], _OPPOSITE[rule["direction"]])
        for entry in entries
        for rule in entry.get("edges", [])
    )


def claims_for(
    node: ProjectedNode,
    reads: Mapping[tuple[str, str], str],
    *,
    unclaimable: frozenset[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    """The authority claims for one anchor, in the shape tap's ``GriftAuthorityClaim`` accepts.

    The anchor is named by its entity id, which this batch writes. ``read`` is always present and
    never defaulted (tap refuses a claim without one).
    """
    return [
        {
            "edge_type": edge_type,
            "anchor": {"entity_id": str(node.entity_id)},
            "direction": direction,
            "read": read,
        }
        for (edge_type, direction), read in sorted(reads.items())
        if (node.entity_type, edge_type, direction) not in unclaimable
    ]


def merge_claims(claims: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One claim per (edge type, anchor, direction), the worst read where a scope repeats.

    tap fails a whole batch that carries two claims for one scope (``duplicate_authority_claim``).
    """
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for claim in claims:
        scope = (claim["edge_type"], json.dumps(claim["anchor"], sort_keys=True), claim["direction"])
        if scope in merged:
            merged[scope]["read"] = worst([merged[scope]["read"], claim["read"]])
        else:
            merged[scope] = dict(claim)
    return list(merged.values())


@cache
def importer_accepts_edge_cases() -> bool:
    """Whether the running tap's GRIFT schema defines a batch's ``edge_cases`` section.

    The plugin's tap floor predates the section, and an importer that does not know it refuses the
    whole batch. Read from the importer's own published schema, so the answer is the contract the
    batch will be judged by. Anything unreadable is ``False``: no claim is the state that proposes
    nothing.
    """
    try:
        text = resources.files("tap_grid").joinpath("schemas", "grift-document.schema.json").read_text()
        container = json.loads(text)["$defs"]["GriftBatchContainer"]["properties"]
    except ModuleNotFoundError, OSError, ValueError, KeyError, TypeError:
        return False
    return "edge_cases" in container
