# validate

Live validation of the collector against a real account, in waves
(`specs/spec-aws-core-live-validation.md`). Nothing here is part of the plugin wheel.

## Wave 0: call-path smoke (`wave0_smoke.py`)

A read-only pass over every manifest-driven type, with the collector's own read-only identity. For each type and
region it drives the real engine path (`iter_source`, `project_item`, `resolve_node_tags`) and records the outcome,
the row count, the AWS calls made, the seconds taken and the error class. It builds no batch, writes nothing to the
grid and nothing to AWS; a guard (`readguard.py`, standard library only, unit-tested) refuses any operation whose name is not a read verb, any
read-named operation that returns credentials (`GetSecretValue`, `GetSessionToken`, `GetPasswordData` and the rest of
its list), and any request that asks the service to reveal a secret (`WithDecryption`, `includeValue`), and refuses `GetConnection(s)` unless `HidePassword` is true. The refused-operation list is a deny list of known credential-returning names, not a proof that no other read returns a secret: `test_readguard.py` checks every operation the manifest names against it, and the by-product operations below are the known exceptions. It is a botocore `before-parameter-build` handler (`readguard.install(session)`, tested against real botocore clients: a write, a credential-returning read and a revealing request are refused before anything is sent), and it must be installed before any client is built, because a client copies the session's handlers when it is created. It is registered on the session, so any client built from that session is covered (a client built from another session, or with `boto3.client`, would not be). It does not stop an operation the collector itself makes that returns a secret as a by-product of describing something else (`DescribeUserPoolClient`, `DescribeListeners`, `DescribeVerifiedAccessTrustProviders`, listed in `readguard.BY_PRODUCT_SECRETS`): the manifest drops those fields, so the smoke test holds them in memory as production does and never writes them. A zero-row result proves the
call path only (see the spec's three layers).

Run it inside the stack's web container, which holds the collector's secret:

```
scripts/dc exec -T web uv run python manage.py shell -c \
  "exec(open('/app/_dev-plugins/aws_core/tools/validate/wave0_smoke.py').read())"
```

`WAVE0_ONLY` takes comma-separated `fnmatch` patterns on the entity type, `WAVE0_LIMIT` the first N entries,
`WAVE0_OUT` a JSON path inside the container, `WAVE0_MESSAGES=1` records error messages for local debugging only. The result is printed between `WAVE0_JSON_BEGIN` and
`WAVE0_JSON_END`.

## Run records (`runs/`)

One file per run: counts, operation names and error codes only. An entry that made no AWS call (a parent-dependent type with no parent resources) is `not-exercised`, never `empty`: it is not evidence that its call path works. From the run after this change a result also carries `calls_made`, every `service.operation` the entry made, so a successful call can be audited; `wave0-2026-11-01.json` predates it and records operation names for failed calls only (`failed_calls`). Never resource content, never error messages (they can
name resources), and account numbers removed because this repository is public. A record is the merge of the first
pass and a re-run of the entries that did not come back clean (the re-run replaces the first result), so it is not
the raw output of one invocation of the script. The ledger decisions cite these files as the evidence for a type's
live state.

| File | What |
| --- | --- |
| `runs/wave0-2026-11-01.json` | Wave 0 over 898 manifest-driven types, `us-gov-west-1`, GovCloud staging account |

Not covered by wave 0: the hand-written readers (landing zone, Organizations, findings), which run only through the
full collector.
