# AWS Core Live Validation Specification

## Philosophy

Every type in the manifest was built from botocore and the CloudFormation schemas, never from a response.
The ledger says so in the only honest way it can: `collected-unverified`. A type becomes
`collected-verified` only after "a live trial has run" (`spec-aws-core-coverage-ledger.md`), and until now
there was no account to run one in.

There is now a GovCloud account, and the work this specification governs is the trial itself: how to
establish, for each of the +1,000 collected shapes, that the collector's call works, that it turns a real
resource into the right row, and that the row agrees with an independent reading. It cannot be done in one
pass. The cost of creating the resources, the order in which they matter, and the fact that the collector
can only be scoped by region today all push the same way: validate in **waves**, ordered by a weighting,
each wave created, tested and destroyed before the next.

The collection oracle (`spec-aws-core-collection-oracle.md`) says how to compare the grid with a reference.
This specification says what to compare, in what order, against what seed, and what a pass earns.

## Provenance

- Read 2026-11-01: the collector's run loop in `collector.py` (regions and partition are the only scoping;
  every manifest entry is walked), the coverage ledger specification (`collected-verified` is defined as
  "a live trial has run"), the oracle specification, and the crosscheck weighting files.
- Told by the operator 2026-11-01 (not observed): a GovCloud staging account exists (partition `aws-us-gov`, one home
  region); the collector runs under a read-only identity; a separate seeder identity creates and tears down; the
  account already holds networking the infrastructure repository does not declare, so its existing contents are
  treated as unknown. Account identifiers and policy details are deliberately not recorded in this public file.
- Not read or run: Terraform and either AWS provider (whether the Cloud Control provider works in GovCloud is
  unchecked), any live response, the completeness and retirement code paths under a subset run, and whether
  the account is an AWS Organizations member.
- Designed, not run. Every requirement is Proposed.

