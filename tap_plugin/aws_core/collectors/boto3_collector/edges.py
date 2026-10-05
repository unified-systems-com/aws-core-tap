"""Declarative edge emission for the boto3 collector (phase two).

Spec: plugins/aws_core/specs/spec-aws-core-collector-v0.md
(req-aws-collector-edges).

Nodes are emitted first, then edges in a separate pass. An endpoint is named by
node ref (:mod:`.identity`); when the batch is assembled, an endpoint naming a
node the batch does not carry is rewritten to its type and natural key, which
core resolves against the live grid and never mints. So the edge pass needs no
per-target lookup, and an edge to a target not collected this run resolves to
the row an earlier run wrote, or is skipped and recorded when there is none
(GRIFT's permissive dangling-edge mode, ``req-grid-import-grift-edge-endpoints``).

Each manifest edge rule declares ``value_path`` (a jsonpath into the item —
scalar or list; a list fans out one edge per element), ``target_type``,
``key_kind``, ``edge_type``, ``direction``, and an optional ``transform`` (a
*named, registered* callable mapping the raw value to the target's natural
key — never code from manifest data, mirroring ``req-aws-collector-source-3``).

This module is the **single chokepoint** for the v0-fence gap: an edge whose
``target_type`` is not a type this collector models is dropped with a
structured warning, never a run failure (``req-aws-collector-edges-6``). Edges
requiring policy-document parsing are out of v0 scope and are simply not
declared in the manifest (``req-aws-collector-edges-5``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .identity import edge_ref, node_ref, split_node_ref
from .paths import eval_path
from .projection import ProjectedNode


class EdgeError(Exception):
    """An edge rule named a transform that is not registered."""


# A transform maps a raw extracted value to the target's natural key. It may
# return a scalar or a list (further fan-out). Specific transforms are
# registered by the fan-out increment, not here.
Transform = Callable[..., Any]


class TransformRegistry:
    """Plugin-local registry of edge ``transform`` callables.

    The manifest names a transform; the engine resolves it here. Code is
    never imported from manifest data (mirrors ``req-aws-collector-source-3``).
    """

    def __init__(self) -> None:
        self._fns: dict[str, Transform] = {}
        self._source_aware: set[str] = set()

    def register(self, name: str, fn: Transform, *, source_aware: bool = False) -> None:
        """Register ``fn`` under ``name`` (last registration wins).

        A ``source_aware`` transform is also handed the SOURCE node's natural key
        (``fn(value, source_key=...)``): for a target whose identity carries the region and account
        the referring value does not (a Lambda names its log group by bare name; the log group is
        keyed by its ARN), the source's own ARN is where they come from.
        """
        self._fns[name] = fn
        if source_aware:
            self._source_aware.add(name)
        else:
            self._source_aware.discard(name)

    def is_source_aware(self, name: str) -> bool:
        """Whether ``name`` was registered ``source_aware``."""
        return name in self._source_aware

    def get(self, name: str) -> Transform:
        """Resolve a registered transform or raise ``EdgeError``."""
        try:
            return self._fns[name]
        except KeyError:
            known = ", ".join(sorted(self._fns)) or "<none>"
            raise EdgeError(f"edge transform {name!r} is not registered (known: {known})") from None


def edge_envelope(
    edge_type: str,
    *,
    from_ref: str,
    to_ref: str,
    dimensions: dict[str, str],
) -> dict[str, Any]:
    """One GRIFT edge envelope, addressed by ref with both endpoints named by node ref.

    The single place its shape is written, so the manifest-driven edges and the collector's own
    structural edges (footprint containment, the Organizations and landing-zone readers) cannot
    drift apart. Core finds the edge by its type's declared identity (``req-grid-edge-identity``);
    :func:`.batch.address_batch` rewrites an endpoint the batch carries no node for to a natural key.
    """
    from_key = split_node_ref(from_ref)[1]
    to_key = split_node_ref(to_ref)[1]
    return {
        "entity": {
            "ref": edge_ref(edge_type, from_ref, to_ref),
            "entity_type": "edge",
            "name": f"{from_key} {edge_type} {to_key}",
            "dimensions": dict(dimensions),
        },
        "edge": {
            "from_ref": from_ref,
            "to_ref": to_ref,
            "edge_type": edge_type,
            "properties": {},
        },
    }


@dataclass(frozen=True)
class EdgeEmission:
    """Result of the edge pass for one node: envelopes + drop warnings.

    ``warnings`` are structured drop messages the runtime feeds to
    ``record_warn`` — one per dropped rule, not per fanned-out value.
    """

    envelopes: list[dict[str, Any]]
    warnings: list[str]


def _as_value_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    return [v for v in values if v is not None and v != ""]


#: The entity type of the parent every ``containment`` listing hangs from.
ACCOUNT_ENTITY_TYPE = "aws_core__aws_account"


def account_ref(account_id: str) -> str:
    """The ref of the account node the run collected (``aws_account_singleton`` keys it on the id)."""
    return node_ref(ACCOUNT_ENTITY_TYPE, account_id)


def emit_containment(
    node: ProjectedNode,
    containment: dict[str, Any],
    *,
    account_id: str,
    dimensions: dict[str, str],
) -> dict[str, Any]:
    """The account -> item edge for one item of a ``containment`` listing.

    Emitted for every item the listing returned, from the account the credential resolved to (STS
    ``GetCallerIdentity``), never from anything on the item: an item's own account field could name a
    different account (a shared or cross-account reference), and this edge says only that THIS
    account's listing named THIS item. A re-run sends the same (type, account, item), which core
    finds as the same edge (``req-grid-edge-identity``) rather than adding a second.
    """
    return edge_envelope(
        containment["edge_type"], from_ref=account_ref(account_id), to_ref=node.ref, dimensions=dimensions
    )


def emit_edges(
    node: ProjectedNode,
    entry: dict[str, Any],
    *,
    modeled_types: set[str],
    transforms: TransformRegistry,
    dimensions: dict[str, str],
) -> EdgeEmission:
    """Emit GRIFT edge envelopes for one projected node.

    Args:
        node: The source node (its identity + ``ResponseMetadata``-free item).
        entry: The validated manifest entry the node came from.
        modeled_types: Entity types this collector models. An edge to a
            ``target_type`` outside this set is dropped with a warning.
        transforms: The plugin-local transform registry.
        dimensions: Dimensions stamped on every emitted edge entity.
    """
    envelopes: list[dict[str, Any]] = []
    warnings: list[str] = []

    for rule in entry.get("edges", []):
        target_type = rule["target_type"]
        if target_type not in modeled_types:
            warnings.append(
                f"{node.entity_type} {node.natural_key}: dropped "
                f"{rule['edge_type']} edge — target_type {target_type!r} is "
                f"not modeled by this collector (v0 fence)"
            )
            continue

        raw = eval_path(node.raw_item, rule["value_path"])
        transform_name = rule.get("transform")
        transform = transforms.get(transform_name) if transform_name else None
        source_aware = bool(transform_name) and transforms.is_source_aware(str(transform_name))

        for raw_value in _as_value_list(raw):
            # The transform maps each extracted value to the target's
            # natural key. It is applied per-element AFTER fan-out
            # expansion: a list value_path (e.g. Origins.Items[]) must feed
            # the transform one element at a time, never the whole list.
            # A transform may return None to mean "this value is not a
            # valid target of this edge" — drop it so no bogus edge is
            # fabricated (the transforms.py contract).
            if transform is None:
                value = raw_value
            elif source_aware:
                value = transform(raw_value, source_key=node.natural_key)
            else:
                value = transform(raw_value)
            if value is None:
                continue
            target_ref = node_ref(target_type, str(value))
            if rule["direction"] == "inbound":
                from_ref, to_ref = target_ref, node.ref
            else:  # outbound
                from_ref, to_ref = node.ref, target_ref

            envelopes.append(edge_envelope(rule["edge_type"], from_ref=from_ref, to_ref=to_ref, dimensions=dimensions))

    return EdgeEmission(envelopes=envelopes, warnings=warnings)
