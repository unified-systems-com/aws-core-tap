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
  the value is one a filtering transform drops on purpose, recognised by its own test
  (:data:`FILTERING_TRANSFORMS`: a non-S3 CloudFront origin, an AWS-managed policy);
- a rule whose target type the collector does not model is ``partial``: its edges are never emitted;
- a rule reading a field of the item itself (not a hydrate slot) is ``complete`` only when the field's
  presence is established (:func:`_field_established`). AWS omits an unset optional field from a
  response, and an older API version omits a field it does not know: the two look the same, so an
  absent field is ``partial`` unless a documented sibling in the same response says the field was
  answerable (:data:`ABSENCE_ESTABLISHED`). Ruled 2026-10-05 (Q34): report ``partial``, never drop the
  claim, so the gap stays visible on the batch record.

All rules of one edge type and direction at one anchor are folded into one read, the worst of them
(:func:`worst`), because tap accepts one claim per scope and a claim made from only some of the rules
would propose removing what the others assert.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
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

_AWS_MANAGED_POLICY_RE = re.compile(r"^arn:[a-z0-9-]+:iam::aws:policy/")
_S3_HOST_RE = re.compile(r"(?:^|\.)s3[.-]", re.IGNORECASE)


def _not_an_s3_origin(value: Any) -> bool:
    """A CloudFront origin domain with no S3 host segment: an ALB, API Gateway or custom origin,
    which ``RETRIEVES_CONTENT_FROM`` (to an S3 bucket) does not cover. An S3-looking domain the
    transform could not read is NOT out of scope."""
    return isinstance(value, str) and not _S3_HOST_RE.search(value.strip())


def _aws_managed_policy(value: Any) -> bool:
    """``arn:<partition>:iam::aws:policy/...``: AWS's own policy, never a node of the account."""
    return isinstance(value, str) and bool(_AWS_MANAGED_POLICY_RE.match(value.strip()))


#: Transform name -> the test a value must pass for the transform's ``None`` to mean "this value is
#: not a target of this edge", leaving the read complete. Any other ``None`` for a non-empty value,
#: from these transforms or any other, is "a reference the collector could not map": ``partial``.
FILTERING_TRANSFORMS: dict[str, Callable[[Any], bool]] = {
    "s3_bucket_name_from_origin_domain": _not_an_s3_origin,
    "customer_managed_policy_arn_or_none": _aws_managed_policy,
}

_OPPOSITE = {"outbound": "inbound", "inbound": "outbound"}


def _cloudfront_certificate_answered(item: Mapping[str, Any]) -> bool:
    """A ``DistributionSummary.ViewerCertificate`` that names a NON-ACM source answers "no ACM
    certificate": the CloudFront default certificate, an IAM certificate, or ``CertificateSource``
    ``cloudfront`` / ``iam``. ``CertificateSource: acm`` without an ARN says the opposite and stays
    unanswered."""
    cert = item.get("ViewerCertificate")
    if not isinstance(cert, dict):
        return False
    if cert.get("CertificateSource") == "acm":
        return False
    return (
        cert.get("CloudFrontDefaultCertificate") is True
        or "IAMCertificateId" in cert
        or cert.get("CertificateSource") in ("cloudfront", "iam")
    )


def _sqs_encryption_answered(item: Mapping[str, Any]) -> bool:
    """``GetQueueAttributes(All)`` returns ``SqsManagedSseEnabled`` on every API version that reports a
    queue's server-side encryption; when it is there, an absent ``KmsMasterKeyId`` means "no KMS key"."""
    return "SqsManagedSseEnabled" in item


#: ``(entity_type, value_path)`` -> a test on the item that establishes an ABSENT field as answered
#: (complete and empty). Every field not named here reads ``partial`` when absent.
ABSENCE_ESTABLISHED: dict[tuple[str, str], Callable[[Mapping[str, Any]], bool]] = {
    ("aws_core__aws_cloudfront_distribution", "ViewerCertificate.ACMCertificateArn"): _cloudfront_certificate_answered,
    ("aws_core__aws_sqs_queue", "KmsMasterKeyId"): _sqs_encryption_answered,
}


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


def _path_present(item: Any, value_path: str) -> bool:
    """Whether every key on ``value_path`` is present, up to its last list segment.

    A list segment's elements were read whole, so a key missing inside one element is that element's
    own answer (a trust statement with no ``Federated`` principal). Above the last list, and on a path
    with no list at all, a missing key is a field the response did not carry.
    """
    parts = value_path.split(".")
    last_list = max((i for i, part in enumerate(parts) if part.endswith("[]")), default=None)
    checked = parts if last_list is None else parts[: last_list + 1]
    value: Any = item
    for part in checked:
        key = part.removesuffix("[]")
        if not isinstance(value, dict) or key not in value:
            return False
        value = value[key]
    return True


def _field_established(node: ProjectedNode, value_path: str) -> bool:
    """Whether the item's field at ``value_path`` is present, or its absence is a documented answer."""
    item = node.raw_item
    if not isinstance(item, dict):
        return False
    if _path_present(item, value_path):
        return True
    established = ABSENCE_ESTABLISHED.get((node.entity_type, value_path))
    return established is not None and established(item)


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
    if (
        status == COMPLETE
        and not rule["value_path"].startswith("_hydrate")
        and not _field_established(node, rule["value_path"])
    ):
        return PARTIAL
    transform_name = rule.get("transform")
    if status != COMPLETE or not transform_name:
        return status
    transform = transforms.get(transform_name)
    source_aware = transforms.is_source_aware(str(transform_name))
    out_of_scope = FILTERING_TRANSFORMS.get(str(transform_name))
    for value in _values(eval_path(item, rule["value_path"])):
        mapped = transform(value, source_key=node.natural_key) if source_aware else transform(value)
        if mapped is None and not (out_of_scope is not None and out_of_scope(value)):
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
    anchor: Mapping[str, Any],
    reads: Mapping[tuple[str, str], str],
    *,
    unclaimable: frozenset[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    """The authority claims for one anchor, in the shape tap's ``GriftAuthorityClaim`` accepts.

    ``anchor`` names the node by type and full natural key (``{entity_type, key}``), built by
    :func:`.batch.node_anchor` from the envelope the batch sends: the collector mints no id, so
    the anchor is the same identity core finds the node by. ``read`` is always present and never
    defaulted (tap refuses a claim without one).
    """
    entity_type = str(anchor["entity_type"])
    return [
        {
            "edge_type": edge_type,
            "anchor": {"entity_type": entity_type, "key": dict(anchor["key"])},
            "direction": direction,
            "read": read,
        }
        for (edge_type, direction), read in sorted(reads.items())
        if (entity_type, edge_type, direction) not in unclaimable
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
