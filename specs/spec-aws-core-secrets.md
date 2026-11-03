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
| req-aws-core-secret-selection | [Collection Selection Settings](#collection-selection-settings) | Proposed | Optional `data.include_types`, `data.exclude_types` and `data.accounts_allowed` on both kinds: which types and which accounts a run collects; consumed by `req-aws-collector-selection` |

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
  - `member_role_name` — required. A plain IAM role **name**, matching `^[A-Za-z0-9_+=,.@-]{1,64}$`, the ASCII set IAM documents
    for role names. The committed CloudFormation template uses `^[\w+=,.@-]{1,64}$`
    (`cross-account-role.yaml:70`); `\w` matches non-ASCII letters in Python's regex engine, which
    the repository's JSON Schema validation uses, so the template, the secret schema and the tests
    all move to the explicit ASCII class, never an ARN and never a path. The member role is deployed at the
    root path `/`, so the ARN the collector builds, `…:role/<member_role_name>`, is the role's real
    ARN. A role under a non-root path is not supported here. Supporting one needs a separate
    `member_role_path` field and template parameter, and is Future. The
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
    break-glass account). Each one is reported as `skipped: excluded`. This is a scope control,
    not a security boundary: the base credential's AssumeRole grant (`req-aws-collector-fanout-19`)
    still names every account. An account that must be unreachable is kept out of the member-role
    deployment (the baseline does not create the role there), and where the operator wants a
    belt-and-braces guard the caller policy adds an explicit `Deny sts:AssumeRole` on each excluded
    account's member-role ARN; the handoff template generates that deny from this list.
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
StackSet- or Terraform-deployable role, deployed per account by the account baseline (an
organization StackSet or the Gruntwork account baseline). Unlike the existing cross-account role, it
attaches no AWS-managed policy: its only permissions are the repo-owned, generated
`member-read-policy.json` (`req-aws-collector-fanout-17`). It uses `${AWS::Partition}` /
`data.aws_partition`, so it is correct in `aws-us-gov` on first use.

### Base credential blast radius

**The risk.** Fan-out turns one long-lived access key, for a read-only IAM user in the management
account, into read access to every member account: whoever holds the key can assume the member
role in each of them. The role is read-only, but it reads configuration across the whole
organization. So one leaked key exposes the organization's full configuration, not one
account's. Static keys do not expire on their own, and the 2026-09-30 ruling chose them for the
first GovCloud run.

**Already in place.** The member role trusts only the collector's one management-account principal,
and only with the External ID (`req-aws-collector-fanout-12`, `-7` below).

**Open decision (pending maintainer, Q118).** This block is not normative. Nothing in it is a
requirement or an acceptance criterion until it is ruled. A ruling turns the chosen items into
criteria, with their secret and template inputs defined. The candidates are:

