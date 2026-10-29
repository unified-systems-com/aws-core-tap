"""Join the ledger's facts with its decisions into one deterministic document.

Spec: ``specs/spec-aws-core-coverage-ledger.md`` (``req-aws-core-ledger-states``, ``-tags``, ``-scope``).

Facts come from ``sources.py`` and are re-derived on every run. Decisions are the committed
``decisions.json``: which entity types map to which CloudFormation types, which botocore service a
CloudFormation service means when its name does not say, and the reviewed ``excluded`` or
``not-enumerable`` classifications. A type with no decision is ``unclassified``; nothing here guesses.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .sources import BotoService, CfnType, normalise

PARTITIONS = ("aws", "aws-us-gov")
STATES = ("unclassified", "excluded", "not-enumerable", "modeled", "collected-unverified", "collected-verified")
#: A manifest ``tags.source`` and the treatment the ledger records for it (``req-aws-core-ledger-tags``).
TREATMENT_OF_SOURCE = {"rgta": "rgta", "service": "side-call", "field": "inline", "organizations": "organizations", "none": "none"}


class LedgerError(Exception):
    """The facts and the decisions disagree, or a decision names something that does not exist."""


@dataclass(frozen=True)
class Inputs:
    cfn: dict[str, CfnType]
    cfn_sha256: str
    botocore_version: str
    boto: dict[str, BotoService]
    partitions: dict[str, frozenset[str]]
    #: every endpoint prefix botocore's endpoint data names in any partition; one named in none is unknown
    named_prefixes: frozenset[str]
    decisions: dict[str, Any]
    #: every aws_core entity type with a model, and the manifest entries (entity type -> entry)
    models: frozenset[str]
    manifest: dict[str, dict[str, Any]]


def _boto_services_for(service: str, inputs: Inputs) -> list[str]:
    """The botocore services a CloudFormation service means: the decision if there is one, else by name."""
    declared = inputs.decisions.get("service_map", {}).get(service)
    if declared is not None:
        return sorted(declared)
    wanted = normalise(service)
    candidates: set[str] = set()
    for name, svc in inputs.boto.items():
        if wanted in {normalise(name), normalise(svc.endpoint_prefix)}:
            candidates.add(name)
    exact = [name for name in candidates if normalise(name) == wanted]
    return sorted(exact if len(exact) == 1 else candidates)


def _available(boto_names: list[str], partition: str, inputs: Inputs) -> bool | None:
    """Whether botocore's endpoint data gives the service an endpoint in the partition; None when it does not say."""
    prefixes = [inputs.boto[name].endpoint_prefix for name in boto_names]
    if not prefixes or not any(prefix in inputs.named_prefixes for prefix in prefixes):
        return None
    return any(prefix in inputs.partitions.get(partition, frozenset()) for prefix in prefixes)


def _tier(commercial: bool | None, govcloud: bool | None) -> str:
    if commercial is None or govcloud is None:
        return "unknown"
    if commercial and govcloud:
        return "both"
    if commercial:
        return "commercial-only"
    return "govcloud-only" if govcloud else "neither"


def _validate_decisions(inputs: Inputs) -> dict[str, list[str]]:
    """Cross-check the decisions against the facts; return CloudFormation type -> entity types."""
    decisions = inputs.decisions
    problems: list[str] = []
    for service, names in decisions.get("service_map", {}).items():
        problems += [f"service_map {service}: botocore has no service {n!r}" for n in names if n not in inputs.boto]
    type_map: dict[str, Any] = decisions.get("type_map", {})
    problems += [f"type_map: {e} has no model" for e in type_map if e not in inputs.models]
    problems += [f"type_map is missing the model {e}" for e in sorted(inputs.models) if e not in type_map]
    by_type: dict[str, list[str]] = {}
    for entity, entry in sorted(type_map.items()):
        for cfn_name in entry.get("cfn", []):
            if cfn_name not in inputs.cfn:
                problems.append(f"type_map {entity}: the bundle has no type {cfn_name}")
            by_type.setdefault(cfn_name, []).append(entity)
        if not entry.get("cfn") and not entry.get("reason"):
            problems.append(f"type_map {entity}: no CloudFormation type and no reason")
    classification: dict[str, Any] = decisions.get("classification", {})
    for cfn_name in classification:
        if cfn_name not in inputs.cfn:
            problems.append(f"classification: the bundle has no type {cfn_name}")
        if cfn_name in by_type:
            problems.append(f"classification: {cfn_name} is also modelled as {by_type[cfn_name]}")
    problems += [f"manifest: {e} has no model" for e in inputs.manifest if e not in inputs.models]
    if problems:
        raise LedgerError("\n".join(problems))
    return by_type