Tracked by `unified-systems-com/aws-core-tap#107`.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Staged        | No more is created, run or paid for at once than the wave needs |
| 2. | Prioritised   | What matters most is validated first, by a weighting kept as data |
| 3. | Evidenced     | Moving a type to `collected-verified` rests on a stored record of what ran |
| 4. | Honest        | A type that cannot be seeded says so; an unrun type is unobserved, never empty |
| 5. | Safe          | The collector never writes; only the seeder creates; teardown touches only what the run created |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-aws-core-livevalidation-layers | [Three Layers](#three-layers) | Proposed | Call path, projection, independent reading; what each proves |
| req-aws-core-livevalidation-selection | [Type Selection](#type-selection) | Proposed | Include and exclude on entity type; unrun means unobserved |
| req-aws-core-livevalidation-result | [Per-Type Result](#per-type-result) | Proposed | One record per type per run |
| req-aws-core-livevalidation-smoke | [Smoke Wave](#smoke-wave) | Proposed | Wave 0: every collected type, no seeding |
| req-aws-core-livevalidation-seed | [Seeding](#seeding) | Proposed | Terraform under `tools/seed`, tagged, state as expected inventory |
| req-aws-core-livevalidation-catalog | [Seed Catalog](#seed-catalog) | Proposed | Per-type seeding facts, as data |
| req-aws-core-livevalidation-waves | [Waves](#waves) | Proposed | A planner turns weights, ledger state and the catalog into ordered waves |
| req-aws-core-livevalidation-verdict | [Verdict And Promotion](#verdict-and-promotion) | Proposed | What a pass is; what moves a ledger row |
| req-aws-core-livevalidation-lifecycle | [Lifecycle](#lifecycle) | Proposed | Delete in AWS, collect again, and confirm the grid retires it and what it contains, with negative controls |
| req-aws-core-livevalidation-safety | [Safety](#safety) | Proposed | Identities, regions, cost, teardown, state |

### Three Layers
----
RID: `req-aws-core-livevalidation-layers`

Status: `Proposed`

Validation has three layers. A type can pass one without the next, and the report keeps them apart.

| Layer | Needs | Proves | Does not prove |
| --- | --- | --- | --- |
| Call path | The account as it is | The operation exists in the partition, its parameters are accepted, the credential is enough, the response parses | Any field mapping, tag, or edge |
| Projection | One seeded resource of the type | The natural key, every typed field, the tags and the edges equal what was created | That another tool would see the same |
| Independent reading | A seeded resource and a second source | The grid and a reference agree (the oracle) | Types the reference cannot list |

A zero-row response passes the call path only. It is recorded as `call-path-only`, never as a pass of the
type.

### Type Selection
----
RID: `req-aws-core-livevalidation-selection`

Status: `Proposed`

Type selection is specified by `req-aws-collector-selection`: `include_types` and `exclude_types`, held in the
credential's `data` (`req-aws-core-secret-selection`), patterns over `<service>:<entity>`. This section keeps what
validation needs of it. With neither key, behaviour is unchanged. An entry whose type is excluded is not
read. A parent that a selected type fans out from (a `per` or `bind` source) is read as the input of the
selected type and emits nothing unless it is itself selected.

An unselected type is **unobserved** in the run, not empty. The run must not write a completeness surface,
a retirement candidate or a "no longer seen" signal for a type, a region or a parent it did not read, and
the keep-absent upsert semantics (`tap#1128`) must hold for every row of an unselected type. Before the
filter ships, the completeness and retirement paths are read and a test shows a subset run leaves every
unselected type's rows and surfaces untouched. A pattern that matches no type is an error, not an empty
run.

The weighting is not read by the collector. A planner (see Waves) produces the explicit list.

### Per-Type Result
----
RID: `req-aws-core-livevalidation-result`

Status: `Proposed`

Each run writes one record per selected type:

| Field | Meaning |
| --- | --- |
| `entity_type`, `region` | What was read, where |
| `outcome` | `ok`, `empty`, `error` or `unobserved` |
| `error_class` | For `error`: `access-denied`, `unsupported-in-partition`, `validation`, `throttled`, `truncated`, `other`, with the AWS error code |
| `rows`, `calls`, `seconds` | Volume, API calls made, wall time |
| `truncated` | Whether the read was cut short and why |

The record is data, written next to the run, and holds no resource content. Volume and call counts are what
settle the first-live-run questions (Lambda listing volume, ECS task-definition describes, Glue tables,
Firehose stream limits).

### Smoke Wave
----
RID: `req-aws-core-livevalidation-smoke`

Status: `Proposed`

Wave 0 runs every `collected-unverified` type once with the collector identity, read-only, in the home
region (and in the other regions the type's scope names), with no seeding. Its output is the per-type
result for the whole manifest. It is the cheapest source of real defects: a wrong operation name, a missing
parameter, an operation absent in GovCloud, an action the read-only policies omit. Each `error` is triaged
into a collector defect, a permission residue for the collector policy, or an `unsupported-in-partition`
fact for the ledger. Nothing is created in the account.

### Seeding
----
RID: `req-aws-core-livevalidation-seed`

Status: `Proposed`

Resources are created by Terraform modules under `tools/seed/`, one module per wave and one subdirectory per
service, outside the wheel. Rules:

1. **Tagged.** Every taggable resource carries `tap-seed = <wave>` and `tap-seed-run = <run id>` through the provider's default tags, so the
   oracle scopes to the seeded set and the tag path is exercised on every type that has one. Resources that
   cannot carry tags are recorded in the expected inventory by identifier.
2. **State is the expected inventory.** After apply, a script reads the Terraform state and writes the
   expected inventory: for each resource its CloudFormation type, identifier, ARN and the attributes the
   projection check compares. The collector never reads the state; the state is the known truth, not an input.
3. **Named for the seeder.** IAM roles, users, policies and instance profiles are named `seed-*`, the only
   names the seeder may create.
4. **Awkward on purpose, and bounded.** A module includes the cases the oracle names: an untagged resource, odd tag
   keys, a second region, a public setting. A public setting is **inert**: it exists only to be read, and nothing is
   reachable through it. Concretely, a security-group rule open to the internet on a high port while the group is
   attached to nothing; never a public bucket policy or ACL, never a public IP address, never a resource that holds
   data or listens. It is created and destroyed within the wave, and a module that would make anything reachable is
   refused by review, not tuned.
5. **Provider.** The Cloud Control provider (`awscc`) generates resources from the CloudFormation schemas, so its
   type names are our key space. Where it is unavailable in GovCloud, the `aws` provider is used and the catalog
   carries the mapping. This is an open question.
6. **Destroyed.** A wave is applied, collected, compared and destroyed in one session (see Safety).

### Seed Catalog
----
RID: `req-aws-core-livevalidation-catalog`

Status: `Proposed`

`tools/seed/seeding.json` holds, per CloudFormation type, the facts the planner needs, as data:

| Field | Meaning |
| --- | --- |
| `cfn_type` | The ledger row |
| `terraform` | Provider and resource type, or `null` |
| `cost_class` | `free`, `cheap`, `costly` or `blocked` |
| `blocked_reason` | For `blocked`: why it cannot be seeded (subscription, hardware, organization, minimum spend) |
| `needs` | Other catalog types that must exist first |
| `compares` | The typed fields the projection check compares, by manifest field name. It lists every typed field the manifest fills for the type, except those named in `compares_excluded` |
| `compares_excluded` | Typed fields deliberately not compared, each with a reason (not settable by the seed module, derived by the service, a secret never read) |
| `module` | The module that creates it |

A type with no entry is treated as `unseeded`, not as `free`. Entries are reviewed; a `blocked` type is
validated at the call-path layer only and its ledger note says so.

### Waves
----
RID: `req-aws-core-livevalidation-waves`

Status: `Proposed`

A planner script reads a crosscheck weighting (`tools/crosscheck/weights`, `cfn_type` rules), the ledger and the
seed catalog, and writes an ordered list of waves. Ordering is by weight descending and, within a weight, by
cost class (`free` first), then by `needs`. The first waves are fixed by intent:

| Wave | Contents |
| --- | --- |
| 0 | Every collected type, call path only (Smoke Wave) |
| 1 | Weight 5, `free` or `cheap`: identity, VPC and EC2 basics, S3, KMS, queues and topics, Lambda, DynamoDB, audit |
| 2 | Weight 5, `costly`: databases, EKS, Redshift, search; each destroyed straight after its check |
| 3 | Weight 3, including Bedrock |
| 4 | The rest of the weighted set, then unweighted types |

The planner takes the weighting file as an argument, so a different weighting gives a different order. It also
prints the progress figure: the weighted share of ledger types at each state.

### Verdict And Promotion
----
RID: `req-aws-core-livevalidation-verdict`

Status: `Proposed`

A type passes the **projection** layer when, for every seeded resource of the type in the expected inventory:
the collector returned exactly one row; its natural key equals the expected key; `compares` and `compares_excluded`
together name every typed field the manifest fills for the type, and `compares` is not empty (a catalog entry that
leaves a field in neither list fails review, not the run); every field in `compares` equals the expected value; the tags equal the seeded tags (including `{}` for an untagged resource and no `null`
where a read was possible); every edge the manifest declares for the type, whose target was also seeded, was
emitted; and a second run produces the same rows with no duplicate. It fails with the first mismatch named.

A type is promoted to `collected-verified` only when the projection layer passed in a recorded run and the
independent reading, where the reference can list the type, agrees. Promotion is a change to the ledger
decisions with the run record cited; it is made by a person reading the record, not by the script. A type
validated at the call path only stays `collected-unverified` with the evidence noted. A failed type stays as
it is and the failure becomes an issue.

### Lifecycle
----
RID: `req-aws-core-livevalidation-lifecycle`

Status: `Proposed`

The seed waves also test deletion, because a collector that never notices a deleted thing leaves the grid asserting
what no longer exists. This is a layer beyond projection: it needs the **full collector run that submits to the grid**
(the engine-path harness used for projection writes nothing there), the grid's reconciliation (`spec-grid-reconcile.md`:
retirement ends an observation, not the thing; it needs evidence, a per-type falsifier and an operator-armed
authority that is off by default) and containment cascade (`spec-grid-cascade-corpus.md`).

Preconditions: the test stack only; reconcile authority armed for this collector on that stack with a stated budget,
and disarmed afterwards; the wave applied and collected so the grid holds its nodes and edges (checked against the
expected inventory). Types in scope are those that declare containment, a completeness surface and a falsifier
(`req-aws-core-contained-type-triple`): VPC, subnet, security group, EC2 instance, and the account-contained IAM and
S3 types, all in wave 1.

Cases, each recorded pass or fail with its evidence:

| Case | Action | Expected |
| --- | --- | --- |
| Leaf with edges | Destroy the instance alone (`terraform destroy -target`), collect again | The instance's observation ends with recorded evidence; every edge incident to it ends; its subnet, security group, instance profile and volume are untouched |
| Contained child | Destroy a subnet that is empty, collect again | The subnet retires; the VPC and its sibling subnet are untouched |
| Account-contained | Destroy a role (with its attachments), then a bucket | Each retires; the account node and the other roles and buckets are untouched |
| Subtree | Destroy the rest of the VPC's contents, then the VPC | The VPC retires after its children, in AWS's dependency order; nothing outside it moves |
| History | Read a retired node | The row remains with a terminal observation lifetime; it is not removed |
| Return | Create an object with the same natural key again, collect | A new observation lifetime, not a contradiction |

Negative controls, which matter as much: **absence of evidence must retire nothing.** (1) A run whose listing for a
type is refused (use a type the read-only identity is denied, from the wave 0 record) retires none of that type. (2) A
run restricted to a subset of types retires nothing of the types it did not read (this settles the subset-run open
question below). (3) A run with reconcile authority off retires nothing. (4) A truncated or throttled listing retires
nothing. Each is run with a seeded object present, so a wrong retirement would be visible.

Cascade is reported separately from retirement: for each retirement, the nodes and edges that went with it, listed
against the containment declarations, so a missing or an extra cascade is a named finding.

### Safety
----
RID: `req-aws-core-livevalidation-safety`

Status: `Proposed`

1. **Two identities, never mixed.** The collector uses the read-only profile and nothing else. The seeder
   profile is used only by the seed tooling. Neither profile's keys appear in a file, a state backend, a report
   or a message.
2. **Scope.** Seeding is limited to the regions the wave names; every wave names at most the home region and one
   other. The pre-existing contents of the account are unknown and are never modified or destroyed; only
   what the run's own Terraform state created is destroyed (see item 4).
3. **Cost.** Each wave declares an estimated cost and a duration before apply. A `costly` module has a time box
   after which it is destroyed whether or not the check finished.
4. **Teardown is part of the wave, and bounded by the run.** The wave ends with `terraform destroy` against that
   run's own state; the state is the allowlist, and nothing is deleted by tag or by name. Before apply and before
   destroy the run verifies the account and region it is acting in against what the wave declares. A final check
   lists anything still carrying `tap-seed` and reports it as the wave's failure for a person to resolve; it does
   not delete it. A resource left by an interrupted earlier run is that run's to clean up, identified by its
   `tap-seed-run` marker, never swept up by a later one.
5. **State.** Terraform state is local to the run, not committed, and removed after destroy. It can hold
   secrets, so it is treated as one.
6. **No guessing at limits.** A wave that hits a quota or an `unsupported-in-partition` error records it; it does
   not retry around it.

## Open Questions

1. **Provider.** Does the Cloud Control (`awscc`) provider work against GovCloud endpoints? If not, the `aws`
   provider with a mapping table is the path.
2. **Subset-run semantics.** Does the current completeness and retirement logic treat an unread type as
   unobserved? Read the code and add the test before the filter ships.
3. **Organization.** Is the account an AWS Organizations member? Organization-level types are `blocked` if not.
4. **Budget.** A cost ceiling per wave and per day.
5. **Where verified evidence lives.** In the ledger decisions as a citation, or as files under `ledger/`.
6. **Firing a full run on the test stack.** How a complete collector run, with its collection job and collector node, is
   started on the local stack so that it submits to the grid; and which operator arms reconcile authority and the budget
   to use.
