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
| 3. | Connected     | Relationships are materialized as edges via declarative rules resolved by deterministic identity |
| 4. | Bounded       | The non-declarative residue is two write-once seams, not per-service code |
| 5. | Conventional  | The collector is an ordinary `CollectorBase` implementation; it invents no parallel runtime |
| 6. | Fenced        | v0 collects Sam's finite resource set, one account, no deletion semantics |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-aws-collector-scope | [Collector Scope](#collector-scope) | Approved for Development | One account, Sam's resource set, no deletes |
| req-aws-collector-manifest | [Resource Manifest](#resource-manifest) | Approved for Development | The JSON descriptor format — the architectural heart |
| req-aws-collector-source | [Source Primitive](#source-primitive) | Approved for Development | `source` ∈ {aws_op, custom_fn}, uniform "yields items" contract |
| req-aws-collector-field-projection | [Field Projection](#field-projection) | Approved for Development | jsonpath → typed fields + full payload → `configuration` |
| req-aws-collector-identity | [Deterministic Identity](#deterministic-identity) | Approved for Development | `uuid5(ns, "<type>:<natural_key>")`; re-runs upsert |
| req-aws-collector-edges | [Declarative Edge Rules](#declarative-edge-rules) | Approved for Development | Recompute-uuid5 edge resolution; v0 make-it-work = mutually-available natural keys |
| req-aws-collector-edge-resolver | [Edge Identifier Resolution (Future Seam)](#edge-identifier-resolution-future-seam) | Backlog | The durable fix: pre-batch resolution pass; `key_kind`-driven; misses become observable warnings |
| req-aws-collector-reconcile | [Grid-State Reconciliation (Future Seam)](#v0-non-goals) | Backlog | Implied-absence/tombstone via the same grid-read primitive as the resolver; one generic reconcile vs Cartography per-type cleanup |
| req-aws-collector-hydrate | [Fan-Out Hydrate Seam](#fan-out-hydrate-seam) | Approved for Development | First named seam; per-op error-swallow; S3-style many-call |
| req-aws-collector-s3-bucket-size | [S3 Bucket Size Metrics](#s3-bucket-size-metrics) | Approved for Development | Aggregate size/count from CloudWatch storage metrics; `size_observed_at` data-currency disclosure |
| req-aws-collector-credentials | [Credential Resolution](#credential-resolution) | Approved for Development | `tap_cares` secret, `aws_static_access_key`, single account |
| req-aws-collector-runtime | [Collector Runtime Integration](#collector-runtime-integration) | Approved for Development | `CollectorBase` pipeline; mirrors the KSI reference collector |
| req-aws-collector-regions | [Region Iteration And Resilience](#region-iteration-and-resilience) | Approved for Development | Classify-and-skip; bounded throttle backoff |
| req-aws-collector-partition | [AWS Partitions](#aws-partitions) | Implemented | Commercial and GovCloud: partition derived from the region scope, refused when mixed or unsupported; partition-aware ARNs and global-service routing; CloudFront degrade; FIPS opt-in |
| req-aws-collector-grift-batch | [GRIFT Batch Assembly](#grift-batch-assembly) | Approved for Development | One batch/run; provenance; no deletion semantics |
| req-aws-collector-edge-authority | [Edge Authority Claims](#edge-authority-claims) | Implemented | Per anchor, how each manifest edge rule's source was read (complete, partial, failed); one `edge_cases.authority` claim per scope, sent only to an importer that accepts the section; a failed or truncated sub-call is never `complete` |
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
| `natural_key` | jsonpath to the value used for deterministic identity (see [Deterministic Identity](#deterministic-identity)). |
| `fields` | Map of model field name → jsonpath into the item (see [Field Projection](#field-projection)). |
| `hydrate` | Optional list of per-item hydrate ops, each `{key, op, why}` (see [Fan-Out Hydrate Seam](#fan-out-hydrate-seam)). |
| `edges` | List of declarative edge rules (see [Declarative Edge Rules](#declarative-edge-rules)). |
| `persist_configuration` | Required boolean. Whether this entry's `configuration` envelope is persisted (see [Field Projection](#field-projection), `req-aws-collector-field-projection-7`). |
| `persist_configuration_why` | Required, non-empty. One line saying why the flag has its value. |
| `sensitivity` | Required. Whether this entry's raw response may carry sensitive values, and where (see [Response Sensitivity Declaration](#response-sensitivity-declaration)). |

The manifest is pure data. The engine validates the manifest against a JSON
Schema shipped alongside it at load time; a malformed manifest fails the run
visibly (it is operator/author error, not a runtime condition).

Manifest entry order is advisory only — because edges resolve by deterministic
identity (not by matching an already-loaded node), the engine does not depend on
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

An entry whose `sensitivity` has a `credential`
location defaults to `persist_configuration: false`, and its
`persist_configuration_why` names the credential location. An entry that lists a
`credential` location and is persisted anyway is a **known, reviewed risk**: that
is only allowed with a reason that names every such location, so the acceptance
is visible where the decision is made. As shipped there are none — Lambda
and CloudFront, API Gateway HTTP API and Cognito user pool are off, and a
test fails if any credential-bearing entry is persisted. The canonical `tags`
model field is persisted independently ([Resource Tags](#resource-tags)) and is
not governed by `persist_configuration`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-manifest-1 | Data-Only Manifest | Approved for Development | The engine contains no per-resource-type branching; all per-type knowledge lives in the manifest. | The escape hatch is `custom_fn`, itself named in the manifest. |
| req-aws-collector-manifest-2 | Schema Validated | Approved for Development | The manifest validates against a shipped JSON Schema at load; invalid manifest fails the run visibly. | |
| req-aws-collector-manifest-3 | Order Independent | Approved for Development | Collection results are identical regardless of manifest entry order. | Enabled by deterministic identity. |
| req-aws-collector-manifest-4 | Versioned | Approved for Development | The manifest carries a version recorded in the GRIFT batch provenance. | Supports drift tracking. |
| req-aws-collector-manifest-5 | Self-Describing Entries | Approved for Development | Each entry carries a `why`, and each `hydrate` element a `{key, op, why}`; the schema requires `why` so every collected call's rationale is authorable and visible in the manifest. | Materialized per-node (`_source`) so a grid object is legible without the manifest, for every entry that persists its configuration (`req-aws-collector-field-projection-7`). |
| req-aws-collector-manifest-6 | Response Sensitivity Declared | Approved for Development | Every entry declares `sensitivity` in one of three states (`unreviewed`, `reviewed_none_known`, `reviewed_may_contain`); a missing declaration fails schema validation; `reviewed_may_contain` lists `{path, category, reason, evidence}` locations. | Ruling 2026-09-23. Credential locations default the entry to not persisting (see `req-aws-collector-field-projection-7`). `tests/test_boto3_collector_sensitivity.py`. |
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
| req-aws-collector-source-2 | Generic Pagination | Approved for Development | `aws_op` uses the botocore paginator when the model defines one, else a single call; no per-resource pagination code. | |
| req-aws-collector-source-3 | Registered Callables Only | Approved for Development | `custom_fn` resolves through a plugin-local registry; manifest data never drives code import or path loading. | |
| req-aws-collector-source-4 | Quarantined Complexity | Approved for Development | Multi-call assembly exists only inside `custom_fn` callables, never in the engine. | |
| req-aws-collector-source-5 | Custom-Fn Signature | Approved for Development | `custom_fn` callables accept `(session, *, client_for)`. `client_for(service) → Client` is bound to the current per-region iteration so regional custom_fns can build region-bound clients without inventing their own region resolution; global custom_fns accept-and-ignore. | Discovered in autonomous pass 2026-05-20 when DynamoDB regional collection failed with "You must specify a region." |

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
| req-aws-collector-field-projection-7 | Per-Entry Configuration Persistence | Approved for Development | Each manifest entry's required `persist_configuration` boolean and non-empty `persist_configuration_why` decide whether the emitted node payload carries the in-memory envelope or `{}`; typed fields, tags and edges are unchanged either way; an entry with a `credential` sensitivity location defaults to false; an `unreviewed` entry is always false (`req-aws-collector-manifest-7`); no model field is removed and no migration is written. | `tests/test_boto3_collector_batch.py`, `tests/test_boto3_collector_slice.py::test_credential_canary_is_not_persisted`, `::test_s3_bucket_persists_its_configuration_with_posture`, `tests/test_boto3_collector_sensitivity.py`. |
| req-aws-collector-field-projection-8 | Off-Type Security Facts Kept | Approved for Development | For entries whose `persist_configuration` is false, the Lambda VPC attachment (`vpc_subnet_ids`, `vpc_security_group_ids`), CloudFront per-origin access mode (`origin_access`) and API Gateway HTTP API per-route authorization type (`route_authorization_types`) are typed fields derived from data already fetched; configuration stays `{}`. | Migration 0007. `tests/test_boto3_collector_slice.py::test_promoted_security_facts_land_while_configuration_stays_empty`, `tests/test_boto3_collector_customfns.py::TestCloudfrontDistributionsWithOac::test_origin_access_mode_per_origin`, `tests/test_boto3_collector_new_service_types.py::TestApiGatewayHttpApisDetailed`. |
| req-aws-collector-field-projection-9 | CloudFront Origin Header Presence | Approved for Development | Each CloudFront origin's custom-header presence is the typed field `origin_custom_headers_present` (`{origin Id: bool}`), derived from the `ListDistributions` origin with no extra call; an origin without headers is `false`, not absent or `null`; no header value or name reaches the field, the GRIFT batch, the stored row or its history. | Migration 0008 (additive `AddField` only). `tests/test_boto3_collector_slice.py::test_origin_header_presence_lands_and_the_value_never_does`, `tests/test_boto3_collector_customfns.py::TestCloudfrontDistributionsWithOac::test_custom_header_presence_per_origin`. |

### Deterministic Identity
----
RID: `req-aws-collector-identity`

Status: `Approved for Development`

Every collected node and edge has a deterministic `entity_id` so that repeated
collection runs upsert in place rather than duplicating — the property that makes
"re-run the collector live in the demo" safe.

#### Implementation

- Node identity is `uuid5(NAMESPACE_AWS_COLLECTOR, f"{entity_type}:{natural_key}")`.
- The natural key is the value at the manifest's `natural_key` jsonpath.
  Preference order, declared per entry: the resource **ARN** where one exists
  (the dominant case — Lambda, IAM role, ACM, EventBridge, CloudFront, S3,
  CloudWatch log group);
  otherwise the stable AWS **resource id** (e.g. a hosted-zone id, a subnet id).
  The log group's key is its ARN without the `:*` suffix; how the `WRITES_LOGS`
  referrers reach it is in
  [v0 Make-It-Work: Mutually-Available Natural Keys](#v0-make-it-work-mutually-available-natural-keys).
- Edge identity is `uuid5(NAMESPACE_AWS_COLLECTOR, f"edge:{edge_type}:{from_key}->{to_key}")`.
- `NAMESPACE_AWS_COLLECTOR` is a frozen module-level UUID constant in the plugin;
  changing it would re-identify every collected node and is not permitted.

Because edge endpoints are computed from the same `uuid5` of the target's
natural key, an edge can be emitted before — or without ever — the target node
being collected in the same run; it resolves by identity, not by load order.
GRIFT's dangling-edge handling governs the not-yet-present case.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-identity-1 | Deterministic Nodes | Approved for Development | The same AWS resource always yields the same `entity_id` across runs and grids. | |
| req-aws-collector-identity-2 | ARN-Preferred Key | Approved for Development | Natural key is the ARN where available, else the stable resource id. `aws_cloudwatch_log_group` is keyed by its ARN without the `:*` suffix (`logGroupArn`), so same-named groups in two regions or accounts are two nodes. | Was keyed by `logGroupName` until tap-plugin-aws-core#60; the re-key changes its `entity_id`. |
| req-aws-collector-identity-3 | Deterministic Edges | Approved for Development | Edge identity derives from edge type plus endpoint natural keys. | |
| req-aws-collector-identity-4 | Idempotent Re-Run | Approved for Development | Re-running collection upserts; it never duplicates nodes or edges. | |

### Declarative Edge Rules
----
RID: `req-aws-collector-edges`

Status: `Approved for Development`

Relationships are materialized from declarative edge rules in the manifest entry,
resolved by deterministic identity. The probe established ~80% of valuable edges
are expressible this way.

#### Implementation

An edge rule declares:

| Key | Meaning |
| --- | --- |
| `value_path` | jsonpath into the item yielding the target's natural key — a scalar **or** a list. A list produces fan-out (one edge per element); this covers the common many-target case (e.g. an instance's network interfaces). |
| `target_type` | The target `aws_core` entity type. |
| `key_kind` | `arn` \| `id` \| `name` — declares which identifier space the target's natural key lives in. **Inert in the v0 engine**: it neither transforms nor interprets the extracted value. It is declared intent, consumed only by the backlogged [Edge Identifier Resolution](#edge-identifier-resolution-future-seam) seam. In v0, correctness rests entirely on `value_path` (+ optional `transform`) emitting *exactly* the target's `natural_key` string. |
| `edge_type` | An edge type already declared by `aws_core` (`req-aws-core-edges`). |
| `direction` | `outbound` (this node → target) or `inbound` (target → this node). |

The engine forms the target `entity_id` by *recomputing* the same `uuid5`
scheme as [Deterministic Identity](#deterministic-identity) from the value the
source side extracted, and emits the edge. It does **not** verify the target
was collected, and it does **not** consult `key_kind`. The honest consequence:
an edge connects **iff both ends independently derive the byte-identical
`natural_key` string** — the source side's `value_path`(+`transform`) output
must equal the target entry's `natural_key`. When they match (ARN→ARN:
`ASSUMES_ROLE`, `RETRIEVES_CERT_FROM`; transform→ARN: `RETRIEVES_CONTENT_FROM`)
the edge resolves with no lookup or ordering dependency. When they *cannot*
match — the source carries only a name/domain and the target's ARN needs
account/region/suffix the source item lacks, or a cross-resource join — the
recompute silently produces a `uuid5` no node has: a dangling edge, not an
error. v0 closes this by the manifest discipline below; the durable fix is the
backlogged [Edge Identifier Resolution](#edge-identifier-resolution-future-seam)
seam.

#### v0 Make-It-Work: Mutually-Available Natural Keys

Because the engine is identity-coincidence (not identity-*resolution*) in v0,
every edge that must connect for the demo is made to satisfy the
"both-ends-derive-the-same-string" invariant **by manifest choice alone — no
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
node's natural key as well as the value. Re-keying changes every log group's
`entity_id`; nodes keyed by name on an existing grid are not rewritten or
retired by the collector (`req-aws-collector-scope-3`) and remain until
reconciled or purged.

This spec defines the edge *mechanism* only. It introduces no new edge *types*;
edge-type and target-model selection for specific relationships is `aws_core`
model/edge work governed by `spec-aws-core-v0` (`req-aws-core-edges`). Edges
whose target key is not directly present in the item (derived keys — e.g.
matching a Route 53 alias to a CloudFront distribution by domain rather than
ARN) are supported via a small declared transform on `value_path`; edges that
require parsing an embedded IAM/resource policy document are **out of v0 scope**
and routed to the deferred policy-document resolver (`req-aws-collector-nongoals`).

**Two-phase application.** All nodes are emitted first, then edges in a separate
pass — nodes, then edges. Because endpoints resolve by deterministic identity,
the edge pass needs no per-target lookup. An edge whose `target_type` is not a
resource type this collector models/collects (an expected condition under the v0
fence — e.g. a reference to a not-yet-modeled service) is **dropped with a
recorded `warn`, never a run failure**; the edge pass is the single chokepoint
for that check rather than scattering it. An edge to a modeled type whose
specific instance was not collected this run is a dangling edge governed by
GRIFT's `dangling_edge_mode`; the AWS collector uses the mode that retains/skips
rather than fails, so a later run that collects the target resolves it by
identity.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-edges-1 | Declarative Rules | Approved for Development | Edges are emitted from manifest rules; the engine has no per-relationship code. | |
| req-aws-collector-edges-2 | Scalar And Fan-Out | Approved for Development | `value_path` supports scalar and list extraction; a list yields one edge per element. | |
| req-aws-collector-edges-3 | Identity-Resolved | Approved for Development | Edge endpoints resolve by deterministic `uuid5`, independent of collection order or target presence. | |
| req-aws-collector-edges-4 | Existing Edge Types Only | Approved for Development | Edge rules reference edge types already declared by `aws_core`; no new edge types are defined here. | |
| req-aws-collector-edges-5 | Policy Edges Excluded | Approved for Development | Edges requiring policy-document parsing are not emitted in v0. | Deferred resolver, named seam. |
| req-aws-collector-edges-6 | Two-Phase, Unmodeled-Safe | Approved for Development | Nodes are emitted before edges; an edge to an unmodeled `target_type` is dropped with a `warn`, never a failure; uncollected modeled targets follow GRIFT dangling-edge mode. | Single chokepoint for the v0-fence gap. |
| req-aws-collector-edges-7 | Mutually-Available Natural Keys (v0 make-it-work) | Approved for Development | v0 has no edge resolver: an edge connects iff both ends derive the byte-identical `natural_key`. Every demo-required edge satisfies this by manifest choice alone. `aws_cloudwatch_log_group` is keyed by its ARN, and both `WRITES_LOGS` referrers reach it through the `log_group_arn` transform (a Lambda's bare log-group name takes region and account from the Lambda's own ARN, handed to a source-aware transform). `key_kind` stays truthful but inert. | Deliberate, documented; durable fix is the backlogged `req-aws-collector-edge-resolver` seam. |

### Edge Identifier Resolution (Future Seam)
----
RID: `req-aws-collector-edge-resolver`

Status: `Backlog`

The durable fix for the fragility `req-aws-collector-edges-7` papers over by
manifest discipline. v0 resolves edges by *coincidence* — recompute
`uuid5(target_type, value_from_source)` and hope the string equals what the
target derived. A source that can only name its target by name/domain while the
target is ARN-keyed produces a **silent dangling edge**, and `key_kind` — the
field that exists to express exactly this — is inert.

The future design is a pre-`assemble_batch` **resolution pass**, not a new
identity scheme. `uuid5` stays the *id allocator* (it is what makes re-runs
idempotent, and GRIFT edges are `entity_id`-keyed regardless — see
`req-aws-collector-grift-batch`); the resolver is the missing *lookup layer*
on top of it. Mechanically, with the run's nodes already in memory before batch
assembly:

1. Index the collected nodes by their standard identifiers (ARN, resource id,
   name) per `target_type`.
2. For each edge rule, resolve the target in that index using the identifier
   the source actually carries — **`key_kind` becomes the live input** that
   selects which identifier space to match in (`arn` \| `id` \| `name`).
3. Three outcomes:
   - **(a) resolved** — stamp the resolved node's `entity_id` (still its
     `uuid5` id; idempotency preserved). Verified-present, not assumed.
   - **(b) supported `target_type`, not found** — `warn` + drop. No fabricated
     dangling edge; the miss is observable (rate-limit / permission / scope
     gap is the operator's to read), replacing today's silent failure.
   - **(c) unsupported `target_type`** — already handled today (`warn` + drop,
     the v0 fence — `req-aws-collector-edges-6`); the resolver subsumes it.

Honest cost, and the reason `uuid5` stays *under* the resolver rather than
being replaced: an edge to a node collected in a *prior* run but not *this*
one would `warn`+drop instead of resolving. Acceptable under v0's
collect-everything-every-run scope; revisit if incremental/partial collection
ever lands. Converges conceptually with the grid **hotlink** identifier-
resolution model (a node findable by any of its identifiers); design that
alignment in-spec first if/when built. Demand-signal-gated, not built;
the loud-by-construction warnings are the payoff that justifies it over the
manifest workaround when the signal arrives.

**Grid as the resolution backstop (refinement).** The resolver's index need
not be limited to *this run's* in-memory node set. The grid is fully
functional and already holds every previously-collected node with its ARN and
associated identifiers as standard `BaseModel` fields; the collector is an
ordinary Python process that can read it. So the authoritative index is the
**grid itself**, consulted through a *service-layer read* (a gryphon query, or
a generated search/ORM-backed runner if gryphon lacks the shape — never ad hoc
per-model ORM iteration; that brute-force fallback is the thing the canonical
path exists to avoid, not the design). This is exactly the resolution one
would do anyway absent `uuid5`; `uuid5` is the optimistic accelerator (skip
the lookup when both ends provably coincide), the grid read is the
authoritative relief valve for every case where they might not. It
**dissolves the "honest cost" above**: an edge to a node collected in a prior
run but not this one now *resolves* against the grid instead of `warn`-
dropping. The conscious tradeoff to record (it ties to
[Audit Verifiability](#audit-verifiability)): a resolver that reads grid state
makes the batch no longer a pure function of the AWS responses + manifest
alone. Resolution stays a *lookup* (it does not alter what AWS reported, so
the batch remains a faithful projection); the grid-state dependence becomes
load-bearing only for **reconciliation/tombstone**, which is inherently a diff
and shares this same grid-read primitive — see
the grid-state reconciliation seam (`req-aws-collector-reconcile`) under
[v0 Non-Goals](#v0-non-goals).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-edge-resolver-1 | Seam Named, Not Built | Backlog | The pre-batch edge-resolution pass (collected-node index keyed by standard identifiers; `key_kind`-driven target lookup; resolve / warn-drop / unsupported-drop) is specified here as the durable replacement for `req-aws-collector-edges-7`'s manifest workaround. Not implemented in v0. | The three-case model. |
| req-aws-collector-edge-resolver-2 | uuid5 Retained As Allocator | Backlog | The resolver does not replace `uuid5` identity; it adds a lookup layer above it. `uuid5` stays the idempotent id allocator (`req-aws-collector-identity`); GRIFT edges remain `entity_id`-keyed. | Two jobs, decoupled. |
| req-aws-collector-edge-resolver-3 | Misses Are Observable | Backlog | A supported-type target not found in the run resolves to a recorded `warn` + dropped edge, never a silent dangling edge. | The correctness payoff. |
| req-aws-collector-edge-resolver-4 | Grid Is The Backstop | Backlog | The resolution index is the grid (via a service-layer read), not only this run's in-memory set; this dissolves the prior-run cost. Reads never use ad hoc per-model ORM iteration. Shares the grid-state-read primitive with `req-aws-collector-reconcile`. | uuid5 = accelerator; grid read = authoritative relief valve. |

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
| req-aws-collector-regions-3 | Bounded Throttle Backoff | Approved for Development | Throttling retries with bounded backoff; unbroken throttle fails per protocol. | |
| req-aws-collector-regions-4 | No Data Corruption On Skip | Approved for Development | A skipped region/resource never alters previously collected data. | v0 has no deletes; reaping must honor this. |

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

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-collector-partition-1 | Derived From Regions | Implemented | The run's partition is derived from the secret's region scope; a declared `partition` is only a cross-check. | `tests/test_govcloud.py::TestResolvePartition` |
| req-aws-collector-partition-2 | Mixed Or Unknown Refused | Implemented | A scope spanning partitions, an unrecognised region, a disagreeing `partition`, an unsupported partition, or a `role_arn` in another partition is refused by name before any AWS call (`PARTITION_UNUSABLE`). | `TestResolvePartition`, `TestCollectorRunInGovCloud::test_partition_mismatch_aborts_by_name_before_any_aws_call` |
| req-aws-collector-partition-3 | Partition-Aware ARNs | Implemented | ARNs are parsed in any partition and built in the run's partition; no `arn:aws:` literal decides it. | `TestPartitionAwareTransforms`, `TestCustomFnsUseTheRunsPartition` |
| req-aws-collector-partition-4 | Global Services In Partition | Implemented | Global-service clients bind to a region of the run's partition; the partition's home region is the only fallback literal. | `TestGovCloudEndpoints`, `test_no_hardcoded_commercial_partition_or_region_in_collector_code`. Offline against botocore's endpoint data; no live GovCloud run observed. The falsifiers are outside the guard. |
| req-aws-collector-partition-5 | CloudFront Degrades In GovCloud | Implemented | A service the partition does not offer is recorded as not available and never called. | `test_run_lands_govcloud_shaped_nodes_and_says_cloudfront_is_not_offered` |
| req-aws-collector-partition-6 | FIPS Opt-In | Implemented | `use_fips_endpoint` true/false is pinned on the session and reaches every client; absent defers to botocore's environment/shared-config resolution; the effective value is reported. | `TestGovCloudEndpoints`, `TestSelfTestReportsPartition` |

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
- Nodes and edges use the deterministic identities from
  [Deterministic Identity](#deterministic-identity).
- The document is submitted via `self.submit_grift(...)`; the returned result's
  imported/skipped batch ids and counts inform `self.summary`.
- No deletion, tombstone, or implied-absence content appears in the batch
  (`req-aws-collector-scope-3`).
- Dangling-edge handling uses GRIFT's standard mode; the deterministic-identity
  design means most cross-resource edges resolve even when emitted before their
  target.

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
- **One claim per scope.** All rules of one edge type and direction at one anchor fold into one
  claim with the worst read. The anchor is named by its entity id. A scope another manifest entry's
  rules also write into is not claimed. Containment, Organizations, landing-zone and findings edges
  are not claimed: their completeness is the reconcile surfaces' business.
- **Sent only where accepted.** The claims are carried as the batch's `edge_cases.authority` when
  the running tap's GRIFT schema defines that section; this plugin's tap floor predates it, so on an
  older tap the claims are judged, logged, and not sent. Either way the run records one
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
deterministically-identified nodes. An untagged resource simply gets
`tags: {}` — the correct answer, not a gap. And because nodes are keyed
`uuid5(type, natural_key)` where `natural_key` is the ARN for almost all
types, the RGTA `ResourceARN`→node join is identity-equal — it does *not*
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
| req-aws-collector-fanout-1 | Organization Listing Drives Fan-Out | Proposed | The member set is this run's organization-wide `ListAccounts`, `ACTIVE` members only, minus the base account and the secret's exclude list. It is never read from grid state, and fan-out does not run unless that listing read to its end and the base account is the organization's `MasterAccountId`. | |
| req-aws-collector-fanout-2 | Partition-Aware Role ARN | Proposed | The member role ARN is `arn:<run partition>:iam::<member>:role/<member_role_name>`, with the partition from the run's resolved partition; no literal `arn:aws:` appears in the fan-out path. | A GovCloud test captures `arn:aws-us-gov:iam::…` on the wire, as `test_govcloud.py:351-399` does for the single role. |
| req-aws-collector-fanout-3 | Assert-On-Land Per Member | Proposed | After `AssumeRole`, the member session's `GetCallerIdentity` account equals the member id, or the member is skipped as `MEMBER_ACCOUNT_MISMATCH` and nothing from it is written. | Reuses `account_mismatch_error`. |
| req-aws-collector-fanout-4 | Member Failure Is Local | Proposed | A denied or failed `AssumeRole`, a member identity mismatch, or a member's rejected batch is recorded as that account's outcome and the run continues. A base-credential, partition or base-identity failure, or a rejected base batch (`-21`), still aborts. | |
| req-aws-collector-fanout-5 | Per-Account Results | Proposed | Every listed account has exactly one `ACCOUNT_RESULT` entry (id, outcome ∈ `collected\|partial\|skipped`, reason, regions, counts, batch id), and the summary counts each outcome. The batch id is `null` for an account skipped before any batch was submitted, and the rejected batch's id for an account whose batch was rejected. | The per-account run results the epic asks for. |
| req-aws-collector-fanout-6 | One Batch Per Account | Proposed | Each account's observations are one GRIFT batch submitted with `on_rejection="return"`; a rejected member batch fails only that account, and a rejected base batch stops the run (`-21`). The organization tree, including one org-sourced `aws_account` envelope per listed account, is the base account's observation and is in the base batch, which is submitted first; a collected member's batch re-carries its account's merged envelope. | Supersedes `req-aws-collector-grift-batch-1` for fan-out runs. |
| req-aws-collector-fanout-7 | Surfaces Per Account | Proposed | Completeness surfaces are recorded per account against that account's own batch. A listed member that was not collected records, for each containment edge type declared on its `aws_account` node (observed this run through the base batch's tree envelope), a surface with `scope_authorized: false` and the reason, never omitting one; it records no surface for parents below the account, which this run did not observe. With no submitted batch those surfaces carry `applied_batches: []`; with a rejected batch they cite it, so core derives `applied: false` either way. | Consistent with `req-aws-core-contained-type-triple` (no surface for an unobserved parent). Core counts only `scope_authorized: true` surfaces as in scope (`tap_grid/candidates.py` `_scope_of`), so recording a not-authorized surface and omitting one read the same to withdrawal: core still derives `scope_withdrawn` candidates for the member's previous surfaces, and the falsifier is the backstop (`-9`). The not-authorized surfaces carry the reason on the record. Nothing is armed (unified-systems-com/aws-core-tap#14). |
| req-aws-collector-fanout-8 | Account Node Merged In A Run | Proposed | For every account both the organization tree and a member collection describe in one run, the member's batch carries one envelope whose fields are the union by source (the org-sourced values from this run's tree plus the account-sourced ones); neither reader's fields are dropped or blanked, and the base batch's earlier tree envelope is superseded by it. | Generalizes `collector.py:635-653`, which keeps the tree node and drops the singleton's fields. |
| req-aws-collector-fanout-9 | Falsifier Reach Per Account | Proposed | A falsifier resolves the candidate's account credentials through the base-then-member-role path, with assert-on-land; an unreachable account is `UNDETERMINED(scope_unknown)`. | Today every falsifier resolves the one secret (`falsifiers.py:449-485`). |
| req-aws-collector-fanout-10 | Bounded, Never A Silent Prefix | Proposed | Members are collected serially; a member count above `max_member_accounts` refuses the fan-out with `FANOUT_CAP_EXCEEDED` and still collects the base account. | |
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