- **Enforced key rotation:** a declared maximum key age, checked by `self_test` against the key's
  `CreateDate` (`iam:ListAccessKeys` on the collector's own user), failing past the limit. Needs a
  new secret field for the maximum age.
- **A network condition on the member-role trust:** `aws:SourceIp` or `aws:SourceVpc` limiting
  `sts:AssumeRole` to where the collector runs. Needs a template parameter for the range or VPC.
- **Short-lived credentials, as a target state:** replace the static key with IAM Roles Anywhere or
  OIDC / workload-identity federation, so no long-lived secret exists to leak. The first fan-out
  implementation stays on `aws_static_access_key` (ruling 2026-09-30). This is a direction for a
  later credential kind, not a requirement on this one.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-secret-member-fanout-1 | Optional, Additive | Proposed | A static-key secret without `member_fanout`, or with `enabled: false`, validates and runs exactly as before. | |
| req-aws-core-secret-member-fanout-2 | Role Name, Never ARN | Proposed | `member_role_name` validates against `^[A-Za-z0-9_+=,.@-]{1,64}$` (ASCII only; never `\w`): a plain role name, so a value containing `/` (a path) or an ARN is refused at validation; every handoff variant deploys the member role at path `/` and validates its role-name input with the same pattern; a test feeds a non-ASCII letter (for example `é`) and asserts the secret schema, every template pattern and the collector all refuse it. | The partition comes from the run, never from the secret. |
| req-aws-core-secret-member-fanout-3 | No Default Role | Proposed | `enabled: true` without `member_role_name` fails validation; the collector never falls back to `OrganizationAccountAccessRole` or `AWSControlTowerExecution`. | Both are administrator roles. |
| req-aws-core-secret-member-fanout-4 | Cap Required | Proposed | `enabled: true` without an integer `max_member_accounts` ≥ 1 fails validation. | `req-aws-collector-fanout-10`. |
| req-aws-core-secret-member-fanout-5 | Partition-Neutral Member Artifact | Proposed | The member-role handoff artifact uses the deploying partition (`${AWS::Partition}` / `data.aws_partition`) for every ARN, deploys in `aws-us-gov` without edits, and attaches only the repo-owned `member-read-policy.json`, never an AWS-managed policy. | `req-aws-collector-fanout-13`, `-17`; the same templates unified-systems-com/aws-core-tap#51 names. |
| req-aws-core-secret-member-fanout-6 | Redacted | Proposed | `external_id` is never logged, matching the assumed-role kind. | |
| req-aws-core-secret-member-fanout-7 | External ID Required | Proposed | `enabled: true` without a non-empty `external_id` fails validation, and the collector never calls `AssumeRole` into a member without it. | Ruling 2026-10-01; mirrors `req-aws-core-secret-aws-assumed-role-2`. |

## Collection Selection Settings
----
RID: `req-aws-core-secret-selection`

Status: `Proposed`

Requested by George on 2026-11-03 in conversation, for field testing: a run must be narrowable to chosen
types and chosen accounts, and the collector has no configuration of its own to hold that. Until it does, the
selection rides the credential's `data` as optional keys, beside `regions_allowed`, which is scope already held
there. Design only: nothing in this section is built or run, and it has not been ruled as normative.

Both kinds (`aws_static_access_key`, `aws_assumed_role`) gain four optional keys, defined once as a shared
schema fragment as the region scope is (`_REGION_SCOPE_PROPS`), so the two schemas cannot drift:

- `data.include_types` — non-empty array of type patterns. Absent means every type.
- `data.exclude_types` — non-empty array of type patterns. Absent means none.
- `data.accounts_allowed` — non-empty array of account references: the accounts the run **collects from**. Absent means every account the run can reach. It is a collection scope, not a disclosure control: a fan-out run still reads the organization listing and writes its tree (`req-aws-collector-selection`, open questions).
- `data.retire_within_selection` — boolean, default `false`. Refused when `true` until core honours it; see
  `req-aws-collector-selection-12` and `-13`. It permits a selected run to state its completeness for what it read
  (so that what it read can become a retirement candidate). It retires nothing by itself.

**Type pattern.** `<service>:<entity>`, both halves required, matching `^[a-z0-9*?-]+:[a-z0-9_*?]+$`, with `*`
and `?` as the only glob characters, allowed in either half (no character classes). `<service>` is the manifest entry's `service`
(`ec2`, `eks`, `elbv2`, `sso-admin`: the botocore service name, which is not always the IAM prefix, for example
`elbv2` against `elasticloadbalancing`). `<entity>` is the entry's `entity_type` with the `aws_core__aws_` prefix
removed (`ec2:vpc`, `eks:eks_cluster`). `ec2:*` selects every EC2 entry, `*:*_policy` every entry whose entity
ends in `_policy`, `*:*` everything. Matching is case-sensitive.

**Account reference.** Either a 12-digit account id, or an ARN. An ARN names an account by its account field
(`arn:<partition>:iam::<account>:role/x`), except an Organizations account ARN
(`arn:<partition>:organizations::<management account>:account/<org id>/<account>`), which names the account in
its last segment. An ARN is refused at validation when it contains a wildcard, has an empty account field (an
S3 bucket ARN), or carries a partition other than the one the run's regions resolve to. Every reference is
normalised to a 12-digit id, de-duplicated and sorted before use.

#### Transition

Non-normative. These keys describe scope, not credentials, and sit in the secret only because the collector has
nowhere else to read them. A secret is read once at start-up (restart to rotate), so changing a selection means
restarting the worker, and it cannot be inspected by the operators who would want to audit it; the collector
therefore echoes the effective selection in every run (`req-aws-collector-selection-9`). When the collector gains
its own configuration, these four names and their meanings move there unchanged.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-secret-selection-1 | Optional, Additive | Proposed | A secret without any of the four keys validates and runs exactly as before. | |
| req-aws-core-secret-selection-2 | Shared Fragment, Both Kinds | Proposed | Both kinds accept the same four keys from one shared fragment, and the strict `additionalProperties: false` schemas still refuse any other key; a test builds both schemas and asserts the fragment is the same object. | The region-scope precedent. |
| req-aws-core-secret-selection-3 | Pattern Grammar | Proposed | A type pattern that does not match the grammar is refused at validation; an empty `include_types`, `exclude_types` or `accounts_allowed` array is refused. A test feeds a missing colon, an uppercase letter, a character class and an empty array, and asserts `*:*`, `*:*_policy`, `e*:vpc` and `ec2:vpc` all validate. | A typo must fail where the operator can see it. |
| req-aws-core-secret-selection-4 | Account Forms | Proposed | An id of 12 digits and an ARN naming an account validate and normalise to the same id; an ARN with a wildcard, an empty account field or another partition is refused; duplicates collapse. | A test covers an IAM role ARN, an Organizations account ARN and an S3 ARN. |
| req-aws-core-secret-selection-5 | No Contradiction With The Assertion | Proposed | When `expected_account_id` is also set, it must be in the normalised `accounts_allowed`, or validation refuses the secret. | Two statements about the same scope that disagree are an error, not a precedence rule. |
| req-aws-core-secret-selection-6 | Not Logged As Credential | Proposed | The four keys are scope, not secret material: they are echoed in the run record (`req-aws-collector-selection-9`). The credential values beside them stay redacted as before. | |
| req-aws-core-secret-selection-7 | Retire Flag | Proposed | `retire_within_selection` is a boolean; absent or `false` is the default. `true` is refused at validation until core honours it (`req-aws-collector-selection-13`), whether or not a narrowing key is set, so there is one rule and no case where it is accepted and ignored. A test asserts a non-boolean is refused and `true` is refused with and without a narrowing key. | Names what it does: it is not `retire`. Authority, budget and a falsifier are still required (`spec-grid-reconcile.md`). |
