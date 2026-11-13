"""Rename aws_core's dimension keys on its existing rows (George, 2026-11-12, aws-build Q55a, Q56, Q60a).

- ``tap.cloud`` becomes ``tap.computing.cloud``. computing_core owns the cloud dimension and keeps the same Dimension
  node id, so this is a rename of the key, not a new dimension.
- ``cloud`` is dropped. It carried ``"aws"``, the same fact, and is retired.
- ``aws_region`` becomes ``aws.region``, the same node renamed.
- ``aws_account`` is dropped, not renamed (Q60a). Its values name the account that observed a resource, and
  ``aws.account`` now means the account that owns it (Q57). Until the next collection stamps the owner, a row has no
  ``aws.account``, and the falsifiers answer ``scope_unknown`` for it, which is fail-closed.

Why this touches the spine table: dimensions live on ``tap_entity.dimensions``, not on aws_core's typed tables. Each
statement is limited to aws_core's own rows (node rows whose ``entity_type`` starts ``aws_core__``, and edge rows,
whose spine ``entity_type`` is ``edge``, whose ``tap_edge.edge_type`` ends ``__aws_core``) and to rows that carry the
old key. It moves only that key's value and leaves every other dimension as it was. A row that already carries the new
key keeps that value. Run twice, it changes nothing the second time. It runs on today's name-keyed map, before
core's dimension-map reshape (tap#711).

No value is re-derived here. The next collection stamps ``aws.account`` with the owner. Reversing is a no-op.
"""

from django.db import migrations

#: aws_core's own node types share this prefix; its edge types end in this suffix (the edge's spine row is
#: entity_type "edge", so edges are found through tap_edge).
NODE_PREFIX = "aws_core__"
EDGE_SUFFIX = "__aws_core"

RENAMES = (("tap.cloud", "tap.computing.cloud"), ("aws_region", "aws.region"))
# aws_account is dropped, not renamed (George 2026-11-12, aws-build Q60a): its values name the OBSERVING account,
# and aws.account means the owner. Carried over, a RAM-shared row would name the receiving account as its owner and
# pass that credential's falsifier scope check until re-collected. Dropped, the row has no aws.account, so every
# falsifier answers scope_unknown until the next collection stamps the owner.
DROPPED = ("cloud", "aws_account")

# Constant statements; every value is a bound parameter.
RENAME = """
UPDATE tap_entity AS e
   SET dimensions = (e.dimensions - %(old)s)
       || CASE WHEN e.dimensions ? %(new)s THEN '{}'::jsonb ELSE jsonb_build_object(%(new)s, e.dimensions -> %(old)s) END
 WHERE e.dimensions ? %(old)s
   AND (
        starts_with(e.entity_type, %(prefix)s)
     OR (e.entity_type = 'edge'
         AND EXISTS (SELECT 1 FROM tap_edge AS g
                      WHERE g.entity_id = e.id AND right(g.edge_type, %(suffix_len)s) = %(suffix)s))
   )
"""

DROP = """
UPDATE tap_entity AS e
   SET dimensions = e.dimensions - %(old)s
 WHERE e.dimensions ? %(old)s
   AND (
        starts_with(e.entity_type, %(prefix)s)
     OR (e.entity_type = 'edge'
         AND EXISTS (SELECT 1 FROM tap_edge AS g
                      WHERE g.entity_id = e.id AND right(g.edge_type, %(suffix_len)s) = %(suffix)s))
   )
"""


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
