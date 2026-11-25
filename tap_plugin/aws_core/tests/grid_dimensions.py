"""Write and read a row's dimensions by name, through core's dimension map (tap 0.4.0, unified-systems-com/tap#711).

Core stores ``Entity.dimensions`` keyed by Dimension node id, each value ``{"v": value, "src": provenance}``,
and refuses a name-keyed map written straight to the ORM. Tests speak names, as the collector does: a
fixture stamps a row through :func:`stamp_dimensions` (core's ``dimension_map.supplied``) and an assertion
reads it back through :func:`dimensions_of` (core's ``dimension_names.view``).

A migration that ran before core's flip (tap_grid 0012) read and wrote the name-keyed map. Its test seeds
that shape with :func:`store_pre_flip`, raw SQL past the ORM's shape check, as an upgraded grid held it.
"""

from __future__ import annotations

import json
from typing import Any

from tap_grid.dimension_map import supplied
from tap_grid.dimension_names import view


def stamp_dimensions(row: Any, dimensions: dict[str, str]) -> None:
    """Replace a row's dimensions with ``dimensions`` (``{name: value}``) and save, as a collector run
    would leave them. ``row`` is a typed grid row (its ``entity`` is stamped) or an ``Entity``."""
    entity = getattr(row, "entity", row)
    entity.dimensions = supplied(dimensions)
    entity.save(update_fields=["dimensions"])


def store_pre_flip(entity_id: Any, dimensions: dict[str, Any]) -> None:
    """Store ``dimensions`` on a row exactly as given: the name-keyed, plain-value map rows carried before
    core's flip (tap_grid 0012). For migration tests only; nothing on a 0.4.0 core writes this shape."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("UPDATE tap_entity SET dimensions = %s::jsonb WHERE id = %s", [json.dumps(dimensions), str(entity_id)])


def dimensions_of(row: Any) -> dict[str, Any]:
    """A row's dimensions as ``{name: value}``. ``row`` is a typed grid row, an ``Entity``, or a stored map."""
    stored = row if isinstance(row, dict) else getattr(getattr(row, "entity", row), "dimensions", None)
    return view(stored)

