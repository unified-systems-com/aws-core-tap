# coverage hit list

Ranks AWS services by weight and tracks, for each weighted type, what stands between "collected" and
"retirable": a completeness surface (a containment edge), a falsifier (a probe for "is it really gone"),
both together (reconcilable), whether it is a parent whose children a retirement should take with it, and
whether AWS Config supports the type (a possible second source of deletion evidence).

```
python3 -I tools/coverage/hit_list.py            # rewrite hit-list.json
python3 -I tools/coverage/hit_list.py --check    # exit 1 if it is stale
```

Reads the plugin as data (models by AST, edges, `tap-plugin.toml`, the ledger) and a weighting from
`tools/crosscheck/weights/` (default `fedramp-additions-v1`, status draft). Imports nothing of the plugin,
calls no AWS API. `tests/test_hit_list.py` regenerates the file and compares, so a change that moves a
count without a regeneration fails.

| File | What it is |
| --- | --- |
| `hit-list.json` | Generated. Per service: weight, types, collected, with falsifier, reconcilable, cascade parents, Config-supported; then one row per type. |
| `decisions.json` | Human verdicts the code cannot show (does retiring this type need to retire others; what probe is planned). Empty until a service is worked. |
| `config-resource-types.json` | Config's `ResourceType` enum from botocore, with the version. |

**What the columns do not say.** `config_supported` is the commercial-partition list; neither botocore nor
any API states which types a GovCloud recorder supports. A service weight is only as good as the weighting,
which is a first judgement. `cascade_parent_of` shows only containment the plugin already declares; a type
that should have children but declares none reads as `undecided` until `decisions.json` says otherwise.
