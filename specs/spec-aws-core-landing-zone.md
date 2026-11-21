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
| 5. | Reported | What those services report (GuardDuty, Security Hub, Access Analyzer and Inspector findings, Config rule compliance) is on the grid, attached to the service and the resource it concerns, bounded and never mistaken for a complete inventory |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-aws-landing-zone-availability | [GovCloud Availability](#govcloud-availability) | Proposed | Per-service GovCloud availability as data; an unavailable service is `SERVICE_NOT_AVAILABLE_IN_PARTITION`, never an empty listing; Macie is not modelled |
| req-aws-landing-zone-control-tower | [Control Tower](#control-tower) | Proposed | Landing zone, enabled controls, enabled baselines; targets as reference edges; contained by the landing zone |
| req-aws-landing-zone-identity-center | [Identity Center Access](#identity-center-access) | Proposed | Collect the instance; permission sets, groups and account assignments; users only as principal ids |
| req-aws-landing-zone-security-services | [Security Services](#security-services) | Proposed | Config recorder, delivery channel and aggregator, GuardDuty detector, Security Hub hub, Access Analyzer analyzer per account × region; EBS default encryption and S3 account public-access block as typed fields |
| req-aws-landing-zone-findings | [Security Findings](#security-findings) | Proposed | Active and recently closed (30 days) GuardDuty, Security Hub (control results included) and Access Analyzer findings with what each says about itself, and Config rule and conformance pack compliance with each rule's scope, parameters and policy body, for the run's own account; read to the end unless the operator sets a per-region limit or a read budget; per-severity totals of active findings on the parent; findings surfaces never complete |
| req-aws-landing-zone-inspector | [Inspector Findings](#inspector-findings) | Proposed | Every Amazon Inspector v2 finding type (package vulnerability, code vulnerability, network reachability) by default, down-selectable, for the run's own account, active and closed in 30 days, read to the end unless the shared findings limit is set; true totals and account status on the footprint; linked to the EC2 instance, Lambda function, ECR repository or image host they concern; never complete |
| req-aws-landing-zone-inspector-reachability | [Inspector Reachability Is A Compound Edge](#inspector-reachability-is-a-compound-edge) | Proposed | The reachability finding is the middle node of the first compound edge: gateway source, network-interface destination, route table / security group / NACL path; retires with either end |
| req-aws-landing-zone-inspector-compliance | [Inspector Findings In compliance_core](#inspector-findings-in-compliance_core) | Proposed | Off by default; an optional `depends_on` on compliance_core (>= 0.8.13), written by slug and never imported; projected from the stored rows as the run's last step; CVSS filled only when empty |
| req-aws-landing-zone-inspector-packages | [Inspector Packages On The Image Host](#inspector-packages-on-the-image-host) | Proposed | An ECR image finding's packages as computing_core packages the image host installs, keyed as the SBOM parser keys them; with the projection on, the packages carry the finding, which is what fedramp_20x_vdr's reach walks |
| req-aws-landing-zone-nongoals | [Non-Goals](#non-goals) | Proposed | Account vending, Macie, Control Tower Account Factory, AFT, findings closed before the 30-day window, writing back to a finding, joining Security Hub's copy of an Inspector finding |

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

Read from the management account, in the landing zone's home region. `ListEnabledControls` and
`ListEnabledBaselines` are called with no target or filter: `targetIdentifier` is optional, since
neither input shape has required members (read: botocore 1.43.103 `controltower` model). Both are
called with `includeChildren: true`. `ListEnabledBaselines` documents a default of false, which
omits child enabled baselines, and `ListEnabledControls` documents no default, so neither is left
to it (`req-aws-core-contained-type-triple-6`). Gruntwork builds the landing
zone either by hand in the console (the 2.0 guide) or with `control-tower-landing-zone` (default
version 4.0). The two paths produce the same API objects (inferred: both create an `aws_controltower_landing_zone`).

**Error codes are not verified.** The not-found codes in the falsifier columns come from AWS API knowledge (inferred). Each must be checked against the pinned botocore and the service's documented errors before a falsifier is written, as unified-systems-com/aws-core-tap#15 requires. A code that turns out to be shared with "you may not look" makes that type's falsifier `UNDETERMINED`, never `DROPPED`.

| Type | Source (read: botocore) | Key | Tags (lane, path, shape) | Contained by | Falsifier: gone when | Reference edges |
| --- | --- | --- | --- | --- | --- | --- |
| `aws_controltower_landing_zone` | `controltower:ListLandingZones`, `GetLandingZone` | landing zone ARN | service, `ListTagsForResource(resourceArn)`, `tags`, **map** | home-region footprint of the management account, `HOSTS_LANDING_ZONE` | `ResourceNotFoundException` | — (version, status, drift status, governed regions are typed fields) |
| `aws_controltower_enabled_control` | `controltower:ListEnabledControls(includeChildren=true)` | enabled-control ARN | service, as above | landing zone, `HOLDS_ENABLED_CONTROL` | `GetEnabledControl` → `ResourceNotFoundException` | `APPLIES_TO_TARGET` (→ OU or account, from `targetIdentifier`, which names either; normalized from the ARN to the OU or account id) |
| `aws_controltower_enabled_baseline` | `controltower:ListEnabledBaselines(includeChildren=true)` | enabled-baseline ARN | service, as above | landing zone, `HOLDS_ENABLED_BASELINE` | `GetEnabledBaseline` → `ResourceNotFoundException` | `APPLIES_TO_TARGET` (→ OU or account, normalized as above); a child baseline's `parentIdentifier` is a typed field |

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
| `aws_identity_center_instance` (exists, has `tags`) | `sso-admin:ListInstances`; `home_region` = the instance's `PrimaryRegion`, and `Regions` is a typed field. The instance and its `HOSTS_IDENTITY_CENTER_INSTANCE` edge are emitted once per instance ARN, from the `PrimaryRegion` footprint, whichever regional endpoint returned it | instance ARN | service, `ListTagsForResource(InstanceArn, ResourceArn)`, `Tags`, list_kv | home-region footprint, `HOSTS_IDENTITY_CENTER_INSTANCE` | absent from `ListInstances` | `TRUSTS_IDENTITY_SOURCE` (exists; target open) |
| `aws_identity_center_permission_set` **(new)** | `ListPermissionSets`, `DescribePermissionSet`, `ListManagedPoliciesInPermissionSet` (paginated: read to its end, and a later-page failure leaves the managed-policy list `null`; `req-aws-collector-pagination`) | permission-set ARN | service, as above | instance, `HOLDS_PERMISSION_SET` | `DescribePermissionSet` → `ResourceNotFoundException` | — (managed policy ARNs and session duration are typed fields; the inline policy is not read by this requirement; see below) |
| `aws_identity_center_group` **(new)** | `identitystore:ListGroups(IdentityStoreId)` | (identity store id, group id) | **AWS cannot tag a group** (read: `identitystore` has no tag operation) | instance, `HOLDS_IDENTITY_GROUP` | `DescribeGroup` → `ResourceNotFoundException` | — (`ExternalIds` from SCIM, for example Okta, are a typed field) |
| `aws_identity_center_account_assignment` **(new)** | `ListPermissionSetsProvisionedToAccount` then `ListAccountAssignments(AccountId, PermissionSetArn)` per account | (instance ARN, account id, permission-set ARN, principal type, principal id) | **AWS cannot tag an assignment** | instance, `HOLDS_ACCOUNT_ASSIGNMENT` | the (account, permission set) listing no longer names the principal; or `ListAccountAssignments` raises `ResourceNotFoundException` **and** a disambiguating probe confirms which resource is gone: `DescribePermissionSet` answering not-found, or the account's absence from the organization proven by the membership falsifier's reach-gated `DescribeAccount` (`AccountNotFoundException`; `req-aws-core-organization-membership-4`). `ResourceNotFoundException` alone is `UNDETERMINED`, because sso-admin uses it for the instance, the account and the permission set alike (read: botocore error list) | `GRANTS_PERMISSION_SET` (→ permission set), `GRANTS_ACCESS_TO_ACCOUNT` (→ account), `GRANTED_TO_GROUP` (→ group, when the principal is a group) |

- **One node per instance, whatever endpoint answers.** A multi-region Identity Center instance is
  returned by more than one regional endpoint. It is keyed by ARN and emitted once, contained by
  the footprint of its `PrimaryRegion`. The same rule applies to the landing zone: it is emitted
  once by ARN under its home-region footprint, the region in its ARN (inferred: Control Tower
  creates the landing zone in its home region).
- **A primary region outside the run's region scope** (the finding carried from aws-core-tap#71,
  settled in aws-core-tap#66). Footprints exist only for regions in scope
  (`req-aws-collector-regions-5`), so an instance that an in-scope secondary region returns, but
  whose `PrimaryRegion` is out of scope, has no footprint to be contained by. It is written anyway,
  keyed by ARN with `home_region` = its `PrimaryRegion`, with **no** `HOSTS_IDENTITY_CENTER_INSTANCE`
  edge, and the run records the warning `IDENTITY_CENTER_PRIMARY_REGION_OUT_OF_SCOPE` naming the
  primary region and the region it was read through. Its children are read through that in-scope
  region and recorded under the instance as usual. The in-scope footprint that returned it records a
  complete surface in which the instance counts as observed but not hosted, so it never nominates the
  instance. A landing zone whose home region is out of scope is handled the same way
  (`LANDING_ZONE_HOME_REGION_OUT_OF_SCOPE`). Requiring the primary region in scope was considered and
  declined: it would drop a real instance from the run to protect a containment edge that, with
  reconcile off, nominates nothing.
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
| req-aws-landing-zone-identity-center-1 | Instance Collected | Proposed | A run whose credential can `ListInstances` writes the instance with `home_region` and `identity_store_id`. `home_region` is `ListInstances`' `PrimaryRegion`; a multi-region instance returned by several regional endpoints is one node with one containment edge, from its primary region's footprint. | Closes "modelled, never collected". Supersedes, on approval, `req-aws-core-identity-center`'s "`home_region` is the region that call is made in" (read: botocore 1.43.103 `InstanceMetadata` has `PrimaryRegion` and `Regions`). |
| req-aws-landing-zone-identity-center-2 | Who Reaches Which Account | Proposed | A Gryphon query from a group to the accounts it can reach, with the permission set, is answered from assignment nodes and their three edges. | |
| req-aws-landing-zone-identity-center-3 | No User Nodes | Proposed | No identity-store user is written as a node; a user assignment carries its principal id only. | Ruling 2026-10-01. |
| req-aws-landing-zone-identity-center-4 | Retirement Path | Proposed | Permission set, group and assignment are containment targets with registered falsifiers passing the four-case harness. Each containment pair also records the completeness surface `req-aws-core-contained-type-triple` (`spec-aws-core-v0.md`) lists for it, including a complete-empty surface for a parent with no children. | |
| req-aws-landing-zone-identity-center-5 | Assignment Surface Spans Nested Listings | Proposed | The collector records exactly one `HOLDS_ACCOUNT_ASSIGNMENT` surface per instance, complete only when the organization's account listing, every `ListPermissionSetsProvisionedToAccount` and every `ListAccountAssignments` read to their end; otherwise it is recorded incomplete with the reason. No surface is recorded per (account, permission set). A test fails one nested listing and asserts the surface is incomplete and no assignment is a candidate. | Core fans candidates out from parent and edge type (`req-grid-reconcile-candidates`), so a per-pair surface would nominate other pairs' assignments. Same rule as `req-aws-core-organizations-completeness-13`. |
| req-aws-landing-zone-identity-center-7 | Primary Region Outside The Scope | Proposed | An instance whose `PrimaryRegion` is outside the run's region scope, returned by an in-scope region, is written once with `home_region` = its `PrimaryRegion`, has no `HOSTS_IDENTITY_CENTER_INSTANCE` edge, and raises the warning `IDENTITY_CENTER_PRIMARY_REGION_OUT_OF_SCOPE`; its children are read through the region that returned it. The returning footprint's surface is complete and counts the instance as observed but not hosted. | Settles the finding carried from aws-core-tap#71 (aws-core-tap#66). |
| req-aws-landing-zone-identity-center-6 | Assignment Of A Departed Account Retires | Proposed | An assignment whose account has left the organization is `DROPPED_FROM_OBSERVATION`: when `ListAccountAssignments` raises `ResourceNotFoundException`, the falsifier asks the membership falsifier's reach-gated probe, and `AccountNotFoundException` after reach is proven drops the assignment. If neither the permission set nor the account is confirmed gone, the verdict is `UNDETERMINED`. Tests: account removed → dropped; permission set deleted → dropped; neither confirmed → undetermined. | Without it, an assignment to a departed account would stay `UNDETERMINED` forever, leaving a stale access edge. |

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
| `aws_config_recorder` **(new)** | `config:ListConfigurationRecorders` (paginated, unfiltered: customer-managed and service-linked), then `DescribeConfigurationRecorders(Arn=…)` and `DescribeConfigurationRecorderStatus` per recorder | recorder ARN | service, `config:ListTagsForResource(ResourceArn)`, `Tags`, list_kv (ConfigurationRecorder is a supported resource; read) | footprint, `HOSTS_CONFIG_RECORDER` | absent from `ListConfigurationRecorders` | — (the recording flag, `servicePrincipal` and `recordingScope` are typed fields) |
| `aws_config_delivery_channel` **(new)** | `config:DescribeDeliveryChannels` (unpaginated) | (account, region, channel name) | AWS cannot tag a delivery channel (inferred: it is not among Config's taggable resource types) | footprint, `HOSTS_CONFIG_DELIVERY_CHANNEL` | absent from `DescribeDeliveryChannels` | `WRITES_LOGS` (exists; → S3 bucket, from `s3BucketName`) |
| `aws_config_aggregator` **(new)** | `config:DescribeConfigurationAggregators` | aggregator ARN | service, as above | footprint, `HOSTS_CONFIG_AGGREGATOR` | `NoSuchConfigurationAggregatorException` | — (organization-wide vs account sources are typed fields) |
| `aws_guardduty_detector` **(new)** | `guardduty:ListDetectors`, `GetDetector`, `GetAdministratorAccount` | (account, region, detector id) | field, `Tags`, **map** (`GetDetector` returns it) | footprint, `HOSTS_GUARDDUTY_DETECTOR` | `BadRequestException` naming the detector / absent from `ListDetectors` | `REPORTS_TO_ADMINISTRATOR` (→ administrator account) |
| `aws_securityhub_hub` **(new)** | `securityhub:DescribeHub`, `GetEnabledStandards` (paginated: read to its end, and a later-page failure leaves the enabled-standards list `null`; `req-aws-collector-pagination`), `GetAdministratorAccount` | hub ARN | service, `ListTagsForResource(ResourceArn)`, `Tags`, **map** | footprint, `HOSTS_SECURITYHUB_HUB` | `InvalidAccessException` "not subscribed" / `ResourceNotFoundException` | `REPORTS_TO_ADMINISTRATOR`. The enabled standards are a typed list |
| `aws_access_analyzer` **(new)** | `accessanalyzer:ListAnalyzers(type=…)`, once per value of the pinned `Type` enum | analyzer ARN | field, **`tags`**, map (lowercase; read) | footprint, `HOSTS_ACCESS_ANALYZER` | `ResourceNotFoundException` | — (`type` is a typed field holding the API's `Type` enum: `ACCOUNT`, `ORGANIZATION`, `ACCOUNT_UNUSED_ACCESS`, `ORGANIZATION_UNUSED_ACCESS`, `ACCOUNT_INTERNAL_ACCESS`, `ORGANIZATION_INTERNAL_ACCESS`; read: botocore 1.43.103 `accessanalyzer` model. A value outside the pinned enum is kept verbatim with an `UNKNOWN_ENUM_VALUE` warning, never rejected) |
| EBS default encryption | `ec2:GetEbsEncryptionByDefault`, `GetEbsDefaultKmsKeyId` | — (a per-region account setting, not a resource) | not a resource, so nothing to tag | — (typed fields on the existing footprint: `ebs_encryption_by_default`, `ebs_default_kms_key_id`) | — (replaced every run) | — |
| S3 account public-access block | `s3control:GetPublicAccessBlock(AccountId)`, called once per account in the partition's home region (an account-level setting, so one observation, not one per region) | — (an account setting) | not a resource, so nothing to tag | — (typed fields on `aws_account`: the four block flags) | — (replaced every run) | — |

- **Absent vs denied.** Each setting has its own "off" answer, and a denied call is `null` for
  both. The two are never merged (`req-aws-collector-hydrate-6`'s rule).
  - S3 account public-access block: AWS answers an account with no configuration with
    `NoSuchPublicAccessBlockConfiguration`, which is stored as an observed `false` on all four flags.
  - EBS default encryption: `GetEbsEncryptionByDefault` succeeds and returns
    `EbsEncryptionByDefault: false` (read: botocore output shape), which is stored as returned. No
    exception is expected or interpreted. `GetEbsDefaultKmsKeyId` likewise returns the key id as
    a value.
- **The account-node writer.** The S3 public-access-block fields are account-sourced. They are among
  the fields `req-aws-collector-fanout-8` merges with the organization-sourced ones, so the org-tree
  node does not drop them.
- **Error codes, as checked against botocore 1.43.107 (aws-core-tap#66).** `controltower`
  `ResourceNotFoundException`, `accessanalyzer` `ResourceNotFoundException`, `identitystore`
  `ResourceNotFoundException` and `config` `NoSuchConfigurationAggregatorException` are each
  documented as the resource not existing, distinct from the operation's access-denied code, and are
  the falsifiers' "gone". Two rows differ from the table above:
  - `securityhub:DescribeHub`'s `InvalidAccessException` is documented as "the account doesn't have
    permission to perform this action", which is also the answer for an account without Security
    Hub. The code is shared with "you may not look", so it is never "not enabled": the hub surface is
    recorded incomplete (`scope_authorized` unknown) and the falsifier answers `UNDETERMINED`. No
    verified "not subscribed" code exists in the pinned botocore, so the complete-empty case of
    `req-aws-core-contained-type-triple`'s hub row does not occur yet. The first GovCloud run's
    ledger is the evidence to revisit it.
  - GuardDuty's only modelled error is the generic `BadRequestException`, so the detector falsifier
    uses the table's second rule, absence from a complete `ListDetectors`.
- **Detectors and hubs as nodes, not fields.** GuardDuty and Security Hub each have an ARN or id,
  tags, and an administrator relationship to another account. That makes them nodes, per AGENTS.md's
  "create the dedicated node type".

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-landing-zone-security-services-1 | Per Account And Region | Proposed | For every account and region a fan-out run reaches, each service's presence is a node (or, for the two settings, typed fields) or an explicit not-enabled observation; a denied read is recorded as unknown, never as off. EBS default encryption is read once per footprint (account × region); the S3 account public-access block is read exactly once per account, through `s3control` in the partition's home region, never per region. | |
| req-aws-landing-zone-security-services-2 | Administrator Edges | Proposed | A member detector or hub whose administrator is another account has `REPORTS_TO_ADMINISTRATOR` to that account. | Pairs with `req-aws-core-organizations-completeness-4`. |
| req-aws-landing-zone-security-services-3 | Retirement Path | Proposed | Every node type here is a footprint containment target with a registered falsifier passing the four-case harness; the two settings are fields replaced every run and need none. Each containment pair also records the completeness surface `req-aws-core-contained-type-triple` (`spec-aws-core-v0.md`) lists for it, including a complete-empty surface for a parent with no children. | |
| req-aws-landing-zone-security-services-4 | Tags Per Botocore | Proposed | Each type's tag lane, path and shape are as tabled and pass `req-aws-collector-tags-13`'s botocore check. | GuardDuty, Security Hub, Access Analyzer are `map`; Config is `list_kv`. |

### Security Findings
----
RID: `req-aws-landing-zone-findings`

Status: `Proposed`

Approved 2026-10-02 (highbar Q137a), scoped to the account the collector's credential reads, the
GovCloud management account (Q137b). Member accounts and the delegated security administrator are
fan-out's (`req-aws-collector-fanout`, aws-core-tap#63). Collect-only: nothing here arms reconcile.
Extended 2026-11-20 by the maintainer's rulings on what aws_core left out (aws-core-tap#264): Q114b
(addresses are stored as AWS wrote them), Q114c (what a finding says about itself is kept), Q115a
(recently closed findings are read) and Q115b (GuardDuty reaches every resource type it names).

#### Implementation

Read by the landing-zone reader, from the detector, hub and analyzer it already reads
(`collectors/boto3_collector/findings.py`). Shapes are **read** from botocore 1.43.103 service
models; nothing was observed against a live account.

| Type | Source (read: botocore) | Key | Tags | Contained by | Falsifier: gone when | Reference edges |
| --- | --- | --- | --- | --- | --- | --- |
| `aws_guardduty_finding` **(new)** | `guardduty:ListFindings(FindingCriteria: service.archived=false, accountId=<run account>; SortCriteria: severity DESC; MaxResults 50)`; then `ListFindings(FindingCriteria: service.archived=true, accountId=<run account>, updatedAt >= now - 30 days in epoch ms; SortCriteria: updatedAt DESC)`; each to its end unless the operator's limits stop it; `GetFindings` (≤50 ids a call) for both | finding ARN | **none** (a finding is not taggable; inferred) | detector, `HOLDS_GUARDDUTY_FINDING` | `GetFindings` names no such id (an archived finding is present, closed) | `CONCERNS_RESOURCE` (→ EC2 instance by `InstanceId`, S3 bucket by `S3BucketDetails[].Arn`, IAM user for an `IAMUser` access key, and whichever aws_core node `arn_resolver` finds for an ARN in `Resource`: `LambdaDetails.FunctionArn`, `RdsDbInstanceDetails.DbInstanceArn`, `RdsLimitlessDbDetails.DbShardGroupArn`, `EcsClusterDetails.Arn` and `.TaskDetails.Arn`, `EksClusterDetails.Arn`, and the malware-scan target `EbsVolumeDetails.ScannedVolumeDetails[].VolumeArn`; a closed list of target types, `findings.GUARDDUTY_CONCERNS_TARGETS`, equal to the model's declaration. An EBS snapshot, AMI or backup recovery point a finding names has no aws_core type and gets no edge) |
| `aws_securityhub_finding` **(new)** | `securityhub:GetFindings(Filters: AwsAccountId=<run account>, Region=<region>, RecordState=ACTIVE, SeverityLabel=<label>; MaxResults 100)`, one read per label from CRITICAL down; then `GetFindings(Filters: AwsAccountId, Region, RecordState=ARCHIVED, UpdatedAt DateRange 30 DAYS; SortCriteria: UpdatedAt desc)`; each to its end unless the operator's limits stop it | (`ProductArn`, `Id`) | **none** (inferred) | hub, `HOLDS_SECURITYHUB_FINDING` | `GetFindings(Id, ProductArn)` names none (an `ARCHIVED` record is present, closed); `InvalidAccessException` is `UNDETERMINED` | `EVALUATED_UNDER_STANDARD` (→ the enabled standard each `Compliance.AssociatedStandards[].StandardsId` names); `CONCERNS_RESOURCE` (→ whichever aws_core node is keyed by the ARN in `Resources[].Id`, whatever its type, and an `AwsEc2Instance` by the instance id from its ARN; aws-core-tap#242) |
| `aws_securityhub_standards_subscription` **(new)** | `securityhub:GetEnabledStandards` (unfiltered, to its end; the listing the hub's `enabled_standards` already comes from) | `StandardsSubscriptionArn` | **none** (inferred) | hub, `HOLDS_STANDARDS_SUBSCRIPTION` | absent from `GetEnabledStandards` | — |
| `aws_access_analyzer_finding` **(new)** | `accessanalyzer:ListFindings` for an external-access analyzer (`ACCOUNT`, `ORGANIZATION`), `ListFindingsV2` for the others (botocore: v1 "is supported only for external access analyzers"), `filter: status=ACTIVE, resourceOwnerAccount=<run account>`; then the same with `status in [ARCHIVED, RESOLVED]`, keeping a finding whose `updatedAt` is in the last 30 days (the filter has no date operator: botocore `Criterion` is eq, neq, contains, exists, and no sort on `updatedAt` is documented), applied to each page as it arrives so only in-window findings count against an operator's `findings_max_per_region`; the read walks every page (its 50-page bound was removed by rulings Q125a and b) unless `findings_read_budget_seconds` stops it, and is then recorded truncated | (analyzer ARN, finding id) | **none** (inferred) | analyzer, `HOLDS_ACCESS_ANALYZER_FINDING` | `GetFindingV2` → `ResourceNotFoundException` (an ARCHIVED or RESOLVED finding is present, closed) | `CONCERNS_RESOURCE` (→ S3 bucket, IAM role, IAM user by resource ARN) |
| `aws_config_rule` **(new)** | `config:DescribeConfigRules` (no names, no filters: botocore documents that as every rule), `DescribeComplianceByConfigRule` (every rule and compliance type), each to its end; `GetCustomRulePolicy(ConfigRuleName)` for a `CUSTOM_POLICY` rule whose listing carries no `PolicyText` | rule ARN | service, `config:ListTagsForResource(ResourceArn)`, `Tags`, list_kv | footprint, `HOSTS_CONFIG_RULE` | absent from a complete `DescribeConfigRules` (`NoSuchConfigRuleException` is documented as "not valid", not "does not exist", so it is not used) | — |
| `aws_config_conformance_pack` **(new)** | `config:DescribeConformancePacks` (no names), `GetConformancePackComplianceSummary` (5 names a call) | pack ARN | service, as above | footprint, `HOSTS_CONFORMANCE_PACK` | `DescribeConformancePacks(name)` → `NoSuchConformancePackException` | — |

- **Everything by default, trimmed by the operator** (maintainer, 2026-11-20, rulings Q125a and b: "collect
  everything by default and allow people to trim as necessary"). There is no fixed cap: every findings read
  (GuardDuty, Security Hub, Access Analyzer and Inspector, `req-aws-landing-zone-inspector`) runs to its last page.
  Two optional settings in the credential's `data` trim it (`spec-aws-core-secrets.md`,
  `req-aws-core-secret-findings-settings`), both off by default:
  - `findings_max_per_region`: the most findings one service writes per region per run, shared by that
    service's reads there in order: GuardDuty active then closed; Security Hub one label at a time from CRITICAL
    down, then closed; every analyzer of the region in turn, each active then closed. The order puts the most
    severe and the active first, so the limit drops the least severe and never lets closed findings crowd out
    active ones. Access Analyzer findings carry no severity and are read in the API's order.
  - `findings_read_budget_seconds`: each findings read stops at its next page once it has run that long.
  A read either one stops records `reasons.truncated` with the reason, and the parent's totals say so
  (GuardDuty's still come exact from `GetFindingsStatistics`). `FINDINGS_CAP` (1000 per parent) and
  `ACCESS_ANALYZER_CLOSED_MAX_PAGES` (50) are gone.
- **Closed in the last 30 days.** Beside the active read, each parent reads the findings it closed
  in the last 30 days (`CLOSED_WINDOW_DAYS`): GuardDuty archived, Security Hub `RecordState`
  ARCHIVED, Access Analyzer ARCHIVED or RESOLVED (aws-core-tap#264, ruling Q115a). Each closed read
  comes after the active one, most recently updated first where the API sorts, so under an operator's limit
  closed findings never crowd out active ones. A finding's state is the service's own field, stored verbatim:
  GuardDuty `archived`, Security Hub `record_state` (beside `workflow_status`, the operator's triage
  state), Access Analyzer `status`. No normalized copy is added: it would restate a field on the same
  node. A finding that closes is rewritten closed on the next run instead of staying on the grid as
  active, and its time to close is visible: AWS stamps no closed-at, so `updated_at` (the last change,
  which for a closed finding is its closing or later) minus `created_at` bounds it. One closed longer
  than the window is not read again and keeps the closed state it was last written with; one that
  closed while the collector was not running for over 30 days stays as it was last read.
- **Never complete.** Each findings surface depends on source-side filters (the run's account, active
  or closed in the window) with no bogus-value positive control, so it records `filter` verbatim and
  `filter_control: null`, and is `enumeration_complete: false` (`req-grid-reconcile-evidence-4`)
  however far the read ran: a read that reached its end uncapped is still filtered. It never nominates
  a retirement. Removing the cap removed one reason a surface was incomplete, not the filter rule.
  The surface relation is `<parent>.findings` (one surface for both
  reads). The falsifiers are registered so the triple is whole; a closed finding the service still
  returns is present, and a finding is gone only when the service no longer returns it.
- **Totals on the parent.** The detector, hub and analyzer carry `active_finding_counts`
  (`{label: count}`; by finding type for an analyzer), `active_finding_counts_complete` and
  `active_findings_truncated`. GuardDuty's totals come from
  `GetFindingsStatistics(GroupBy=SEVERITY)` and are exact however far the read ran; when that call fails
  or answers more than one page (its input takes no continuation token), the counts fall back to
  the read and are marked incomplete. Security Hub's are exact for every label read to its
  end. GuardDuty's labels are its documented bands: Critical 9.0-10.0, High 7.0-8.9, Medium
  4.0-6.9, Low 1.0-3.9 (web: https://docs.aws.amazon.com/guardduty/latest/ug/guardduty_findings-severity.html).
- **Typed fields, and what a finding says about itself.** Each reader stores typed fields, and each
  group of a finding's own detail as one JSON field in AWS's shape (aws-core-tap#264, ruling Q114c):
  GuardDuty `description`, `action` (`Service.Action`, remote addresses, ports, domains and API calls
  included; botocore marks the addresses sensitive, and they are addresses, not secrets),
  `network_interfaces` (`Resource.InstanceDetails.NetworkInterfaces`) and `evidence`
  (`Service.Evidence`); Security Hub `description`, `types`, `severity_normalized`, `remediation`,
  `network`, `malware`, `vulnerabilities`, `product_fields`, `compliance_status_reasons` and
  `finding_provider_fields`; a Config rule's `scope`, `input_parameters` (parsed from its JSON string),
  `policy_runtime` and `policy_text` (the Guard policy body). A JSON group is null when the finding
  carries none. Titles and Security Hub resource ids are stored as AWS wrote them, addresses
  included (ruling Q114b). Still not stored: the rest of the ASFF document (process, threats, resource
  details, notes), GuardDuty `Service.AdditionalInfo` and runtime detail, an Access Analyzer
  finding's condition **values** (its condition summary is the keys), and conformance-pack parameters.
  A Config rule's own `description` (operator-authored, at most 256 characters) is kept and declared
  `free_text`. Each type's declaration is in `reader_sensitivity.json`.
- **Resource keys.** `CONCERNS_RESOURCE` is emitted by the target's natural key whether or not the
  target was collected; core resolves the key to the target's row when one is live, and otherwise
  skips the edge and records a `skip` event. GuardDuty names an IAM
  user, not its ARN, so the key is built with the default path (inferred); a user under another path
  is left dangling.
- **Any resource its ARN names.** A Security Hub finding names its resources by ARN, and an account
  by the pseudo-id `AWS::::Account:<id>`; the target is whichever aws_core node that id names,
  whatever its type and however it is keyed (aws-core-tap#242, #252, #249;
  `collectors/boto3_collector/arn_resolver.py`, `req-aws-collector-identity-14`). No table of types
  is kept: the resolver reads each model's `ARN_RESOURCE` and `NATURAL_KEY` from the entity registry,
  each natively keyed type's identity declaration (`req-aws-collector-identity-13`) and the vendored
  `arn_formats.json` (`req-aws-collector-identity-11`). An ARN resolves when exactly one vendored
  format matches it most specifically (most literal characters) and that format's resource type
  belongs to one model. A type keyed by its ARN (one field named `arn`, or `<x>_arn` until
  `req-aws-collector-identity-10` renames it) is named by the ARN. A natively keyed type is named by
  the key its declaration's `arn_key` reads from the ARN: an EC2 instance, a VPC, a subnet, a security
  group, a network ACL or a volume by its id, a GuardDuty detector by `(account_id, region,
  detector_id)` with the account and region read from the ARN itself. The account pseudo-id reaches
  the account node through the account's declared `other_ids`. The ASFF `Type` plays no part, so the
  EC2 instance special case is gone. Otherwise the id stays a string in `resource_ids` and no edge is
  sent: an id nothing matches, two formats of the same shape (a Lambda alias and a version), a
  resource type several models share (`cloudwatch:alarm`, `rds:cluster-pg`, the transit gateway
  attachment types and others), a key the ARN does not carry, or a type still keyed by a string the
  collector makes. A mismatch cannot attach a finding to the wrong row, because the key sent is the
  ARN itself or what the target's own declaration reads from it; at worst it names a node not on the
  grid and core skips the edge. The
  edge type's targets are open (`edges/CONCERNS_RESOURCE.edge.json`) for the same reason. The
  resolver takes an ARN alone, so an OCSF `resources[].uid` can use it unchanged.
- **GovCloud.** Every call is to a service already in the availability table. Two are not verified
  in GovCloud: `GetFindingsStatistics` with `GroupBy` (the counts fall back) and
  `ListFindingsV2` (the analyzer's findings surface is recorded failed). A failing call is
  recorded, never read as empty.
- **Permissions.** SecurityAudit (commercial v94, web:
  https://docs.aws.amazon.com/aws-managed-policy/latest/reference/SecurityAudit.html; GovCloud's
  copy not verified) grants every read here through `guardduty:Get*`/`List*`,
  `securityhub:Get*`, `access-analyzer:ListFindings` and `config:Describe*`/`Get*`/`List*`
  (`config:GetCustomRulePolicy` included, by the `Get*` wildcard; inferred, not observed). The
  Access Analyzer finding falsifier's `access-analyzer:GetFindingV2` is not in it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-landing-zone-findings-1 | Active Findings Collected | Proposed | Each written detector, hub and analyzer has its active findings for the run's own account written under it, read with the filters tabled above and to their last page unless the operator's limits stop them (`-3`). | |
| req-aws-landing-zone-findings-9 | Recently Closed Findings Collected | Proposed | Each written detector, hub and analyzer also has the findings it closed in the last 30 days written under it, with the service's own state field saying closed (`archived`, `record_state`, `status`), read with the closed filters tabled above, after the active read; parent counts stay counts of active findings, and the surface stays never complete. | aws-core-tap#264, ruling Q115a. `tests/test_security_findings.py::TestClosedFindings`, `tests/test_findings_stubbed.py` (requests and responses validated against botocore's models). |
| req-aws-landing-zone-findings-2 | Findings Reference Their Resource | Proposed | A finding naming an EC2 instance, S3 bucket, IAM user or IAM role has `CONCERNS_RESOURCE` to it by natural key. A GuardDuty finding naming the ARN of a Lambda function, an RDS instance or Limitless shard group, an ECS cluster or task, an EKS cluster or a scanned EBS volume has `CONCERNS_RESOURCE` to the node `arn_resolver` finds for it (aws-core-tap#264, ruling Q115b); its targets are a closed list and any other type is refused. A Security Hub finding naming the ARN of any aws_core type keyed by its ARN, or of a natively keyed type whose declaration reads its key from the ARN (`req-aws-collector-identity-14`), or naming an account by `AWS::::Account:<id>`, has `CONCERNS_RESOURCE` to that node by its natural key; an id no single keyed type claims stays a string with no edge. | aws-core-tap#242, #252; closes aws-core-tap#249. `collectors/boto3_collector/arn_resolver.py`, `findings.py::_asff_target`; `tests/test_arn_resolver.py`, `tests/test_security_findings.py::TestSecurityHub::test_a_finding_concerns_whatever_aws_core_node_its_arns_name`. |
| req-aws-landing-zone-findings-3 | Read To The End Unless Trimmed, Never Complete | Proposed | A findings read runs to its last page by default; `findings_max_per_region` stops a service's reads in a region once they have written that many findings, and `findings_read_budget_seconds` stops a read that has run that long, each recorded in `reasons.truncated` with the reason; its surface records the filter with no control and is never complete. | Rulings Q125a and b (2026-11-20) replaced the fixed 1000-finding cap and the Access Analyzer 50-page bound. `tests/test_findings_stubbed.py`, `tests/test_security_findings.py`. |
| req-aws-landing-zone-findings-4 | Totals On The Parent | Proposed | The parent carries per-label counts and says whether they are exact and whether the read was truncated. | |
| req-aws-landing-zone-findings-5 | Retirement Path | Proposed | Every new type is a containment target with a registered falsifier; each parent records a surface for each of its containment edges. | |
| req-aws-landing-zone-findings-6 | Control Results And Standards | Proposed | A control finding carries its compliance status and security control id, and `EVALUATED_UNDER_STANDARD` to each enabled standard it names; enabled standards are nodes contained by the hub. | |
| req-aws-landing-zone-findings-7 | What A Finding Says Is Kept | Proposed | A finding's description, action, network detail, evidence, remediation, malware, vulnerabilities, product fields, types, normalized severity, compliance status reasons and finding-provider fields, and a Config rule's scope, input parameters and Guard policy body, reach the node as tabled; titles and resource ids keep their addresses. An Access Analyzer condition value, a conformance-pack parameter and a standards subscription's `StandardsInput` still do not: a test plants each and finds none. | Revised 2026-11-20 by rulings Q114b and Q114c (aws-core-tap#264); it read "Typed Fields Only", with addresses replaced by `[ip]`. `tests/test_security_findings.py::TestDeclarations`, `::TestSecurityHubDetail`, `::TestConfigRuleDetail`. |
| req-aws-landing-zone-findings-8 | Config Rules And Conformance Packs | Proposed | Every Config rule (service-linked included) and conformance pack is a footprint child with its compliance; a failed compliance read is null, never compliant. | |

### Inspector Findings
----
RID: `req-aws-landing-zone-inspector`

Status: `Proposed`

Requested by the maintainer on aws-core-tap#261 (reported by an outside contributor; built on the maintainer's
rulings of 2026-11-20, which this section records). It lifts the non-goal "Inspector" for **findings only**:
Amazon Inspector v2's own configuration types (`inspectorv2_filter`, `inspectorv2_connector` and the others) are
manifest entries already and are unchanged. Collect-only: nothing here arms reconcile.

Every VDR method on the grid reads `compliance_core` findings, and without a CVE id and a CVSS vector each falls
back to its worst case. For AWS workloads Inspector is the natural CVE source for EC2, ECR and Lambda. aws_core
keeps Inspector's findings **in its own format**, as typed aws_core types, and can project them into
`compliance_core` (`req-aws-landing-zone-inspector-compliance`); there is no bridge plugin.

#### Implementation

Read by the landing-zone reader for the run's own account, once per region in scope
(`collectors/boto3_collector/inspector.py`). Shapes are **read** from botocore 1.44.4's `inspector2` service
model; nothing was observed against a live account (no Inspector-enabled account was available, so the reads
are built to the model and tested with `botocore.stub.Stubber`, every request and response validated against it).

| Type | Source (read: botocore) | Key | Tags | Contained by | Falsifier: gone when | Reference edges |
| --- | --- | --- | --- | --- | --- | --- |
| `aws_inspector2_finding` **(new)** | `inspector2:ListFindings(filterCriteria: awsAccountId=<run account>, findingType=PACKAGE_VULNERABILITY, findingStatus=ACTIVE; sortCriteria: SEVERITY DESC; maxResults 100)` to its end; then the same with `findingStatus=CLOSED, updatedAt` in the last 30 days, sorted `LAST_OBSERVED_AT` DESC; then both again with `findingType=CODE_VULNERABILITY` | finding ARN | **none** (a finding is not taggable; inferred: botocore's `Finding` shape has no tag member, and `resources[].tags` are the resource's tags) | footprint, `HOSTS_INSPECTOR2_FINDING` | `ListFindings(filterCriteria: findingArn=<arn>)` names none (a CLOSED or SUPPRESSED finding is present) | `CONCERNS_RESOURCE` (→ the EC2 instance, Lambda function or ECR repository `resources[]` names, and for an ECR image the image host, below) |
| `aws_inspector2_reachability_finding` **(new)** | the same two reads with `findingType=NETWORK_REACHABILITY` | finding ARN | **none** (as above) | footprint, `HOSTS_INSPECTOR2_REACHABILITY_FINDING` | as above | the compound edge of `req-aws-landing-zone-inspector-reachability` |

- **Everything by default, trimmed by choice** (maintainer, 2026-11-20, Q124a: "collect everything by default and
  allow people to trim as necessary"). Every finding type is read: `PACKAGE_VULNERABILITY`, `CODE_VULNERABILITY`
  and `NETWORK_REACHABILITY`. The credential's `inspector_finding_types` down-selects them
  (`spec-aws-core-secrets.md`, `req-aws-core-secret-findings-settings`); absent means all three. A type left out is
  not read and its surface says so. In GovCloud the code type returns nothing, because Lambda code scanning and
  code-repository scanning are not offered there (web:
  https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-inspector2.html); an empty answer is stored as
  such, not treated as an error.
- **Read to the end, unless the operator limits it.** No fixed cap: each read runs to its last page. The shared
  findings settings of `req-aws-landing-zone-findings-3` apply here as to GuardDuty, Security Hub and Access
  Analyzer: `findings_max_per_region` caps the findings one service writes per region (Inspector's reads, active
  first and package before code before reachability, share that one budget), and `findings_read_budget_seconds`
  stops a read that runs too long. A read stopped by either records `reasons.truncated`, and the footprint's true
  totals still come from the aggregation call.
- **Never complete, and never retires.** The surfaces (`account_region.inspector2_findings`, one for the package
  and code reads, and `account_region.inspector2_reachability_findings`) depend on source-side filters (the run's
  account, the status) with no positive control, so they record `filter` verbatim, `filter_control: null` and
  `enumeration_complete: false` (`req-grid-reconcile-evidence-4`) however far the read ran, and nominate nothing.
- **True totals.** The footprint carries `inspector2_active_finding_counts`, `{finding type: {severity:
  count}}` from `ListFindingAggregations(aggregationType=FINDING_TYPE, accountIds=[<run account>],
  aggregationRequest.findingTypeAggregation.findingType=<type>)`, which counts however far the walk ran; the
  lowercase `severityCounts` members (`all`, `critical`, `high`, `medium`, `low`, `informational`, `untriaged`)
  are stored upper-cased as Inspector's own `Severity` labels, `ALL` included. `inspector2_active_finding_counts_complete`
  is true only when every aggregation call answered; `inspector2_active_findings_truncated` is true when an
  active read was stopped by the operator's limit or budget. Null means not read. That the aggregation counts ACTIVE findings only is
  inferred from the API reference, not observed.
- **Not enabled is not empty.** `BatchGetAccountStatus(accountIds=[<run account>])` gives the footprint
  `inspector2_status` (`state.status`, verbatim: `ENABLED`, `DISABLED`, `SUSPENDED`, ...) and
  `inspector2_resource_status` (`{ec2, ecr, lambda, lambdaCode, codeRepository, ami: status}` as returned). A
  failed status read is null on both. When the status is positively `DISABLED` or `SUSPENDED` no finding is
  read and both surfaces say why; any other status, or none, still reads.
- **What is stored.** Typed fields: `finding_type`, `status`, `severity`, `inspector_score`, `title`,
  `description`, `remediation` (`remediation.recommendation.text`), `remediation_url`, `first_observed_at`,
  `last_observed_at`, `updated_at`, `resource_type` and `resource_id` (the first `resources[]` entry). A
  package-vulnerability finding also keeps `vulnerability_id`, `related_vulnerabilities`,
  `vulnerability_source`, `source_url`, `vendor_severity`, `vendor_created_at`, `vendor_updated_at`,
  `reference_urls`, **every** CVSS entry (`cvss`, Inspector's list verbatim: `baseScore`, `scoringVector`,
  `version`, `source`), the environment-adjusted score (`adjusted_cvss`, `inspectorScoreDetails.adjustedCvss`
  verbatim with its adjustments), `fix_available`, `exploit_available`, `last_known_exploit_at`,
  `epss_score`, `vulnerable_packages` (each package's name, version, epoch, release, arch, package manager,
  file path, fixed-in version, remediation, source layer hash and Lambda layer ARN, verbatim) and
  `image_digest` (an ECR image's digest). A code-vulnerability finding keeps, from `codeVulnerabilityDetails`
  (read: botocore `CodeVulnerabilityDetails`, `CodeFilePath`), `cwes`, `detector_id`, `detector_name`,
  `detector_tags`, `rule_id`, `reference_urls`, `code_file_name`, `code_file_path`, `code_start_line`,
  `code_end_line` and `code_source_lambda_layer_arn`; the code snippet itself (`GetCodeSnippet`) is not read.
  **`resources[].details` is not stored**: the node the finding
  concerns already holds those facts (addresses, key names, image tags), and keeping a second copy is the
  defect add-model's 5a names. A reader that needs one transient fact from it (an image's `platform`, for
  the package ecosystem) reads it in memory and stores only what it derived.
- **The resource it concerns.** `resources[0]` names it. `AWS_EC2_INSTANCE`: the instance by the instance id
  (Inspector's `id` is the instance id, or an instance ARN whose `instance/` id is taken). `AWS_LAMBDA_FUNCTION`:
  the function by its unqualified ARN, a `:$LATEST` qualifier removed (Inspector scans `$LATEST`; any other
  qualifier names a version aws_core does not model, so no edge). `AWS_ECR_REPOSITORY`: the repository by its
  ARN. `AWS_ECR_CONTAINER_IMAGE` (`arn:…:repository/<name>/sha256:<hex>`): the repository by the ARN with the
  digest removed, **and** the image as computing_core's image host, `computing_core__host` realm `oci-digest`
  keyed by the digest, written by aws_core exactly as the ECS reader writes one (`req-aws-collector-ecs-21`): a
  host the grid already holds is sent with its key and kind only. Any other resource type gets no edge and keeps
  its id in `resource_id`. The edge is `CONCERNS_RESOURCE`, a reference, emitted by natural key whether or not
  the target was collected.
- **Lifecycle.** `status` is Inspector's own field, verbatim. A finding that closes is rewritten `CLOSED` by the
  closed read while it is inside the 30-day window. One a read did not return because the operator's limit or
  budget stopped it is left as it was last written: absence from a truncated read is never a state.
- **Not Security Hub's copy.** Inspector also sends its findings to Security Hub, and `aws_securityhub_finding`
  stores that copy's `Vulnerabilities[]` (`req-aws-landing-zone-findings-7`). Joining the two (the ASFF `Id` is
  the Inspector finding ARN) is **deferred** (maintainer, 2026-11-20): the direct read is its own read, works
  without Security Hub, and carries the adjusted score and the structured image digest. Until the join is built
  an Inspector finding that Security Hub also holds is two aws_core nodes, one per service, and only this one is
  projected into compliance_core, so nothing is counted twice there.
- **GovCloud.** `inspector2` is in both GovCloud regions with FIPS endpoints (web: the GovCloud page above);
  its row in the partition availability table says so.
- **Permissions.** `inspector2:ListFindings`, `inspector2:ListFindingAggregations` and
  `inspector2:BatchGetAccountStatus`, all in AWS-managed `SecurityAudit` (web:
  https://docs.aws.amazon.com/aws-managed-policy/latest/reference/SecurityAudit.html, v95). The generated
  custom policy set carries them (`handoff/README.md`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-landing-zone-inspector-1 | Package And Code Findings Collected | Proposed | In each region read, the run's account's ACTIVE `PACKAGE_VULNERABILITY` and `CODE_VULNERABILITY` findings, and those CLOSED in the last 30 days, are `aws_inspector2_finding` nodes keyed by finding ARN, contained by the footprint, read with the filters tabled above. | `tests/test_inspector_findings.py` (botocore Stubber). |
| req-aws-landing-zone-inspector-2 | Vulnerability Fields Kept | Proposed | A package finding keeps its vulnerability id, related ids, every CVSS entry with vector, score, version and source, the adjusted score, EPSS, exploit and fix flags, and every vulnerable package with its version, fixed-in version and file path; a code finding keeps its CWEs, detector id and name, rule id, file path and line range; `resources[].details` reaches no field. | A test plants details and finds none. |
| req-aws-landing-zone-inspector-3 | Linked To Its Resource | Proposed | A finding has `CONCERNS_RESOURCE` to the EC2 instance, Lambda function or ECR repository it names, by natural key; an ECR image finding also to the `oci-digest` image host, sent with key and kind only when the grid holds it. | |
| req-aws-landing-zone-inspector-4 | Read To The End, Totalled, Never Complete | Proposed | Each read runs to its last page unless the shared findings limit or budget stops it, and then names the truncation; its surface records the filter with no control and is never complete; the footprint carries the true active totals from `ListFindingAggregations`. | `req-aws-landing-zone-findings-3`. |
| req-aws-landing-zone-inspector-5 | Not Enabled Is Said | Proposed | The footprint carries Inspector's account and per-resource status from `BatchGetAccountStatus`; a positively disabled or suspended account reads no finding and its surfaces say why; a failed status read is null. | |
| req-aws-landing-zone-inspector-6 | Retirement Path | Proposed | Both finding types are footprint containment targets with a registered falsifier; each footprint read records a surface for each containment edge. | `req-aws-core-contained-type-triple`. |
| req-aws-landing-zone-inspector-7 | Every Type By Default | Proposed | With `inspector_finding_types` absent all three finding types are read; with it set only the named types are, and each type left out records why on its surface. | Q124a. |

### Inspector Reachability Is A Compound Edge
----
RID: `req-aws-landing-zone-inspector-reachability`

Status: `Proposed`

The first compound edge (`req-grid-edge-compound`, `tap_grid/specs/spec-grid-edge.md` § Compound Edges; tap PR
1268). A `NETWORK_REACHABILITY` finding says a port range is open from a VPC edge to an EC2 network interface
along a path. It has an identity of its own (its ARN) and a sender, a receiver and the components in between, so
the finding **is the middle node** (ruled 2026-11-20): `aws_inspector2_reachability_finding` declares

```python
COMPOUND_EDGE = {
    "source": "REACHABILITY_SOURCE__aws_core",
    "destination": "REACHABILITY_DESTINATION__aws_core",
    "carrier": None,
    "path": "TRAVERSES_COMPONENT__aws_core",
    "retires_with": ("source", "destination"),
}
```

#### Implementation

| Role | Edge | From → to | Targets |
| --- | --- | --- | --- |
| source | `REACHABILITY_SOURCE__aws_core` | entry gateway → finding | closed list: `aws_internet_gateway` (`igw_id`), `aws_ec2_vpn_gateway` (a virtual private gateway, `ec2_vpn_gateway_id`), `aws_ec2_vpc_peering_connection` (`ec2_vpc_peering_connection_id`), `aws_alb` (`lb_arn`). AWS documents the edges as "an internet gateway (including instances behind Application Load Balancers or Classic Load Balancers), a VPC peering connection, or a VPN through a virtual gateway" (web: https://docs.aws.amazon.com/inspector/latest/user/findings-types.html, read 2026-11-20) |
| destination | `REACHABILITY_DESTINATION__aws_core` | finding → `aws_ec2_network_interface` (`ec2_network_interface_id`) | the network interface, not the instance: it is what the port is open on, an instance can have several, and the instance is one `ATTACHED_TO_INSTANCE` away |
| path | `TRAVERSES_COMPONENT__aws_core` | finding → each component the path passes through | closed list: `aws_route_table` (`route_table_id`), `aws_security_group` (`group_id`), `aws_network_acl` (`network_acl_id`). Property `step`, the component's position in `networkPath.steps` (not identity) |

- **Fields.** `protocol` (`TCP`/`UDP`, verbatim), `open_port_begin`, `open_port_end`, `network_path`
  (`networkPath.steps` verbatim, in order), and the shared fields of `req-aws-landing-zone-inspector`.
- **Which component a step is.** botocore types `Step.componentType` as a plain string with no enum, and no AWS
  page found lists its values (searched 2026-11-20: the API reference, the finding-types page, Security Hub's
  `NetworkPathComponent`). So the role and target type of a step are decided from what AWS **does** document,
  never from a guessed `componentType`: the `componentId`'s AWS resource-id prefix (`igw-`, `vgw-`, `pcx-`,
  `rtb-`, `sg-`, `acl-`, `eni-`) or, for a load balancer, its `componentArn` read by `arn_resolver`. The first
  step that is a gateway is the source; the last step that is a network interface is the destination; every
  route table, security group and network ACL is on the path. `DOCUMENTED_COMPONENT_TYPES` is the table of
  `componentType` values whose meaning AWS documents, and it is **empty**: every step's `componentType` is kept
  verbatim in `network_path`, and each value not in the table is listed in `component_types_unmatched`, so the
  gap is a field, not a guess. A step whose id and ARN name no tabled type (a subnet, a VPC, an endpoint, a
  Classic Load Balancer named by its name) is listed in `unmatched_steps` with the reason and gets no edge.
  **Real `componentType` values must be captured from a live finding** and the table filled from them.
- **Retirement.** `retires_with` both ends: when the gateway or the network interface retires, by a plain
  delete or a cascade, the finding retires with it (`req-grid-edge-compound-5`). A path component's retirement
  ends only its edge (`req-grid-edge-compound-8`). History stays on (`req-grid-history-optout` is not used).
- **Port range and protocol are fields**, not `computing_core__port` nodes: a range up to 0-65535 is not a set of
  ports, and computing_core's network types have no natural key (tap#1261's answer, recorded in
  `spec-grid-edge.md`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-landing-zone-inspector-reachability-1 | The Finding Is The Middle Node | Proposed | `aws_inspector2_reachability_finding` declares the `COMPOUND_EDGE` above, which `parse_compound_edge` accepts and `tap_grid.E006` passes. | |
| req-aws-landing-zone-inspector-reachability-2 | Ends And Path From The Steps | Proposed | A finding whose path starts at a tabled gateway and ends at a network interface has one source edge from the gateway, one destination edge to the interface, and one path edge (with `step`) to each route table, security group and network ACL on it. | |
| req-aws-landing-zone-inspector-reachability-3 | Unknown Is A Field, Not A Guess | Proposed | Every `componentType` not in `DOCUMENTED_COMPONENT_TYPES` is listed in `component_types_unmatched`; a step no tabled type matches is listed in `unmatched_steps` and gets no edge. | |
| req-aws-landing-zone-inspector-reachability-4 | Retires With Either End | Proposed | Deleting the gateway or the interface retires the finding; deleting a path component does not. | tap_grid's delete walk. |

### Inspector Findings In compliance_core
----
RID: `req-aws-landing-zone-inspector-compliance`

Status: `Proposed`

An operator can turn on writing `compliance_core`'s neutral finding from the stored Inspector rows, so a VDR
method reads a CVE id and a CVSS vector instead of its worst case. It is **off by default**: the switch is
`inspector_compliance_findings` in the collector's credential data (`spec-aws-core-secrets.md`,
`req-aws-core-secret-findings-settings`).

**The cross-plugin dependency, named** (AGENTS.md, plugins are hermetic: "when a cross-plugin dependency IS
right it becomes a first-class spec concern"). aws_core declares `compliance_core` an **optional** `depends_on`
with `min_version = "0.8.13"`, and nothing more: no pyproject dependency and no import of compliance_core code
(the preboot import scan would see one). The narrow contract is the slugs it writes and reads by name:
`compliance_core__compliance_finding` (`source`, `source_key`, `name`, `summary`, `description`, `status`,
`first_detected_at`), `compliance_core__compliance_vulnerability` (`vuln_id`, `aliases`, `cvss_score`,
`cvss_vector`, `cvss_version`, `cvss_source`), `CONCERNS_COMPLIANCE_VULNERABILITY__compliance_core`
(`fixed_versions`, `fix_state`) and `CARRIES_COMPLIANCE_FINDING__compliance_core`. 0.8.13 is the floor because
it is the first release with all of them as written here: `fix_state` arrived in 0.8.8, the dimension
declarations a live-dimension core needs in 0.8.12, and one `CARRIES_COMPLIANCE_FINDING` per pair in 0.8.13,
which makes re-writing a carrier every run idempotent. Absent, compliance_core is simply not written, and every
Inspector row is still collected.

#### Implementation

- **From the stored rows, as the run's last step.** After the collection batch has imported, the projection
  reads the live `aws_inspector2_finding` rows of the run's account (not the API response) and writes one
  further GRIFT batch. So turning the option on later back-fills every row already stored, and a projection
  failure never touches the collection.
- **Readiness.** The collector's self-test fails (`INSPECTOR_COMPLIANCE_READY`, misconfigured) when the option is
  on and compliance_core is not installed, is older than 0.8.13, or lacks one of the types, fields or edges named
  above. The run makes the same check before it projects: when it fails, the AWS data is still collected and
  written, the projection is not attempted, and the run records `INSPECTOR_COMPLIANCE_PROJECTION_FAILED` as an
  error with the reason (named in the run summary). A projection batch the importer rejects is recorded the same
  way (the collection batch has already imported).
- **Identity.** `source` = `aws_inspector`; `source_key` = the Inspector finding ARN, which is stable while the
  finding lives and equals Security Hub's ASFF `Id`.
- **The neutral finding.** `name` = the title (255), `summary` = severity, vulnerability id and package names
  (500), `description` = Inspector's description, `first_detected_at` = `first_observed_at`. `status` is `open`
  for an ACTIVE row and `resolved` for a CLOSED one: a row is CLOSED only when a read in the 30-day window
  returned it CLOSED, so a finding resolves only on that positive record, never because a truncated read missed it.
- **The vulnerability.** `vuln_id` is the Inspector `vulnerabilityId` when it is a CVE id, else the first CVE
  id in `relatedVulnerabilities`, else the id as given (the grype rule). Before one is minted it is looked up
  under that id as a `vuln_id` **or an alias** of a live vulnerability; one found is linked to and keeps its
  own `vuln_id`; two found is ambiguous and that finding is not projected (a warning names it). A new one is
  created with its `aliases` = the Inspector id when it differs. **CVSS is filled only when the node has none**
  (`cvss_score` null): Inspector's entries are ranked NVD 3.x, then any other 3.x (the vendor's), then 2.x, the
  highest version first within a rank, and the chosen entry's score, vector, version and source are written.
  The full list stays on the aws_core row. Inspector's EPSS and exploit flags are **not** written: its EPSS has
  no date (`req-compliance-core-vulnerability-5` needs one) and vuln_mosaic owns EPSS and KEV. The adjusted
  Inspector score stays on the aws_core finding: it is a fact about this resource, not about the CVE. The
  fill-only rule is read-then-write: a vulnerability another writer fills between the read and the write is
  overwritten once (inferred risk, not guarded by version).
- **A code finding has no vulnerability record** (maintainer, 2026-11-20, Q124b). A `CODE_VULNERABILITY` row is
  projected as its `compliance_finding` and its carrier edge only: no `compliance_vulnerability` node and no
  `CONCERNS_COMPLIANCE_VULNERABILITY` edge. A code finding usually names a CWE and a detector rule, not a CVE, and a
  key invented for it would be a vulnerability record no other source can name.
- **The fix, on the pair.** `CONCERNS_COMPLIANCE_VULNERABILITY` carries `fixed_versions` = every vulnerable
  package's `fixedInVersion` (sorted, distinct; `[]` when none names one) and `fix_state` from `fixAvailable`:
  `YES` → `fixed`, `NO` → `not-fixed`, `PARTIAL` → `fixed` with the partial list; absent when Inspector says
  nothing.
- **The carrier.** In v1 the neutral finding is carried (`CARRIES_COMPLIANCE_FINDING`) by the aws_core resource
  node it concerns: the EC2 instance, the Lambda function, the ECR repository (for an image finding too). When the
  package chain names the finding's packages (`req-aws-landing-zone-inspector-packages`), the packages carry it
  instead (see there). A row whose resource aws_core cannot name is projected with no carrier.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-landing-zone-inspector-compliance-1 | Off By Default | Proposed | With the option absent or false, no compliance_core node or edge is written and readiness is not checked. | |
| req-aws-landing-zone-inspector-compliance-2 | Optional, Never Imported | Proposed | `depends_on` names compliance_core `optional = true`, `min_version = "0.8.13"`; pyproject names no compliance-core-tap; no module imports `tap_plugin.compliance_core`. | A test scans the package. |
| req-aws-landing-zone-inspector-compliance-3 | Readiness Fails Loud | Proposed | Self-test fails when the option is on and compliance_core is missing, too old or lacks a needed type, field or edge; at run start the same failure collects the AWS data, skips the projection and records the reason as an error. | |
| req-aws-landing-zone-inspector-compliance-4 | Projected From Stored Rows | Proposed | The projection reads stored rows, so a row collected before the option was on is projected on the first run after. | |
| req-aws-landing-zone-inspector-compliance-5 | The Neutral Shape | Proposed | Each projected package row is one `compliance_finding` (`aws_inspector`, finding ARN), a `CONCERNS_COMPLIANCE_VULNERABILITY` to the vulnerability chosen and looked up as above with `fixed_versions` and `fix_state` as mapped, and a carrier edge; a code row is the finding and its carrier edge only, with no vulnerability node or `CONCERNS` edge. | Q124b. |
| req-aws-landing-zone-inspector-compliance-6 | CVSS Only When Empty | Proposed | A vulnerability with a CVSS score keeps it; one without gets Inspector's top-ranked entry with its vector; EPSS, exploit flags and the adjusted score are never written to the vulnerability. | |
| req-aws-landing-zone-inspector-compliance-7 | Resolved Only On A Closed Read | Proposed | A neutral finding is `resolved` only when its row is CLOSED; a row a truncated read did not return stays as it was. | |

### Inspector Packages On The Image Host
----
RID: `req-aws-landing-zone-inspector-packages`

Status: `Proposed`

Deferred from v1 until aws_core's ECS containers ran their images (aws-core-tap#95: `RUNS_IMAGE__computing_core`
from `aws_ecs_container` to the `oci-digest` host, `req-aws-collector-ecs-20`), which they now do. With it,
fedramp_20x_vdr's reach Search can name an owner for an Inspector finding instead of `owner_kind: none`.

**What reach walks** (read: fedramp-20x-vdr-tap `tap_plugin/fedramp_20x_vdr/searches/reach.py`, 2026-11-20): an
open finding with a `CONCERNS_COMPLIANCE_VULNERABILITY` edge; its `CARRIES_COMPLIANCE_FINDING` carriers; for a
carrier that is a `computing_core__package`, the hosts that `INSTALLS_PACKAGE` it; for each host, the nodes that
`RUNS_IMAGE` it (the containers); then each container's `RUNS_PROGRAM` closure. Any other carrier yields one row
with no owner. So the chain aws_core writes is exactly: image host `INSTALLS_PACKAGE` package, and package
`CARRIES_COMPLIANCE_FINDING` finding; the ECS reader already writes the container's `RUNS_IMAGE`.

#### Implementation

- **The package.** For an ECR image finding, each vulnerable package becomes a `computing_core__package` keyed
  `(ecosystem, name, version)` exactly as computing_core's SBOM parser keys one (`classify_component`: the purl
  type, the component name, the component version), so Inspector, grype and anchore name one node: grype and
  anchore both take their packages from that parser. `ecosystem` comes from `packageManager`: `NPM`, `YARN`,
  `NODEPKG` → `npm`; `PIP`, `PIPENV`, `POETRY`, `PYTHONPKG` → `pypi`; `BUNDLER`, `GEMSPEC` → `gem`; `CARGO` →
  `cargo`; `NUGET`, `DOTNET_CORE` → `nuget`; `GOBINARY`, `GOMOD` → `golang`; `OS` → the image's distribution
  family read from its transient `platform` (`AMAZON_LINUX*`, `RHEL*`, `CENTOS*`, `ORACLE*`, `ALMA*`, `ROCKY*`,
  `FEDORA*`, `SUSE*`, `SLES*`, `OPENSUSE*` → `rpm`; `DEBIAN*`, `UBUNTU*` → `deb`; `ALPINE*` → `apk`).
  `version` is `version` for a language package and, for an OS package, `version-release` with `epoch:`
  prefixed when the epoch is above zero (inferred to be Syft's form for rpm, dpkg and apk versions; to be checked against a live finding and an SBOM of the same image). `JAR`, `POM` and
  `COMPOSER` are **not mapped**: Syft names a Maven component by its artifact id and Inspector by
  `group:artifact`, and composer is not a package type the parser keeps, so a node would join nothing. Every
  vulnerable package is listed in the row's `package_identities` with the key it got, or `null` and the reason
  it got none. The `platform` strings are free text in botocore: the prefixes are inferred from Inspector's
  documented supported operating systems and must be checked against live findings.
- **Only key fields are sent.** A package envelope carries `ecosystem`, `name` and `version`, nothing else, so a
  purl, licence or architecture an SBOM writer stored is left as it was (the importer's keep-absent upsert).
- **The host.** The image host the finding already concerns (`req-aws-landing-zone-inspector-3`) `INSTALLS_PACKAGE`
  each package. EC2 and Lambda findings get no package chain: aws_core writes no computing_core host for an
  instance or a function, and minting one here would be a second identity for a machine aws_core already
  models.
- **The carrier.** When the projection is on, an image finding whose packages got keys is carried by those
  packages (`CARRIES_COMPLIANCE_FINDING` from each), **instead of** the repository: reach reads every carrier,
  and a second carrier that is not a package would add a row with no owner beside the owned ones. An image
  finding whose packages all failed to key keeps the repository as carrier. A carrier edge an earlier run wrote
  from the repository is not retired by this run (pre-users: a reload clears it).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-landing-zone-inspector-packages-1 | Image Host Installs Its Packages | Proposed | Each vulnerable package of an ECR image finding with a mapped ecosystem is a `computing_core__package` keyed as the SBOM parser keys it, sent with its key only, with `INSTALLS_PACKAGE` from the image host. | |
| req-aws-landing-zone-inspector-packages-2 | Unmapped Is Said | Proposed | A package with no mapped ecosystem gets no node, and `package_identities` gives the reason. | |
| req-aws-landing-zone-inspector-packages-3 | Packages Carry The Finding | Proposed | With the projection on, an image finding whose packages got keys is carried by them and not by the repository; reach resolves it through `INSTALLS_PACKAGE` and `RUNS_IMAGE` to the containers running the image. | `tests/test_inspector_compliance.py`. |

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
- **Old closed findings, and writing back.** Config rules, conformance packs, active findings and
  findings closed in the last 30 days are collected (`req-aws-landing-zone-findings`, aws-core-tap#76,
  #264). Findings closed before that window are not read. A Security Hub finding whose record is
  ACTIVE but whose workflow is RESOLVED or SUPPRESSED is read with the active ones, with
  `workflow_status` saying so: the workflow is an operator's triage state, not the record's. Nothing
  updates a finding's workflow or archives it. Member accounts' findings (Q115c) wait on fan-out.
- **Detective.** No Gruntwork baseline read enables it (not found in the module reference pages). Inspector's
  findings were a non-goal on the same ground until aws-core-tap#261 lifted it (`req-aws-landing-zone-inspector`).
- **Security Hub's copy of Inspector's findings.** Joining an `aws_securityhub_finding` whose `ProductName` is
  Inspector to the `aws_inspector2_finding` with the same ARN, and projecting only one of them, is deferred
  (maintainer, 2026-11-20; `req-aws-landing-zone-inspector`, *Not Security Hub's copy*).

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
