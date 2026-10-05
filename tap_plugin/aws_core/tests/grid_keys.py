"""Find what a collection run wrote by natural key, as the collector names it (req-aws-collector-identity).

The collector mints no ids: core assigns a node's id on first sight and finds it by its declared
natural key after that. A test therefore finds a row the way core does, by type and key, never
by recomputing an id.
"""

from __future__ import annotations

import uuid
from typing import Any

from tap_grid.models import Edge
from tap_grid.registry import get_model_class


def node_id(entity_type: str, key: str | dict[str, Any]) -> uuid.UUID:
    """The live row's id for a type and natural key (a string for a one-field key, else a dict)."""
    model = get_model_class(entity_type)
    declared = tuple(model.NATURAL_KEY)
    values = key if isinstance(key, dict) else {declared[0]: key}
    assert set(values) == set(declared), (entity_type, declared, values)
    row = model.find_existing(**values)
    assert row is not None, f"no live {entity_type} with {values}"
    return row.entity_id


def find_node_id(entity_type: str, key: str | dict[str, Any]) -> uuid.UUID | None:
    """As :func:`node_id`, or None when no live row has that key."""
    model = get_model_class(entity_type)
    declared = tuple(model.NATURAL_KEY)
    values = key if isinstance(key, dict) else {declared[0]: key}
    row = model.find_existing(**values)
    return None if row is None else row.entity_id


def live_edges(edge_type: str, from_id: Any, to_id: Any) -> list[Edge]:
    """Every live edge of ``edge_type`` between two node ids."""
    return list(
        Edge.objects.filter(
            edge_type=edge_type, from_entity_id=from_id, to_entity_id=to_id, entity__deleted_at__isnull=True
        )
    )


def edge_between(
    edge_type: str, from_type: str, from_key: str | dict[str, Any], to_type: str, to_key: str | dict[str, Any]
) -> Edge:
    """The one live edge of ``edge_type`` from one keyed node to another."""
    edges = live_edges(edge_type, node_id(from_type, from_key), node_id(to_type, to_key))
    assert len(edges) == 1, (edge_type, from_key, to_key, len(edges))
    return edges[0]


def has_edge(
    edge_type: str, from_type: str, from_key: str | dict[str, Any], to_type: str, to_key: str | dict[str, Any]
) -> bool:
    """Whether a live edge of ``edge_type`` joins two keyed nodes (either may be absent)."""
    source, target = find_node_id(from_type, from_key), find_node_id(to_type, to_key)
    if source is None or target is None:
        return False
    return bool(live_edges(edge_type, source, target))
