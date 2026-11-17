"""Delete edges of the four edge types renamed in the edge-naming conformance wave.

`INVOKES` -> `INVOKES_LAMBDA`, `FEDERATES_INTO` -> `FEDERATES_INTO_ROLE`,
`ENCRYPTED_WITH` -> `ENCRYPTED_WITH_KEY`, `AUTHENTICATES_VIA` -> `AUTHENTICATES_VIA_USER_POOL`
(core's `req-tap-plugin-edge-naming`: a slug names a mechanical action on a destination noun).

Edge ids derive from the slug (`boto3_collector.identity.edge_entity_id`), so a renamed type is
a NEW edge on the next collection and the old rows would linger as unregistered types nothing
reads. This removes them (with their spine rows) so a grid upgraded in place is not left carrying
two generations of the same relation; the next collection repopulates the new types. Nodes are
untouched. Same shape as github_core's 0013_retire_renamed_edge_types (github-core#79).

Direct ORM access is the sanctioned path in migrations.
"""

from typing import Any

from django.db import migrations

_RETIRED_EDGE_TYPES = (
    "INVOKES__aws_core",
    "FEDERATES_INTO__aws_core",
    "ENCRYPTED_WITH__aws_core",
    "AUTHENTICATES_VIA__aws_core",
)


def delete_retired_edges(apps: Any, schema_editor: Any) -> None:
    Edge = apps.get_model("tap_grid", "Edge")
    Entity = apps.get_model("tap_grid", "Entity")
    edges = Edge.objects.filter(edge_type__in=_RETIRED_EDGE_TYPES)
    entity_ids = list(edges.values_list("entity_id", flat=True))
    edges.delete()
    Entity.objects.filter(pk__in=entity_ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aws_core", "0004_historicalsecretsmanagersecret_tags_and_more"),
        ("tap_grid", "0001_initial"),
    ]

    operations = [migrations.RunPython(delete_retired_edges, migrations.RunPython.noop)]