def _tags(cfn: CfnType, entities: list[str], inputs: Inputs) -> dict[str, Any]:
    """The tag treatment and its evidence, from the schema and, where a manifest entry exists, from the entry."""
    treatment: str | None = None
    for entity in entities:
        source = ((inputs.manifest.get(entity) or {}).get("tags") or {}).get("source")
        if source in TREATMENT_OF_SOURCE:
            treatment = TREATMENT_OF_SOURCE[source]
            break
    if cfn.taggable is False:
        return {
            "treatment": "none",
            "evidence": "confirmed",
            "taggable": False,
            "tag_property": None,
            "citation": "CloudFormation schema: tagging.taggable is false",
        }
    if cfn.taggable is True:
        return {
            "treatment": treatment,
            "evidence": "confirmed",
            "taggable": True,
            "tag_property": cfn.tag_property,
            "citation": "CloudFormation schema: tagging.taggable is true",
        }
    return {
        "treatment": treatment,
        "evidence": "not-found",
        "taggable": None,
        "tag_property": None,
        "citation": None,
    }


def build_ledger(inputs: Inputs) -> dict[str, Any]:
    by_type = _validate_decisions(inputs)
    classification: dict[str, Any] = inputs.decisions.get("classification", {})
    rows: list[dict[str, Any]] = []
    for type_name in sorted(inputs.cfn):
        cfn = inputs.cfn[type_name]
        boto_names = _boto_services_for(cfn.service, inputs)
        commercial = _available(boto_names, "aws", inputs)
        govcloud = _available(boto_names, "aws-us-gov", inputs)
        entities = by_type.get(type_name, [])
        decision = classification.get(type_name)
        if entities:
            collected = any(e in inputs.manifest for e in entities)
            state, reason = ("collected-unverified" if collected else "modeled"), None
        elif decision:
            state, reason = decision["state"], decision["reason"]
        else:
            state, reason = "unclassified", None
        rows.append(
            {
                "type_name": type_name,
                "service": cfn.service,
                "state": state,
                "reason": reason,
                "entity_types": entities,
                "tier": _tier(commercial, govcloud),
                "partitions": {"aws": commercial, "aws-us-gov": govcloud},
                "botocore_services": boto_names,
                "enumerable_by_botocore": (
                    any(inputs.boto[n].has_enumerator for n in boto_names) if boto_names else None
                ),
                "cfn": {
                    "primary_identifier": list(cfn.primary_identifier),
                    "has_list_handler": cfn.has_list_handler,
                    "has_tagging_block": cfn.has_tagging_block,
                },
                "tags": _tags(cfn, entities, inputs),
            }
        )
    unmapped = [
        {"entity_type": entity, "reason": entry["reason"]}
        for entity, entry in sorted(inputs.decisions.get("type_map", {}).items())
        if not entry.get("cfn")
    ]
    return {
        "description": (
            "AWS coverage ledger (specs/spec-aws-core-coverage-ledger.md): every CloudFormation resource type, with "
            "what aws_core does with it. Generated by `python -m tap_plugin.aws_core.ledger build`; do not edit by "
            "hand. Facts are derived from the CloudFormation schema bundle and botocore; classifications are the "
            "reviewed decisions in decisions.json."
        ),
        "botocore_version": inputs.botocore_version,
        "cfn_bundle_sha256": inputs.cfn_sha256,
        "summary": _summary(rows),
        "unmapped_models": unmapped,
        "rows": rows,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_state = Counter(r["state"] for r in rows)
    in_scope = [r for r in rows if r["tier"] == "both"]
    return {
        "types": len(rows),
        "services": len({r["service"] for r in rows}),
        "by_state": {s: by_state.get(s, 0) for s in STATES},
        "by_tier": dict(sorted(Counter(r["tier"] for r in rows).items())),
        "in_scope_types": len(in_scope),
        "in_scope_unclassified": sum(1 for r in in_scope if r["state"] == "unclassified"),
        "tier_unknown_unclassified": sum(1 for r in rows if r["tier"] == "unknown" and r["state"] == "unclassified"),
        "tags_not_found": sum(1 for r in rows if r["tags"]["evidence"] == "not-found"),
    }


def render(ledger: dict[str, Any]) -> str:
    """The ledger as text: header keys sorted, one row per line, so a diff names the row that moved."""
    head = json.dumps({k: ledger[k] for k in sorted(ledger) if k != "rows"}, indent=1, sort_keys=True, ensure_ascii=False)
    rows = ",\n".join("  " + json.dumps(r, sort_keys=True, ensure_ascii=False) for r in ledger["rows"])
    return head[:-2] + ',\n "rows": [\n' + rows + "\n ]\n}\n"
