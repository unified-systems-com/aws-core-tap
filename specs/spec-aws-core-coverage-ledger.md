# AWS Core Coverage Ledger Specification

## Philosophy

`aws_core` models and collects a growing slice of AWS, and today nobody can say how much of the
whole is covered, because "the whole" has no list. This specification gives it one. A **coverage
ledger** is a generated, committed file that names every AWS service and resource type in scope and
gives each exactly one state: modeled and collected, modeled only, not yet classified, or excluded
with a written reason. The aim is then falsifiable: the work is done when no in-scope row is
unclassified.

The ledger's denominator comes from machine-readable AWS sources (botocore's bundled service models,
and the CloudFormation resource type schemas), never from a person's recollection of what AWS offers.
Classification (is this thing a node, an attribute, an edge, or nothing) stays a reviewed judgement,
using the heuristic already in the README: anything with a stable ARN is a candidate node unless it is
only an embedded configuration detail, a transient execution artifact, a metric sample or a policy
statement fragment.

Tags are treated as a first-class part of every row, not an afterthought. AWS applies tags in a dozen
different ways, and a type may be recorded as untaggable only when that is confirmed as fact from a
named authoritative source.

Tracked by `unified-systems-com/aws-core-tap#107`. Depends on `unified-systems-com/tap#1128` for
safe handling of a failed tag read.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Falsifiable   | "Full AWS coverage" becomes a ledger with a countable number of unclassified rows |
| 2. | Derived       | The denominator is generated from AWS's own machine-readable models, not hand-listed |
| 3. | Tag-complete  | Every collected type has its tags read, or a confirmed, cited reason it has none |
| 4. | Honest        | A type built without a live trial is marked unverified until one has run |
| 5. | Current       | A scheduled job reports AWS growth against the committed ledger |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-aws-core-ledger-denominator | [Denominator](#denominator) | Proposed | Which sources define the rows |
| req-aws-core-ledger-scope | [Scope](#scope) | Proposed | Commercial and GovCloud services, security first |
| req-aws-core-ledger-states | [Row States](#row-states) | Proposed | The states a row may be in and what each requires |
| req-aws-core-ledger-tags | [Tag Evidence](#tag-evidence) | Proposed | When tags may be dropped, and how they are found |
| req-aws-core-ledger-tag-shapes | [Tag Shapes](#tag-shapes) | Proposed | Every wire shape of tags is handled, not just three |
| req-aws-core-ledger-tranches | [Tranches](#tranches) | Proposed | Build order and the loop each tranche follows |
| req-aws-core-ledger-shape-conformance | [Shape Conformance](#shape-conformance) | Proposed | Boto-only verification before a live account exists |
| req-aws-core-ledger-drift | [Drift Detection](#drift-detection) | Proposed | A scheduled job that reports AWS growth |

### Denominator
----
RID: `req-aws-core-ledger-denominator`

Status: `Proposed`

The ledger's service list is the set of services in the botocore data bundled with the pinned
`boto3`. As of botocore 1.43.121 that is 435 service models, of which 397 have `List*` or `Describe*`
operations. A service with no list or describe operation cannot enumerate resources and is recorded as
`excluded` with that reason, not omitted.

Resource types within a service are taken from the CloudFormation resource type schemas where the
service has them (each carries a primary identifier and a `tagging` block), and otherwise from the
service's own list and describe operations. A row records which source named it.

The generator is deterministic: the same botocore version and the same schema snapshot produce the
same ledger byte for byte, so a diff means AWS changed or the pin moved.

### Scope
----
RID: `req-aws-core-ledger-scope`

Status: `Proposed`

In scope are services offered in both the commercial (`aws`) and GovCloud (`aws-us-gov`) partitions,
ordered by security and compliance relevance first (ruled 2026-10-28, maintainer). A service offered in
only one partition is recorded with its partition availability and not built until the in-scope set is
classified, or until the maintainer pulls it forward.

Partition availability is read from botocore's bundled endpoint data and recorded in the row;
`partition.py`'s `_UNAVAILABLE_SERVICES` is updated in the same change as any collected service that
GovCloud lacks, so the run records a named skip instead of a connection failure.

### Row States
----
RID: `req-aws-core-ledger-states`

Status: `Proposed`

Each row is in exactly one state:

| State | Meaning | Required to be in it |
| --- | --- | --- |
| `unclassified` | Named by the denominator, not yet judged | Nothing; the aim is zero of these in scope |
| `excluded` | Judged not to be a node | A written reason: attribute of a named node, transient, metric, policy fragment, or no list operation |
| `modeled` | A model exists, no manifest entry | The model name |
| `collected-unverified` | A manifest entry exists, built from botocore only | The entry, the shape-conformance test passing, and the tag evidence below |
| `collected-verified` | A live trial has run | The trial run recorded under `add-aws-type` step 5 |

Until a sandbox account exists (deferred 2026-10-28), nothing can reach `collected-verified`. That is
deliberate: the ledger must not claim a verification that did not happen.

### Tag Evidence
----
RID: `req-aws-core-ledger-tags`

Status: `Proposed`

Every row that is `modeled` or later records a `tags` treatment: `inline` (tags arrive in the
list or describe output), `side-call` (a separate operation reads them), `rgta` (the Resource Groups
Tagging API sweep), `organizations` (the Organizations lane), or `none`.

A row may be `none` only when untaggability is confirmed as fact. Confirmation requires a citation
recorded in the row from at least one of: the CloudFormation resource schema's `tagging.taggable`
being `false`, the service's botocore model having no tag operation and no tag member on the
resource's shapes, or the service's own documentation stating the resource cannot be tagged. When the
sources disagree, the row stays unresolved and the disagreement is written down.

"I could not find the tags" is not `none`. It is the state `tags: not-found`, and a row in it cannot
be `collected-unverified` or later. The order of search, stopping at the first confirmed answer:

1. The CloudFormation resource schema: `tagging.taggable` and `tagProperty` name whether and where.
2. The botocore model: shapes with a tag-list or tag-map member on the describe output, and any
   operation whose input takes the resource's ARN and whose output carries tags. Operation names are
   not evidence; SQS, IAM, Secrets Manager, EMR, RAM, Lightsail and Data Pipeline all have a tag-write
   operation without a read operation matching the usual names.
3. The Resource Groups Tagging API supported-services list.
4. The service's own documentation page on tagging that resource, found by search.

A tag read that fails is never recorded as an empty tag set. Today a failed read cannot be expressed
safely: the GRIFT importer applies every existing node as a replace, which resets an omitted field to
its default (`aws-core-tap#60`). The maintainer ruled on 2026-10-28 that core's upsert semantics change
(`unified-systems-com/tap#1128`: an absent field is left alone, a present field replaces whole, a null on
a non-nullable field resets to the model default), and that **no new type is collected until that ships**.
Once it does, a failed or unauthorized tag read omits `tags` from the node; a successful read of an
untagged resource sends `{}`. Models, ledger rows and manifest drafts proceed in the meantime; only
`collected-unverified` is held.

AWS-reserved `aws:*` tag keys are kept (`aws-core-tap#69`).

### Tag Shapes
----
RID: `req-aws-core-ledger-tag-shapes`

Status: `Proposed`

`tags.py` handles `list_kv`, `list_kv_lower` and `map`, and names the CloudTrail nested and WAFv2
wrapped shapes as out of scope. With tags critical, that fence is lifted: the normalizer enum is
extended to cover every shape the survey finds, each with a fixture taken from the service's own
botocore output shape, and an unrecognized shape fails the manifest load rather than yielding `{}`.
The survey of shapes is a step of the first tranche, run over all 435 service models.

### Tranches
----
RID: `req-aws-core-ledger-tranches`

Status: `Proposed`

Work proceeds in tranches of one service group each, in this order, which the maintainer may
reorder:

0. Ledger generator, tag-shape survey, and the classification of all in-scope rows.
1. Identity, logging, audit and encryption: remaining IAM, Access Analyzer, CloudTrail, Config,
   KMS, Secrets Manager, ACM and Private CA, Identity Center, Organizations completion.
2. Security services: GuardDuty, Security Hub, Inspector, Macie, Detective, WAF, Shield, Firewall
   Manager, Network Firewall, Security Lake, Audit Manager.
3. Network: the rest of the VPC family, load balancers and target groups, transit gateways, Direct
   Connect, Route 53 Resolver, VPC Lattice (folds in `aws-core-tap#64` and `#74`).
4. Compute and containers: EC2 remainder (volumes, images, snapshots, launch templates, scaling),
   EKS, ECR, Lambda remainder, Batch (folds in `#95`).
5. Data: RDS, ElastiCache, OpenSearch, Redshift, EFS, FSx, Backup, DynamoDB remainder.
6. Integration: SNS, SQS remainder, EventBridge remainder, Step Functions, API Gateway v1, AppSync,
   MQ, MSK, Kinesis, Firehose.
7. Developer tools, analytics and machine learning: CodePipeline, CodeBuild (`#96`), SageMaker,
   Bedrock, Glue, Athena, Lake Formation, EMR.
8. The long tail, from the ledger's remaining `unclassified` rows.

No tranche marks a row `collected-unverified` before `unified-systems-com/tap#1128` ships (see
[Tag Evidence](#tag-evidence)).

Each tranche follows one loop per resource type: classify; establish tag evidence; sensitivity review
and the bulk persistence default; model; manifest entry; edges; shape-conformance and unit tests;
ledger row updated; spec rows updated. One pull request per service group, not per tranche.

The sensitivity default for bulk work (ruled 2026-10-28, maintainer): store `configuration` only
after review finds nothing sensitive, never where a credential location exists, otherwise store
nothing. The three stop conditions in the `add-aws-type` skill still apply to anything outside that
default, such as a request to store a response that has a credential location.

### Shape Conformance
----
RID: `req-aws-core-ledger-shape-conformance`

Status: `Proposed`

Without a live account, every collected entry is tested against botocore's own output shapes: each
jsonpath in `fields`, `natural_key`, `edges`, the tag lane and `sensitivity` must resolve to a member
that exists in the shape of the operation it reads, and a response synthesized from the shape must
run through the engine to a batch that validates against the model's create schema. This extends
`test_boto3_collector_sensitivity.py`'s existing path check to the whole entry.

This catches a wrong path, a missing model field (the v0.4.0 failure), and a mistyped tag lane. It
cannot catch behaviour the shape does not state: absent versus null fields, pagination, denied calls,
and eventual consistency. Those are what the live trial is for, and why the ledger separates
`collected-unverified` from `collected-verified`.

### Drift Detection
----
RID: `req-aws-core-ledger-drift`

Status: `Proposed`

A scheduled workflow regenerates the ledger against the newest botocore and CloudFormation schema
data and, when the result differs from the committed ledger, opens an issue listing new services, new
resource types, new fields on modeled types, and newly taggable types. It detects and reports only;
it never edits a model or a manifest, so a new AWS service never reaches the grid unreviewed.

The botocore pin moves through the existing Renovate update; the drift job runs against that PR so a
bump that adds services reports them before merge. This supersedes the "nightly refresh" placeholder
`req-aws-catalog-future-ci` for the service surface; regions and availability zones stay with the
catalog skill.
