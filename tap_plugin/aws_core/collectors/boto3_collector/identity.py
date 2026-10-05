"""How the boto3 collector names the nodes and edges it sends (``req-aws-collector-identity``).

Spec: ``specs/spec-aws-core-collector-v0.md``.

The collector never mints a grid id. A node is sent with a batch-local ``ref`` and its declared
natural-key fields; core's ``resolve_identity`` finds the live row those fields name, or assigns a
UUIDv7 on first sight (``req-grid-entity-natural-key``, ``req-grid-import-grift-identity-3``). An
edge is sent with a ``ref`` too and is found by its type's declared identity
(``req-grid-edge-identity``). An endpoint names a node of the same batch by ``from_ref`` /
``to_ref``, and any other node by type and natural key (``from_key`` / ``to_key``,
``req-grid-import-grift-edge-endpoints``), resolved against the live grid and never minted.

A ref is ``<entity_type>:<natural_key>`` for a node and ``edge:<edge_type>:<from ref>-><to ref>``
for an edge. It is only a name inside one batch; what it resolved to comes back on the import
result (``resolved_refs``), which is where a completeness subject learns its grid id.

The one exception is an edge type that declares no identity (``ROUTES_TRAFFIC``, deferred to
aws-core-tap#64). Core creates a ref-addressed edge of such a type without a lookup, so a ref would
add a new edge on every run. Those edges keep the explicit ``uuid5`` id they always had
(:func:`undeclared_edge_id`), until the type declares its identity.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

#: Frozen: the explicit id of an edge whose type declares no identity is derived under it, and
#: the rows written under it before natural-key refs must keep matching.
NAMESPACE_AWS_COLLECTOR: Final[uuid.UUID] = uuid.uuid5(uuid.NAMESPACE_DNS, "tap.aws_core.boto3_collector")

_EDGE_REF_PREFIX: Final[str] = "edge:"


class IdentityError(Exception):
    """A node or endpoint the collector cannot name completely.

    Raised instead of sending something core would mint afresh on every run: a node whose declared
    key has a hole is "not found" by core's search (``find_existing`` returns None on a null part),
    so it would be created again each run. Failing loudly is the only honest answer.
    """


def node_ref(entity_type: str, natural_key: str) -> str:
    """The batch-local ref of a node: ``<entity_type>:<natural_key>``."""
    return f"{entity_type}:{natural_key}"


def split_node_ref(ref: str) -> tuple[str, str]:
    """``(entity_type, natural_key)`` of a node ref. Entity types carry no colon; keys may."""
    entity_type, sep, natural_key = ref.partition(":")
    if not sep or not entity_type or not natural_key:
        raise IdentityError(f"{ref!r} is not a node ref (<entity_type>:<natural_key>)")
    return entity_type, natural_key


def edge_ref(edge_type: str, from_ref: str, to_ref: str) -> str:
    """The batch-local ref of an edge: its type and both endpoint refs."""
    return f"{_EDGE_REF_PREFIX}{edge_type}:{from_ref}->{to_ref}"


def undeclared_edge_id(edge_type: str, from_key: str, to_key: str) -> uuid.UUID:
    """The explicit id of an edge whose type declares no identity: ``uuid5(NS, "edge:<type>:<from>-><to>")``.

    The same derivation every edge used before natural-key refs, so such an edge already on a grid
    is replaced in place rather than duplicated.
    """
    return uuid.uuid5(NAMESPACE_AWS_COLLECTOR, f"edge:{edge_type}:{from_key}->{to_key}")


def declared_key(entity_type: str) -> tuple[str, ...]:
    """The type's declared ``NATURAL_KEY``; a keyless or undeclared type cannot be named by key."""
    from tap_grid.registry import get_model_class

    try:
        declared = getattr(get_model_class(entity_type), "NATURAL_KEY", None)
    except KeyError:
        raise IdentityError(f"{entity_type} is not a registered entity type") from None
    if not isinstance(declared, tuple) or not declared:
        raise IdentityError(f"{entity_type} declares no NATURAL_KEY, so the collector cannot name it by key")
    return declared


def missing_parts(key: dict[str, Any]) -> list[str]:
    """The parts of a key that cannot identify anything: absent, null or empty."""
    return [name for name, value in key.items() if value is None or value == ""]


def endpoint_key(entity_type: str, natural_key: str) -> dict[str, Any]:
    """An endpoint naming a node the batch does not carry: ``{entity_type, key}``.

    Only a type keyed on ONE field can be named from its natural-key string: a composite key
    (``(account_id, region_code)``, say) is joined into the string with separators its parts may
    contain, so it cannot be split back honestly. Such a node is always one the collector writes
    in the same batch as the edge and is named by ref; reaching here for one is a defect.
    """
    fields = declared_key(entity_type)
    if len(fields) != 1:
        raise IdentityError(
            f"{entity_type} is keyed on {list(fields)}; an edge to {natural_key!r} can only name it by ref, "
            "and this batch does not carry it"
        )
    key = {fields[0]: natural_key}
    if missing_parts(key):
        raise IdentityError(f"{entity_type}: an endpoint with an empty natural key cannot be named")
    return {"entity_type": entity_type, "key": key}
