# AWS Core Availability Specification

## Philosophy

Whether an AWS service, an operation or a resource type is really available in a partition and region has no single
authoritative, machine-readable answer. The coverage ledger's availability data comes from botocore's partition
tables, which say whether an endpoint hostname can be built, not whether the service is deployed; the AWS
documentation says more but only as prose and HTML; AWS publishes a few machine-readable lists that cover parts of
the question. The first live run against a GovCloud account showed the cost of guessing: of 54 types that turned out
not to work there, the ledger had marked 53 available in both partitions.

This specification describes a record of availability that is built from several independent sources, keeps each
source's evidence separate and dated, and derives its verdict by rule. The aim is a list we can defend, reproduce and
publish: a dataset of what is live in a partition and region, with the method and raw evidence attached, so that
others can check it and correct us. It starts with one partition and region because that is the only place we have a
credential; it is designed to grow by adding evidence, not by editing verdicts.

## Provenance

- **Read** 2026-11-01: the botocore `endpoints.json` bundled with the AWS CLI v2.37.9. The `aws-us-gov` partition
  lists 192 services; `datazone`, `internetmonitor`, `kendra-ranking` and `kinesisvideo` are listed, `ecr-public` and
  `cloudwatch-omni` are not. botocore's endpoint rule sets contain no availability data for those services.
