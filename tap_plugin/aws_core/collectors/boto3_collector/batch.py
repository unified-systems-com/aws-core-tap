"""GRIFT batch assembly for the boto3 collector (one batch per run).

Spec: plugins/aws_core/specs/spec-aws-core-collector-v0.md
(req-aws-collector-grift-batch).

A pure document-shaper: it turns the run's node + edge envelopes plus
provenance into the GRIFT document root, mirroring the KSI reference
collector's shape in ``aws_core``'s own format. It performs no I/O and never
submits — submission via ``self.submit_grift`` is the runtime integration's
job (``req-aws-collector-grift-batch-3``). The batch carries no deletion or
tombstone content (``req-aws-collector-grift-batch-4``); v0 has no
implied-absence semantics.

Nodes and edges are sent by batch-local ``ref`` (:mod:`.identity`), never by an id this collector
minted: core finds each one's live row by its declared identity, or assigns a UUIDv7 on first
sight. :func:`address_batch` is the last step before assembly: it refuses a node whose declared
key has a hole, keeps one envelope per identity, and names each edge endpoint the batch carries
no node for by type and natural key. Only the per-run ``batch_entity`` id is minted here (``uuid7``).
The one grid read is :func:`withhold_retired_undeclared_edges`, a lookup of fixed edge ids on the
entity spine; everything else here is pure shaping.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid7

from .identity import (
    IdentityError,
    declared_key,
    edge_ref,
    endpoint_key,
    missing_parts,
    split_node_ref,
    undeclared_edge_id,
)
from .projection import ProjectedNode

# The description_json format tag for this collector's provenance payload —
# aws_core's own format, parallel to the KSI collector's.
COLLECTION_FORMAT = "tap.aws_core.collection-v0"

# GRIFT document format version. A literal at the producer, exactly as the
# KSI reference collector does (it is the document's format version, not the
# collector's to derive).
_GRIFT_VERSION = "0"


def persisted_configuration(node: ProjectedNode, *, persist_configuration: bool) -> dict[str, Any]:
    """The ``configuration`` value to persist for ``node``.

    ``persist_configuration`` is the node's manifest entry's flag
    (``req-aws-collector-field-projection-7``): the in-memory envelope when
    true, otherwise ``{}``. ``{}`` is sent explicitly rather than omitted so
    the replace on import sets the column deterministically — a resource
    stored before its entry was turned off has its configuration replaced
    with ``{}`` the next time it is collected.
    """
    if persist_configuration:
        return node.configuration
    return {}


def node_envelope(
    node: ProjectedNode,
    dimensions: dict[str, str],
    tags: dict[str, str] | None = None,
    *,
    persist_configuration: bool,
) -> dict[str, Any]:
    """Build a GRIFT node envelope from a projected node.

    The ``node`` payload is the projected typed fields, the canonical
    ``tags`` map (``req-aws-collector-tags``; ``{}`` when untagged — the
    correct answer, never omitted), and ``configuration`` as decided by
    :func:`persisted_configuration`; the service layer validates it on import.

    ``persist_configuration`` is keyword-only and has no default: the caller
    passes the manifest entry's ``persist_configuration`` flag, so there is
    no path that emits a node without that decision having been made.
    """
    return {
        "entity": {
            "ref": node.ref,
            "entity_type": node.entity_type,
            "name": node.name,
            "dimensions": dimensions,
        },
        "node": {
            **node.fields,
            "tags": tags or {},
            "configuration": persisted_configuration(node, persist_configuration=persist_configuration),
        },
    }


def envelope_ref(envelope: Mapping[str, Any]) -> str:
    """The batch-local ref a node or edge envelope is sent under."""
    return str(envelope["entity"]["ref"])


@dataclass
class AddressedBatch:
    """The run's envelopes as they are sent, and what :func:`address_batch` did to get there."""

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    #: ``dropped ref -> kept ref`` for a node that repeated another node's identity under a
    #: different ref, so a completeness subject naming the dropped one still resolves.
    aliases: dict[str, str] = field(default_factory=dict)
    #: ``(code, message)`` for each envelope left out, for the run log.
    notices: list[tuple[str, str]] = field(default_factory=list)
    #: Edges sent with an explicit id because their type declares no identity.
    undeclared_edges: int = 0
    #: Endpoints named by type and natural key (resolved against the live grid by core).
    key_endpoints: int = 0


