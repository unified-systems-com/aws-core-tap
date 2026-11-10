# AWS Core Collector Specification (v0)

## Philosophy

The AWS Core collector populates the TAP grid from a running AWS account. It is the
first concrete consumer of the `aws_core` resource-type models, the `tap_cares`
collector runtime, and the `tap_cares` secrets subsystem.

The collector is **manifest-driven**. Instead of one hand-written fetch/transform
module per AWS resource type, a single generic engine is driven by a JSON resource
manifest. Each manifest entry declares: which service it covers, how to enumerate
its instances, which fields to surface as indexed model columns, and which
relationships to materialize as edges. The full AWS payload is retained verbatim
in the node's in-memory `configuration` envelope, so nothing collected is ever
lost to a too-narrow projection. Whether that envelope is persisted is decided
per manifest entry (`persist_configuration`, rulings 2026-09-23; see
[Field Projection](#field-projection)); the envelope is always built in memory.

The design bet, validated by an offline extensibility probe before any code was
written (S3 / EC2 / IAM hard set): roughly **80% of resources and edges across the
AWS surface are declarable** as manifest data, and the non-declarable residue is
**concentrated, not scattered** — it collapses into two write-once engine seams
(a fan-out hydrate template and a policy-document edge resolver) rather than
sprawling into per-service code. This is what makes the pattern extensible and
keeps the future build-collector skill a *config generator*, not a code generator.

v0 is fenced hard to the `step-rampart-sam-demo` roadmap step: a single account,
the finite set of resource types in the reproduced samaydlette.com stack, no
deletion/reaping, no multi-account. The engine is specified generally (the
architectural bet is deliberate and the user is choosing this over a
Steampipe/Cartography-style per-service route), but the manifest *contents* and the
seams *built* in v0 are scoped to what the demo needs.

There is deliberately **no per-service class**. Per-service subclasses are the
Steampipe/Cartography/Magpie pattern this design rejects: the moment per-resource
knowledge lives in a class hierarchy instead of manifest data, the manifest is
decorative and the future build-collector skill reverts to a code generator. The
only base class is the framework's `CollectorBase`, with exactly one subclass for
all of AWS. Beneath it the engine composes a small fixed set of shared
collaborators — a credential/client factory, the fan-out hydrate helper, a
`custom_fn` protocol, a parsed `ResourceSpec` value object — composition over
inheritance, per the TAP guide. Reuse lives in those composed helpers, never an
inheritance tree; "no per-service class" is a load-bearing invariant, not a
style choice.

## Prior Art

Cartography (Lyft), ScoutSuite, Prowler, and CloudQuery were studied early for
shape: the fetch → pure-transform → load → cleanup decomposition, declarative
node/relationship schemas, per-region/per-account iteration, classify-and-skip
error handling, and the `update_tag` staleness sweep. The manifest-driven
*inversion* (declarative-first with code as the bounded exception, rather than
code-first with schema declarations) is TAP's own design.

No open-source code is incorporated. Per `AGENTS.md`, this is a licensing boundary,
not a style preference: ideas and shapes were extracted; implementations are
clean-room in TAP's own vocabulary against `CollectorBase` and GRIFT. AWS API
facts (which operation, which response field) are factual properties of the AWS
SDK that TAP depends on, not borrowed source.

## Roadmap Alignment

Governing step: `step-rampart-sam-demo` (Active, Timeline Target 2026-06-01).
This collector is named in that step's `Depends-on` as "the from-scratch boto3
`aws_core` collector — clean slate, Steampipe excised". It supersedes the parked
Steampipe collector design (`git tag park/steampipe-tooling`); the durable
credential/config/target *patterns* from the parked spec informed this design and
were re-expressed clean-room here. The step's Non-Goals (no live pull from Sam's
real account, no VPC/subnet topology, no config-vs-ops dimensions, no multi-user,
no encrypted secrets) are inherited as v0 fences.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Declarative   | A JSON manifest drives collection; adding a resource is a manifest entry, not a module |
| 2. | Lossless      | The full AWS payload is retained in the in-memory `configuration` envelope and persisted for every entry whose manifest `persist_configuration` is true; projection never discards data |
| 3. | Connected     | Relationships are materialized as edges via declarative rules, each endpoint named by natural key |
| 4. | Bounded       | The non-declarative residue is two write-once seams, not per-service code |
| 5. | Conventional  | The collector is an ordinary `CollectorBase` implementation; it invents no parallel runtime |
| 6. | Fenced        | v0 collects Sam's finite resource set, one account, no deletion semantics |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-aws-collector-scope | [Collector Scope](#collector-scope) | Approved for Development | One account, Sam's resource set, no deletes |
| req-aws-collector-manifest | [Resource Manifest](#resource-manifest) | Approved for Development | The JSON descriptor format — the architectural heart |
| req-aws-collector-source | [Source Primitive](#source-primitive) | Approved for Development | `source` ∈ {aws_op, aws_op with per, custom_fn}, uniform "yields items" contract |
| req-aws-collector-field-projection | [Field Projection](#field-projection) | Approved for Development | jsonpath → typed fields + full payload → `configuration` |
| req-aws-collector-identity | [Identity By Natural Key](#identity-by-natural-key) | Approved for Development | Nodes and edges sent by ref and natural key; core assigns and finds ids; re-runs update in place |
| req-aws-collector-edges | [Declarative Edge Rules](#declarative-edge-rules) | Approved for Development | Endpoints named by natural key, resolved by core; v0 make-it-work = mutually-available natural keys |
| req-aws-collector-edge-resolver | [Edge Identifier Resolution (Future Seam)](#edge-identifier-resolution-future-seam) | Backlog | The durable fix: pre-batch resolution pass; `key_kind`-driven; misses become observable warnings |
| req-aws-collector-reconcile | [Grid-State Reconciliation (Future Seam)](#v0-non-goals) | Backlog | Implied-absence/tombstone via the same grid-read primitive as the resolver; one generic reconcile vs Cartography per-type cleanup |
| req-aws-collector-progressive-upload | [Progressive Upload (Future Seam)](#progressive-upload-future-seam) | Backlog | Write to the grid as the run works, not in one batch at the end: either by phase (nodes, edges, completeness) or by self-contained units the manifest or collector declares complete |
| req-aws-collector-hydrate | [Fan-Out Hydrate Seam](#fan-out-hydrate-seam) | Approved for Development | First named seam; per-op error-swallow; S3-style many-call |
| req-aws-collector-s3-bucket-size | [S3 Bucket Size Metrics](#s3-bucket-size-metrics) | Approved for Development | Aggregate size/count from CloudWatch storage metrics; `size_observed_at` data-currency disclosure |
| req-aws-collector-ecs | [ECS Clusters, Tasks And Container Images](#ecs-clusters-tasks-and-container-images) | Proposed | Collect ECS clusters, services, tasks and containers; per-container image and image digest as the join key to builds, SBOMs and findings; credential-bearing overrides declared, configuration off |
| req-aws-collector-lb-topology | [Load Balancer Topology](#load-balancer-topology) | In Development | A load balancer reaches its targets through its target groups, one edge per listener rule carrying the rule; each target edge carries its port and health; load balancer and Lambda targets are linked; Route 53 record sets become nodes between a zone and what they resolve to |
| req-aws-collector-credentials | [Credential Resolution](#credential-resolution) | Approved for Development | `tap_cares` secret, `aws_static_access_key`, single account |
| req-aws-collector-runtime | [Collector Runtime Integration](#collector-runtime-integration) | Approved for Development | `CollectorBase` pipeline; mirrors the KSI reference collector |
| req-aws-collector-regions | [Region Iteration And Resilience](#region-iteration-and-resilience) | Approved for Development | Classify-and-skip; bounded throttle backoff |
| req-aws-collector-selection | [Collection Selection](#collection-selection) | Proposed | A run collects only the types and accounts the credential's `include_types`, `exclude_types` and `accounts_allowed` select; an unselected type or account is unobserved, never empty, and retires nothing; the effective selection is echoed in every run |
| req-aws-collector-partition | [AWS Partitions](#aws-partitions) | Implemented | Commercial and GovCloud: partition derived from the region scope, refused when mixed or unsupported; partition-aware ARNs and global-service routing; CloudFront degrade; FIPS opt-in; entries a partition does not offer are marked per entry in the manifest (`not_offered`) and kept honest by a test against the newest wave 0 record |
| req-aws-collector-outcome | [Listing Outcomes And Client Posture](#listing-outcomes-and-client-posture) | Approved for Development | A listing that yields nothing for a named reason that is not a failed call (`not_configured`, `unsupported_in_partition`, `throttled`) is a recorded result and never a complete-empty observation; one `Config` for timeouts and retries |
| req-aws-collector-grift-batch | [GRIFT Batch Assembly](#grift-batch-assembly) | Approved for Development | One batch/run; provenance; no deletion semantics |
| req-aws-collector-edge-authority | [Edge Authority Claims](#edge-authority-claims) | Implemented | Per anchor, how each manifest edge rule's source, and each Organizations placement and attachment read, was read (complete, partial, failed); one `edge_cases.authority` claim per scope, sent only to an importer that accepts the section; a failed or truncated sub-call is never `complete` |
| req-aws-collector-progress | [Run Progress](#run-progress) | Proposed | A run writes progress lines to the process log while it works: a start line, a throttled heartbeat naming the entry being read, a line when the reads end, and a line when the batch is imported; counts only |
| req-aws-collector-audit-ledger | [Audit Verifiability](#audit-verifiability) | Approved for Development | Per-run AWS call ledger → `CollectionJob.results`; step one of the verifiability theme |
| req-aws-collector-tags | [Resource Tags](#resource-tags) | Approved for Development | Per-node `tags.source` (RGTA default / per-service side-quest); one canonical `{str:str}` field. Proposed amendment ACs `-9`..`-15` (landing-zone epic): declared lanes including `none`, the Organizations lane, AWS-reserved keys kept, untaggable declared, every new type declares its lane, a per-entity-type lane registry for types with no manifest entry, the `service` lane reads every page |
| req-aws-collector-fanout | [Multi-Account Fan-Out](#multi-account-fan-out) | Proposed | From the organization's management account: list members, `AssumeRole` into each with a partition-aware role ARN, collect each, report per account; one batch per account |
| req-aws-collector-pagination | [Every Paginated Call Read To Its End](#every-paginated-call-read-to-its-end) | Proposed | Every call the landing-zone epic names that botocore paginates is read to exhaustion; a later-page failure leaves the field or surface unknown, never partial |
| req-aws-collector-model-deps | [Model Dependencies](#model-dependencies) | Proposed | CloudFront / CloudWatch log group / EventBridge rule models must exist |
| req-aws-collector-sam-example | [Sam Worked Example](#sam-worked-example) | Proposed | Concrete manifest + edge set for the demo target |
| req-aws-collector-build-skill | [Build-Collector Skill Direction](#build-collector-skill-direction) | Proposed | Skill is a manifest generator; trust-tier axis |
| req-aws-collector-drift | [Shape-Drift Detection](#shape-drift-detection) | Proposed | botocore-pinned `service-2.json` diff via the catalog skill |
| req-aws-collector-nongoals | [v0 Non-Goals](#v0-non-goals) | Proposed | Deletes, multi-account, uniform-enum, policy resolver, deep IAM graph |

### Collector Scope
----
RID: `req-aws-collector-scope`

Status: `Approved for Development`

v0 collects a single AWS account into the grid, scoped to the resource types
present in the reproduced samaydlette.com stack.

#### Implementation

In scope for v0:

- one AWS account, resolved from one `tap_cares` secret
- the resource types: S3 bucket, CloudFront distribution, ACM certificate,
  Route 53 hosted zone, Lambda function, IAM role, CloudWatch log group,
  EventBridge rule
- one or more regions of ONE partition — commercial (`aws`) or AWS GovCloud
  (US) (`aws-us-gov`), see [AWS Partitions](#aws-partitions) — plus global
  services (S3, CloudFront, Route 53, IAM) collected once
- create/upsert of nodes and edges through GRIFT only

Explicitly out of scope for v0 (see [v0 Non-Goals](#v0-non-goals)): deletion /
reaping / implied-absence semantics, multi-account, uniform-enumeration APIs,
the policy-document edge resolver, the deep IAM/Org/SCP permission graph,
the China and isolated partitions.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-scope-1 | Single Account | Approved for Development | v0 targets exactly one AWS account per collection run. | Proposed to be superseded by `req-aws-collector-fanout` (one run, the organization's member accounts). Unchanged until that requirement is approved. |
| req-aws-collector-scope-2 | Sam Resource Set | Approved for Development | The v0 manifest covers exactly the eight named resource types. | Driven by the demo, not by completeness. |
| req-aws-collector-scope-3 | No Deletion Semantics | Approved for Development | v0 only creates/upserts; absence from a run never deletes a node. | Reaping deferred (`req-aws-collector-nongoals`). |
| req-aws-collector-scope-4 | Commercial and GovCloud | Approved for Development | A run collects one partition: commercial (`aws`) or AWS GovCloud (US) (`aws-us-gov`). The China and isolated partitions are refused by name. | Mirrors `req-aws-core-scope-2`; the mechanism is `req-aws-collector-partition`. |

### Resource Manifest
----
RID: `req-aws-collector-manifest`

Status: `Approved for Development`

A single JSON manifest, versioned and shipped in the plugin, declares every
resource type the collector knows how to gather. The generic engine carries no
per-resource knowledge.

#### Implementation

The manifest is an ordered list of resource entries. Each entry declares:

| Key | Meaning |
| --- | --- |
| `entity_type` | The `aws_core` model entity type the entry populates (e.g. `aws_lambda`). |
| `service` | The boto3 service name (e.g. `lambda`, `s3`). |
| `scope` | `regional` or `global`. Global services are collected once, not per region. |
| `source` | The enumeration source (see [Source Primitive](#source-primitive)). |
| `why` | Human one-line reason this resource/enumerate call is collected; materialized into the node's `_source` (see [Field Projection](#field-projection)). |
| `items_path` | jsonpath to the list of resource items within the source result, supporting nested-array flatten (e.g. `Reservations[].Instances[]`). |
| `natural_key` | jsonpath to the value the node is identified by (see [Identity By Natural Key](#identity-by-natural-key)). |
| `fields` | Map of model field name → jsonpath into the item (see [Field Projection](#field-projection)). |
| `hydrate` | Optional list of per-item hydrate ops, each `{key, op, why}` (see [Fan-Out Hydrate Seam](#fan-out-hydrate-seam)). |
| `edges` | List of declarative edge rules (see [Declarative Edge Rules](#declarative-edge-rules)). |
| `persist_configuration` | Required boolean. Whether this entry's `configuration` envelope is persisted (see [Field Projection](#field-projection), `req-aws-collector-field-projection-7`). |
| `persist_configuration_why` | Required, non-empty. One line saying why the flag has its value. |
| `sensitivity` | Required. Whether this entry's raw response may carry sensitive values, and where (see [Response Sensitivity Declaration](#response-sensitivity-declaration)). |

The manifest is pure data. The engine validates the manifest against a JSON
Schema shipped alongside it at load time; a malformed manifest fails the run
visibly (it is operator/author error, not a runtime condition).

Manifest entry order is advisory only — because an edge names its endpoints by
natural key (not by matching an already-loaded node), the engine does not depend on
collection order. This is a deliberate divergence from the prior-art convention
where sync order encodes the dependency graph.

#### Response Sensitivity Declaration

Ruling (George, 2026-09-23): masking or redacting values in `configuration` is
ruled out — the raw responses are future audit evidence, and a masked copy is
useless as evidence. Instead the manifest records, per entry, which responses may
carry sensitive values and where. This is tracking, not control: persistence is
decided by the entry's `persist_configuration` flag
([Field Projection](#field-projection)). The two meet in one rule, below.

Every entry carries a `sensitivity` block. The schema requires it, so a new
entry without one fails manifest load; declaring `{"status": "unreviewed"}` is
the cheap, honest default, and an unreviewed entry is not stored (below).

| Key | Meaning |
| --- | --- |
| `status` | `unreviewed` (nobody has checked the response shape; says nothing about safety), `reviewed_none_known` (checked; no sensitive location known), or `reviewed_may_contain` (checked; `locations` lists where). Absence is not a fourth state: it is a schema error. |
| `basis` | One line naming the method behind the status — what was read (botocore output shapes, the `custom_fn`) and when. Required for both reviewed states. |
| `locations` | Present and non-empty exactly when `status` is `reviewed_may_contain`. Each is `{path, category, reason, evidence}`. |
| `locations[].path` | The manifest's own path dialect (`paths.py`), resolved against the item the source yields — the root of the `configuration` envelope, so `_hydrate.<key>.data...` and `custom_fn`-added `_` keys are addressable. A path ending at a map or object covers its subtree. |
| `locations[].category` | `credential`, `personal_data`, `customer_content`, `access_policy`, `free_text`, `diagnostic`, or `other` (defined in the schema). |
| `locations[].evidence` | `botocore_sensitive` (the botocore service model marks the member `sensitive`) or `reviewer_judgement` (a reviewer read the shape and judged it). |

Why a path list and not a per-entry boolean: the remedy when persistence returns
will be per location (encrypt this subtree, move that one to a secret-kind
store, drop a third), and a boolean would force re-doing the review. Why
`evidence`: the provider's own `sensitive` trait is a checkable fact, a
reviewer's judgement is not, and the two should not read alike. Why
`free_text` and `diagnostic` are listed at all: operators paste secrets into
descriptions, and error text can echo input; leaving them off would let a
reviewed entry read as cleaner than it is.

For `aws_op` entries a test resolves each declared path against botocore's
output shape for that op, and checks that every `botocore_sensitive` location
really carries the trait; and, as a completeness ratchet, that every member
botocore marks `sensitive` in the item shape is covered by a declared location (a
declared ancestor covers its subtree). `custom_fn` entries build their own items,
so their paths and completeness are checked by reading the `custom_fn`.

Tag values are operator-set arbitrary strings. Where they ride inside the
envelope — the `field` lane's `from` path, or `_hydrate.tags` for the `service`
lane — they are declared as `customer_content`, and a test enforces it for every
entry on those lanes. The `rgta` lane's tags come from the per-run sweep, not the
item.

**Sensitivity and persistence.** Unreviewed means not stored: an entry whose `sensitivity.status` is `unreviewed` must set
`persist_configuration: false`. Nobody has looked at the response shape, so
nothing supports storing it. The manifest schema carries the rule as an
`if`/`then` on the entry, so `load_manifest()` rejects an unreviewed entry that
persists before any collection runs; no separate check can drift from it. As
shipped no entry is unreviewed. Deciding the flag on any unreviewed entry, any
entry with a `credential` location, or any entry that persists while listing a
location is surfaced to the person who requested the work, who decides it
(the `add-aws-type` skill, step 1).

**Redaction (`req-aws-collector-redaction`).** The collector stores everything AWS returns and removes only obvious
secret material: keys, passwords and credentials (George, 2026-11-05: the more data on the grid the better the map;
a secret an operator typed into a tag, a description or a policy is the operator's). Every entry therefore sets
`persist_configuration: true`. Two things are removed from a stored `configuration`: the paths the entry's
`sensitivity.locations` mark `redact: true` (the members AWS itself marks sensitive, and the reviewed secrets such as
`ClientSecret`, `PreSharedKey`, `UserData`), and any string whose key names a secret (`password`, `secret`, `private
key`, `API key`, `token`) unless the key is a reference, flag, date or URL (`SecretArn`, `PasswordLastUsed`, `TokenUrl`).
What was removed is listed under `_redacted`, so a reader can tell a withheld value from an absent one. Categories other
than `credential` (customer content, free text, access policies, personal data) are never redacted. The contents of a
resource (S3 objects, Parameter Store values, table items) are not collected at all, because no operation that reads
them is made. The canonical `tags` model field is persisted independently ([Resource Tags](#resource-tags)).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-manifest-1 | Data-Only Manifest | Approved for Development | The engine contains no per-resource-type branching; all per-type knowledge lives in the manifest. | The escape hatch is `custom_fn`, itself named in the manifest. |
| req-aws-collector-manifest-2 | Schema Validated | Approved for Development | The manifest validates against a shipped JSON Schema at load; invalid manifest fails the run visibly. | |
| req-aws-collector-manifest-3 | Order Independent | Approved for Development | Collection results are identical regardless of manifest entry order. | Enabled by identity by natural key. |
| req-aws-collector-manifest-4 | Versioned | Approved for Development | The manifest carries a version recorded in the GRIFT batch provenance. | Supports drift tracking. |
| req-aws-collector-manifest-5 | Self-Describing Entries | Approved for Development | Each entry carries a `why`, and each `hydrate` element a `{key, op, why}`; the schema requires `why` so every collected call's rationale is authorable and visible in the manifest. | Materialized per-node (`_source`) so a grid object is legible without the manifest, for every entry that persists its configuration (`req-aws-collector-field-projection-7`). |
| req-aws-collector-manifest-6 | Response Sensitivity Declared | Approved for Development | Every entry declares `sensitivity` in one of three states (`unreviewed`, `reviewed_none_known`, `reviewed_may_contain`); a missing declaration fails schema validation; `reviewed_may_contain` lists `{path, category, reason, evidence}` locations. | Ruling 2026-09-23. A location may carry `redact: true` (see `req-aws-collector-redaction`). `tests/test_boto3_collector_sensitivity.py`. |
| req-aws-collector-manifest-7 | Unreviewed Is Not Stored | Approved for Development | An entry whose `sensitivity.status` is `unreviewed` has `persist_configuration: false`; the manifest schema rejects an unreviewed entry that persists, so the manifest fails load. | Enforced in `aws_resource_manifest.schema.json` (entry `allOf`). `tests/test_boto3_collector_sensitivity.py::TestSchema::test_unreviewed_entry_that_persists_is_rejected`. |

### Source Primitive
----
RID: `req-aws-collector-source`

Status: `Approved for Development`

A manifest entry's `source` is a single primitive with two implementations. Both
return the same thing — an iterable of raw resource items — so the engine never
branches on which was used.

#### Implementation

`source` is one of:

- **`aws_op`** — a declared boto3 operation. The entry names the operation (e.g.
  `ListFunctions`) and the engine drives it generically: it resolves the client
  for `service`, uses the operation's paginator when one exists in the botocore
  model, otherwise calls it once, and yields items via `items_path`. This is the
  common case ("one describe call per service" — confirmed single-call for
  Lambda, IAM roles, EventBridge rules, CloudWatch log groups, and CloudFront).
- **`aws_op` with `per`** — the same declared operation for a resource whose list
  call needs a parent's identifier. `per` names the call that lists the parents
  (itself `per` another for a resource two levels down) and `bind` maps the
  operation's request parameters to paths on one parent. The engine runs the
  operation once per parent and tags each child item with its parent under
  `_parent`. It is a loop over declared calls, not assembly (`req-aws-collector-source-6`).
- **`custom_fn`** — a named, registered Python callable shipped in the plugin,
  used only where AWS requires multiple calls to assemble one logical resource
  (confirmed for S3, ACM full detail, Route 53 record sets, DynamoDB
  table-describe fan-out, IAM OIDC-provider detail fan-out). The callable
  signature is `fn(session, *, client_for) -> Iterator[dict]`: it receives
  the unbound boto3 session (for global resources or service-bound clients
  it constructs itself) AND a `client_for(service) -> Client` callable
  already bound to the current per-region iteration so regional custom_fns
  can build region-bound clients without inventing their own region
  resolution. Global custom_fns (Route 53, the S3 list-buckets head)
  accept-and-ignore the kwarg. The manifest names the callable; the engine
  looks it up in a plugin-local registry. Code is **never** loaded from
  manifest data (mirrors `req-tap-cares-collector-registry-6`).

`custom_fn` callables are expected to compose the [Fan-Out Hydrate
Seam](#fan-out-hydrate-seam) rather than hand-rolling pagination/error handling.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-source-1 | Uniform Item Contract | Approved for Development | `aws_op` and `custom_fn` both yield the same raw-item iterable; the engine does not branch on source kind downstream. | |
| req-aws-collector-source-2 | Generic Pagination | Approved for Development | `aws_op` uses the botocore paginator when the model defines one; else it calls the operation and, while the response carries a continuation marker (`NextToken`, `nextToken`, `NextMarker`/`Marker`, `NextContinuationToken`) the operation accepts as a request parameter, calls it again with that marker. A marker that repeats, one the operation cannot take, or more than 1000 calls stops the walk and is reported as truncated, never as a complete listing. No per-resource pagination code. | `source.py::_walk_unpaginated`; `tests/test_boto3_collector_source.py::TestUnpaginatedContinuation`. Amended when 61 entries on operations without a paginator were found to read only a first page. |
| req-aws-collector-source-3 | Registered Callables Only | Approved for Development | `custom_fn` resolves through a plugin-local registry; manifest data never drives code import or path loading. | |
| req-aws-collector-source-4 | Quarantined Complexity | Approved for Development | Multi-call assembly of one logical resource exists only inside `custom_fn` callables. The one thing the engine does itself is the declared parent fan-out of `req-aws-collector-source-6`, which runs a list call once per parent and assembles nothing. | Narrowed from "multi-call assembly never in the engine" when `source.per` was added. |
| req-aws-collector-source-5 | Custom-Fn Signature | Approved for Development | `custom_fn` callables accept `(session, *, client_for)`. `client_for(service) → Client` is bound to the current per-region iteration so regional custom_fns can build region-bound clients without inventing their own region resolution; global custom_fns accept-and-ignore. | Discovered in autonomous pass 2026-05-20 when DynamoDB regional collection failed with "You must specify a region." |
| req-aws-collector-source-6 | Parent Fan-Out | Approved for Development | `source` may be `{aws_op, per, bind}`: `per` is the call (itself possibly `per` another) that lists the parents, `bind` maps this operation's request parameters to paths on one parent (`""` is the parent itself), and the operation runs once per parent. Each child item carries its parent under `_parent` for `fields` to read. A parent whose call raises fails the whole listing, so the type reads as not collected, never as a short list that looks complete. A `per` that has its own `per` must carry a `bind`. The final listing's items must be structures (a scalar item has no slot for `_parent`, so one fails the listing); every declared operation, parent calls included, must start with a read verb (`tests/test_boto3_collector_source.py::test_every_declared_operation_is_a_read`); `_parent` is stripped before the item is stored as `configuration` (for a `per` entry only; `raw_item` keeps it in memory for edge and authority reads and is never stored). Either level may carry literal `params`, fixed request arguments the parent does not supply. A `per` may instead be `{values: [...]}`, a literal list of string parents for a request no call can supply the value of (App Auto Scaling's `ServiceNamespace`), bound with `""`. A middle level that lists bare names carries each as `{"_self": name, "_parent": the level above}`, so the next level binds both (`_self`, `_parent`); only the last level's items must be structures. A `bind` key may be dotted (`SchemaId.SchemaArn`) to build a nested request structure, and a bind value may be `{path, list: true}` for a list-typed parameter. A scalar parent (a bare name or ARN from the list) is described by a final operation whose `items_path` names one structure without `[]` (a `Describe`/`Get`): that structure is the one item.  An entry with `per` cannot declare `containment`. The collector reads the whole listing before it emits any node, so a failing parent skips the entry with no partial output (`collector.py`, `items = list(iter_source(...))`). | `source.py::iter_fanout`; `tests/test_boto3_collector_source.py::TestPerFanout`. Opens the types whose list call needs a parent id (a table inside a database, a device inside a fleet). |
| req-aws-collector-source-7 | Account Parameter | Approved for Development | A plain `aws_op` source may carry literal `params`, and any `params` value in a source (plain or `per`) equal to the string `$account_id` is replaced by the account being collected. A source that names it when the collector has no account id fails the listing. | `source.py::_with_account`; `tests/test_boto3_collector_source.py::TestAccountParam`. Opens the list calls that ask for the account (QuickSight `AwsAccountId`). |
| req-aws-collector-source-8 | Derived Item Keys | Approved for Development | An entry may carry `derive`, a map of item key (must start with `_`, so it cannot shadow an AWS member) to a template. `{partition}`, `{region}` and `{account}` are the scope being collected; any other `{Path}` is a path on the item. The built keys are added to each item before projection, so `natural_key`, `fields` and the tags lane read them like any member; they are not stored in `configuration`. A missing value fails the listing. For a resource a listing names but gives no ARN, with the ARN format cited per service from botocore or IAM documentation. | `source.py::iter_source`, `render_template`; `tests/test_boto3_collector_source.py::TestDerive`. Prior art: Steampipe builds the Glue job ARN from partition, region, account and name; Cartography's `build_arn`. |
| req-aws-collector-source-9 | Item Filter | Approved for Development | A plain `aws_op` source, a `per` level, or the final `per` call may carry `where`, a list of conditions every item must satisfy: a `path` on the item and one of `equals`, `not_equals`, `in`, `prefix`, `contains`. For a listing that mixes kinds of one resource with no request filter (Comprehend's document-classifier and entity-recognizer endpoints), or that returns a mutable working copy beside the numbered versions (`not_equals: DRAFT` on a version listing). A tags-lane `service` param may carry `list: true` to send the value as a one-element list. | `source.py::_passes`; `tests/test_boto3_collector_source.py::TestWhere`. |
| req-aws-collector-source-10 | Request Forms The API Insists On | Approved for Development | A listing the API refuses without a parameter carries it in `params` (`DescribeVpcBlockPublicAccessExclusions` takes `MaxResults`, which it requires when no `ExclusionIds` are given); a listing the API cannot make account-wide fans out per parent (`ListAssets` of IoT SiteWise requires an asset model, so it runs per `ListAssetModels` item of type `ASSET_MODEL`, as AWS documents). | `tests/test_boto3_collector_outcomes.py::TestRequestFixes`. Both found by the 2026-11-01 GovCloud wave-0 run. |
| req-aws-collector-source-11 | AWS-Owned Registry Not The Account's | Approved for Development | The EventSchemas registry `aws.events` is AWS's, its schemas carry no `SchemaArn` and it no `RegistryArn`; both entries filter it out by exact name (`where` `not_equals: aws.events`, never a prefix, so a registry the account owns is never dropped from a listing that reports itself complete) and say so in `why`. This is the only AWS-owned-default filtering the manifest does; any other is a separate decision. | `TestRequestFixes::test_the_aws_owned_registry_is_not_read_as_the_accounts`, `::test_the_schemas_of_the_aws_owned_registry_are_not_listed`. |

### Field Projection
----
RID: `req-aws-collector-field-projection`

Status: `Approved for Development`

Each raw item is projected into a typed `aws_core` node plus a full
`configuration` payload.

#### Implementation

For each item:

- the manifest `fields` map assigns each declared model field a jsonpath into
  the item; the engine extracts each, applying graceful-missing semantics — a
  path that does not resolve yields `null`, never an error. (AWS response shapes
  are stable across SDK versions; the real variability is conditional/optional
  fields absent on a given instance, which this handles by design — it mirrors
  the existing `aws_core` hybrid nullable-field pattern, `req-aws-core-fields-3`.)
- the **entire raw item** is retained verbatim in the node's in-memory
  `configuration` envelope, so no AWS attribute is lost to projection even if it
  is not surfaced as a typed field. Whether that envelope is **persisted** to the
  `configuration` JSONField (`req-aws-core-fields-1`) is decided per entry by
  the manifest's `persist_configuration`, below.
- the node's `name` is taken from the manifest-declared name field or the
  natural key.

Field projection performs no type coercion beyond what the model's
`FIELD_CRUD_SCHEMA` requires; values are passed as received and the existing
service-layer validation applies.

**Temporal fields.** Dates are the one normalization the collector performs, and
it is engine-level, not a manifest transform:

- boto3 already parses every AWS field the botocore model types as `timestamp`
  into a `datetime` (uniform regardless of wire format). The engine serializes
  every `datetime` to ISO 8601 UTC (`…Z`) when writing the `configuration` blob
  and GRIFT — a single mandatory rule (a `datetime` is not JSON-serializable),
  not a per-field transform.
- The raw `configuration` blob otherwise keeps AWS's value verbatim, including
  the two known non-`timestamp` date shapes (epoch-millis `long` — CloudWatch
  Logs `creationTime`; offset-string — Lambda `LastModified`). The blob is for
  inspection and is never canonicalized (consistent with No Silent Coercion).
- The manifest may map one source field to the entity envelope's `created_at`
  and one to `updated_at`. This is the **only** place a date is canonicalized
  for query. That mapping carries a 3-value format hint
  (`timestamp` | `epoch_ms` | `iso8601_offset`) covering exactly the two
  non-`timestamp` warts; the engine normalizes all three into one ISO 8601 UTC
  envelope field at collection time. The hint is an input-parsing enum on ~1
  field per resource, not a transform language, and it never leaks to the query
  side: "entities created/updated after X" is a single query against one
  canonical envelope field — never three queries or per-resource field
  spelunking.

Two temporal concepts are kept distinct and must not be conflated: the
**grid-native** first-seen/updated time (TAP-owned, always present, uniform —
the reliable spine for "what did this run collect/change" and the History/FLIP
audit-evidence surface) and the **AWS-source** creation/modification time
(mapped into the envelope where AWS exposes it). The probe showed several
enumerate calls — CloudFront `ListDistributions`, Route 53 `ListHostedZones`,
EventBridge `ListRules` — return *no* creation timestamp; for those the
AWS-source envelope `created_at` is legitimately null and the grid-native time
is the answer. Single-field / single-query holds for both; completeness of the
AWS-source field is bounded by what AWS returns, by design.

**Reserved envelope keys and stable serialization.** The node `configuration`
is the enumerate item at its root plus engine-reserved keys: `_source`
(`{op, why}` — the enumerate call and its manifest rationale, present on
**every** node, single-call and fan-out, so even a single-call object is
self-describing), and on fan-out resources `_hydrate` and `_hydrate_mapping`
(see [Fan-Out Hydrate Seam](#fan-out-hydrate-seam)). Reserved keys are
engine-managed and are **not** valid `fields`/`edges` jsonpath targets for
authored mappings — they are engine output, not AWS payload. Node identity
derives only from the root enumerate item, never a reserved key.

Two engine rules keep the blob stable across runs:

- `ResponseMetadata` is stripped from every boto3 response before it becomes the
  item, `_hydrate[*].data`, or `configuration`. It carries request ids, retry
  counts, and timestamped headers; retaining it would change `configuration`
  every run on an unchanged resource, churning idempotent upsert and polluting
  History/FLIP.
- The engine serializes deterministically (manifest/sorted key order plus the
  ISO 8601 datetime rule above). Combined with `ResponseMetadata` stripping, an
  unchanged resource yields byte-identical `configuration` — clean re-runs, no
  false History entries, protecting the "re-run live in the demo" and
  audit-evidence properties.

**Per-entry configuration persistence (decided 2026-09-23).**
`configuration` does two jobs: it is the raw boto3 response kept as future audit
evidence, and it is where everything that does not fit a typed field lives —
hydrate posture (`_hydrate`: S3 encryption, versioning, public-access block,
policy), `custom_fn` additions, `_source` provenance. A blanket halt (the first
design on this PR) lost the second job to protect the first, so persistence is
decided per resource type instead.

Every manifest entry declares `persist_configuration` (boolean) and
`persist_configuration_why` (non-empty string), both required by the schema.
The reason is required when the flag is true as well as false: every other
decision in the manifest carries a `why` (`req-aws-collector-manifest-5`), and a
persisted entry that lists a credential location must say so there (see
[Response Sensitivity Declaration](#response-sensitivity-declaration)).

The cut is at the GRIFT emit: `node_envelope` takes `persist_configuration` as a
required keyword with no default, and the collector passes the entry's flag. The
engine builds the full envelope in memory either way, so typed fields, tags,
hydrate-gap warnings and edges are derived identically; a `false` entry emits
`configuration: {}`. `{}` is sent explicitly, not omitted, so the replace on
import is deterministic — a resource stored before its entry was turned off has
its configuration replaced with `{}` the next time it is collected. No migration
and no model change. History rows are left as they are (the data so
far is synthetic or drawn from open repositories).

Off, as shipped, each with a reason naming the credential location:
`aws_core__aws_lambda` (`Environment.Variables`), `aws_core__aws_cloudfront_distribution`
(`Origins.Items[].CustomHeaders.Items[].HeaderValue`),
`aws_core__aws_apigateway_http_api` (`_integrations[].RequestParameters`),
`aws_core__aws_cognito_user_pool` (`SmsConfiguration.ExternalId`). For those
four types the grid holds only typed fields, tags and edges; nothing downstream
reads the stored blob. Every other entry persists its full configuration.

**Security facts kept as typed fields.** Turning
storage off for those types dropped three security facts that had lived only in
the stored blob. Each is now a typed field, derived from data the collector
already fetches (no new AWS call), so it survives with configuration `{}`:

| Type | Field | Source | Value |
| --- | --- | --- | --- |
| `aws_core__aws_lambda` | `vpc_subnet_ids`, `vpc_security_group_ids` | `ListFunctions` `VpcConfig.SubnetIds[]` / `VpcConfig.SecurityGroupIds[]` | Lists of ids; both `[]` means the function is not in a VPC. |
| `aws_core__aws_cloudfront_distribution` | `origin_access` | `ListDistributions` origins, derived by `cloudfront_distributions_with_oac` as `_origin_access` | `{origin Id: "oac" \| "oai" \| "none"}`: a non-empty `OriginAccessControlId` is `oac`, a non-empty `S3OriginConfig.OriginAccessIdentity` is `oai`, neither is `none`. `none` means only "no OAC or OAI". It does not mean the origin is public: a custom origin may still check a shared-secret header (`CustomHeaders`, the credential location that keeps this type off), whose presence `origin_custom_headers_present` records. |
| `aws_core__aws_cloudfront_distribution` | `origin_custom_headers_present` | `ListDistributions` origins, derived by `cloudfront_distributions_with_oac` as `_origin_custom_headers_present` | `{origin Id: bool}`: `true` when `CustomHeaders.Items` is non-empty or `CustomHeaders.Quantity` is positive, otherwise `false`, an observed absence. **Presence only, never the value**: a header value is the credential that keeps this type off, and the header name is not kept either. `null` only on a row not collected since migration 0008. |
| `aws_core__aws_apigateway_http_api` | `route_authorization_types` | `GetRoutes`, derived by `apigateway_http_apis_detailed` as `_route_authorization_types` | `{RouteKey: AuthorizationType}`, AWS's values passed through: `NONE`, `AWS_IAM`, `JWT`, or `CUSTOM` (a Lambda authorizer); a route that omits it is `NONE`, the AWS default. `null` when `GetRoutes` failed, so a denied listing never reads as "no open routes". |

These are fields, not edges. `aws_core` has no Lambda-to-subnet or
Lambda-to-security-group edge type, and it does not collect subnets or security
groups, so an edge to them would be dropped by the v0 fence
(`req-aws-collector-edges-6`). Nothing else from those types' responses is
promoted; `aws_core__aws_cognito_user_pool` gains no field.
`origin_custom_headers_present` was added later (2026-09-24)
and is the one field here read from a credential location: it records that a
custom origin header exists, never what it says.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-field-projection-1#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-field-projection-1 | Declared Field Mapping | Approved for Development | Typed fields are populated from manifest jsonpaths. | |
| req-aws-collector-field-projection-2 | Graceful Missing | Approved for Development | An unresolved jsonpath yields `null`, never a run failure. | |
| req-aws-collector-field-projection-3 | Lossless Payload | Approved for Development | The full raw item is retained in the in-memory `configuration` envelope; it is persisted when the entry's `persist_configuration` is true (`req-aws-collector-field-projection-7`). | |
| req-aws-collector-field-projection-4 | No Silent Coercion | Approved for Development | Values are passed through; model/service-layer validation is the sole gate. | |
| req-aws-collector-field-projection-5 | One Canonical Timestamp | Approved for Development | All date input shapes normalize at collection into one ISO 8601 UTC envelope field; "created/updated after X" is one query, never per-resource spelunking. | Grid-native time is the always-present spine; AWS-source time is null where AWS omits it. |
| req-aws-collector-field-projection-6 | Reserved Keys & Stable Blob | Approved for Development | `_source`/`_hydrate`/`_hydrate_mapping` are engine-reserved (not authored jsonpath targets); `ResponseMetadata` stripped; deterministic serialization ⇒ unchanged resource = byte-identical `configuration`. | Protects idempotent upsert + History/FLIP. Reserved keys are in-memory only for an entry whose `persist_configuration` is false. |
| req-aws-collector-field-projection-7 | Per-Entry Configuration Persistence | Approved for Development | Each manifest entry's required `persist_configuration` boolean and non-empty `persist_configuration_why` decide whether the emitted node payload carries the in-memory envelope or `{}`; typed fields, tags and edges are unchanged either way; every entry is `true` (`req-aws-collector-redaction-1`): a credential location no longer turns persistence off, it is removed from the stored copy (`req-aws-collector-redaction-2`); no model field is removed and no migration is written. | `tests/test_boto3_collector_batch.py`, `tests/test_boto3_collector_slice.py::test_secret_material_is_removed_and_the_rest_is_stored`, `::test_flag_is_what_stores_the_response`, `tests/test_boto3_collector_sensitivity.py`. |
| req-aws-collector-redaction-1 | Everything Is Stored | Proposed | Every manifest entry has `persist_configuration: true`: a node's `configuration` carries the whole response, `_source`, `_hydrate` and `_hydrate_mapping`, less what `-2` and `-3` remove. | A test fails if any entry is off. The size and import time are measured on a full run. |
| req-aws-collector-redaction-2 | Declared Secret Paths Are Removed | Proposed | A `sensitivity.locations` entry with `redact: true` names a path (the manifest's path dialect, `[]` to flatten) that is removed from the stored configuration. Only `credential` locations may be redacted. Every location AWS marks sensitive is redacted except four named non-secrets (an app client id, two claim names, a directory account name). | `tests/test_boto3_collector_sensitivity.py`: a canary planted at every redacted path of every entry is absent from what is stored. |
| req-aws-collector-redaction-3 | Secret-Named Keys Are Scrubbed | Proposed | Any string value whose key names a secret is removed from every stored configuration, wherever it sits, unless the key is a reference, a flag, a date, a URL or a number. | `tests/test_boto3_collector_redaction.py`. A net for what no location declares; the list of removed paths is `_redacted`. |
| req-aws-collector-redaction-4 | Only Secrets | Proposed | Operator-authored content (tags, names, descriptions, comments, policies, personal data) is stored. | Test: representative content passes through unchanged. |
| req-aws-collector-enrich-1 | Detail Enrichment | Proposed | An entry whose list call returns a summary and whose Describe/Get call returns more carries an `enrich` block `{op, params, why}`: one read call per listed resource, parameters taken from the listed item, the response stored under `configuration._hydrate.detail` with the status of any hydrate slot (`ok`, `absent`, `denied`, `error`; a refused call is a `HYDRATE_GAP`). Secret members of the detail response are declared as `_hydrate.detail.data.<path>` redact locations and removed before storage (`req-aws-collector-redaction-2`). The detail op must be a Get/Describe read that names no secret, and every required input must be supplied. 104 types are enriched; 32 are listed in the PR as not mappable. | `tests/test_boto3_collector_enrich.py`. |
| req-aws-collector-tags-17 | Untaggable Refusal Is An Answer | Proposed | A tag read the service refuses because the resource cannot hold tags (an AWS-owned object) is the outcome `not_taggable`, named by a reviewed row of `error_outcomes.json` (service, operation, error code and message text), authored from an observed refusal: the node's tags are `{}`, the slot records `not_taggable` with the error code, and no `HYDRATE_GAP` is raised. A refusal because the resource is shared in from another account is `not_readable`: the owner's tags may exist and are not visible, so the tags stay unread (not `{}`), the slot records `not_readable`, and no gap is raised. A refusal no row names stays a failed read. | `tests/test_gap_sweep.py`. |
| req-aws-collector-ledger-4 | Ledger Keeps The Error Code | Proposed | Each call-ledger entry carries the `error_code` of a refused call (null for a call that answered), so an outcome can be named from the ledger without re-running the call. | `tests/test_gap_sweep.py`. |
| req-aws-collector-edges-8 | Reference Edges For Exposure | Proposed | The manifest declares an edge for each reference the exposure work follows: ElastiCache cluster to its subnet group and the group to its subnets; network interface to its subnet and instance; EBS volume to its instance; Auto Scaling group to its instances and launch template; security group rule to its group and to the group it references; RDS snapshot to its database; Network and Gateway load balancer listener to its load balancer by DNS name. `ROUTES_TRAFFIC` is written from load balancers to the instances and functions in their target groups and from hosted zones to the load balancers their aliases name, with a plain identity. | `tests/test_gap_sweep.py`; checked live against a seeded GovCloud stack (`tools/seed/wave4-gapsweep`). |
| req-aws-collector-iam-policy-1 | Generated Collector Policy | Proposed | The IAM policy the collector needs is generated, not hand-written: the inventory is every operation the manifest names (list, parent, tag, hydrate, detail) plus the operations the collector's Python makes, mapped to IAM actions through AWS's Service Authorization Reference (overrides for the few that differ), written as customer-managed policy documents of at most 6,000 characters each with an explicit `Deny` on actions that return secret values or a resource's contents. The committed documents must equal the generator's output, every inventory operation must be granted, no write verb may appear, and no granted action may be denied. Operations whose action name is only the default `<prefix>:<Operation>` are listed by `unverified()` until a live round trip with the role. | `tests/test_iam_policy.py`. |
| req-aws-collector-field-projection-8 | Off-Type Security Facts Kept | Approved for Development | For entries whose `persist_configuration` is false, the Lambda VPC attachment (`vpc_subnet_ids`, `vpc_security_group_ids`), CloudFront per-origin access mode (`origin_access`) and API Gateway HTTP API per-route authorization type (`route_authorization_types`) are typed fields derived from data already fetched; configuration stays `{}`. | Migration 0007. `tests/test_boto3_collector_slice.py::test_promoted_security_facts_land_while_configuration_stays_empty`, `tests/test_boto3_collector_customfns.py::TestCloudfrontDistributionsWithOac::test_origin_access_mode_per_origin`, `tests/test_boto3_collector_new_service_types.py::TestApiGatewayHttpApisDetailed`. |
| req-aws-collector-field-projection-9 | CloudFront Origin Header Presence | Approved for Development | Each CloudFront origin's custom-header presence is the typed field `origin_custom_headers_present` (`{origin Id: bool}`), derived from the `ListDistributions` origin with no extra call; an origin without headers is `false`, not absent or `null`; no header value or name reaches the field, the GRIFT batch, the stored row or its history. | Migration 0008 (additive `AddField` only). `tests/test_boto3_collector_slice.py::test_origin_header_presence_lands_and_the_value_never_does`, `tests/test_boto3_collector_customfns.py::TestCloudfrontDistributionsWithOac::test_custom_header_presence_per_origin`. |

### Identity By Natural Key
----
RID: `req-aws-collector-identity`

Status: `Approved for Development`

Every collected node and edge is identified by what it is, never by an id this collector makes
up, so repeated collection runs update in place rather than duplicating — the property that makes
"re-run the collector live in the demo" safe — and a resource deleted on the grid and seen again
is simply created again. Core owns the ids (`req-grid-entity-natural-key`,
`req-grid-edge-identity`); the collector only names things.

#### Implementation

- A node is sent with a batch-local `ref` (`<entity_type>:<natural_key>`) instead of an
  `entity_id`, carrying its model's declared `NATURAL_KEY` fields in the payload. Core's
  `resolve_identity` finds the live row those fields name, under an advisory lock, or assigns a
  UUIDv7 on first sight (`req-grid-import-grift-identity-3`). The collector mints no node id.
- The natural key is the value at the manifest's `natural_key` jsonpath, and it is the field the
  model declares as its `NATURAL_KEY` (`req-aws-core-fields-7`). Preference order, declared per
  entry: the resource **ARN** where one exists (the dominant case — Lambda, IAM role, ACM,
  EventBridge, CloudFront, S3, CloudWatch log group); otherwise the stable AWS **resource id**
  (e.g. a hosted-zone id, a subnet id). The log group's key is its ARN without the `:*` suffix; how
  the `WRITES_LOGS` referrers reach it is in
  [v0 Make-It-Work: Mutually-Available Natural Keys](#v0-make-it-work-mutually-available-natural-keys).
  The readers that are not manifest-driven (Organizations, landing zone, findings) send the same
  shape, and some of their types declare composite keys (`(account_id, region_code)` for the
  footprint, `(organization_id, account_id, service_principal)` for a delegation, and others).
- An edge is sent with a `ref` too and is found by its type's declared identity
  (`req-grid-edge-identity`; every aws_core edge type declares the plain key, `{"discriminators":
  []}`, except `ROUTES_TRAFFIC`). An endpoint naming a node the same batch carries is a `from_ref` /
  `to_ref`; any other endpoint names its node by type and natural key (`from_key` / `to_key`),
  which core resolves against the batch, then the live grid, and never mints
  (`req-grid-import-grift-edge-endpoints`). Only a node keyed on one field can be named that way;
  a composite-key endpoint is always a node of the same batch.
- An edge type that declares no identity (`ROUTES_TRAFFIC`, whose identity aws-core-tap#64
  settles) cannot be sent by ref: core would create a ref-addressed edge of it afresh on every run.
  It keeps the explicit id it always had, `uuid5(NAMESPACE_AWS_COLLECTOR,
  f"edge:{edge_type}:{from_key}->{to_key}")`, so existing rows are replaced in place. When either
  end was deleted, core ended that edge and its id is tombstoned; re-sending it would fail the batch
  (`entity_tombstoned`), so the run leaves it out with an `UNDECLARED_EDGE_RETIRED` warning. It
  returns once the type declares its identity. The run asks tap's `entity_liveness`
  (`req-grid-service-read-direct-4`, one read under the collector's own `grid.read`) about every
  such id: only `tombstoned` is left out; `missing` is the edge's first sight and is sent.
- Before the batch is assembled, the run checks every node's declared key: a part that is absent,
  null or empty fails the run (`IDENTITY_INCOMPLETE`), because core's search finds nothing on a
  null part and would create the node again every run. It keeps one node per identity (two refs
  for one source object fail a batch, `duplicate_entity_id`) and one edge per (type, endpoints,
  discriminators) (`duplicate_edge`).
- A completeness surface (`req-grid-reconcile-evidence`) names its parent by ref while the run
  reads; once the batch has imported, the subject becomes the grid id core resolved that ref to,
  read from the import result (`resolved_refs`). A parent the batch did not carry keeps its ref,
  which is its source locator, and candidate derivation reads it as unresolved.

Edges no longer depend on collection order or on recomputing a hash: an edge to a node collected
in an earlier run resolves to that row; an edge whose target is not on the grid at all is skipped by
GRIFT's permissive dangling-edge mode and recorded as a `skip` event the run record lists.

Collected nodes therefore no longer carry the same id on every grid: each grid assigns its own
(intended, per the edge epic Issue# 911 - tap; shared seed nodes such as regions keep their fixed ids). Rows a grid already
holds from before this change keep their `uuid5` ids, because they are found by key, not by id.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-identity-1 | Found By Natural Key | Implemented | A node is sent by `ref` with its declared natural-key fields, never with an id the collector derived; core finds its live row or assigns a UUIDv7. The same AWS resource is the same row on every run of one grid. | `tests/test_natural_key_refs.py::test_a_rerun_keeps_every_id_and_adds_no_edge`, `::test_rows_written_under_uuid5_ids_are_found_not_duplicated`. |
| req-aws-collector-identity-2 | ARN-Preferred Key | Approved for Development | Natural key is the ARN where available, else the stable resource id. `aws_cloudwatch_log_group` is keyed by its ARN without the `:*` suffix (`logGroupArn`), so same-named groups in two regions or accounts are two nodes. | Was keyed by `logGroupName` until tap-plugin-aws-core#60; a group re-keyed then is a new row. |
| req-aws-collector-identity-3 | Edges By Identity | Implemented | An edge is sent by `ref` and found by its type's declared identity; each endpoint is a ref to a node of the batch or the node's type and natural key, resolved by core and never minted. An edge type with no identity declaration keeps its explicit `uuid5` id, and is left out with a warning when that id is tombstoned. | `tests/test_boto3_collector_batch.py::TestAddressBatch`, `tests/test_natural_key_refs.py::test_an_endpoint_the_batch_does_not_carry_resolves_to_the_row_on_the_grid`, `::test_an_edge_type_with_no_identity_keeps_its_uuid5_id_across_runs`, `::test_an_undeclared_edge_ended_on_the_grid_is_left_out_not_a_wedge`, `::test_retired_ids_are_asked_of_the_grid_read_service_and_a_missing_id_is_sent`. |
| req-aws-collector-identity-4 | Idempotent Re-Run | Implemented | Re-running collection updates in place; it never duplicates nodes or edges. | `tests/test_natural_key_refs.py::test_a_rerun_keeps_every_id_and_adds_no_edge`. |
| req-aws-collector-identity-5 | An Incomplete Key Fails The Run | Implemented | A node whose declared key has an absent, null or empty part, or an edge naming a composite-key node the batch does not carry, fails the run with `IDENTITY_INCOMPLETE` before anything is submitted; nothing is minted. | `tests/test_natural_key_refs.py::test_a_node_with_a_hole_in_its_key_fails_the_run_and_writes_nothing`, `tests/test_boto3_collector_batch.py::TestAddressBatch`. |
| req-aws-collector-identity-6 | A Deleted Resource Returns | Implemented | A resource tombstoned on the grid and collected again is written as a new row under the same natural key; the tombstone is left alone, the batch succeeds, and the edges that named the resource follow the new row. | aws-core-tap#14. `tests/test_natural_key_refs.py::test_a_tombstoned_resource_returns_with_a_new_id_and_the_batch_does_not_wedge`. |
| req-aws-collector-identity-7 | Completeness Subjects Are Grid Ids | Implemented | A completeness surface's subject is the grid id its parent's ref resolved to in the imported batch; a parent the batch did not carry keeps its ref as the source locator. | `tests/test_natural_key_refs.py::test_a_tombstoned_parent_is_the_new_id_in_its_completeness_surface`, `tests/test_boto3_collector_batch.py::TestResolveSubject`. |

### Declarative Edge Rules
----
RID: `req-aws-collector-edges`

Status: `Approved for Development`

Relationships are materialized from declarative edge rules in the manifest entry,
each endpoint named by natural key. The probe established ~80% of valuable edges
are expressible this way.

#### Implementation

An edge rule declares:

| Key | Meaning |
| --- | --- |
| `value_path` | jsonpath into the item yielding the target's natural key — a scalar **or** a list. A list produces fan-out (one edge per element); this covers the common many-target case (e.g. an instance's network interfaces). |
| `target_type` | The target `aws_core` entity type. |
| `key_kind` | `arn` \| `id` \| `name` — declares which identifier space the target's natural key lives in. **Inert in the v0 engine**: it neither transforms nor interprets the extracted value. It is declared intent, consumed only by the backlogged [Edge Identifier Resolution](#edge-identifier-resolution-future-seam) seam. In v0, correctness rests entirely on `value_path` (+ optional `transform`) emitting *exactly* the target's `natural_key` value. |
| `edge_type` | An edge type already declared by `aws_core` (`req-aws-core-edges`). |
| `direction` | `outbound` (this node → target) or `inbound` (target → this node). |

The engine names the target by its type and the value the source side extracted, and emits the
edge ([Identity By Natural Key](#identity-by-natural-key)). It does **not** verify the target was
collected, and it does **not** consult `key_kind`; core resolves the endpoint, against this batch's
nodes, then the live grid (`req-grid-import-grift-edge-endpoints`). The honest consequence: an edge
connects **iff the source side's `value_path`(+`transform`) output equals the target's natural
key**. When they match (ARN→ARN: `ASSUMES_ROLE`, `RETRIEVES_CERT_FROM`; transform→ARN:
`RETRIEVES_CONTENT_FROM`) the edge resolves with no lookup in the collector and no ordering
dependency. When they *cannot* match — the source carries only a name/domain and the target's ARN
needs account/region/suffix the source item lacks, or a cross-resource join — the endpoint names no
live node: core skips the edge and records a `skip` event, which the run record lists
(`GRIFT_EDGES_SKIPPED`), so the miss is visible rather than silent. Nothing is ever created for an
endpoint. v0 closes the gap by the manifest discipline below; the durable fix is the backlogged
[Edge Identifier Resolution](#edge-identifier-resolution-future-seam) seam.

#### v0 Make-It-Work: Mutually-Available Natural Keys

Because the engine resolves an endpoint only by its exact natural key in v0
(not by any other identifier the target carries), every edge that must connect
for the demo is made to satisfy the "both-ends-derive-the-same-string" invariant **by manifest choice alone — no
engine change**: pick a `natural_key` for the target that the edge-emitting
source side already carries verbatim.

The log group was once the exception: it was keyed by `logGroupName` so that a
Lambda's `WRITES_LOGS` `value_path` (`LoggingConfig.LogGroup`, a bare *name*)
and the log-group node derived the same string. A name is unique only within
one account and region, and a region scope of more than one region breaks that
(the same name in `us-gov-west-1` and `us-gov-east-1` was one identity, and the
second was dropped as `DUPLICATE_IDENTITY`). So **`aws_cloudwatch_log_group` is
keyed by its ARN without the `:*` suffix** (`logGroupArn`,
`arn:<partition>:logs:<region>:<account>:log-group:<name>`), like every other
ARN-bearing type. Both referrers reach that key through one declared transform,
`log_group_arn`: a trail's `CloudWatchLogsLogGroupArn` drops its `:*`; a
Lambda's bare name takes partition, region and account from the Lambda's own
ARN (its natural key — a Lambda can only log to a group in its own account and
region). That is a *source-aware* transform: the engine hands it the referring
node's natural key as well as the value. Re-keying makes every log group a new
row; nodes keyed by name on an existing grid are not rewritten or retired by the
collector (`req-aws-collector-scope-3`) and remain until reconciled or purged.

This spec defines the edge *mechanism* only. It introduces no new edge *types*;
edge-type and target-model selection for specific relationships is `aws_core`
model/edge work governed by `spec-aws-core-v0` (`req-aws-core-edges`). Edges
whose target key is not directly present in the item (derived keys — e.g.
matching a Route 53 alias to a CloudFront distribution by domain rather than
ARN) are supported via a small declared transform on `value_path`; edges that
require parsing an embedded IAM/resource policy document are **out of v0 scope**
and routed to the deferred policy-document resolver (`req-aws-collector-nongoals`).

**Two-phase application.** All nodes are emitted first, then edges in a separate
pass — nodes, then edges. Because endpoints are named by natural key and core
resolves them, the edge pass needs no per-target lookup. An edge whose `target_type` is not a
resource type this collector models/collects (an expected condition under the v0
fence — e.g. a reference to a not-yet-modeled service) is **dropped with a
recorded `warn`, never a run failure**; the edge pass is the single chokepoint
for that check rather than scattering it. An edge to a modeled type whose
specific instance was not collected this run is a dangling edge governed by
GRIFT's `dangling_edge_mode`; the AWS collector uses the mode that skips rather
than fails: the endpoint resolves to the target's row when an earlier run wrote
it, and otherwise the edge is skipped and recorded, and a later run that collects
the target writes it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-edges-1 | Declarative Rules | Approved for Development | Edges are emitted from manifest rules; the engine has no per-relationship code. | |
| req-aws-collector-edges-2 | Scalar And Fan-Out | Approved for Development | `value_path` supports scalar and list extraction; a list yields one edge per element. | |
| req-aws-collector-edges-3 | Identity-Resolved | Implemented | Edge endpoints are named by natural key and resolved by core against the batch, then the live grid, independent of collection order; an endpoint naming no live node skips the edge with a recorded `skip` event and never creates a node. | `req-grid-import-grift-edge-endpoints`. `tests/test_natural_key_refs.py::test_an_endpoint_that_names_nothing_is_skipped_and_recorded_never_minted`. |
| req-aws-collector-edges-4 | Existing Edge Types Only | Approved for Development | Edge rules reference edge types already declared by `aws_core`; no new edge types are defined here. | |
| req-aws-collector-edges-5 | Policy Edges Excluded | Approved for Development | Edges requiring policy-document parsing are not emitted in v0. | Deferred resolver, named seam. |
| req-aws-collector-edges-6 | Two-Phase, Unmodeled-Safe | Approved for Development | Nodes are emitted before edges; an edge to an unmodeled `target_type` is dropped with a `warn`, never a failure; uncollected modeled targets follow GRIFT dangling-edge mode. | Single chokepoint for the v0-fence gap. |
| req-aws-collector-edges-7 | Mutually-Available Natural Keys (v0 make-it-work) | Approved for Development | v0 has no identifier resolver of its own: core finds an endpoint by its exact natural key only, so an edge connects iff both ends derive the byte-identical `natural_key`. Every demo-required edge satisfies this by manifest choice alone. `aws_cloudwatch_log_group` is keyed by its ARN, and both `WRITES_LOGS` referrers reach it through the `log_group_arn` transform (a Lambda's bare log-group name takes region and account from the Lambda's own ARN, handed to a source-aware transform). `key_kind` stays truthful but inert. | Deliberate, documented; durable fix is the backlogged `req-aws-collector-edge-resolver` seam. |
| req-aws-collector-edges-9 | Edge Properties From Object Values | Implemented | A rule whose `value_path` yields objects names `key_path`, where in each object the target's key is, and may name `properties_path`, where the edge's properties are; the edge carries those properties. A value that is not an object, or whose key is absent or empty, makes no edge. A rule without `key_path` behaves as before and sends empty properties. | aws-core-tap#220: one relationship carries what decides it (the listener rule on a load balancer's edge to a target group). `tests/collectors/test_boto3_collector_edges.py::TestObjectValues`. |
| req-aws-collector-edges-10 | Discriminated Edge Refs | Implemented | An edge whose type declares discriminators has their values in its batch ref, in the envelope the edge pass writes and in the one the batch re-addresses, so two edges of one pair that differ in a discriminator are two edges and neither replaces the other in the batch. A plain-key edge's ref is unchanged. | `req-grid-edge-identity-declaration`. `tests/collectors/test_boto3_collector_edges.py::TestObjectValues`. |

### Progressive Upload (Future Seam)
----
RID: `req-aws-collector-progressive-upload`

Status: `Backlog`

Backlogged on George's request, 2026-11-04. Nothing here is built or approved. Today a run reads everything, then
submits **one** GRIFT batch (`address_batch`, `assemble_batch`, `submit_grift`). The question was whether rows could
reach the grid as the run works. The full collection of 2026-11-04 took 676 seconds, 643 of them reading and 31 of them
importing about 1,200 nodes and 1,600 edges (measured in the stack on that date; no run record is committed), so the case rests on
visibility and on what a failure loses, not on import time today.

**Two directions, not exclusive.**

1. **Split by phase.** Nodes, then edges, then the completeness statement and edge authority. The cheapest cut. It keeps
   one statement of completeness, written once after the last batch, and makes the edge ordering explicit (an edge
   whose far end is not in its own batch is sent by key and skipped by core if that node does not exist yet).
2. **Self-contained units.** Reorganise collection so that a unit (a service, a service in a region, a group of
   entries that depend on one another) carries its nodes, its edges and its completeness surfaces, and the manifest or
   the collector says when the unit is done, so it can be uploaded then. George's reasoning: AWS is organised by
   service and region, so a unit likely exists. **Not verified.** The cross-unit dependencies to find are edges between
   services (a Lambda to its IAM role), the per-account footprints every regional containment hangs from, the
   `per` parents some entries fan out from, the tag sweep that spans services (`shared_scopes`), and the account anchor.

**What a design has to settle** (the strengths and weaknesses weighed on 2026-11-04):

- **Edges depend on nodes.** Order or a later pass, as above.
- **Completeness is recorded against the batch that carries a listing's observations.** A half-uploaded run must not
  state completeness it has not earned; the statement is written when the last unit is in.
- **Retirement candidates and edge authority** are only sound once a whole listing is known, so they cannot go early.
- **Identity** is deduplicated across the run (`duplicate_entity_id` is batch-fatal at import), so splitting needs the
  seen-set to span batches.
- **A crash leaves a partial, mixed-age grid** where today it leaves nothing. A unit that fails must say so.
- **More batches** are more writes and more audit records. The collection job already links several
  (`PRODUCED_BATCH` carries a disposition per batch); how core treats several batches in one run, and what the
  importer needs to be told, has to be read before approval.
- **Alternatives that need no upload change:** the progress lines (`req-aws-collector-progress`), and a read-only "nodes
  so far by type" count.

#### Requirements

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-progressive-upload-1 | Phased Batches | Backlog | A run submits its nodes, then its edges, then its completeness statement and edge authority, as separate batches, and states completeness only after the last. | Direction 1. |
| req-aws-collector-progressive-upload-2 | Units Declare Completion | Backlog | The manifest or the collector names the self-contained units of a run and declares each complete; a complete unit is uploaded with its nodes and edges, and with the completeness surfaces of the listings it contains whole. A listing that more than one unit contributes to (the tag sweep, the per-account footprints, a `per` parent) is stated complete, and its retirement candidates and edge authority are written, only when the last unit that contributes to it is in; a run that stops early states no completeness for a listing an unfinished unit contributes to. | Direction 2; needs the dependency survey above. Read with the constraints above: completeness is never stated for a part of a listing, so no unit can authorise retirement by itself. |

### Edge Identifier Resolution (Future Seam)
----
RID: `req-aws-collector-edge-resolver`

Status: `Backlog`

The durable fix for the fragility `req-aws-collector-edges-7` papers over by
manifest discipline. v0 names an edge's target by the exact value the source
carries, and core finds the target only by that natural key. A source that can
only name its target by name/domain while the target is ARN-keyed names no live
node — the edge is skipped and recorded, not resolved — and `key_kind`, the field
that exists to express exactly this, is inert.

Two parts of the original design are now core's and are no longer this seam's to
build. Ids are assigned by core, not derived here
([Identity By Natural Key](#identity-by-natural-key)), so there is no `uuid5`
allocator to keep under a resolver. And the grid is the resolution index: an
endpoint named by natural key is resolved against the batch, then the live grid
(`req-grid-import-grift-edge-endpoints`), so an edge to a node collected in a
prior run resolves, and a miss is a recorded `skip` event rather than a silent
dangling edge. What remains is the translation between identifier spaces: with
the run's nodes in memory before batch assembly,

1. Index the collected nodes by their standard identifiers (ARN, resource id,
   name) per `target_type`.
2. For each edge rule, resolve the target in that index using the identifier
   the source actually carries — **`key_kind` becomes the live input** that
   selects which identifier space to match in (`arn` \| `id` \| `name`).
3. Three outcomes:
   - **(a) resolved** — name the resolved node by its natural key.
   - **(b) supported `target_type`, not found** — name it as the source does
     and let core's grid lookup decide; a miss is recorded as a `skip` event.
   - **(c) unsupported `target_type`** — already handled today (`warn` + drop,
     the v0 fence — `req-aws-collector-edges-6`); the resolver subsumes it.

Converges conceptually with the grid **hotlink** identifier-resolution model (a
node findable by any of its identifiers); design that alignment in-spec first
if/when built. Demand-signal-gated, not built. A grid read for a *different*
identifier than the declared natural key (a name, say) would make the batch
depend on grid state beyond the key lookup core already does; record that
tradeoff against [Audit Verifiability](#audit-verifiability) when it is built.
Reconciliation and tombstoning share the grid-read primitive — see the
grid-state reconciliation seam (`req-aws-collector-reconcile`) under
[v0 Non-Goals](#v0-non-goals).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-edge-resolver-1 | Seam Named, Not Built | Backlog | The pre-batch identifier-translation pass (collected-node index keyed by standard identifiers; `key_kind`-driven target lookup; resolve / grid-decides / unsupported-drop) is specified here as the durable replacement for `req-aws-collector-edges-7`'s manifest workaround. Not implemented in v0. | The three-case model. |
| req-aws-collector-edge-resolver-2 | uuid5 Retained As Allocator | Superseded | Superseded by `req-aws-collector-identity`: the collector derives no node id; core assigns them. | The only `uuid5` left is the explicit id of an edge type with no identity declaration. |
| req-aws-collector-edge-resolver-3 | Misses Are Observable | Implemented | A target that names no live node skips its edge with a recorded `skip` event the run record lists, never a silent dangling edge. | By core: `req-grid-import-grift-edge-endpoints-7`, `-8`. |
| req-aws-collector-edge-resolver-4 | Grid Is The Backstop | Implemented | The resolution index is the grid: an endpoint named by natural key resolves against the batch, then the live grid, through core's generated search. | By core: `req-grid-import-grift-edge-endpoints-2`. |

### Fan-Out Hydrate Seam
----
RID: `req-aws-collector-hydrate`

Status: `Approved for Development`

The first of the two named seams. A reusable, manifest-parameterised template
for the AWS resources that have no single rich describe call and instead require
a per-item fan-out of secondary calls (confirmed worst case: S3, where
`ListBuckets` returns four fields and ~9 independent `GetBucket*` calls supply
everything else).

#### Implementation

The hydrate template is a single engine helper a `custom_fn` composes. Given an
enumerate operation and the manifest's declared `hydrate` list, for each
enumerated item it calls each hydrate op with the item's identifier and assembles
one **self-describing configuration envelope** on the node. The enumerate item is
the envelope root; hydrate output and its explanation are two reserved siblings:

- `_hydrate` — the **event record**. Per declared slot key:
  `{ "status": <ok|absent|denied|error>, "op": <aws op>, "data": <verbatim
  response> }` on success, or `{ "status": …, "op": …, "error_code": <aws code> }`
  when the call returned no data. `data` is the full response verbatim
  (losslessly, per slot) with `ResponseMetadata` stripped (see [Field
  Projection](#field-projection)).
- `_hydrate_mapping` — the **intent**. Per slot key:
  `{ "op": <aws op>, "why": <manifest rationale> }`, materialized from the
  manifest at collection time, embedded per-node (deterministic, tiny next to
  `data`) so a grid object is legible **without** the manifest. The batch
  independently records manifest version / account / regions; the per-node
  mapping is what makes a single object self-explanatory.

Slot `status` is the load-bearing distinction:

- `ok` — call succeeded; `data` present.
- `absent` — AWS's "not configured" signal (`NoSuchBucketPolicy`,
  `NoSuchWebsiteConfiguration`, `…NotFoundError`). A real, queryable fact: the
  resource genuinely has no such configuration.
- `denied` — `AccessDenied` / authorization failure. Value unknown — recorded as
  a structured `warn`. **Never conflated with `absent`**: "no policy" and "could
  not read the policy" are opposite compliance conclusions, and the KSI
  scoreboard depends on telling them apart.
- `error` — unexpected / throttle-exhausted. Swallowed → `warn`; the node is
  still collected, partially hydrated.

`absent`/`denied`/`error` are swallowed independently per op, so one missing
sub-config never fails the resource. Node identity is always taken from the root
enumerate item (`req-aws-collector-identity`), never a hydrate slot — a fully
denied hydration still yields a stable, correctly-identified node.

The template is written once. Adding an S3-like resource is a manifest `hydrate`
list, not new Python. This is the mechanism by which even the worst-case
collection class stays declarative.

v0 builds the template and exercises it for S3, with S3's hydrate list fenced to
the minimum the demo needs (existence + region + the small set of
compliance-relevant sub-configs the KSI scoreboard reads). Broad S3
sub-configuration is deferred.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-hydrate-1 | Single Template | Approved for Development | One reusable hydrate helper exists; per-item multi-call code is not duplicated per resource. | |
| req-aws-collector-hydrate-2 | Independent Sub-Call Resilience | Approved for Development | Each hydrate sub-call's `NoSuch*`/`AccessDenied`/absent result is swallowed independently and recorded as `warn`. | |
| req-aws-collector-hydrate-3 | Manifest-Driven Op List | Approved for Development | Adding a hydrated resource is a declared op-name list, not new engine code. | |
| req-aws-collector-hydrate-4 | S3 Fenced | Approved for Development | v0 exercises the template for S3 with a minimal hydrate op list. | Broad S3 sub-config deferred. |
| req-aws-collector-hydrate-5 | Hydrate Envelope | Approved for Development | Fan-out output is the `_hydrate` event-record map (per slot: `status`, `op`, verbatim `data` or `error_code`) on the enumerate-item root. | |
| req-aws-collector-hydrate-6 | Absent vs Denied Distinct | Approved for Development | `absent` (not configured) and `denied` (no permission) are distinct first-class statuses, never merged; the KSI reading depends on it. | |
| req-aws-collector-hydrate-7 | Self-Describing, No Manifest Needed | Approved for Development | `_hydrate_mapping` (slot → `{op, why}`, materialized from the manifest, embedded per-node, deterministic) makes a grid object legible without the manifest. | |

### S3 Bucket Size Metrics
----
RID: `req-aws-collector-s3-bucket-size`

Status: `Approved for Development`

Every `aws_s3_bucket` node carries `size_bytes` and `object_count` so the
grid distinguishes a four-object bucket from a four-million-object one —
and, via `size_bytes / object_count`, a pile of tiny objects from a few
large ones. Both feed the viz: a bucket node can be weighted by its
actual footprint instead of rendering identically regardless of contents.

#### Source — CloudWatch daily storage metrics, not object listing

The values come from the `AWS/S3` CloudWatch namespace (`BucketSizeBytes`,
`NumberOfObjects`), which S3 publishes automatically and free once per day.
One `get_metric_data` call per bucket — batching `NumberOfObjects`
(`AllStorageTypes`) and `BucketSizeBytes` across every storage tier — gets
both. The rejected alternative is summing `list_objects_v2`: one call per
1000 objects, i.e. thousands of calls and (if objects were also nodes) a
grid-count explosion for a large bucket. CloudWatch is pre-aggregated; the
collector never enumerates objects.

`BucketSizeBytes` has no all-tiers rollup dimension — it is queried per
storage tier and the tiers that return data are summed, so a lifecycled
bucket (objects tiered to Glacier etc.) reports a complete total. The
CloudWatch call lives inside the `s3_buckets_hydrated` custom_fn, which
already resolves each bucket's region per-bucket; the CloudWatch client is
bound to that region.

#### Data currency — the shortcut is disclosed, machine-readably

CloudWatch storage metrics are daily, with up to ~24–48h publish lag, so
`size_bytes` / `object_count` are not real-time. Rather than estimate the
staleness, the collector surfaces the exact `Timestamp` of the CloudWatch
datapoint the values came from, as `size_observed_at` (ISO 8601). A
consumer computes `now − size_observed_at` and knows the currency
precisely. The **absolute timestamp is stored; the age is always derived
at read time, never stored** — a stored age is wrong one second later
(same discipline as the docs `last-edited` rule).

`size_observed_at` is **data currency** — what wall-clock moment the value
reflects — and is deliberately distinct from FLIP write provenance (which
collector / batch wrote the field). The collector ran today; the value
reflects yesterday's daily rollup. Conflating the two would be wrong.
This is the first instance of a currency-disclosure field. If a second
lagged-data consumer appears, generalizing the pattern — a standard
currency shape, or folding it into FLIP's adjacent axis — is the demand
signal; it is not pre-built here (future-seam discipline:
[[feedback-spec-before-mirroring-rules]]).

The per-field constants — "sourced from CloudWatch daily storage metrics,
granularity daily" — describe the *field*, not the *row*, and live in the
field schema (the registry-backed discovery surface), not duplicated on
every bucket row.

When CloudWatch has no datapoint for a bucket (new or just-emptied), all
three fields are empty/null and internally consistent: "unknown", never a
misleading "0 bytes".

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-s3-bucket-size-1 | Aggregate, Not Per-Object | Approved for Development | `size_bytes` + `object_count` come from CloudWatch `AWS/S3` storage metrics via one `get_metric_data` call per bucket; the collector never enumerates objects. | |
| req-aws-collector-s3-bucket-size-2 | All Storage Tiers Summed | Approved for Development | `BucketSizeBytes` is queried across every storage tier and the datapoints with data are summed; `NumberOfObjects` uses `AllStorageTypes`. | `BucketSizeBytes` has no all-tiers rollup dimension. |
| req-aws-collector-s3-bucket-size-3 | Currency Disclosed | Approved for Development | `size_observed_at` carries the CloudWatch datapoint's own timestamp; the consumer derives age, the collector never stores it. | Data currency — distinct from FLIP write provenance. |
| req-aws-collector-s3-bucket-size-4 | Unknown Is Not Zero | Approved for Development | A bucket with no CloudWatch datapoint reports empty/null fields, never a misleading 0. | |
| req-aws-collector-s3-bucket-size-5 | Non-Fatal | Approved for Development | A denied/failed CloudWatch call leaves the three fields empty/null; the bucket still collects. | Mirrors the hydrate-seam per-op resilience. |

### ECS Clusters, Tasks And Container Images
----
RID: `req-aws-collector-ecs`

Status: `Proposed`

The collector gathers ECS clusters, services, tasks and the containers inside each task, and records, per
container, the image reference and the image digest ECS reports. The digest is the join key to everything
known about a build: the SBOM published for an image, its attestation, and its vulnerability findings. Until
it is on the grid, "which build is this running task" has no answer there. Today `aws_ecs_cluster`,
`aws_ecs_service` and `aws_ecs_task` exist as models but no manifest entry populates them, and
`aws_ecs_task` has no image or container field (read, 2026-10-15, `models/ecs_task.py`, the 23-entry
manifest).

#### Implementation

**Calls (one walk, four `custom_fn`s).** The fan-out is made once per run and region by `walk_ecs` (`ecs.py`); `ecs_clusters_described`, `ecs_services_described`, `ecs_tasks_described` and `ecs_containers_described` each take their slice of it, because a manifest entry yields exactly one node type. A multi-call fan-out is what `custom_fn` is for
([Source Primitive](#source-primitive)). Per swept region: `ListClusters`, then `DescribeClusters`; per cluster
`ListServices` then `DescribeServices` (at most 10 per call), and `ListTasks` (once with
`desiredStatus="RUNNING"`, once with `desiredStatus="STOPPED"`) then one `DescribeTasks` sequence (at most 100
per call) over the running tasks and the held stopped ones, the Describe calls with `include=["TAGS"]`. Every paginated call is read to its end
([Every Paginated Call Read To Its End](#every-paginated-call-read-to-its-end)). A denied or failed
sub-call degrades that slot to unknown and never fails the run
([Fan-Out Hydrate Seam](#fan-out-hydrate-seam)).

**Image digest.** `DescribeTasks` returns, per container, `image` (the reference in the task definition,
which may be a movable tag) and `imageDigest` (what ECS resolved when it pulled). The collector stores both
verbatim and never resolves a tag itself: it makes no registry call. `imageDigest` is missing when ECS did
not report one (for example a container that has not yet pulled); that is stored as null, never as an empty
string (the hybrid nullable-field pattern, `req-aws-core-fields-3`: null is unobserved).

**Types.**

- `aws_ecs_container` (new, aws_core-owned, keyed on `container_arn`): `name`, `image`, `image_digest`,
  `runtime_id`, `last_status`.
- `aws_ecs_task` gains `cluster_arn`, `last_status`, `desired_status`, `started_at`, `platform_version` and
  `group` (the `service:<name>` string ECS sets for a service-launched task), and `stopped_at`,
  `stopped_reason` and `stop_code`, which are null until ECS reports the task stopped (`-15`).
- `aws_ecs_cluster`, `aws_ecs_service` and `aws_ecs_task` each gain the mandatory `tags` field. They have none
  today, and the collector writes `tags` on every node, so adding the entries without it would reject whole
  batches (the v0.4.0 trap named in the `add-aws-type` skill).

**Edges.** `RUNS_SERVICE` (cluster to service) already exists. New: `RUNS_TASK` (cluster or service to
task) and `RUNS_CONTAINER` (task to container), declared in the manifest as edge rules
([Declarative Edge Rules](#declarative-edge-rules)). The service-to-task link is resolved from `group`; where
`group` is not `service:<name>` the task attaches to its cluster alone.

**Sensitivity.** `DescribeTasks` returns `overrides.containerOverrides[].environment` and `.command`, which
callers use to pass secrets to a container. These are declared `reviewed_may_contain` with category
`credential` and are removed before storage (`req-aws-collector-redaction-1`); the rest of the response is
stored as `configuration` (`persist_configuration: true`, since aws-core-tap#207). Typed fields, tags and
edges carry every fact this requirement needs, so nothing is read back from the stored blob. Whether to store
`configuration` is the requester's decision and storing a `credential` location is the owner's
([the `add-aws-type` skill](../tap_plugin/aws_core/skills/add-aws-type/SKILL.md), step 1).

**Running, stopped, and the limit of it.** `ListTasks` with `desiredStatus="RUNNING"` returns running and
pending tasks; with `desiredStatus="STOPPED"` it returns the tasks ECS still shows after they stopped (at
least an hour, per the `DescribeTasks` API reference). A stopped task is described and recorded only when the
grid already holds a live node for it (`tap_grid.services.find_by_natural_key`). It records `last_status`,
`desired_status`, `stopped_at`, `stopped_reason` and `stop_code` (`-15`), and asserts no `RUNS_TASK` edge,
nor its containers a `RUNS_CONTAINER` edge, with those edge reads `partial` so the run claims none of them
absent (`-16`), so its earlier `RUNS_TASK` edge is kept. A run that writes the task has observed it, so it is
not a retirement candidate while ECS still lists it (`req-grid-reconcile-candidates-1`: observed is every
entity the run wrote). Once ECS stops listing it, the run writes nothing for it, and reconciliation finds it
through that kept edge: the stop is recorded first and the task retired after, by the falsifier, at least an
hour after it stopped (ruled 2026-11-09, aws-core-tap#211). A task that
started and stopped between two runs is never created, because with no `RUNS_TASK` edge it would be held by
nothing and could never be reconciled. A task absent from both listings is not deleted or modified
([Collector Scope](#collector-scope), `req-aws-collector-scope-3`); retiring it is the task falsifier's and
reconcile's job (aws-core-tap#211), not this collector's. Stopped-task history beyond the last recorded state,
task-definition revisions as nodes, ECS Anywhere and EKS are out of scope.

**Retirement path (aws-core-tap#211).** A cluster contains its tasks (`RUNS_TASK`) and a task its containers
(`RUNS_CONTAINER`); `RUNS_TASK` from a service is a reference, not containment (`-17`). The walk records a
completeness surface for every cluster's running-task listing (relation `ecs_cluster.tasks`) and every described
task's containers (`ecs_task.containers`), complete only when the listing reached its end, incomplete with the
reason when it was denied, failed or stopped short, and complete-empty for a cluster running nothing (`-18`;
`req-aws-core-contained-type-triple`). Core derives the candidates: a task the grid holds under a cluster whose
listing this run completed, and which this run did not write. `EcsTaskFalsifier` and `EcsContainerFalsifier` probe
`DescribeTasks` (already granted), 100 ARNs a call per region and cluster, reading region and cluster from the
task's own ARN: a `MISSING` failure is gone, and so is `STOPPED` once the grid has recorded that stop (record first,
retire after); any other state is present, and an error, refusal or throttle is undetermined, never absence (`-19`). A container is gone with its task or when its running task no
longer lists it. Nothing retires until an operator arms reconcile authority for the collector (off by default,
`req-grid-reconcile-verb-2`). Not covered: a deleted cluster. It is not contained by anything, so its tasks are
not candidates until a later change adds footprint-to-cluster containment and a cluster falsifier.

**Read-only permissions added to the collector role:** `ecs:ListClusters`, `ecs:DescribeClusters`,
`ecs:ListServices`, `ecs:DescribeServices`, `ecs:ListTasks`, `ecs:DescribeTasks`.

**Not specified here (open).** Where the digest-to-build join lives. aws_core and github_core must not import
each other. The candidates are equality of a digest field read by a Search, or a neutral image node in
computing_core that both plugins link to. That is a computing_core decision and is not made by this
requirement.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-ecs-1 | Three Types Collected | Implemented | A run collects `aws_ecs_cluster`, `aws_ecs_service` and `aws_ecs_task` from every swept region through manifest entries backed by `custom_fn`s that share one ECS walk. | Before this requirement none had a manifest entry; now each does. One entry yields one node type, so the container node has its own entry (`-3`). |
| req-aws-collector-ecs-2 | Call Shape And Pagination | Implemented | The calls are `ListClusters`/`DescribeClusters`, `ListServices`/`DescribeServices` (10 per call) and `ListTasks` (`desiredStatus` `RUNNING`, then `STOPPED`)/`DescribeTasks` (100 per call, `include=["TAGS"]`, one sequence for running and held stopped tasks), each read to its end. | `req-aws-collector-pagination-1`. |
| req-aws-collector-ecs-3 | Container Node | Implemented | Each container in a described task is an `aws_ecs_container` node keyed on `container_arn`, with `name`, `image`, `image_digest`, `runtime_id` and `last_status`. | |
| req-aws-collector-ecs-4 | Digest Verbatim | Implemented | `image` and `image_digest` are stored as ECS reports them. The collector makes no registry call and never resolves a tag to a digest. | The tag may move; the digest is what ran. |
| req-aws-collector-ecs-5 | Unreported Is Null | Implemented | A container with no `imageDigest` has `image_digest` null, never an empty string and never copied from the tag. | Grid null convention: null is unobserved. |
| req-aws-collector-ecs-6 | Task Fields | Implemented | `aws_ecs_task` carries `cluster_arn`, `last_status`, `desired_status`, `started_at`, `platform_version`, `group`, `stopped_at`, `stopped_reason` and `stop_code`. | Additive migrations (`0051` adds the three stop fields). |
| req-aws-collector-ecs-7 | Tags Field On All Three | Implemented | The cluster, service and task models each declare `tags` (field, create schema and validation schema) and are listed in the always-on tags guard. | The v0.4.0 reject-the-batch trap. |
| req-aws-collector-ecs-8 | Edges | Implemented | `RUNS_TASK` (cluster or service to task) and `RUNS_CONTAINER` (task to container) exist, declared as manifest edge rules, and are asserted for running tasks. A task whose `group` is not `service:<name>` attaches to its cluster only. | `RUNS_SERVICE` is unchanged. Stopped tasks: `-16`. |
| req-aws-collector-ecs-9 | Sensitivity Declared, Credentials Removed | Implemented | The entry declares `overrides.containerOverrides[].environment` and `.command` as `reviewed_may_contain` credential locations, removed before storage while the rest of the response is stored (`persist_configuration: true`), and a planted canary at each location never reaches the GRIFT document or the stored row. | `req-aws-collector-redaction-1` (aws-core-tap#207); requester decides storing, owner decides a credential location. |
| req-aws-collector-ecs-10 | Denial Degrades, Never Cleans | Implemented | An `AccessDenied` on any ECS sub-call leaves the fields that call supplies null and records a warning. The task or container is still collected, and the denial is distinguishable from an empty result. | Mirrors `req-aws-collector-hydrate-2`. |
| req-aws-collector-ecs-11 | Absence Is Not Deletion | Implemented | A task absent from both listings of a later run is not deleted or modified, and the collector adds no "currently running" flag of its own: a task's state is ECS's `lastStatus`, recorded when ECS lists it. | `req-aws-collector-scope-3`; retirement is aws-core-tap#211's falsifier and reconcile. |
| req-aws-collector-ecs-12 | Read-Only Permissions | Implemented | The collector's permission list adds exactly the six `ecs:List*`/`ecs:Describe*` actions named above and no write action. | The repo's only action list is the trial policy's read section (`handoff/trial-provisioner-policy.json`); the cross-account handoff grants AWS-managed `SecurityAudit`, which already covers these reads. |
| req-aws-collector-ecs-13 | Live Trial Before Release | Proposed | The change passes the `add-aws-type` trial run against a real cluster and Fargate task (or carries a named `deferred_reason`) and a collected container's digest is shown equal to the digest `DescribeTasks` returns for it. | Needs a human to approve what is provisioned. |
| req-aws-collector-ecs-14 | Digest Join Not Made Here | Implemented | This requirement adds no import of github_core or computing_core types and no digest-matching logic. | The join home is an open computing_core question. |
| req-aws-collector-ecs-15 | Held Stopped Task Records Its Stop | Implemented | Each cluster is listed with `desiredStatus="STOPPED"`. A listed task the grid already holds is described and records `last_status`, `desired_status`, `stopped_at`, `stopped_reason` and `stop_code`; one the grid does not hold is neither described nor created. A grid read that fails, or finds two live rows for one ARN, records no stopped task and leaves a `stopped_tasks` gap on the cluster naming why. | Ruled 2026-11-09, aws-core-tap#211. A task listed under both filters is read as running. |
| req-aws-collector-ecs-16 | Stopped Task Asserts No Edges | Implemented | A stopped task carries no `RUNS_TASK` source and its held containers no `RUNS_CONTAINER` source, and those edge reads are `partial`, so the run neither asserts nor claims absent the edges a running read would write. | Keeps the earlier `RUNS_TASK` edge, the containment a reconcile candidate is derived from once ECS stops listing the task (aws-core-tap#211). Not what makes it a candidate: a written task is observed (`req-grid-reconcile-candidates-1`). |
| req-aws-collector-ecs-17 | Cluster And Task Contain | Implemented | `aws_ecs_cluster` declares `RUNS_TASK` and `aws_ecs_task` declares `RUNS_CONTAINER` in `CONTAINMENT_EDGES` (and `OUTBOUND_EDGES`); `aws_ecs_service` declares no containment. | aws-core-tap#211. A deleted cluster is not yet a candidate (no footprint containment). |
| req-aws-collector-ecs-18 | A Surface Per Parent | Implemented | The walk records a surface for every cluster's running-task listing and every described task's containers; a denied, failed or short listing is recorded incomplete with its reason, never omitted, and a cluster running nothing is complete-empty. A stopped task whose container could not be looked up on the grid records its container surface incomplete (`grid_lookup_failed`), so an omitted container never reads as absent. The stopped-task listing records no surface. | `req-aws-core-contained-type-triple-1`..`-3`. |
| req-aws-collector-ecs-19 | Task And Container Falsifiers | Implemented | `EcsTaskFalsifier` and `EcsContainerFalsifier` are registered in `[falsifiers]` and pass core's four proof cases. They probe `DescribeTasks` at most 100 ARNs a call per region and cluster; `MISSING` is gone, `STOPPED` is gone only once the row already records `STOPPED` (otherwise undetermined), an error is undetermined, and an ARN that names no cluster, or whose own account is not the credential's (whatever the row's `aws_account` dimension says), is not probed. | Reconcile authority stays off by default. Ruled 2026-11-09: a stopped task retires. |

### Load Balancer Topology
----
RID: `req-aws-collector-lb-topology`

Status: `In Development`

A load balancer is mapped as it actually routes: listener, rule, target group and target, with each hop keeping
what decides it. Ruled by George on 2026-11-10 (aws-core-tap#220): the target group stays in the path; one edge per
listener rule; the direct load-balancer edges are replaced; IP addresses become nodes; and every Route 53 record
set becomes a node between its zone and what it resolves to. The general rule behind it: "when in doubt, map it
out".

**The path.** `FORWARDS_TO_TARGET_GROUP` runs from an Application, Network or Gateway Load Balancer to a target
group, one edge per route. An Application Load Balancer's routes are its listeners' rules, read with
`DescribeListeners` and `DescribeRules`, including each listener's default rule. A Network or Gateway Load Balancer
has no rules, so each listener's default action is the route. Each edge carries the listener's ARN, port and
protocol; the rule's ARN, priority and conditions exactly as AWS returns them; whether it is the default; and the
forward's weight. A rule that forwards to two groups by weight makes two edges. Redirect, fixed-response and
authenticate actions forward nowhere and make no edge. The key's discriminator is `route_id`: the rule's ARN, or
the listener's where there are no rules.

From the target group, `DescribeTargetHealth` names the registered targets:
- an instance is `ROUTES_TO_TARGET` to the instance
- an Application Load Balancer's ARN (a Network Load Balancer fronting an Application one) is `ROUTES_TO_TARGET`
  to that load balancer
- a Lambda function is `INVOKES_LAMBDA`

Each edge carries the target's port (the `ROUTES_TO_TARGET` discriminator, since one instance can be registered on
two ports), its availability zone, and its health state, reason and description. Health changes in place from run
to run. An IP target is kept on the target group's item, with no edge, until the IP address node's key is settled
(see -4).

**Replacing the direct edges.** Before this, `ROUTES_TRAFFIC` ran from a load balancer straight to the instances
and functions in its target groups, and IP and load-balancer targets were dropped. Those rules stay declared for
one release, read complete and empty, so a reconcile-armed run proposes removing the edges earlier runs wrote.
A Classic load balancer has no target groups. It keeps `ROUTES_TRAFFIC` to the instances registered on it, which
are now read from its own listing.

**The engine.** The rules above are manifest rules whose values are objects, carrying `key_path` and
`properties_path` (`req-aws-collector-edges-9`). Their batch refs carry the discriminators
(`req-aws-collector-edges-10`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-lb-topology-1 | One Edge Per Rule | Implemented | An Application Load Balancer has a `FORWARDS_TO_TARGET_GROUP` edge for each (rule, target group) a forward action names, the default rule included. It carries `route_id`, `listener_arn`, `listener_port`, `listener_protocol`, `rule_arn`, `priority`, `is_default`, `conditions` (verbatim) and `weight`. A Network or Gateway Load Balancer has one per listener default forward, with `route_id` the listener's ARN and `rule_arn` null. A non-forward action makes no edge. A listener or rule read that fails reads the slot `failed`. | `tests/test_elb_collection.py::TestForwards` |
| req-aws-collector-lb-topology-2 | Targets With Port And Health | Implemented | A target group has `ROUTES_TO_TARGET` to each registered instance and Application Load Balancer, one per port, and `INVOKES_LAMBDA` to a registered function. Each carries `health_state`, `health_reason`, `health_description` and `availability_zone` from `DescribeTargetHealth`, with null where AWS gave nothing. An IP target is kept on the item with no edge. A failed `DescribeTargetHealth` reads every target slot `failed`. | `tests/test_gap_sweep.py::test_a_target_group_sorts_its_targets_by_kind_with_port_and_health`, `::test_a_target_read_that_failed_is_not_an_absence` |
| req-aws-collector-lb-topology-3 | Direct Edges Replaced | Implemented | An Application, Network or Gateway Load Balancer's `ROUTES_TRAFFIC` slots read complete and empty, so earlier runs' direct edges become removal proposals under armed reconcile. A Classic load balancer's slot holds the instances its own listing registers. | `tests/test_elb_collection.py::TestForwards::test_the_replaced_direct_routes_read_complete_and_empty`, `::test_a_classic_load_balancer_keeps_its_direct_routes_to_its_instances`. Drop the empty rules after one release. |
| req-aws-collector-lb-topology-4 | IP Targets As Nodes | Proposed | An IP target becomes an IP address node, with an edge from the target group, and edges from the address to the network interface holding it and to that interface's owner. Both move when the address moves. | Blocked on the IP address node's key: `network_name` plus address in computing_core, a joint question with the tenable session (aws-core-tap#220). |
| req-aws-collector-lb-topology-5 | Record Sets As Nodes | Proposed | Every record set `ListResourceRecordSets` returns is an `aws_route53_record_set` node, keyed `<zone id>/<name>/<type>/<set identifier>`, contained by its zone through `HAS_RECORD_SET`, with a completeness surface per zone so a record set the zone no longer lists is a retirement candidate. | Next change on aws-core-tap#220. |
| req-aws-collector-lb-topology-6 | Records Resolve | Proposed | A record set has `RESOLVES_TO` to the Application Load Balancer, other load balancer, CloudFront distribution or record set its alias names, or a CNAME value names by DNS name, with `via` and `evaluate_target_health`. The zone's direct `ROUTES_TRAFFIC` rules are replaced, as in -3. | Next change on aws-core-tap#220. |
| req-aws-collector-lb-topology-7 | Live Trial | Proposed | A staging seed wave with an Application Load Balancer that has host and path rules and a weighted forward, a Network Load Balancer in front of it, instance and Lambda targets, and a private hosted zone with alias, CNAME and weighted records is collected, and each edge above is found on the grid. | |

### Credential Resolution
----
RID: `req-aws-collector-credentials`

Status: `Approved for Development`

AWS credentials are resolved through the `tap_cares` secrets subsystem. The
collector never reads credential files directly.

#### Implementation

- The collector resolves a secret via `resolve_secret(SecretRef(scope="aws_core",
  key=<configured>))` and validates it is `kind: aws_static_access_key` with the
  required `data` fields, using `require_secret_kind(...)` with an `aws_core`-owned
  JSON Schema (consumer-side validation, `req-tap-cares-secrets-validation-2`).
- Accepted `data`: `access_key_id`, `secret_access_key`, optional
  `session_token`, optional `region` (single), optional `regions_allowed`
  (list). The kind shape and its `aws_core`-owned schema are specified in
  `spec-aws-core-secrets.md` (`req-aws-core-secret-aws-static`).
- Region scope is operator-owned and carried on the secret: a non-empty
  `data.regions_allowed` scopes regional collection to exactly those regions; absent,
  the singular `data.region` is the sole swept region; with neither, the run
  fails visibly (one region is required to collect). Global-scope services are
  collected once regardless. A manifest/run-configuration region source is a
  deferred seam — not in the make-it-work path — and would override the secret
  default when introduced.
- A missing or malformed secret fails the run visibly with a structured,
  redacted error (`req-tap-cares-secrets-redaction-3`); it never logs secret
  material and never disables the collector capability.
- Two credential kinds are supported, dispatched by the resolved secret's
  `kind`:
  - `aws_static_access_key` — a boto3 session bound directly to the static
    credentials (our own account).
  - `aws_assumed_role` — **cross-account**: build a base session from
    `data.base`, attach the audit ledger to it, call `sts:AssumeRole(RoleArn,
    ExternalId, RoleSessionName, DurationSeconds?)`, and build the working
    session from the returned short-lived credentials. The existing
    `GetCallerIdentity` reachability probe doubles as the assert-on-land check
    against `data.expected_account_id` when present. The kind shape and its
    `aws_core`-owned schema are specified in `spec-aws-core-secrets.md`
    (`req-aws-core-secret-aws-assumed-role`).
- v0 collects a single account per run. The assumed-role kind lifts the
  cross-account restriction (`req-aws-core-secret-aws-static-3` superseded);
  multi-account fan-out remains "more secret files" (`req-aws-collector-nongoals`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-credentials-1 | Secrets Subsystem Only | Approved for Development | Credentials resolve via `resolve_secret`; no direct file reads. | |
| req-aws-collector-credentials-2 | Consumer-Side Validation | Approved for Development | The collector validates `kind` and required `data` against an `aws_core`-owned schema before use. | |
| req-aws-collector-credentials-3 | Visible Redacted Failure | Approved for Development | Missing/malformed secret fails the run with a structured redacted error; no secret material is logged. | |
| req-aws-collector-credentials-4 | Static Keys v0 | Approved for Development | v0 supports static access keys for the operating account. | Multi-account fan-out deferred. Proposed: lifted by `req-aws-collector-fanout`, whose base credential is exactly this kind (static keys of a read-only user in the organization's management account; ruling 2026-09-30). |
| req-aws-collector-credentials-5 | Cross-Account Assume-Role | Proposed | The collector resolves the `aws_assumed_role` kind, assumes the target-account role via STS (with a mandatory External ID), and collects with the returned short-lived credentials; the STS probe doubles as the assert-on-land check. | Specified by `req-aws-core-secret-aws-assumed-role`. |

### Collector Runtime Integration
----
RID: `req-aws-collector-runtime`

Status: `Approved for Development`

The collector is an ordinary `CollectorBase` implementation registered with
`tap_cares`. It invents no parallel runtime; it mirrors the established
`fedramp_20x_ksi` KSI collector reference shape.

#### Implementation

- A `CollectorBase` subclass implementing `run()` and `self_test()`.
- `run()` pipeline: resolve credentials → load+validate manifest → for each
  manifest entry, drive `source` → project fields → emit nodes → emit edges →
  assemble one GRIFT batch → `self.submit_grift(document)` → set `self.summary`
  to a one-line human result.
- `self_test()`: validate the secret resolves and is the right kind, and probe
  read-only reachability via STS `GetCallerIdentity` (cheap, no resource
  permissions required), within the bounded self-test latency budget
  (`req-tap-cares-collector-self-test-12`).
- Structured events via `record_info` / `record_warn` / `record_error` with
  4-hex site tokens minted by `scripts/log-site-id` and held unique per the
  repo-wide site-uniqueness test.
- Failure protocol: an unrecoverable condition records a structured error and
  raises (an `_abort`-style helper), letting the `run_collector` task body write
  the FAILED terminal patch — exactly the framework convention
  (`req-tap-cares-collector-failure-mode`). The collector never writes
  `CollectionJob`.
- Registration in the plugin `apps.py` `ready()` via `register_collector(key=…,
  cls=…, name=…, description=…)` — the dual-existence call that both registers
  the runner and upserts the on-grid `Collector` node.
- The collector reads AWS (external) and the grid only through approved
  surfaces; its sole grid-mutation path is `self.submit_grift`
  (`req-tap-cares-collector-read-boundary`, `-grift-import`).

Trust posture: unlike the KSI collector (which ingests untrusted upstream JSON
and carries a paranoid denylist/structural-cap/mass-deletion layer), this
collector reads our own account with our own read-only credentials. That input
is **trusted**; the KSI-style paranoid safety layer is deliberately **not**
replicated. This trust-tier distinction is carried forward as a build-skill axis
(`req-aws-collector-build-skill`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-runtime-1 | CollectorBase Subclass | Approved for Development | The collector subclasses `CollectorBase`, implements `run()` and `self_test()`. | |
| req-aws-collector-runtime-2 | Sole Mutation Path | Approved for Development | The only grid write is `self.submit_grift`; the collector never writes `CollectionJob` or the ORM. | |
| req-aws-collector-runtime-3 | Framework Failure Protocol | Approved for Development | Unrecoverable conditions record a structured error and raise; the task body owns the terminal patch. | |
| req-aws-collector-runtime-4 | Dual-Existence Registration | Approved for Development | Registered in `apps.py` via `register_collector(...)`. | |
| req-aws-collector-runtime-5 | Self-Test Reachability | Approved for Development | `self_test()` validates the secret and probes STS `GetCallerIdentity` within budget. | |
| req-aws-collector-runtime-6 | No Paranoid Layer | Approved for Development | The trusted-input posture is documented; the KSI paranoid safety layer is intentionally not replicated. | |
| req-aws-collector-runtime-7 | No Per-Service Class | Approved for Development | Exactly one `CollectorBase` subclass for all of AWS; no per-service subclasses; reuse via composed collaborators. | The invariant that keeps the build-skill a config generator. |

### Region Iteration And Resilience
----
RID: `req-aws-collector-regions`

Status: `Approved for Development`

The engine iterates regions for regional services and degrades gracefully on the
expected partial-failure conditions, without ever corrupting collected data.

#### Implementation

- The swept region set is resolved from the secret: `data.regions_allowed` if
  non-empty, else `[data.region]`, else the run fails visibly. Regional entries
  are collected once per resolved region; global entries once.
- A permission/region condition — `AccessDenied`, `UnauthorizedOperation`,
  authorization failures, "not supported in this region" — is recorded as a
  structured `warn` and that (region, resource) is skipped; the run continues.
- Throttling is retried with bounded exponential backoff; an unbounded or
  unbroken throttle ultimately records an `error` and the run fails per the
  framework protocol.
- A skipped region/resource never removes or alters previously collected data.
  Because v0 has no deletion semantics, the Cartography-style
  transient-vs-skippable hazard (an ambiguous read causing a false delete) does
  not arise in v0; it is noted as a constraint to honor if/when reaping is
  introduced.

The classify-and-skip behavior is a clean-room re-expression of a widely-used
resilience shape, implemented as TAP code against `record_warn`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-regions-1 | Per-Region / Global Split | Approved for Development | Regional entries sweep configured regions; global entries collect once. | |
| req-aws-collector-regions-5 | Secret-Scoped Region Set | Approved for Development | The swept region set is `data.regions_allowed` if non-empty, else `[data.region]`, else the run fails visibly. | Operator-owned scope; `req-aws-core-secret-aws-static-4`. |
| req-aws-collector-regions-2 | Classify-And-Skip | Approved for Development | Expected permission/region errors record a `warn` and skip; the run continues. | |
| req-aws-collector-regions-3 | Bounded Throttle Backoff | Approved for Development | Throttling retries with bounded backoff; unbroken throttle fails per protocol. | Realised by `req-aws-collector-outcome-4` and `-6`: the adaptive retry budget, then the named `throttled` outcome. |
| req-aws-collector-regions-4 | No Data Corruption On Skip | Approved for Development | A skipped region/resource never alters previously collected data. | v0 has no deletes; reaping must honor this. |

### Collection Selection
----
RID: `req-aws-collector-selection`

Status: `Proposed`

A run can be narrowed to chosen types and chosen accounts. Requested by George on 2026-11-03 for field testing;
the keys live in the credential's `data` for now (`req-aws-core-secret-selection`, which defines the grammar of a
type pattern and of an account reference). Built for a single-account run (`-1` to `-6`, `-9`, `-13` and `-14`; tests in
`test_boto3_collector_selection.py` and `test_boto3_collector_selection_run.py`) and run live once (`tools/validate/runs/selection-2026-11-04.json`: keep-absent, no completeness and the edge count; not the retirement control). Not built: the
fan-out parts (`-7`, `-8`, `-10`, `-11`), which wait on `req-aws-collector-fanout` itself, and `-12`, which waits on
unified-systems-com/tap#1156. It carries the type selection that `req-aws-core-livevalidation-selection` first proposed for validation, with one change of
grammar (`<service>:<entity>`, not an `fnmatch` pattern over the raw entity type).

#### Type Selection

A manifest entry is **selected** when it matches at least one pattern of `include_types` (or `include_types` is
absent) and matches no pattern of `exclude_types`. Exclusion wins. The match string is `<service>:<entity>`.

**Exclusions are entry filters, not service-call boundaries.** `exclude_types` decides which manifest entries are read. It
does not promise that no call reaches the service: a selected entry whose source needs an excluded entry as its parent
causes that parent's list call (next bullets). An operator who needs a service never called must also keep the grant
out of the role; the echo (`-9`) names every parent read on a selected child's behalf so the gap is visible.

- An unselected entry makes no call **of its own**: it is absent from the batch, and from the run's call ledger except where a
  selected entry's source needs it as a parent (next bullet). A call made for that purpose is the selected child's: the
  ledger records it against the child, and the role's grant must include it. An operator who excludes a service whose
  list call a selected child depends on still needs that permission; the echo (`-9`) names such parents.
- A parent that a selected type fans out from (a `per` or `bind` source) is read as the input of that type and
  emits nothing unless it is itself selected.
- Some things are not manifest entries and are never filtered: the per-(account, region) footprints every
  regional containment hangs from, and the run's own account node (the `sts:account` entry, an anchor that is always
  selected and never counted as skipped).
- Two reads are not manifest entries and no pattern can name them: the Organizations tree and the landing-zone read. A
  run whose type patterns leave anything unselected skips both, so that it makes no call it did not select. A run
  narrowed by `accounts_allowed` alone keeps them (the tree is what fan-out lists members from).
- A pattern, in `include_types` or `exclude_types`, that matches no manifest entry stops the run before any call,
  naming the pattern (`SELECTION_PATTERN_UNMATCHED`). An exclude that matched nothing would widen the run silently
  (a typo, or a manifest rename), and the selection lives in a secret the operator cannot inspect, so both fail closed.

**Unselected is unobserved, not empty, and a selected run states no completeness.** Core reads a run's
completeness statement against the previous run's, and a surface the run leaves out, or marks not authorized,
reads as a **narrowed scope**: the previously observed children become `scope_withdrawn` candidates
(`spec-grid-reconcile.md`, *Withdrawal is not absence*; `tap_grid/candidates.py` `_scope_of`). Core cannot tell
"this run read less" from "the credential's scope was narrowed", so a selection must not leave a partial
statement. A run in which the selection leaves anything unselected (a type or an account) therefore records **no completeness statement at all**: no surface, no `declare_no_surfaces`, and no
edge authority claim for a source it did not read. This is the course `-21` takes for a rejected base batch, and
for the same reason. The keep-absent upsert semantics (tap#1128) hold for every row of an unselected type. The
cost is stated: a selected run retires nothing, even within what it read; retirement comes from runs that
select everything. Retiring the old scope on purpose, by narrowing it, is not offered through selection (open
question below). Retirement *within* a selection is the flag `retire_within_selection` (below), which waits on core. This is the rule `req-aws-core-livevalidation-lifecycle`'s second negative control tests.

Regions are not a selector in this amendment. `regions_allowed` is the existing region scope
(`req-aws-collector-regions-5`); it is unchanged, does not trigger the no-statement rule, and a run restricted by it
states its completeness as it does today.

#### Account Selection

- **Single account.** When `accounts_allowed` is set, the account `GetCallerIdentity` resolves must be in it, or
  the run fails visibly before any collection, as an `expected_account_id` mismatch does today
  (`account_mismatch_error`).
- **Fan-out** (`req-aws-collector-fanout`). The member set is the organization's `ACTIVE` members from this run's
  `ListAccounts`, restricted to `accounts_allowed` when set, minus the secret's `exclude_account_ids`. Exclusion
  wins. Every listed account still has exactly one `ACCOUNT_RESULT`; one the selection left out is
  `skipped` with reason `not_selected`. It does **not** record the `scope_authorized: false` surfaces
  `req-aws-collector-fanout-7` gives a member that failed: the run records no completeness statement at all
  (above), so there is nothing to read as a withdrawal. `max_member_accounts` bounds the **selected**
  member count; an explicit list is not a silent prefix.
- **`exclude_account_ids` is not a selection.** The existing exclude list (`req-aws-core-secret-member-fanout`) is
  a scope control: an excluded account is `skipped: excluded` and keeps the `scope_authorized: false` surfaces of
  `req-aws-collector-fanout-7`, as it does today, so a run with only an exclude list states its completeness and
  an excluded account reads as withdrawn from scope. The no-statement rule applies when `accounts_allowed`,
  `include_types` or `exclude_types` leaves anything unselected; in such a run nothing is recorded for any
  account, the excluded ones included. `-7` governs the failure case (a member that could not be read) and the
  exclude list; selection omissions are governed by this section.
- **Unselected members still appear in the organization tree, and `accounts_allowed` is a collection scope, not a
  disclosure control.** It limits which accounts are assumed into and read; it does not limit which accounts the
  organization listing writes to the grid. See the open question on the tree.
- **The tree.** The tree is the organization's observation, not
  the account's: it carries each member's org-sourced fields (`req-aws-collector-fanout-8`) whether or not the
  account is selected. "Unobserved" here means the account's own resources, surfaces and account-sourced fields
  (`-16`): none is read, none is written, none is withdrawn.
- **An account the organization does not list.** An `accounts_allowed` entry that is not an `ACTIVE` member of
  the organization (and is not the base account) stops the run before any member is assumed
  (`SELECTION_ACCOUNT_UNKNOWN`), naming the id. A typo must not narrow a run silently.
- **The base account.** When `accounts_allowed` is set and omits the base account, the base account's own
  resources are not collected. The organization tree is still read, because fan-out needs it to list members.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-selection-1 | Include, Exclude, Exclusion Wins | Proposed | An entry is read exactly when it matches an include pattern (or none is given) and no exclude pattern; a test over the committed manifest asserts the selected set for `ec2:*`, `eks:*`, `*:*_policy`, an include with an overlapping exclude, and neither. | |
| req-aws-collector-selection-2 | Unselected Makes No Call | Proposed | With a selection that excludes a service no selected entry depends on, the fake-client harness records zero calls for that service and the ledger holds none; with one a selected child's `per`/`bind` source reads as its parent, the call is made, is ledgered against the child, and the echo names the parent. | |
| req-aws-collector-selection-3 | Anchors Are Never Filtered | Proposed | With `include_types: ["ec2:vpc"]`, the account and region footprint nodes and the account node are still emitted. | |
| req-aws-collector-selection-4 | Typos Fail Loudly | Proposed | Any include or exclude pattern matching no entry stops the run before any call (`SELECTION_PATTERN_UNMATCHED`); a test feeds a typo in each list. | |
| req-aws-collector-selection-5 | A Selected Run States No Completeness | Proposed | A run whose selection leaves any type or account unselected records no completeness statement (no surface, no `declare_no_surfaces`, no edge authority claim for an unread source), derives no candidate, and writes no tombstone; every row of an unselected type keeps its fields (keep-absent). A test runs a full run, then a restricted run over a grid holding the unselected type's rows, and asserts no statement, no candidate, and those rows untouched; and that a run selecting everything records its statement as before. | The first of two tests: the second is live, `req-aws-core-livevalidation-lifecycle`'s negative control (2). This must hold before the status moves past Proposed. |
| req-aws-collector-selection-6 | Single-Account Assertion | Proposed | A resolved account outside `accounts_allowed` fails the run before collection; one inside it proceeds. | |
| req-aws-collector-selection-7 | Fan-Out Member Set | Proposed | The member set is `ACTIVE` members, restricted to `accounts_allowed`, minus the base account and `exclude_account_ids`; a member in both lists is excluded; each left-out listed account has one `ACCOUNT_RESULT` of `skipped`/`not_selected` and records no surface; `max_member_accounts` bounds the selected count. | Amends `req-aws-collector-fanout-1`, `-5` and `-10`. |
| req-aws-collector-selection-8 | Unknown Account Stops The Run | Proposed | An `accounts_allowed` id that is not an `ACTIVE` member or the base account stops the run before any `AssumeRole` (`SELECTION_ACCOUNT_UNKNOWN`). | |
| req-aws-collector-selection-9 | Effective Selection Is Echoed | Proposed | The run's start message and its `CollectionJob.results` carry the effective selection: the type patterns, the normalised account ids, and counts (entries total, selected, skipped by type selection; accounts listed, selected, skipped). One aggregated info line, not one per skipped entry. | The secret cannot be inspected, so the run is where an auditor reads the scope it had. Account ids are runtime output; none is committed. |
| req-aws-collector-selection-10 | Base Account Omitted | Proposed | With `accounts_allowed` set and omitting the base account, no base-account resource is collected, the organization tree is read, and the base batch carries the tree. | See the open question below. |
| req-aws-collector-selection-11 | Exclude List And Tree Distinguished | Proposed | A run with only `exclude_account_ids` records its statement and an excluded account carries the `fanout-7` surfaces; a run with `accounts_allowed` records no statement and no account, excluded or not, carries a surface; in both, every listed member has its org-sourced fields from the tree and no unselected member has an account-sourced field written. | Settles the first review's `exclude` question and the second's tree question. |

#### Retirement Within The Selection

`data.retire_within_selection` (`req-aws-core-secret-selection-7`, default `false`). Requested by George on 2026-11-03.
With it `false`, a selected run states no completeness (above) and retires nothing. With it `true`, the run states its
completeness **for the surfaces it read**, and also declares its selection in grid terms: the entity types it listed,
and the accounts it covered. A surface the selection did not cover is then neither in the
statement nor read as withdrawn.

This cannot be done by the collector alone. Core derives withdrawal from the previous statement and the grid
(`tap_grid/candidates.py` `_scope_of`, `derive_candidates`), and a producer cannot name a surface under a subject it
did not read. It needs core to accept a selection block in the completeness statement and skip, with the reason
`not_selected`, any previous surface outside it. Filed as unified-systems-com/tap#1156 (an L: whether the block is
its own or part of the reach block of #683 is unsettled). Until core takes it, the flag is rejected at validation
when `true`, so no operator sets a value the collector cannot honour.

What the flag does and does not do. It **permits candidates** for what the run read; a candidate still passes the
falsifier, the operator-armed authority and the budget (`spec-grid-reconcile.md`). Retirement stays off by default,
per collector. Falsification is per candidate and needs no change: a candidate inside the selection is probed as any
other, and nothing outside it is a candidate.

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-selection-12 | Retirement Only Within The Selection | Proposed | With `retire_within_selection: true` and core's selection block, a run records its statement for the surfaces it read and its selection; a previous surface outside the selection is skipped as `not_selected`, never `scope_withdrawn`; a surface inside it compares as today. Live: collect everything, delete one object of a selected type and one of an unselected type, run with the flag on, and only the first becomes a candidate (and retires, with authority armed). | Blocked on unified-systems-com/tap#1156. Extends `req-aws-core-livevalidation-lifecycle`'s negative control (2). |
| req-aws-collector-selection-13 | Flag Refused Until Core Honours It | Proposed | Until core accepts the selection block, a secret with `retire_within_selection: true` fails validation with a message naming tap#1156, whether or not a narrowing key is set; `false` or absent behaves as `-5`. | A flag that is accepted and silently ignored would read as "retirement is on". |
| req-aws-collector-selection-14 | Edges To An Unselected Type Are Not Emitted | Proposed | A run whose selection leaves a type unselected emits no edge whose far end is of that type, counts them in one `EDGES_NOT_SELECTED` info line, and writes no `EDGE_DROPPED` warning for them; an edge between two selected types, and the account containment edges, are emitted as before. A run that selects everything records no such line. | The run never read the far end, so it cannot state the relationship. Edges from earlier full runs are untouched (keep-absent). |

#### Open Questions

- **Limiting what the organization tree writes.** The tree lists every member with its org-sourced fields whatever
  `accounts_allowed` says, so an operator who scopes a run to a few accounts still has the others' ids, names and
  organizational placement in the grid. Whether the allowlist should also limit the tree (a disclosure control, with
  consequences for the org-unit structure the tree draws) is not decided; until it is, the secret's wording says the
  allowlist selects accounts to collect, and no one should read it as a way to keep other accounts out of the grid.
- **The organization tree under a type selection.** The tree and the landing-zone readers are not manifest
  entries, so no pattern can name them, and a run whose type patterns leave anything unselected skips both. Whether they
  should become selectable (pseudo-entries such as `organizations:account`) waits for someone who wants an
  organization-only run.
- **Retiring a scope on purpose.** Because a selected run states no completeness, narrowing the selection cannot
  withdraw what the wider selection observed. If an operator wants that (the credential's scope really did
  shrink), it needs either a full-scope run under the new credential or a core notion of a filter-level scope,
  which `spec-grid-reconcile.md` names and does not specify (Issue# 599 - tap). Not settled here.
- **Vocabulary.** The type pattern uses botocore service names. An alias table for IAM prefixes
  (`elasticloadbalancing:*`) is possible and not specified.
- **An exclude pattern that no longer matches** after a manifest rename now stops the run (`-4`). If field use shows that is too
  brittle, the alternative is a pinned manifest version in the selection; not specified here.

### AWS Partitions
----
RID: `req-aws-collector-partition`

Status: `Implemented`

An AWS *partition* is a hard isolation boundary: commercial (`aws`), AWS GovCloud
(US) (`aws-us-gov`), China (`aws-cn`) and the isolated `aws-iso*` partitions.
Credentials, IAM principals, Organizations and ARNs never cross one, and the
partition is the second segment of every ARN. The collector runs in the
commercial and GovCloud partitions. It never assumes which one: the partition
is derived from the secret's own region scope and every partition-specific
choice follows from it.

#### Implementation

- **Derived, then checked, before any AWS call.** `credentials.resolve_partition`
  derives the partition from the region scope (`us-gov-*` → `aws-us-gov`,
  otherwise by botocore's own region table) and refuses, by name
  (`PARTITION_UNUSABLE`, the run aborts), a region no table recognises, a scope
  spanning two partitions, a declared `data.partition` that disagrees with the
  regions, a partition this collector does not support (`aws-cn`, `aws-iso*`),
  and on the assumed-role kind a `role_arn` in another partition or account.
  The secret's optional `partition` is a cross-check, never the source.
- **Partition-aware ARNs.** ARNs are parsed with a partition-agnostic pattern
  (`partition.PARTITION_RE`, `parse_arn`) and every ARN the collector builds
  (an S3 bucket ARN synthesised from its name, the edge transforms that mint
  one, the API Gateway API ARN) takes the run's partition (`build_arn`). No
  `arn:aws:` literal decides a partition.
- **Global-service routing.** A global service (IAM, Route 53, Organizations,
  STS) is addressed through a region of the run's own partition — the scope's
  first region — and botocore resolves that partition's global endpoint
  (`iam.us-gov.amazonaws.com` in GovCloud). Where a literal is unavoidable the
  partition's home region is used (`us-east-1` commercial, `us-gov-west-1`
  GovCloud). The collector package carries no literal `us-east-1` client
  region; `tests/test_govcloud.py` guards it. The falsifiers
  (`falsifiers.py`) are outside that guard: the IAM role, user and policy
  falsifiers and the S3 bucket falsifier still bind `us-east-1`.
- **Services a partition does not offer.** CloudFront does not exist in
  GovCloud: its entry records `SERVICE_NOT_AVAILABLE_IN_PARTITION` and makes no
  call, rather than calling a host no DNS server knows. Any other entry whose
  endpoint cannot be reached outside the commercial partition is skipped
  (`ENTRY_SKIPPED`) with a hint naming the partition.
- **FIPS endpoints are opt-in.** The secret's `use_fips_endpoint` is a
  tri-state: `true` / `false` is pinned on the botocore session, so every
  client made from it (engine, custom fns, RGTA sweep, falsifiers) inherits it;
  absent defers to `AWS_USE_FIPS_ENDPOINT` and the shared AWS config, botocore's
  own precedence. The effective setting is reported in `IDENTITY_RESOLVED` and
  the `self_test` `AWS_PARTITION` check. Per-service FIPS exceptions are not
  modelled.
- **Entries a partition does not offer (`-7` to `-14`).** Wave 0 on GovCloud (`runs/wave0-2026-11-02.json`, measured)
  found 22 entries in 10 services whose endpoint does not resolve there (`EndpointConnectionError`, 20 to 52 seconds
  each, the client's five-second connect timeout across its eight attempts). The smoke test drives each entry on its
  own, so it paid that 22 times (815 of 1,385 seconds). The collector already learns an unreachable service once per
  (service, region) in a run (`unreachable` in `collector.py`, built in #163, `-9`), so a full collection pays it once
  per service and region: the full collection of 2026-11-04 took 1,090 seconds, 1,008 of them reading, and the listed
  entries were called in it. The list removes that remaining first call (about 35 seconds a service, 10 services, per
  region) and, more important, the **masking** that learning causes in a service served in part: `wellarchitected`
  serves `lens`, `profile`, `review_template` and `workload` but not its three `agent_*` entries, and because
  `agent_profile` is read first, the first connection error marks the whole service unreachable and the four served
  entries are settled as "not offered" without a call (`-12`, shown by a probe run on 2026-11-04). The list is per
  entry, with a whole service listed only when none of its entries is served. The connect timeout and retry budget are
  **not** shortened (George, 2026-11-04): a slow network must not read as an absent service. The list is held in
  the manifest, the source of truth for what is collected: an optional `not_offered` block on the entry, keyed by
  partition, with why, how it was established, the evidence and the date (George, 2026-11-04). A new entry is authored
  with the question in front of the author, and the schema refuses a malformed block. A service all of whose entries
  carry the block is answered as a whole service (`service_unavailable_reason`); `macie2`, which has no manifest entry,
  stays named in `partition.py`. The test in `-10` keeps the blocks honest: it reads the newest wave 0 record and fails when an entry that record shows unreachable is neither
  listed nor named as an exception.

  Keeping the blocks current over time is layered. The offline test in `-14` runs on every botocore bump. The probe in `-13`
  reports, during ordinary runs, a service the manifest does not know is unreachable and a marked service that now
  resolves, so neither needs a wave 0 re-run to be noticed. A wave 0 re-run with the blocks ignored remains the way to
  prove a marked entry reachable, and runs after a batch of manifest additions and before a release. Measured on
  2026-11-04 from the stack's container: of the ten services wave 0 could not reach, three are absent from botocore's
  GovCloud data and unresolved, five (`qbusiness`, `datazone`, `internetmonitor`, `kendra-ranking`, `notifications`)
  are listed by botocore at `*.api.aws` hosts that do not resolve, `kinesisvideo` resolves only at its FIPS host, and
  `wellarchitected` resolves at its main host though its `agent_*` entries failed (which host they called was not
  established), so the host has to be the operation's, not the service's, to see a service served in part (`-12`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-partition-1 | Derived From Regions | Implemented | The run's partition is derived from the secret's region scope; a declared `partition` is only a cross-check. | `tests/test_govcloud.py::TestResolvePartition` |
| req-aws-collector-partition-2 | Mixed Or Unknown Refused | Implemented | A scope spanning partitions, an unrecognised region, a disagreeing `partition`, an unsupported partition, or a `role_arn` in another partition is refused by name before any AWS call (`PARTITION_UNUSABLE`). | `TestResolvePartition`, `TestCollectorRunInGovCloud::test_partition_mismatch_aborts_by_name_before_any_aws_call` |
| req-aws-collector-partition-3 | Partition-Aware ARNs | Implemented | ARNs are parsed in any partition and built in the run's partition; no `arn:aws:` literal decides it. | `TestPartitionAwareTransforms`, `TestCustomFnsUseTheRunsPartition` |
| req-aws-collector-partition-4 | Global Services In Partition | Implemented | Global-service clients bind to a region of the run's partition; the partition's home region is the only fallback literal. | `TestGovCloudEndpoints`, `test_no_hardcoded_commercial_partition_or_region_in_collector_code`. Offline against botocore's endpoint data; no live GovCloud run observed. The falsifiers are outside the guard. |
| req-aws-collector-partition-5 | CloudFront Degrades In GovCloud | Implemented | A service the partition does not offer is recorded as not available and never called. | `test_run_lands_govcloud_shaped_nodes_and_says_cloudfront_is_not_offered` |
| req-aws-collector-partition-6 | FIPS Opt-In | Implemented | `use_fips_endpoint` true/false is pinned on the session and reaches every client; absent defers to botocore's environment/shared-config resolution; the effective value is reported. | `TestGovCloudEndpoints`, `TestSelfTestReportsPartition` |
| req-aws-collector-partition-7 | Unavailable Entries Are Listed Per Entry | Proposed | For each supported partition the manifest marks the entries it knows are not offered there (`not_offered`), each with how it was established (`ran`, `web` or `read`, and the evidence) and the date. An entry so marked makes no call, records one `SERVICE_NOT_AVAILABLE_IN_PARTITION` info line carrying the reason, and is counted under "not offered" in the run summary. A service is marked on every entry only when none of its entries is served; `wellarchitected` marks its `agent_*` entries and not the others. | Replaces the service-keyed `_UNAVAILABLE_SERVICES`; the list is the manifest entry's optional `not_offered` block (schema-validated; no separate file). The landing zone's `Availability` record is the model for the method vocabulary. |
| req-aws-collector-partition-8 | Initial GovCloud List From The Wave 0 Record | Proposed | The GovCloud list opens with the 22 entries of `runs/wave0-2026-11-02.json` that failed with `EndpointConnectionError`, plus CloudFront and Macie, each marked `ran` with the record as evidence. A run over the manifest against GovCloud makes no call for any of them. | The other 46 entries that record labels unsupported-in-partition are not listed (CloudFront among them is listed already): the service answers and the refusal is per call (`UnknownOperationException`, `InvalidAction` and the like), at no cost in time. |
| req-aws-collector-partition-9 | Unreachable Service Is Learned Once Per Run | Implemented | In one run, the first connection-level failure for a (service, region) settles every later entry of that service in that region as not offered, with no further call; the state is per run. | `test_boto3_collector_outcomes.py::TestCollectorRun::test_an_unreachable_service_is_learned_once_not_once_per_entry`. Built in #163. It is keyed by service, which is what `-12` corrects. |
| req-aws-collector-partition-10 | List Is Checked Against The Latest Record | Proposed | A test reads the newest `runs/wave0-*.json` for each supported partition and fails when an entry it records as `EndpointConnectionError` is neither on that partition's list nor named in a short exception list with a reason; and fails when a listed entry that record shows reachable (`ok` or `empty`) is not named in the same exception list. | Keeps the list from rotting in either direction; a re-run of wave 0 updates the record and the test says what to change. |
| req-aws-collector-partition-11 | Not Offered Is Not Selection | Proposed | An entry skipped as not offered is reported as not offered and never counted as skipped by type selection (`req-aws-collector-selection-9`), and does not by itself make a run a selected run: a full run over a partition that does not offer an entry still states its completeness for every entry it can read, and records no surface for the one it does not. | Without this, the first listed entry would turn every GovCloud run into a run that states no completeness. |
| req-aws-collector-partition-12 | A Service Served In Part Is Not Masked | Proposed | A connection failure learned for a (service, region) applies only to entries that would call the endpoint that failed. With the three `agent_*` entries unlisted and failing, `lens`, `profile`, `review_template` and `workload` are still called and collected. | Today the first failure marks the whole service: with the list emptied, a probe run made one `wellarchitected` call and settled all seven entries as not offered. The list covers the known case; an unlisted service served in part is still masked until this is built. Keying by the failing endpoint's host is one way. |
| req-aws-collector-partition-13 | Endpoint Probe Checks The Claims | Proposed | In a run, the collector works out the host a call for an entry would be sent to (the request is built unsigned and stopped before it is sent, so no credential is needed; the client's default endpoint is not that host) and resolves it. It records `PARTITION_GAP_LEARNED` (once per service and region) when the host has no record and the entry is not marked `not_offered`, and `PARTITION_LIST_STALE` (once per marked entry) when a marked entry's host resolves. An entry one call cannot read (a parent to fan out from, a custom function, a required parameter it lacks) is not probed and the probe says nothing. The probe never skips a call and never makes one. Every run records one `ENDPOINT_PROBE` info line with whether the probe was usable and the hosts checked, gaps and stale claims found, and entries it could not probe, so a run that found nothing is distinguishable from one whose DNS could not be trusted. It first resolves the host of STS, which the run has already called; if that does not resolve, the probe is disabled for the run and records nothing. | A first build used each client's default endpoint and was wrong in all five warnings of the 2026-11-04 full run: `s3control`, `iottwinmaker` and `location` carry a host prefix per operation, `wellarchitected`'s agent operations go to `wellarchitected-agent`, and `kinesisvideo`'s FIPS client reports one host and calls another. The lookup is a detector: a collector behind a proxy or on private DNS may not resolve public hosts, which is why a failed lookup alone is never a reason to skip. Each host is looked up once per run. |
| req-aws-collector-partition-14 | Botocore Cannot Contradict A Documented Claim | Proposed | A test fails when a manifest entry's `not_offered` block rests on `web`, `read` or `inferred` evidence and botocore's own endpoint data lists the service for that partition; a block marked `ran` rests on a live failed call and is not held to botocore. | Botocore's silence proves nothing (it synthesises hostnames) and its listing does not prove a service is reachable: seven of the ten services wave 0 could not reach in GovCloud are listed by it. The test runs on every botocore bump. |
| req-aws-collector-partition-15 | A Block May Hold In One Region Or One FIPS Setting | Proposed | A `not_offered` block may carry `regions` (the regions of the partition it holds in) and `fips` (`true` or `false`: only with FIPS endpoints on, or only off). With neither it holds for the whole partition, as before. A block limited to regions is applied inside the region loop: the entry makes no call in those regions, records one `SERVICE_NOT_AVAILABLE_IN_PARTITION` line naming the region, and is called in the others; a block limited by `fips` is applied when the run's FIPS setting matches. The endpoint probe checks a marked entry in every region the block covers, and reports `PARTITION_LIST_STALE` when its host resolves there. A conditional block is not a whole-service listing. The collector always passes the effective FIPS setting (the secret, else the environment, else the shared config, resolved to a boolean); a call that does not know the setting (`None`) is not guessed at: a block limited by `fips` does not apply and the entry is called. `wave0_smoke.py` applies region-limited blocks per region. | `tools/validate/availability_matrix.py` looked up the host of every service one call can read, in us-gov-west-1 and us-gov-east-1 with FIPS off and on (`runs/availability-matrix-2026-11-05.json`, DNS only, no AWS call): 15 services resolve in gov-west and not in gov-east, 9 have no FIPS host in either region, bedrock-agent has none at the gov-east FIPS host, and kinesisvideo resolves only at its FIPS host. `tools/validate/availability_calls.py` then made one signed read call per service in each of the four variants (`runs/availability-calls-2026-11-05.json`): 133 of 140 agreed with the DNS result; the timestream-query and timestream-write gov-east blocks were removed because those calls were answered, and managedblockchain, which has an endpoint in gov-west only (not with FIPS endpoints on), is marked for gov-east. The remaining variant (gov-west with FIPS) needs two conditions at once and is learned at run time; the ratchet carries it as an accepted difference. 124 entries carry such a block. A host that resolves, or a call that connects, says the service has an endpoint, not that every operation works. |

### Listing Outcomes And Client Posture
----
RID: `req-aws-collector-outcome`

Status: `Approved for Development`

A listing that raised is not always a failed call. Four results are kept apart, and only the
first is a failure:

- **failed** — any error no reviewed row names. Recorded as `ENTRY_SKIPPED` (a warning), as before.
- **`not_configured`** — the feature is not set up in this account (DRS and MGN never initialised, no
  QuickSight subscription, S3 Access Grants without an instance, Security Hub V2 or Security Lake not
  enabled). Zero rows, an `ENTRY_NOT_CONFIGURED` info, no warning.
- **`unsupported_in_partition`** — the partition does not offer the service or the operation
  (`EndpointConnectionError`, `UnknownOperationException`, `InvalidAction`,
  `UnsupportedOperation`, a 404 Unknown Operation, "not supported in this region"). A connect timeout is not on
  this list: it shows the endpoint was unreachable, which a transient fault also does, so it stays a failed call
  (bounded by the client's connect timeout). Zero rows, the
  existing `SERVICE_NOT_AVAILABLE_IN_PARTITION` info (carrying `outcome`), no warning. A service whose
  endpoint could not be reached is learned once per (service, region) and its other entries are settled
  without a call.
- **`throttled`** — the service rate-limited past the client's retries. A distinct `ENTRY_THROTTLED`
  warning; never read as empty.

#### Implementation

- **Data, not code, not a broad catch.** `error_outcomes.json` (schema `error_outcomes.schema.json`,
  validated at load by `outcomes.load_rows`) holds one reviewed row per case with a `why`. A
  `not_configured` row must name its service, its error code and its operations or entity types. The
  `unsupported_in_partition` rows apply only in the partitions they were observed in (`partitions`, today `aws-us-gov`; an observation in one partition says nothing about another), always name
  their service (no wildcard) and one of its operations, entity types or, for a connection failure, the exception
  class, and record only what a run observed for that service (the schema refuses a wildcard row). The same error
  code on a service or operation no row names stays a failed call. They are a stopgap until availability is derived
  from data; they are small and meant to be replaced. A transient network fault on a service a row names is read
  the same way, for that run only: the listing is never complete, so nothing is retired on it.
  Throttling is classified from the error code alone.
- **Never an authoritative empty listing.** `Listing.outcome` (region-scoped containment) and
  `ListingWalk.not_observed` (account-scoped) record the outcome; the surface is then
  `enumeration_complete: false`, `admitted: false`, with the named reason, so
  `tap_grid.completeness` derives `reconcilable` false and no candidate is derived: an account that
  has not set a feature up must never license retiring what the grid holds for it. The credential was
  allowed to ask for `not_configured` (`scope_authorized: true`); for the other two it is not determinable.
- **One client `Config`.** `credentials.client_config` is the only place connect timeout (5 s: a regional
  endpoint answers in well under a second), read timeout (60 s) and retry posture (`adaptive`, 8 attempts in all, set as `total_max_attempts` because botocore's `max_attempts` counts retries after the first request:
  client-side rate limiting absorbs a fan-out's burst, and the budget stays finite) are set. Every client
  the collector builds takes it, and it is the session's default client config so a client a `custom_fn`
  builds directly has it too. botocore has no separate budget for connection errors, so an endpoint that
  never answers costs at most ~8 connect timeouts plus backoff per (service, region), about a minute,
  where botocore's defaults cost ~312 s per entry (Inspector classic, GovCloud, measured).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-outcome-1 | Reviewed Data Rows | Approved for Development | An error is a `not_configured` or `unsupported_in_partition` result only where a row of `error_outcomes.json` matches its service, error code or exception, operation or entity type, and message text; every row has a `why`, and a `not_configured` row cannot omit its service, code or operation. An unmatched error fails the listing as before. | `tests/test_boto3_collector_outcomes.py::TestTheShippedRows`, `::TestClassify` |
| req-aws-collector-outcome-2 | Empty Plus Info | Approved for Development | A matching listing yields zero rows and an info (`ENTRY_NOT_CONFIGURED`, or `SERVICE_NOT_AVAILABLE_IN_PARTITION` with `outcome`), never an `ENTRY_SKIPPED` warning. | `::TestCollectorRun::test_a_mapped_error_is_empty_plus_an_info_and_not_a_complete_listing` |
| req-aws-collector-outcome-3 | Not A Complete Empty Observation | Approved for Development | A named outcome makes the listing's completeness surface `enumeration_complete: false` and `admitted: false` with the reason, region-scoped and account-scoped alike, so it licenses no retirement. | `::TestCompletenessConsequence` |
| req-aws-collector-outcome-4 | Throttling Is Named | Approved for Development | A throttling error that outlasts the client's retries is `throttled`: an `ENTRY_THROTTLED` warning and an incomplete surface, never an empty one. | `::TestCollectorRun::test_a_throttled_listing_is_a_named_warning_and_not_an_empty_one` |
| req-aws-collector-outcome-5 | Unreachable Learned Once | Approved for Development | An unreachable endpoint (outside commercial) is recorded `unsupported_in_partition` and the service's remaining entries in that region are settled without a call. | `::TestCollectorRun::test_an_unreachable_service_is_learned_once_not_once_per_entry` |
| req-aws-collector-outcome-6 | One Client Config | Approved for Development | Every collection client has an explicit connect timeout, read timeout and finite adaptive retry budget from `credentials.client_config`; no module builds its own retry `Config`. | `::TestClientConfig` |

### GRIFT Batch Assembly
----
RID: `req-aws-collector-grift-batch`

Status: `Approved for Development`

One collection run assembles one GRIFT batch carrying all collected nodes and
edges, submitted through the approved import surface.

#### Implementation

- One batch per run. The `batch_node` records provenance: collector source
  identity, AWS account id, regions swept, manifest version, and per-type
  counts, in a structured `description_json` (mirroring the KSI collector's
  provenance shape, in `aws_core`'s own format).
- Nodes and edges are named by ref and natural key, never by an id the
  collector derives ([Identity By Natural Key](#identity-by-natural-key)).
- The document is submitted via `self.submit_grift(...)`; the returned result's
  imported/skipped batch ids and counts inform `self.summary`.
- No deletion, tombstone, or implied-absence content appears in the batch
  (`req-aws-collector-scope-3`).
- Dangling-edge handling uses GRIFT's permissive mode: an endpoint named by
  natural key resolves to the batch's node or the live grid's row, so most
  cross-resource edges resolve even when emitted before their target; one that
  names nothing is skipped and recorded as a `skip` event.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-grift-batch-1 | One Batch Per Run | Approved for Development | A run produces a single GRIFT batch. | Proposed to be superseded for fan-out runs by `req-aws-collector-fanout-6` (one batch per account per run). A single-account run is unchanged. |
| req-aws-collector-grift-batch-2 | Provenance Recorded | Approved for Development | The batch records account, regions, manifest version, and counts. | |
| req-aws-collector-grift-batch-3 | Approved Surface Only | Approved for Development | Submission is via `self.submit_grift`. | |
| req-aws-collector-grift-batch-4 | No Deletion Content | Approved for Development | The batch contains no deletion/tombstone semantics. | |

### Edge Authority Claims
----
RID: `req-aws-collector-edge-authority`

Status: `Implemented`

tap's `req-grid-reconcile-edge-authority` lets a batch state that, for an edge type at an anchor node
in one direction, its edges are the whole set, and proposes removing every other live edge in that
scope. Only a claim whose `read` is `complete` proposes anything. This requirement is the producer
side for aws_core (aws-core-tap#77, child C10 of tap#911): every reader that feeds a manifest edge
rule says, per anchor, how it read the rule's source, so that "found nothing" and "could not look"
are never the same value.

#### Implementation

- **Three values.** `complete` (every source the scope draws on answered in full), `partial` (an
  answer that is not all of it: a final page that still says more, a reference the collector could
  not map to a target, a value it could not interpret), `failed` (a call the scope depends on
  errored or was denied). Code: `collectors/boto3_collector/authority.py`.
- **How a rule is judged.** A rule that reads a hydrate slot takes the slot's status (`ok` and
  `absent` are complete; `denied`, `error` and a missing slot are failed). A rule that reads a key a
  `custom_fn` declared in the item's `_edge_reads` map takes that declaration; any other key of a
  `custom_fn` item is `partial` (a reader that did not say how it read a key is not trusted to have
  read it all). An `aws_op` item is the API's own record of the resource and is `complete`. A
  transform that returns nothing for a non-empty reference makes a complete read `partial`, except
  the two transforms that filter out-of-scope values on purpose (a non-S3 CloudFront origin, an
  AWS-managed policy). A rule whose target type is not modelled is `partial`.
- **The Organizations tree's reference edges.** The Organizations reader is not a manifest entry,
  so it judges its own reads (`collectors/boto3_collector/organizations.py`, "Edge authority";
  aws-core-tap#88). Two scopes, both outbound from the anchor:
  - `NESTED_UNDER_PARENT` at every account and OU the run writes. AWS gives each exactly one parent,
    so the batch's one edge is the whole set when the read that found it is whole. An OU's parent is
    the `ListOrganizationalUnitsForParent` listing that named it (AWS has no operation that
    re-parents an OU). An account's is complete only when the whole placement walk was: every OU
    listing and every `ListAccountsForParent` read to its last page, no OU refused by its model (its
    accounts were never listed), and the account named under exactly one parent. An errored page
    anywhere in the walk is `failed` for every account; an account named under no parent or two (a
    `MoveAccount` between two listings) is `partial`. This is the claim that ends the stale parent
    edge a `MoveAccount` leaves behind.
  - `ATTACHED_TO_TARGET` at every customer-managed policy (SCP and every other enabled policy type)
    the run writes: `ListTargetsForPolicy` read to its last page is the whole set. An errored page
    is `failed`; a target the reader cannot map to a node is `partial`. An AWS-managed policy, or
    one whose `AwsManaged` flag is missing, is never claimed: its ARN names no organization, so its
    one node is shared by every organization in the partition, and tap's scope is every live edge
    at the anchor whoever wrote it.
- **One claim per scope.** All rules of one edge type and direction at one anchor fold into one
  claim with the worst read. The anchor is named by type and full natural key (`{entity_type,
  key}`), read from the envelope the batch sends by the same function the batch's node identity is
  read with (`batch.node_key`), so the anchor and the node are one identity. A scope another manifest entry's
  rules also write into is not claimed. Containment edges (the Organizations tree's
  `PARTITIONED_INTO_OU`, `ENROLLS_ACCOUNT`, `HOLDS_*` and `DECLARES_*` among them), landing-zone and
  findings edges are not claimed: a contained child never moves to another live parent, and its
  removal is the reconcile surfaces' business. Nor is `NESTED_UNDER_PARENT` inbound at a parent: a
  child the model refused is not sent, so a parent's inbound set can be short by a true edge.
  `DELEGATES_TO_ACCOUNT` is fixed by its delegation's own key and never goes stale.
- **Sent only where accepted.** The claims are carried as the batch's `edge_cases.authority` when
  the running tap's GRIFT schema defines that section. The plugin's tap floor (`>=0.3.0`) has it, so
  the check no longer changes what a supported tap receives; on an older tap the claims would be
  judged, logged, and not sent. Either way the run records one
  `EDGE_AUTHORITY_CLAIMS` entry with the counts by read status and the claims that are not
  `complete`.
- **Not deletion content.** A claim removes nothing here: tap's first form is a dry-run that records
  proposals (`req-aws-collector-grift-batch-4` is unchanged).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-edge-authority-1 | Failed Is Not Empty | Implemented | A reader whose sub-call for an anchor raised reports `failed` for every rule that reads it; the anchor's claim is never `complete`. | `eventbridge_rules_with_targets` (a denied `ListTargetsByRule`), the API Gateway sub-listings, the IAM attached-policy slots, the S3 encryption slot. `tests/test_edge_authority.py`. |
| req-aws-collector-edge-authority-2 | Partial Is Not Complete | Implemented | A sub-listing whose last page says more, a reference a transform cannot map, or a document the rule's path cannot walk reports `partial`. | |
| req-aws-collector-edge-authority-3 | Complete And Empty Is Said | Implemented | A read that answered with nothing is `complete` with no edges, distinct from the two above. | |
| req-aws-collector-edge-authority-4 | Fail Closed | Implemented | A `custom_fn` key an edge rule reads that the reader did not declare is `partial`; an unknown status counts as `failed`; no status is ever defaulted to `complete`. | |
| req-aws-collector-edge-authority-5 | One Claim Per Scope | Implemented | A batch carries at most one claim per (edge type, anchor, direction), with the worst read of every rule that contributes. | tap fails a batch with two (`duplicate_authority_claim`). |
| req-aws-collector-edge-authority-6 | Sent Only Where Accepted | Implemented | The `edge_cases` section is written only when the importer's own schema defines it; the run record says whether it was sent. | Drop the check when `requires_tap` reaches a release that has the section. |
| req-aws-collector-edge-authority-7 | Organizations Placement Is Claimed | Implemented | Every account and OU the Organizations reader writes carries one `NESTED_UNDER_PARENT` outbound claim: `complete` only when the read behind its one parent was whole (an OU: the listing that named it; an account: the whole placement walk, and named under exactly one parent); an errored page is `failed`, an account named under no parent or two is `partial`. | aws-core-tap#88: the stale parent edge a `MoveAccount` leaves. `tests/test_organizations_edge_authority.py::TestPlacement`. |
| req-aws-collector-edge-authority-8 | Organizations Attachments Are Claimed | Implemented | Every customer-managed Organizations policy the reader writes carries one `ATTACHED_TO_TARGET` outbound claim from its `ListTargetsForPolicy` read: an errored page is `failed`, an unmappable target `partial`; an AWS-managed policy (shared by every organization in the partition) is never claimed. | `tests/test_organizations_edge_authority.py::TestAttachments`. |

### Run Progress
----
RID: `req-aws-collector-progress`

Status: `Proposed`

Requested by George on 2026-11-04 ("interim logging so that we know that it's cooking"). The run log (`CollectionJob.results`)
is persisted once, when the run ends, so a long run is silent until then. Progress goes to the process log, where it can
be followed as it happens. Built in `progress.py`; tested in `test_boto3_collector_progress.py`.

- **Lines.** A start line (manifest entries, regions, partition, and whether a selection is applied); a heartbeat at most
  once per 30 seconds, written at the start of an entry, naming that entry's service and entity type, the entries finished
  and the percentage, the nodes and edges so far, and the seconds elapsed; a line when the reads end and the batch is
  about to be submitted; a line when the import returns.
- **Counts only.** A line holds counts, an entity type, a partition and seconds. Never an account number, a resource
  id or name, or response content.
- **Limit.** The heartbeat is written between entries, not from a side thread (a thread would outlive an aborted run). During
  one long call nothing is written; the last line names the entry being read.

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-progress-1 | Start, Reads-Finished And Finished Lines | Proposed | A run writes a start line, a line when the reads end and a line when the import returns, to the process log. | Tests read the log records of a real `run()`. |
| req-aws-collector-progress-2 | Throttled Heartbeat | Proposed | A run faster than the interval writes no heartbeat; a slower one writes one per interval, naming the entry about to be read, the entries finished, the nodes and edges so far and the seconds elapsed. | Tests drive a fake clock. |
| req-aws-collector-progress-3 | Counts Only | Proposed | No progress line carries an account number, a resource id or name, or response content. | A test asserts no 12-digit number in the lines of a real run. |

### Audit Verifiability
----
RID: `req-aws-collector-audit-ledger`

Status: `Approved for Development`

**Theme (future).** A later theme makes a collection run *verifiable* — able
to show evidence the grid reflects data actually gathered from AWS at a
knowable time, not merely asserted. The only non-deterministic datum AWS
returns that anchors this is the per-call **request id**
(`ResponseMetadata.RequestId`; S3 also `HostId` / `x-amz-id-2`) plus the
response `Date`. Correlating our recorded request ids and times to the
account's own CloudTrail (`requestID` ↔, `eventTime` ↔ response `Date`) is
contemporaneous proof a call occurred — *not* attestation of the response
body, but the evidentiary spine the verification theme will build on. The
verification machinery itself (matching, attestation, reporting) is out of
v0 scope and is named here only as the future seam this requirement feeds.

**Step one (this requirement).** The collector records a per-run AWS call
ledger as run provenance on the persisted, history-tracked `CollectionJob`
(its `results` log) — never on a resource node, never in the GRIFT batch.

#### Implementation

- Request ids are the canonical reason `ResponseMetadata` is stripped from
  every node / `configuration` / `_hydrate`
  (`req-aws-collector-field-projection-6`): per-call ids change every run
  and would poison node byte-identity. The ledger captures them on the run
  record instead, where per-run variance is expected and carries zero
  idempotent-upsert / History cost.
- Capture is at the boto3 boundary via botocore `after-call` /
  `after-call-error` session handlers (a run-scoped collaborator), so every
  enumerate call, paginator page, fan-out sub-call, and the STS identity
  probe is recorded with no per-resource code and no engine-signature
  change. The `after-call-error` path is the only place a `denied` /
  `throttled` call is observable.
- The ledger is drained once at end of `run()` as a single structured
  `record_info` entry (`message_code` `AWS_CALL_LEDGER`) whose
  `message_data` carries the call array: per call `{service, operation,
  request_id, host_id?, http_status, outcome, response_date}`. One run-log
  event, not one per call — the operator stream stays legible while the
  full machine ledger is captured.
- `outcome` ∈ `ok | absent | denied | throttled | error` — aligned with
  the hydrate classifier, **including `absent`**: AWS's expected "not
  configured" 404 (e.g. `NoSuchBucketPolicy`) is a first-class call
  outcome, never folded into `error`. (Live validation falsified the
  earlier "a call cannot be absent" framing — S3 fan-out is dominated by
  these expected 404s; conflating them into `error` is exactly the
  anti-pattern `req-aws-collector-hydrate-6` forbids.) The `absent`/
  `denied` code rule is shared with hydrate by convention (one dialect);
  factoring a single classifier is a named future cleanup, not v0.
- It lands in `CollectionJob.results` via the existing `record_*` →
  task-body persistence path; this needs **no** new schema — the
  `collection_job_results.schema.json` entry shape already defines
  `message_data` as free-form keyed by `message_code`.
- The ledger is the *complete* call record; `record_warn`
  (`ENTRY_SKIPPED` / `HYDRATE_GAP`) remains the operator-attention subset —
  complementary, never a second source of truth.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-audit-ledger-1 | Run-Record Placement | Approved for Development | The call ledger is on `CollectionJob.results`, never a resource node or the GRIFT batch. | Determinism — why `ResponseMetadata` is stripped elsewhere. |
| req-aws-collector-audit-ledger-2 | Boundary Capture | Approved for Development | Capture via botocore `after-call` / `after-call-error`; every call incl. paginator / fan-out / STS; no engine-signature change. | `after-call-error` is the only `denied` / `throttled` site. |
| req-aws-collector-audit-ledger-3 | Single Drained Entry | Approved for Development | Drained once per run as one `AWS_CALL_LEDGER` `record_info` entry; `message_data.calls` is the array. | Operator stream stays legible. |
| req-aws-collector-audit-ledger-4 | Outcome Vocabulary | Approved for Development | Per-call `outcome` ∈ `ok\|absent\|denied\|throttled\|error`, aligned with the hydrate classifier; AWS "not configured" 404s are `absent`, never `error`. | Live-validated; conflating absent into error is the `req-aws-collector-hydrate-6` anti-pattern. |
| req-aws-collector-audit-ledger-5 | No New Format | Approved for Development | Reuses `collection_job_results.schema.json` (`message_data` free-form by `message_code`); no new schema. | Verification machinery is a future theme, not v0. |

### Resource Tags
----
RID: `req-aws-collector-tags`

Status: `Approved for Development`

Every collected node carries a single canonical `tags` field — a flat
`{str: str}` map — regardless of the wildly varying ways AWS returns tags.
A broad botocore survey (42 services) found ~5 distinct wire shapes; AWS's
unified Resource Groups Tagging API (`resourcegroupstaggingapi:GetResources`,
"RGTA") returns one uniform shape for most resources in a single per-region
sweep.

The strategy is **RGTA-primary with per-service side-quests**, chosen
clean-room from prior-art analysis (Cartography/CloudQuery/Steampipe/Prowler/
ScoutSuite — patterns only, no code). Mature tools distrust RGTA *as a
discovery source* (it returns only ever-tagged resources). That failure mode
**does not bind this collector**: discovery is the per-service enumerate
path (`req-aws-collector-source`); RGTA only *decorates* already-discovered,
already-identified nodes. An untagged resource simply gets
`tags: {}` — the correct answer, not a gap. And because nodes are keyed by
their natural key, which is the ARN for almost all types, the RGTA
`ResourceARN`→node join is identity-equal — it does *not*
reintroduce the `req-aws-collector-edges` ARN↔identity reconciliation
problem (the decisive reason mature ARN-short-id tools suffered it; we do
not).

#### Implementation

- A per-entry optional manifest `tags` block declares the source:
  - `{"source": "rgta"}` — the default. Tags come from the per-region RGTA
    sweep, joined by ARN.
  - `{"source": "service", "op": …, "params": {<param-name>: {…spec…}, …},
    "path": …, "shape": "list_kv"|"map"}` — a side-quest: a per-resource
    tag op resolved through the [Fan-Out Hydrate Seam](#fan-out-hydrate-seam)
    (no new mechanism). `params` is a dict mapping the boto3 keyword-arg
    name to a per-arg spec, where each spec is either `{"literal": "…"}`
    (a constant value) or `{"from": "<path>"}` (a path into the item).
    Most ops take a single identifier param (e.g. `ListRoleTags →
    {"RoleName": {"from": "RoleName"}}`); the multi-param form supports
    APIs that mix constants with per-item identifiers
    (e.g. `route53:ListTagsForResource → {"ResourceType": {"literal":
    "hostedzone"}, "ResourceId": {"from": "_zone_resource_id"}}`).
    Quarantined complexity, per `req-aws-collector-source-4`.
  - Absent `tags` block → the type carries no tags (declarative; never
    hidden code).
- **RGTA path.** One paginated `GetResources` per swept region, scoped by
  `ResourceTypeFilters`, building an `ResourceARN → [{Key,Value}]` map; each
  node's tags are `map.get(arn_for(node), {})` where `arn_for` is the node's
  `natural_key` directly, or a small declared ARN→key transform where they
  differ (CloudWatch log-group trailing `:*`; Route 53 hosted-zone
  `arn:aws:route53:::hostedzone/<id>` → bare id). Reuses the existing
  transform registry.
- **Side-quest path (v0).** `aws_iam_role` (RGTA *explicitly excludes* IAM
  roles) via `iam:ListRoleTags`; `aws_cloudfront_distribution` (CloudFront
  documents Tag Editor / Resource Groups as unsupported, contradicting the
  RGTA service list — do not trust RGTA) via
  `cloudfront:ListTagsForResource`; `aws_route53_zone` via
  `route53:ListTagsForResource` (RGTA excludes; multi-param call —
  `ResourceType="hostedzone"` literal + `ResourceId` from a bare-zone-id
  field the `custom_fn` adds to each item as `_zone_resource_id`);
  `aws_iam_oidc_provider` via `iam:ListOpenIDConnectProviderTags` (single
  ARN param). Other resource types follow the same shape as those need
  arises.
- **One canonical normalizer.** A single engine seam folds any declared
  shape (`list_kv` `[{Key,Value}]` → `{Key:Value}`; `map` → as-is) into the
  `{str: str}` field. Never a per-service loop — that is the drift-prone
  Steampipe-style boilerplate the prior-art analysis flagged; the
  CloudQuery single-helper pattern is the model. Raw-retention follows the
  `tags`/`tags_raw` discipline but is path-aware: the variable-shaped
  **side-quest** path retains the raw response losslessly via the
  `_hydrate` envelope (with the `ok|absent|denied|error` slot status),
  stored when the entry's `persist_configuration` is true;
  the **RGTA** path needs no separate raw store because RGTA's
  `list_kv`↔`map` is information-preserving (AWS tag keys are unique per
  resource, values are strings) — the canonical `{str:str}` map is itself
  the lossless form.
- **Per-model field, no spine.** `tags` is a `JSONField(default=dict)` on
  each `aws_core` model — same field name and canonical shape across the
  model family, so "everything `Owner=X` across `aws_*`" is a normal field
  query *by convention*. It is **not** an Entity-spine facet: `dimensions`
  is already the spine's key/value system, and AWS tags are mutable
  source-owned descriptive metadata that must never silently re-partition
  the grid (`req-grid-*` scoping is dimension-owned).
- **Home-region invariant.** Global resources (IAM, CloudFront, Route 53)
  and CloudFront-bound ACM certificates appear in RGTA only in the per-region
  results of the partition's home region for global services — `us-east-1`
  commercial, `us-gov-west-1` GovCloud ([AWS Partitions](#aws-partitions)).
  The region scope **must** include it or those tags are silently missed; the
  run warns (`REGION_INVARIANT`) when it is absent. A partition with no settled
  home region has no invariant to warn about.
- **RGTA operational contract.** `PaginationToken` is valid ≤ 15 minutes
  (`PaginationTokenExpiredException` → restart the sweep, never resume
  mid-iteration); `ThrottledException` → bounded backoff; per-region,
  per-account; `ResourceTypeFilters` only (never `ResourceARNList`) for
  sweeps. RGTA is a tag-presence index, eventually consistent — the
  per-service enumerate remains authoritative for existence; RGTA only
  decorates.
- The v0 shape enum is fenced to `list_kv | map` (covers all of Sam's 8).
  The known outliers — ECS lowercase `key`/`value`, CloudTrail per-resource
  nesting, WAFv2 wrapped — are real but out of scope, named as a future
  enum extension, not built.

#### Landing-Zone Amendments (Proposed)

Ruling (George, 2026-09-30): the mechanism above **is** the tag normalization. The
landing-zone epic adds no tag keys, no tag vocabulary and no tag-to-dimension mapping, and touches
no dimension. What it changes is limited to making the spec say what the code does, declaring the
one tag path that lives outside the manifest, and holding every type the epic adds to the contract.
The rulings of 2026-10-01 are encoded below as decided.

- **Three lanes, not two.** The manifest schema has carried a third lane since the field-lane work:
  `{"source": "field", "from": <path>, "shape": "list_kv"|"map"}`, normalizing tags the enumerate
  item already carries (`aws_resource_manifest.schema.json` `$defs/tags_block`, `oneOf[0]`;
  `collector.py:167-168`). Ten of the 23 entries use it, including VPC, subnet, EC2 instance and security
  group. `-1` names only `rgta|service`; `-9` states all three, plus the `none` and `owned_by` declarations below.
- **The Organizations lane.** `organizations.py` is not a manifest entry, and it calls
  `normalize_tags(raw, "list_kv")` from its own code (`organizations.py:431`) for OU, account and
  customer-managed SCP tags. Under `-1` ("no hidden per-service code") that path is undeclared.
  `-10` declares it, so it is a named lane and not hidden code. The epic routes the root's tags and
  every new Organizations policy type through the same `tags_of` (`organizations.py:387-431`).
  Account tags set through Organizations (for example by Gruntwork's `control-tower-account-tagger`,
  outside Terraform state) stay in `aws_account.tags` (ruling 2026-10-01). They are not a second tag
  system and are not moved to the membership node.
- **A type AWS cannot tag declares it.** Today "no `tags` block" means "carries no tags" (`-1`), and
  reads the same as "forgot to declare". The schema gains a fourth variant,
  `{"source": "none", "why": <non-empty string>}` (ruling 2026-10-01), so that every manifest entry
  declares a tag lane and a test can require one (`-12`). Routes, NACL entries, TGW routes,
  route-table, NACL and Elastic IP associations, resolver endpoint IPs, resolver-rule associations,
  Config delivery channels, Identity Center groups and assignments, delegations and memberships use
  it.
- **A type with no manifest entry still declares its lane.** Several types are not enumerated by a
  manifest entry of their own: they are emitted from a parent's entry (routes from
  `DescribeRouteTables`, NACL entries from `DescribeNetworkAcls`, TGW routes per route table) or by a
  custom reader (the Organizations reader's organization, OUs, accounts, memberships, delegations,
  policies, policy statements and tag-policy rules). A manifest-entry test cannot see them. So the
  declaration is made per **(entity type, emitting path)**, not per manifest entry. A path is a
  manifest entry or a named custom reader (`organizations`, and each reader the epic adds). A
  manifest entry declares in its own `tags` block. A reader declares in one manifest-adjacent
  registry, `collectors/boto3_collector/tag_lanes.json`, keyed by entity type and reader. Its rows
  hold a `tags_block` validated by the same schema `$defs`, or `{"source": "organizations"}`, which
  names `-10`'s lane.
- **A type with two writers declares both, and one owns the tags.** `aws_account` is emitted by
  two paths: the manifest's `aws_account_singleton` entry and the Organizations reader. Account tags
  come only from Organizations (ruling 2026-10-01). Neither `none` (the type is taggable) nor a
  second reading lane is true of the singleton. So the schema gains one more variant,
  `{"source": "owned_by", "lane": <lane>, "why": <non-empty string>}`. It means "this path does not
  read this type's tags; the named lane does". The singleton entry declares
  `{"source": "owned_by", "lane": "organizations", ...}`, and the Organizations reader declares
  `{"source": "organizations"}`. Today `aws_account` is the only type with two emitting paths
  (`-14`).
- **The `service` lane reads every page.** The lane makes one hydrate call (`collector.py:176-186`;
  `hydrate_item` calls the operation once, `hydrate.py:91`) and normalizes that one response. Several
  tag operations the epic adds are paginated in botocore's own paginator data:
  `sso-admin:ListTagsForResource` (`NextToken`), `config:ListTagsForResource` (`NextToken`, `Limit`)
  and `route53resolver:ListTagsForResource` (`NextToken`, `MaxResults`). So are the existing IAM
  lanes, `ListRoleTags` and `ListOpenIDConnectProviderTags` (`Marker`, `IsTruncated`). Control Tower,
  Security Hub, CloudFront and Route 53 `ListTagsForResource` have no paginator (read: botocore
  1.43.103 `paginators-1.json`, the local copy; the spec's pin is 1.43.104). One call silently drops
  every tag after the first page, and a path-and-shape check accepts it. `-15` requires the lane to
  read to the last page for every operation botocore paginates.
- **AWS-reserved keys stay in the one map** (ruling 2026-10-01). Tags under the `aws:` prefix (for
  example `aws:cloudformation:stack-name`) are written by AWS, cannot be changed by the owner, and
  arrive in the same wire lists as operator tags. `normalize_tags` keeps them verbatim in the same map
  (`tags.py:39-50`); nothing filters them. `-11` states that as the contract, so a reader of `tags`
  knows such keys are provenance stamped by AWS, not operator intent. Control Tower's
  `aws-control-tower` key and Gruntwork's org-prefixed keys are not under `aws:` and are ordinary tags.
- **New types.** Every type the epic adds carries the `tags` field and declares its lane (`-13`).
  The wire shapes were read from botocore 1.43.104's service models (offline data, not a live
  call): every new taggable type returns tags either as a list of `{Key, Value}` (`list_kv`) or as a
  string map (`map`). ENIs carry theirs under `TagSet`, not `Tags`; Control Tower and Access
  Analyzer under a lowercase `tags` map. Both are a path difference, not a shape. **No shape-enum
  extension is needed for this epic**; `-8` stays as written.
- **A failed tag read is still written as `{}`: a named defect with a core dependency, not a task
  here.** `batch.py:79` writes `"tags": tags or {}`, and `collector.py:166` returns `{}` for a node
  whose region's RGTA sweep failed (`collector.py:375-381` records `RGTA_SWEEP_SKIPPED` and
  continues). The KMS, SQS and CloudTrail custom functions do the same when their tag call fails
  (`customfns.py:897-898`, `:929-930`, `:972-973`). GRIFT upsert resets an omitted field, so omitting
  `tags` does not preserve the stored value either. Only the Organizations reader avoids the false
  empty today, by withholding the node (`organizations.py:387-451`). The general fix needs a write
  that leaves a field "not observed" instead of replacing it, which is core's GRIFT replacement
  semantics work (unified-systems-com/tap#886, its GRIFT write-semantics track). aws_core takes no
  interim withhold-everything rule. Fan-out repeats the defect in every member account, so it is
  named here and in `req-aws-collector-fanout`. Item 1 of unified-systems-com/aws-core-tap#60
  records the same defect. The partition home-region change to `-6` belongs to that issue's fix and
  is not restated here.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-tags-1 | Declarative Source | Approved for Development | A manifest `tags.source` ∈ `rgta\|service` declares per-type tag retrieval; absent ⇒ no tags. No hidden per-service code. | Names two of the schema's three lanes; see `-9`. |
| req-aws-collector-tags-2 | RGTA Default Path | Approved for Development | One paginated per-region `GetResources` sweep, `ResourceTypeFilters`-scoped, joined to nodes by ARN (`natural_key` or a declared transform). Untagged ⇒ `{}`, correct (discovery is independent). | RGTA never drives discovery. |
| req-aws-collector-tags-3 | Side-Quest Path | Approved for Development | `service` sources resolve via the hydrate seam with a `params` dict (each entry `{literal:…}` or `{from:<path>}`) so multi-param tag APIs are first-class; v0 = `aws_iam_role` (`ListRoleTags`), `aws_cloudfront_distribution` (`ListTagsForResource`), `aws_route53_zone` (`ListTagsForResource`, multi-param), `aws_iam_oidc_provider` (`ListOpenIDConnectProviderTags`). | RGTA excludes IAM roles, Route 53 zones, and IAM OIDC providers; CloudFront unsupported. |
| req-aws-collector-tags-4 | One Canonical Normalizer | Approved for Development | A single engine seam folds any declared shape → `{str:str}`; no per-service loops; raw retained losslessly. | CloudQuery pattern; not Steampipe boilerplate. |
| req-aws-collector-tags-5 | Per-Model Field, No Spine | Approved for Development | `tags` `JSONField` on each `aws_core` model, uniform name+shape; never an Entity-spine facet. | Cross-resource query by convention. |
| req-aws-collector-tags-6 | Home-Region Invariant | Approved for Development | Region scope must include the partition's home region for global services (`us-east-1` commercial, `us-gov-west-1` GovCloud); the run warns (`REGION_INVARIANT`) if absent, or global / CloudFront-cert tags are silently missed. | Was a literal `us-east-1` before GovCloud entered scope (`req-aws-collector-partition`). |
| req-aws-collector-tags-7 | RGTA Op-Contract | Approved for Development | 15-min pagination-token TTL (restart, not resume), throttle backoff, `ResourceTypeFilters` only; RGTA decorates, never authoritative for existence. | Eventually consistent. |
| req-aws-collector-tags-8 | Shape Enum Fenced | Approved for Development | v0 `shape` ∈ `list_kv\|map` (all of Sam's 8); ECS / CloudTrail / WAFv2 outliers named as a future extension, not built. | |
| req-aws-collector-tags-9 | Declared Lanes | Proposed | A manifest entry's `tags.source` ∈ `field\|rgta\|service\|none\|owned_by`, matching `aws_resource_manifest.schema.json`. `field` normalizes a path into the enumerate item with a declared `shape`; `none` carries a non-empty `why` and means the type carries no AWS tags; `owned_by` names another path's lane that owns this type's tags (`-14`). The reading lane `organizations` is not a manifest value: it appears only in `tag_lanes.json` rows, for the Organizations reader (`-10`). | Supersedes `-1`'s two-lane wording on approval. `none` is new schema (`-12`). |
| req-aws-collector-tags-10 | Organizations Lane Declared | Proposed | The Organizations reader is the one tag path outside the manifest: `organizations:ListTagsForResource`, shape `list_kv`, for the root, OUs, accounts and customer-managed policies of every type it reads, through `normalize_tags` and the `tags_of` unread sentinel (an unreadable tag set withholds the node, as today). Account tags read here are written to `aws_account.tags`. No type the epic adds folds tags by hand. | `organizations.py:80,431`. Ruling 2026-10-01: Organizations account tags stay on the account. Existing debt, named and not fixed here: two custom functions fold tags by hand before the `field` lane sees them, KMS from `[{TagKey, TagValue}]` (`customfns.py:890-895`, a wire shape outside the `-8` enum) and CloudTrail from nested `ResourceTagList[].TagsList[]` (`customfns.py:966-971`). Both bypass `-4`'s single normalizer. |
| req-aws-collector-tags-11 | AWS-Reserved Keys Kept Verbatim | Proposed | Tag keys under the AWS-reserved `aws:` prefix are kept verbatim in the same `tags` map as operator tags, never filtered, renamed or moved. | States today's behaviour (`tags.py:39-50`). Ruling 2026-10-01. |
| req-aws-collector-tags-12 | Untaggable Is Declared | Proposed | The manifest schema's `tags_block` accepts `{"source": "none", "why": <non-empty string>}`, and every manifest entry declares a `tags` block; a test fails on an entry with none. Existing entries without a block gain a lane or `none` in the same change. | Ruling 2026-10-01. A schema change to the tag mechanism; no tag key or dimension changes. |
| req-aws-collector-tags-13 | Every New Type Declares Its Lane | Proposed | Every type added by `req-aws-collector-fanout`, `req-aws-core-network-plane`, `req-aws-core-organizations-completeness`, `req-aws-core-organization-membership` or `spec-aws-core-landing-zone.md` carries the `tags` field (`req-aws-core-fields-4`) and declares its lane, or `none` for a type AWS cannot tag. For `field` and `service` lanes a test resolves the declared tag path and shape against the pinned botocore output shape, as `req-aws-collector-manifest-6` does for sensitivity paths. | Shapes read from botocore 1.43.104: no `-8` extension needed. |
| req-aws-collector-tags-14 | Every Emitted Type Declares, Once | Proposed | Every (entity type, emitting path) the collector emits declares a tag lane exactly once: a manifest entry in its own `tags` block, a custom reader in `collectors/boto3_collector/tag_lanes.json` (rows validate against the manifest schema's `tags_block`, or are `{"source": "organizations"}`). The schema accepts `{"source": "owned_by", "lane": <lane>, "why": <non-empty>}` for a path that does not read a type's tags because another path's lane does. For each entity type, exactly one emitting path declares a reading lane, or every path declares `none`; every other path declares `owned_by` naming that lane. A test collects from the full fake source and fails on any (type, path) with no declaration or two, and on a type with two reading lanes; a second test fails on a registry row naming a type that is not an aws_core model. | Makes `-12` and `-13` enforceable for routes, NACL entries, TGW routes, memberships, delegations, policies, statements and tag-policy rules, which have no manifest entry. |
| req-aws-collector-tags-15 | Service Lane Reads Every Page | Proposed | For every `service`-lane operation that the pinned botocore's paginator data lists, the lane follows the continuation token to the last page and normalizes the union of all pages. A failure on any page makes the slot `error`, exactly as a first-page failure does; the pages read so far are never written as the resource's tags. A test per such operation feeds a fake client two pages joined by a continuation token and asserts tags from both pages land, and a second test fails the second page and asserts the slot is `error`. | Today one call (`collector.py:176-186`). Paginated in botocore 1.43.103: `sso-admin`, `config` and `route53resolver` `ListTagsForResource`; IAM `ListRoleTags`, `ListOpenIDConnectProviderTags`. |
| req-aws-collector-tags-16 | An Unread Tag Set Is Omitted | Implemented | A tag read that fails, is refused, or is skipped (a `service` call whose status is `denied` or `error`, an RGTA sweep that failed for the node's region, a custom function whose own tag call failed and set `_tags_unread`) resolves to `UNREAD` and the node envelope leaves `tags` out; a successful read of an untagged resource sends `{}`. Core >= 0.3.1 (keep-absent upsert, tap#1128) then leaves the stored tags alone. | aws-core-tap#111. `tags` is nullable and defaults to null on every model (migration 0021): a resource first seen on an unread run stays null, "not read", never `{}`. Organizations and landing-zone readers withhold the node instead. `tests/test_tags_unread.py`; end to end in `test_boto3_collector_slice.py`. |

### Multi-Account Fan-Out
----
RID: `req-aws-collector-fanout`

Status: `Proposed`

One run collects every member account of an AWS organization from one credential in the
organization's **management account**, by assuming a read-only role in each member. This is the
path to a landing zone's member accounts. A Gruntwork landing zone is AWS Control Tower
([AF-LZ](https://docs.gruntwork.io/2.0/docs/accountfactory/prerequisites/awslandingzone)) with tens of accounts, and today a run reaches one of them.

#### Status Details

Proposed by the landing-zone epic, step 2. Ruling (George, 2026-09-30): the first GovCloud run uses
**static access keys for a read-only IAM user in the GovCloud organization's management account**,
with FIPS optional for the first run (Q103c). Endpoint FIPS is the operator's existing opt-in,
`use_fips_endpoint` (`req-aws-collector-partition-6`, defined on the fix-pack branch). This
requirement sets no default for it, and the first run's setting is an operator decision recorded
with that run. It is AWS SDK endpoint selection only, independent of TAP's FIPS-validated
cryptographic module. Fan-out from the organization is therefore the only path to
member accounts. Depends on unified-systems-com/aws-core-tap#14 (assigned identity) before any
reconcile is armed, and on `req-aws-collector-partition`, which the code cites and which the fix for
unified-systems-com/aws-core-tap#60 defines (part of unified-systems-com/aws-core-tap#51; not yet on
main when this section was written).

**Sequencing (binding).** Two orderings are part of this requirement:

- **Fan-out writes land only after core's field preservation.** No release writes fan-out batches
  until unified-systems-com/tap#886 gives GRIFT a write that leaves a field "not observed" instead
  of resetting it. Without it, every skipped or rejected member erases its own account-sourced
  fields (`-16`), and fan-out repeats the tag false-empty write in every member.
- **The membership lands before account → footprint containment.**
  `req-aws-core-organization-membership` (step 8, unified-systems-com/aws-core-tap#68) ships before
  `req-aws-core-account-footprint`. Until the membership exists, `AccountFalsifier` can retire an
  account, and footprint containment would extend that cascade to the account's whole regional
  network plane.

Epic unified-systems-com/aws-core-tap#62 states both constraints in its checklist.

#### Why the current shape cannot do this (read, aws_core@d5b1cf8)

- The secret ref is one module constant, `SecretRef(scope="aws_core", key="boto_collector")`
  (`collectors/boto3_collector/credentials.py:64`), resolved once per run (`collector.py:253`).
- The `aws_assumed_role` kind assumes exactly one `role_arn` (`credentials.py:339-371`).
- The Organizations reader discovers every member and writes it as a node, and nothing consumes the
  list (`collector.py:608-654`).
- The falsifiers resolve the same one secret, so in a multi-account grid every candidate outside
  that account is `UNDETERMINED(scope_unknown)` (`falsifiers.py:449-485`).

#### Implementation

**Order of a fan-out run.**

1. Resolve the base credential (`req-aws-core-secret-member-fanout`), the region scope and the
   partition exactly as today, then STS-identify the base account.
2. Read the Organizations tree with the base credential (`organizations.py`). Fan-out runs only when
   `DescribeOrganization` reports the base account as `MasterAccountId` and the organization-wide
   `ListAccounts` read to its end. Otherwise the run records `FANOUT_NOT_POSSIBLE` with the reason and
   collects the base account alone, as today.
3. Collect the base account with the manifest engine, as today.
4. For each member account `ListAccounts` returned, in account-id order: skip it with a recorded
   reason if its `State` is not `ACTIVE`, if it is the base account, or if the secret's exclude list
   names it. Otherwise call `sts:AssumeRole` on
   `arn:<partition>:iam::<member id>:role/<member_role_name>`, where `<partition>` is the run's
   resolved partition and never a literal (`aws`, `aws-us-gov`). Assert on land: the assumed
   session's `GetCallerIdentity` account must equal the member id. Then read that member's region
   facts and run the manifest engine against it with the run's region scope.
5. Submit one GRIFT batch per account and record that account's completeness surfaces against its
   own batch. A member skipped before collection (not `ACTIVE`, excluded, `AssumeRole` denied,
   identity mismatch) submits no batch: its result's batch id is `null`. Its account node is
   observed this run (the tree envelope in the base batch), so it records a not-authorized surface
   for each containment edge type on that account, carrying `applied_batches: []`. It records no
   surface for parents below the account (its footprints and their children), because this run
   did not observe them (`req-aws-core-contained-type-triple`). A member whose batch was submitted and rejected cites that batch, and
   core derives `applied: false` from it (`tap_grid/completeness.py`, `applied` is derived from the
   cited batches, never authored).

**Member role: a dedicated read-only role** (ruling 2026-10-01). Fan-out assumes a role created for
it in every member account, never an administrator role:

- **Trust:** only the collector's principal in the management account (the base credential's IAM
  user), and only when the call presents the External ID. The External ID is required, consistent
  with aws_core's existing cross-account rule (`req-aws-core-secret-aws-assumed-role-2`), even though
  base and members share one organization.
- **Permissions: one repo-owned, least-privilege read-only policy, and no AWS-managed policy.**
  AWS changes its managed policies on its own schedule (`SecurityAudit` included), and a change to
  one would widen every member role in every estate without review. So the member role carries only
  `collectors/boto3_collector/handoff/member-read-policy.json`. That policy is generated from the
  manifest's operations and each custom reader's declared call list: the same list `-12`'s test
  checks calls against. The generator maps each API operation to its IAM action through a declared
  table, for the operations whose action name differs from the API name.
  **Every call declaration names its execution context.** `context: base` marks a call made only
  with the base (management) credential: the Organizations reader, Control Tower, Identity Center
  administration (`sso-admin`, `identitystore`), and the fan-out's own `sts:AssumeRole`.
  `context: account` marks a call made in every account session, base and members alike: the
  manifest engine's entries, region facts, and the per-account security services and settings.
  The member policy is generated **only** from `account`-context declarations. A base-only action
  is never granted to the member role (`-20`).
  **Falsifier probes are calls too.** A falsifier reaches a member through the same member role
  (`-9`), and its probe is often not a collection call. For example, resolver-rule associations are
  collected with `ListResolverRuleAssociations` but probed with `GetResolverRuleAssociation`. So
  every registered falsifier declares its probe calls with a context, in the same declared call set
  the policy is generated from. A probe left out of the policy would be denied on every candidate
  and could never retire one (`-22`).
  **The gate is an allowlist, not a name pattern.** A prefix rule ("begins with `Get`") with a
  denylist does not fail closed: `codecommit:GetFile`, `ecr:GetDownloadUrlForLayer` and
  `ssm:GetDocument` all pass it and read content. So the generator reads a committed, reviewed
  allowlist of metadata actions, `collectors/boto3_collector/handoff/member-read-actions.json`.
  Each entry is one IAM action with a one-line `why` saying what metadata it reads. Generation
  **fails** when a declared call maps to an action that is not on the allowlist. Adding a call
  therefore needs a reviewed allowlist entry first. The committed policy is the allowlisted
  actions the declared calls need, regenerated in CI and failing when stale (`-17`). Two further
  tests run over the allowlist itself, as sanity checks rather than the gate: every entry's name
  begins with `Describe`, `List`, `Get`, `BatchGet` or `Search` unless its `why` says why not, and
  no entry is on the data-plane denylist (`-18`). The 2026-10-01 ruling, a dedicated read-only
  role, stands; this is how "read-only" is enforced.
- **Deployment:** per account, through the account baseline: an organization StackSet or the
  Gruntwork account baseline, attaching the repo-owned policy above and nothing else (Gruntwork's
  `cross-account-iam-roles` module already ships a comparable role,
  `allow-read-only-access-from-other-accounts`;
  [SEC-MODS](https://github.com/gruntwork-io/docs/tree/main/docs/reference/modules/terraform-aws-security/)).
- **Name:** operator-declared (`member_role_name`), a plain role name with no path (the role is
  deployed at the root path `/`; `req-aws-core-secret-member-fanout-2`), never defaulted in code, so an estate can use the
  name its baseline deploys.
- **Not used:** `OrganizationAccountAccessRole`, the administrator role `CreateGovCloudAccount`
  creates in each member ([C-GCORG](https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-organizations.html)), and
  `AWSControlTowerExecution`, Control Tower's administration role
  ([C-ROLES](https://docs.aws.amazon.com/controltower/latest/userguide/roles-how.html)).

**Handoff templates are in scope.** The committed handoff artifacts
(`collectors/boto3_collector/handoff/`) are the natural home for the member role, and they are
commercial-only today: `arn:aws:` literals in the CloudFormation parameter pattern and managed-policy
ARN (`cross-account-role.yaml:51,103`), the Terraform policy ARN (`cross-account-role.tf:72`) and the
collector principal policy (`collector-principal-policy.json:9`). Making them partition-neutral
(`${AWS::Partition}`, `data.aws_partition`) is part of this requirement's delivery, so the member
role deploys in `aws-us-gov` on first use (`req-aws-core-secret-member-fanout-5`). The member-role
variant of each template attaches only `member-read-policy.json`, with no `ManagedPolicyArns` entry
and no `aws_iam_role_policy_attachment` to an AWS-managed policy (`-17`).

**The caller side of `AssumeRole`.** The member role's trust policy admits the collector, but the
collector's own principal also needs an IAM allow to call `sts:AssumeRole`. Today
`collector-principal-policy.json` grants it for one `<PARTNER_ACCOUNT_ID>` role with an `arn:aws:`
literal. For fan-out, that file grants `sts:AssumeRole` on
`arn:${Partition}:iam::*:role/<member_role_name>`. The partition comes from the deploying
partition, and the role name from the same parameter the member-role template takes. The grant
carries an `aws:ResourceOrgID` condition equal to the organization's id, so it can reach only
roles in this organization's accounts. Whether STS evaluates `aws:ResourceOrgID` for
`AssumeRole` is inferred from IAM's global-condition-key documentation and is to be confirmed
before build. If it is not, the fallback is `aws:ResourceAccount` limited to the member ids
the organization listed, regenerated when membership changes. No `*` role name and no
`arn:aws:` literal appears (`-19`).

**Per-account results.** Every account the organization listed gets exactly one `ACCOUNT_RESULT`
run-log entry: account id, outcome (`collected` / `partial` / `skipped`), reason, regions read,
node and edge counts, and its batch id (`null` when no batch was submitted). The run summary counts each outcome. A member's failure
(denied `AssumeRole`, account mismatch, rejected batch) is that account's outcome and does not abort
the run. It still marks the run's top-level result degraded (`-14`).
The base account's own credential, partition or identity failure still aborts the run
(`req-aws-collector-runtime-3`).

**The base batch is rejected.** The base batch carries the organization tree and every account's
org-sourced envelope, and it is submitted first. If it is rejected, nothing this run observed has
landed, and member batches would land account resources with no membership or tree under them.
So the run stops there:

- No member role is assumed and no member batch is submitted.
- Every listed account, the base account included, gets an `ACCOUNT_RESULT` with outcome
  `skipped`, reason `base_batch_rejected`, and `batch_id` the rejected base batch for the base
  account and `null` for the others.
- **The run records no completeness statement.** It neither records surfaces nor declares that it
  read none. This was checked against core: candidate derivation compares a run's in-scope
  surfaces with the previous successful run's (`tap_grid/candidates.py`, `_scope_of` counts only
  `scope_authorized: true`). Any statement that omitted the members, or marked them not
  authorized, would therefore read as a narrowed scope, and would nominate every member's
  previously observed resources as `scope_withdrawn`. With no statement, `tap_cares/tasks.py`
  `_record_candidates` derives nothing.
- The run ends **failed**, not degraded, as a base-credential failure does (`-4`). A failed job is
  never the "previous successful run" (`tap_cares/tasks.py` `_previous_run`), so the next run
  compares its scope against the last run that did land, and no withdrawal is lost or invented.
  The results, `ACCOUNT_RESULT` entries included, are still persisted on the failure path (`-21`).

**One batch per account.** Each account's nodes and edges are their own GRIFT batch, submitted with
`submit_grift(..., on_rejection="return")`. tap_cares offers that mode for exactly this case
("multi-batch collectors wanting partial-success", `tap_cares/collectors/base.py:306-308`). One
rejected batch, for example a member that hits unified-systems-com/aws-core-tap#14's tombstone conflict, then
loses only that account's data.

**Which batch owns what.** The organization tree is read with the base credential, so it is the
base account's observation and belongs to the base account's batch. That batch carries the
organization, its OUs, policies, statements, tag-policy rules, delegations, memberships, and one
`aws_account` envelope per listed account with the org-sourced fields. It is submitted first. Each
collected member's batch then carries everything read through that member's session, and also
that account's merged `aws_account` envelope: the same org-sourced values from this run's tree, plus
the account-sourced fields (`-8`). Because the member's write is the union, it replaces the
base batch's write of that node without blanking anything. So:

- **Member collected:** the account node ends the run with both sources' fields.
  `ACCOUNT_RESULT.batch_id` is the member's batch.
- **Member skipped before collection** (not `ACTIVE`, excluded, `AssumeRole` denied, identity
  mismatch): no member batch exists. The base batch's tree envelope is the only write, and its
  `ACCOUNT_RESULT.batch_id` is `null`.
- **Member batch rejected:** the base batch's tree envelope has already landed, and the member's
  batch, merged envelope included, writes nothing. `ACCOUNT_RESULT.batch_id` is the rejected batch.
- In the last two cases, the tree envelope resets the account-sourced fields. That is `-16`'s
  named dependency on unified-systems-com/tap#886.
- **Base batch rejected:** nothing landed, and the run stops before any member (*The base batch is
  rejected*, below; `-21`).

"One batch per account" therefore means one batch per account's credential session. The base
account's batch also holds the organization tree, because that is what the base credential read.

**The account node, merged and not clobbered.** The same `aws_account` node is described by two
readers: the organization tree (name, Organizations tags, `ParentId`; email and state today, which
move to the membership;
`organizations.py:607-659`) and the member's own collection (the STS/alias singleton,
`customfns.py:321-363`, and the account-level settings that `spec-aws-core-landing-zone.md`
adds). GRIFT upsert replaces the node and resets every optional field the envelope omits
(`organizations.py:390-397`), so whichever envelope lands second blanks the other's fields.
Within one run the collector already prefers the org-tree node for its own account
(`collector.py:635-653`), but it drops the singleton's fields instead of merging them, and only for
the base account. Fan-out makes every member hit this path:

- **In a run:** one envelope per account id, with fields merged by source. Org-sourced fields come
  from the tree; account-sourced fields come from the member collection. Neither replaces the other.
- **Which source owns which field.** Two fields have two writers today. `name`: the singleton writes
  the IAM account alias, or `AWS Account <id>` (`aws_resource_manifest.json:33`,
  `customfns.py:357-363`), and the tree writes Organizations `Account.Name`
  (`organizations.py:623`). `configuration`: both persist it, and both put a top-level `Arn` in it,
  which is the caller's ARN from STS in one and the account's ARN from `ListAccounts` in the other.
  So:
  - `name` is the account's Organizations name. When the run read the organization tree, the tree
    owns `name` and the singleton never writes it.
  - The alias is its own fact, `AwsAccount.account_alias`, written only by the member collection:
    the alias string, `""` when `ListAccountAliases` answered with none, `null` when the call was
    denied or failed (the grid's null-is-unobserved convention). It never feeds `name` in a run
    that read the tree.
  - The singleton's caller identity moves under `configuration.caller_identity` (`Arn`, `UserId`),
    so the account's `Arn` from the tree is not overwritten by the caller's.
  - Org-sourced: `name`, `tags` (the Organizations lane), `configuration.Arn` and
    `configuration.ParentId`, `partition`. The account's lifecycle facts from `ListAccounts`
    (`State`, `Status`, `JoinedMethod`, `JoinedTimestamp`, `Email`) belong to the membership
    (`req-aws-core-organization-membership-7`). No account envelope carries them, in
    `configuration` or in a typed field, so a member-scoped write has nothing of theirs to blank.
    Account-sourced: `account_alias`, `configuration.caller_identity`, and the account settings
    `spec-aws-core-landing-zone.md` adds (the four S3 account public-access-block flags).
- **A member that was not collected keeps its account-sourced fields.** A member can be skipped,
  denied at `AssumeRole`, fail assert-on-land, or have its batch rejected (`-4`). The tree still
  writes that account's envelope, and today's replace resets every optional field the envelope
  omits (`tap_grid/services/_impl.py` `_apply_replace`). So the tree envelope alone erases the last
  observed alias, caller identity and public-access-block flags. The requirement is that those
  fields keep their last observed values, and it depends on the same core work as the tag
  false-empty write: a GRIFT write that marks a field not observed instead of resetting it (core's
  replacement-semantics work, unified-systems-com/tap#886, on its default path). aws_core takes no
  collector workaround for it: it does not withhold the account node, and it does not read stored
  grid values back into the envelope. Fan-out writes do not ship before that core work does
  (*Sequencing*, under Status Details), so no release has an interim period in which the reset
  happens (`-16`).
- **Across runs:** a run that did not read the organization does not fan out, and so writes no
  member's node. The remaining cross-run case is a separately configured member-scoped
  installation, which today writes the singleton with `tags: {}`, blank email and status, and a `name`
  from its alias or id. `req-aws-core-organization-membership` (step 8) closes the email and status
  half: it moves those organization-sourced facts onto the membership node (ruling 2026-10-01). The
  alias half is closed by `account_alias` above: the alias is never stored as the Organizations
  name by a run that read the tree. Two halves stay open. Organizations account tags stay in
  `aws_account.tags` (ruling 2026-10-01), so a member-scoped run that cannot read them still writes
  `{}` over them; that is the false-empty write named under `req-aws-collector-tags`. And `name` is
  required on every write (`CREATE_REQUIRED`, `minLength: 1`; `models/aws_account.py:81,101`), so a
  member-scoped run still writes its alias-or-id fallback over the Organizations name. Both depend
  on core's GRIFT replacement semantics (unified-systems-com/tap#886), not on this requirement.

**Falsifier reach.** A falsifier judging a candidate in account X resolves X's credentials through
the same base-then-member-role path, assert-on-land included. A candidate whose account the member
role cannot reach is `UNDETERMINED(scope_unknown)`, as today.

**Bounds.** Members are collected one at a time in v0. A declared `max_member_accounts` cap
**refuses** the fan-out (`FANOUT_CAP_EXCEEDED`, base account still collected) rather than collecting
a silent prefix of the organization. Every `AssumeRole` and every member call lands in the run's call
ledger tagged with its account id (`req-aws-collector-audit-ledger`).

**What fan-out does not do.** It does not read Control Tower's or Gruntwork's account lists, model
account vending, or assume roles across partitions. A GovCloud management credential reaches
GovCloud members only, and the paired commercial accounts are a separate organization
(`req-aws-core-partition-pairing`). It arms no reconcile.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-fanout-1 | Organization Listing Drives Fan-Out | Proposed | The member set is this run's organization-wide `ListAccounts`, `ACTIVE` members only, minus the base account and the secret's exclude list, restricted to the secret's `accounts_allowed` when set (`req-aws-collector-selection-7`). It is never read from grid state, and fan-out does not run unless that listing read to its end and the base account is the organization's `MasterAccountId`. | |
| req-aws-collector-fanout-2 | Partition-Aware Role ARN | Proposed | The member role ARN is `arn:<run partition>:iam::<member>:role/<member_role_name>`, with the partition from the run's resolved partition; no literal `arn:aws:` appears in the fan-out path. | A GovCloud test captures `arn:aws-us-gov:iam::…` on the wire, as `test_govcloud.py:351-399` does for the single role. |
| req-aws-collector-fanout-3 | Assert-On-Land Per Member | Proposed | After `AssumeRole`, the member session's `GetCallerIdentity` account equals the member id, or the member is skipped as `MEMBER_ACCOUNT_MISMATCH` and nothing from it is written. | Reuses `account_mismatch_error`. |
| req-aws-collector-fanout-4 | Member Failure Is Local | Proposed | A denied or failed `AssumeRole`, a member identity mismatch, or a member's rejected batch is recorded as that account's outcome and the run continues. A base-credential, partition or base-identity failure, or a rejected base batch (`-21`), still aborts. | |
| req-aws-collector-fanout-5 | Per-Account Results | Proposed | Every listed account has exactly one `ACCOUNT_RESULT` entry (id, outcome ∈ `collected\|partial\|skipped`, reason, regions, counts, batch id), and the summary counts each outcome. The batch id is `null` for an account skipped before any batch was submitted, and the rejected batch's id for an account whose batch was rejected. | The per-account run results the epic asks for. |
| req-aws-collector-fanout-6 | One Batch Per Account | Proposed | Each account's observations are one GRIFT batch submitted with `on_rejection="return"`; a rejected member batch fails only that account, and a rejected base batch stops the run (`-21`). The organization tree, including one org-sourced `aws_account` envelope per listed account, is the base account's observation and is in the base batch, which is submitted first; a collected member's batch re-carries its account's merged envelope. | Supersedes `req-aws-collector-grift-batch-1` for fan-out runs. |
| req-aws-collector-fanout-7 | Surfaces Per Account | Proposed | Completeness surfaces are recorded per account against that account's own batch. A listed member that was not collected records, for each containment edge type declared on its `aws_account` node (observed this run through the base batch's tree envelope), a surface with `scope_authorized: false` and the reason, never omitting one; it records no surface for parents below the account, which this run did not observe. With no submitted batch those surfaces carry `applied_batches: []`; with a rejected batch they cite it, so core derives `applied: false` either way. | Consistent with `req-aws-core-contained-type-triple` (no surface for an unobserved parent). Core counts only `scope_authorized: true` surfaces as in scope (`tap_grid/candidates.py` `_scope_of`), so recording a not-authorized surface and omitting one read the same to withdrawal: core still derives `scope_withdrawn` candidates for the member's previous surfaces, and the falsifier is the backstop (`-9`). The not-authorized surfaces carry the reason on the record. Nothing is armed (unified-systems-com/aws-core-tap#14). |
| req-aws-collector-fanout-8 | Account Node Merged In A Run | Proposed | For every account both the organization tree and a member collection describe in one run, the member's batch carries one envelope whose fields are the union by source (the org-sourced values from this run's tree plus the account-sourced ones); neither reader's fields are dropped or blanked, and the base batch's earlier tree envelope is superseded by it. | Generalizes `collector.py:635-653`, which keeps the tree node and drops the singleton's fields. |
| req-aws-collector-fanout-9 | Falsifier Reach Per Account | Proposed | A falsifier resolves the candidate's account credentials through the base-then-member-role path, with assert-on-land; an unreachable account is `UNDETERMINED(scope_unknown)`. | Today every falsifier resolves the one secret (`falsifiers.py:449-485`). |
| req-aws-collector-fanout-10 | Bounded, Never A Silent Prefix | Proposed | Members are collected serially; a selected member count above `max_member_accounts` refuses the fan-out with `FANOUT_CAP_EXCEEDED` and still collects the base account. | |
| req-aws-collector-fanout-11 | Ledgered Per Account | Proposed | Every `AssumeRole` and every member-session call is in the run's call ledger tagged with the member account id. | `req-aws-core-secret-aws-assumed-role-6`. |
| req-aws-collector-fanout-12 | Dedicated Read-Only Member Role | Proposed | The member role is a dedicated role trusting only the collector's management-account principal with a required External ID, whose only permissions are the repo-owned read-only policy of `-17`; a test fails on a collector call in a member that the policy does not grant. `OrganizationAccountAccessRole` and `AWSControlTowerExecution` are never assumed by default. | Ruling 2026-10-01 (dedicated read-only role). How read-only is enforced is refined by `-17`: no AWS-managed policy. |
| req-aws-collector-fanout-13 | Partition-Neutral Handoff Templates | Proposed | Every committed handoff artifact builds its ARNs from the deploying partition: no `arn:aws:` literal in a template value, parameter pattern or policy ARN decides the partition, and the README shows a GovCloud example beside each commercial one. | In scope for this step by the 2026-10-01 ruling; overlaps unified-systems-com/aws-core-tap#51, which named the same templates. |
| req-aws-collector-fanout-14 | A Degraded Run Is Never Plain Success | Proposed | When the organization listing did not read to its end, the base account is not the organization's management account, or any listed member's outcome is not `collected`, the run's top-level result is marked degraded and carries the per-outcome counts. It is never reported as a plain success, so automation cannot read base-account-only collection as full coverage. | Uses core's job status for a partial run if one exists; otherwise a top-level `degraded` flag in `CollectionJob.results`. Member failure stays local to the run (`-4`); this makes it visible at the top. |
| req-aws-collector-fanout-15 | Account Name Has One Owner | Proposed | In a run that read the organization tree, `AwsAccount.name` is Organizations `Account.Name` and nothing else writes it; the IAM alias is `AwsAccount.account_alias` (`""` = observed none, `null` = not read); the singleton's caller identity is `configuration.caller_identity`, never a top-level `Arn`. A test merges a tree envelope and a singleton for one account and asserts each field's source. | Closes the alias-for-name collision in fan-out runs. The member-scoped cross-run overwrite of `name` depends on unified-systems-com/tap#886. |
| req-aws-collector-fanout-16 | Member-Sourced Fields Survive A Member Failure | Proposed | When a listed member is not collected (skipped, `AssumeRole` denied, identity mismatch, batch rejected), the organization tree's envelope for that account leaves its account-sourced fields (`account_alias`, `configuration.caller_identity`, the S3 account public-access-block flags) at their last observed values, through a GRIFT write that marks them not observed. Fan-out writes do not ship before that write exists (*Sequencing*). | Depends on core's replacement-semantics work, unified-systems-com/tap#886, as the tag false-empty write does; no collector workaround (no withheld node, no read-back of stored values). |
| req-aws-collector-fanout-17 | Repo-Owned Member Policy | Proposed | The member role's permissions are exactly `collectors/boto3_collector/handoff/member-read-policy.json`, generated from the manifest's operations, every custom reader's declared call list and every falsifier's declared `account`-context probe calls (`-22`) through a declared API-to-IAM action map, and drawn only from the committed, reviewed allowlist `member-read-actions.json` (each entry one action with a one-line `why`). Generation fails when a declared call maps to an action not on the allowlist. Every member-role handoff variant attaches only that policy and no AWS-managed policy. Tests fail when a collector call made in a member is not granted by the policy, when generation succeeds for a call whose action is not allowlisted, when the committed policy differs from a fresh generation, and when a member-role template attaches any other policy. The verb-prefix check (`Describe`, `List`, `Get`, `BatchGet`, `Search`) runs over the allowlist as a sanity check, not as the gate. | AWS-managed policies such as `SecurityAudit` change without review in this repo, which would widen every member role. A prefix rule alone admits content reads such as `codecommit:GetFile`, `ecr:GetDownloadUrlForLayer` and `ssm:GetDocument`. |
| req-aws-collector-fanout-18 | Data-Plane Reads Denied | Proposed | A second, independent test over the allowlist itself: no entry of `member-read-actions.json` is on a committed denylist of actions that read customer data or secret material (at least `secretsmanager:GetSecretValue`, `ssm:GetParameter`, `ssm:GetParameters`, `ssm:GetParametersByPath` and `ssm:GetParameterHistory` outright (each returns parameter values, and `WithDecryption` is a request parameter, not an IAM action, so it cannot be denied separately; parameter metadata comes from `ssm:DescribeParameters`), `ssm:GetDocument`, `kms:Decrypt`, `s3:GetObject*`, `dynamodb:GetItem`/`Query`/`Scan`/`BatchGetItem`, `logs:GetLogEvents`/`FilterLogEvents`, `lambda:GetFunction` outright (its response carries a code-download URL whatever the request; function metadata comes from `lambda:ListFunctions`), `codecommit:GetFile`/`GetBlob`, `ecr:GetDownloadUrlForLayer`/`BatchGetImage`). A test fails when a denylisted action is added to the allowlist. | Belt and braces over `-17`'s allowlist gate: the allowlist is reviewed, and the denylist catches a review that let a content read through. Collection is metadata-only (`req-aws-collector-scope`). Every entry is a whole IAM action or action pattern; none is qualified by a request parameter, which IAM cannot match. |
| req-aws-collector-fanout-19 | Caller-Side AssumeRole Grant | Proposed | `collector-principal-policy.json` grants the base principal `sts:AssumeRole` on `arn:${Partition}:iam::*:role/<member_role_name>` only, with an `aws:ResourceOrgID` condition equal to the organization's id (fallback, if STS does not evaluate that key for `AssumeRole`: `aws:ResourceAccount` limited to the listed member ids). Tests fail on an `arn:aws:` literal, a wildcard role name, or a grant with neither condition. | Without a caller-side allow, every member `AssumeRole` is denied whatever the member trust says. `aws:ResourceOrgID` support for `sts:AssumeRole` is inferred and confirmed before build. |
| req-aws-collector-fanout-20 | Member Policy From Member-Reachable Calls Only | Proposed | Every call declaration (manifest and custom readers) carries `context: base` or `context: account`; `member-read-policy.json` is generated only from `account`-context calls. A test fails when an action of a `base`-only call (at least `organizations:*`, `controltower:*`, `sso:*`/`sso-admin` actions, `identitystore:*`) appears in the member policy, and when a call declaration has no context. | Least privilege: the Organizations, Control Tower and Identity Center readers run only with the base credential. |
| req-aws-collector-fanout-21 | Base Batch Rejection Stops The Run | Proposed | When the base batch is rejected, no member role is assumed and no member batch is submitted; every listed account's `ACCOUNT_RESULT` is `skipped` with reason `base_batch_rejected`; the run records no completeness statement (no surface and no `declare_no_surfaces`); and the job ends failed. A test rejects the base batch in the fake importer and asserts all four, and that candidate derivation records nothing for the run. | Checked against core: any statement omitting the members would read as a narrowed scope and derive `scope_withdrawn` for their resources (`tap_grid/candidates.py` `_scope_of`); a failed job is never the previous run compared against (`tap_cares/tasks.py` `_previous_run`). |
| req-aws-collector-fanout-22 | Falsifier Probes In The Member Policy | Proposed | Every falsifier registered in `[falsifiers]` declares each AWS call its probe makes, with `context: base` or `context: account`; the member policy's source set is manifest operations, custom-reader calls and `account`-context probe calls, all through `-17`'s allowlist. A test fails when an `account`-context probe call is not granted by `member-read-policy.json`, and when a registered falsifier declares no probe calls. | `-9` runs probes through the member role; `GetResolverRuleAssociation` is a probe-only call. |

#### Future

- Concurrency across members, with Organizations and STS quotas named.
- A delegated-administrator base credential instead of the management account.
- The cross-run singleton clobber for member-scoped installations: its email and status half is
  closed by `req-aws-core-organization-membership`; its tags and `name` halves, and `-16`'s
  preservation of a failed member's fields, wait on core's replacement semantics
  (unified-systems-com/tap#886).

### Every Paginated Call Read To Its End
----
RID: `req-aws-collector-pagination`

Status: `Proposed`

One rule for every call the landing-zone epic names: listings, hydrate sub-calls, tag lanes and
falsifier probes alike. A call that botocore can paginate is read to its last page. One page is
never treated as the whole answer.

#### Implementation

- **Which calls.** A call is paginated when the pinned botocore's `paginators-1.json` for its
  service lists the operation (`client.can_paginate(op)` is true). The hydrate seam makes one
  direct call today (`hydrate.py:91`), so this rule changes it for paginated operations.
- **When a read is finished.** A read ends by its paginator's own stop condition: no output token,
  and, where the paginator declares a `more_results` flag, that flag false on the last page. Two
  calls declare one: `ec2:SearchTransitGatewayRoutes` (`AdditionalRoutesAvailable`) and the IAM
  `List*Tags` / `ListAccountAliases` calls (`IsTruncated`). A page whose flag says more while it
  carries no token is a truncated answer: the result is unknown (incomplete surface, `null` field,
  `UNDETERMINED` probe), never complete. For `SearchTransitGatewayRoutes` the pinned model has
  both: input `NextToken` and `MaxResults` (default 1000), and output `NextToken` and
  `AdditionalRoutesAvailable`, and its paginator joins them (read: botocore 1.43.103). The call is
  made with the maximum page size. If a table is truncated anyway, the surface stays incomplete.
  Narrowing the search by filter (per attachment or per CIDR) to get under the cap is allowed only
  as a set of filtered searches whose union is controlled (`req-aws-core-contained-type-triple-5`).
- **A later page fails.** If any page after the first fails, the result is unknown, never the pages
  read so far:
  - a typed field written from the call is `null`, with the hydrate slot's `error` status;
  - a completeness surface backed by the call is `enumeration_complete: false` with the reason;
  - a falsifier probe answers `UNDETERMINED`.
- **The service tag lane** (`req-aws-collector-tags-15`) is this rule applied to tags.
- **Calls this applies to** (read: botocore 1.43.103 `paginators-1.json` for every call the epic's
  specs name; result key in parentheses):

| Service | Paginated calls |
| --- | --- |
| `ec2` | `DescribeFlowLogs`, `DescribeInternetGateways`, `DescribeNatGateways`, `DescribeNetworkAcls`, `DescribeNetworkInterfaces`, `DescribeRouteTables`, `DescribeSecurityGroupRules`, `DescribeTransitGatewayAttachments`, `DescribeTransitGatewayRouteTables`, `DescribeTransitGateways`, `DescribeVpcEndpoints`, `DescribeVpcPeeringConnections`, `GetTransitGatewayRouteTablePropagations`, `SearchTransitGatewayRoutes` (stop condition also requires `AdditionalRoutesAvailable` false) |
| `organizations` | `ListAccounts`, `ListAccountsForParent`, `ListAWSServiceAccessForOrganization`, `ListDelegatedAdministrators`, `ListDelegatedServicesForAccount`, `ListOrganizationalUnitsForParent`, `ListPolicies`, `ListRoots`, `ListTagsForResource`, `ListTargetsForPolicy`; `ListCreateAccountStatus` (Future, pairing) |
| `sso-admin` | `ListAccountAssignments`, `ListInstances`, `ListManagedPoliciesInPermissionSet` (`AttachedManagedPolicies`), `ListPermissionSets`, `ListPermissionSetsProvisionedToAccount`, `ListTagsForResource` |
| `identitystore` | `ListGroups` |
| `controltower` | `ListEnabledBaselines`, `ListEnabledControls`, `ListLandingZones` |
| `config` | `DescribeConfigurationAggregators`, `ListConfigurationRecorders`, `ListTagsForResource` |
| `guardduty` | `ListDetectors` |
| `securityhub` | `GetEnabledStandards` (`StandardsSubscriptions`) |
| `accessanalyzer` | `ListAnalyzers` |
| `route53resolver` | `ListResolverEndpointIpAddresses`, `ListResolverEndpoints`, `ListResolverRuleAssociations`, `ListResolverRules`, `ListTagsForResource` |
| `iam` | `ListAccountAliases`, `ListOpenIDConnectProviderTags`, `ListRoleTags` |

Not paginated in the same data, so one call is the whole answer: `ec2:DescribeAddresses`,
`DescribeRegions`, `GetEbsEncryptionByDefault`, `GetEbsDefaultKmsKeyId`;
`config:DescribeConfigurationRecorders`, `DescribeConfigurationRecorderStatus`,
`DescribeDeliveryChannels`; `securityhub:DescribeHub`, `ListTagsForResource`;
`controltower:ListTagsForResource`; `s3control:GetPublicAccessBlock`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-pagination-1 | Read To Exhaustion | Proposed | Every declared call (manifest, custom reader, hydrate sub-call, tag lane, falsifier probe) whose operation the pinned botocore can paginate is read until no continuation token remains. | |
| req-aws-collector-pagination-2 | Later-Page Failure Is Unknown | Proposed | A failure on any page after the first leaves the field `null`, the surface incomplete, or the probe `UNDETERMINED`; the pages already read are never written as the answer. A test fails the second page of a paginated hydrate call, listing and probe, and asserts each outcome. | |
| req-aws-collector-pagination-3 | Walked Against botocore | Proposed | A test walks every declared call against the pinned botocore's `paginators-1.json` and fails when a paginated operation is read through a single-call path, or when a declared call's operation does not exist in the service model. | Keeps the table above from going stale. |

### Model Dependencies
----
RID: `req-aws-collector-model-deps`

Status: `Proposed`

The collector can only populate models that exist. Three of Sam's eight resource
types are not yet modeled in `aws_core`.

#### Implementation

Already modeled (usable now): S3 bucket, ACM certificate, Route 53 hosted zone,
Lambda function, IAM role.

Must be added via the `add-model` skill before their manifest entries can
collect, governed by `spec-aws-core-v0` (`req-aws-core-models`):

- CloudFront distribution
- CloudWatch log group
- EventBridge rule

Edge types required by the Sam worked example must already be declared by
`aws_core` (`req-aws-core-edges`); any not present are added through that spec's
edge process, not invented here.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-model-deps-1 | Missing Models Identified | Proposed | CloudFront, CloudWatch log group, and EventBridge rule are named as prerequisites. | |
| req-aws-collector-model-deps-2 | Added Via Skill | Proposed | The three models are added via `add-model` under `spec-aws-core-v0`, not ad hoc. | |
| req-aws-collector-model-deps-3 | Edge Types Pre-Declared | Proposed | Worked-example edges use `aws_core`-declared edge types; new types go through the edge process. | |

### Sam Worked Example
----
RID: `req-aws-collector-sam-example`

Status: `Proposed`

A concrete v0 manifest and edge set for the reproduced samaydlette.com stack, so
the demo target is explicit rather than implied.

#### Implementation

> **v0 planning snapshot.** This section captured the original eight-entry
> demo target. The live manifest (`aws_resource_manifest.json`) has since
> grown past it — `aws_account`, DynamoDB table, IAM OIDC provider entries
> and their edges were added during build — and the manifest is the
> authoritative inventory. The collection classes and demo edges below are
> kept current for the entries they name.

Original demo resource entries (eight): S3 bucket, CloudFront distribution,
ACM certificate, Route 53 hosted zone, Lambda function, IAM role, CloudWatch
log group, EventBridge rule.

Collection class per entry:

- single-call `aws_op`: Lambda, IAM role, CloudWatch log group
- `custom_fn`: S3 (minimal hydrate fan-out), Route 53 (zones + record-set
  cross-join for the alias edge), CloudFront (distribution list + per-origin
  `GetOriginAccessControl` fan-out), EventBridge rule (`ListRules` +
  per-rule `ListTargetsByRule` fan-out for the target edge), ACM (summary
  list sufficient for the demo)

The demo-legible edges, all declarable (no policy resolver needed — none of
Sam's edges require policy-document parsing):

- CloudFront → S3 (origin domain → bucket; derived-key transform on the origin
  domain)
- CloudFront → ACM (viewer certificate ARN)
- Route 53 → CloudFront (alias target → distribution by domain; the matcher the
  prior art does not ship — TAP-authored)
- Lambda → IAM role (`Role` ARN)
- EventBridge rule → IAM role (`RoleArn`)
- EventBridge rule → Lambda (`INVOKES_LAMBDA`; target ARNs from `ListTargetsByRule`,
  filtered to Lambda targets) — the daily schedule tick that drives the
  compliance Lambda
- Lambda → CloudWatch log group (logging configuration / convention)

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-sam-example-1 | Eight Entries Named | Proposed | The manifest's v0 entries are exactly Sam's eight resource types. | |
| req-aws-collector-sam-example-2 | Collection Class Stated | Proposed | Each entry's source class (single-call vs custom_fn+hydrate) is explicit. | From the probe. |
| req-aws-collector-sam-example-3 | Demo Edges Declarable | Proposed | The six demo edges are expressible as declarative rules; no policy resolver is required for the demo. | |

### Build-Collector Skill Direction
----
RID: `req-aws-collector-build-skill`

Status: `Proposed`

The manifest-driven design is the foundation of a future build-collector skill.
This requirement records what the skill should be so the design stays aligned
with it (it is not built in v0).

#### Implementation

The skill should:

- generate manifest entries (entity_type, service, source, items_path,
  natural_key, field map, edge rules) by introspecting the botocore service
  model — the ~80% declarative majority
- compose, not generate, the fixed seam library — the [fan-out hydrate
  template](#fan-out-hydrate-seam) and the deferred policy-document resolver —
  for the bounded residue
- gate which guards apply on a **trust-tier axis**: a trusted own-account boto3
  source omits the KSI-style paranoid input layer; an untrusted source (a future
  external/customer feed) would re-enable it. Trust tier is an explicit skill
  input, not an implicit default
- stay a **config generator**, never a code generator, even at depth

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-build-skill-1 | Manifest Generator | Proposed | The skill generates manifest entries from botocore introspection. | |
| req-aws-collector-build-skill-2 | Seam Library Composed | Proposed | The skill composes the fixed seam library; it does not generate per-resource fetch/edge code. | |
| req-aws-collector-build-skill-3 | Trust-Tier Axis | Proposed | Which safety guards apply is an explicit trust-tier input. | |

#### Future

The skill graduates from Proposed once the v0 collector is proven against the
Sam target and the manifest format has stabilized through real use.

### Shape-Drift Detection
----
RID: `req-aws-collector-drift`

Status: `Proposed`

AWS API shape changes are detected deterministically by diffing the pinned
botocore service models, folded into the existing catalog-refresh skill rather
than as new infrastructure.

#### Implementation

- `botocore` is pinned in the lockfile; its bundled, versioned `service-2.json`
  models are the canonical machine-readable AWS API surface (offline, no
  external tracker).
- On a botocore bump, the relevant operation output shapes for manifested
  services are diffed; added/removed/changed members are surfaced as proposed
  manifest/field updates.
- This extends `spec-aws-core-catalog`'s refresh skill (already "detects changes
  and proposes additions") to cover collector manifest drift; it is not a
  separate pipeline.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-drift-1 | botocore Pinned | Proposed | botocore is version-pinned; its service models are the drift baseline. | |
| req-aws-collector-drift-2 | Model Diff | Proposed | Botocore bumps trigger an output-shape diff for manifested services. | |
| req-aws-collector-drift-3 | Folded Into Catalog Skill | Proposed | Drift detection extends the existing catalog-refresh skill, not new infra. | |

### v0 Non-Goals
----
RID: `req-aws-collector-nongoals`

Status: `Proposed`

Explicitly deferred. Each is a bounded future seam, not an abandoned idea — named
so later readers do not mistake the omission for an oversight (`feedback:
future-seam discipline`).

#### Implementation

Deferred from v0:

- **Grid-state reconciliation — deletion / reaping / staleness sweep.**
  RID: `req-aws-collector-reconcile` (Backlog). No tombstones, no implied
  absence in v0. The named future seam: implied-absence is *the same
  primitive* as the edge resolver's grid-as-backstop
  (`req-aws-collector-edge-resolver-4`) — read the authoritative current grid
  shape through a service-layer read, diff this run's batch against the slice
  of the grid the run claims authority over, tombstone the difference. One
  capability serves both (resolve references; reap absences). The strategic
  bet (Cartography contrast): Cartography and peers carry per-node-type
  `lastupdated` timestamps + bespoke per-relationship cleanup jobs — fiddly,
  scattered, and the classic mass-false-delete footgun. TAP's uniform
  Entity/Edge spine + dimensions + per-run GRIFT batch provenance make a
  *single generic* reconcile (scope authority by source/dimensions, tombstone
  grid-minus-batch) plausibly far less code and more systematic — that is the
  reason to keep this seam, designed in-spec first when the signal arrives.
  Hard constraints, non-negotiable: it must route through GRIFT + the service
  layer (never a collector side channel); it must honor
  `req-aws-collector-regions-4` (an ambiguous/skipped read must never cause a
  false delete — the transient-vs-skippable hazard); and a **partial or
  failed run must never trigger a sweep** (authority is only as wide as what
  the run actually, completely covered — the single sharpest Cartography
  footgun). Demand-signal-gated; not built.

  **Update (tap-plugin-aws-core#42):** the demand signal arrived from core's newer, separately
  designed reconcile primitive — `tap_grid.falsifiers` / `tap_grid.candidates` (probe the
  source per candidate, never a batch-vs-grid diff) — which `tap-plugin-github-core` adopted
  first (github-core#151). This plugin's `spec-aws-core-v0.md`
  (`req-aws-core-reconcile-falsifiers`) now builds the JUDGING half of that newer mechanism
  (the `[falsifiers]` manifest table, a base `_AwsFalsifier`, `SubnetFalsifier`) — a different,
  now-superseding design from the "diff this run's batch against the grid" sketch above. What
  remains Backlog, unchanged by that work: this collector still produces no per-surface
  completeness statement, so `tap_grid.candidates.derive_candidates` has nothing to derive a
  subnet (or any other) candidate from yet. The two pieces are independent: the falsifier layer
  can be built and tested (and is) before the collector emits a single completeness surface.

  **Update (tap-plugin-aws-core#43):** the collector now DOES emit per-surface completeness
  statements, for five of its manifest entries — `spec-aws-core-v0.md`'s
  `req-aws-core-reconcile-containment`: `aws_core__aws_iam_role`, `aws_core__aws_iam_user`,
  `aws_core__aws_iam_policy`, `aws_core__aws_iam_oidc_provider`, `aws_core__aws_s3_bucket`, the
  five types an AWS account owns exclusively. `tap_grid.candidates.derive_candidates` can now
  actually derive a candidate for those five falsifiers to judge on a live run. The other ~47
  `BELONGS_TO_ACCOUNT`-sourced entries are regional, RAM-shareable, or both, and remain exactly
  as Backlog as before — this is a slice of `req-aws-collector-reconcile`, not its close-out. v0 is one account. The secrets model already frames
  multi-account as "more secret files"; orchestration across accounts is later.

  **Proposed (landing-zone epic):** multi-account is no longer deferred. `req-aws-collector-fanout`
  specifies orchestration across an organization's member accounts from one management-account
  credential. "More secret files" never worked as written: the secret ref is one module constant
  (`collectors/boto3_collector/credentials.py:64`), so a second account meant rewriting the one file
  between runs.
- **Uniform-enumeration APIs** (Resource Groups Tagging API, Cloud Control API,
  AWS Config). Evaluated and rejected for v0: Tagging API returns spine only,
  Cloud Control is CFN-shaped with uneven coverage and strips edge-bearing
  fields, Config requires an in-account recorder. Per-service declared ops are
  the v0 basis.
- **Policy-document edge resolver** — the second named seam. The ~20%
  non-declarable edges concentrate almost entirely into IAM/resource policy
  document parsing. None of Sam's demo edges need it, so it is specified as a
  seam (one write-once resolver, built — when built — as a post-ingestion pass
  over the already-collected graph, the shape every mature prior-art project
  converged on independently: Cartography analysis jobs, Fix `connect_in_graph`;
  not an ever-richer inline manifest DSL) but not built in v0. Its existence is
  what proves the pattern extensible without per-service sprawl.
- **Deep IAM / Organizations / SCP permission graph.** The known weak spot
  (~60% declarable); the same weak spot prior-art tools have and solve with a
  dedicated pass. Deferred with the policy resolver.
- **General jsonpath edge-DSL** beyond the declared rule shape (scalar/list +
  small derived-key transform). Richer expression waits for a demand signal.
- **Per-object S3 introspection — its own targeted collector.** Listing a
  bucket's *contents* as individual `aws_s3_object` nodes (with a
  `STORES_OBJECT` edge from the bucket) is deferred to a dedicated
  collector — one pointed at a specific bucket deliberately, not part of the
  general manifest-driven account sweep. Object counts run to the millions
  (this account already has buckets at 1.7M and 2.1M objects); a blanket
  node-per-object pass over every bucket would explode the grid and the viz.
  The general sweep gets only the cheap CloudWatch *aggregate*
  (`req-aws-collector-s3-bucket-size` — `size_bytes` / `object_count`);
  deep per-object introspection is an opt-in "point it at one bucket and go
  to town" tool. The aggregate and the per-object collector compose — cheap
  universal stats now, targeted deep introspection when a specific bucket
  warrants it. Backlog.
- **China and isolated partitions.** Recognised (an ARN or region from one is classified, never mistaken for commercial) but refused at credential resolution: nothing here has run against them. GovCloud is in scope ([AWS Partitions](#aws-partitions)).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-nongoals-1 | Deferrals Named | Proposed | Each deferral is explicitly named as a bounded future seam. | |
| req-aws-collector-nongoals-2 | Reaping Constraint Recorded | Proposed | Future reaping must route through GRIFT and never false-delete on an ambiguous read. | |
| req-aws-collector-nongoals-3 | Uniform-Enum Rejection Justified | Proposed | The rejection of Tagging/Cloud Control/Config for v0 is recorded with rationale. | |
| req-aws-collector-nongoals-4 | Policy Resolver Is A Seam | Proposed | The policy-document resolver is specified as a write-once seam, deferred, not abandoned. | |

## Open Questions

- **Commercial partition list.** Nothing is listed for `aws`. A list for it is wanted (George, 2026-11-04) but not yet:
  the record shape in `-7` holds one, and it waits for a commercial run to show which entries need it.
- **Derived-key edge transforms.** The Route 53-alias → CloudFront-by-domain
  edge needs a small transform on `value_path` (domain normalization), not a raw
  jsonpath. v0 supports a minimal declared transform; how expressive that
  becomes before it turns into a DSL is a demand-driven decision, not settled
  here.
- **S3 hydrate op list for the KSI scoreboard.** The exact minimal set of
  `GetBucket*` operations v0 hydrates depends on which compliance signals the
  KSI scoreboard reads from Sam's catalog; pinned when that surface is built.
- **Edge-type assignment.** Which already-declared `aws_core` edge type each
  demo relationship uses (and whether CloudFront/CloudWatch/EventBridge model
  additions require any new edge types) is resolved in the `add-model` work
  under `spec-aws-core-v0`, not here.
- **Tag-derived dimensions** *(deferred, demand-driven)*. The collector
  already captures AWS resource tags into the per-model `tags` JSON column
  (via RGTA sweep + per-service side-quests). A natural extension is a
  configurable mapping from collected tags → entity `dimensions`
  (e.g. `tag.Project` → `dimension.tap.project`), stamped at collection
  time without a downstream hook. Held off in v0 because **dimensions are
  the security-boundary pillar** and arbitrary user-controlled tags must
  not silently become security boundaries. When the feature is built it
  needs: a per-collector or per-account allowlist of which tags may become
  dimensions; a denylist for reserved TAP dimension prefixes (`tap.*`,
  `aws.*`, etc.); collision/conflict handling when multiple sources map the
  same tag key; FLIP provenance recording which collector run wrote which
  dimension on which node; and an explicit policy for what happens when a
  previously-mapped tag value changes (re-stamp, history, or both). Demand
  signal that promotes this from Open to Proposed: >1 system collected
  into one account, or >1 customer collected at all. Until then samsite
  (the originating use case) uses tag-based ORM filters directly. Cross-ref:
  `plan/strat-sam-demo.md` "System-identification" decision (2026-05-20).
