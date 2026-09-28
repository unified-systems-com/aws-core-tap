# TAP AWS Core Plugin

`aws_core` owns the TAP vocabulary for AWS resources and relationships, and the
collector that populates it from a running AWS account:

- **59 TAP-managed AWS resource models** (`tap_plugin/aws_core/models/`)
- **29 AWS edge types** (`tap_plugin/aws_core/edges/`)
- **Reference GRIFT data** for regions and availability zones (`tap_plugin/aws_core/grift/`)
- **The boto3 collector** — a manifest-driven engine that collects a single AWS
  account into the grid (`tap_plugin/aws_core/collectors/boto3_collector/`)
- **Specs** that are authoritative for all of the above (`specs/`)
- **Skills** for catalog refresh and icon sourcing (`skills/`)

Identity (enforced by the conformance gate): slug `aws_core` == dist
`tap-plugin-aws-core` == namespace `tap_plugin.aws_core` == entry-point key.
The version is derived from git tags via hatch-vcs; the plugin's Tier-0 `boto3`
dependency travels with the package. `tap_cares` (in TAP core) owns the
collector runtime, run records, secret mechanics, and the GRIFT import
boundary; everything AWS-specific lives here.

> **⚠️ The collector is additive-only.** Deletion/reaping has not been built:
> a run only creates and upserts. A resource deleted in AWS **stays on the
> grid** — absence from a run never deletes or tombstones a node or edge, so
> the grid reflects everything ever observed, not the account's current state.
> Supporting deletion is the first roadmap item below.

## The collector

The collector is **built and registered**: `apps.py` registers key `boto3`
(scope `aws_core`) with the `tap_cares` collector registry, backed by exactly
one `CollectorBase` subclass for all of AWS. There are deliberately **no
per-service classes** — that is a load-bearing invariant
(`req-aws-collector-runtime-7`), not a style choice. All per-resource knowledge
lives in a JSON resource manifest
(`collectors/boto3_collector/aws_resource_manifest.json`), schema-validated at
load; the engine contains no per-resource-type branching.

The pipeline per run: resolve credentials → load + validate the manifest → for
each entry, per region, drive the source → project declared fields via jsonpath
(the full AWS payload is always retained verbatim in `configuration`) → decorate
tags → emit nodes, then edges → submit **one GRIFT batch** → write a run
summary. Supporting behavior:

- **Sources** are either a bare `aws_op` (botocore paginator when available) or
  a registered `custom_fn` — thin per-service glue for resources AWS cannot
  enumerate richly in one call. Custom fns compose the write-once
  `hydrate_item` fan-out template; multi-call complexity is quarantined there,
  never in the engine.
- **Hydrate** records per-sub-call status (`ok` / `absent` / `denied` /
  `error`) and never conflates "no policy" with "could not read the policy" —
  opposite compliance conclusions.
