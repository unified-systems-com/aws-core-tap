# validate

Live validation of the collector against a real account, in waves
(`specs/spec-aws-core-live-validation.md`). Nothing here is part of the plugin wheel.

## Wave 0: call-path smoke (`wave0_smoke.py`)

A read-only pass over every manifest-driven type, with the collector's own read-only identity. For each type and
region it drives the real engine path (`iter_source`, `project_item`, `resolve_node_tags`) and records the outcome,
the row count, the AWS calls made, the seconds taken and the error class. It builds no batch, writes nothing to the
grid and nothing to AWS; a guard refuses any operation whose name is not a read verb. A zero-row result proves the
call path only (see the spec's three layers).

Run it inside the stack's web container, which holds the collector's secret:

```
scripts/dc exec -T web uv run python manage.py shell -c \
  "exec(open('/app/_dev-plugins/aws_core/tools/validate/wave0_smoke.py').read())"
```

`WAVE0_ONLY` takes comma-separated `fnmatch` patterns on the entity type, `WAVE0_LIMIT` the first N entries,
`WAVE0_OUT` a JSON path inside the container. The result is printed between `WAVE0_JSON_BEGIN` and
`WAVE0_JSON_END`.

## Run records (`runs/`)

One file per run: counts, operation names and error codes only, never resource content, with account numbers
removed because this repository is public. The ledger decisions cite these files as the evidence for a type's
live state.

| File | What |
| --- | --- |
| `runs/wave0-2026-11-01.json` | Wave 0 over 898 manifest-driven types, `us-gov-west-1`, GovCloud staging account |

Not covered by wave 0: the hand-written readers (landing zone, Organizations, findings), which run only through the
full collector.
