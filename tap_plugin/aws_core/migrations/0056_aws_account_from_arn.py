"""Fill ``aws.account`` from each aws_core row's own ARN (George, 2026-11-13, aws-build Q62).

``0055`` dropped every old ``aws_account`` value (Q60a), because it named the account that OBSERVED a resource, and
``aws.account`` now means the account that OWNS it (Q57). For a row our collector collects, the next run stamps the
owner again. A row nothing re-collects keeps no owner: an ECS node that only Anchore created (in an account or region
this collector does not cover) is never rewritten, because Anchore creates only what is absent. Its falsifiers would
answer ``scope_unknown`` forever.

Most aws_core types are keyed by their ARN, and an ARN carries its owner: ``arn:<partition>:<service>:<region>:
<account>:<resource>``. This fills ``aws.account`` from that account field: a 12-digit id, or ``aws`` for a resource
AWS itself owns (an AWS-managed policy). That is the same first source the collector uses for the owner
(``containment.resource_owner``), so the value matches what the next collection would stamp.

Why it reads the spine ``natural_key``: since tap PR #1179 (tap v0.3.4) ``tap_entity.natural_key`` holds a
single-field natural key verbatim, which for an ARN-keyed type IS the ARN. tap_grid ``0010`` backfills it for every
existing row, so this depends on it, and aws_core's ``requires_tap`` floor is 0.3.4.

What it leaves alone: a row that already carries ``aws.account``, which is never overwritten; a row whose natural key
is not a well-formed ARN, or is a multi-field key (joined with ``|``); and an ARN with no account field (S3 buckets, Route 53 and
the like), whose owner only the collector can supply. Edge rows carry no ARN natural key, so they are not touched.
It works on today's name-keyed dimensions map, as ``0055`` does, in chunks. A second run changes nothing, because
every row it fills then carries the key. Each chunk commits on its own (``atomic = False``), and the predicates
are rechecked on the row being updated, so a value written concurrently is never overwritten. Reversing is a no-op.
"""

from django.db import migrations

NODE_PREFIX = "aws_core__"
KEY = "aws.account"
CHUNK = 5000

# A whole ARN, not just an "arn:" prefix: a non-empty partition and service, any region (global services leave it
# empty), a 12-digit account and a non-empty resource. The account "aws" is accepted only where AWS really owns the
# resource, an AWS-managed IAM policy (arn:<partition>:iam::aws:...): no other service's ARN carries it, so anywhere
# else it is malformed. A malformed key is left alone, so its row stays fail-closed (scope_unknown) rather than gaining
# an owner from a field that only looks like one.
ARN_WITH_ACCOUNT = r"^arn:[a-z0-9-]+:([a-z0-9-]+:[^:]*:[0-9]{12}|iam::aws):.+$"

# Constant statements; every value is a bound parameter. split_part(natural_key, ':', 5) is the ARN's account field.
CANDIDATES = """
SELECT id FROM tap_entity
 WHERE starts_with(entity_type, %(prefix)s)
   AND NOT (dimensions ? %(key)s)
   AND strpos(natural_key, '|') = 0
   AND natural_key ~ %(arn)s
   AND id > %(after)s
 ORDER BY id
 LIMIT %(chunk)s
"""

# Every predicate is repeated on the row being updated: PostgreSQL re-evaluates an UPDATE's WHERE against the latest
# row version after waiting on a concurrent writer's lock, so a value a collector wrote after the id snapshot is
# never overwritten.
FILL = """
UPDATE tap_entity AS e
   SET dimensions = e.dimensions || jsonb_build_object(%(key)s, split_part(e.natural_key, ':', 5))
 WHERE e.id = ANY(%(ids)s)
   AND starts_with(e.entity_type, %(prefix)s)
   AND NOT (e.dimensions ? %(key)s)
   AND strpos(e.natural_key, '|') = 0
   AND e.natural_key ~ %(arn)s
"""


def fill_account_from_arn(apps, schema_editor):
    """Keyset-paged by id, so the pass ends only when no candidate is left, never early because a chunk's rows were
    all written concurrently in the meantime."""
    params = {"key": KEY, "prefix": NODE_PREFIX, "chunk": CHUNK, "arn": ARN_WITH_ACCOUNT}
    after = "00000000-0000-0000-0000-000000000000"
    with schema_editor.connection.cursor() as cursor:
        while True:
            cursor.execute(CANDIDATES, {**params, "after": after})
            ids = [row[0] for row in cursor.fetchall()]
            if not ids:
                break
            cursor.execute(FILL, {**params, "ids": ids})
            after = ids[-1]


class Migration(migrations.Migration):
    # Not one transaction around every chunk: each chunk's UPDATE commits on its own, so a large grid is not held in
    # one long transaction on tap_entity (tap_grid 0010 does the same). An interrupted run is safe to repeat, since a
    # filled row no longer matches.
    atomic = False

    dependencies = [
        ("aws_core", "0055_rename_aws_dimensions"),
        # The spine natural key must be populated first (tap PR #1179's backfill).
        ("tap_grid", "0010_entity_natural_key_backfill"),
    ]

    operations = [
        migrations.RunPython(fill_account_from_arn, migrations.RunPython.noop),
    ]