- **Tags** ride a Resource Groups Tagging API sweep by default (one paginated
  call per region, scoped by the manifest's `resource_type_filter` set), with a
  per-service side-quest shape for services RGTA handles poorly. RGTA
  decorates; it never drives discovery.
- **Audit ledger**: every AWS call's request id + outcome + AWS-side timestamp
  is captured at the botocore boundary and drained into
  `CollectionJob.results`, so a run can be correlated against the account's own
  CloudTrail.
- **Resilience**: a per-(entry, region) failure — missing permission, service
  absent in a region — is classified, recorded as a structured warn, and
  skipped; only unrecoverable conditions (bad secret, no region scope,
  unreachable STS) fail the run.
- **Identity** is deterministic (`uuid5` over type + natural key), so re-runs
  upsert. **Additive-only** (see the warning above): no deletion, reaping, or
  implied-absence semantics exist yet (v0 non-goal).

### Credentials

The collector never reads credential files; credentials resolve through the
`tap_cares` secrets subsystem at the well-known ref `aws_core/boto_collector`
(the operator drops `aws_core/boto_collector.secret.json` under
`TAP_SECRETS_ROOT`). Two kinds are supported (shapes owned by this plugin —
`specs/spec-aws-core-secrets.md`):

- `aws_static_access_key` — static keys for an account we own.
- `aws_assumed_role` — cross-account: a base session calls STS `AssumeRole`
  with a **mandatory External ID**; short-lived credentials back the working
  session. `collectors/boto3_collector/handoff/` holds the operator handoff
  (CloudFormation + Terraform templates for the partner's read-only role, plus
  the collector-principal policy for our side).

Both kinds carry operator-owned region scoping (`data.regions_allowed` /
`data.region`) and the optional `data.expected_account_id` assert-on-land — if
set, the `GetCallerIdentity` account must match or the run fails visibly,
catching the "collected a real but wrong account" failure mode.

## Service coverage — honest inventory

Three tiers, from most to least covered. A model without a manifest entry
renders fine on the grid if data arrives some other way (GRIFT import), but the
collector will not populate it.

### Collected by the boto3 collector (17 manifest entries)

| AWS service | Resource type(s) | Edges emitted |
| --- | --- | --- |
| STS | account (synthesized node — no AWS API enumerates "the account") | — |
| Lambda | functions | ASSUMES_ROLE, WRITES_LOGS |
| IAM | roles | FEDERATES_INTO_ROLE |
| IAM | OIDC providers | — |
| EventBridge | rules (with targets) | ASSUMES_ROLE, INVOKES_LAMBDA |
| CloudWatch Logs | log groups | ENCRYPTED_WITH_KEY |
| ACM | certificates | — |
| CloudFront | distributions (with origin access control) | RETRIEVES_CONTENT_FROM, RETRIEVES_CERT_FROM |
| S3 | buckets (hydrated: per-bucket `GetBucket*` fan-out + size metrics) | ENCRYPTED_WITH_KEY |
| Route 53 | hosted zones (with alias targets) | ROUTES_TRAFFIC |
| DynamoDB | tables (described) | — |
| API Gateway v2 | HTTP APIs (stages/routes/integrations/authorizers resolved) | INVOKES_LAMBDA, AUTHENTICATES_VIA_USER_POOL |
| Cognito | user pools (described) | — |
| KMS | keys (described; aliases + tags joined) | — (the ENCRYPTED_WITH_KEY target) |
| SQS | queues (attributes + tags) | ENCRYPTED_WITH_KEY |
| CloudTrail | trails (home-region only; status + tags) | WRITES_LOGS, ENCRYPTED_WITH_KEY |
| Secrets Manager | secrets (**metadata only** — never `GetSecretValue`) | ENCRYPTED_WITH_KEY |

Tags for these ride the RGTA sweep or per-service tag calls. The original
eleven are the demo-driven v0 fence (`req-aws-collector-scope-2`); the last
six track the upstream samaydlette.com deployment's growth (Silk Reeling
app + audit/encryption hardening) so the reference target stays fully
collectible.

### Seeded from reference GRIFT (not collected)

Regions and availability zones ship as GRIFT seed data
(`grift/regions.grift.json`), kept current by the `refresh-aws-catalog` skill
rather than by the collector.

### Modeled, but NOT collected (40 models)

These have first-class TAP models and icons but **no manifest entry** — the
collector does not populate them today:

- **Compute**: EC2 instances, EBS volumes
- **Containers**: ECS clusters / services / tasks, EKS clusters, ECR repositories
- **Networking**: VPCs, subnets, security groups, network ACLs, internet
  gateways, NAT gateways, Elastic IPs, route tables, ALBs, classic ELBs,
  target groups, Network Firewalls, transit gateways and their attachments,
  Direct Connect connections / gateways / virtual interfaces, VPC endpoints and
  endpoint services, Route 53 Resolver DNS Firewall rule groups
