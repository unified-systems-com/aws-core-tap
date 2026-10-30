# AWS Core Collection Oracle Specification

## Philosophy

`aws_core` collects AWS into the grid with its own readers, on purpose: Steampipe's AWS plugin is
robust, but running it means carrying Steampipe, and Cartography means carrying Neo4j. The cost of
going our own way is that nothing independent says our collection is complete or correct. The
coverage ledger says what we *intend* to collect; it cannot say what a live account holds that we
failed to see.

This specification describes an **oracle**: a separate, standalone script that asks AWS, and
optionally other mature collectors, what an account contains, and then compares that answer with what
`aws_core` put on the grid. It is a test instrument, not a product feature. It reads AWS and the
grid and writes a report. It never writes to either, it is not part of the `aws_core` wheel, and it
is not on the collection path, so it adds no runtime dependency to TAP.

The comparison is ordered by what it is worth. First, **inventory**: does the grid hold every
resource the reference sees, and nothing the reference cannot find? Second, **tags**, which this
project treats as critical. Third, a short list of **security attributes**. Most of the value is in
the first, and it is cheap; the third is expensive because every tool names fields differently, so
it is kept small on purpose.

## Provenance

- Read, 2026-10-30, from the projects' GitHub pages through a fetch tool, not from source:
  `turbot/steampipe-plugin-aws` (Apache 2.0; installed into the Steampipe CLI, which bundles
  Postgres; also usable as a Postgres foreign data wrapper or SQLite extension; the page also
  describes an Export option, a standalone binary that extracts data without a database) and
  `cartography-cncf/cartography` (Apache 2.0, CNCF sandbox; needs Neo4j; queried with Cypher;
  models an `AWSAccount` linked to resources by a `RESOURCE` relationship).
- Not read: either project's table or node schema, the Steampipe Export binary's output format and
  size, or Cloud Control's per-type list limits. Each is checked before the adapter for it is built
  (see Open Questions).
- Designed, not run. Nothing here has been exercised against an account. Every requirement is
  Proposed.

