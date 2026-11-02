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
| `decisions.json` | Human verdicts the code cannot show (does retiring this type need to retire others), with a status and the basis for each. Add an entry when a service is worked and delete none without saying why in the commit. It holds proposed verdicts for the top services, all `proposed-unverified` until a live trial shows the behaviour; each carries its basis. A type with no entry reads as `undecided`. |
| `config-aliases.json` | Ledger type names that Config files under another name (`AWS::CertificateManager::Certificate` is Config's `AWS::ACM::Certificate`), so a supported type is not reported unsupported. |
| `config-resource-types.json` | Config's `ResourceType` enum from botocore, with the version. |
| `extended-read-actions.json` | Read actions the collector's role (SecurityAudit plus ReadOnlyAccess) is denied, in four sections: the 19 collection gaps (list/describe calls the manifest makes), which are **known misses** (aws-core-tap#172) left out on purpose because the collector ships on SecurityAudit alone; two opt-in sections (6 Bedrock `Get` probe reads, which return the object's content, and `glue:GetConnections`, which can return secrets); and denials a role allow cannot fix. Each section says why it is there. The default policy `role_gap.py` prints is therefore empty; `--include-known-misses` and `--include-opt-in` print the policy a policy owner would need if they chose to grant them. `--check` fails when an action is not a read verb, has a credential-suggesting name (a heuristic on the name, not IAM's own metadata), is listed twice, or a collection-gap action is no longer called by a manifest entry under the matching service. The collection-gap action names are derived from the manifest (wave 0 recorded no action), so they are worth confirming against a real denial message. It applies nothing; whether an allow clears a denial is untried (see `provenance.not_established`). |

**What the columns do not say.** `config_supported` is the commercial-partition list; neither botocore nor
any API states which types a GovCloud recorder supports. A service weight is only as good as the weighting,
which is a first judgement. `cascade_parent_of` shows only containment the plugin already declares; a type
that should have children but declares none reads as `undecided` until `decisions.json` says otherwise.