- **Organization**: the organization (which also stands for its root),
  organizational units, service control policies
- **Data**: RDS instances, Elasticsearch/OpenSearch domains, ElastiCache clusters
- **Identity & secrets**: IAM users, IAM policies, SSM parameters, IAM Identity
  Center instances, ACM Private CAs
- **AI/ML**: Bedrock models, SageMaker endpoints

### Everything else

Any AWS service not listed above is neither modeled nor collected. The
expansion heuristic: *anything with a stable ARN is a candidate TAP node unless
it is clearly only an embedded configuration detail, transient execution
artifact, metric sample, or policy statement fragment.* A non-ARN resource can
still be first-class when it is structurally important, edge-worthy, or
compliance-relevant (the VPC family is the standing example).

## Adding a new service

The design bet (validated before the engine was built): ~80% of AWS resources
and edges are declarable as manifest data, so adding a service is usually a
**manifest entry, not a module**. In order:

1. **Classify the thing.** Is it a node (durable resource), an
   edge/attribute on an existing node, evidence (a finding/evaluation), or a
   metric? Only nodes get models and manifest entries; apply the ARN heuristic
   above.
2. **Model, if missing.** Use the core repo's `add-model` skill against a dev
   workspace with this plugin checked out editable. That registers the model in
   `tap-plugin.toml` `[models]` and generates the migration. Source the icon
   with the `get-aws-icons` skill (`skills/get-aws-icons/`) — official AWS
   Architecture icons only, never hand-drawn.
3. **Edge types, if the relationship is new.** Use the `add-edge` skill; edge
   definitions land as `edges/<TYPE>.edge.json` registered in
   `tap-plugin.toml` `[edges]`.
4. **Write the manifest entry** in
   `collectors/boto3_collector/aws_resource_manifest.json`. Required per entry:
   `entity_type`, `service`, `scope` (`global` | `regional`), `source`, `why`
   (every entry and every hydrate op carries its rationale — the schema
   requires it), `items_path`, `natural_key`, `fields` (jsonpath → typed model
   columns). Add a `tags` block (`source: rgta` + `resource_type_filter` joins
   the sweep automatically; a per-service side-quest shape exists for the
   outliers) and declarative `edges` rules (`value_path`, `target_type`,
   `key_kind`, `edge_type`, `direction`). The entry is validated against
   `aws_resource_manifest.schema.json` at load; an invalid manifest fails the
   run visibly.
5. **Code only as a last resort.** If one list call isn't enough, first try a
   manifest-declared `hydrate` op list (S3-style fan-out — declarative, no new
   code). Only when identifier binding or region routing genuinely needs glue,
   add a `custom_fn` to `collectors/boto3_collector/customfns.py`, registered
   in the plugin-local registry and composing `hydrate_item`. Never add a
   per-service class.
6. **Permissions.** Ensure the collector credential can perform the new read
   ops: the cross-account role uses AWS-managed `SecurityAudit` (covers most
   read APIs); a static-key principal's policy may need extending. Keep
   `collectors/boto3_collector/handoff/` in sync if the partner-facing
   footprint changes.
7. **Test and validate.** Tests live in `tap_plugin/aws_core/tests/` and ship
   in the wheel. Add coverage alongside the existing `test_boto3_collector_*`
   suites, then run `pytest --pyargs tap_plugin.aws_core` and
   `manage.py validate_plugin aws_core --strict` from a consuming instance —
   "it boots" is not a completion check.
8. **Release.** Version comes from the git tag (hatch-vcs); tag and re-release
   so installs pick up the change.

## Roadmap

