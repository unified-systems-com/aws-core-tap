# AWS Core Plugin Specification

## Philosophy

The AWS Core plugin provides the foundational resource-type models needed to represent a modern AWS cloud application inside TAP's graph. The plugin favors granularity over abstraction — each AWS resource type that matters for security, compliance, or operations is its own model with typed fields, rather than a generic "cloud resource" blob. This makes the graph queryable, the edges meaningful, and the visualization useful.

The plugin deliberately models resource types, not the AWS service catalog itself. EC2 Instance, S3 Bucket, and VPC are resource types that exist in a running AWS account. "Amazon EC2" as a product page on aws.amazon.com is not modeled — it has no state to track and no edges to traverse.

v0 is intentionally scoped to the "meat and potatoes" AWS resources common to most major infrastructures. The plugin is designed to grow as new resource types prove necessary, with a catalog refresh skill that can detect and propose additions.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Granular      | Each resource type is its own model with typed fields and a configuration JSONField for full metadata |
| 2. | Queryable     | Key fields (instance IDs, ARNs, states) are indexed Django fields, not buried in JSON |
| 3. | Connected     | Semantically meaningful edge types express security, operational, and structural relationships |
| 4. | Refreshable   | Reference data (regions, AZs) is maintained by an automated catalog refresh skill |
| 5. | Portable      | The plugin lives in its own git repo and integrates into TAP as a git submodule |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-aws-core-scope | [Plugin Scope](#plugin-scope) | Implemented | Defines what the plugin covers and excludes |
| req-aws-core-models | [Resource-Type Models](#resource-type-models) | Implemented | Typed resource-type models; manifest is the canonical inventory |
| req-aws-core-fields | [Field Design](#field-design) | Implemented | Hybrid typed fields + configuration JSONField |
| req-aws-core-edges | [Edge Types](#edge-types) | Implemented | Semantic edge vocabulary; manifest is the canonical inventory |
| req-aws-core-reference | [Reference Data](#reference-data) | Implemented | Regions and AZs as GRIFT seed data |
| req-aws-core-icons | [Icon Assets](#icon-assets) | Implemented | SVG icons per the TAP grid icon spec |
| req-aws-core-computing-core | [Computing Core Alignment](#computing-core-alignment) | Proposed | Future AWS-to-generic mapping belongs here rather than in `computing_core` |
| req-aws-core-validation | [Plugin Validation](#plugin-validation) | Implemented | Passes TAP plugin validation at all three levels |
| req-aws-core-organizations | [Organizations Tree](#organizations-tree) | Implemented | Organization (as its own root), OU and SCP design vocabulary; the tree and SCP attachment edges |
| req-aws-core-organizations-collect | [Organizations Tree Collection And Reconciliation](#organizations-tree-collection-and-reconciliation) | Implemented | A collector for the Organizations tree; two new parent -> child containment edges with completeness surfaces; `OrganizationalUnitFalsifier` / `AccountFalsifier` |
| req-aws-core-identity-center | [IAM Identity Center](#iam-identity-center) | Implemented | Identity Center instance design vocabulary and its open edge to an external identity provider |
| req-aws-core-transit-gateway | [Transit Gateway](#transit-gateway) | Implemented | Transit gateway and attachment design vocabulary; attachment, VPC and peering edges |
| req-aws-core-placement | [Resource Placement](#resource-placement) | Implemented | Account, VPC and subnet placement edges; a VPC contains its subnets |
| req-aws-core-direct-connect | [Direct Connect](#direct-connect) | Implemented | Connection, DX gateway and virtual interface design vocabulary; the TGW association reuses the attachment |
| req-aws-core-privatelink | [PrivateLink](#privatelink) | Implemented | Endpoint service and VPC endpoint design vocabulary |
| req-aws-core-dns-firewall | [Route 53 Resolver DNS Firewall](#route-53-resolver-dns-firewall) | Implemented | Rule group with typed domain-list summary; VPC association edge |
| req-aws-core-private-ca | [ACM Private CA](#acm-private-ca) | Implemented | Private CA design vocabulary and the issuer edge |
| req-aws-core-page-dashboard | [AWS Pages](#aws-pages) | Implemented | `/aws`: count tiles, the estate as one picture, accounts per OU, boundary scope |
| req-aws-core-page-organization | [AWS Pages](#aws-pages) | Implemented | `/aws/organization`: the OU tree as nested boxes, SCP attachments, account placement |
| req-aws-core-page-network | [AWS Pages](#aws-pages) | Implemented | `/aws/network`: transit gateways, attachments, VPCs around their subnets, gateways, firewalls, Direct Connect |
| req-aws-core-panel-counts | [AWS Pages](#aws-pages) | Implemented | The `aws-counts` panel type: count tiles over the estate |
| req-aws-core-layout-hints | [AWS Pages](#aws-pages) | Implemented | Placement read from a node's own `layout:*` tags, never its name or id |
| req-aws-core-nongoals | [v0 Non-Goals](#v0-non-goals) | Proposed | Explicitly deferred concerns |
| req-aws-core-reconcile-falsifiers | [Reconciliation Foundation — Falsifiers](#reconciliation-foundation--falsifiers) | Amended | `[falsifiers]` manifest table, base `_AwsFalsifier`, `SubnetFalsifier`; account/org's original "excluded by design" is narrowed — `AwsAccount` now has both a falsifier and containment, see the rows below |
| req-aws-core-reconcile-containment | [Account-Scoped Containment — IAM & S3 Reconcile](#account-scoped-containment--iam--s3-reconcile) | Implemented | Five NEW `AwsAccount` → owned-type containment edges (IAM role/user/policy, OIDC provider, S3 bucket); `IamOidcProviderFalsifier`; collector-emitted completeness per listing |
| req-aws-core-regional-containment | [Region-Scoped Containment](#region-scoped-containment) | Implemented | `aws_account_region` (account × region footprint), `HOSTS_*` containment edges, per-region completeness surfaces; VPC, subnet, EC2 instance, security group |
| req-aws-core-organization-membership | [Organization Membership](#organization-membership) | Proposed | An account leaving the organization ends its membership, never the account: `aws_organization_membership` contained by the organization, `ENROLLS_ACCOUNT` re-sourced as a reference, `MembershipFalsifier` replaces `AccountFalsifier` (ruling 2026-09-30) |
| req-aws-core-organizations-completeness | [Organizations Completeness](#organizations-completeness) | Proposed | Root tags, enabled policy types, enabled service access, delegated administration, the other GovCloud-allowed policy types, a retirement path for policies; SCP and RCP statements and tag-policy rules as contained nodes |
| req-aws-core-network-plane | [Network Plane Collection](#network-plane-collection) | Proposed | Route tables + routes, IGW, NAT, EIP, NACLs + entries, SG rules, VPC endpoints, flow logs, ENIs, TGW + attachments + route tables + routes, peering, Route 53 Resolver; each with tags lane and retirement path |
| req-aws-core-account-footprint | [Account Owns Its Region Footprints](#account-owns-its-region-footprints) | Proposed | `OWNS_REGION_FOOTPRINT` account → footprint containment; a never-drop `FootprintFalsifier` |
| req-aws-core-contained-type-triple | [Every Contained Type Has Its Three Parts](#every-contained-type-has-its-three-parts) | Proposed | Every (parent, edge type) the epic adds has containment, a completeness surface and a falsifier; empty parents are complete-empty; unfinished listings are incomplete |
| req-aws-core-reference-derivation | [Reference Edges Declare What They Derive From](#reference-edges-declare-what-they-derive-from) | Proposed | Every emitted reference edge names its source payload, ready for core edge re-derivation; last-seen edges listed |
| req-aws-core-partition-pairing | [Account Partition And GovCloud Pairing](#account-partition-and-govcloud-pairing) | Proposed | `AwsAccount.partition`; `PAIRED_WITH_ACCOUNT` GovCloud → commercial, declared (not discoverable from the GovCloud side); no vending model (ruling 2026-09-30) |

### Plugin Scope
----
RID: `req-aws-core-scope`

Status: `Implemented`

The AWS Core plugin models the resource types needed to represent a running AWS cloud environment.

#### Implementation

The plugin covers:

- compute resources (EC2, Lambda, ECS, EKS)
- container infrastructure (ECR)
- storage (S3, EBS)
- databases (RDS, DynamoDB, ElastiCache, Elasticsearch/OpenSearch)
- networking (VPC, Subnet, Security Group, Network ACL, Internet Gateway, NAT Gateway, Elastic IP, Route Table, ALB, ELB, Target Group, Route 53, Network Firewall, Transit Gateway, Transit Gateway Attachment, Direct Connect connection / gateway / virtual interface, VPC endpoint and endpoint service, Route 53 Resolver DNS Firewall rule group)
- identity and access (IAM User, IAM Role, IAM Policy, IAM OIDC Provider, IAM Identity Center instance)
- organization structure (Organization, Organizational Unit, Service Control Policy)
- security and configuration (ACM Certificate, ACM Private CA, Secrets Manager, SSM Parameter Store)
- AI services (Bedrock, SageMaker)
- infrastructure reference (Region, Availability Zone, Account)

The plugin excludes GovCloud and China partition regions from its reference data.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-scope-1 | Resource Type Granularity | Implemented | Each AWS resource type is modeled as its own TAP model, not a generic cloud resource. | |
| req-aws-core-scope-2 | Commercial Regions Only | Implemented | Reference data covers standard commercial AWS regions; GovCloud and China partitions are excluded. | |
| req-aws-core-scope-3 | Common Infrastructure Focus | Implemented | v0 covers resource types common to most major AWS deployments. | |

#### Future

Expand to include additional services as they prove necessary for security, compliance, or operations use cases. CloudFront, WAF, CloudWatch, SNS/SQS, Step Functions, and API Gateway are likely candidates. The catalog refresh skill should detect and propose additions.

### Resource-Type Models
----
RID: `req-aws-core-models`

Status: `Implemented`

The plugin declares TAP-managed resource-type models organized by category. The
plugin manifest (`tap-plugin.toml`) is the authoritative inventory and
`validate_plugin` enforces that every declared model loads and creates — the
spec documents the categories, not a frozen count (a count is derived state that
drifts on every model added; the manifest + validator own "which models exist").

#### Implementation

| Category | Models |
| --- | --- |
| Infrastructure | AwsRegion, AvailabilityZone, AwsAccount |
| Organization | AwsOrganization, AwsOrganizationalUnit, AwsServiceControlPolicy |
| Compute | Ec2Instance, LambdaFunction, EcsCluster, EcsService, EcsTask, EksCluster |
| Containers | EcrRepository |
| Storage | S3Bucket, EbsVolume |
| Database | RdsInstance, DynamoDbTable, ElasticsearchDomain, ElasticacheCluster |
| Networking | Vpc, Subnet, SecurityGroup, NetworkAcl, InternetGateway, NatGateway, ElasticIp, RouteTable, Alb, Elb, TargetGroup, Route53HostedZone, NetworkFirewall, CloudfrontDistribution, TransitGateway, TransitGatewayAttachment, DxConnection, DxGateway, DxVirtualInterface, VpcEndpointService, VpcEndpoint, Route53ResolverFirewallRuleGroup |
| Identity/Security | IamUser, IamRole, IamPolicy, AcmCertificate, SecretsManagerSecret, SsmParameter, AwsIdentityCenterInstance, AcmPrivateCa |
| AI | BedrockModel, SagemakerEndpoint |
| Observability | CloudwatchLogGroup |
| Integration | EventbridgeRule |

All models follow the TAP BaseModel contract with `ENTITY_TYPE`, `ENTITY_NAME`, `ENTITY_DESCRIPTION`, `ENTITY_ICON`, `FIELD_CRUD_SCHEMA`, `FIELD_VALIDATION_SCHEMA`, and `CREATE_REQUIRED`.

#### Known Constraints

The Django field name `instance_type` collides with `django-simple-history`'s `HistoricalRecord.instance_type` internal attribute. Models that would naturally use `instance_type` must use an alternative name:

- `Ec2Instance` uses `ec2_type`
- `ElasticsearchDomain` uses `node_type`
- `SagemakerEndpoint` uses `endpoint_instance_type`

This is a django-simple-history limitation, not a TAP design choice. The collision was detected by the plugin validation system's `runs` level.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-models-1 | Manifest-Canonical Inventory | Implemented | Models are declared in `tap-plugin.toml` and enforced by `validate_plugin` (every declared model loads and `create_node` succeeds). The spec documents categories, not a frozen count. | Replaces the prior "N models declared" census — derived state that drifted on every add. |
| req-aws-core-models-2 | BaseModel Contract | Implemented | All models follow TAP's BaseModel contract. | |
| req-aws-core-models-3 | History Tracking | Implemented | All models inherit automatic history tracking via django-simple-history. | |
| req-aws-core-models-4 | Collector Demo Models | Implemented | CloudfrontDistribution, CloudwatchLogGroup, EventbridgeRule added for the boto3 collector demo (see `spec-aws-core-collector-v0.md` req-aws-collector-model-deps). | Migration 0002; validate_plugin `runs` PASS; aws_core suite 15/15. |

#### Future

New models should be added through the catalog refresh skill when new AWS resource types become relevant to security, compliance, or operations tracking.

### Field Design
----
RID: `req-aws-core-fields`

Status: `Implemented`

Each model uses a hybrid approach: key typed fields for queryable data, plus a `configuration` JSONField for the full metadata payload.

#### Implementation

Every AWS resource model has:

- **Key typed fields** — the most important attributes for querying, filtering, and display. These are indexed Django fields (CharField, IntegerField, BooleanField, GenericIPAddressField). Examples: `instance_id`, `vpc_id`, `engine`, `status`, `encrypted`.
- **`configuration` JSONField** — holds the complete resource configuration as received from AWS plus whatever does not fit a typed field (hydrate posture, `custom_fn` additions, `_source` provenance), so the graph carries full metadata without a schema change for every new attribute AWS adds; the raw responses in it are also future audit evidence, so its contents are never masked or redacted. Whether the collector persists it is decided per resource type by the collection manifest's `persist_configuration` flag and its `persist_configuration_why` reason (decided 2026-09-23; `spec-aws-core-collector-v0.md` `req-aws-collector-field-projection-7`). Lambda, CloudFront distribution, API Gateway HTTP API and Cognito user pool are off because their responses carry credentials, and those nodes carry `{}`; every other collected type persists it. A type whose response has not been reviewed for sensitive values is never persisted (`req-aws-collector-manifest-7`). The field stays on every model with no migration.
- **Security facts kept where configuration is off** — for the types whose configuration is not stored, three security facts are typed fields instead (`spec-aws-core-collector-v0.md` `req-aws-collector-field-projection-8`): Lambda `vpc_subnet_ids` and `vpc_security_group_ids` (both empty means not in a VPC), CloudFront distribution `origin_access` (each origin's `oac`, `oai` or `none`, where `none` means no OAC or OAI, not necessarily public) and `origin_custom_headers_present` (whether each origin is sent any custom header: presence only, the header value and name are never stored), and API Gateway HTTP API `route_authorization_types` (each route's `NONE`, `AWS_IAM`, `JWT` or `CUSTOM`, the last being a Lambda authorizer).
- **`tags` JSONField** — the resource's AWS tags as a canonical flat `{str: str}` map, with the **same field name and shape on every `aws_core` model** so a cross-resource tag query ("everything `Owner=X` across `aws_*`") works by convention. Default `dict`, blank; populated by the collector (`spec-aws-core-collector-v0.md` `req-aws-collector-tags`), which normalizes AWS's varied tag wire shapes. It is deliberately **not** an Entity-spine facet — `dimensions` is the spine's key/value system and owns scoping; AWS tags are mutable source-owned descriptive metadata and must never re-partition the grid. v0 implements the field on the 8 manifest-collected models; rolling it onto the remaining uncollected models is a tracked mechanical follow-up (the contract is family-wide; the v0 *implementation* is scoped to what the collector populates).
- **`name` field** — human-readable name, typically from the AWS Name tag or resource display name.
- **Identity** — every model declares `NATURAL_KEY` (`req-grid-entity-natural-key`): the AWS identifier that stays stable across renames — the ARN where the model carries one, otherwise the AWS-assigned resource ID (`vpc-…`, `subnet-…`, `sg-…`, `i-…`, `vol-…`, `igw-…`, `nat-…`, `acl-…`, `rtb-…`, `eipalloc-…`). AWS does not document those IDs as unique across accounts and regions; if two ever clashed, the generated search raises `AmbiguousIdentity` rather than merging, and a blank key is "not found", never a match (`req-grid-entity-natural-key-12`). Where the boto3 collector already collects a type, the key is the field its manifest `natural_key` projects to, so the model and the collector name the same fact. Owner-chosen names are never the key where AWS offers better: RDS instances and ElastiCache clusters carry `db_instance_arn` / `cluster_arn` columns for that reason. Two exceptions are stated where they are declared: a Classic Load Balancer has no ARN and keys on its assigned DNS name; a CloudWatch log group keys on its name because that is the collector's identity today (unique only within an account and region; moving the collector to the ARN changes entity ids and is its own change).
- **Null is not observed** — a structured field a collector fills (Lambda `vpc_subnet_ids` / `vpc_security_group_ids`, CloudFront `origin_access`) defaults to null, never `[]` or `{}`: null means not observed, and an empty value is an observation (the collector writes `[]` for a function outside a VPC). Rows written before migration `0011` keep their stored value.

The `FIELD_CRUD_SCHEMA` (service layer) and `FIELD_VALIDATION_SCHEMA` (validation layer with `validation`/`schema` wrappers) both declare every field. Nullable fields use `{"type": ["integer", "null"]}` or `{"type": ["string", "null"]}`.

`CREATE_REQUIRED` is set to the minimum fields that meaningfully identify a resource — typically the AWS resource ID (e.g. `instance_id`, `vpc_id`) or `name`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-fields-1 | Hybrid Field Approach | Implemented | Key typed fields for queries plus a configuration JSONField for full metadata. The collector persists it per resource type, as the collection manifest's `persist_configuration` declares; types whose raw response carries credentials, or whose response is unreviewed, store `{}`. | No masking, because masked evidence is not evidence; per-entry flag (`req-aws-collector-field-projection-7`); sensitive locations tracked in the manifest (`req-aws-collector-manifest-6`); unreviewed is not stored (`req-aws-collector-manifest-7`). |
| req-aws-core-fields-2 | Dual Schema Declaration | Implemented | Both FIELD_CRUD_SCHEMA and FIELD_VALIDATION_SCHEMA are declared on every model. | |
| req-aws-core-fields-3 | Nullable Fields Correct | Implemented | Fields using `null=True` on the Django model declare nullable types in their schemas. | |
| req-aws-core-fields-4 | Canonical Tags Field | In Development | Every `aws_core` resource model declares a `tags` JSONField — canonical flat `{str:str}`, default empty, uniform name+shape across the family; collector-populated; never an Entity-spine facet. | 2026-05-19: implemented for the 8 manifest-collected models (migration 0003); the remaining ~32 uncollected models are a tracked mechanical rollout (no behavior change) — board follow-up. |
| req-aws-core-fields-5 | Off-Type Security Facts | Implemented | Lambda `vpc_subnet_ids` / `vpc_security_group_ids`, CloudFront distribution `origin_access` and API Gateway HTTP API `route_authorization_types` are typed fields with item-level schemas, so these facts survive configuration not being stored for those types. | Migration 0007 (additive `AddField` only). See `req-aws-collector-field-projection-8`. |
| req-aws-core-fields-6 | CloudFront Origin Header Presence | Implemented | CloudFront distribution `origin_custom_headers_present` is `{origin Id: bool}` with an item-level boolean schema, nullable only for rows not yet re-collected; it records whether each origin is sent a custom header and never the header's value or name. | Migration 0008 (additive `AddField` only). See `req-aws-collector-field-projection-9`. |
| req-aws-core-fields-7 | Every Type Declares Its Identity | Implemented | Every `aws_core` model declares a `NATURAL_KEY` whose fields are model fields; where the boto3 manifest collects the type, the key is the field its `natural_key` path projects to. | `tests/test_natural_keys.py` |
| req-aws-core-fields-8 | Unobserved Is Null | Implemented | Lambda `vpc_subnet_ids` / `vpc_security_group_ids` and CloudFront `origin_access` default to null and their schemas accept null. Migration 0011. | `tests/test_natural_keys.py` |

#### Future

Consider adding `"default"` values to `FIELD_CRUD_SCHEMA` entries to support a "create with just a name" workflow. This is a TAP-wide discussion, not plugin-specific.

### Edge Types
----
RID: `req-aws-core-edges`

Status: `Implemented`

The plugin declares a semantic edge vocabulary organized by relationship
category. The plugin manifest (`tap-plugin.toml`) is the authoritative inventory
and `validate_plugin` enforces that every declared edge loads and `create_edge`
succeeds for constrained types — the spec documents the categories and the
naming convention, not a frozen count (a count is derived state that drifted on
every edge added; the manifest + validator own "which edges exist").

#### Implementation

Edge slugs follow the consolidated naming convention canonical in
`tap_grid/skills/add-edge/SKILL.md`: mechanical-not-philosophical;
`<ACTION>_<OBJECT>`; the edge points in the direction of action initiation;
`_TO` is never used (forward is unmarked); `_FROM` is reserved for a
data-backwards edge (data flows opposite the action/edge direction); and
locative/relational prepositions (e.g. `FEDERATES_INTO_ROLE`) keep their inherent
preposition. Lineage: `e5229d4` renamed terse predicates to explicit
`<ACTION>_<OBJECT>` forms; the subsequent refinement dropped redundant `_TO` and
reserved `_FROM` for data-reversal.

**Dead-edge prune (pre-eviction, 2026-07-08).** The vocabulary previously declared
~23 edge types, but only the ones the collector actually emits (or the region seed
creates) carried any data. 15 defined-but-never-emitted edge types were deleted
rather than frozen into the release tag as speculative surface (an AI-legibility trap:
the schema implied aws_core modeled containment/attachment/protection when it modeled
none). Specific edges will be re-introduced — correctly named per the add-edge skill —
when a collector rule actually emits them. The generic `CONTAINS` edge (region→AZ seed)
was replaced by the specific `DIVIDED_INTO_AZ` (region → az, parent→child).

The categories (representative; the manifest is the canonical, enforced list):

| Category | Edge Types | Description |
| --- | --- | --- |
| Structural | DIVIDED_INTO_AZ, NESTED_UNDER_PARENT, BELONGS_TO_ACCOUNT, RESIDES_IN_VPC, PARTITIONED_INTO_SUBNET, RESIDES_IN_SUBNET, ATTACHED_TO_VPC, RESIDES_IN_AZ | Region → availability zone reference topology (parent→child); the Organizations tree (child→parent) |
| Network attachment | ATTACHED_TO_TRANSIT_GATEWAY, ATTACHES_VPC, PEERS_WITH_TRANSIT_GATEWAY, ATTACHES_DX_GATEWAY, CARRIED_ON_CONNECTION, ATTACHED_TO_DX_GATEWAY, TERMINATES_AT_CUSTOMER_DEVICE, CONSUMES_ENDPOINT_SERVICE | Transit gateway attachments, Direct Connect, and PrivateLink |
| Operational | INVOKES_LAMBDA, ROUTES_TRAFFIC, WRITES_LOGS, RETRIEVES_CONTENT_FROM, RETRIEVES_CERT_FROM | Runtime actions, traffic, and data retrieval (`_FROM` = data-backwards) |
| Access/Security | ASSUMES_ROLE, FEDERATES_INTO_ROLE, ATTACHED_TO_TARGET, TRUSTS_IDENTITY_SOURCE, FILTERS_VPC_DNS, ISSUED_BY_CA | IAM role assumption and federated identity; SCP attachment; Identity Center's external identity provider |

Edge types use explicit `sources` and `targets` constraints where the relationship is well-defined (e.g. `ASSUMES_ROLE` from IAM users/roles, Lambda functions, and EventBridge rules to IAM roles; `RETRIEVES_CONTENT_FROM` from CloudFront distributions to S3 buckets). Where one end is genuinely open, only the other is constrained (e.g. `INVOKES_LAMBDA` fixes its target to `aws_lambda` and leaves the source open).

Several edge types declare `property_schema` for structured edge metadata (e.g. `ROUTES_TRAFFIC` has optional `destination_cidr` and `port`; `INVOKES_LAMBDA` has an optional `method`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-edges-1 | Manifest-Canonical Inventory | Implemented | Edge types are declared in `tap-plugin.toml` and enforced by `validate_plugin` (every declared edge loads; `create_edge` succeeds for constrained types). The spec documents categories + convention, not a frozen count. | Replaces the prior "N edge types" census — derived state that drifted on every add. |
| req-aws-core-edges-2 | Constrained Where Appropriate | Implemented | Edge types with well-defined relationships use explicit source/target constraints. | |
| req-aws-core-edges-3 | Property Schemas | Implemented | Edge types that carry structured metadata declare property_schema. | |
| req-aws-core-edges-4 | Naming Convention | Implemented | Edge slugs follow the convention canonical in `tap_grid/skills/add-edge/SKILL.md` (mechanical; `<ACTION>_<OBJECT>`; action-direction; `_TO` never; `_FROM` = data-backwards; locative carve-out). | |

#### Open Questions

**Compliance-boundary membership needs a real design (revisit — 2026-08-10).** Today
every `aws_account` node is auto-enrolled in the compliance boundary: samsite's
compliance collector synthesizes `SCOPED_TO_COMPLIANCE_BOUNDARY__compliance_core`
edges from the presence of `aws_account` nodes, carrying
`properties.kludge = "all-aws-accounts-auto-in-boundary-v0"` — a self-confessed
placeholder rule. That field is being schema'd **as-is** (per the mandatory
edge-property-schema work in core's `spec-grid-edge.md`,
`req-grid-edge-schema-required`) so the v0 behavior is at least typed and honest.
The open design questions before renaming it to a real `membership_rule`:
which accounts belong to which boundary (all-in is only right for single-account
deployments); who declares membership (operator boot-profile config, account
tags/OU structure pulled by the collector, or explicit grid authoring); and where
the rule lives (aws_core owns account semantics, compliance_core owns the boundary
vocabulary, consumers like samsite currently hard-code the synthesis). Resolve the
design first; the field rename rides it.

**Generic vs. specific edge types (resolved toward specific).** The vocabulary
formerly carried broad generic edges (`ATTACHED_TO`, `DEPENDS_ON`, `CONTAINS`,
`RESIDES_IN`, `PROTECTS`) meant to be reusable across resource types. In practice none
of them were ever emitted, and a generic edge conflates unrelated relationships (one
`ATTACHED_TO` bundled EBS↔EC2, policy↔role, EIP↔instance). The pre-eviction prune
resolved the trade-off toward **specific**: delete the unused generics, and add a
precise `<ACTION>_<OBJECT>` edge (per the add-edge skill) when a collector actually
emits that relationship. Generalized "what is inside what" is deferred to reified paths
over specific edges (`docs/misc/grid-native-paths-notes.md`), not a generic containment edge.

#### Future

CloudWatch logging (`WRITES_LOGS`) and the CloudFront retrieval edges landed with the boto3 collector demo set. Additional edge types will emerge for cross-account trust, VPC peering, and Transit Gateway connectivity. The deferred policy-document edge resolver (`spec-aws-core-collector-v0.md` req-aws-collector-nongoals) will add IAM/resource-policy-derived access edges as a post-ingestion pass.

### Reference Data
----
RID: `req-aws-core-reference`

Status: `Implemented`

Regions and availability zones are seeded as GRIFT data with `DIVIDED_INTO_AZ` edges
(region → az, parent→child; formerly the generic `CONTAINS`, replaced in the
pre-eviction edge prune).

#### Implementation

The `grift/regions.grift.json` file contains:

- 34 commercial AWS regions with region code, display name, and geographic area
- 108 availability zones with zone name and zone ID
- 108 DIVIDED_INTO_AZ edges linking each region to its AZs

Entity IDs use deterministic UUID ranges so that repeated GRIFT imports (upsert mode) update existing entities rather than creating duplicates:

- Regions: `01965b00-1000-7000-8000-*`
- AZs: `01965b00-2000-7000-8000-*`
- Edges: `01965b00-3000-7000-8000-*`

Data source: AWS official documentation at `docs.aws.amazon.com/global-infrastructure/latest/regions/`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-reference-1 | Commercial Regions Complete | Implemented | All standard commercial AWS regions are represented. | |
| req-aws-core-reference-2 | AZs Per Region | Implemented | All availability zones per region are represented with zone IDs. | |
| req-aws-core-reference-3 | DIVIDED_INTO_AZ Edges | Implemented | Every AZ has a DIVIDED_INTO_AZ edge from its parent region (region → az). | |
| req-aws-core-reference-4 | Deterministic IDs | Implemented | Entity IDs are deterministic for GRIFT upsert compatibility. | |
| req-aws-core-reference-5 | Schema Validated | Implemented | GRIFT file validates against `tap_grid/schemas/grift-document.schema.json`. | |

#### Future

Add Local Zones and Wavelength Zones when they become relevant for the compliance/operations use cases.

### Icon Assets
----
RID: `req-aws-core-icons`

Status: `Implemented`

Every model type has a corresponding SVG icon per the TAP grid icon specification.

#### Implementation

32 unique SVG icons live at `static/aws_core/icons/`. Icon keys use kebab-case (e.g. `aws-ec2`, `aws-vpc`). Several models share icon keys where the AWS service is the same:

- `aws-ecs` — EcsCluster, EcsService, EcsTask
- `aws-iam` — IamUser, IamRole, IamPolicy
- `aws-vpc` — Vpc, Subnet

Icons follow the TAP icon contract: 24x24 viewBox, `currentColor` fill, `aria-hidden="true"`, SVG format only. The plugin validation system's `loads` level verifies that every declared `ENTITY_ICON` resolves to an existing SVG file.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-icons-1 | All Models Have Icons | Implemented | Every model declares ENTITY_ICON and the corresponding SVG exists. | |
| req-aws-core-icons-2 | TAP Icon Contract | Implemented | Icons follow the TAP grid icon specification (kebab-case, SVG, currentColor). | |
| req-aws-core-icons-3 | Validation Enforced | Implemented | Plugin validation at loads level checks icon key format and file existence. | |

#### Future

Replace placeholder icons with proper AWS Architecture Icons simplified to TAP's 24x24 single-color convention. The catalog refresh skill should handle icon updates.

### Computing Core Alignment
----
RID: `req-aws-core-computing-core`

Status: `Proposed`

Future alignment between AWS-native resource types and generic computing primitives is the responsibility of `aws_core`, not `computing_core`.

#### Implementation

`computing_core` defines the lower generic substrate. When TAP is ready to model cross-plugin relationships and dependencies, `aws_core` should adapt its provider-native resources to those generic primitives rather than requiring `computing_core` to carry AWS-specific accommodation logic.

Examples of future alignment work in `aws_core` may include:

- relating `aws_elastic_ip` to generic `ip_address`
- relating `aws_subnet` to generic `ip_subnet`
- relating `aws_ebs_volume` to generic `storage_volume` or `filesystem`
- relating AWS compute and container resources to `virtual_machine` or `container`
- introducing hotlink-backed synchronization where provider-native fields embed generic identifiers and TAP benefits from enforcing that contract

This specification does not yet define the exact cross-plugin edge family, hotlink contracts, dependency semantics, or load ordering rules. Those belong to a later phase once `computing_core` is stable and TAP is ready for plugin dependency design.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-computing-core-1 | AWS Adapts Downward | Proposed | Future AWS-to-generic mapping is defined in `aws_core` rather than in `computing_core`. | |
| req-aws-core-computing-core-2 | Generic Substrate Respected | Proposed | `aws_core` treats `computing_core` as the lower generic substrate for relevant concepts. | |

#### Open Questions

Should `aws_elastic_ip.public_ip` eventually participate in a hotlink contract to a generic `ip_address` node across a future provider-to-generic edge such as `PROVIDES`, or should AWS/generic correspondence stay as ordinary graph relationships only? This is intentionally left open so TAP can decide later whether the embedded AWS field plus materialized generic node relationship is strong enough to justify hotlink synchronization.

### Plugin Validation
----
RID: `req-aws-core-validation`

Status: `Implemented`

The plugin passes TAP's centralized plugin validation system at all three levels.

#### Implementation

- **structure** — manifest, paths, edge files, directories, undeclared files
- **loads** — class imports, ENTITY_TYPE matching, icon validation
- **runs** — create_node for all 37 models, create_edge for constrained edge types, GRIFT import

Plugin-specific tests cover only domain behavior (field defaults, configuration round-trips). All structural, load, and runtime smoke testing is delegated to the centralized validator.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-validation-1 | Structure Level Passes | Implemented | Plugin passes `validate_plugin --level structure`. | |
| req-aws-core-validation-2 | Loads Level Passes | Implemented | Plugin passes `validate_plugin --level loads`. | |
| req-aws-core-validation-3 | Runs Level Passes | Implemented | Plugin passes `validate_plugin --level runs`. | |

### Organizations Tree
----
RID: `req-aws-core-organizations`

Status: `Implemented`

The plugin can draw an AWS Organizations tree: the organization, its organizational units, the
member accounts in them, and the service control policies attached anywhere in it. This started as
**design vocabulary** with no collector, and every field is still one AWS reports; a collector now
fills it (`req-aws-core-organizations-collect`, below) as its own read rather than a
collection-manifest entry, since the tree is one connected structure and not a per-account
resource list.

#### Implementation

- `aws_core__aws_organization`: `name`, `organization_id` (`o-…`), `root_id` (`r-…`),
  `management_account_id`, `feature_set` (`ALL` / `CONSOLIDATED_BILLING`), `partition` (`aws`,
  `aws-us-gov` or `aws-cn`, the three partitions AWS Organizations runs in). Source: `organizations:DescribeOrganization` and `ListRoots`; the partition is the
  organization ARN's partition segment. An organization has no name in AWS, so `name` is the label
  its author or collector gives it. It carries no `tags`: AWS cannot tag an organization.
  *(Proposed amendment, `req-aws-core-organizations-completeness-1`: the organization stands for
  its root, and AWS can tag a root — `organizations:TagResource` accepts an `r-…` id — so the
  organization node carries the root's tags.)*
  Blank means not observed for every id and enum field on these types, as on
  `aws_elb.lb_type`: `""` is in each enum, and nothing here is nullable except the transit
  gateway's integer and boolean options.
- `aws_core__aws_organizational_unit`: `name`, `ou_id` (`ou-…`), `tags`.
- `aws_core__aws_service_control_policy`: `name`, `policy_arn`, `policy_id` (`p-…`), `description`,
  `aws_managed` (null when not observed), `tags`. The policy document is not stored. No source fills a typed summary of it
  yet, and a raw document blob is the unsourced JSON the model contract forbids; `description`
  carries the author's statement of what the policy does.
- **SCP identity is the ARN.** AWS documents no global uniqueness for a customer policy's `p-…` id,
  but its ARN is scoped by management account and organization, so `policy_arn` is the key. An
  AWS-managed policy such as FullAWSAccess has one ARN in every organization because it is one
  AWS-owned object, so it is one node, and each organization's use of it is its own
  `ATTACHED_TO_TARGET` edge.
- **The organization is its own root.** AWS allows exactly one root per organization and the root
  has no facts of its own besides its id (and which policy types are enabled on it). A separate root
  node would stand for the same thing as the organization node. So the root's id is `root_id` on the
  organization, and every edge that lands on "the root" (a top-level OU, an account directly under
  the root, a policy attached at the root) lands on the organization node.
- `NESTED_UNDER_PARENT` (OU or account → OU or organization): AWS's single parent/child
  relationship. `organizations:ListParents` takes an account or an OU and returns an OU or the root,
  so OU nesting and account placement are one edge type, not two.
- `ATTACHED_TO_TARGET` (service control policy → OU, account or organization):
  `organizations:AttachPolicy(PolicyId, TargetId)`. The `_TO` is the locative preposition of
  "attached to" (the add-edge carve-out), and the edge is scoped to SCPs, not a generic attachment.
- Account membership is an edge and not a field on the account: the tree changes when an account
  is moved, and an edge is what `MoveAccount` changes.
- **Declared, not enforced on write.** tap_grid checks an edge by permission union
  (`spec-grid-edge.md`): an edge is allowed if the edge type's declaration *or* the source and
  target nodes' own `OUTBOUND_EDGES` / `INBOUND_EDGES` permit it. aws_core models declare neither,
  so today any aws_core node pair passes the node side and a write outside an edge's declared pairs
  still succeeds. This holds for every aws_core edge type, not only these; the declarations are what
  `validate_plugin`, queries and readers rely on.
- No containment is declared. Both edges point child → parent (and policy → target), and
  `CONTAINMENT_EDGES` can only name outbound edges; an account also outlives its organization.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-organizations-1 | Keyed On AWS Ids | Implemented | Organization, OU and SCP declare `NATURAL_KEY` on `organization_id`, `ou_id` and `policy_arn`. | |
| req-aws-core-organizations-2 | Designable Before AWS Mints Ids | Implemented | Each type creates with only `name`; a blank id is not observed, and two id-less designs stay two nodes. | |
| req-aws-core-organizations-3 | Ids Validated | Implemented | Each id field validates against AWS's documented id pattern, or is blank. | |
| req-aws-core-organizations-4 | Organization Is Its Own Root | Implemented | There is no root type; `root_id` is a field on the organization, and root-level edges target the organization. | |
| req-aws-core-organizations-5 | Tree Edge | Implemented | `NESTED_UNDER_PARENT` declares OU or account → OU or organization and no other pair. | |
| req-aws-core-organizations-6 | SCP Attachment Edge | Implemented | `ATTACHED_TO_TARGET` declares SCP → OU, account or organization and no other pair. | |
| req-aws-core-organizations-7 | No Policy Document Blob | Implemented | The SCP model carries no policy document or `configuration` field. | A typed summary field can be added when a source fills it. Proposed (landing-zone epic): statements become typed nodes instead, and this criterion stands (`req-aws-core-organizations-completeness-7`). |

### Organizations Tree Collection And Reconciliation
----
RID: `req-aws-core-organizations-collect`

Status: `Implemented`

The design vocabulary above (`req-aws-core-organizations`) is now collected, and its removal
detectable, by `collectors/boto3_collector/organizations.py` (tap-plugin-aws-core#50). Org-level
rollout is the first thing a management or delegated-administrator credential does, so this is a
first-class read alongside the manifest-driven resource sweep, not a manifest entry: the
Organizations tree is one connected structure, not a per-account resource list.

#### Implementation

- **What it reads**, every call read-only: `DescribeOrganization`, `ListRoots`,
  `ListOrganizationalUnitsForParent` (recursive — nested OUs, so "sub-orgs" are walked to
  whatever depth AWS holds them), `ListAccounts` (organization-wide membership) and
  `ListAccountsForParent` (per-parent placement), `ListPolicies(Filter=SERVICE_CONTROL_POLICY)`
  and `ListTargetsForPolicy`, `ListTagsForResource`.
- **Two NEW parent → child containment edges**, because the existing tree edges are references
  that must stay references (`req-aws-core-organizations`'s own ruling: `NESTED_UNDER_PARENT`
  points child → parent, and an account moves between OUs under `MoveAccount` with nothing ending
  the old edge, so a cascade through it would tombstone a live account):
  - `PARTITIONED_INTO_OU` (organization/OU → OU): safe as containment because AWS has no
    operation that re-parents an OU and refuses to delete a non-empty one, so an OU's parent is
    fixed for its life. Declared on `AwsOrganization` and `AwsOrganizationalUnit`.
  - `ENROLLS_ACCOUNT` (organization → account): the organization-wide membership, deliberately
    NOT the OU-level listing, so `MoveAccount` never touches it and a moved account is never
    mistaken for a departed one. Declared on `AwsOrganization` only.
  - An account's current OU is also carried on the node (`configuration.ParentId`), because the
    reference edge alone cannot say which of two `NESTED_UNDER_PARENT` edges is stale after a
    move.
- **Completeness surfaces** (`req-grid-reconcile-evidence`) are recorded for every parent's OU
  listing and for the organization-wide account listing — the two relations the new containment
  edges cover — never for the per-parent `ListAccountsForParent` placement reads or the SCP calls,
  which back a reference, not a containment edge. A failed or denied listing is recorded as
  incomplete with a reason, never as an empty "no children" result; a listing whose model refused
  one of its items withdraws `admitted` rather than silently dropping that item's evidence
  (`req-aws-core-organizations-collect-4`).
- **`OrganizationalUnitFalsifier`** (`DescribeOrganizationalUnit` + `ListParents`) and
  **`AccountFalsifier`** (`DescribeAccount`), both subclassing `_AwsFalsifier`
  (`tap_plugin/aws_core/falsifiers.py`) and both registered in `[falsifiers]`. Neither probes
  without first proving **reach**: the credential's own `DescribeOrganization` + `ListRoots`
  must show it is inside an organization, and — because `AccountNotFoundException` is documented
  as raised both for "no such account" and for "the calling credential is not in an
  organization" — that organization must be the one the candidate was recorded under (its `o-…`
  id for an account, embedded in its ARN; the OU id's own root suffix for an OU). A candidate
  outside that reach is `UNDETERMINED(scope_unknown)` without a probe, mirroring
  `req-aws-core-reconcile-falsifiers-3`'s single-account check, which still runs first and needs
  no organization read at all.
- **What "gone" means, decided explicitly:**
  - An OU is deleted only when AWS has already emptied it, so `OrganizationalUnitNotFoundException`
    is unambiguous — `DROPPED_FROM_OBSERVATION`.
  - An account **moved** to another OU never reaches either falsifier: `ENROLLS_ACCOUNT` is
    organization-wide and `MoveAccount` does not change it; only its `NESTED_UNDER_PARENT` edge
    goes stale until the next run re-collects it.
  - A **closed or suspended** account is still named by `ListAccounts` and still describable
    (`Account.State` `SUSPENDED` / `PENDING_CLOSURE` / `CLOSED`, with the deprecated `Status`
    field as a fallback) — it is `PRESENT_AT_PROBE` with a note, never retired here; only its
    `status` field changes. A **removed** account (left the organization, or finally purged by
    AWS after closure) is `DROPPED_FROM_OBSERVATION`.
  - An account whose ARN reports a **different organization** than the one it was recorded under
    is `RELOCATED(transferred)` — the standing verdict semantics
    (`req-grid-reconcile-observation-lifetime`), not a new case invented here.
- **GovCloud.** Region and partition are never hardcoded: the `organizations` client is built in
  the collector's own first region, exactly like every other global-scope manifest entry, so
  botocore resolves the GovCloud endpoint (`organizations.us-gov-west-1.amazonaws.com`) and
  partition (`aws-us-gov`) from the credential's own region scope — verified offline against
  botocore 1.43.103's endpoint data, not against a live GovCloud organization. The organization's
  `partition` field is read from the ARN `DescribeOrganization` returns, never constructed.
  **Assumed, not verified**, because no GovCloud organization was reachable to confirm it: that
  GovCloud Organizations exposes the same operations and response shapes read above (in
  particular `Account.State`), and that service control policies are enabled on a GovCloud root.
  Flagged here rather than silently relied on.
- **Credential postures.** A member-account credential can `DescribeOrganization` but not
  `ListRoots`; a delegated administrator may hold some Organizations actions and not others. Both
  degrade to a recorded, reasoned incompleteness — never an exception that aborts the run (the
  manifest-driven sweep's own foundation-abort posture does not apply here: the Organizations
  tree is an optional structure this credential may simply not have visibility into, not a
  failure of the credential's own identity).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-organizations-collect-1 | Nested OUs Walked | Implemented | `ListOrganizationalUnitsForParent` recurses from the root through every depth AWS returns. | `test_organizations.py::TestCollectOrganizationTree::test_full_tree_nodes_edges_and_surfaces` |
| req-aws-core-organizations-collect-2 | New Containment Edges | Implemented | `PARTITIONED_INTO_OU` and `ENROLLS_ACCOUNT` are declared in `CONTAINMENT_EDGES` on their parent model(s); `NESTED_UNDER_PARENT` is unchanged and stays a reference. | `test_falsifiers.py::TestOrganizationContainment`. The `ENROLLS_ACCOUNT` half is proposed to be superseded by `req-aws-core-organization-membership-2` (ruling 2026-09-30). |
| req-aws-core-organizations-collect-3 | Falsifiers Registered | Implemented | `OrganizationalUnitFalsifier` and `AccountFalsifier` subclass `_AwsFalsifier`, are registered in `[falsifiers]`, and pass the four-case proof harness. | `test_organizations.py::TestOrganizationalUnitFalsifierFourCases`, `TestAccountFalsifierFourCases`. The `AccountFalsifier` half is proposed to be superseded by `req-aws-core-organization-membership-4`. |
| req-aws-core-organizations-collect-4 | Failed Listing Is Incomplete, Never Empty | Implemented | A denied or failing parent listing records `enumeration_complete: false` with a reason; no node is fabricated and no candidate is derivable from it. | `test_organizations.py::test_ou_listing_failure_is_incomplete_not_empty`, `test_list_roots_denied_refuses_both_child_surfaces_but_keeps_the_org_node` |
| req-aws-core-organizations-collect-5 | Reach Gates Every Probe | Implemented | Neither falsifier probes without first proving the credential is inside the candidate's own organization (account id / OU root suffix); a mismatch is `UNDETERMINED(scope_unknown)`. | `test_ou_from_another_organizations_root_is_scope_unknown`, `test_wrong_organization_reach_is_scope_unknown` |
| req-aws-core-organizations-collect-6 | Closed/Suspended Present, Moved Invisible, Removed Dropped | Implemented | A suspended/closed account is `PRESENT_AT_PROBE` with its status noted; a moved account never reaches the falsifier (organization-wide membership); a removed one is `DROPPED_FROM_OBSERVATION`. | `test_closed_account_is_reported_present_not_dropped`, `test_account_moved_mid_walk_still_placed_and_enrolled`, `TestAccountFalsifierFourCases::test_four_cases` Proposed: "removed" retires the **membership**, not the account (`req-aws-core-organization-membership-5`; ruling 2026-09-30). |
| req-aws-core-organizations-collect-7 | Partition Never Hardcoded | Implemented | The `organizations` client is built from the credential's own resolved region; the organization's `partition` field is read from the returned ARN. | `test_govcloud_partition_read_from_arn` (offline, against botocore's own endpoint resolution — not a live GovCloud organization) |

### Organization Membership
----
RID: `req-aws-core-organization-membership`

Status: `Proposed`

When an account disappears from the organization's listing, what ends is its **membership**: the
fact that this organization enrolls it. The account is not retired, and nothing it holds is retired
with it.

#### Status Details

Proposed by the landing-zone epic, step 8. Ruling (George, 2026-09-30): an account that leaves
the organization's listing has its membership ended, meaning the `ENROLLS_ACCOUNT` and placement
edges. The account is not retired, and nothing cascades to its IAM or S3. Retiring or deleting an
account is a **separate later step and out of scope here**.

#### Why the current design cannot honour the ruling (read, aws_core@d5b1cf8)

- `ENROLLS_ACCOUNT` (organization → account) is containment
  (`models/aws_organization.py:87`). So the account itself is the reconcile candidate.
- `AccountFalsifier` answers `AccountNotFoundException` with `DROPPED_FROM_OBSERVATION`
  (`falsifiers.py:934-937`).
- Core applies `DROPPED_FROM_OBSERVATION` as `delete_node(cascade="contained")`
  (`spec-grid-reconcile.md`, the verb). That walks `AwsAccount.CONTAINMENT_EDGES`
  (`OWNS_IAM_ROLE/USER/POLICY`, `OWNS_OIDC_PROVIDER`, `OWNS_BUCKET`; `models/aws_account.py:64-70`)
  and tombstones the account's IAM and S3 inventory. The AWS account still exists after
  `RemoveAccountFromOrganization`.
- Re-mapping the verdict cannot fix it inside core's canon. `RELOCATED(transferred)` ends only the
  parent's containment edge, but it fires **only when the probe succeeded and returned a different
  owner**. A transfer out of reach "presents as a probe that answers not-found … and is handled like
  any other loss of observation" (`req-grid-reconcile-observation-lifetime`, ruled 2026-09-15). An
  account removed from this organization answers not-found to this organization's credential.

So the epic follows canon's own sentence: "retirement ends an observation, not a thing". The
membership becomes the observed thing, and the thing that retires.

#### Implementation

- **`aws_core__aws_organization_membership`** — one node per (organization, member account), with
  `NATURAL_KEY = ("organization_id", "account_id")`. Fields: `organization_id`, `account_id`,
  `state` (`Account.State`, falling back to `Status`, as `account_state` does today), `joined_method`,
  `joined_at`, `email` (the address the organization records), and the `tags` field
  (`req-aws-core-fields-4`). Source: the organization-wide `ListAccounts` the reader already makes
  (`organizations.py:630-659`). AWS cannot tag a membership, so its declaration is
  `{"source": "none", ...}` (`req-aws-collector-tags-12`). Account tags set through Organizations
  stay on `aws_account.tags` (ruling 2026-10-01), not here.
- **`HOLDS_MEMBERSHIP`** (organization → membership), containment, declared in
  `AwsOrganization.CONTAINMENT_EDGES` **in place of** `ENROLLS_ACCOUNT`. The `ListAccounts` listing's
  completeness surface names this edge type. The surface rules, the reach gate and the
  failed-listing rules are unchanged (`req-aws-core-organizations-collect-4`, `-5`).
- **`ENROLLS_ACCOUNT`** is re-sourced from the organization to the membership (membership → account)
  and becomes a **reference**. Retiring a membership ends it by core's endpoint rule: node
  retirement ends every incident edge, and the far node stays live
  (`req-grid-service-delete-baseline-2`).
- **`MembershipFalsifier`** replaces `AccountFalsifier` in `[falsifiers]`. Its probe, its reach gate
  and its verdict table are `AccountFalsifier`'s (`DescribeAccount`; closed or suspended is
  present with a note; `AccountNotFoundException` after reach is proven is
  `DROPPED_FROM_OBSERVATION`). The verdict now lands on the membership, which declares no
  containment, so the cascade closure of a retired membership is the membership alone.
- **What retiring a membership touches:** the membership node; its `HOLDS_MEMBERSHIP` and
  `ENROLLS_ACCOUNT` edges. **What it does not touch:** the account node, the account's
  `OWNS_*` children, its region footprints, anything collected inside it.
- **Placement stays on the account** (ruling 2026-10-01). The 2026-09-30 ruling names
  placement edges too: `NESTED_UNDER_PARENT` (account → OU) and `ATTACHED_TO_TARGET` (SCP →
  account). Both start at, or land on, the account, which stays live, so retiring the membership
  does not end them. Moving placement onto the membership was considered and declined for now: it
  would change `req-aws-core-organizations-5` and the `/aws/organization` tree, which nests accounts
  on `NESTED_UNDER_PARENT` (`grift/pages.grift.json:265`). So a departed account keeps its last-seen
  placement edges until core's edge re-derivation (`req-grid-reconcile-falsifier-5`, Proposed) can end
  them. That gap is named here (`-6`) and in `req-aws-core-reference-derivation-2`, so a reader does
  not read those edges as current.
- **Email and status move to the membership** (ruling 2026-10-01). The organization-sourced
  lifecycle facts from `ListAccounts` (`email`, `state`, `joined_method`, `joined_at`) live on the
  membership and nowhere else: no `aws_account` envelope carries them, as typed fields or in
  `configuration` (`State`, `Status`, `JoinedMethod`, `JoinedTimestamp` leave the account's
  `configuration` too). `AwsAccount.email` and `AwsAccount.status`
  are deprecated: the collector stops writing them, and they are removed by a later migration once
  nothing reads them. No page reads either today (grep of `grift/pages.grift.json` and
  `static/aws_core/js`). That gives those facts one writer and closes their half of the cross-run
  clobber `req-aws-collector-fanout` leaves open. The other half is not closed here: Organizations
  account tags stay on `aws_account.tags` (ruling 2026-10-01), so the account's `tags` still has two writers. A
  member-scoped run that cannot read them writes `{}`, which is the false-empty write named under
  `req-aws-collector-tags` and waits on core's GRIFT replacement semantics
  (unified-systems-com/tap#886).
- **Organization cascade.** A deliberate `delete_node(cascade="contained")` of the organization
  tombstones everything it contains: its OUs, memberships, delegations, customer-managed SCPs and
  other customer-managed policies, and through those policies their statements and tag-policy
  rules (`req-aws-core-organizations-completeness`). It does **not** reach its accounts, or
  AWS-managed policies and their statements, which no organization contains. That narrows the blast radius
  `models/aws_organization.py:61-79` flags for human sign-off.
- **Migration.** Existing grids hold organization → account `ENROLLS_ACCOUNT` edges. They are
  retired once, by an operator-run GRIFT bundle with a `deletes` section
  (`req-grift-import-deletes`). The collector never retires anything.
- **Out of scope:** retiring or deleting an `aws_account` node, and any account falsifier. After this
  change no containment edge targets `aws_account` except through a deliberate manual delete, so an
  account has no automatic retirement path. That is deliberate (ruling 2026-09-30).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-organization-membership-1 | Membership Node | Proposed | `aws_core__aws_organization_membership` exists, keyed `(organization_id, account_id)`, one per account `ListAccounts` returns, carrying `state`, `joined_method`, `joined_at`, `email` and the `tags` field (declared `none`). | Ruling 2026-10-01: the node design is approved for specification. |
| req-aws-core-organization-membership-2 | Organization Holds Memberships | Proposed | `AwsOrganization.CONTAINMENT_EDGES` names `HOLDS_MEMBERSHIP` and not `ENROLLS_ACCOUNT`; the `ListAccounts` surface's `edge_type` is `HOLDS_MEMBERSHIP`. | Supersedes `req-aws-core-organizations-collect-2`'s `ENROLLS_ACCOUNT` half on approval. |
| req-aws-core-organization-membership-3 | Enrollment Is A Reference | Proposed | `ENROLLS_ACCOUNT` declares membership → account and is in no model's `CONTAINMENT_EDGES`. | |
| req-aws-core-organization-membership-4 | Membership Falsifier | Proposed | `MembershipFalsifier` is registered for the membership type and passes the four-case harness; `AccountFalsifier` is no longer registered. | Supersedes `req-aws-core-organizations-collect-3`'s `AccountFalsifier` half. |
| req-aws-core-organization-membership-5 | Account Untouched | Proposed | Applying `DROPPED_FROM_OBSERVATION` to a membership tombstones the membership only: the account node, its `OWNS_*` children and its footprints stay live, and `contained_closure` of the membership is the membership alone. | The done-test for the 2026-09-30 ruling. |
| req-aws-core-organization-membership-6 | Placement Gap Named | Proposed | The spec states which placement edges a departed account keeps (`NESTED_UNDER_PARENT`, `ATTACHED_TO_TARGET`) and why: they stay last seen until core edge re-derivation can end them. | Ruling 2026-10-01: placement stays on the account. |
| req-aws-core-organization-membership-7 | One Writer Per Account Fact | Proposed | `email`, `state`, `joined_method` and `joined_at` live on the membership only; the collector no longer writes `AwsAccount.email` or `AwsAccount.status`, and no account envelope carries `State`, `Status`, `JoinedMethod` or `JoinedTimestamp` in `configuration`; a member-scoped run writing the account node cannot blank them. | Ruling 2026-10-01. Closes the email and status half of `req-aws-collector-fanout-8`'s cross-run case; the tags and `name` halves depend on unified-systems-com/tap#886 (`req-aws-collector-fanout-15`). |
| req-aws-core-organization-membership-8 | Account Retirement Out Of Scope | Proposed | No requirement here retires an `aws_account`; a later requirement owns it. | Ruling 2026-09-30. |

### Organizations Completeness
----
RID: `req-aws-core-organizations-completeness`

Status: `Proposed`

What a landing zone's management account holds in AWS Organizations beyond the tree and its SCPs:
the root's tags, which policy types and which AWS services are enabled, who is a delegated
administrator, and the other policy types GovCloud allows.

#### Status Details

Proposed by the landing-zone epic, step 4. The reader's own op list (`organizations.py:14-23`) is
what is read today. Everything below is absent from it (read). Policy bodies follow the 2026-10-01
rule on what becomes a node (*Policy Statements*, below).

#### Implementation

- **Root tags.** The organization stands for its root (`req-aws-core-organizations-4`).
  `organizations:TagResource` accepts a root id (`r-…`) as a taggable resource (read: botocore
  1.43.104 `organizations` model, `TagResource.ResourceId` documentation). So the sentence "It carries
  no tags: AWS cannot tag an organization" in `req-aws-core-organizations` is true of the
  organization and false of its root. `AwsOrganization` gains the `tags` field, filled by `tags_of(root_id)`
  under the Organizations lane (`req-aws-collector-tags-10`), with the same unread rule: an unreadable
  root tag set withholds the organization node, as it withholds OUs and accounts today.
- **Enabled policy types.** `ListRoots` returns `Root.PolicyTypes` (read: botocore `Root` shape),
  and the reader drops it today (`organizations.py:485-487`). `AwsOrganization` gains
  `enabled_policy_types`, a typed list of the API's `PolicyType` enum values whose status is
  `ENABLED`. `null` means not read, and `[]` is an observed empty.
- **Enabled service access.** `ListAWSServiceAccessForOrganization` →
  `AwsOrganization.enabled_service_principals`, a typed list of `{service_principal, enabled_at}`.
  A denied call leaves it `null`, never `[]`.
- **Delegated administration.** `ListDelegatedAdministrators`, then `ListDelegatedServicesForAccount`
  per delegated account → **`aws_core__aws_delegated_administration`**, keyed
  `(organization_id, account_id, service_principal)`. AWS addresses a delegation by exactly that pair:
  `DeregisterDelegatedAdministrator(AccountId, ServicePrincipal)`. Edges: `HOLDS_DELEGATION`
  (organization → delegation, containment) and `DELEGATES_TO_ACCOUNT` (delegation → account,
  reference). Falsifier: `ListDelegatedServicesForAccount(AccountId)`, after the same reach gate.
  A successful answer that no longer names the service principal is `DROPPED_FROM_OBSERVATION`.
  So is `AccountNotRegisteredException`, which botocore documents as "the specified account is not
  a delegated administrator" (read: botocore 1.43.103 `organizations` model). That is the answer
  AWS gives when the account's last delegation is removed. `AccessDeniedException` and every other
  error are `UNDETERMINED`. During collection, `AccountNotRegisteredException` for an account the
  outer listing named means the two reads disagree: the aggregate surface is recorded incomplete
  with that reason (`req-aws-core-organizations-completeness-13`). AWS cannot tag a delegation, so
  its tags are declared `none` (`req-aws-collector-tags-12`).
  **One surface for the nested listings.** Every delegation hangs directly off the organization, but
  the inventory comes from one outer listing plus one inner listing per delegated account. Core
  derives candidates by fanning out from the surface's parent through its edge type
  (`req-grid-reconcile-candidates`: `children(P, R) − observed`), so a surface recorded for any one
  inner call would nominate every other account's delegations. The rule is one organization-wide
  `HOLDS_DELEGATION` surface, recorded complete only when `ListDelegatedAdministrators` read to its
  end **and** `ListDelegatedServicesForAccount` read to its end for every account it returned; any
  failed or partial call records it `enumeration_complete: false` with the reason, and no
  per-account surface is recorded. A per-account parent node was considered and declined: AWS
  addresses a delegation by (account, service principal), and has no object for "the delegations of
  one account" to retire, so the parent would be a node AWS does not address
  (`req-aws-core-network-plane`'s rule). The cost of the aggregate is that one failed inner listing
  defers every delegation's retirement for that run, which fails closed.
  Landing-zone relevance: Control Tower 4.0 makes the audit account the Config delegated administrator
  ([C-CFGV4](https://docs.aws.amazon.com/controltower/latest/userguide/config-updates-v4.html)), and GuardDuty and Security Hub are commonly delegated to the security account
  (inferred from [CT-SECB](https://docs.gruntwork.io/reference/modules/terraform-aws-control-tower/control-tower-security-account-baseline/); not stated there).
- **Other policy types.** **`aws_core__aws_organizations_policy`**, keyed `policy_arn`, with
  `policy_type` drawn from the API's `PolicyType` enum. It is read with
  `ListPolicies(Filter=<type>)` only for types in `enabled_policy_types`, so an unavailable type is
  never called and so never misread. GovCloud's allowed set is SCP, RCP, TAG, declarative EC2 and S3
  (web, [C-GCORG](https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-organizations.html)). Backup, chat and AI opt-out policies are not available there.
  SCPs keep their own model, `req-aws-core-organizations`; this adds no second SCP node.
  `ATTACHED_TO_TARGET` gains the new type as a source. Tags: the Organizations lane, for customer-managed policies.
- **Policies get a retirement path.** `HOLDS_SERVICE_CONTROL_POLICY` and
  `HOLDS_ORGANIZATIONS_POLICY` (organization → policy, containment) carry the org-wide `ListPolicies`
  listing's completeness. `HOLDS_ORGANIZATIONS_POLICY` is filled by one `ListPolicies(Filter=<type>)`
  per enabled non-SCP type, all under the same parent and edge type, so it follows the delegation
  rule: one surface, complete only when `enabled_policy_types` was read (not `null`) and every
  per-type listing read to its end. The falsifier is `DescribePolicy`, where `PolicyNotFoundException` is
  `DROPPED_FROM_OBSERVATION`. An AWS-managed policy (one ARN in every organization,
  `req-aws-core-organizations`) is never a containment child of one organization, so the edge is
  emitted for customer-managed policies only. Today an SCP has no containment parent and no falsifier (`models/aws_service_control_policy.py`, `tap-plugin.toml` `[falsifiers]`), so it can never retire; this closes that for SCPs.
- **Tag policies are collected** (ruling 2026-10-01). A `TAG_POLICY` is AWS's own tag governance.
  Collecting it as policy nodes adds nothing to TAP's tag normalization and is not a new tag system.

#### Policy Statements

**The rule, and this spec's reading of it.** George's rule (2026-10-01): if statement, action and
effect would make sense to reference independently, break them into nodes, with cascade delete and
the ability to update them thoughtfully as they change; if they always ship together and make no
sense alone, keep them together. This section is this spec's reading of that rule. It is open to
override in review.

- **A statement is independently meaningful, so it is a node.** A statement has its own name (`Sid`),
  and the questions asked of policies are statement questions: "which policy denies
  `iam:CreateUser`", "which statements restrict regions", "what did this `Sid` say last month". So
  each statement of an authorization policy (SCP, RCP) is a node contained by its policy.
- **Effect, actions, resources and conditions ship together, so they are fields.** An effect means
  nothing without the actions it applies to, and an action list means nothing without its effect and
  conditions. They are typed fields on the statement, not nodes.
- **An action is not a node.** `s3:PutObject` has no identity outside the statement that names it:
  the same string in two statements is two different facts. "Which statements deny `s3:PutObject`"
  is a query over the `actions` field, and IAM wildcard matching (`s3:*`, `s3:Put*`) is the query's
  concern, not the model's.

**`aws_core__aws_policy_statement`.** One node per statement of an SCP or RCP document read by
`DescribePolicy`.

| Field | Meaning |
| --- | --- |
| `policy_arn` | The containing policy's ARN. |
| `statement_key` | Identity within the policy (below). `NATURAL_KEY = ("policy_arn", "statement_key")`. |
| `sid` | The statement's `Sid`, blank when it has none. |
| `effect` | `Allow` or `Deny`. |
| `actions`, `not_actions` | Lists of action strings, de-duplicated and sorted; exactly one is non-empty. |
| `resources`, `not_resources` | Lists of resource ARN patterns, de-duplicated and sorted. |
| `principals`, `not_principals` | RCP only: a list of `{type, value}` (for example `{"type": "AWS", "value": "*"}`); `[]` on an SCP, whose grammar has no principal. |
| `conditions` | A list of `{operator, condition_key, values}`, one entry per key under each operator of the `Condition` block, `values` a sorted list of strings. `[]` when there is no `Condition`. |
| `positions` | The sorted 0-based indices at which this statement appears in the document as last read: one entry normally, `occurrences` entries when identical statements share the node. Informational, never identity. |
| `occurrences` | How many identical statements the document holds under this key (normally 1). |
| `content_sha256` | SHA-256 of the canonical form (below), as a change detector. |
| `tags` | Declared `{"source": "none", ...}`: a statement is not an AWS resource. |

Each JSON-typed field carries a schema with a description of the field and of each entry
(`req-aws-core-fields`). Statement content is access-control configuration and is classified
`access_policy` (`req-aws-collector-manifest-6`).

**Canonical form.** The hash is computed from the normalized typed fields, never from the raw
statement. The canonical form is the JSON object `{effect, actions, not_actions, resources,
not_resources, principals, not_principals, conditions}`, exactly as those fields are stored,
serialized with sorted keys and no insignificant whitespace. So two statements that store the same
fields have the same hash, and every spelling AWS treats as one value is folded before storage:

- Every member AWS allows as a string or a list becomes a de-duplicated, sorted list. That covers
  `Action`, `NotAction`, `Resource`, `NotResource`, each condition value, and each principal type's
  value under `Principal` and `NotPrincipal` (`{"AWS": "arn:…"}` and `{"AWS": ["arn:…"]}` store the
  same entries).
- `principals` and `not_principals` are lists of `{type, value}`, one entry per value, sorted by
  `(type, value)`. A bare `"Principal": "*"` is stored as `{type: "*", value: "*"}`. It is not
  folded into `{type: "AWS", value: "*"}`: IAM's documentation describes the two as equivalent
  (inferred, not verified against the page for SCPs and RCPs), and folding them is left to an
  amendment that cites it.
- Action names are lowercased, since IAM matches action names case-insensitively. Condition
  operator names and condition-key names are lowercased, since IAM matches both case-insensitively
  (inferred from IAM's policy-grammar documentation). Condition values, resource ARNs and principal
  values keep their case.
- `conditions` entries are sorted by `(operator, condition_key)`.
- `Sid` is excluded.

`content_sha256` is the SHA-256 of that serialization. A test recomputes it from the stored fields
of every statement node and asserts equality, and asserts that each pair of equivalent spellings
above hashes the same.

**Identity.**

- A statement with a `Sid` is keyed `sid:<Sid>`. IAM's policy grammar requires a `Sid` to be unique
  within a policy (inferred to hold for SCPs and RCPs, which use that grammar; to be confirmed
  against AWS's SCP syntax page before build).
- A statement without a `Sid` is keyed `content:<content_sha256>`.
- If a document repeats a `Sid`, every statement carrying that `Sid` is keyed
  `dupsid:<sha256>`, hashing the canonical serialization with a `sid` member added, and a
  `DUPLICATE_SID` warning names the
  policy. The Sid is in the hash because the canonical form excludes it: without it, a duplicate-Sid
  statement and a Sid-less statement with the same content, or statements under two different
  duplicated Sids, would get one key and be merged although their `sid` values differ. The distinct
  `dupsid:` prefix keeps the fallback apart from `content:` keys. Two statements are never merged by
  a shared `Sid` alone; two statements under the same duplicated `Sid` with identical content are one
  node with `occurrences`, as identical Sid-less statements are.
- Identical statements without a `Sid` share one key. Repeating a statement changes nothing in IAM
  evaluation, so they are one node with `occurrences` counting them.

**Update semantics.**

| Change in AWS | What the grid shows |
| --- | --- |
| Statements reordered | Same nodes. `positions` changes; nothing retires. Statement order has no effect on IAM evaluation (every statement is evaluated, and an explicit deny wins). |
| A statement with a `Sid` is edited | Same node, fields replaced in place. `content_sha256` changes, and the node's history holds the before and after. |
| A statement without a `Sid` is edited | Its content key changes. The old node retires and a new node is created. This is the honest reading: AWS gives such a statement no identity beyond its content. Authors who want edits to read as edits give their statements a `Sid`. |
| A `Sid` is added, removed or renamed, or becomes or stops being duplicated | The key changes: the old node retires and a new one is created. |
| A statement is removed | Its node retires (below). |
| The policy is deleted | The policy retires, and the cascade retires its statements (containment). |

**Retirement.** `DECLARES_STATEMENT` (policy → statement) is containment. The listing behind it is
the policy's own `DescribePolicy` document: complete when the call succeeded and the document parsed,
and recorded `enumeration_complete: false` with the reason otherwise, so a failed read never derives a
candidate. `PolicyStatementFalsifier` re-reads `DescribePolicy`: the key present is
`PRESENT_AT_PROBE`; the policy found and the key absent, or `PolicyNotFoundException`, is
`DROPPED_FROM_OBSERVATION`; a denied call or an unparseable document is `UNDETERMINED`. It uses the
same reach gate as the other Organizations falsifiers (`req-aws-core-organizations-collect-5`). An
AWS-managed policy (one ARN in every organization) is not a containment child of the organization,
but its statements are containment children of it, so an AWS edit to `FullAWSAccess` retires and
creates statements like any other.

**No edges from statements yet.** Resolving a statement's actions and resources to grid nodes is the
policy-document edge resolver, which stays deferred (`spec-aws-core-collector-v0.md`, v0 Non-Goals).

**`req-aws-core-organizations-7` stands.** It forbids a policy document blob on the policy model,
and nothing here stores one: the statement fields are typed, and the document itself is not kept.

**Management policy types.** Tag policies and the declarative EC2 and S3 policies are not statement
documents. They are trees of settings with inheritance operators (`@@assign`, `@@append`,
`@@remove`). Read by the same rule, their independently meaningful unit is the setting, not the
document:

- **Tag policies.** The unit is one tag key's rule. **`aws_core__aws_tag_policy_rule`**, keyed
  `(policy_arn, tag_key_lower)`, contained by its policy (`DECLARES_TAG_RULE`), with `tag_key` (the
  capitalization the rule assigns), `allowed_values` (null when the rule does not constrain values),
  `enforced_for` (null when absent) and `inheritance_operators` (the operators the rule uses). Its
  tags are declared `none`. An edit to a key's rule updates the node in place; removing the key
  retires it. Same falsifier shape as statements, and the same surface: `DECLARES_TAG_RULE` is
  backed by the policy's `DescribePolicy` document, complete when the call succeeded and the
  document parsed (a policy with no keys is complete-empty), and incomplete with the reason
  otherwise (`req-aws-core-contained-type-triple`).
- **Declarative EC2 and S3 policies.** The unit is one top-level attribute (for example an EC2 image
  block-public-access setting). The typed fields differ per attribute, and this spec does not yet
  name them. Their bodies are **not read** until an amendment specifies each attribute's fields from
  AWS's declarative-policy syntax reference. The policy node and its attachments are collected.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-organizations-completeness-1 | Root Tags | Proposed | `AwsOrganization.tags` holds the root's Organizations tags via the Organizations lane; an unreadable root tag set withholds the organization node (`req-aws-collector-tags-10`). | Amends `req-aws-core-organizations`' "carries no tags". |
| req-aws-core-organizations-completeness-2 | Enabled Policy Types | Proposed | `enabled_policy_types` lists the root's `ENABLED` policy types; `null` = not read, `[]` = observed none. | |
| req-aws-core-organizations-completeness-3 | Enabled Service Access | Proposed | `enabled_service_principals` lists `{service_principal, enabled_at}`; a denied call leaves `null`. | |
| req-aws-core-organizations-completeness-4 | Delegated Administration | Proposed | One `aws_delegated_administration` per (organization, account, service principal), keyed `NATURAL_KEY = ("organization_id", "account_id", "service_principal")`, contained by the organization, with a registered falsifier passing the four-case harness. | |
| req-aws-core-organizations-completeness-5 | Other Policy Types | Proposed | Non-SCP policies of each enabled type are `aws_organizations_policy` nodes with `policy_type`; a type not enabled on the root is never listed. | GovCloud: SCP, RCP, TAG, declarative EC2, S3. |
| req-aws-core-organizations-completeness-6 | Policies Contained | Proposed | Customer-managed SCPs and other policies are containment children of the organization with registered falsifiers; AWS-managed policies are not. | |
| req-aws-core-organizations-completeness-7 | Statements Are Nodes | Proposed | Each statement of a customer-managed or AWS-managed SCP or RCP read by `DescribePolicy` is an `aws_policy_statement` node contained by its policy (`DECLARES_STATEMENT`), with `effect`, `actions`, `not_actions`, `resources`, `not_resources`, `principals`, `not_principals` and `conditions` as typed fields. No action is a node, and no policy document is stored. | The 2026-10-01 rule, as read in *Policy Statements*. `req-aws-core-organizations-7` stands. |
| req-aws-core-organizations-completeness-8 | Statement Identity | Proposed | A statement is keyed `sid:<Sid>` when it has a unique `Sid`; `content:<content_sha256>` when it has no `Sid`; and `dupsid:<sha256 of the Sid and the canonical form>`, with a `DUPLICATE_SID` warning, when its `Sid` is repeated. The canonical form is built from the normalized typed fields, principals and not-principals included, never the raw statement. Identical statements under one key are one node with `occurrences`. Tests: a duplicate-Sid statement and a Sid-less statement with identical content get different nodes; statements under two different duplicated Sids get different nodes; a string and a singleton-list spelling of an action, resource, condition value or principal value hash the same; `content_sha256` recomputed from the stored fields equals the stored value. | The canonical form excludes `Sid`, so the Sid enters the fallback hash explicitly. |
| req-aws-core-organizations-completeness-9 | Statement Update Semantics | Proposed | Reordering changes only `positions`; editing a statement with a `Sid` updates its node in place; editing a Sid-less statement, or adding, removing or renaming a `Sid`, retires the old node and creates a new one; deleting the policy cascades to its statements. | Each row of the update table is a test. |
| req-aws-core-organizations-completeness-10 | Statement Retirement Path | Proposed | `DECLARES_STATEMENT` is containment, its listing is the policy's `DescribePolicy` document (incomplete when the call or the parse fails), and `PolicyStatementFalsifier` is registered and passes the four-case harness. | |
| req-aws-core-organizations-completeness-11 | Tag Policy Rules | Proposed | Each tag key in a `TAG_POLICY` is an `aws_tag_policy_rule` node keyed `(policy_arn, tag_key_lower)` and contained by its policy, with a registered falsifier. Each containment pair also records the completeness surface `req-aws-core-contained-type-triple` lists for it. | Ruling 2026-10-01: collecting tag policies is in scope. |
| req-aws-core-organizations-completeness-12 | Declarative Bodies Not Yet Read | Proposed | Declarative EC2 and S3 policies are collected as policy nodes with their attachments; their bodies are not read until an amendment specifies each attribute's typed fields. | |
| req-aws-core-organizations-completeness-13 | Delegation Surface Spans Nested Listings | Proposed | The collector records exactly one `HOLDS_DELEGATION` surface per organization, complete only when `ListDelegatedAdministrators` and every `ListDelegatedServicesForAccount` it implies read to their end; otherwise it is recorded incomplete with the reason. No surface is recorded per delegated account. A test fails one inner listing and asserts the surface is incomplete and no delegation is a candidate. | Core fans candidates out from parent and edge type (`req-grid-reconcile-candidates`), so a per-call surface would nominate other accounts' delegations. |
| req-aws-core-organizations-completeness-14 | Policy Surface Spans Per-Type Listings | Proposed | The collector records exactly one `HOLDS_ORGANIZATIONS_POLICY` surface per organization, complete only when `enabled_policy_types` was read and every per-type `ListPolicies` read to its end; otherwise it is recorded incomplete. | Same rule as `-13`. |

### IAM Identity Center
----
RID: `req-aws-core-identity-center`

Status: `Implemented`

The plugin can draw an IAM Identity Center instance and the external identity provider it takes its
workforce users from (for example Okta). Design vocabulary, as above.

#### Implementation

- `aws_core__aws_identity_center_instance`: `name`, `instance_arn`, `identity_store_id`,
  `owner_account_id`, `home_region`, `tags`. Source: `sso-admin:ListInstances` /
  `DescribeInstance`; `home_region` is the region that call is made in, because the instance ARN
  carries no region.
- `TRUSTS_IDENTITY_SOURCE` (instance → external identity provider). AWS calls the provider the
  instance's *identity source*; the instance accepts SAML 2.0 assertions from it. The target is
  **open** (omitted): the provider is another plugin's node, most often an Okta application, and
  aws_core declares no plugin dependency. identity_core's `oidc_issuer` is not the target either:
  Identity Center federates over SAML, not OIDC. An instance that uses its own identity store or
  Active Directory has no edge of this type.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-identity-center-1 | Keyed On Instance ARN | Implemented | The instance declares `NATURAL_KEY = ("instance_arn",)`; the ARN validates against AWS's pattern or is blank. | |
| req-aws-core-identity-center-2 | Designable Before AWS Mints Ids | Implemented | The instance creates with only `name`. | |
| req-aws-core-identity-center-3 | Open Identity-Source Edge | Implemented | `TRUSTS_IDENTITY_SOURCE` declares only an Identity Center instance as its source, and leaves its target open. | aws_core stays dependency-free. |

### Transit Gateway
----
RID: `req-aws-core-transit-gateway`

Status: `Implemented`

The plugin can draw transit gateways, their VPC attachments, and transit gateway peering. Design
vocabulary, as above.

#### Implementation

- `aws_core__aws_transit_gateway`: `name`, `transit_gateway_id` (`tgw-…`), `owner_account_id`,
  `region`, `amazon_side_asn`, `auto_accept_shared_attachments`,
  `default_route_table_association`, `default_route_table_propagation`, `tags`. Source:
  `ec2:DescribeTransitGateways`; the three flags come from its `Options` (`enable` / `disable`
  there, `true` / `false` here, null when not observed).
- `aws_core__aws_transit_gateway_attachment`: `name`, `attachment_id` (`tgw-attach-…`),
  `resource_type` (AWS's `TransitGatewayAttachmentResourceType` enum: `vpc`, `vpn`,
  `vpn-concentrator`, `direct-connect-gateway`, `connect`, `peering`, `tgw-peering`,
  `network-function`), `resource_owner_account_id`, `tags`. Source:
  `ec2:DescribeTransitGatewayAttachments`.
- **Account ownership.** aws_core attaches a collected resource to its account through the
  collection-path dimension (`aws_account`), not through an edge or field. These two types add a
  typed owner field only where AWS reports one on the item and it can differ from the observing
  account: a transit gateway is routinely shared through AWS RAM (`OwnerId` →
  `owner_account_id`), and a cross-account attachment's VPC belongs to another account
  (`ResourceOwnerId` → `resource_owner_account_id`). The attachment does not repeat its gateway's
  owner; that is on the gateway node.
- `ATTACHED_TO_TRANSIT_GATEWAY` (attachment → its transit gateway, `TransitGatewayId`).
- `ATTACHES_VPC` (VPC attachment → VPC, `ResourceId` when `ResourceType` is `vpc`).
- `PEERS_WITH_TRANSIT_GATEWAY` (peering attachment → peer transit gateway, `ResourceId` when
  `ResourceType` is `peering`). A separate edge from `ATTACHED_TO_TRANSIT_GATEWAY` because the local
  and the far gateway are two relationships.
- `ROUTES_TRAFFIC` is not reused: attachment is a structural connection, not a route. Transit
  gateway route tables, when modelled, are where `ROUTES_TRAFFIC` applies. VPN, Direct Connect and
  Connect attachments have no far-side node type in aws_core yet, so they carry no far-side edge.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-transit-gateway-1 | Keyed On AWS Ids | Implemented | Transit gateway and attachment declare `NATURAL_KEY` on `transit_gateway_id` and `attachment_id`; each validates against AWS's id pattern or is blank. | |
| req-aws-core-transit-gateway-2 | Designable Before AWS Mints Ids | Implemented | Each type creates with only `name`. | |
| req-aws-core-transit-gateway-3 | Typed Options | Implemented | `amazon_side_asn` is null or an integer in one of AWS's two private ranges (64512-65534, 4200000000-4294967294); the three option flags are nullable booleans; `resource_type` is AWS's enum. | |
| req-aws-core-transit-gateway-4 | Attachment Edges | Implemented | `ATTACHED_TO_TRANSIT_GATEWAY` and `PEERS_WITH_TRANSIT_GATEWAY` declare attachment → transit gateway; `ATTACHES_VPC` declares attachment → VPC; none declares any other pair. | |

### AWS Pages
----
RIDs: `req-aws-core-page-dashboard`, `req-aws-core-page-organization`, `req-aws-core-page-network`,
`req-aws-core-panel-counts`, `req-aws-core-layout-hints`

Status: `Implemented`

Reusable pages over whatever AWS nodes a grid holds. Nothing on them names a deployment: a consumer
that wants them in its own navigation adds a `NESTS_UNDER` edge from `/aws` to its page (highbar does,
under `/highbar`). `/aws/organization` and `/aws/network` nest under `/aws` by URL. URLs carry no
entity id.

#### Implementation

- Bundle `grift/pages.grift.json` (`pages` in `tap-plugin.toml`): three pages, three graph panels
  with their projections, elevations, layouts and scene searches, five standard table panels, one
  standard text panel and one `aws-counts` panel.
- `/aws` (**AWS**): `counts` (aws-counts), `estate` (graph: organisation tree, transit gateways and
  their attachments, VPCs, internet and NAT gateways, network firewalls, the boundaries OUs are scoped
  to), `per-ou` (projection table: accounts directly in each OU), `scope` (projection table: what each
  compliance boundary is scoped from).
- `/aws/organization` (**Organization**): `tree` (graph: organization ⊃ OU ⊃ account and nothing
  else, laid out by `aws-organization.js`), `scp` (SCP attachments), `placement` (each account and
  its parent). Policies, boundaries and Identity Center stay in the tables and on `/aws`; drawing
  them as lines across the tree made it unreadable (George, 2026-09-24).
- `/aws/network` (**Network**): `plane` (graph: each transit gateway around its attachments, a line
  from each VPC attachment to its VPC, peering attachments to their peer; each VPC around its subnets
  and its internet gateway; NAT gateways and network firewalls placed by `RESIDES_IN_SUBNET`),
  `attachments` (gateway, attachment, VPC, CIDR), `subnets` (VPC, subnet, availability zone, CIDR,
  public), `igw` (every internet gateway), `dx` (Direct Connect: a text panel that says plainly that
  no connection is on the grid; the table of connections is future work).
- Layout module `static/aws_core/js/projections/aws-organization.js` (the organization graph): nests
  on `NESTED_UNDER_PARENT` only and drops any other node a search brings in. The organization lays
  its children out in columns; each OU lays its children out in rows, wrapping at its
  `layout:columns`; both from the nodes' layout tags (below). With no tags it still draws: one
  column, rows by label.
- Layout hints `static/aws_core/js/runtime/layout-hints.js`, importable by any layout module: neutral
  tag keys on the node itself. `layout:order` (integer) orders siblings; unordered siblings follow,
  by label. `layout:column` (integer, default 0) picks a column where the parent lays out in columns.
  `layout:columns` (integer, on a parent) wraps its children at that many per row; 1 stacks them.
  `layout:row` (integer) groups a parent's children into rows where the layout asks for rows by tag; inside a row, siblings sharing a `layout:column` stack in one column.
  `layout:fill` (`"true"`) widens a box that shares its column with other siblings to the
  parent's inner width (when every sibling is in that one column) or to the column's widest box;
  a box alone in its column is a row cell and takes the rest of its row. The helpers
  stamp `_stage` / `_order` for tap_viz's `ranked` inner layout; a parent with more than one row
  gets an invisible row box per row (view-only `_layout_row` nodes and `_LAYOUT_ROW` edges, sized
  bottom-up by the projection like any box). They name no entity type and no deployment; the tag
  values come from whatever seeds or collects the node. tap_viz is the natural long-term home.
- Layout module `static/aws_core/js/projections/aws-estate.js`, shared by the dashboard and network graphs: nests on
  `NESTED_UNDER_PARENT` (organization and OU around their children), `ATTACHED_TO_TRANSIT_GATEWAY`
  (a gateway around its attachments), `PARTITIONED_INTO_SUBNET` (a VPC around its subnets),
  `ATTACHED_TO_VPC` (a VPC around its internet gateway) and the collector's `aws_account` dimension
  (an account around what was collected in it). A `RESIDES_IN_SUBNET` source in exactly one subnet of
  the scene nests in that subnet and its line is hidden; one in several subnets of a single VPC (a
  network firewall's per-zone endpoints) nests in the VPC and keeps a line to each subnet. The
  derivation is a `_PLACED_IN` scene edge the module adds and removes itself (the shadow-nodes
  pattern); it is never stored. Inside a VPC, subnets stand in one column per availability zone (the
  subnet's `availability_zone`, zones in name order), public subnets first, then by label; what the
  VPC holds directly stands in a column to their left. **Known gap:** tap_viz's graph panel lifts only a
  node's `tags` onto the scene, not its model fields, so today no zone reaches the layout and a VPC's
  subnets stand as a compact square-ish block in label order instead. Every other edge is a line; roots stack in
  bands. Nothing is placed by name or id. Standard icon-badge node style.
- Panel type `aws-counts` (`panels/counts/__init__.py`, `templates/aws_core/panels/counts.html`,
  `static/aws_core/css/counts.css`), registered in `AppConfig.ready()`. `config.tiles` picks tiles
  from a fixed catalogue (default all): accounts, OUs, SCPs, VPCs, internet gateways, internet-facing
  load balancers, buckets not blocking public access, network firewalls, transit gateways,
  attachments, KMS keys; `config.boundaries` (default true) adds one tile per compliance boundary
  counting the accounts inside it, where an account is inside when it or any OU above it is
  `SCOPED_TO_COMPLIANCE_BOUNDARY` the boundary. Reads go through Gryphon; folding is pure.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-page-dashboard-1 | Dashboard Seeded | Implemented | `/aws` exists and mounts counts, estate, per-ou and scope. | Observed on the highbar dev grid, 2026-09-24. |
| req-aws-core-page-organization-1 | Organization Page Seeded | Implemented | `/aws/organization` exists, mounts tree, scp and placement, and its breadcrumb parent is `/aws`. | |
| req-aws-core-page-organization-2 | Tree Only | Implemented | The tree graph's searches return organizations, OUs, accounts and `NESTED_UNDER_PARENT` edges, nothing else: no policy, boundary or Identity Center node or line. | Observed on the highbar dev grid, 2026-09-24. |
| req-aws-core-layout-hints-1 | Order And Column From Tags | Implemented | Siblings are placed by `layout:order`, and under the organization by `layout:column`; a node's name and id are never read for placement. | Observed on the highbar dev grid, 2026-09-24. |
| req-aws-core-layout-hints-2 | Fill To Lane | Implemented | A `layout:fill` box sharing its column with siblings widens to the parent's inner width when all siblings share that column, else to the column's widest box; a box alone in its column takes the rest of its row. | Observed on the highbar dev grid, 2026-09-24. |
| req-aws-core-layout-hints-3 | Rows From Tags | Implemented | A parent's `layout:columns` wraps its children into rows of at most that many (1 stacks them); where the layout groups by `layout:row`, children sharing a value share a row, and those in a row sharing a `layout:column` stack in one column. | Observed on the highbar dev grid, 2026-09-24. |
| req-aws-core-page-network-1 | Network Page Seeded | Implemented | `/aws/network` exists, mounts plane, attachments, igw and dx, and its breadcrumb parent is `/aws`. | |
| req-aws-core-page-network-2 | Direct Connect Stated, Not Invented | Implemented | With no Direct Connect data, the dx section says no connection is on the grid; it draws no placeholder site. | |
| req-aws-core-page-network-3 | VPCs Hold Their Subnets | Implemented | The plane nests each subnet in the VPC that `PARTITIONED_INTO_SUBNET` it, in its availability zone's column (a compact block while the scene carries no zone), and each internet gateway in the VPC it is `ATTACHED_TO_VPC`; a resource in one subnet nests in it, a resource in several subnets of one VPC nests in the VPC with a line to each. | `tests/test_network_page_bundle.py` (scene searches). The layout itself has no JS test and is not yet observed in a browser. |
| req-aws-core-page-network-4 | Subnets Table | Implemented | `/aws/network` mounts `subnets`, one row per subnet a VPC is partitioned into, with zone, CIDR and public. | `tests/test_network_page_bundle.py`. |
| req-aws-core-panel-counts-1 | Counts Fold Purely | Implemented | Tiles fold from Gryphon envelopes by pure functions; a failed read renders "read failed", never 0. | `tests/test_counts_panel.py` |
| req-aws-core-panel-counts-2 | Design Marked | Implemented | A tile whose counted nodes are all dcom=design is marked design. | `tests/test_counts_panel.py` |
| req-aws-core-panel-counts-3 | Boundary Membership Follows The Tree | Implemented | An account counts inside a boundary when it or an OU above it at any depth is scoped to the boundary. | `tests/test_counts_panel.py` |

#### Future

- Nest VPCs in their accounts on the network graph from `BELONGS_TO_ACCOUNT` (`req-aws-core-placement`).
- Replace the dx text panel with a table of connections, virtual interfaces and Direct Connect
  gateways (`req-aws-core-direct-connect`) once a grid holds one.

### Resource Placement
----
RID: `req-aws-core-placement`

Status: `Implemented`

Edges that say which account owns a resource, which VPC holds a VPC-wide resource, and which subnet
a networked resource sits in, so a page can nest account → VPC → subnet → resource from real edges.

#### Implementation

- `BELONGS_TO_ACCOUNT` (resource → `aws_account`): ownership, one relationship over every
  account-owned aws_core type. The sources are listed, so a new type is added on purpose. Excluded:
  region, AZ, the account itself, the Organizations types (their placement is
  `NESTED_UNDER_PARENT`) and Bedrock foundation models, which AWS owns.
- `RESIDES_IN_VPC` (security group, network ACL, route table, target group, VPC endpoint → VPC):
  VPC-wide resources that are not placed in a subnet. A gateway-type VPC endpoint has no subnet.
- `PARTITIONED_INTO_SUBNET` (VPC → subnet): the one containment edge.
- `RESIDES_IN_SUBNET` (EC2 instance, Lambda, ECS service and task, EKS cluster, RDS, ElastiCache,
  OpenSearch, NAT gateway, ALB, ELB, network firewall, VPC endpoint, SageMaker endpoint → subnet):
  one edge per subnet. A resource in subnets reaches its VPC through the subnet, so its VPC is never
  recorded twice.
- `ATTACHED_TO_VPC` (internet gateway → VPC): kept apart from `RESIDES_IN_VPC` because an internet
  gateway exists on its own and can be detached and attached elsewhere.
- `RESIDES_IN_AZ` (subnet → `aws_az`): the zone a subnet was created in. A subnet lives in exactly one
  zone and cannot span zones or move, so there is one edge per subnet; the edge schema has no
  cardinality field, so the rule is stated in the edge description and not enforced on write
  (unified-systems-com/tap#794). Subnet-placed resources reach their zone through the subnet and do
  not carry it, as they do not carry `RESIDES_IN_VPC`. It is a reference: the zone is AWS's reference
  topology, never retires with a subnet, and is not a second containing parent (the VPC is the only
  one). The subnet's `availability_zone` field is the AWS-reported string the collector derives this
  edge from (matched to the `aws_az` node of that name); placement queries use the edge.
- **Delete tree.** Only `PARTITIONED_INTO_SUBNET` is containment, declared on `Vpc` through
  `CONTAINMENT_EDGES` and `OUTBOUND_EDGES`. A subnet exists only inside its VPC. The cascade stops at
  the subnet, which declares nothing. VPC-wide resources point child → VPC, and a cascade cannot
  follow an inbound edge, so they stay live, with their edge ended. Account ownership is a
  reference, not containment: a RAM-shared resource is used from other accounts, and an account's
  subtree can exceed `TAP_CASCADE_MAX_CLOSURE`. Containment takes effect only on a core that
  implements `req-grid-service-delete-cascade`. On the plugin's floor core, the declaration is inert.
- **VPC becomes a constrained source.** `OUTBOUND_EDGES` on `Vpc` means an edge type whose sources
  are undeclared can no longer start at a VPC. Edge types that list the VPC, or leave the source
  WILDCARD, are unaffected (permission union). No shipped grift has an edge out of a VPC.
- **How a collector derives them later** (no collector change in this PR; collector changes are
  additive and separate): from the raw item, not from typed fields, which these resource models
  mostly do not carry. `BELONGS_TO_ACCOUNT` comes from the item's owner field (`OwnerId`,
  `OwnerAccountId`, `ownerAccount`), falling back to the run's account. `RESIDES_IN_VPC` comes from
  `VpcId`. `PARTITIONED_INTO_SUBNET` comes from the subnet's `VpcId`. `RESIDES_IN_SUBNET` comes from
  `SubnetId` or each entry of the item's subnet list. `ATTACHED_TO_VPC` comes from
  `Attachments[].VpcId`. `RESIDES_IN_AZ` comes from the subnet's `AvailabilityZone`.
  These are manifest `edges` entries like the existing ones.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-placement-1 | Account Ownership Edge | Implemented | `BELONGS_TO_ACCOUNT` declares every account-owned aws_core type as a source and `aws_account` as its target, and excludes region, AZ, account, the Organizations types and Bedrock models. | |
| req-aws-core-placement-2 | VPC And Subnet Placement | Implemented | `RESIDES_IN_VPC`, `RESIDES_IN_SUBNET` and `ATTACHED_TO_VPC` declare the pairs above and no others; a subnet-placed resource is not a `RESIDES_IN_VPC` source. | |
| req-aws-core-placement-3 | VPC Contains Its Subnets | Implemented | `Vpc.CONTAINMENT_EDGES == ("PARTITIONED_INTO_SUBNET__aws_core",)`; a contained cascade from a VPC retires its subnets and leaves a security group that `RESIDES_IN_VPC` live. | Cascade test skips on a core without `cascade`. |
| req-aws-core-placement-4 | Owner Not Duplicated | Implemented | The network-plane types added with these edges carry no `owner_account_id`; ownership is the edge. | The transit gateway types keep the AWS-reported owner field from `req-aws-core-transit-gateway`. |
| req-aws-core-placement-5 | Subnet Zone Edge | Implemented | `RESIDES_IN_AZ` declares `aws_subnet` as its only source and `aws_az` as its only target; no model lists it in `CONTAINMENT_EDGES`, so a contained cascade from a VPC retires its subnets and leaves their zones live. | Exactly-one per subnet is stated, not enforced (unified-systems-com/tap#794). |

### Direct Connect
----
RID: `req-aws-core-direct-connect`

Status: `Implemented`

Design vocabulary for AWS Direct Connect, so the network page can draw the full path from the
customer router to a transit gateway.

#### Implementation

- `aws_core__aws_dx_connection`: `name`, `connection_id` (`dxcon-…`), `location` (the DX location
  code), `bandwidth` (AWS's string, e.g. `10Gbps`), `is_hosted` (null until observed), `region`,
  `tags`. Source: `directconnect:DescribeConnections` / `DescribeHostedConnections`.
- `aws_core__aws_dx_gateway`: `name`, `direct_connect_gateway_id` (a UUID), `amazon_side_asn` (AWS's
  two private ranges, or null). Source: `DescribeDirectConnectGateways`. It is global, so it has no
  region. It has no tags, because that call returns none.
- `aws_core__aws_dx_virtual_interface`: `name`, `virtual_interface_id` (`dxvif-…`),
  `virtual_interface_type` (`private` / `public` / `transit`), `vlan` (1-4094), `customer_asn` (AWS's
  `asn`: the customer side), `region`, `tags`. Source: `DescribeVirtualInterfaces`.
- `CARRIED_ON_CONNECTION` (VIF → connection) and `ATTACHED_TO_DX_GATEWAY` (VIF → DX gateway).
- **DX gateway ↔ transit gateway reuses the attachment.** AWS represents a DX gateway association on
  the transit gateway side as a transit gateway attachment of resource type
  `direct-connect-gateway`, with its own `tgw-attach-…` id. So the association is that
  `aws_transit_gateway_attachment` node: `ATTACHED_TO_TRANSIT_GATEWAY` to the gateway, and the new
  `ATTACHES_DX_GATEWAY` to the DX gateway. A direct DX-gateway-to-TGW edge would record the same fact
  a second time.
- **The customer end is open.** `TERMINATES_AT_CUSTOMER_DEVICE` (connection → WILDCARD) points at
  whatever node represents the customer's router or colocation device. aws_core does not model
  on-premises equipment.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-direct-connect-1 | Keyed On AWS Ids | Implemented | Connection, gateway and VIF declare `NATURAL_KEY` on `connection_id`, `direct_connect_gateway_id` and `virtual_interface_id`; each validates against AWS's id shape or is blank. | |
| req-aws-core-direct-connect-2 | Typed Fields | Implemented | Bandwidth pattern, VIF type enum, VLAN 1-4094, and the DX gateway's ASN limited to AWS's private ranges. | |
| req-aws-core-direct-connect-3 | Edges | Implemented | `CARRIED_ON_CONNECTION`, `ATTACHED_TO_DX_GATEWAY` and `ATTACHES_DX_GATEWAY` declare the pairs above; `TERMINATES_AT_CUSTOMER_DEVICE` leaves its target open. | |

### PrivateLink
----
RID: `req-aws-core-privatelink`

Status: `Implemented`

The provider and consumer sides of AWS PrivateLink: how tenants reach highbar privately.

#### Implementation

- `aws_core__aws_vpc_endpoint_service`: `name`, `service_id` (`vpce-svc-…`), `service_name`,
  `acceptance_required`, `private_dns_name`, `region`, `tags`. Source:
  `ec2:DescribeVpcEndpointServiceConfigurations`.
- `aws_core__aws_vpc_endpoint`: `name`, `vpc_endpoint_id` (`vpce-…`), `endpoint_type` (AWS's enum),
  `service_name`, `private_dns_enabled`, `region`, `tags`. Source: `ec2:DescribeVpcEndpoints`.
- `CONSUMES_ENDPOINT_SERVICE` (endpoint → endpoint service), for an endpoint whose service is a
  modelled PrivateLink service. An AWS-service endpoint (for example S3) is recorded only in
  `service_name`.
- The service's load balancer **reuses `ROUTES_TRAFFIC`**, with the endpoint service added as a
  source. The service forwards consumer traffic to the NLB or GWLB behind it, which is the same
  relationship a load balancer or route table already records with that edge.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-privatelink-1 | Keyed On AWS Ids | Implemented | Endpoint service and endpoint declare `NATURAL_KEY` on `service_id` and `vpc_endpoint_id`. | |
| req-aws-core-privatelink-2 | Consumer Edge | Implemented | `CONSUMES_ENDPOINT_SERVICE` declares endpoint → endpoint service only. | |
| req-aws-core-privatelink-3 | Provider Routing Reuses ROUTES_TRAFFIC | Implemented | The endpoint service is a `ROUTES_TRAFFIC` source. | |

### Route 53 Resolver DNS Firewall
----
RID: `req-aws-core-dns-firewall`

Status: `Implemented`

#### Implementation

- `aws_core__aws_route53_resolver_firewall_rule_group`: `name`, `rule_group_id` (`rslvr-frg-…`),
  `rule_count`, `block_domain_lists`, `allow_domain_lists`, `alert_domain_lists`, `region`, `tags`.
  The rules are summarised as typed name lists, one per action, with no rule blob. Source:
  `route53resolver:ListFirewallRules` (`FirewallDomainListId`, `Action`) joined to
  `GetFirewallDomainList` (`Name`; AWS-managed lists keep AWS's name).
- `FILTERS_VPC_DNS` (rule group → VPC), one per `FirewallRuleGroupAssociation`, with
  `additionalProperties: false` properties `priority` (100-9900) and `mutation_protection`, both from
  `AssociateFirewallRuleGroup`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-dns-firewall-1 | Keyed On AWS Id | Implemented | The rule group declares `NATURAL_KEY = ("rule_group_id",)`. | |
| req-aws-core-dns-firewall-2 | Typed Rule Summary | Implemented | Domain lists are arrays of non-empty name strings per action; no rule or domain blob. | |
| req-aws-core-dns-firewall-3 | Association Edge | Implemented | `FILTERS_VPC_DNS` declares rule group → VPC and validates `priority` and `mutation_protection`, refusing any other property. | |

### ACM Private CA
----
RID: `req-aws-core-private-ca`

Status: `Implemented`

#### Implementation

- `aws_core__aws_acm_private_ca`: `name`, `ca_arn`, `ca_type` (`ROOT` / `SUBORDINATE`),
  `key_algorithm`, `status`, `usage_mode` (all AWS's enums), `subject_common_name`, `tags`. Source:
  `acm-pca:DescribeCertificateAuthority`.
- `ISSUED_BY_CA` (subordinate CA or ACM certificate → issuing private CA): the CA chain for the
  `pki` account, and which private CA issued an ACM private certificate (`CertificateAuthorityArn`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-private-ca-1 | Keyed On CA ARN | Implemented | The CA declares `NATURAL_KEY = ("ca_arn",)`; the ARN validates against the acm-pca shape or is blank. | |
| req-aws-core-private-ca-2 | Typed Enums | Implemented | CA type, key algorithm, status and usage mode are AWS's enums (blank = not observed). | |
| req-aws-core-private-ca-3 | Issuer Edge | Implemented | `ISSUED_BY_CA` declares private CA or ACM certificate → private CA. | |

### v0 Non-Goals
----
RID: `req-aws-core-nongoals`

Status: `Proposed`

The following are explicitly deferred from v0:

- live AWS account discovery (querying a running account to populate the grid)
- AWS service catalog modeling (products vs. resource types)
- cross-account and cross-region edge inference
- CloudFormation/Terraform state import
- cost and billing data
- CloudWatch metrics and alarm integration
- Local Zones and Wavelength Zones
- GovCloud and China partition support
- plugin dependency declarations
- API endpoints for AWS-specific queries

#### Future

Live account discovery is the next major capability. It will require AWS credentials (assumed role or org-level access) and should populate all resource types, edges, and configuration metadata for a running AWS environment. The catalog refresh skill provides the foundation for this by maintaining the reference data that live discovery will build on.

**Editor's note (tap-plugin-aws-core#42):** live account discovery shipped since this section
was written — `collectors/boto3_collector` — but this list is otherwise accurate: the grid it
writes is still add/update only. See [Reconciliation Foundation — Falsifiers](#reconciliation-foundation--falsifiers) below and `req-aws-collector-reconcile`
(`specs/spec-aws-core-collector-v0.md`, Backlog) for what "grid-state reconciliation" now
means and how much of it exists.

### Reconciliation Foundation — Falsifiers
----
RID: `req-aws-core-reconcile-falsifiers`

Status: `Implemented`

`tap-plugin-aws-core#42`. This plugin had zero falsifier/reconciliation infrastructure: no
`[falsifiers]` manifest table, no base `Falsifier` subclass, nothing registered — the grid
accumulates AWS resources that no longer exist (`README.md`'s Roadmap item 1). This
requirement is the foundation two sibling PRs build specific-resource-type falsifiers on top
of, mirroring `tap-plugin-github-core`'s already-shipped `falsifiers.py` (github-core#151) and
core's `tap_grid.falsifiers` / `tap_grid.falsifier_testing`.

#### Implementation

- **`[falsifiers]` manifest table**, `tap-plugin.toml`: the foundation registered one entry,
  `aws_core__aws_subnet = "tap_plugin.aws_core.falsifiers.SubnetFalsifier"`; `tap-plugin-aws-core#43`
  adds `VpcFalsifier`, `Ec2InstanceFalsifier` and `SecurityGroupFalsifier` beside it, on a shared
  `_Ec2Falsifier(_AwsFalsifier)` (region from the `aws_region` dimension, else a type hint, else a
  fallback sweep that may find but never drop — `falsifiers.py`'s module docstring). `requires_tap`
  moved to `>=0.2.1` — 0.1.6, the release before it, refuses the `[falsifiers]` key at
  manifest parse (`tap_plugins/manifest.py::_parse_falsifiers`).
- **`tap_plugin/aws_core/falsifiers.py`**: a base `_AwsFalsifier(Falsifier)` mirroring
  `_GithubFalsifier`'s shape but simpler — `Boto3Collector` is single-account
  ("manifest-driven, single account, no deletes", its own docstring), so there is no
  GitHub-App-style `Reach`; the analogous check compares the resolved credential's STS
  caller-identity account against the candidate's own `aws_account` dimension
  (`collectors/boto3_collector/collector.py` stamps `dimensions = {"cloud": "aws",
  "aws_account": account_id, "aws_region": region_label}` on every node it writes). A mismatch,
  or a candidate with no `aws_account` dimension at all, is `UNDETERMINED(scope_unknown)`
  without a probe.
- **Subnet, not VPC, is the concrete proof — the task that opened this requirement suggested
  VPC, and that turned out to be wrong.** `tap_plugins/validate/service.py`'s
  `_check_falsifier_coverage` (a `loads`-level check every plugin repo's CI runs under
  `--strict`, promoting its warning to a hard failure) reads a model's `CONTAINMENT_EDGES` to
  find the edge's declared TARGETS, not the declaring model itself — a candidate is a child
  held under a parent, never the parent. `Vpc.CONTAINMENT_EDGES ==
  ("PARTITIONED_INTO_SUBNET__aws_core",)` (`req-aws-core-placement`) and that edge's target
  is `aws_core__aws_subnet`, so **Subnet** is the one type this plugin's existing containment
  declaration already marks reconcilable — not VPC, which nothing today makes a containment
  target of anything. Registering a `VpcFalsifier` instead would have been unreachable
  infrastructure that also left the coverage check's one real warning unaddressed, which
  would red `validate_plugin --strict` the moment `requires_tap` moved to a core release
  that carries the check (as this PR's own `requires_tap` bump does).
- **`SubnetFalsifier(_AwsFalsifier)`**: probes `ec2:DescribeSubnets(SubnetIds=[subnet_id])`
  in the candidate's own region; compares AWS's `SubnetId` (the grid's `NATURAL_KEY`) and
  `OwnerId`. `InvalidSubnetID.NotFound` (and the generic `*.NotFound` / `*NotFoundException`
  AWS error-code shapes every service follows) is `not_found`; `UnauthorizedOperation` /
  `AccessDenied(Exception)` is `forbidden`; a rate-limit code is `rate_limited`; anything else,
  including a `BotoCoreError`, is `errored` — never guessed at.
- **`AwsAccount` / `AwsOrganization` declare `CONTAINMENT_EDGES = ()` explicitly**, each with a
  comment citing why, rather than leaving it an unexplained inherited default:
  - Cascade requires the retiring node to be the edge's SOURCE
    (`tap_grid/models.py::BaseModel.__init_subclass__`: `CONTAINMENT_EDGES ⊆ OUTBOUND_EDGES`;
    `tap_grid/services/_impl.py::_contained_children` walks `from_entity_id=<parent>`).
    `BELONGS_TO_ACCOUNT` (resource → account) and `NESTED_UNDER_PARENT` (OU/account →
    OU/organization) both point child → parent, so neither model is ever a source of an edge
    reaching something it "owns" — this was already the `req-aws-core-organizations` ruling
    above ("Both edges point child → parent... an account also outlives its organization"),
    restated here as an explicit class-level declaration.
  - `edges/BELONGS_TO_ACCOUNT.edge.json` and `edges/RESIDES_IN_VPC.edge.json` both carry the
    same disclaimer in their own manifest description: "a reference, not containment" — RAM
    sharing and `TAP_CASCADE_MAX_CLOSURE` fan-out for `BELONGS_TO_ACCOUNT` specifically. A
    blanket account-level cascade over all 52 `BELONGS_TO_ACCOUNT` source types would
    contradict that already-documented design, not fix a gap.
  - Retiring an account therefore ends its resources' `BELONGS_TO_ACCOUNT` edges (the
    tombstone endpoint rule) and leaves the resources themselves live; each resource type's
    own truth is a question for that type's own falsifier (the sibling PRs' work), never a
    blanket account-level cascade.
- **`AwsOrganization` has no falsifier; `AwsAccount` now does (amended by tap-plugin-aws-core#50,
  `req-aws-core-organizations-collect` below).** The account-identity reasoning above
  (`Boto3Collector.run()` treats the run's OWN credential/region-scope/account-identity failure
  as unrecoverable, mirroring `tap-plugin-github-core`'s foundation-layer abort,
  `specs/spec-github-core-reliability.md` `req-github-core-reliability-absence`) still holds for
  the boto3 manifest engine's single-account scope, and is why `AwsOrganization` — the credential
  cannot lose sight of its OWN account, and nothing contains the organization — has none. It does
  not apply to which OUs and accounts an **organization** holds: that is an external,
  independently-falsifiable fact (`req-grid-reconcile-falsifier`), which is what
  `OrganizationalUnitFalsifier` and `AccountFalsifier` (`req-aws-core-organizations-collect`)
  judge. `AwsOrganization` additionally still has no collector emitting a candidate FOR it (it is
  never itself a containment target), so this paragraph's original "no collector at all"
  observation is retired without contradicting the row below it.
- **Candidates now flow from a live run for the Organizations tree only.** `boto3_collector`
  still does not produce completeness statements for its manifest-driven resource types
  (`req-aws-collector-reconcile`, `specs/spec-aws-core-collector-v0.md`, still Backlog) — Subnet
  stays judging-layer-only, proved by `tap_grid.falsifier_testing.run_four_cases` against a fake
  `ec2` client (`tap_plugin/aws_core/tests/test_falsifiers.py`) with no live surface behind it.
  The Organizations tree is the exception: `collectors/boto3_collector/organizations.py` records
  one completeness surface per parent listing it reads to the end
  (`req-aws-core-organizations-collect-4`), so `OrganizationalUnitFalsifier` and
  `AccountFalsifier` are reachable from a real run today.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-reconcile-falsifiers-1 | Manifest Table | Implemented | `tap-plugin.toml` declares `[falsifiers]` with `aws_core__aws_subnet`; `requires_tap` is `>=0.2.1`. | |
| req-aws-core-reconcile-falsifiers-2 | Four Proof Cases | Implemented | `SubnetFalsifier` produces `PRESENT_AT_PROBE` / `DROPPED_FROM_OBSERVATION` / `UNDETERMINED(forbidden)` / `REIDENTIFIED` against a fake `ec2` client, run through `tap_grid.falsifier_testing.run_four_cases`. | |
| req-aws-core-reconcile-falsifiers-3 | Single-Account Scope Check | Implemented | A candidate whose `aws_account` dimension does not match the falsifier's resolved credential account is `UNDETERMINED(scope_unknown)` without a probe. | |
| req-aws-core-reconcile-falsifiers-4 | Account/Org Declare No Containment Of Their Own | Superseded | Both originally declared `CONTAINMENT_EDGES == ()`. Neither does anymore, for two independent reasons: `AwsAccount`'s is superseded by `req-aws-core-reconcile-containment` below (containment for the five account-exclusive types it owns); `AwsOrganization`'s is superseded by `req-aws-core-organizations-collect-2` (its two OU/account containment edges). `BELONGS_TO_ACCOUNT` stays unreversed for every other type `AwsAccount` owns, and `AwsAccount` remains a containment TARGET of `AwsOrganization` (`ENROLLS_ACCOUNT`), never a reversal either. | Superseded by two separate PRs (tap-plugin-aws-core#43 and #50) for two separate reasons; neither reverses `BELONGS_TO_ACCOUNT`. |
| req-aws-core-reconcile-falsifiers-5 | Account/Org Falsifier Registration | Amended | `AwsOrganization` still has no falsifier (nothing contains it; it also still has no collector emitting a candidate for it). `AwsAccount` now does — `AccountFalsifier`, `req-aws-core-organizations-collect-3` — because which accounts an organization holds is an external, falsifiable fact distinct from the collector's own account identity, which is what the foundation-abort reasoning this row originally generalized from actually covers. | Superseded by tap-plugin-aws-core#50; the original all-or-nothing reading of this row was too broad. |
| req-aws-core-reconcile-falsifiers-6 | Completeness Statements — First Surfaces (tap-plugin-aws-core#43, #49, #50) | Implemented | `boto3_collector` now produces completeness surfaces from three independent sources: its five account-scoped `containment` manifest entries (IAM role/user/policy, OIDC provider, S3 bucket — `req-aws-core-reconcile-containment-2`), its four region-scoped `containment` manifest entries (VPC, subnet, EC2 instance, security group — `req-aws-core-regional-containment`), and, independent of the manifest engine entirely, its own Organizations-tree read (`req-aws-core-organizations-collect-4`). Every other manifest-driven listing still records none. | Narrowed by tap-plugin-aws-core#43, #49 and #50: this row no longer describes every reconcilable type as backlog; see [Account-Scoped Containment](#account-scoped-containment--iam--s3-reconcile) and [Region-Scoped Containment](#region-scoped-containment). |

### Account-Scoped Containment — IAM & S3 Reconcile

RID: `req-aws-core-reconcile-containment`

Status: `Implemented`

`tap-plugin-aws-core#43`. The falsifier foundation above (`req-aws-core-reconcile-falsifiers`)
and the sibling storage/IAM falsifiers (`aws-core-tap#41`) built the JUDGING half of reconcile
with nothing to judge: `AwsAccount.CONTAINMENT_EDGES` was empty, so no IAM role, IAM user,
customer-managed IAM policy, IAM OIDC provider or S3 bucket could ever become a retirement
candidate, however correct its falsifier. This requirement builds the missing FAN-OUT half for
exactly those five types — the ones an AWS account owns exclusively, never shares, and whose
account-scoped listing is a complete inventory of them.

#### Implementation

- **Five NEW parent → child edge types**, each `aws_core__aws_account` → one owned type:
  `OWNS_IAM_ROLE__aws_core`, `OWNS_IAM_USER__aws_core`, `OWNS_IAM_POLICY__aws_core` (scoped to
  customer-managed policies — an AWS-managed policy belongs to AWS, not the account),
  `OWNS_OIDC_PROVIDER__aws_core`, `OWNS_BUCKET__aws_core`. Declared on `AwsAccount`'s
  `OUTBOUND_EDGES` and `CONTAINMENT_EDGES` (superseding the empty declaration
  `req-aws-core-reconcile-falsifiers-4` made, with the comment there rewritten to say why:
  these five are account-EXCLUSIVE — never RAM-shared, never regional — which is exactly the
  property `BELONGS_TO_ACCOUNT` lacks for the general resource population and why that edge
  stays an unreversed reference). `ATTACHES_POLICY__aws_core` (role/user → customer-managed
  policy) and `TRUSTS_ACCOUNT__aws_core` (role → the cross-account accounts its trust policy
  names) are two further edges the same fan-out work makes possible, not containment
  themselves.
- **A `containment` manifest block** (`aws_resource_manifest.schema.json`), on the four entries
  it now names (`aws_core__aws_iam_role`, `aws_core__aws_iam_user`, `aws_core__aws_iam_policy`,
  `aws_core__aws_iam_oidc_provider`, `aws_core__aws_s3_bucket`): `{parent: "account", relation,
  edge_type, why}`. The collector emits the account → item edge for every item a `containment`
  entry's listing returns (`collectors/boto3_collector/edges.py::emit_containment`), from the
  credential's own resolved account (STS `GetCallerIdentity`), never from anything the item
  itself claims.
- **The completeness seam** (`collectors/boto3_collector/listing.py`): a `ListingWalk` per
  `containment` entry, filled in by the source driver while it consumes pages
  (`source.py::iter_listing` for a plain `aws_op`; the four new `custom_fn`s —
  `iam_roles_described`, `iam_users_described`, `iam_customer_policies_listed`, and
  `iam_oidc_providers_described`'s existing one-call walk — for the rest) and turned into an
  authored completeness surface (`surface_statement`) after the batch is submitted
  (`collector.py::run`, mirroring `tap_plugin.github_core`'s `_note_listing` /
  `record_surface` sequencing: the subject is resolved to the account's own grid id, which this
  run's batch just wrote). `enumeration_complete` is derived from the walk itself — the final
  page's own continuation marker (`page_says_more`), never asserted by the collector — and
  `source_consistent` is always `"unknown"` with a reason: AWS documents no snapshot guarantee
  across the pages of any of these listings.
- **IAM role and user identity + posture fields.** `IamRole` gains `role_id`,
  `permissions_boundary_arn`, `last_used_at`, `attached_policy_arns`, `trusted_account_ids`,
  `trusted_services`, `trusts_wildcard_principal`; `IamUser` gains `user_id`,
  `permissions_boundary_arn`, `password_last_used`, `attached_policy_arns`, `mfa_enabled`
  (widened to nullable — `False` used to mean both "no MFA" and "not read"); `IamPolicy` gains
  `policy_id`, `default_version_id`, `attachment_count`, `is_attachable`. `role_id` / `user_id`
  / `policy_id` are AWS's own immutable ids, not reused across a delete-and-recreate under the
  same ARN — the concrete answer to `aws-core-tap#41`'s flagged gap ("a genuinely open
  follow-up... only AWS's own immutable RoleId/UserId would catch" a same-path recreation).
  `ListRoles` / `ListUsers` omit `PermissionsBoundary`, `RoleLastUsed` and `Tags` by AWS's own
  documented contract, so each role/user is read again with `GetRole` / `GetUser` (a `hydrate`
  op, per item, alongside `ListAttached*Policies`). `IamUser` and `IamPolicy` also gain the
  canonical `tags` field (`req-aws-core-fields-4`) — both were manifest-collected but had never
  carried it, a v0.4.0-scar shape `test_aws_core_tags_field.py` derives from the manifest
  specifically so this cannot recur silently.
- **The trust-policy summary** (`collectors/boto3_collector/iam_trust.py`,
  `summarize_trust_policy`): partition-aware ARN parsing (`aws`, `aws-us-gov`, `aws-cn`) reduces
  a role's `AssumeRolePolicyDocument` to `trusted_account_ids` (every OTHER account an `Allow`
  statement's `Principal.AWS` names — the cross-account assume-role targets an organization
  rollout needs), `trusted_services` and `trusts_wildcard_principal`. Only `Effect: Allow`
  grants; `Condition` is not evaluated, so the field says who is NAMED and the wildcard flag
  says the name is unconditional, without claiming to evaluate IAM. Feeds `TRUSTS_ACCOUNT__aws_core`.
- **`IamOidcProviderFalsifier`** (`falsifiers.py`, registered in `[falsifiers]`): the fifth
  falsifier this containment makes reachable; `GetOpenIDConnectProvider` by ARN, the same
  "looked up by the value under test" reasoning `aws-core-tap#41`'s `IamPolicyFalsifier` gives
  for why `REIDENTIFIED` cannot occur. The other four falsifiers this containment activates
  (`S3BucketFalsifier`, `IamRoleFalsifier`, `IamUserFalsifier`, `IamPolicyFalsifier`) are
  `aws-core-tap#41`'s and are not duplicated here.
- **GovCloud region handling.** IAM and STS are global per account AND PARTITION — there is no
  `us-east-1` in `aws-us-gov`. `aws_account_singleton`, `iam_roles_described`,
  `iam_users_described`, `iam_customer_policies_listed` and `iam_oidc_providers_described` all
  take the engine's region-bound `client_for` in preference to a hardcoded `us-east-1` session
  client, and `Boto3Collector.run`'s `us-east-1`-region-scope warning (CloudFront/ACM tags) is
  now conditioned on the region set actually being commercial-partition, so a GovCloud-only run
  is not warned about a commercial-only concern it cannot have.

#### What this deliberately does not do

- **The other ~47 `BELONGS_TO_ACCOUNT` source types stay references.** EC2 instances, VPCs and
  the rest are regional, some are RAM-shareable, and an account's full resource fan-out can
  exceed `TAP_CASCADE_MAX_CLOSURE`; each needs its own regional listing and its own
  containment decision, not a blanket account-level one. That remains
  `req-aws-collector-reconcile`, Backlog.
- **No scope/region node.** The design this requirement's predecessor named as "the real
  substrate" (a scope node per account and region) is still unbuilt; these five containment
  edges are account-global (IAM) or account-wide-across-regions (S3 `ListBuckets`), so they did
  not need it. A regional type still does.
- **Attached AWS-managed policies are not graph edges.** `ATTACHES_POLICY__aws_core` is scoped
  to customer-managed policies, whose nodes this collector holds; the full attachment list
  (AWS-managed included) lives on `attached_policy_arns`, since an edge to an uncollected node
  would only dangle.

### Region-Scoped Containment
----
RID: `req-aws-core-regional-containment`

Status: `Implemented`

`tap-plugin-aws-core#49`. Before this, no regional compute/network type had a containment
parent: `Vpc.CONTAINMENT_EDGES` reached only `aws_subnet` (`req-aws-core-placement`), and every
other type — VPC itself, EC2 instances, security groups, and the rest of the regional surface —
had none, so `req-aws-core-reconcile-falsifiers`' falsifiers (and the sibling PR,
tap-plugin-aws-core#44, that builds four of them) had no candidates to judge: the collector
recorded no completeness statement for any listing, so `tap_grid.candidates.derive_candidates`
had nothing to derive from. This closes that gap for four types and builds the substrate the
rest can extend.

#### Implementation

- **`aws_core__aws_account_region`** (`models/aws_account_region.py`): one node per (account,
  region) the collector's credential is scoped to — the parent every regional containment edge
  fans out from. Deliberately not `AwsRegion` (shared by every account; a listing read by one
  account says nothing about another's resources — see the model's own docstring) and
  deliberately not `AwsAccount` (`req-aws-core-reconcile-falsifiers-4`'s ruling stands: one
  account-wide fan-out would exceed the cascade cap and conflate independently-succeeding or
  -failing regional listings). Identity is `(account_id, region_code)`
  (`req-grid-entity-natural-key`). `BELONGS_TO_ACCOUNT` (footprint -> account) is a reference,
  not containment, matching every other source of that edge.
- **One `HOSTS_*` containment edge per contained child type**
  (`tap_plugin/aws_core/regional.py`'s `REGIONAL_CHILDREN` table is the single place the shape is
  written down; `tests/test_regional_containment.py` checks every other source of truth — the
  `.edge.json` files, the manifest's `containment` blocks, `AwsAccountRegion`'s
  `OUTBOUND_EDGES`/`CONTAINMENT_EDGES` (written as literals — `validate_plugin`'s structure-level
  edge check reads them with an AST parser and refuses a computed expression), and the
  `[falsifiers]` table — against it). One edge type per child type, not one shared `HOSTS` edge:
  a completeness surface names the grid edge type its relation maps to, and candidate derivation
  fans out over every live edge of that type from the parent (`tap_grid.candidates._children`) —
  sharing one edge type across child types would let a complete VPC listing nominate an
  EC2 instance as a candidate whether or not the instance listing ever ran.
- **Four child types today: VPC, subnet, EC2 instance, security group** — the task's own
  priority order, and, together with existing `PARTITIONED_INTO_SUBNET` (VPC -> subnet), the
  ones tap-plugin-aws-core#44's falsifiers are built for. Route table, internet gateway, NAT
  gateway, network ACL, Elastic IP, VPC endpoint, EBS volume and RDS instance are all
  region-scoped and belong in this table, but are deliberately NOT added yet: each needs its own
  falsifier first, or `validate_plugin --level loads --strict`'s falsifier-coverage check reds
  the moment a `CONTAINMENT_EDGES` target has no `[falsifiers]` row — the exact trap
  `req-aws-core-reconcile-falsifiers` named for `VpcFalsifier`. `regional.py`'s `NOT_YET_WIRED`
  worklist names all eight, so the gap is tracked, not merely absent.
- **All four falsifiers were already on `main` before this PR merged (tap-plugin-aws-core#44),
  registered ahead of a containment path reaching them** (`falsifiers.py`'s own module docstring:
  "become live the moment a containment edge reaches them"). This PR is that containment edge:
  `VpcFalsifier` / `SubnetFalsifier` / `Ec2InstanceFalsifier` / `SecurityGroupFalsifier` all
  start producing real candidates from a real collector run the moment it lands, with no further
  change needed on the falsifier side. (During review this PR's base was #46 and #44 was a still-
  open sibling; #44 merged first, so by the time this PR itself merged the two were already
  reconciled — `tests/test_regional_containment.py::TestEveryRegionalChild::
  test_falsifier_registered` asserts every containment target has a live `[falsifiers]` row.)
- **Per-region completeness, never "observed empty" for a region the credential could not
  read** (`tap_grid/specs/spec-grid-reconcile.md`, `req-grid-reconcile-evidence`).
  `collectors/boto3_collector/regions.py::read_region_facts` calls `ec2:DescribeRegions
  (AllRegions=True)` once per run and classifies every region the run's scope names as
  `enabled` (`OptInStatus` `opt-in-not-required` / `opted-in`), `disabled`
  (`not-opted-in` — the account has not opted in to a commercial opt-in region, or, in
  practice, the shape a GovCloud credential sees for `us-gov-east-1` before it is enabled) or
  `unknown` (the call failed, or the region is absent from its answer). A `disabled` region's
  containment listings are never called at all — `collector.py`'s region gate skips them before
  any request — and every surface for that region is authored `scope_authorized: false` /
  `enumeration_complete: false` with a `region_disabled` reason
  (`tests/test_boto3_collector_regional_containment.py::TestDisabledRegion`, proving the call
  itself never happens, not merely that its result is discarded). An `unknown` region's *empty*
  listing is likewise never read as complete (`containment.py::surface_of`'s
  `empty_unverified` branch) — only a NON-empty listing, or a positively `enabled` region,
  licenses `enumeration_complete: true`. GovCloud is exactly the case this exists for: a fresh
  `aws-us-gov` credential commonly has one of `us-gov-west-1` / `us-gov-east-1` enabled and the
  other not, and the wrong read (silently treating the unauthorized region as "checked, found
  nothing") is precisely the false-retirement failure mode `req-grid-reconcile-falsifier`
  exists to rule out.
- **Partition-aware.** `regions.py::partition_of` derives `aws` / `aws-us-gov` (`us-gov-`) /
  `aws-cn` (`cn-`) from the region code prefix — GovCloud is `aws-us-gov`, matching AWS's own
  naming, never inferred from the operator's own region string some other way. Stamped on
  `AwsAccountRegion.partition`. A region scope spanning two partitions is warned about once
  (`MIXED_PARTITION_SCOPE`): a credential resolves in exactly one partition, so the regions of
  the other(s) can never be read by it.
- **Ownership, not mere presence — the AWS RAM case.** A `containment` manifest entry may name
  an `owner_path` (the item's own `OwnerId` field). `containment.py::owner_of` reads it; a
  resource whose owner differs from the observing account gets `BELONGS_TO_ACCOUNT` toward its
  REAL owner but NO `HOSTS_*` edge from the footprint — observed, not hosted, so an AWS RAM
  share later revoked can never read as this account's own resource having been deleted
  (`tests/test_boto3_collector_regional_containment.py::TestEnabledRegion::
  test_shared_vpc_is_not_hosted_by_this_account_footprint`).
- **A resource's persisted `name`** (`projection.py::_name_from_tag`): VPC/subnet/security-group
  entries declare `name_tag: "Name"`; a resource carrying that tag is named by it, matching every
  AWS console's own convention, with the natural key as the fallback (an entry declaring no
  `fields.name` at all — VPC, subnet, EC2 instance — gets it from the same fallback, so the
  persisted `name` column and the projection's own display name never disagree).
- **`iter_aws_op` now reports a continuation marker on a call it could not paginate itself**
  (`source.py::continuation_of` / the `truncated` parameter): a `containment` listing's
  completeness cannot say `enumeration_complete: true` if the response it read was only a
  partial page (`containment.py::surface_of`'s `truncated` branch). Only wired for
  `containment` entries; every existing entry is unaffected (`truncated=None`).
- **What this PR does NOT cover** (see `NOT_YET_WIRED`, above, and the priority order the task
  set): route table, internet gateway, NAT gateway, network ACL, Elastic IP, VPC endpoint, EBS
  volume, RDS instance (each needs its own falsifier, paired with its containment row, together);
  ELB/ALB and target group (VPC-scoped but reached only via `RESIDES_IN_VPC`, a reference, not a
  `HOSTS_*` target, so they are collected — where a manifest entry exists — but not yet
  region-footprint-contained); Lambda, DynamoDB, and every other already-collected type this PR
  does not touch, none of which had containment before and none of which loses anything by this
  PR's absence. `HOSTS_EC2_INSTANCE` does not reach a security-group MEMBERSHIP edge from the
  instance (dropped from the manifest entry rather than misusing `RESIDES_IN_VPC` for it — a
  correct instance -> security-group edge type is a small, separate follow-up).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-reconcile-containment-1 | Five Account-Owned Edge Types | Implemented | `OWNS_IAM_ROLE__aws_core`, `OWNS_IAM_USER__aws_core`, `OWNS_IAM_POLICY__aws_core`, `OWNS_OIDC_PROVIDER__aws_core`, `OWNS_BUCKET__aws_core` declared, each `aws_core__aws_account` → the owned type, on `AwsAccount.OUTBOUND_EDGES`/`CONTAINMENT_EDGES`. | |
| req-aws-core-reconcile-containment-2 | Collector Emits Containment + Records Completeness | Implemented | The five listings are driven through `ListingWalk`; the collector emits the account → item edge per item and records a completeness surface per listing after batch submission, `enumeration_complete` derived from the walk, never asserted. | |
| req-aws-core-reconcile-containment-3 | BELONGS_TO_ACCOUNT Unreversed | Implemented | `BELONGS_TO_ACCOUNT` stays a resource → account reference for every type; only the five new edges are containment. | |
| req-aws-core-reconcile-containment-4 | IAM Immutable Ids | Implemented | `IamRole.role_id`, `IamUser.user_id`, `IamPolicy.policy_id` are collected and stored, closing `aws-core-tap#41`'s flagged same-path-recreation gap. | |
| req-aws-core-reconcile-containment-5 | Trust Policy Summary | Implemented | `summarize_trust_policy` derives `trusted_account_ids` / `trusted_services` / `trusts_wildcard_principal` from a role's `AssumeRolePolicyDocument`, partition-aware; feeds `TRUSTS_ACCOUNT__aws_core`. | |
| req-aws-core-reconcile-containment-6 | Fifth Falsifier | Implemented | `IamOidcProviderFalsifier` registered in `[falsifiers]`; the other four this containment activates are `aws-core-tap#41`'s, not duplicated. | |
| req-aws-core-reconcile-containment-7 | GovCloud-Reachable | Implemented | The account/IAM listings use the engine's region-bound client rather than a hardcoded `us-east-1`; the CloudFront/ACM region-scope warning is conditioned on a commercial-partition region being in scope. | |
| req-aws-core-reconcile-containment-8 | Regional Types Remain Backlog | Proposed | The ~47 other `BELONGS_TO_ACCOUNT` source types (regional or RAM-shareable) are unaddressed except where `req-aws-core-regional-containment` (below) now covers four of them; `req-aws-collector-reconcile` still tracks the rest. | Narrowed by tap-plugin-aws-core#49. |
| req-aws-core-regional-containment-1 | Account-Region Footprint | Implemented | `aws_core__aws_account_region`, keyed on `(account_id, region_code)`, emitted for every region in the run's scope. | |
| req-aws-core-regional-containment-2 | One Containment Edge Per Child Type | Implemented | `REGIONAL_CHILDREN` declares `HOSTS_VPC` / `HOSTS_SUBNET` / `HOSTS_EC2_INSTANCE` / `HOSTS_SECURITY_GROUP`; `AwsAccountRegion.CONTAINMENT_EDGES` and every `.edge.json` file agree, checked by `test_regional_containment.py`. | |
| req-aws-core-regional-containment-3 | Per-Region Completeness, Not Observed-Empty | Implemented | A disabled or unknown-status region's listing is never called / never counted complete when empty; `region_disabled` / `empty_unverified` reasons are recorded. | |
| req-aws-core-regional-containment-4 | GovCloud Partition-Aware | Implemented | `partition_of` derives `aws-us-gov` from `us-gov-*`; a mixed-partition scope is warned once. | |
| req-aws-core-regional-containment-5 | RAM Share Observed, Not Hosted | Implemented | `owner_path` on a containment entry routes `BELONGS_TO_ACCOUNT` to the real owner and withholds the `HOSTS_*` edge when it differs from the observing account. | |
| req-aws-core-regional-containment-6 | All Four Falsifiers Live | Implemented | `VpcFalsifier` / `SubnetFalsifier` / `Ec2InstanceFalsifier` / `SecurityGroupFalsifier` (tap-plugin-aws-core#44, #46) are all registered in `[falsifiers]`; `validate_plugin --level loads --strict`'s falsifier-coverage check is green for every `REGIONAL_CHILDREN` target. | |
| req-aws-core-regional-containment-7 | Remaining Regional Types Named, Not Silently Skipped | Proposed | `NOT_YET_WIRED` names 8 region-scoped types with no containment yet, each blocked on pairing a new row with a new falsifier. | Backlog. `req-aws-core-network-plane-5` wires six of the eight; EBS volume and RDS instance remain. |

### Network Plane Collection
----
RID: `req-aws-core-network-plane`

Status: `Proposed`

Collect the network plane a landing zone deploys, so egress and segmentation questions are answered
from collected data. Today most of it is vocabulary only: route table, IGW, NAT, EIP, NACL, VPC endpoint, transit gateway and attachment are models with no manifest entry (`collectors/boto3_collector/aws_resource_manifest.json`; `regional.py:86-95`).

#### Status Details

Proposed by the landing-zone epic, step 3. What a Gruntwork landing zone deploys per account is
`vpc-app`: public, private-app and private-persistence subnets, a route table per tier, an IGW, NAT
gateways with EIPs, per-tier NACLs, gateway and interface endpoints, and flow logs. VPC peering to a
management VPC is optional. A transit gateway or network firewall appears only as an Enterprise
customisation ([VPC-APP](https://docs.gruntwork.io/reference/modules/terraform-aws-vpc/vpc-app/), [AF-NET](https://docs.gruntwork.io/2.0/docs/accountfactory/architecture/network-topology)). highbar's design adds a transit gateway
with four attachments (highbar `grift/design-staging.grift.json`, branch `feat/org-layout-v2`). `regional.py:86-95` (`NOT_YET_WIRED`) already names six of
these types as the next regional containment rows.

#### Rule for sub-resources: what AWS addresses individually is a node

A route, a NACL entry and a security-group rule each have an identity AWS itself uses to delete them:
`DeleteRoute(RouteTableId, DestinationCidrBlock|…)`, `DeleteNetworkAclEntry(NetworkAclId, RuleNumber, Egress)`,
`RevokeSecurityGroupIngress(SecurityGroupRuleIds)`. Each is therefore a node, keyed on that identity
and contained by its parent with a falsifier and a per-parent completeness surface
(`req-aws-core-contained-type-triple`). That gives them a retirement path. The edges they emit
(a route's target, a rule's referenced group) end when they retire, instead of staying stale while
both endpoints live (`req-aws-core-reference-derivation`, below).

The rule, stated in full, has three cases:

1. **A sub-structure is a node** when AWS gives it its own identity within its parent (a minted id
   such as `rtbassoc-…`, `aclassoc-…`, `eipassoc-…`, an `IpId` or a resolver-rule association id,
   or a key AWS defines within the parent, such as a route's destination or a NACL entry's
   direction and rule number), **and** it carries a reference edge or attributes of its own. So
   route-table associations, NACL associations, Elastic IP associations, resolver endpoint IP
   addresses, resolver-rule associations and Config delivery channels are nodes, alongside routes,
   NACL entries, SG rules and TGW routes. The edge each carries then ends when AWS deletes that
   identity, instead of staying last seen.
2. **A relationship AWS addresses only by naming the two resources it joins stays a reference
   edge.** Examples are a TGW route-table association or propagation
   (`DisassociateTransitGatewayRouteTable(TransitGatewayRouteTableId, TransitGatewayAttachmentId)`), a policy
   attachment (`DetachPolicy(PolicyId, TargetId)`), a VPC endpoint's subnets and security groups
   (`ModifyVpcEndpoint` by id lists), an ENI's security groups, and a detector's administrator.
   There is no identity to retire, only the pair, so these are listed **last seen** in
   `req-aws-core-reference-derivation` until core re-derivation exists.
3. **A sub-structure with no reference edge stays a typed field** on its parent, even when AWS
   can address it: enabled policy types, enabled service principals, Security Hub's enabled
   standards, Control Tower's governed regions, a permission set's managed policies. A typed field
   is replaced whole on every write of its parent, so it cannot go stale the way an edge can.

**Keys, normalized.** A route's key is `(route_table_id, destination_kind, destination)`, with
`destination_kind` ∈ `ipv4|ipv6|prefix_list` naming which of `DestinationCidrBlock`,
`DestinationIpv6CidrBlock` or `DestinationPrefixListId` is set. An IPv6 CIDR is stored in its
compressed lowercase form, so two spellings of one prefix are one key. A TGW route's key is
`(tgw_route_table_id, destination_kind, destination)` with `destination_kind` ∈
`ipv4|ipv6|prefix_list`. `DestinationCidrBlock` carries IPv4 and IPv6 alike, so its kind is the
parsed address family, never assumed, and an IPv6 CIDR is normalized to the same compressed
lowercase form before keying. The EC2 route key classifies the same way: each CIDR is parsed, and
a value in the wrong member for its family is still keyed by its parsed family. A NACL entry's key is `(network_acl_id, egress, rule_number)`. An SG rule's
key is its `SecurityGroupRuleId`. Each association node's key is its AWS-minted id.

#### Types, tags and retirement

"Lane" is the `req-aws-collector-tags` lane. Every EC2 `Describe*` below returns its tags inline as
`[{Key, Value}]` (read: botocore 1.43.104 `ec2` model), so the EC2 types use the `field` lane. That
costs no extra call and does not depend on the RGTA sweep, whose failure today writes a false empty
(`req-aws-collector-tags`, *Landing-Zone Amendments*).
"Contained by" is the containment parent and edge, so the type has a candidate. "Falsifier" is the
type's probe and what counts as gone. Edge names are working names, finalized through the
`add-edge` skill.

**Error codes are not verified.** The not-found codes in the falsifier columns come from AWS API knowledge (inferred). Each must be checked against the pinned botocore and the service's documented errors before a falsifier is written, as unified-systems-com/aws-core-tap#15 requires. A code that turns out to be shared with "you may not look" makes that type's falsifier `UNDETERMINED`, never `DROPPED`.

| Type | Model today | Enumerate (read: botocore) | Tags (lane, path, shape) | Contained by | Falsifier: gone when | Reference edges |
| --- | --- | --- | --- | --- | --- | --- |
| `aws_route_table` | exists, **no `tags`** | `ec2:DescribeRouteTables` | field, `Tags[]`, list_kv | footprint, `HOSTS_ROUTE_TABLE` | `InvalidRouteTableID.NotFound` | `RESIDES_IN_VPC` (exists) |
| `aws_route_table_association` **(new)** | — | inside `RouteTables[].Associations[]`, keyed `RouteTableAssociationId` | AWS cannot tag an association (the `RouteTableAssociation` shape has no tags) | route table, `DECLARES_RT_ASSOCIATION` | the table's describe no longer lists the id, **or `AssociationState.State` = `disassociated`** | `ROUTES_FOR_SUBNET` (→ subnet, when `SubnetId` is set; `GatewayId` and `Main` are typed fields) |
| `aws_route` **(new)** | — | inside `RouteTables[].Routes[]` | AWS cannot tag a route | route table, `DECLARES_ROUTE` | the route table's describe no longer lists that destination | `ROUTES_TRAFFIC` (exists; source becomes the route) → each modeled target in *Route targets* below; every target member is also kept as a typed field; `state` = `active\|blackhole\|filtered` |
| `aws_internet_gateway` | exists, **no `tags`** | `ec2:DescribeInternetGateways` | field, `Tags[]`, list_kv | footprint, `HOSTS_INTERNET_GATEWAY` | `InvalidInternetGatewayID.NotFound` | `ATTACHED_TO_VPC` (exists) |
| `aws_nat_gateway` | exists, **no `tags`** | `ec2:DescribeNatGateways` | field, `Tags[]`, list_kv | footprint, `HOSTS_NAT_GATEWAY` | not found, **or `State` = `deleted`** | `RESIDES_IN_SUBNET` (exists); `USES_ELASTIC_IP` (→ EIP) |
| `aws_elastic_ip` | exists, **no `tags`** | `ec2:DescribeAddresses` (unpaginated) | field, `Tags[]`, list_kv | footprint, `HOSTS_ELASTIC_IP` | `InvalidAllocationID.NotFound` | — |
| `aws_eip_association` **(new)** | — | `Addresses[]` carrying an `AssociationId`, keyed by it | AWS cannot tag an association (inferred: no tag field on the address's association members) | Elastic IP, `HOLDS_EIP_ASSOCIATION` | the EIP's describe no longer carries that `AssociationId` | `ASSOCIATED_WITH_INTERFACE` (→ ENI, from `NetworkInterfaceId`) |
| `aws_network_acl` | exists, **no `tags`** | `ec2:DescribeNetworkAcls` | field, `Tags[]`, list_kv | footprint, `HOSTS_NETWORK_ACL` | `InvalidNetworkAclID.NotFound` | `RESIDES_IN_VPC` (exists) |
| `aws_network_acl_association` **(new)** | — | inside `NetworkAcls[].Associations[]`, keyed `NetworkAclAssociationId` | AWS cannot tag an association (the shape has no tags) | NACL, `DECLARES_ACL_ASSOCIATION` | the NACL's describe no longer lists the id (`ReplaceNetworkAclAssociation` mints a new one) | `FILTERS_SUBNET` (→ subnet) |
| `aws_network_acl_entry` **(new)** | — | inside `NetworkAcls[].Entries[]` | AWS cannot tag an entry | NACL, `DECLARES_ACL_ENTRY` | the NACL no longer lists (egress, rule number) | — (CIDR, ports, action are typed fields) |
| `aws_security_group_rule` **(new)** | — | `ec2:DescribeSecurityGroupRules` | field, `Tags[]`, list_kv | security group, `DECLARES_SG_RULE` | `InvalidSecurityGroupRuleId.NotFound` | `REFERENCES_SECURITY_GROUP` (→ SG); prefix list id is a typed field |
| `aws_vpc_endpoint` | exists, has `tags` | `ec2:DescribeVpcEndpoints` | field, `Tags[]`, list_kv | footprint, `HOSTS_VPC_ENDPOINT` | not found, **or `State` = `Deleted`** | `RESIDES_IN_VPC`, `RESIDES_IN_SUBNET`, `CONSUMES_ENDPOINT_SERVICE` (exist); `USES_SECURITY_GROUP` |
| `aws_vpc_flow_log` **(new)** | — | `ec2:DescribeFlowLogs` | field, `Tags[]`, list_kv | footprint, `HOSTS_FLOW_LOG` | `InvalidFlowLogId.NotFound` | `MONITORS_TRAFFIC` (→ VPC / subnet / ENI / transit gateway / TGW attachment / NAT gateway, per every `FlowLogsResourceType` value); `WRITES_LOGS` (exists; → log group / S3 bucket, normalized by `LogDestinationType` per *Target keys*; the S3 prefix is the typed field `log_destination_prefix`) |
| `aws_network_interface` **(new)** | — | `ec2:DescribeNetworkInterfaces(IncludeManagedResources=true)` | field, **`TagSet[]`**, list_kv | footprint, `HOSTS_NETWORK_INTERFACE` (owner only) | `InvalidNetworkInterfaceID.NotFound` | `RESIDES_IN_SUBNET` (extend sources); `USES_SECURITY_GROUP` |
| `aws_transit_gateway` | exists, has `tags` | `ec2:DescribeTransitGateways` | field, `Tags[]`, list_kv | footprint, `HOSTS_TRANSIT_GATEWAY` (**owner only**, RAM) | not found, or `State` = `deleted` | — |
| `aws_transit_gateway_attachment` | exists, has `tags` | `ec2:DescribeTransitGatewayAttachments` | field, `Tags[]`, list_kv | transit gateway, `HOLDS_TGW_ATTACHMENT` (observed from the gateway owner) | not found, or `State` = `deleted` | `ATTACHED_TO_TRANSIT_GATEWAY`, `ATTACHES_VPC`, `PEERS_WITH_TRANSIT_GATEWAY` (exist); `ASSOCIATED_WITH_TGW_ROUTE_TABLE`, `PROPAGATES_TO_TGW_ROUTE_TABLE` |
| `aws_transit_gateway_route_table` **(new)** | — | `ec2:DescribeTransitGatewayRouteTables`, then `GetTransitGatewayRouteTablePropagations` per table (for `PROPAGATES_TO_TGW_ROUTE_TABLE`) | field, `Tags[]`, list_kv | transit gateway, `HOLDS_TGW_ROUTE_TABLE` | not found, or `deleted` | — |
| `aws_transit_gateway_route` **(new)** | — | `ec2:SearchTransitGatewayRoutes` per table | AWS cannot tag a route | TGW route table, `DECLARES_TGW_ROUTE` | the search no longer returns that destination | `ROUTES_TRAFFIC` → each `TransitGatewayAttachments[].TransitGatewayAttachmentId`; `ResourceId`, `ResourceType`, `Type`, `State` and `TransitGatewayRouteTableAnnouncementId` are typed fields; a blackhole route has no attachment and no edge |
| `aws_vpc_peering_connection` **(new)** | — | `ec2:DescribeVpcPeeringConnections` | field, `Tags[]`, list_kv | footprint of the **requester** owner, `HOSTS_VPC_PEERING_CONNECTION` | not found, or `Status.Code` ∈ `deleted\|rejected\|expired\|failed` | `CONNECTS_VPC` (→ requester and accepter VPC, `side` property) |
| `aws_route53_resolver_endpoint` **(new)** | — | `route53resolver:ListResolverEndpoints` | service, `ListTagsForResource(ResourceArn)`, `Tags`, list_kv | footprint, `HOSTS_RESOLVER_ENDPOINT` | `ResourceNotFoundException` | `USES_SECURITY_GROUP` |
| `aws_route53_resolver_endpoint_ip` **(new)** | — | `ListResolverEndpointIpAddresses(ResolverEndpointId)`, keyed `(resolver_endpoint_id, IpId)` | AWS cannot tag an endpoint IP (`IpAddressResponse` has no ARN) | resolver endpoint, `DECLARES_ENDPOINT_IP` | the listing no longer names the `IpId`, **or `Status` ∈ `DETACHING\|DELETING\|FAILED_RESOURCE_GONE`** | `RESIDES_IN_SUBNET` (extend sources; → subnet) |
| `aws_route53_resolver_rule` **(new)** | — | `route53resolver:ListResolverRules` | service, as above | footprint of the **owner**, `HOSTS_RESOLVER_RULE` (RAM-shareable) | `ResourceNotFoundException` | `FORWARDS_THROUGH_ENDPOINT` (→ outbound endpoint) |
| `aws_route53_resolver_rule_association` **(new)** | — | `route53resolver:ListResolverRuleAssociations`, keyed by the association `Id` | AWS cannot tag an association (the shape has no ARN) | footprint of the VPC owner (the account whose listing returns it), `HOSTS_RESOLVER_RULE_ASSOCIATION` | `GetResolverRuleAssociation` → `ResourceNotFoundException`, **or `Status` = `DELETING`** | `ASSOCIATES_RESOLVER_RULE` (→ rule), `FORWARDS_VPC_DNS` (→ VPC) |

**Route targets.** Every member of botocore 1.43.103's EC2 `Route` shape is classified below, and
a test fails when the pinned shape gains a member this table does not name. Every target member,
modeled or not, is kept verbatim on the route node in a typed `targets` map
(`{member: value}` for each target member present). So a target with no node type is preserved,
not dropped, and gains an edge when its type is modeled.

| `Route` member | Role | Edge |
| --- | --- | --- |
| `DestinationCidrBlock`, `DestinationIpv6CidrBlock`, `DestinationPrefixListId` | destination (the key) | — |
| `GatewayId` = `local` | the VPC's local route | none; `targets.GatewayId = "local"` |
| `GatewayId` = `igw-…` | internet gateway | `ROUTES_TRAFFIC` → `aws_internet_gateway` |
| `GatewayId` = `vpce-…` | gateway VPC endpoint (S3, DynamoDB) or Gateway Load Balancer endpoint | `ROUTES_TRAFFIC` → `aws_vpc_endpoint`. The pinned `Route` shape has no `VpcEndpointId` member, so endpoint targets arrive here (inferred from the id prefix) |
| `GatewayId` = `vgw-…` | virtual private gateway | none (not modeled); typed field |
| `NatGatewayId` | NAT gateway | `ROUTES_TRAFFIC` → `aws_nat_gateway` |
| `TransitGatewayId` | transit gateway | `ROUTES_TRAFFIC` → `aws_transit_gateway` |
| `VpcPeeringConnectionId` | peering connection | `ROUTES_TRAFFIC` → `aws_vpc_peering_connection` |
| `NetworkInterfaceId` | network interface | `ROUTES_TRAFFIC` → `aws_network_interface` |
| `InstanceId` (with `InstanceOwnerId`) | NAT instance or appliance | `ROUTES_TRAFFIC` → `aws_ec2_instance`; AWS also fills `NetworkInterfaceId`, which gets its own edge |
| `EgressOnlyInternetGatewayId` | egress-only internet gateway | none (not modeled); typed field |
| `LocalGatewayId`, `CarrierGatewayId`, `CoreNetworkArn`, `OdbNetworkArn` | Outposts, Wavelength, Cloud WAN, ODB network | none (not modeled); typed fields |
| `IpAddress` | next hop from VPC Route Server | none; typed field |
| `Origin`, `State` | how the route was created; `active\|blackhole\|filtered` | — (typed fields) |

A TGW route's targets are `TransitGatewayAttachments[]` (`ResourceId`, `TransitGatewayAttachmentId`,
`ResourceType`). Each attachment id gets a `ROUTES_TRAFFIC` edge to the attachment node, and the
resource fields are kept as typed fields.

The state values were read from botocore 1.43.104's enums: `NatGatewayState` includes `deleted`,
the EC2 `State` enum includes `Deleted`, `TransitGatewayState` and `TransitGatewayAttachmentState`
include `deleted`, and `VpcPeeringConnectionStateReasonCode` includes `deleted`, `rejected` and
`expired`. AWS keeps returning a deleted NAT gateway, endpoint, peering or attachment for a while
after deletion (inferred from those enums; the retention period is not verified). These are the
soft-delete hazards unified-systems-com/aws-core-tap#15 names: a falsifier that counted "the describe answered"
as present would never retire them. The collector filters these states out of the listing, with a
recorded count, so that it does not re-observe a dead object as live.

**Ownership, not presence.** A RAM-shared transit gateway, subnet or resolver rule, or the accepter
side of a peering connection, is observed from an account that does not own it. Each such entry
declares an `owner_path` (`req-aws-core-regional-containment-5`). `BELONGS_TO_ACCOUNT` goes to the
real owner, and no `HOSTS_*` edge is emitted from a non-owner's footprint.

**Tags field rollout.** Route table, IGW, NAT gateway, EIP and NACL have no `tags` field today (read:
`grep -c tags` is 0 in each model file). Each gains it, by an additive migration
(`req-aws-core-fields-4`). New types are born with it (`req-aws-collector-tags-13`). A type AWS
cannot tag (route, NACL entry, TGW route, route-table, NACL and EIP associations, resolver endpoint IP, resolver-rule association) declares `{"source": "none", ...}` (`req-aws-collector-tags-12`).

**Sensitivity.** Security-group rule and NACL descriptions are `free_text`. Resolver endpoint IPs and
flow-log destinations are `reviewer_judgement` reviews (`req-aws-collector-manifest-6`). No entry
persists `configuration` until it has been reviewed (`req-aws-collector-manifest-7`).

**GovCloud.** Every EC2 operation above is in `aws-us-gov` (read: botocore 1.43.104 endpoint data). Route 53 Resolver's availability in GovCloud is **not verified**. An
`EndpointConnectionError` there is reported by the existing partition hint (`collector.py:571-575`)
and is never read as an empty listing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-network-plane-1 | Collected | Proposed | Each type in the table has a manifest entry (or, for sub-resources, is emitted from its parent's entry) and appears on the grid from a collection run against a fake source. | |
| req-aws-core-network-plane-2 | Tags On Every Type | Proposed | Route table, IGW, NAT gateway, EIP and NACL gain the `tags` field by additive migration; every type in the table carries it and declares its lane per the table. | `req-aws-collector-tags-13`. |
| req-aws-core-network-plane-3 | Field Lane For EC2 | Proposed | EC2 types take tags from the enumerate item (`field` lane, `Tags[]`, ENI `TagSet[]`), never from the RGTA sweep. | Keeps these types off the RGTA sweep and its false-empty write. |
| req-aws-core-network-plane-4 | Addressable Sub-Resources Are Nodes | Proposed | Routes, NACL entries, security-group rules, TGW routes, route-table associations, NACL associations, Elastic IP associations, resolver endpoint IPs and resolver-rule associations are nodes keyed on AWS's own identity (normalized as *Keys, normalized* states), contained by their parent, each with a registered falsifier; relationships AWS addresses only by their two ends stay reference edges, and sub-structures with no edge stay typed fields, per the three-case rule. | `req-aws-core-reference-derivation`, for these edges. |
| req-aws-core-network-plane-5 | Every Type Has A Retirement Path | Proposed | Every type in the table is a containment target with a `[falsifiers]` row; `validate_plugin --level loads --strict` is green; `NOT_YET_WIRED` no longer names route table, IGW, NAT gateway, NACL, EIP or VPC endpoint. Each containment pair also records the completeness surface `req-aws-core-contained-type-triple` lists for it. | EBS and RDS stay on the worklist (not network plane). |
| req-aws-core-network-plane-6 | Soft-Deleted Is Absent | Proposed | A NAT gateway, VPC endpoint, transit gateway, attachment, peering connection, route-table association, resolver endpoint IP or resolver-rule association in a deleted, disassociated, detaching, rejected, expired or failed state is not projected as live, and its falsifier treats that state as not found. | unified-systems-com/aws-core-tap#15 hazards. |
| req-aws-core-network-plane-7 | Owner, Not Observer | Proposed | RAM-shared and cross-account types route `BELONGS_TO_ACCOUNT` to the owner and emit `HOSTS_*` only from the owner's footprint. | `req-aws-core-regional-containment-5`. |
| req-aws-core-network-plane-8 | Edge Names Through The Skill | Proposed | Every new edge type is named and declared through the `add-edge` skill; the working names here are not canon. | |

### Account Owns Its Region Footprints
----
RID: `req-aws-core-account-footprint`

Status: `Proposed`

Close the break in the containment chain at account → footprint. Today
`aws_account_region` has no containing parent and no falsifier. Its edge to the account,
`BELONGS_TO_ACCOUNT`, is a reference (`collectors/boto3_collector/containment.py:59-66`). So
organization → account → {VPC, subnet, instance, SG} is not a chain, and a footprint, once written,
is never retired.

#### Implementation

- **Sequencing (binding).** This requirement ships only after `req-aws-core-organization-membership`
  (unified-systems-com/aws-core-tap#68). Before the membership exists, `AccountFalsifier` can retire
  an account, and this edge would extend that cascade to every footprint and its regional network
  plane. Epic unified-systems-com/aws-core-tap#62 records the order.
- `OWNS_REGION_FOOTPRINT` (account → footprint), containment, in `AwsAccount.CONTAINMENT_EDGES`
  beside the five `OWNS_*` edges. The listing behind it is the run's own region scope for that
  account, which the collector already iterates (`collector.py:401-410`). Its completeness surface
  is authored per account.
- **`FootprintFalsifier` never drops.** What would make a footprint "gone" is a region the account
  disabled, or a region the operator stopped scoping. Neither means the resources in it no longer
  exist: opting out of a region does not delete them. So the falsifier answers
  `PRESENT_AT_PROBE` when `DescribeRegions` reports the region enabled for the account, and
  `UNDETERMINED` otherwise. It never answers `DROPPED_FROM_OBSERVATION`. It exists so that the
  `falsifier-coverage` check passes honestly, which is the same "may find, never drop" posture as
  `_Ec2Falsifier`'s fallback sweep (`falsifiers.py` module docstring).
- **Consequence, stated:** a deliberate `delete_node(cascade="contained")` of an account now reaches
  its footprints and, through `HOSTS_*`, everything each footprint contains and everything below
  that (`req-aws-core-contained-type-triple`): the regional network plane with its routes,
  associations, rules, TGW children and resolver children, plus the landing-zone types hosted
  there (landing zone and its controls and baselines, the Identity Center instance and its
  children, the security services). The closure is bounded by
  `TAP_CASCADE_MAX_CLOSURE`. A closure over the cap refuses rather than half-applying.
  `req-aws-core-organization-membership` ensures no automatic path retires an account.
- **The cascade-cap reasoning still holds.**
  `req-aws-core-regional-containment` (Implemented) chose the footprint over `AwsAccount` as the
  parent of regional resources because "one account-wide fan-out would exceed the cascade cap and
  conflate independently-succeeding or -failing regional listings". Both halves of that reason are
  about the parent that **derives candidates** for regional resources, and that parent is still the
  footprint: each region's listing stays its own surface, so a failed region withdraws only its own
  candidates. This requirement adds one level above it, and the listing behind
  `OWNS_REGION_FOOTPRINT` is the run's region scope, a handful of rows. What changes is the reach of
  a cascade that starts at the account. No automatic path starts one: `FootprintFalsifier` never
  drops a footprint, and after `req-aws-core-organization-membership` no falsifier retires an
  account. The only such cascade is a deliberate operator delete, where a closure over
  `TAP_CASCADE_MAX_CLOSURE` is refused whole, never half-applied. That is the outcome the cap exists
  to produce: the operator retires footprints first, or raises the cap knowingly.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-account-footprint-1 | Account Contains Footprints | Proposed | `AwsAccount.CONTAINMENT_EDGES` includes `OWNS_REGION_FOOTPRINT`; every footprint the collector writes has that edge from its account. | |
| req-aws-core-account-footprint-2 | Never-Drop Falsifier | Proposed | `FootprintFalsifier` is registered, returns `PRESENT_AT_PROBE` or `UNDETERMINED`, and has a test proving it never returns `DROPPED_FROM_OBSERVATION`. | |
| req-aws-core-account-footprint-3 | Cascade Reach Tested | Proposed | A contained cascade from an account retires its footprints and their `HOSTS_*` children, and refuses past `TAP_CASCADE_MAX_CLOSURE`. | |

### Every Contained Type Has Its Three Parts
----
RID: `req-aws-core-contained-type-triple`

Status: `Proposed`

Core retires nothing unless three parts agree on the same (parent, edge type). Containment must be
declared in the parent's `CONTAINMENT_EDGES`. A completeness surface must name that edge type for
that parent. And the child type needs a registered falsifier. Candidate derivation is
`children(P, R) − observed(this run) − outside_scope`, read per parent from a surface whose
`edge_type` is `R` (`req-grid-reconcile-candidates`; `tap_grid.candidates`). A containment edge
with no surface never nominates anything, and a surface with no falsifier stops at dispatch. This
requirement lists every (parent, edge type) the landing-zone epic adds, across
`spec-aws-core-v0.md`, `spec-aws-core-landing-zone.md` and `spec-aws-core-collector-v0.md`. Each
row gives the listing that backs its surface and when that surface is complete.

#### Implementation

**Rules every row follows.**

- **One surface per observed parent.** It is recorded for every parent the run observed, and never
  omitted. A parent observed with no children records a **complete, empty** surface, for example
  a security group with zero rules, a transit gateway with no attachments, or an instance with no
  groups. That is what lets the last child's removal nominate it.
- **Incomplete, with the reason, when the listing did not finish.** That covers a failed call, a
  partial page, a filtered listing without a passing positive control (`req-grid-reconcile-evidence`),
  an unknown or disabled region (`req-aws-core-regional-containment-3`), and an unparseable
  document. A parent the run did not observe records no surface. Core's per-parent prerequisite
  already refuses to derive under it.
- **A child listing read once per region covers every parent it groups.** Security-group rules,
  TGW attachments and TGW route tables come from one regional listing, grouped by the parent's id.
  Each observed parent's surface is complete only if that regional listing read to its end.
- **Nested listings aggregate.** When one (parent, edge type) is filled by several listings, it
  gets one surface, complete only when every listing finished
  (`req-aws-core-organizations-completeness-13`, `-14`; `req-aws-landing-zone-identity-center-5`).
- **Owner only.** For a RAM-shareable parent (transit gateway), only the owner's run records the
  surface, matching where `HOSTS_*` is emitted (`req-aws-core-network-plane-7`).

**Listings read their full set.** Some listings return less than everything by default, and a
default-narrowed answer read as complete would nominate whatever it left out. Each listing below
is called with the flag that widens it. Each flag has a test, so that a child or hidden item
appears in the fake-source run (`-6`). The flags were read from botocore 1.43.103's input shapes:
every listing the PR names was scanned for `include*`, `*Children`, `All*`, `type` and status
filters.

| Listing | Default (read: botocore) | Called with |
| --- | --- | --- |
| `controltower:ListEnabledBaselines` | `includeChildren` defaults to false (documented) | `includeChildren: true`; child baselines carry `parentIdentifier`, kept as a typed field |
| `controltower:ListEnabledControls` | `includeChildren` default not documented | `includeChildren: true`, never left to the default |
| `ec2:DescribeNetworkInterfaces` | omits interfaces AWS services manage when managed-resource visibility is hidden | `IncludeManagedResources: true` |
| `config:DescribeConfigurationRecorders` | with no name, returns only the customer-managed recorder | not used to enumerate: `config:ListConfigurationRecorders` (paginated, unfiltered) lists customer-managed and service-linked recorders, then `DescribeConfigurationRecorders(Arn=…)` per recorder |
| `accessanalyzer:ListAnalyzers` | `type` optional; behavior when absent not documented | one call per value of the pinned `Type` enum (six), one aggregate surface complete only when all six finish |
| `sso-admin:ListPermissionSetsProvisionedToAccount` | `ProvisioningStatus` is a filter | never set |
| `ec2:DescribeRegions` | omits opt-in regions not enabled | `AllRegions: true` (already, `regions.py`) |

**The pairs.** "Regional" means the existing footprint mechanism (`containment.py::surface_of`,
per region, `req-aws-core-regional-containment`). A custom reader's footprint type follows the same
per-region rules.

| Parent | Edge type | Child | Surface backed by | Complete when | Falsifier |
| --- | --- | --- | --- | --- | --- |
| organization | `HOLDS_MEMBERSHIP` | membership | `ListAccounts` | read to its end | `MembershipFalsifier` |
| organization | `HOLDS_DELEGATION` | delegation | `ListDelegatedAdministrators` + every `ListDelegatedServicesForAccount` | all read to their end | delegation falsifier (`-organizations-completeness-4`) |
| organization | `HOLDS_SERVICE_CONTROL_POLICY` | customer-managed SCP | `ListPolicies(Filter=SERVICE_CONTROL_POLICY)` | read to its end | `DescribePolicy` |
| organization | `HOLDS_ORGANIZATIONS_POLICY` | customer-managed other policy | every per-type `ListPolicies` | `enabled_policy_types` read and all listings finished | `DescribePolicy` |
| SCP, RCP | `DECLARES_STATEMENT` | statement | the policy's `DescribePolicy` document | call succeeded and the document parsed | `PolicyStatementFalsifier` |
| tag policy | `DECLARES_TAG_RULE` | tag-policy rule | the policy's `DescribePolicy` document | call succeeded and the document parsed; a policy with no keys is complete-empty | `TagPolicyRuleFalsifier` (`DescribePolicy`) |
| account | `OWNS_REGION_FOOTPRINT` | footprint | the run's region scope for the account | `DescribeRegions` answered | `FootprintFalsifier` (never drops) |
| footprint | `HOSTS_ROUTE_TABLE`, `HOSTS_INTERNET_GATEWAY`, `HOSTS_NAT_GATEWAY`, `HOSTS_ELASTIC_IP`, `HOSTS_NETWORK_ACL`, `HOSTS_VPC_ENDPOINT`, `HOSTS_FLOW_LOG`, `HOSTS_NETWORK_INTERFACE`, `HOSTS_TRANSIT_GATEWAY`, `HOSTS_VPC_PEERING_CONNECTION`, `HOSTS_RESOLVER_ENDPOINT`, `HOSTS_RESOLVER_RULE` | the network-plane type | that type's regional `Describe*` / `List*` | regional rules | per `req-aws-core-network-plane`'s table |
| route table | `DECLARES_RT_ASSOCIATION` | route-table association | the table's own `Associations[]` in `DescribeRouteTables` | the regional `DescribeRouteTables` read to its end | association falsifier |
| network ACL | `DECLARES_ACL_ASSOCIATION` | NACL association | the ACL's own `Associations[]` in `DescribeNetworkAcls` | the regional `DescribeNetworkAcls` read to its end | association falsifier |
| Elastic IP | `HOLDS_EIP_ASSOCIATION` | EIP association | the address's own `AssociationId` in `DescribeAddresses` | `DescribeAddresses` answered (unpaginated); an unassociated address is complete-empty | association falsifier |
| resolver endpoint | `DECLARES_ENDPOINT_IP` | endpoint IP | `ListResolverEndpointIpAddresses(ResolverEndpointId)` | read to its end | endpoint-IP falsifier |
| footprint (VPC owner) | `HOSTS_RESOLVER_RULE_ASSOCIATION` | resolver-rule association | regional `ListResolverRuleAssociations` | regional rules | `GetResolverRuleAssociation` |
| route table | `DECLARES_ROUTE` | route | the table's own `Routes[]` in `DescribeRouteTables` | the regional `DescribeRouteTables` read to its end | route falsifier |
| network ACL | `DECLARES_ACL_ENTRY` | NACL entry | the ACL's own `Entries[]` in `DescribeNetworkAcls` | the regional `DescribeNetworkAcls` read to its end | NACL-entry falsifier |
| security group | `DECLARES_SG_RULE` | SG rule | regional `DescribeSecurityGroupRules`, grouped by `GroupId` | the regional listing read to its end; a group with no rules is complete-empty | `InvalidSecurityGroupRuleId.NotFound` |
| transit gateway | `HOLDS_TGW_ATTACHMENT` | attachment | regional `DescribeTransitGatewayAttachments`, grouped by `TransitGatewayId` (owner's run) | the regional listing read to its end | attachment falsifier |
| transit gateway | `HOLDS_TGW_ROUTE_TABLE` | TGW route table | regional `DescribeTransitGatewayRouteTables`, grouped by `TransitGatewayId` (owner's run) | the regional listing read to its end | TGW route-table falsifier |
| TGW route table | `DECLARES_TGW_ROUTE` | TGW route | `SearchTransitGatewayRoutes(TransitGatewayRouteTableId, Filters=[type ∈ static, propagated])` | read to its end, `AdditionalRoutesAvailable` false, and the filter's positive control passed (the call requires `Filters`; read: botocore) | TGW-route falsifier |
| footprint (management account) | `HOSTS_LANDING_ZONE` | landing zone | `ListLandingZones` in that region; only a landing zone whose ARN names this region is this footprint's child | regional rules | `ResourceNotFoundException` |
| landing zone | `HOLDS_ENABLED_CONTROL` | enabled control | `ListEnabledControls` with no `targetIdentifier` or filter and `includeChildren: true` (the input has no required members: read, botocore 1.43.103 `controltower` model) | read to its end | `GetEnabledControl` |
| landing zone | `HOLDS_ENABLED_BASELINE` | enabled baseline | `ListEnabledBaselines` with no filter and `includeChildren: true` (it defaults to false) | read to its end | `GetEnabledBaseline` |
| footprint | `HOSTS_IDENTITY_CENTER_INSTANCE` | instance | `sso-admin:ListInstances` in that region; only instances whose `PrimaryRegion` is this region are this footprint's children | regional rules | absent from `ListInstances` |
| instance | `HOLDS_PERMISSION_SET` | permission set | `ListPermissionSets(InstanceArn)` | read to its end | `DescribePermissionSet` |
| instance | `HOLDS_IDENTITY_GROUP` | group | `identitystore:ListGroups(IdentityStoreId)` with no `Filters` | read to its end | `DescribeGroup` |
| instance | `HOLDS_ACCOUNT_ASSIGNMENT` | assignment | `ListAccounts` + every `ListPermissionSetsProvisionedToAccount` + every `ListAccountAssignments` | all read to their end | assignment falsifier |
| footprint | `HOSTS_CONFIG_RECORDER`, `HOSTS_CONFIG_AGGREGATOR`, `HOSTS_GUARDDUTY_DETECTOR`, `HOSTS_ACCESS_ANALYZER` | the security-service type | `ListConfigurationRecorders` (paginated, unfiltered), `DescribeConfigurationAggregators`, `ListDetectors`, `ListAnalyzers` once per `Type` value (aggregated) | regional rules; the analyzer surface is complete only when all six per-type listings finish | per `req-aws-landing-zone-security-services`' table |
| footprint | `HOSTS_CONFIG_DELIVERY_CHANNEL` | delivery channel | `DescribeDeliveryChannels` (unpaginated) | regional rules | absent from `DescribeDeliveryChannels` |
| footprint | `HOSTS_SECURITYHUB_HUB` | hub | `DescribeHub` | a hub returned, or complete-empty only on the verified "not subscribed" error code; any other error is incomplete | per that table |

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-contained-type-triple-1 | Every Pair Has All Three | Proposed | Every (parent type, edge type) in an aws_core model's `CONTAINMENT_EDGES` has a child type with a `[falsifiers]` row and a collector path that records a surface naming that edge type. A test collects from the full fake source and fails if any live parent node observed in the run lacks a surface for any containment edge type its model declares. | The table above is the epic's list; the test is the guard against the next one. |
| req-aws-core-contained-type-triple-2 | Empty Parent Is Complete-Empty | Proposed | A parent observed with no children records a complete surface with zero items; a test removes a security group's last rule and asserts the rule becomes a candidate. | |
| req-aws-core-contained-type-triple-3 | Unfinished Listing Is Incomplete | Proposed | A failed, partial, unverified-empty or uncontrolled-filter listing records the surface `enumeration_complete: false` with the reason, for every parent it would have covered, and never omits it. | `req-grid-reconcile-evidence`. |
| req-aws-core-contained-type-triple-4 | Regional Child Listings Cover Each Parent | Proposed | For children read by one regional listing grouped by parent (SG rules, TGW attachments, TGW route tables), each observed parent's surface is complete only when that regional listing read to its end. | |
| req-aws-core-contained-type-triple-5 | TGW Route Search Is Controlled | Proposed | The `DECLARES_TGW_ROUTE` surface is complete only when `SearchTransitGatewayRoutes` reached its paginator's stop condition (no `NextToken` and `AdditionalRoutesAvailable` false on the last page), was called at the maximum `MaxResults`, and its required filter's positive control passed. `AdditionalRoutesAvailable: true` with no token leaves the surface incomplete, never partially complete. If the search is split by narrower filters to get under the cap, every filtered search must reach its stop condition and the union must be controlled. | `SearchTransitGatewayRoutes` requires `Filters`, and has `NextToken` in input and output with a paginator whose `more_results` is `AdditionalRoutesAvailable` (read: botocore 1.43.103). `req-aws-collector-pagination`. |
| req-aws-core-contained-type-triple-6 | Listings Read Their Full Set | Proposed | Every listing in *Listings read their full set* is called with the stated widening flag (or replacement call), never its narrowed default. Tests: a child enabled baseline and a control enabled on a nested OU and on an account appear; an AWS-managed network interface appears; a service-linked Config recorder appears; an analyzer of each `Type` appears; a provisioned permission set of either provisioning status is listed. | Read: botocore 1.43.103 input shapes. A default-narrowed listing read as complete would nominate what it omitted. |

### Reference Edges Declare What They Derive From
----
RID: `req-aws-core-reference-derivation`

Status: `Proposed`

No core verb ends a reference edge while both of its endpoints are live. Edge re-derivation,
`req-grid-reconcile-falsifier-5`, is Proposed and unbuilt. So `ATTACHES_POLICY` after a
detach, `TRUSTS_ACCOUNT` after a trust edit, `NESTED_UNDER_PARENT` after `MoveAccount`, and
`ATTACHED_TO_TARGET` after an SCP detach all persist as stale positive security facts. aws_core
cannot fix that alone. What it can do is (1) avoid it where AWS gives an identity
(`req-aws-core-network-plane-4`), and (2) declare, for every reference edge, which source node's
payload it is derived from, so that re-derivation can apply once core builds it.

#### Last-seen reference edges

Below is every reference edge this epic adds or newly collects, plus the four named above. "Last
seen" means AWS can change the edge's payload while both endpoints stay live. The edge then
persists after the change until core re-derivation exists. "Ends with its source" means the target
is part of the source node's key, or AWS offers no operation that changes it. Then a change retires
the source node, and core's endpoint rule ends the edge. The changing operations were read from
botocore 1.43.103's operation list (the local copy; the spec's pin is 1.43.104). Paths are relative
to the named call's response. `PAIRED_WITH_ACCOUNT` (declared, not collected; `-3` below) and
`TRUSTS_IDENTITY_SOURCE` (target open, not emitted by the collector) are not derived from a payload,
so they are not listed.

| Edge | Source → target | Derived from (call, payload path) | Lifetime | Changed by |
| --- | --- | --- | --- | --- |
| `ATTACHES_POLICY` | role / user → policy | role and user manifest entries, `value_path` `_attached_policy_arns` (`aws_resource_manifest.json:225-231,752-758`) | **last seen** | `DetachRolePolicy`, `DetachUserPolicy` |
| `TRUSTS_ACCOUNT` | role → account | role manifest entry, `value_path` `_trusted_account_ids` (`aws_resource_manifest.json:218-223`), derived from the trust policy | **last seen** | `UpdateAssumeRolePolicy` |
| `NESTED_UNDER_PARENT` | account → root / OU | `ListAccountsForParent(ParentId)` → `Accounts[].Id` under that parent (`organizations.py:636-661`) | **last seen** | `MoveAccount` |
| `NESTED_UNDER_PARENT` | OU → parent | `ListOrganizationalUnitsForParent(ParentId)` → `OrganizationalUnits[].Id` (`organizations.py:506-521`) | ends with its source (Organizations has no operation that moves an OU) | — |
| `ATTACHED_TO_TARGET` | SCP / organizations policy → root / OU / account | `ListTargetsForPolicy(PolicyId)` → `Targets[].TargetId`, `Targets[].Type` (`organizations.py:696-705`) | **last seen** | `DetachPolicy` |
| `ENROLLS_ACCOUNT` | membership → account | `ListAccounts` → `Accounts[].Id` | ends with its source (`account_id` is in the membership key) | — |
| `DELEGATES_TO_ACCOUNT` | delegation → account | `ListDelegatedAdministrators` → `DelegatedAdministrators[].Id` | ends with its source (in the key) | — |
| `ROUTES_FOR_SUBNET` | route-table association → subnet | `DescribeRouteTables` → `RouteTables[].Associations[].SubnetId` | ends with its source (`ReplaceRouteTableAssociation` mints a new association id) | — |
| `ROUTES_TRAFFIC` | route → IGW / VPC endpoint / NAT / TGW / peering / ENI / EC2 instance | `DescribeRouteTables` → `RouteTables[].Routes[].GatewayId` (`igw-…`, `vpce-…`) `\| NatGatewayId \| TransitGatewayId \| VpcPeeringConnectionId \| NetworkInterfaceId \| InstanceId` (*Route targets*) | **last seen** (the route keeps its destination key) | `ReplaceRoute` |
| `ROUTES_TRAFFIC` | TGW route → attachment | `SearchTransitGatewayRoutes` → `Routes[].TransitGatewayAttachments[].TransitGatewayAttachmentId` | **last seen** | `ReplaceTransitGatewayRoute` |
| `RESIDES_IN_VPC` | route table / NACL / endpoint → VPC | `RouteTables[].VpcId`, `NetworkAcls[].VpcId`, `VpcEndpoints[].VpcId` | ends with its source (no operation moves them) | — |
| `ATTACHED_TO_VPC` | IGW → VPC | `DescribeInternetGateways` → `InternetGateways[].Attachments[].VpcId` | **last seen** | `DetachInternetGateway`, `AttachInternetGateway` |
| `RESIDES_IN_SUBNET` | NAT gateway → subnet | `DescribeNatGateways` → `NatGateways[].SubnetId` | ends with its source | — |
| `RESIDES_IN_SUBNET` | VPC endpoint → subnet | `DescribeVpcEndpoints` → `VpcEndpoints[].SubnetIds[]` | **last seen** | `ModifyVpcEndpoint` (`RemoveSubnetIds`) |
| `RESIDES_IN_SUBNET` | ENI → subnet | `DescribeNetworkInterfaces` → `NetworkInterfaces[].SubnetId` | ends with its source | — |
| `RESIDES_IN_SUBNET` | resolver endpoint IP → subnet | `ListResolverEndpointIpAddresses` → `IpAddresses[].SubnetId` | ends with its source (`UpdateResolverEndpoint`'s `UpdateIpAddresses` takes only `IpId` and `Ipv6`) | — |
| `USES_ELASTIC_IP` | NAT gateway → EIP | `DescribeNatGateways` → `NatGateways[].NatGatewayAddresses[].AllocationId` | **last seen** (secondary addresses). The same link is also carried by the EIP association node, whose `ASSOCIATED_WITH_INTERFACE` reaches the NAT gateway's ENI and ends with that association; this edge is a convenience shortcut | `DisassociateNatGatewayAddress` |
| `ASSOCIATED_WITH_INTERFACE` | EIP association → ENI | `DescribeAddresses` → `Addresses[].NetworkInterfaceId` | ends with its source (a re-association mints a new `AssociationId`) | — |
| `FILTERS_SUBNET` | NACL association → subnet | `DescribeNetworkAcls` → `NetworkAcls[].Associations[].SubnetId` | ends with its source (`ReplaceNetworkAclAssociation` mints a new association id) | — |
| `REFERENCES_SECURITY_GROUP` | SG rule → SG | `DescribeSecurityGroupRules` → `SecurityGroupRules[].ReferencedGroupInfo.GroupId` | **last seen** (the rule id survives an edit) | `ModifySecurityGroupRules` |
| `CONSUMES_ENDPOINT_SERVICE` | VPC endpoint → endpoint service | `VpcEndpoints[].ServiceName` | ends with its source | — |
| `USES_SECURITY_GROUP` | VPC endpoint → SG | `VpcEndpoints[].Groups[].GroupId` | **last seen** | `ModifyVpcEndpoint` (`RemoveSecurityGroupIds`) |
| `USES_SECURITY_GROUP` | ENI → SG | `NetworkInterfaces[].Groups[].GroupId` | **last seen** | `ModifyNetworkInterfaceAttribute` |
| `USES_SECURITY_GROUP` | resolver endpoint → SG | `ListResolverEndpoints` → `ResolverEndpoints[].SecurityGroupIds[]` | ends with its source (set only by `CreateResolverEndpoint`) | — |
| `MONITORS_TRAFFIC` | flow log → VPC / subnet / ENI / transit gateway / TGW attachment / NAT gateway | `DescribeFlowLogs` → `FlowLogs[].ResourceId` | ends with its source (no modify operation for flow logs) | — |
| `WRITES_LOGS` | flow log → log group / bucket | `FlowLogs[].LogDestinationType` + `FlowLogs[].LogDestination`, normalized per *Target keys* below | ends with its source | — |
| `WRITES_LOGS` | Config delivery channel → bucket | `DescribeDeliveryChannels` → `DeliveryChannels[].s3BucketName` | **last seen** (the channel keeps its name when its bucket changes) | `PutDeliveryChannel` |
| `ATTACHED_TO_TRANSIT_GATEWAY`, `ATTACHES_VPC`, `PEERS_WITH_TRANSIT_GATEWAY` | attachment → TGW / VPC / peer TGW | `DescribeTransitGatewayAttachments` → `TransitGatewayAttachments[].TransitGatewayId`, `.ResourceId` | ends with its source | — |
| `ASSOCIATED_WITH_TGW_ROUTE_TABLE` | attachment → TGW route table | `TransitGatewayAttachments[].Association.TransitGatewayRouteTableId` | **last seen** | `DisassociateTransitGatewayRouteTable` |
| `PROPAGATES_TO_TGW_ROUTE_TABLE` | attachment → TGW route table | `GetTransitGatewayRouteTablePropagations(TransitGatewayRouteTableId)` → `TransitGatewayRouteTablePropagations[].TransitGatewayAttachmentId` (read per route table; this call is added to the network-plane reads) | **last seen** | `DisableTransitGatewayRouteTablePropagation` |
| `CONNECTS_VPC` | peering → requester / accepter VPC | `DescribeVpcPeeringConnections` → `RequesterVpcInfo.VpcId`, `AccepterVpcInfo.VpcId` | ends with its source | — |
| `FORWARDS_VPC_DNS` | resolver-rule association → VPC | `ListResolverRuleAssociations` → `ResolverRuleAssociations[].VPCId` | ends with its source | — |
| `ASSOCIATES_RESOLVER_RULE` | resolver-rule association → rule | `ResolverRuleAssociations[].ResolverRuleId` | ends with its source | — |
| `FORWARDS_THROUGH_ENDPOINT` | resolver rule → outbound endpoint | `ListResolverRules` → `ResolverRules[].ResolverEndpointId` | **last seen** | `UpdateResolverRule` |
| `BELONGS_TO_ACCOUNT` | each new regional type → owner account | the entry's `owner_path` (`req-aws-core-regional-containment-5`) | ends with its source (an owner does not change) | — |
| `APPLIES_TO_TARGET` | enabled control / baseline → OU / account | `ListEnabledControls` → `enabledControls[].targetIdentifier`; `ListEnabledBaselines` → `enabledBaselines[].targetIdentifier` | ends with its source (`UpdateEnabledControl` and `UpdateEnabledBaseline` take no target) | — |
| `GRANTS_PERMISSION_SET`, `GRANTS_ACCESS_TO_ACCOUNT`, `GRANTED_TO_GROUP` | assignment → permission set / account / group | `ListAccountAssignments` → `AccountAssignments[].PermissionSetArn`, `.AccountId`, `.PrincipalId` | ends with its source (all three are in the key) | — |
| `REPORTS_TO_ADMINISTRATOR` | GuardDuty detector / Security Hub hub → account | `GetAdministratorAccount` → `Administrator.AccountId` | **last seen** | `DisassociateFromAdministratorAccount` |

#### Target keys

An edge's payload value is not always its target's natural key. Where it is not, the derivation
names the normalization, and a test feeds each documented payload form and asserts the edge lands on
the target's key. Every other reference edge in the table above carries the target's own id, which
is its natural key (read: each target model's `NATURAL_KEY`).

| Edge | Payload | Normalized to |
| --- | --- | --- |
| `WRITES_LOGS` (flow log), `LogDestinationType` = `cloud-watch-logs` | a log-group ARN, possibly ending `:*` | the log group's natural key. On the fix-pack branch that is `log_group_arn`, the ARN without a trailing `:*` (DescribeLogGroups' `logGroupArn` form); on `main` today it is `name`, the ARN's `log-group:<name>` segment. The edge uses whichever key the model declares when this ships |
| `WRITES_LOGS` (flow log), `LogDestinationType` = `s3` | `arn:<partition>:s3:::<bucket>[/<prefix>/]` | the bucket's key, `arn:<partition>:s3:::<bucket>`. The object prefix is kept as the flow log's typed field `log_destination_prefix` (empty when none) |
| `WRITES_LOGS` (flow log), `LogDestinationType` = `kinesis-data-firehose` | a Firehose delivery-stream ARN | no edge: Firehose delivery streams are not modeled. `log_destination_type` and `log_destination` are typed fields, verbatim |
| `WRITES_LOGS` (Config delivery channel) | `s3BucketName`, a bare bucket name | `arn:<run partition>:s3:::<s3BucketName>`; `s3KeyPrefix` is a typed field |
| `APPLIES_TO_TARGET` | `targetIdentifier`, an OU ARN (`…:ou/o-…/ou-…`) or an account ARN (`…:account/o-…/<id>`) | the OU's `ou_id` or the account's `account_id`, the ARN's last segment, with the resource type naming the target type |
| `MONITORS_TRAFFIC` | `ResourceId` | the id itself. `FlowLog` carries no resource-type member, so the id prefix names the target type, covering every value of botocore 1.43.103's `FlowLogsResourceType` enum: `VPC` → `vpc-…` (`aws_vpc`), `Subnet` → `subnet-…` (`aws_subnet`), `NetworkInterface` → `eni-…` (`aws_network_interface`), `TransitGatewayAttachment` → `tgw-attach-…` (`aws_transit_gateway_attachment`, matched before `tgw-`), `TransitGateway` → `tgw-…` (`aws_transit_gateway`), `RegionalNatGateway` → `nat-…` (`aws_nat_gateway`; the prefix is inferred). An unrecognized prefix emits no edge and keeps `ResourceId` as a typed field |
| `GRANTED_TO_GROUP` | `PrincipalId` | `(identity_store_id, group_id)`, with the identity store id taken from the instance |

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-reference-derivation-1 | Derivation Source Declared | Proposed | Every reference edge type aws_core's collector emits names, in its manifest or edge file, the source node type and the payload path it is derived from. A test fails on an emitted reference edge without one. | Consumer: core's `req-grid-reconcile-falsifier-5`. |
| req-aws-core-reference-derivation-2 | Last-Seen Edges Listed | Proposed | *Last-seen reference edges* lists every reference edge this epic adds or newly collects, with its source call and payload path, and marks each **last seen** or ends-with-its-source. A test compares that table with `-1`'s machine-readable declarations and fails on an emitted reference edge the table omits. | Edges aws_core emitted before the epic, other than the four named, are covered by `-1`'s declaration, which is the exhaustive source once built. |
| req-aws-core-reference-derivation-3 | Payloads Normalized To Target Keys | Proposed | Every edge in *Target keys* normalizes its payload as stated; a test per row feeds each payload form (a log-group ARN with and without `:*`, an S3 destination with and without a prefix, a Firehose destination, a bare bucket name, an OU ARN and an account ARN, each `MONITORS_TRAFFIC` prefix, a group principal id) and asserts the edge lands on the target's natural key, or that no edge is emitted and the typed fields hold the value. | A raw payload that is not the target's key never matches a node. |

### Account Partition And GovCloud Pairing
----
RID: `req-aws-core-partition-pairing`

Status: `Proposed`

A GovCloud account is always created together with a commercial account. Its pair lives in a
separate commercial organization, in a separate partition. The grid should say which partition an
account is in, and which commercial account a GovCloud account is paired with.

#### Status Details

Proposed by the landing-zone epic, step 7. Ruling (George, 2026-09-30): model the pairing,
not the vending. Both initial accounts were created manually, so there is **no** Service Catalog
provisioned-product requirement and no `CreateGovCloudAccount` workflow model.

#### Implementation

- **`AwsAccount.partition`** (`""`, `aws`, `aws-us-gov`, `aws-cn`; blank = not observed), the same
  enum as `AwsOrganization.partition` (`models/aws_organization.py:95`). Read from the partition
  segment of the STS caller ARN for the account's own run, or of the account ARN `ListAccounts`
  returns for an organization-listed account. Never inferred from a region string. Today only the
  footprint and the organization carry a partition (`models/aws_account.py` has no `partition`).
- **Not a dimension.** An `aws_partition` dimension was considered. The ruling is to touch no
  dimension, so the partition is a field only. A query that separates GovCloud from commercial reads
  the field.
- **`PAIRED_WITH_ACCOUNT`** (GovCloud account → commercial account), a reference, at most one per
  GovCloud account. Neither account contains the other.
- **Not discoverable from the GovCloud side (read).** The Organizations `Account` shape a GovCloud
  management credential reads has `Id, Arn, Email, Name, Status, State, Paths, JoinedMethod,
  JoinedTimestamp`, and no paired-account member (botocore 1.43.104). The pair is recorded only on
  the commercial side: `CreateAccountStatus` carries both `AccountId` and `GovCloudAccountId`, read
  through `ListCreateAccountStatus` / `DescribeCreateAccountStatus` by the **commercial**
  management account, and only for accounts that organization created and still tracks (read:
  botocore shape and operation docs).
- **So the pairing is declared, in highbar's design** (ruling 2026-10-01). For the first GovCloud
  estate the edge is declared data with `declared` provenance in highbar's own GRIFT, never
  discovered or invented by the GovCloud collector, and never carried on a secret: the pairing is a
  fact about the estate, not about a credential. The edge points GovCloud → commercial because the
  GovCloud account exists by virtue of its commercial pair (`CreateGovCloudAccount` is called from
  the commercial side), and "at most one per GovCloud account" is then a per-source rule a test can
  check. A later commercial-side run may *observe* the pair from `ListCreateAccountStatus`. That is
  Future: it needs the commercial account collected in the same grid, with its own collector
  configuration, which is unified-systems-com/aws-core-tap#70 (Backlog).
- **Two organizations, one grid.** A commercial organization and a GovCloud organization in one grid
  are two `aws_organization` nodes with distinct `organization_id`s. Every Organizations falsifier
  already gates on the candidate's own organization (`req-aws-core-organizations-collect-5`).
  GovCloud account ids differ from their commercial pair's (web, [C-GCORG](https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-organizations.html): two accounts are created), so `account_id` stays a
  sufficient key. EC2 ids (`vpc-…`, `subnet-…`) carry no partition; that is unified-systems-com/aws-core-tap#14's concern.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-partition-pairing-1 | Account Partition Field | Proposed | `AwsAccount.partition` is filled from an ARN the run read, for both the self-collected and the organization-listed path; blank means not observed. | |
| req-aws-core-partition-pairing-2 | No Partition Dimension | Proposed | No dimension key is added or changed by this requirement. | Ruling 2026-09-30. |
| req-aws-core-partition-pairing-3 | Pairing Edge | Proposed | `PAIRED_WITH_ACCOUNT` declares GovCloud account → commercial account, reference, and the spec states it is declared, not collected, from the GovCloud side. | Ruling 2026-10-01: declared as data in highbar's design. |
| req-aws-core-partition-pairing-4 | No Vending Model | Proposed | No model or requirement here represents account vending (Service Catalog provisioned product, `CreateGovCloudAccount` request). | Ruling 2026-09-30. |
