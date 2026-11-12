"""Remove the retired ``cloud`` dimension from aws_core's own rows (George, 2026-11-12, aws-build Q55a).

The collector used to stamp ``{"cloud": "aws"}`` on every node and edge it wrote, beside ``aws_account`` and
``aws_region``. That carried the same fact as ``tap.cloud``, which every aws_core model and edge type declares as a
default dimension, so the key is retired: the collector no longer writes it, and this migration drops it from the
rows that already carry it.

Why this touches the spine table: dimensions live on ``tap_entity.dimensions``, not on aws_core's typed tables, so
the key can only be removed there. The statement is limited to aws_core's own rows (node rows whose
``entity_type`` starts ``aws_core__``, and edge rows, whose spine ``entity_type`` is ``edge``, whose
``tap_edge.edge_type`` ends ``__aws_core``) and to rows that carry the key, and it removes only that key, so it is idempotent and leaves every
other dimension as it was. Run on today's name-keyed map, before core's dimension-map reshape (tap#711).

Not reversible in any useful sense: the value was always ``"aws"`` and nothing reads it, so reversing is a no-op.
"""

from django.db import migrations

DROP_CLOUD = """
UPDATE tap_entity AS e
   SET dimensions = e.dimensions - 'cloud'
 WHERE e.dimensions ? 'cloud'
   AND (
        starts_with(e.entity_type, %s)
     OR (e.entity_type = 'edge'
         AND EXISTS (SELECT 1 FROM tap_edge AS g WHERE g.entity_id = e.id AND right(g.edge_type, %s) = %s))
   )
"""

#: aws_core's own node types share this prefix; its edge types end in this suffix (the edge's spine row is
#: entity_type "edge", so edges are found through tap_edge).
NODE_PREFIX = "aws_core__"
EDGE_SUFFIX = "__aws_core"


def drop_cloud(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(DROP_CLOUD, [NODE_PREFIX, len(EDGE_SUFFIX), EDGE_SUFFIX])


class Migration(migrations.Migration):
    dependencies = [
        ("aws_core", "0053_region_unique_natural_keys"),
    ]

    operations = [
        migrations.RunPython(drop_cloud, migrations.RunPython.noop),
    ]
