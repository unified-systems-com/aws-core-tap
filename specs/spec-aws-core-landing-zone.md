# AWS Core Landing-Zone Governance Specification

## Philosophy

A landing zone is the set of AWS controls that decide who can reach which account and what is
watching each one: Control Tower and its controls, IAM Identity Center's permission sets and
assignments, and the per-account security services (Config, GuardDuty, Security Hub, Access
Analyzer, account-level encryption and public-access defaults). A Gruntwork landing zone is AWS
Control Tower with Gruntwork baselines layered on ([AF-LZ](https://docs.gruntwork.io/2.0/docs/accountfactory/prerequisites/awslandingzone)). aws_core models none of
it today, except an Identity Center instance it never collects (no manifest entry or custom function calls `sso-admin`; a grep of `collectors/` for `controltower` is empty).

This spec adds that governance surface as collected, retire-able grid types. It adds **no tag
vocabulary and touches no dimension** (ruling 2026-09-30). Every type here carries the
canonical `tags` field and declares its lane under `req-aws-collector-tags`
(`spec-aws-core-collector-v0.md`), or declares that AWS cannot tag it.

It is the landing-zone epic's step 5. It depends on `req-aws-collector-fanout` (step 2) to reach member
accounts, and on `req-aws-core-organizations-completeness` (step 4) for the delegated-administrator
facts the security services point at. Method: AWS API shapes were **read** from botocore 1.43.104's
service models, which are offline data. GovCloud availability is **web**, cited per row. Nothing here was observed against a live account.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Governed | Control Tower's landing zone, enabled controls and enabled baselines are on the grid, attached to the OUs and accounts they govern |
| 2. | Reachable | Who can reach which account with which permission set is a graph query: Identity Center permission sets, groups and account assignments |
| 3. | Watched | Which security services are on, per account and region, is a collected fact, not an assumption |
| 4. | Partition-honest | A service AWS does not offer in a partition is recorded as such, never collected as empty |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-aws-landing-zone-availability | [GovCloud Availability](#govcloud-availability) | Proposed | Per-service GovCloud availability as data; an unavailable service is `SERVICE_NOT_AVAILABLE_IN_PARTITION`, never an empty listing; Macie is not modelled |
| req-aws-landing-zone-control-tower | [Control Tower](#control-tower) | Proposed | Landing zone, enabled controls, enabled baselines; targets as reference edges; contained by the landing zone |
| req-aws-landing-zone-identity-center | [Identity Center Access](#identity-center-access) | Proposed | Collect the instance; permission sets, groups and account assignments; users only as principal ids |
| req-aws-landing-zone-security-services | [Security Services](#security-services) | Proposed | Config recorder, delivery channel and aggregator, GuardDuty detector, Security Hub hub, Access Analyzer analyzer per account × region; EBS default encryption and S3 account public-access block as typed fields |
| req-aws-landing-zone-nongoals | [Non-Goals](#non-goals) | Proposed | Account vending, Macie, Control Tower Account Factory, AFT, Config rules and conformance packs, findings |

### GovCloud Availability
----
RID: `req-aws-landing-zone-availability`

Status: `Proposed`

#### Implementation

The collector already skips a service its partition does not offer, by name
(`collectors/boto3_collector/partition.py:101-108`, `collector.py:413-427`). Every service this spec
adds joins that table with its evidence:

| Service | GovCloud (US) | Evidence | Collected here |
| --- | --- | --- | --- |
| Control Tower | Both regions. Account Factory cannot create accounts; AFT closed to new customers; RCP controls unavailable; six controls including the landing-zone region deny have no effect; the baseline APIs' GovCloud status is **not verified** (excluded in Feb 2024, not re-checked) | web, [C-GCCT](https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-controltower.html), [C-2024](https://docs.aws.amazon.com/controltower/latest/userguide/2024-all.html) | yes; an enabled-baseline listing that fails in GovCloud is recorded as not authorized or failed, never empty |
| IAM Identity Center | Both regions, no multi-region | web, https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-sso.html | yes |
| AWS Config | Available | inferred (Control Tower's baseline Config recorder is part of GovCloud Control Tower); **not verified** against a GovCloud page | yes |
| GuardDuty | Available, with feature gaps | web, GovCloud User Guide service pages (not re-fetched for this spec) | yes |
| Security Hub | Available; some Control Tower Security Hub controls unavailable | web, [C-GCCT](https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-controltower.html) | yes |
| IAM Access Analyzer | Available except policy generation | web, GovCloud User Guide (not re-fetched for this spec) | yes |
| Macie | **Not available** | inferred from https://docs.aws.amazon.com/general/latest/gr/macie.html (no GovCloud endpoint) | **no** (`req-aws-landing-zone-nongoals`) |
| EC2 EBS default encryption, S3 Control public-access block | Available | read: botocore 1.43.104 endpoint data (not a GovCloud page) | yes |

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-landing-zone-availability-1 | Availability Is Data | Proposed | Every service this spec collects has a row in the partition availability table with its evidence and method. A service not offered in the run's partition records `SERVICE_NOT_AVAILABLE_IN_PARTITION` and makes no call. | Extends `partition.py`'s table. |
| req-aws-landing-zone-availability-2 | Unverified Is Said | Proposed | Where availability is unverified (Control Tower baseline APIs, Config), a failing call is recorded as failed with the partition hint, and a listing is never read as observed-empty. | |

### Control Tower
----
RID: `req-aws-landing-zone-control-tower`

Status: `Proposed`

#### Implementation

Read from the management account, in the landing zone's home region. Gruntwork builds the landing
zone either by hand in the console (the 2.0 guide) or with `control-tower-landing-zone` (default
version 4.0). The two paths produce the same API objects (inferred: both create an `aws_controltower_landing_zone`).

**Error codes are not verified.** The not-found codes in the falsifier columns come from AWS API knowledge (inferred). Each must be checked against the pinned botocore and the service's documented errors before a falsifier is written, as unified-systems-com/aws-core-tap#15 requires. A code that turns out to be shared with "you may not look" makes that type's falsifier `UNDETERMINED`, never `DROPPED`.

| Type | Source (read: botocore) | Key | Tags (lane, path, shape) | Contained by | Falsifier: gone when | Reference edges |
| --- | --- | --- | --- | --- | --- | --- |
| `aws_controltower_landing_zone` | `controltower:ListLandingZones`, `GetLandingZone` | landing zone ARN | service, `ListTagsForResource(resourceArn)`, `tags`, **map** | home-region footprint of the management account, `HOSTS_LANDING_ZONE` | `ResourceNotFoundException` | — (version, status, drift status, governed regions are typed fields) |
| `aws_controltower_enabled_control` | `controltower:ListEnabledControls` | enabled-control ARN | service, as above | landing zone, `HOLDS_ENABLED_CONTROL` | `GetEnabledControl` → `ResourceNotFoundException` | `APPLIES_TO_TARGET` (→ OU or account, from `targetIdentifier`, which names either) |
| `aws_controltower_enabled_baseline` | `controltower:ListEnabledBaselines` | enabled-baseline ARN | service, as above | landing zone, `HOLDS_ENABLED_BASELINE` | `GetEnabledBaseline` → `ResourceNotFoundException` | `APPLIES_TO_TARGET` (→ OU or account) |

- The Control Tower tag `aws-control-tower` = `managed-by-control-tower`, which AWS evidences only
  on Config resources ([C-MAND](https://docs.aws.amazon.com/controltower/latest/controlreference/mandatory-controls.html)), is an ordinary tag. Its key is not under the reserved `aws:`
  prefix, so `req-aws-collector-tags-11` does not apply to it. It gets no special handling.
- The model does not hard-code landing zone 3.x's resource set. 4.0 makes Config, CloudTrail,
  security roles, Backup and Identity Center optional, and drops the Security OU ([C-V4](https://docs.aws.amazon.com/controltower/latest/userguide/key-changes-lz-v4.html)).
- Control Tower's account-vending objects (the Service Catalog "AWS Control Tower Account Factory"
  product and its provisioned products) are **not** modelled (`req-aws-landing-zone-nongoals`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-landing-zone-control-tower-1 | Landing Zone Collected | Proposed | A management-account run with Control Tower writes one landing-zone node with version, status, drift status and governed regions; a run without one writes none and says so. | |
| req-aws-landing-zone-control-tower-2 | Controls And Baselines Attached | Proposed | Each enabled control and enabled baseline is a node with an `APPLIES_TO_TARGET` edge to the OU or account its target identifier names. | |
| req-aws-landing-zone-control-tower-3 | Retirement Path | Proposed | All three types are containment targets with registered falsifiers passing the four-case harness. Each containment pair also records the completeness surface `req-aws-core-contained-type-triple` (`spec-aws-core-v0.md`) lists for it, including a complete-empty surface for a parent with no children. | |
| req-aws-landing-zone-control-tower-4 | Tags Via Map Lane | Proposed | Control Tower tags come from `ListTagsForResource`'s lowercase `tags` map through the `service` lane, shape `map`. | Read: botocore `controltower` model. |

### Identity Center Access
----
RID: `req-aws-landing-zone-identity-center`

Status: `Proposed`

#### Implementation

The instance model exists (`req-aws-core-identity-center`) and is never collected.
Identity Center lives in the management account, or in a delegated administrator, in its home
region.

**Error codes are not verified.** The not-found codes in the falsifier columns come from AWS API knowledge (inferred). Each must be checked against the pinned botocore and the service's documented errors before a falsifier is written, as unified-systems-com/aws-core-tap#15 requires. A code that turns out to be shared with "you may not look" makes that type's falsifier `UNDETERMINED`, never `DROPPED`.

| Type | Source (read: botocore) | Key | Tags (lane, path, shape) | Contained by | Falsifier: gone when | Reference edges |
| --- | --- | --- | --- | --- | --- | --- |
| `aws_identity_center_instance` (exists, has `tags`) | `sso-admin:ListInstances` | instance ARN | service, `ListTagsForResource(InstanceArn, ResourceArn)`, `Tags`, list_kv | home-region footprint, `HOSTS_IDENTITY_CENTER_INSTANCE` | absent from `ListInstances` | `TRUSTS_IDENTITY_SOURCE` (exists; target open) |
| `aws_identity_center_permission_set` **(new)** | `ListPermissionSets`, `DescribePermissionSet`, `ListManagedPoliciesInPermissionSet` | permission-set ARN | service, as above | instance, `HOLDS_PERMISSION_SET` | `DescribePermissionSet` → `ResourceNotFoundException` | — (managed policy ARNs and session duration are typed fields; the inline policy is not read by this requirement; see below) |
| `aws_identity_center_group` **(new)** | `identitystore:ListGroups(IdentityStoreId)` | (identity store id, group id) | **AWS cannot tag a group** (read: `identitystore` has no tag operation) | instance, `HOLDS_IDENTITY_GROUP` | `DescribeGroup` → `ResourceNotFoundException` | — (`ExternalIds` from SCIM, for example Okta, are a typed field) |
| `aws_identity_center_account_assignment` **(new)** | `ListPermissionSetsProvisionedToAccount` then `ListAccountAssignments(AccountId, PermissionSetArn)` per account | (instance ARN, account id, permission-set ARN, principal type, principal id) | **AWS cannot tag an assignment** | instance, `HOLDS_ACCOUNT_ASSIGNMENT` | the (account, permission set) listing no longer names the principal | `GRANTS_PERMISSION_SET` (→ permission set), `GRANTS_ACCESS_TO_ACCOUNT` (→ account), `GRANTED_TO_GROUP` (→ group, when the principal is a group) |

- **Users are not nodes** (ruling 2026-10-01). A `USER` assignment records `principal_type` and
  `principal_id` only, and no identity-store user is read or written. Groups are nodes because the
  question asked is which group reaches which account.
- **One surface for the assignment listings.** Every assignment hangs directly off the instance
  (`HOLDS_ACCOUNT_ASSIGNMENT`), but the inventory comes from many listings: the organization's
  account set, one `ListPermissionSetsProvisionedToAccount` per account, and one
  `ListAccountAssignments` per (account, permission set) pair. Core derives candidates by fanning
  out from the surface's parent through its edge type (`req-grid-reconcile-candidates`), so a surface
  recorded for one pair would nominate the assignments of every other pair. The rule is one
  `HOLDS_ACCOUNT_ASSIGNMENT` surface per instance, recorded complete only when the account set read
  to its end (the organization-wide `ListAccounts`) and every nested listing for every account read
  to its end; any failed or partial call records it `enumeration_complete: false` with the reason.
  No surface is recorded per pair. A per-pair parent node was considered and declined: AWS has no
  object for "permission set P provisioned to account A" that it addresses or deletes on its own (an
  assignment is removed by `DeleteAccountAssignment`, which names the whole assignment), so that
  parent would be a node AWS does not address (`req-aws-core-network-plane`'s rule), with its own
  falsifier to write. The cost of the aggregate is that one failed nested listing defers every
  assignment's retirement for that run, which fails closed.
- **Cost.** Assignments cost one call per (account × permission set provisioned to it). With fan-out
  that is bounded by the organization's size, and it is counted in the per-account results.
- **Untaggable types declare it.** Identity-store groups and account assignments cannot be tagged in
  AWS. Their manifest declarations use `{"source": "none", "why": ...}` (`req-aws-collector-tags-12`).
- Control Tower's own groups and permission sets (`AWSAccountFactory`, `AWSAdministratorAccess`, …)
  and Gruntwork's (`GWFullAccess`, …) are ordinary members of these types.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-landing-zone-identity-center-1 | Instance Collected | Proposed | A run whose credential can `ListInstances` writes the instance with `home_region` and `identity_store_id`. | Closes "modelled, never collected". |
| req-aws-landing-zone-identity-center-2 | Who Reaches Which Account | Proposed | A Gryphon query from a group to the accounts it can reach, with the permission set, is answered from assignment nodes and their three edges. | |
| req-aws-landing-zone-identity-center-3 | No User Nodes | Proposed | No identity-store user is written as a node; a user assignment carries its principal id only. | Ruling 2026-10-01. |
| req-aws-landing-zone-identity-center-4 | Retirement Path | Proposed | Permission set, group and assignment are containment targets with registered falsifiers passing the four-case harness. Each containment pair also records the completeness surface `req-aws-core-contained-type-triple` (`spec-aws-core-v0.md`) lists for it, including a complete-empty surface for a parent with no children. | |
| req-aws-landing-zone-identity-center-5 | Assignment Surface Spans Nested Listings | Proposed | The collector records exactly one `HOLDS_ACCOUNT_ASSIGNMENT` surface per instance, complete only when the organization's account listing, every `ListPermissionSetsProvisionedToAccount` and every `ListAccountAssignments` read to their end; otherwise it is recorded incomplete with the reason. No surface is recorded per (account, permission set). A test fails one nested listing and asserts the surface is incomplete and no assignment is a candidate. | Core fans candidates out from parent and edge type (`req-grid-reconcile-candidates`), so a per-pair surface would nominate other pairs' assignments. Same rule as `req-aws-core-organizations-completeness-13`. |

### Security Services
----
RID: `req-aws-landing-zone-security-services`

Status: `Proposed`

#### Implementation

Collected in **every** account and region the run reaches, through `req-aws-collector-fanout`.
Gruntwork's baselines turn these on per opt-in region (`control-tower-app-account-baseline`, https://docs.gruntwork.io/reference/modules/terraform-aws-control-tower/control-tower-app-account-baseline/).

**Error codes are not verified.** The not-found codes in the falsifier columns come from AWS API knowledge (inferred). Each must be checked against the pinned botocore and the service's documented errors before a falsifier is written, as unified-systems-com/aws-core-tap#15 requires. A code that turns out to be shared with "you may not look" makes that type's falsifier `UNDETERMINED`, never `DROPPED`.

| Type | Source (read: botocore) | Key | Tags (lane, path, shape) | Contained by | Falsifier: gone when | Reference edges |
| --- | --- | --- | --- | --- | --- | --- |
| `aws_config_recorder` **(new)** | `config:DescribeConfigurationRecorders`, `DescribeConfigurationRecorderStatus` | (account, region, recorder name) | service, `config:ListTagsForResource(ResourceArn)`, `Tags`, list_kv (ConfigurationRecorder is a supported resource; read) | footprint, `HOSTS_CONFIG_RECORDER` | absent from the describe call | — (the recording flag is a typed field) |
| `aws_config_delivery_channel` **(new)** | `config:DescribeDeliveryChannels` (unpaginated) | (account, region, channel name) | AWS cannot tag a delivery channel (inferred: it is not among Config's taggable resource types) | footprint, `HOSTS_CONFIG_DELIVERY_CHANNEL` | absent from `DescribeDeliveryChannels` | `WRITES_LOGS` (exists; → S3 bucket, from `s3BucketName`) |
| `aws_config_aggregator` **(new)** | `config:DescribeConfigurationAggregators` | aggregator ARN | service, as above | footprint, `HOSTS_CONFIG_AGGREGATOR` | `NoSuchConfigurationAggregatorException` | — (organization-wide vs account sources are typed fields) |
| `aws_guardduty_detector` **(new)** | `guardduty:ListDetectors`, `GetDetector`, `GetAdministratorAccount` | (account, region, detector id) | field, `Tags`, **map** (`GetDetector` returns it) | footprint, `HOSTS_GUARDDUTY_DETECTOR` | `BadRequestException` naming the detector / absent from `ListDetectors` | `REPORTS_TO_ADMINISTRATOR` (→ administrator account) |
| `aws_securityhub_hub` **(new)** | `securityhub:DescribeHub`, `GetEnabledStandards`, `GetAdministratorAccount` | hub ARN | service, `ListTagsForResource(ResourceArn)`, `Tags`, **map** | footprint, `HOSTS_SECURITYHUB_HUB` | `InvalidAccessException` "not subscribed" / `ResourceNotFoundException` | `REPORTS_TO_ADMINISTRATOR`. The enabled standards are a typed list |
| `aws_access_analyzer` **(new)** | `accessanalyzer:ListAnalyzers` | analyzer ARN | field, **`tags`**, map (lowercase; read) | footprint, `HOSTS_ACCESS_ANALYZER` | `ResourceNotFoundException` | — (`type` is a typed field holding the API's `Type` enum: `ACCOUNT`, `ORGANIZATION`, `ACCOUNT_UNUSED_ACCESS`, `ORGANIZATION_UNUSED_ACCESS`, `ACCOUNT_INTERNAL_ACCESS`, `ORGANIZATION_INTERNAL_ACCESS`; read: botocore 1.43.103 `accessanalyzer` model. A value outside the pinned enum is kept verbatim with an `UNKNOWN_ENUM_VALUE` warning, never rejected) |
| EBS default encryption | `ec2:GetEbsEncryptionByDefault`, `GetEbsDefaultKmsKeyId` | — (a per-region account setting, not a resource) | not a resource, so nothing to tag | — (typed fields on the existing footprint: `ebs_encryption_by_default`, `ebs_default_kms_key_id`) | — (replaced every run) | — |
| S3 account public-access block | `s3control:GetPublicAccessBlock(AccountId)` | — (an account setting) | not a resource, so nothing to tag | — (typed fields on `aws_account`: the four block flags) | — (replaced every run) | — |

- **Absent vs denied.** For the two settings, AWS's "not configured" (`NoSuchPublicAccessBlockConfiguration`)
  is an observed `false`, and a denied call is `null`. The two are never merged
  (`req-aws-collector-hydrate-6`'s rule).
- **The account-node writer.** The S3 public-access-block fields are account-sourced. They are among
  the fields `req-aws-collector-fanout-8` merges with the organization-sourced ones, so the org-tree
  node does not drop them.
- **Detectors and hubs as nodes, not fields.** GuardDuty and Security Hub each have an ARN or id,
  tags, and an administrator relationship to another account. That makes them nodes, per AGENTS.md's
  "create the dedicated node type".

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-landing-zone-security-services-1 | Per Account And Region | Proposed | For every account and region a fan-out run reaches, each service's presence is a node (or, for the two settings, typed fields) or an explicit not-enabled observation; a denied read is recorded as unknown, never as off. | |
| req-aws-landing-zone-security-services-2 | Administrator Edges | Proposed | A member detector or hub whose administrator is another account has `REPORTS_TO_ADMINISTRATOR` to that account. | Pairs with `req-aws-core-organizations-completeness-4`. |
| req-aws-landing-zone-security-services-3 | Retirement Path | Proposed | Every node type here is a footprint containment target with a registered falsifier passing the four-case harness; the two settings are fields replaced every run and need none. Each containment pair also records the completeness surface `req-aws-core-contained-type-triple` (`spec-aws-core-v0.md`) lists for it, including a complete-empty surface for a parent with no children. | |
| req-aws-landing-zone-security-services-4 | Tags Per Botocore | Proposed | Each type's tag lane, path and shape are as tabled and pass `req-aws-collector-tags-13`'s botocore check. | GuardDuty, Security Hub, Access Analyzer are `map`; Config is `list_kv`. |

### Non-Goals
----
RID: `req-aws-landing-zone-nongoals`

Status: `Proposed`

- **Account vending.** No Service Catalog provisioned product, no Account Factory request, no
  `CreateGovCloudAccount` workflow (ruling 2026-09-30). Control Tower's Account Factory cannot
  create GovCloud accounts anyway ([C-GCCT](https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-controltower.html)).
- **Macie.** It is not available in GovCloud (inferred from https://docs.aws.amazon.com/general/latest/gr/macie.html), so it is not
  modelled. Gruntwork's baseline must run there with `disable_macie`.
- **AFT.** It is closed to new customers in GovCloud ([C-GCCT](https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-controltower.html)).
- **Config rules, conformance packs and findings.** Control Tower's detective controls are Config
  rules, numerous and service-linked. Findings from GuardDuty, Security Hub and Access Analyzer are
  events, not resources. Both are later work.
- **Inspector and Detective.** No Gruntwork baseline read enables them (not found in the module reference pages).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-landing-zone-nongoals-1 | Deferrals Named | Proposed | Each non-goal is named with its reason, so its absence is not read as an oversight. | |

## Open Questions

- The Control Tower baseline APIs (`ListEnabledBaselines`) were excluded from GovCloud in February
  2024 (https://docs.aws.amazon.com/controltower/latest/userguide/2024-all.html), and their current
  GovCloud status has not been re-verified. The first GovCloud run's call ledger answers this.
- Permission-set inline policies are not read by this requirement. When a later change reads them,
  they follow the policy-statement rule of `req-aws-core-organizations-completeness`
  (`spec-aws-core-v0.md`, *Policy statements*): each statement a node contained by its permission
  set, not a stored document.
