# AWS Core Secrets Specification (v0)

## Philosophy

The `tap_cares` secrets subsystem owns the *mechanics* of secret handling —
file discovery, the in-process registry, `resolve_secret`, the
`require_secret_kind` validation harness, redaction, and string-keyed kind
dispatch — and is deliberately kind-agnostic
(`tap_cares` `req-tap-cares-secrets-consumer-kinds`).

The *shape* of a given secret kind's `data` — which fields exist, which are
required, and the JSON Schema it validates against — is owned by the consuming
plugin or collector, not by `tap_cares`. This spec is the canonical owner of
the AWS credential kind(s) consumed by `aws_core` collectors. It is the first
concrete instance of the consumer-owned-shape contract.

`aws_core` supplies its schema to the subsystem at the consumer boundary via
`require_secret_kind(secret, "aws_static_access_key", data_schema=<aws_core schema>)`;
`tap_cares` enumerates none of these fields.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-aws-core-secret-aws-static | [AWS Static Access Key Kind](#aws-static-access-key-kind) | Approved for Development | `aws_static_access_key` `data` shape + region scope; relocated from `req-tap-cares-secrets-aws-static` |
| req-aws-core-secret-aws-assumed-role | [AWS Assumed-Role Kind (cross-account)](#aws-assumed-role-kind-cross-account) | Proposed | `aws_assumed_role` `data` shape; STS AssumeRole + mandatory External ID for cross-account read-only collection; supersedes the deferral in `req-aws-core-secret-aws-static-3` |
| req-aws-core-secret-member-fanout | [Member Fan-Out Settings](#member-fan-out-settings) | Proposed | Optional `data.member_fanout` block on the static kind: the dedicated member role's name, its required External ID, an exclude list and a cap; consumed by `req-aws-collector-fanout` |

## AWS Static Access Key Kind
----
RID: `req-aws-core-secret-aws-static`

Status: `Approved for Development`

The first AWS collector credential mode is static AWS access keys. The
`aws_static_access_key` secret kind carries:

- `kind`: `aws_static_access_key`
- `data.access_key_id` — required
- `data.secret_access_key` — required
- optional `data.session_token`
- optional `data.region` — single default/fallback region
- optional `data.regions_allowed` — list of regions to scope the sweep to

`data.region` / `data.regions_allowed` are the operator's region-scoping knob.
Region scope is operationally bound to the credential set (a key is intended
for the regions it should touch), so it travels in `data` next to the
credentials rather than in descriptive `metadata`. The plural list is named
`regions_allowed` (not bare `regions`) so it is never confused with the
singular `data.region` or the superseded steampipe `metadata.target_regions`
interim shape.

Region-scope *semantics* are specified by the consuming collector in
`spec-aws-core-collector-v0.md` (`req-aws-collector-credentials` /
`req-aws-collector-regions`): a non-empty `data.regions_allowed` scopes
regional collection to exactly those regions; absent, the singular
`data.region` is the sole swept region; with neither, the collector fails the
run visibly. Global
services are collected once regardless.

`aws_core` owns the JSON Schema for this `data` shape and applies it
consumer-side via `require_secret_kind(..., data_schema=...)`
(`tap_cares` `req-tap-cares-secrets-validation`). A missing or malformed
secret fails the run visibly with a structured, redacted error
(`tap_cares` `req-tap-cares-secrets-redaction-3`); secret material is never
logged and the collector capability is never disabled by a bad secret.

Assume-role support is no longer deferred: the samsite next-iteration app runs
in a **separate AWS account**, which is the concrete collector need that lifts
the deferral. Cross-account collection is specified by
[`req-aws-core-secret-aws-assumed-role`](#aws-assumed-role-kind-cross-account)
(the `aws_assumed_role` kind). Other credential modes (e.g. keyless/ambient
base identity, web-identity/OIDC) remain backlog until a collector needs them.

#### Lineage

This requirement was relocated from `tap_cares` `req-tap-cares-secrets-aws-static`
(and its ACIDs `-1`..`-4`) when the subsystem/shape ownership boundary was
made explicit: the AWS credential *shape* belongs to `aws_core`, not the
generic secrets subsystem. The `tap_cares` requirement is now the generic
`req-tap-cares-secrets-consumer-kinds`, which links here as its reference
example.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-secret-aws-static-1 | Static Key First | Approved for Development | The first AWS collector credential mode is static access keys (`access_key_id` + `secret_access_key`, optional `session_token`). | Was `req-tap-cares-secrets-aws-static-1`. |
| req-aws-core-secret-aws-static-2 | aws_core Owns The Schema | Approved for Development | `aws_core` defines the `data` JSON Schema and validates consumer-side via `require_secret_kind(..., data_schema=...)`. | Was `req-tap-cares-secrets-aws-static-2`; built in the source-driver increment. |
| req-aws-core-secret-aws-static-3 | Assume Role Deferred | Superseded | Deferral lifted by the samsite cross-account need; assume-role is now specified by `req-aws-core-secret-aws-assumed-role`. | Was `req-tap-cares-secrets-aws-static-3`; Backlog → Superseded. |
| req-aws-core-secret-aws-static-4 | Region Scope Carried | Approved for Development | The kind carries optional `data.region` (single) and `data.regions_allowed` (list); region-scope semantics are owned by the collector spec. | Was `req-tap-cares-secrets-aws-static-4`. |
| req-aws-core-secret-aws-static-5 | Assert-On-Land | Approved for Development | The kind carries the same optional `data.expected_account_id` as the assumed-role kind; if set, the account resolved by `GetCallerIdentity` must equal it or the run fails visibly. | Mirrors `req-aws-core-secret-aws-assumed-role-4`. The enforcement was already kind-agnostic (`account_mismatch_error` reads `data` without consulting `kind`, and both call sites invoke it unconditionally); only the strict `additionalProperties: false` schema withheld the field, so an operator declaring it got a validation failure instead of a guard. Catches keys belonging to a different account than declared — which otherwise collects a real but *wrong* system and reports success. |

## AWS Assumed-Role Kind (cross-account)
----
RID: `req-aws-core-secret-aws-assumed-role`

Status: `Proposed`

The second AWS collector credential mode is **cross-account role assumption**.
It exists because the collector must reach a *running service in an AWS account
we do not own* (the samsite next-iteration app in a partner account). Handing
long-lived keys across an account boundary is the anti-pattern this mode
forecloses: instead the partner (the account owner) creates a read-only IAM
**role**, and the collector assumes it via STS to obtain **short-lived**
credentials scoped to that account.

This is the industry-standard third-party-access pattern (Datadog, Wiz, Prowler,
Steampipe all onboard this way). The three guards it composes:

1. **A dedicated collector principal** in *our* account whose only privilege is
   `sts:AssumeRole` on the partner's role ARN — so the base credential is
   near-worthless if leaked (it can mint nothing but a read-only session the
   partner controls).
2. **An External ID** — a shared secret the partner's trust policy requires via
   `sts:ExternalId`. It defeats the confused-deputy problem: only a caller who
   knows the agreed ID can assume the role, so the partner cannot be tricked
   into lending its account to another of our tenants. For cross-account /
   cross-org access it is **mandatory here**, not optional (see ACID `-2`).
3. **A least-privilege, read-only grant** — the partner attaches AWS-managed
   `SecurityAudit` (config/metadata read, no data-plane object reads), which the
   partner can inspect before accepting.

The `aws_assumed_role` secret kind carries:

- `kind`: `aws_assumed_role`
- `data.role_arn` — required; the role in the **target** account to assume
- `data.external_id` — required; the confused-deputy guard (see `-2`)
- `data.base` — required (this increment); the base identity used to *call*
  `AssumeRole`: `{ access_key_id, secret_access_key, session_token? }`. A
  keyless/ambient base (instance/task role, web-identity) is a declared future
  branch, deferred until the collector runs on AWS compute.
- optional `data.expected_account_id` — if set, the collector asserts the
  post-assume `GetCallerIdentity` account equals it and fails visibly on
  mismatch (wrong-role catch; see `-4`)
- optional `data.role_session_name` — the `RoleSessionName` stamped into the
  target's CloudTrail; defaults to a run-identifying value (see `-5`)
- optional `data.duration_seconds` — requested session lifetime
- optional `data.region` / `data.regions_allowed` — identical region-scope
  semantics to the static kind (`req-aws-core-secret-aws-static-4` /
  `req-aws-collector-regions-5`); reused, not redefined

`aws_core` owns this `data` JSON Schema and validates it consumer-side via
`require_secret_kind(secret, "aws_assumed_role", data_schema=...)` exactly as the
static kind does. A missing/malformed secret — including a missing `external_id`
— fails the run visibly with a structured, redacted error; secret material
(including `base` credentials and the external ID) is never logged.

Collector semantics live in `spec-aws-core-collector-v0.md`
(`req-aws-collector-credentials`): build a base session from `data.base` →
attach the audit ledger to it → `sts:AssumeRole(RoleArn, ExternalId,
RoleSessionName, DurationSeconds?)` → build the working session from the returned
short-lived credentials → run the existing `GetCallerIdentity` reachability
probe, now doubling as the assert-on-land check. The `AssumeRole` call is itself
captured by the run ledger (`req-aws-collector-audit-ledger`).

#### Operator handoff (the partner-side bootstrap)

Correctness of the *trust* side is ours, not the partner's: the External-ID
condition, the trust principal, and the read-only scope are security-sensitive
and easy to fumble in the console. So `aws_core` ships the grant as a
**declarative, reviewable, committed artifact** the partner merely runs — the
open-source analog of the vendor onboarding wizard:

- a canonical **CloudFormation template** (role + External-ID trust condition +
  `SecurityAudit`), launched via a console deep-link with parameters pre-filled;
  the stack **Outputs the Role ARN**, and deleting the stack is the clean
  uninstall/revoke;
- an equivalent **Terraform module** for partners already on IaC;
- a short **one-pager** carrying the minted External ID, the launch link, a
  "what am I granting?" summary, and the "send us the Role ARN" step.

**We** mint the External ID (per-partner, never partner-chosen) and hand the
partner our collector principal ARN; the partner returns the Role ARN + target
account id + region(s), which populate the `aws_assumed_role` secret.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-secret-aws-assumed-role-1 | Assume-Role Mode | Proposed | The `aws_assumed_role` kind assumes a target-account role via STS and collects with the returned short-lived credentials. | Coexists with `aws_static_access_key`; additive. |
| req-aws-core-secret-aws-assumed-role-2 | External ID Mandatory | Proposed | `data.external_id` is required for this kind; a secret lacking it fails validation and the run never calls `AssumeRole` without the confused-deputy guard. | Cheap foundational security edge; stricter than a generic optional external id. |
| req-aws-core-secret-aws-assumed-role-3 | Explicit Base Identity | Proposed | This increment requires a static `data.base` credential set to call `AssumeRole`; keyless/ambient base is a declared future branch. | Validated consumer-side; keeps the base identity legible, not implicit. |
| req-aws-core-secret-aws-assumed-role-4 | Assert-On-Land | Proposed | If `data.expected_account_id` is set, the post-assume `GetCallerIdentity` account must equal it or the run fails visibly. | Reuses the existing STS probe; catches a misconfigured/misrouted role. |
| req-aws-core-secret-aws-assumed-role-5 | Session-Name Legibility | Proposed | The `RoleSessionName` carries a run-identifying value into the target account's CloudTrail. | AI/audit legibility on the partner side; partner can trace every call to a run. |
| req-aws-core-secret-aws-assumed-role-6 | Audited Assume | Proposed | The `AssumeRole` call is captured by the per-run audit ledger. | Ledger attaches to the base session before the STS call. |
| req-aws-core-secret-aws-assumed-role-7 | Least-Privilege Grant Artifact | Proposed | The committed handoff artifacts request AWS-managed `SecurityAudit` (read-only config) and a trust policy naming a specific collector principal + the External ID; broader `ReadOnlyAccess` is opt-in, named where used. | Honest-risk: names what is deliberately granted vs. left out. |

#### Lineage

This requirement lifts the deferral recorded in
`req-aws-core-secret-aws-static-3` (Assume Role Deferred → Superseded). The
concrete collector need is the samsite next-iteration app running in a separate
AWS account.

## Member Fan-Out Settings
----
RID: `req-aws-core-secret-member-fanout`

Status: `Proposed`

The data shape behind `req-aws-collector-fanout` (`spec-aws-core-collector-v0.md`). Ruling
(George, 2026-09-30): the first GovCloud run uses static access keys for a read-only IAM user in the
GovCloud organization's **management account**. So fan-out rides the existing
`aws_static_access_key` kind as an optional block. It is not a third kind, and the base is not an
assumed role.

The `aws_static_access_key` kind gains one optional key:

- `data.member_fanout` — absent or `{"enabled": false}` means today's single-account run, unchanged.
  When `enabled` is true:
  - `member_role_name` — required. An IAM role **name** (optionally with a path), never an ARN. The
    collector builds the ARN from the run's resolved partition and each member's id, so a secret
    cannot carry a wrong-partition ARN. It names the dedicated read-only member role
    (`req-aws-collector-fanout`, ruling 2026-10-01). No default: the roles a member has by default
    (`OrganizationAccountAccessRole`, `AWSControlTowerExecution`) are administrator roles, and the
    collector never assumes one silently.
  - `external_id` — required (ruling 2026-10-01). The member role trusts only the collector's
    management-account principal and only with this External ID, consistent with the assumed-role
    kind (`req-aws-core-secret-aws-assumed-role-2`), even though base and members share one
    organization. One value serves every member, because one baseline deploys the role everywhere.
  - `exclude_account_ids` — optional list of 12-digit ids never assumed into (for example a
    break-glass account). Each one is reported as `skipped: excluded`.
  - `max_member_accounts` — required integer ≥ 1. A larger organization refuses fan-out; it never
    collects a silent prefix.
  - `role_session_name` / `duration_seconds` — optional, the same semantics as the assumed-role kind.

The base keys' own `expected_account_id` (`req-aws-core-secret-aws-static-5`) still asserts the
**management** account. Each member is asserted against its own id by the collector
(`req-aws-collector-fanout-3`), never against a value in the secret.

The committed handoff artifacts (`collectors/boto3_collector/handoff/`) are commercial-only today.
The CFN parameter pattern and the managed-policy ARN are `arn:aws:` literals (`cross-account-role.yaml:51,103`,
`cross-account-role.tf:72`, `collector-principal-policy.json:9`). Fixing them is in scope for the
fan-out step (`req-aws-collector-fanout-13`; ruling 2026-10-01). The member-role artifact is a
StackSet- or Terraform-deployable variant of the same role, deployed per account by the account
baseline (an organization StackSet or the Gruntwork account baseline). It uses `${AWS::Partition}` /
`data.aws_partition`, so it is correct in `aws-us-gov` on first use.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-secret-member-fanout-1 | Optional, Additive | Proposed | A static-key secret without `member_fanout`, or with `enabled: false`, validates and runs exactly as before. | |
| req-aws-core-secret-member-fanout-2 | Role Name, Never ARN | Proposed | `member_role_name` validates as an IAM role name with optional path; an ARN is refused at validation. | The partition comes from the run, never from the secret. |
| req-aws-core-secret-member-fanout-3 | No Default Role | Proposed | `enabled: true` without `member_role_name` fails validation; the collector never falls back to `OrganizationAccountAccessRole` or `AWSControlTowerExecution`. | Both are administrator roles. |
| req-aws-core-secret-member-fanout-4 | Cap Required | Proposed | `enabled: true` without an integer `max_member_accounts` ≥ 1 fails validation. | `req-aws-collector-fanout-10`. |
| req-aws-core-secret-member-fanout-5 | Partition-Neutral Member Artifact | Proposed | The member-role handoff artifact uses the deploying partition (`${AWS::Partition}` / `data.aws_partition`) for every ARN, and deploys in `aws-us-gov` without edits. | `req-aws-collector-fanout-13`; the same templates unified-systems-com/aws-core-tap#51 names. |
| req-aws-core-secret-member-fanout-6 | Redacted | Proposed | `external_id` is never logged, matching the assumed-role kind. | |
| req-aws-core-secret-member-fanout-7 | External ID Required | Proposed | `enabled: true` without a non-empty `external_id` fails validation, and the collector never calls `AssumeRole` into a member without it. | Ruling 2026-10-01; mirrors `req-aws-core-secret-aws-assumed-role-2`. |