def node_key(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """The declared ``NATURAL_KEY`` values a node envelope carries, one per declared property.

    Read with core's own extraction (``constituting_properties``) from the payload the batch sends,
    so the collector and the importer agree on what the key is. The one place the collector reads
    a node's key: the identity :func:`address_batch` dedupes on and the anchor an authority claim
    names (:func:`node_anchor`) are both this value. A hole reads ``None``; it is not refused here.
    """
    from tap_grid.natural_key import constituting_properties

    return constituting_properties(declared_key(str(envelope["entity"]["entity_type"])), envelope["node"])


def node_anchor(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """A node envelope named by type and full natural key: ``{entity_type, key}``.

    The form tap resolves against the batch's nodes, then the live grid, for an authority claim's
    anchor (``GriftRemovalEndpoint``). Only for an envelope :func:`address_batch` accepted, so the
    key has no hole.
    """
    return {"entity_type": str(envelope["entity"]["entity_type"]), "key": node_key(envelope)}


def _node_identity(envelope: Mapping[str, Any]) -> tuple[str, str]:
    """``(entity_type, declared key values)`` of a node envelope, refusing a key with a hole.

    A hole (absent, null, or ``""``) is refused: core's search finds nothing on a null part, so
    such a node would be created afresh on every run. An AWS identifier is never legitimately
    empty, so ``""`` is refused here too.
    """
    entity_type = str(envelope["entity"]["entity_type"])
    values = node_key(envelope)
    holes = missing_parts(values)
    if holes:
        raise IdentityError(
            f"{entity_type} {envelope_ref(envelope)!r}: declared key part(s) {holes} of {list(values)} are "
            "absent or empty; such a node cannot be found again, so it is not sent"
        )
    return entity_type, json.dumps(values, sort_keys=True, default=str)


def address_batch(node_envelopes: list[dict[str, Any]], edge_envelopes: list[dict[str, Any]]) -> AddressedBatch:
    """Make the run's envelopes the batch core will accept, naming everything by identity.

    1. Every node's declared key is complete, or the run fails here (:class:`.identity.IdentityError`).
    2. One node per identity: core fails a batch whose two refs describe one source object
       (``duplicate_entity_id``), so a repeat is left out and its ref aliased to the kept one.
    3. Each endpoint the batch carries a node for stays a ``*_ref``; any other becomes a
       ``*_key`` naming the node by type and natural key, which core resolves against the live grid
       and never mints (``req-grid-import-grift-edge-endpoints``).
    4. One edge per identity (type, both endpoints, declared discriminators): core fails a batch
       naming one relationship twice (``duplicate_edge``).
    5. An edge whose type declares no identity is sent with its explicit ``uuid5`` id instead of a
       ref (:func:`.identity.undeclared_edge_id`), so it is replaced in place, not added again.

    Edge endpoint refs are taken as the edge pass wrote them; the refs a node pass wrote are the
    batch's. Mutates nothing it was given.
    """
    from tap_grid.edge_identity import edge_identity_values, get_edge_identity

    result = AddressedBatch(nodes=[], edges=[])
    by_identity: dict[tuple[str, str], str] = {}
    for envelope in node_envelopes:
        ref = envelope_ref(envelope)
        identity = _node_identity(envelope)
        kept = by_identity.get(identity)
        if kept is not None:
            if kept != ref:
                result.aliases[ref] = kept
            result.notices.append(
                ("DUPLICATE_IDENTITY", f"{identity[0]} {ref!r} repeats the identity of {kept!r}; the repeat is left out.")
            )
            continue
        by_identity[identity] = ref
        result.nodes.append(envelope)
    node_refs = set(by_identity.values())

    seen_edges: set[tuple[str, str, str, str]] = set()
    for envelope in edge_envelopes:
        payload = dict(envelope["edge"])
        edge_type = str(payload["edge_type"])
        ends: dict[str, str] = {}
        for side in ("from", "to"):
            ref = str(payload.pop(f"{side}_ref"))
            ends[side] = result.aliases.get(ref, ref)
        declaration = get_edge_identity(edge_type)
        values = edge_identity_values(declaration, payload.get("properties") or {}) if declaration else {}
        identity = (edge_type, ends["from"], ends["to"], json.dumps(values, sort_keys=True, default=str))
        if identity in seen_edges:
            continue
        seen_edges.add(identity)
        for side in ("from", "to"):
            if ends[side] in node_refs:
                payload[f"{side}_ref"] = ends[side]
            else:
                payload[f"{side}_key"] = endpoint_key(*split_node_ref(ends[side]))
                result.key_endpoints += 1
        entity = {k: v for k, v in envelope["entity"].items() if k not in ("ref", "entity_id")}
        if declaration is None:
            entity["entity_id"] = str(
                undeclared_edge_id(edge_type, split_node_ref(ends["from"])[1], split_node_ref(ends["to"])[1])
            )
            result.undeclared_edges += 1
        else:
            entity["ref"] = edge_ref(edge_type, ends["from"], ends["to"])
        result.edges.append({**envelope, "entity": entity, "edge": payload})
    return result


def withhold_retired_undeclared_edges(addressed: AddressedBatch) -> None:
    """Leave out an explicitly addressed edge whose id is already tombstoned on the grid.

    Only an edge whose type declares no identity is sent under a fixed id
    (:func:`.identity.undeclared_edge_id`). When either end of such an edge was deleted, core ended
    the edge too, and re-sending a tombstoned id fails the whole batch (``entity_tombstoned``): the
    aws-core-tap#14 wedge, for that one edge. The run leaves it out and says so instead. It cannot
    be written again under that id; it returns once its type declares an identity and is sent by
    ref (``ROUTES_TRAFFIC``: aws-core-tap#64). One read of the entity spine, by id.
    """
    from tap_grid.models import Entity

    fixed = [e["entity"]["entity_id"] for e in addressed.edges if "entity_id" in e["entity"]]
    if not fixed:
        return
    retired = {
        str(pk)
        for pk in Entity.objects.filter(pk__in=fixed, deleted_at__isnull=False).values_list("pk", flat=True)
    }
    if not retired:
        return
    kept = []
    for envelope in addressed.edges:
        if envelope["entity"].get("entity_id") not in retired:
            kept.append(envelope)
            continue
        addressed.undeclared_edges -= 1
        addressed.notices.append(
            (
                "UNDECLARED_EDGE_RETIRED",
                f"{envelope['edge']['edge_type']} {envelope['entity']['name']}: left out; its fixed id "
                f"{envelope['entity']['entity_id']} is tombstoned and the type declares no identity to find "
                "a live edge by, so it cannot be written again until it does.",
            )
        )
    addressed.edges = kept


def resolve_subject(subject: str, addressed: AddressedBatch, resolved_refs: Mapping[str, str]) -> str:
    """The grid id a completeness subject's ref resolved to in the imported batch.

    A subject is the ref of the parent the surface describes. When the batch carried that parent,
    the import result says which row it is (``resolved_refs``, the id core found or assigned). A
    parent the batch did not carry (a node the run withheld this time) keeps its ref, which is its
    source locator (``completeness.schema.json``: "the source locator or the grid entity id"):
    candidate derivation reads such a surface as unresolved and derives nothing from it, which is
    right, since the run did not observe that parent.
    """
    ref = addressed.aliases.get(subject, subject)
    return str(resolved_refs.get(ref, subject))


def assemble_batch(
    *,
    source: str,
    manifest_version: str,
    account_id: str | None,
    regions: list[str],
    node_envelopes: list[dict[str, Any]],
    edge_envelopes: list[dict[str, Any]],
    now: datetime | None = None,
    batch_entity_id: str | None = None,
    authority: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the single GRIFT document for one collection run.

    Args:
        source: The collector's dotted source identity.
        manifest_version: The resource manifest's ``manifest_version``.
        account_id: The collected AWS account id (``None`` if undetermined).
        regions: The regions swept this run.
        node_envelopes: Phase-one node envelopes (see :func:`node_envelope`).
        edge_envelopes: Phase-two edge envelopes (see :func:`.edges.emit_edges`).
        now: Collection timestamp; defaults to ``datetime.now(UTC)``.
        batch_entity_id: Override the per-run batch id (tests); defaults to a
            fresh ``uuid7``.
        authority: Edge-authority claims (``req-aws-collector-edge-authority``),
            carried as the batch's ``edge_cases.authority``. ``None`` or empty
            leaves the section out, which claims nothing.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    now_iso = moment.isoformat().replace("+00:00", "Z")
    label = f"AWS collection {now_iso}"

    by_entity_type = Counter(env["entity"]["entity_type"] for env in node_envelopes)
    description_data = {
        "schema_version": "v0",
        "manifest_version": manifest_version,
        "account_id": account_id,
        "regions": regions,
        "counts": {
            "nodes": len(node_envelopes),
            "edges": len(edge_envelopes),
            "by_entity_type": dict(sorted(by_entity_type.items())),
        },
    }

    batch = {
        "batch_entity": {
            "entity_id": batch_entity_id or str(uuid7()),
            "entity_type": "batch",
            "name": label,
            "dimensions": {},
        },
        "batch_node": {
            "source": source,
            "name": label,
            "description": "AWS account collection via tap_cares.",
            "description_json": {
                "format": COLLECTION_FORMAT,
                "data": description_data,
            },
        },
        "nodes": node_envelopes,
        "edges": edge_envelopes,
    }
    if authority:
        batch["edge_cases"] = {"authority": authority}
    return {
        "metadata": {"grift_version": _GRIFT_VERSION},
        "_reserved": {},
        "batches": [batch],
    }