1. **Support deletion.** Close the additive-only gap. The JUDGING layer now exists
   (`req-aws-core-reconcile-falsifiers`, Implemented — `tap-plugin.toml`'s `[falsifiers]`
   table, `falsifiers.py`'s `_AwsFalsifier` base, `SubnetFalsifier`): given a retirement
   candidate, a falsifier probes AWS directly and returns a verdict, the same mechanism
   `tap-plugin-github-core` ships (github-core#151). What is still missing is the FEEDING
   half: `boto3_collector` produces no per-surface completeness statement yet
   (`req-aws-collector-reconcile`, still Backlog in `spec-aws-core-collector-v0.md`), so
   `tap_grid.candidates.derive_candidates` has nothing to derive a candidate from — until
   that lands, the grid still accumulates resources that no longer exist in AWS, just with
   the judging half of the pipeline already proven end-to-end in tests.
2. **Add more supported AWS types.** First, manifest entries for the 27
   modeled-but-not-collected types (usually pure manifest work — no new code);
   then models for unmodeled services per the ARN heuristic, following the
   process above.
3. **`trial_provisioner` credential envelope for the trial-run harness.** The
   live trial (`tests/test_trial_run_live.py`, the `add-aws-type` skill's
   verification step) provisions sacrificial resources with WRITE-capable
   credentials — today via ambient AWS credentials (SSO session / `AWS_PROFILE`),
   deliberately disjoint from the read-only `boto_collector` collector secret.
   The optional second lane — a tap-secrets envelope (scope `aws_core`, key
   `trial_provisioner`, kind `aws_static_access_key`, opt-in via
   `TAP_AWS_TRIAL_SECRET_ENVELOPE=1`) — is drafted but NOT wired: it goes
   through TAP's `/manage-secret` review before first use (dedicated IAM
   identity or not; whether `expected_account_id` is mandatory for a
   write-capable key; preflight detection). The least-privilege policy draft
   ships at `collectors/boto3_collector/handoff/trial-provisioner-policy.json`
   (creates require the `tap:trial=sacrificial` request tag; deletes require
   the matching resource tag). Build when a trial must run without a live
   operator session.
4. **kms_key + cloudtrail_trail trial-run legs.** The live trial covers 4 of
   the 6 v0.4.0 types; these two are skip-with-reason (the skips print in
   every gated run — see `test_trial_run_live.py`). `kms_key` is a policy
   fork: KMS keys cannot be hard-deleted (`ScheduleKeyDeletion`, 7-day floor),
   so every trial leaves pending-deletion residue — decide between accepting
   the residue or keeping one long-lived reusable trial key. `cloudtrail_trail`
   is scaffolding only: a trail needs an S3 bucket + bucket policy first, with
   its own teardown ordering. Neither blocks the other four legs.

## Specs (authoritative — this README is orientation only)

| Spec | Owns |
| --- | --- |
| `specs/spec-aws-core-v0.md` | The model + edge vocabulary |
| `specs/spec-aws-core-collector-v0.md` | Collector behavior end to end (the canonical contract) |
| `specs/spec-aws-core-secrets.md` | The two AWS credential kinds' `data` shapes |
| `specs/spec-aws-core-catalog.md` | Catalog refresh (regions/AZs/icons) |
| `specs/spec-aws-projection-top-level-minimal.md` | Field-projection posture |

## Skills

- `skills/get-aws-icons/` — source the official AWS Architecture icon for a
  model's `ENTITY_ICON` key (downloads the pack to a tmp dir per run, installs
  normalized to the 80×80 convention; `--all-missing` backfills).
- `skills/refresh-aws-catalog/` — periodic reference-data refresh for regions
  and AZs; incremental, with an authoritative-evidence deprecation policy.

## History

This plugin was evicted from the TAP monorepo into this repository; the
pre-eviction history (including the parked Steampipe collector effort, its
`park/steampipe-tooling` tag, and the AAR that motivated the manifest-driven
boto3 pivot) lives in the core monorepo, not here. The Cartography /
ScoutSuite / Prowler / CloudQuery prior-art study is summarized in the
collector spec; no open-source code is incorporated — implementations are
clean-room per the project's OSS licensing boundary.