- **Ran** 2026-11-01: a read-only call-path smoke over 898 manifest-driven types in `us-gov-west-1`
  (`tools/validate/runs/wave0-2026-11-01.json`, PR #161): 683 types had a working call path (rows or none), 54 were unsupported
  (endpoint missing, unknown operation, invalid action, unsupported operation), 161 other.
- **Ran** 2026-11-01: DNS lookups of 8 public endpoint hostnames in `us-gov-west-1`. `datazone`, `ecr-public`,
  `internetmonitor`, `kendra-ranking` and `kinesisvideo` have no record; `ec2`, `logs` and `inspector` resolve. The
  `inspector` endpoint resolves yet connections time out, so a record is necessary, not sufficient. A research agent
  ran 32 lookups with the same pattern.
- **Ran** 2026-11-01: the CloudFormation resource specification for `us-gov-west-1` (a public file,
  `cfn-resource-specifications-us-gov-west-1-prod`, version 270.0.0, 1,030 resource types) against the wave 0
  outcomes. Of the types in the specification with a classifiable outcome, 564 of 567 worked (99.5%); the three that
  did not were two `KinesisVideo` types (no endpoint) and `SageMaker::Workteam` (unknown operation). Absence is weak
  evidence: 117 types the specification lacks had a working call path and 51 did not.
- **Read, not fetched or run:** SSM `/aws/service/global-infrastructure/` (documented to include GovCloud regions;
  needs credentials in a commercial region), the undocumented regional-services JSON behind the AWS Regional Services
  List, Prowler's `aws_regions_by_service.json` (records negative availability per partition; method unknown), the
  General Reference endpoint tables (HTML), the FedRAMP services-in-scope page (a compliance assertion, not
  availability), AWS Config's supported resource types by region (HTML).
- **Not checked:** the Go and JavaScript SDK endpoint data, Steampipe, CloudQuery, Cartography, Cloud Custodian.
- **Designed, not run:** every requirement below is Proposed or Backlog.

Tracked by `unified-systems-com/aws-core-tap#107`. Related: `spec-aws-core-live-validation.md` (wave 0 is the first
empirical layer) and `spec-aws-core-coverage-ledger.md` (the consumer).

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Layered       | Each source of evidence is stored apart, with its method and date; none is overwritten by another |
| 2. | Derived       | A verdict is computed by rule from the evidence, never edited by hand |
| 3. | Reproducible  | Anyone can re-run the probes and the derivation and get the same record from the same evidence |
| 4. | Honest        | A thing never probed is `declared-only` or `unknown`, never offered |
| 5. | Publishable   | The dataset carries its method and raw evidence, contains no account identifiers, and can stand alone |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-aws-core-availability-record | [Record](#record) | Proposed | One record per partition, region, service and operation, with layers and a derived verdict |
| req-aws-core-availability-layers | [Evidence Layers](#evidence-layers) | Proposed | Declared, derived and empirical, each stored with source, method and date |
| req-aws-core-availability-verdicts | [Verdicts](#verdicts) | Proposed | The values, and the error signatures that earn each |
| req-aws-core-availability-combine | [Combining Evidence](#combining-evidence) | Proposed | Rules for which layer outranks which; disagreement is recorded |
| req-aws-core-availability-probe | [Probe](#probe) | Proposed | DNS and a credentialed read call per operation, with raw outcomes kept |
| req-aws-core-availability-evidence | [Evidence Store](#evidence-store) | Proposed | Raw outputs committed, dated, tool versions pinned, no account identifiers |
| req-aws-core-availability-consumers | [Consumers](#consumers) | Proposed | How the ledger and the collector use the verdict, and what they must not do |
| req-aws-core-availability-publish | [Publication](#publication) | Proposed | The standalone dataset: schema, method, evidence, changelog |
| req-aws-core-availability-cfn-verifier | [CloudFormation Verifier](#cloudformation-verifier) | Backlog | Check the ledger and the collector against AWS's own per-region CloudFormation specification |

### Record
----
RID: `req-aws-core-availability-record`

Status: `Proposed`

A record is keyed by `(partition, region, service, operation)`; `operation` is empty for a service-level record and
`region` is `global` for a global service. It holds:

| Field | Meaning |
| --- | --- |
| `layers` | A list of evidence entries (see Evidence Layers), each independent |
| `verdict` | The derived value (see Verdicts), with the rule that produced it |
| `disagreements` | Layers that contradict the verdict, kept, not resolved silently |
| `first_seen`, `last_checked` | The dates of the earliest and latest evidence |

The verdict can be re-derived from `layers` alone. Service-level and operation-level verdicts are separate records,
because a service can be reachable while an operation of it does not exist.

### Evidence Layers
----
RID: `req-aws-core-availability-layers`

Status: `Proposed`

Each layer entry is `{source, kind, value, fetched_at, source_version_or_digest, method}`.

| Kind | Sources | What it says |
| --- | --- | --- |
| Declared | botocore endpoint data and its version; the AWS General Reference endpoint tables; SSM `/aws/service/global-infrastructure/`; the regional-services JSON; Prowler's file | Someone asserts the service exists in the region |
| Derived | The per-region CloudFormation resource specification; AWS Config and Cloud Control supported types | Availability inferred from what another AWS system deploys |
| Empirical | DNS resolution of the endpoint hostname; the outcome of a credentialed read call with the raw error code, exception class and HTTP status | What happened when we asked |

A source that cannot be fetched is recorded as unavailable with the reason; it is never silently dropped.

### Verdicts
----
RID: `req-aws-core-availability-verdicts`

Status: `Proposed`

| Verdict | Meaning |
| --- | --- |
| `offered` | A credentialed call to the operation succeeded, or failed in a way that proves the operation exists |
| `access-denied-present` | The call was refused for permission; the operation exists (a positive signal) |
| `endpoint-absent` | The endpoint hostname does not resolve, or connections to it fail |
| `operation-absent` | The endpoint answers but names the operation unknown (`UnknownOperationException`, `InvalidAction`, `UnsupportedOperation`, HTTP 404 "unknown operation") |
| `service-unsupported-in-region` | The service answers that it does not support the region or partition ("not supported in this region", "not supported in GovCloud") |
| `account-not-enabled` | The service answers that the account has not opted in, subscribed or activated the feature (`OptInRequired`, `SubscriptionRequiredException`, `UninitializedAccountException`, "not enabled for this account") |
| `unreachable-unknown` | Connect or read timed out; neither present nor absent |
| `declared-only` | Declared or derived evidence exists and no empirical evidence |
| `unknown` | No evidence |

The error signatures above were observed in wave 0; each new signature is added with the run that produced it.
Service, operation and account level stay separate.

### Combining Evidence
----
RID: `req-aws-core-availability-combine`

Status: `Proposed`

1. A positive empirical result outranks any declared or derived layer.
2. A negative DNS result outranks declared data for the service-level verdict (botocore listed four services that
   have no endpoint). A resolving name proves nothing; `inspector` resolves and times out.
3. A derived layer's presence is positive evidence (the GovCloud CloudFormation specification was right 99.5% of the
   time when it listed a type). Its absence is not negative evidence: it lacked 117 types whose call path worked.
4. Where layers disagree, the stronger layer decides and the weaker is kept under `disagreements`.
5. Without empirical evidence, the verdict is `declared-only`, never `offered`.

### Probe
----
RID: `req-aws-core-availability-probe`

Status: `Proposed`

The probe has two parts. **DNS:** resolve each service's regional endpoint hostname (the standard, FIPS and dual-stack
forms) with the system resolver and record the answer or its absence. **Call:** one credentialed read call per
operation under the least-privilege read-only identity, with a before-call guard refusing any non-read operation,
recording the raw error code, exception class and HTTP status. The wave 0 smoke (`tools/validate`) is this part's first
implementation: its run record is an empirical layer. The probe never records resource content and removes any account
identifier before storing.

### Evidence Store
----
RID: `req-aws-core-availability-evidence`

Status: `Proposed`

Raw outputs of each fetch and probe are committed with the date, the tool and library versions (botocore and the AWS CLI
version, the resolver, the script's commit) and a digest. Account numbers, request ids and resource names are removed.
A fetch of an AWS-hosted source stores the file's digest and the fields used, not necessarily the whole file, when the
file is large or not freely redistributable.

### Consumers
----
RID: `req-aws-core-availability-consumers`

Status: `Proposed`

- The **coverage ledger** carries the observed verdict beside its botocore-derived tier, with the date, so a
  contradiction is visible; it does not replace the tier.
- The **collector** classifies a failing call into the matching verdict as a named, recorded outcome (not a crash) and
  never skips a read because of declared or derived data alone. A skip is justified only by empirical evidence.
- A **validation wave** treats a type whose service-level verdict is `endpoint-absent` or `operation-absent` as
  call-path-only and does not seed it.

### Publication
----
RID: `req-aws-core-availability-publish`

Status: `Proposed`

A standalone dataset (a directory or its own repository) with `data/<partition>/<region>.json` holding the records, a
JSON schema, a method document describing every probe and rule, the raw evidence by date, and a changelog of verdicts
that changed between releases. Releases are dated and tagged. It is licensed so others can reuse it and contains no
identifier of any account. Whether it lives here or apart is an open question.

### CloudFormation Verifier
----
RID: `req-aws-core-availability-cfn-verifier`

Status: `Backlog`

Build a verifier against AWS's own CloudFormation data, because it comes from AWS and is the most authoritative
machine-readable description of what is deployable: (1) for each partition and region, fetch the per-region resource
specification and check that every ledger type we claim collected-or-modeled is present, reporting any that is not as
a lead rather than a verdict (absence is weak evidence, see Combining Evidence); (2) compare each type's properties in
that specification with the fields we hold, flagging read-only properties we do not collect and properties we name that
the specification lacks; (3) record the specification version and digest with each run so a change in AWS's data shows
as a change in the report. Not designed beyond this; it reuses the CloudFormation schema bundle the ledger already reads.

## Open Questions

1. **Scope of the first dataset.** One region (`us-gov-west-1`) is all we can probe. `us-gov-east-1` is not known to be
   enabled for the account; commercial and China regions need credentials we do not hold.
2. **SSM and the regional-services JSON.** Both need fetching and comparing with the empirical layer before they are
   trusted as declared sources.
3. **Where it lives.** In this repository under `tools/`, or its own repository with its own release cadence.
4. **Probe cost and cadence.** One pass is about 1,300 read calls and 18 minutes; how often to re-run, and whether it
   runs in CI.
5. **Operation-level probing without side effects.** Calling every operation with deliberately invalid input would
   separate "operation exists" from "operation is permitted" more cheaply; whether that is safe per service is
   unchecked.
