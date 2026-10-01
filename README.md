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
`aws-core-tap` == namespace `tap_plugin.aws_core` == entry-point key.
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

1. **Support deletion.** Close the additive-only gap. The JUDGING layer exists
   (`req-aws-core-reconcile-falsifiers`, Implemented — `tap-plugin.toml`'s `[falsifiers]`
   table, `falsifiers.py`'s `_AwsFalsifier` base, four falsifiers: `SubnetFalsifier`,
   `VpcFalsifier`, `Ec2InstanceFalsifier`, `SecurityGroupFalsifier`): given a retirement
   candidate, a falsifier probes AWS directly and returns a verdict, the same mechanism
   `tap-plugin-github-core` ships (github-core#151). The FEEDING half now exists too, for
   those same four types (`req-aws-core-regional-containment`, Implemented —
   `aws_core__aws_account_region`, one `HOSTS_*` containment edge per type, per-region
   completeness surfaces): `boto3_collector` produces real completeness statements for VPC,
   subnet, EC2 instance and security group, so `tap_grid.candidates.derive_candidates` can
   derive real candidates for all four from a live collector run. Every other collected type
   still records no completeness statement — the remaining regional types are named in
   `regional.py`'s `NOT_YET_WIRED`, each blocked on pairing a new containment row with a new
   falsifier together.
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

## Deploying to GovCloud

The collector is **partition-aware**: a secret scoped to `us-gov-*` regions
resolves the whole run to the `aws-us-gov` partition — the credential, every
client endpoint (including the "global" services, which route through the
partition's own global endpoint rather than a hardcoded `us-east-1`), every
ARN it mints, and cross-account `AssumeRole` all stay inside that one
partition. `tap_plugin/aws_core/collectors/boto3_collector/partition.py` is
the single module that knows about partitions; nothing else in the collector
package names one (`tests/test_govcloud.py` enforces this with an AST guard).

### Secret shape

Same two kinds as commercial (`spec-aws-core-secrets.md`), with three new
optional `data` fields, identical on both:

```jsonc
{
  // aws_static_access_key, or aws_assumed_role with role_arn/external_id/base
  "access_key_id": "...",
  "secret_access_key": "...",
  "regions_allowed": ["us-gov-west-1", "us-gov-east-1"],

  // NEW, all optional:
  "partition": "aws-us-gov",       // cross-checked against regions_allowed; the
                                     // partition is normally DERIVED from the regions,
                                     // so this is a belt-and-suspenders assertion, not
                                     // something you must set.
  "use_fips_endpoint": true,        // pins every client this run makes to its FIPS
                                     // endpoint. Absent: falls back to the
                                     // AWS_USE_FIPS_ENDPOINT env var / botocore's own
                                     // config resolution — set one or the other
                                     // explicitly for a compliance-relevant run rather
                                     // than relying on the ambient default.
  "expected_account_id": "123456789012"
}
```

For the assumed-role kind, `role_arn` must be an ARN in the **same**
partition as `regions_allowed` (`arn:aws-us-gov:iam::<account>:role/...`) —
a commercial role ARN with GovCloud regions (or vice versa) is refused at
credential resolution, before any AWS call, naming the mismatch. This is the
existing cross-account `AssumeRole` + mandatory `ExternalId` feature
(`spec-aws-core-secrets.md` `req-aws-core-secret-aws-assumed-role`); GovCloud
adds only the partition check.

Region names are shape-checked (`^[a-z]{2,3}(-[a-z]+)+-[0-9]+$`) so a typo
fails secret validation instead of surfacing as a mid-run
`EndpointConnectionError`. On top of that, `resolve_partition` checks every
region against botocore's own bundled endpoint data (or this collector's own
partition table, for a region newer than the vendored botocore) and refuses
to run if any region matches **no partition's shape at all** — a typo that
crosses into gibberish for every partition (`us-gvo-west-1`, letters swapped)
fails closed with a named error instead of silently being treated as
commercial. This is a partition-shape check, not a real-region existence
check: a fabricated-but-plausible commercial-shaped name (`us-east-97`) still
passes, the same as it would against AWS itself before the call is actually
made — closing that would mean maintaining the literal list of regions that
currently exist, which goes stale the moment AWS adds one.

### What changes per run

- **Partition derivation and validation.** The run's partition is derived
  from `regions_allowed` (mixed-partition scopes, an unsupported partition —
  currently anything other than `aws` / `aws-us-gov` — or a role ARN /
  `expected_account_id` mismatch all abort the run by name at startup, before
  any AWS call).
- **Global services route through the partition's own endpoint.** IAM
  resolves to `iam.us-gov.amazonaws.com`, Route 53 to `route53.us-gov.amazonaws.com`,
  Organizations to `organizations.us-gov-west-1.amazonaws.com` — verified
  against botocore's own bundled endpoint rules in `test_govcloud.py`
  (`TestGovCloudEndpoints`), not asserted from memory.
- **The region-scope invariant now names the right anchor.** The old
  "region scope should include `us-east-1`" warning now checks the
  partition's own anchor region (`us-gov-west-1` in GovCloud) and says so.
- **CloudFront degrades to a named result, not an error.** CloudFront is
  **not offered in AWS GovCloud (US)** (AWS GovCloud (US) User Guide,
  "Setting Up Amazon CloudFront with Your AWS GovCloud (US) Resources").
  botocore will still happily construct a plausible-looking
  `cloudfront.us-gov-west-1.amazonaws.com` hostname (there is no DNS behind
  it) — the collector checks the partition explicitly and records one
  `SERVICE_NOT_AVAILABLE_IN_PARTITION` info line for the `cloudfront` manifest
  entry instead of calling it. The Route 53 zone listing still runs; its
  CloudFront cross-join is skipped (the raw `alias_cloudfront_domains` are
  still kept, just not resolved to an ARN — nothing to resolve to). Every
  other manifest-collected service (IAM, STS, S3, Lambda, EventBridge, Logs,
  ACM, DynamoDB, API Gateway v2, Cognito, KMS, SQS, CloudTrail, Secrets
  Manager, Resource Groups Tagging API) has a live GovCloud endpoint
  (confirmed against botocore's bundled endpoint data on 2026-09-28 — see
  `test_govcloud.py`).
- **ARNs are minted in the run's own partition.** The two transforms that
  build an ARN from a bare name (`s3_bucket_arn_from_name`,
  `s3_bucket_name_from_origin_domain`) are bound to the run's partition; every
  other transform reads a partition off an ARN it was handed, which already
  carries the right one. `identity.py`'s `node_entity_id`/`edge_entity_id`
  hash the *natural key string* (already partition-correct) — nothing there
  needed to change.
- **Log groups are keyed by ARN.** A log-group name is unique only within
  one account and region, so `aws_cloudwatch_log_group` is keyed by its ARN
  (without the `:*` suffix); the same name in `us-gov-west-1` and
  `us-gov-east-1` is two nodes. A grid that already holds name-keyed log
  groups from an earlier version keeps those nodes; the collector writes the
  ARN-keyed ones beside them and does not retire the old ones.
- **S3 public access is observed.** `aws_s3_bucket.public_access_blocked` is
  filled from the bucket's own `GetPublicAccessBlock`: true when all four
  settings are on, false when any is off or none is configured, null when the
  read was denied or failed. Account-level Block Public Access is not read.
- **FIPS.** `use_fips_endpoint` (or `AWS_USE_FIPS_ENDPOINT`) is threaded onto
  the `botocore.session.Session` behind every `boto3.session.Session` the
  collector builds (static, assumed-role base, and the assumed-role working
  session alike), so it reaches every client the manifest engine, the RGTA
  sweep, and the falsifiers make — not just one call site. Verified against
  botocore's FIPS endpoint variants (`kms-fips`, `s3-fips`,
  `secretsmanager-fips`, …); IAM/Organizations/Route53 have no separate FIPS
  hostname distinct from their normal GovCloud one (both already terminate
  inside AWS's FIPS boundary per AWS's GovCloud FIPS documentation).

