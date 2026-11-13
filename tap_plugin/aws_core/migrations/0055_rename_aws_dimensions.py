"""Rename aws_core's dimension keys on its existing rows (George, 2026-11-12, aws-build Q55a, Q56).

- ``tap.cloud`` becomes ``tap.computing.cloud``. computing_core owns the cloud dimension and keeps the same Dimension
  node id, so this is a rename of the key, not a new dimension.
- ``cloud`` is dropped. It carried ``"aws"``, the same fact, and is retired.
- ``aws_account`` becomes ``aws.account`` and ``aws_region`` becomes ``aws.region``, the same nodes renamed.

Why this touches the spine table: dimensions live on ``tap_entity.dimensions``, not on aws_core's typed tables. Each
statement is limited to aws_core's own rows (node rows whose ``entity_type`` starts ``aws_core__``, and edge rows,
whose spine ``entity_type`` is ``edge``, whose ``tap_edge.edge_type`` ends ``__aws_core``) and to rows that carry the
old key. It moves only that key's value and leaves every other dimension as it was. A row that already carries the new
key keeps that value. Run twice, it changes nothing the second time. It runs on today's name-keyed map, before
core's dimension-map reshape (tap#711).

The values themselves are not rewritten: ``aws.account`` now means the owning account (Q57), and the next collection
re-stamps it. Reversing is a no-op.
"""

from django.db import migrations

#: aws_core's own node types share this prefix; its edge types end in this suffix (the edge's spine row is
#: entity_type "edge", so edges are found through tap_edge).
NODE_PREFIX = "aws_core__"
EDGE_SUFFIX = "__aws_core"

RENAMES = (("tap.cloud", "tap.computing.cloud"), ("aws_account", "aws.account"), ("aws_region", "aws.region"))
DROPPED = ("cloud",)

_SCOPE = """
   AND (
        starts_with(e.entity_type, %(prefix)s)
     OR (e.entity_type = 'edge'
         AND EXISTS (SELECT 1 FROM tap_edge AS g
                      WHERE g.entity_id = e.id AND right(g.edge_type, %(suffix_len)s) = %(suffix)s))
   )
"""

RENAME = (
    """
UPDATE tap_entity AS e
   SET dimensions = (e.dimensions - %(old)s)
       || CASE WHEN e.dimensions ? %(new)s THEN '{}'::jsonb ELSE jsonb_build_object(%(new)s, e.dimensions -> %(old)s) END
 WHERE e.dimensions ? %(old)s
"""
    + _SCOPE
)

DROP = (
    """
UPDATE tap_entity AS e
   SET dimensions = e.dimensions - %(old)s
 WHERE e.dimensions ? %(old)s
"""
    + _SCOPE
)


def rename_dimensions(apps, schema_editor):
    scope = {"prefix": NODE_PREFIX, "suffix_len": len(EDGE_SUFFIX), "suffix": EDGE_SUFFIX}
    with schema_editor.connection.cursor() as cursor:
        for old, new in RENAMES:
            cursor.execute(RENAME, {**scope, "old": old, "new": new})
        for old in DROPPED:
            cursor.execute(DROP, {**scope, "old": old})


class Migration(migrations.Migration):
    dependencies = [
        ("aws_core", "0054_lb_listener_rule_nodes"),
    ]

    operations = [
        migrations.RunPython(rename_dimensions, migrations.RunPython.noop),
    ]