Tracked by `unified-systems-com/aws-core-tap#107`, as the independent check on its goal X1.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Independent   | The reference answer comes from a source that shares no code with our readers |
| 2. | Light         | Nothing large is vendored or linked; reference tools run as separate processes |
| 3. | Read-only     | The oracle never writes to AWS or to the grid |
| 4. | Attributable  | Every disagreement names which side is wrong, using a known-truth account where one exists |
| 5. | Honest        | A resource the reference cannot see is reported as out of the oracle's scope, never as a pass |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-aws-core-oracle-standalone | [Standalone](#standalone) | Proposed | Separate script, no TAP import, no writes |
| req-aws-core-oracle-sources | [Reference Sources](#reference-sources) | Proposed | Cloud Control first, Steampipe Export second, Cartography optional |
| req-aws-core-oracle-normal-form | [Normal Form](#normal-form) | Proposed | One record shape every adapter emits |
| req-aws-core-oracle-inventory | [Inventory Diff](#inventory-diff) | Proposed | Which resources each side has |
| req-aws-core-oracle-tags | [Tag Diff](#tag-diff) | Proposed | Tags per resource, including unread versus untagged |
| req-aws-core-oracle-attributes | [Attributes](#attributes) | Proposed | A small allowlist of security fields |
| req-aws-core-oracle-truth | [Known Truth](#known-truth) | Proposed | A seeded account decides who is wrong |
| req-aws-core-oracle-noise | [Matching And Noise](#matching-and-noise) | Proposed | Identity mapping, scope gaps, timing |
| req-aws-core-oracle-report | [Report](#report) | Proposed | Output, and how it feeds the ledger |

### Standalone
----
RID: `req-aws-core-oracle-standalone`

Status: `Proposed`

The oracle is one script (or a small package) in its own directory, outside `tap_plugin/aws_core`, and
outside the wheel. It does not import TAP or `aws_core`. It reads the grid through the grid's own
HTTP API, with a credential the operator supplies, and reads AWS with the operator's own read-only
AWS credentials. It writes only its report. It holds no secret in a file it creates, and the report
never contains a credential, an ARN's secret-bearing component, or a tag value flagged sensitive by
the collector.

Reference tools are started as child processes and their output is read as data. They are not
imported, vendored, linked, or pinned into TAP's dependency set. The oracle runs with only the
reference sources that are installed; a missing source is reported as "not run", not as a pass.

Credentials are a secrets matter and `manage-secret` runs before the first line of code that reads
one.

### Reference Sources
----
RID: `req-aws-core-oracle-sources`

Status: `Proposed`

Each source is an adapter that turns its native output into the normal form. Order and purpose:

1. **AWS Cloud Control API** (`ListResources`, keyed by CloudFormation type). First-party, needs no
   install, and uses the same type names as the coverage ledger, so a gap maps directly to a ledger
   row. Limits to check before relying on it: types that cannot be listed without a parent
   identifier, types it does not support, and per-type throttling.
2. **Steampipe Export** (the standalone extraction binary for its AWS plugin), run as a child
   process, output read as JSON. Independent of both Cloud Control and our readers, and the better
   source for tags and attributes.
3. **Cartography**, optional. Needs a Neo4j instance, so it runs only when the operator already has
   one; the oracle reads it with Cypher and does not start it.

A fourth, AWS Config or Resource Explorer, is deliberately left out of v0: both depend on the account
having them enabled, which the oracle must not change.

### Normal Form
----
RID: `req-aws-core-oracle-normal-form`

Status: `Proposed`

Every adapter, and the grid reader, emits records of one shape:

| Field | Meaning |
| --- | --- |
| `partition`, `account`, `region` | Where the resource lives; `region` is `global` for global services |
| `cfn_type` | The CloudFormation type name, as in the ledger (for example `AWS::RDS::DBCluster`) |
| `arn` | The resource's ARN where it has one, else `null` |
| `ident` | The type's primary identifier as the source reports it |
| `tags` | A string-to-string map, `{}` for read-and-untagged, `null` for not read |
| `attrs` | The allowlisted attributes only (see Attributes), each possibly `null` for not read |
| `source` | Which adapter produced it |

`tags` keeps the grid's own convention (`null` is not read, `{}` is untagged), so an oracle that could
not read tags is never mistaken for one that found none.

### Inventory Diff
----
RID: `req-aws-core-oracle-inventory`

Status: `Proposed`

For each `(account, region, cfn_type)` the oracle computes, per reference source, three sets: in both,
in the reference only, in the grid only. The verdicts are:

| Verdict | Meaning |
| --- | --- |
| match | Both sides hold the resource |
| missing-from-grid | The reference has it and the grid does not: a candidate collection gap |
| extra-in-grid | The grid has it and the reference does not: a stale node, a wrong scope, or a reference gap |
| out-of-oracle-scope | The reference cannot list that type, or the type is not collected by design (an `excluded` or `unclassified` ledger row) |

A `missing-from-grid` for a type the ledger lists as `collected-unverified` is the highest-value
finding the oracle produces. A `missing-from-grid` for an `unclassified` type is not a bug; it is the
ledger's own backlog and is reported as such.

### Tag Diff
----
RID: `req-aws-core-oracle-tags`

Status: `Proposed`

For every resource in both sets, the oracle compares tag maps. Findings:

| Finding | Meaning |
| --- | --- |
| tags-match | Identical maps |
| tag-missing-from-grid | The reference has a key the grid lacks |
| tag-value-differs | Same key, different value |
| grid-unread | The grid holds `null` where the reference read a map: our reader did not read tags for that type |
| reference-unread | The reference reports no tag data where the grid has some |

`grid-unread` on a type whose ledger row claims a tag lane is a defect in the lane. Keys the reference
adds itself (for example Cartography-internal or Steampipe-internal columns) are excluded by an
explicit, reviewed list in the adapter, never by a pattern.

### Attributes
----
RID: `req-aws-core-oracle-attributes`

Status: `Proposed`

Attribute comparison covers an allowlist kept in a data file: a short list of `(cfn_type, field)`
pairs chosen for security value (encryption on, public access, deletion protection, state), each with
the grid field it maps to and the reference column or property it maps to in each source. A pair is
added only with all three names written down. Attribute comparison is not generalised to "every
field": field names differ across tools, and a broad comparison would produce noise that hides the
inventory and tag findings.

### Known Truth
----
RID: `req-aws-core-oracle-truth`

Status: `Proposed`

The first run, and every run after the oracle itself changes, is made against a **seeded account**:
one where the operator created a known set of resources (including deliberately awkward ones: untagged,
tagged with odd keys, in a second region, with a public setting) and wrote the list down before any
tool ran. For a seeded account the report shows three columns, not two: known truth, each reference
source, and the grid. A disagreement is then attributed:

| Pattern | Reading |
| --- | --- |
| Truth and reference agree, grid differs | The grid (our collector) is wrong |
| Truth and grid agree, reference differs | The reference has a gap; not our defect |
| All three differ | The seed list or the matching is wrong; fix the oracle first |

Without a seeded account the oracle still runs, but its report says it has no truth column and
labels every disagreement "unattributed". There is no sandbox account yet; this requirement is why
one is needed before the first live trial.

### Matching And Noise
----
RID: `req-aws-core-oracle-noise`

Status: `Proposed`

Three sources of false findings are handled by rule, not by hand:

1. **Identity.** Tools identify a resource differently. The normal form keys on `(account, region,
   cfn_type, ident)`, and the adapter for each source owns the mapping to that key. A resource that
   matches by ARN but not by `ident` is reported as an identity mismatch, which is a finding about the
   grid's natural key, not a miss.
2. **Scope.** Each adapter declares the set of `cfn_type` values it can list. A type outside that set
   is `out-of-oracle-scope`, and the report counts it so a high pass rate cannot hide a narrow oracle.
3. **Time.** Collection and the oracle run at different moments. The oracle records its own start and
   end times and the grid's last-observed time per node, and a resource created or deleted inside the
   window between the two is reported as `churn`, not as a gap. A run on a quiet seeded account has
   none.

### Report
----
RID: `req-aws-core-oracle-report`

Status: `Proposed`

The oracle writes a JSON report and a short Markdown summary. The summary leads with counts per
verdict per source, then lists every `missing-from-grid` and `grid-unread` finding with the type, the
ARN, and the ledger state of the type. Findings are stable: the same account state yields the same
report, so two runs can be diffed.

Findings feed the ledger by hand, not automatically: a confirmed collection gap becomes an issue
against `aws_core`, and a type the oracle shows is collected fine can be upgraded from
`collected-unverified` only after the live trial the ledger already requires. The oracle's pass is
evidence for that trial, not a substitute for it.

## Open Questions

1. **Steampipe Export.** What does the standalone binary output, how large is it, and does it cover
   every AWS table or one binary per table? Read its documentation before the adapter is designed.
2. **Cloud Control coverage.** How many ledger types does `ListResources` support, and which need a
   parent identifier? The answer sets how much of the inventory diff the first source can cover.
3. **Where it lives.** A directory in `aws-core-tap` outside the wheel, or its own repository. A
   separate repository keeps the "not part of the product" line clearest.
4. **Seed account.** What the seeded resource list contains, and who owns creating and tearing it
   down.