### Known gaps — read before tomorrow's rollout

- **Not run against a live GovCloud account.** Everything above is verified
  three ways: real botocore endpoint resolution (no network — asserting
  against botocore's own bundled endpoint rule data), the exact bytes an
  `AssumeRole`/`GetCallerIdentity` call would put on the wire (captured at
  botocore's `before-send` hook), and the collector's `run()` against canned
  GovCloud-shaped responses. None of it is a live call. Run `self_test()`
  against the real secret before the first collection and read the
  `AWS_PARTITION` check's message.
- **AWS Organizations in GovCloud is its own, separate organization** from
  any commercial one — `CreateGovCloudAccount` links a GovCloud account to a
  commercial billing account, but GovCloud accounts can only join a GovCloud
  organization (source: AWS GovCloud (US) User Guide, "AWS Organizations in
  AWS GovCloud (US)"). The Organizations tree collector
  (`collectors/boto3_collector/organizations.py`, `specs/spec-aws-core-v0.md`
  `req-aws-core-organizations-collect`) reads the organization, OUs, accounts
  and SCPs through a client bound to the run's first region, so a GovCloud
  run reads the GovCloud organization. It needs the management account or a
  delegated administrator; from any other account it records why it read
  nothing and the run continues. AWS documents some Organizations calls as
  available only in `us-gov-west-1`; how that interacts with a scope that
  starts with `us-gov-east-1` has not been run. Put `us-gov-west-1` first.
- **China (`aws-cn`) and the isolated partitions are refused, not silently
  mishandled.** `resolve_partition` recognises their regions (so an ARN or
  region from one classifies correctly rather than reading as commercial)
  but raises `CredentialError` naming the partition if a secret is scoped to
  one — nothing here has been exercised against them.
- **Per-service GovCloud availability beyond the 16 manifest-collected
  services is unverified.** `service_unavailable_reason` only names
  CloudFront. If a future manifest entry adds a service GovCloud does not
  offer, botocore may still construct an endpoint for it (as it does for
  CloudFront) and the run will see connection failures rather than a clean
  skip, until that service is added to `partition.py`'s
  `_UNAVAILABLE_SERVICES` table.
- **A failed tag sweep still overwrites stored tags.** When the RGTA
  (`GetResources`) sweep fails in a region, the run warns
  `RGTA_SWEEP_SKIPPED` and every tag-swept node there (Lambda, EventBridge,
  log groups, ACM, DynamoDB, S3) is written with
  `tags = {}`, replacing whatever an earlier run stored. A KMS key, SQS queue
  or CloudTrail trail whose own tag call fails is written the same way. GRIFT
  import replaces every field of an existing node and has no way to say "leave
  this field as it is", so the fix waits on a core decision
  (tap-plugin-aws-core#60). Until then, read `RGTA_SWEEP_SKIPPED` as "tags in
  that region are wrong this run". Whether `GetResources` works in
  `us-gov-east-1` has not been run here. With `use_fips_endpoint: true` the
  sweep is sent to a `tagging-fips.<region>` host, which AWS does not list
  for GovCloud, so expect the sweep to fail.
- **`aws_organization.partition` is read, never assumed.** The
  Organizations collector fills it from the partition segment of the
  organization ARN `DescribeOrganization` returns.
- **FIPS-validated crypto module, not just a FIPS *endpoint*.** This PR
  routes calls to AWS's FIPS-140 *endpoints*; it says nothing about whether
  the TLS termination on this side is itself FIPS-validated (that is a
  platform-level concern — this repo's `tap` runs with `TAP_FIPS_MODE=1` /
  OpenSSL FIPS provider; see the core repo's `bump-openssl-fips` material).
  Confirm the deploying platform's own FIPS posture separately.

### Verifying before you deploy

```
python manage.py validate_plugin <checkout> --level loads --strict
python -m pytest tap_plugin/aws_core/tests/test_govcloud.py -v
```

`self_test()` (also reachable via the collector self-test UI/API) now reports
an `AWS_PARTITION` check naming the resolved partition and FIPS posture
before attempting STS reachability — read its message, not just its pass/fail,
before the first live run.

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
