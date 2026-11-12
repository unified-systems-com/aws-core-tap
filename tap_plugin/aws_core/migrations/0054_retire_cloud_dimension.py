"""Remove the retired ``cloud`` dimension from aws_core's own rows (George, 2026-11-12, aws-build Q55a).

The collector used to stamp ``{"cloud": "aws"}`` on every node and edge it wrote, beside ``aws_account`` and
``aws_region``. That carried the same fact as ``tap.cloud``, which every aws_core model and edge type declares as a
default dimension, so the key is retired: the collector no longer writes it, and this migration drops it from the
rows that already carry it.

Why this touches the spine table: dimensions live on ``tap_entity.dimensions``, not on aws_core's typed tables, so
the key can only be removed there. The statement is limited to aws_core's own rows (``entity_type`` starting
``aws_core__``) and to rows that carry the key, and it removes only that key, so it is idempotent and leaves every
other dimension as it was. Run on today's name-keyed map, before core's dimension-map reshape (tap#711).

Not reversible in any useful sense: the value was always ``"aws"`` and nothing reads it, so reversing is a no-op.
"""

from django.db import migrations

DROP_CLOUD = """
UPDATE tap_entity
   SET dimensions = dimensions - 'cloud'
 WHERE starts_with(entity_type, %s)
   AND dimensions ? 'cloud'
"""


def drop_cloud(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(DROP_CLOUD, ["aws_core__"])


class Migration(migrations.Migration):
    dependencies = [
        ("aws_core", "0053_region_unique_natural_keys"),
    ]

    operations = [
        migrations.RunPython(drop_cloud, migrations.RunPython.noop),
    ]
