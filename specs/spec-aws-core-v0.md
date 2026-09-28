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
| req-aws-core-reconcile-falsifiers | [Reconciliation Foundation — Falsifiers](#reconciliation-foundation--falsifiers) | Implemented | `[falsifiers]` manifest table, base `_AwsFalsifier`, `SubnetFalsifier`; account/org excluded by design |
| req-aws-core-regional-containment | [Region-Scoped Containment](#region-scoped-containment) | Implemented | `aws_account_region` (account × region footprint), `HOSTS_*` containment edges, per-region completeness surfaces; VPC, subnet, EC2 instance, security group |

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
member accounts in them, and the service control policies attached anywhere in it. These are
**design vocabulary**: no collector emits them yet, so they have no collection-manifest entry, and
every field is one AWS reports so a later collector fills the same fields.

#### Implementation

- `aws_core__aws_organization`: `name`, `organization_id` (`o-…`), `root_id` (`r-…`),
  `management_account_id`, `feature_set` (`ALL` / `CONSOLIDATED_BILLING`), `partition` (`aws`,
  `aws-us-gov` or `aws-cn`, the three partitions AWS Organizations runs in). Source: `organizations:DescribeOrganization` and `ListRoots`; the partition is the
  organization ARN's partition segment. An organization has no name in AWS, so `name` is the label
  its author or collector gives it. It carries no `tags`: AWS cannot tag an organization.
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
| req-aws-core-organizations-7 | No Policy Document Blob | Implemented | The SCP model carries no policy document or `configuration` field. | A typed summary field can be added when a source fills it. |

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

- **`[falsifiers]` manifest table**, `tap-plugin.toml`: one entry today,
  `aws_core__aws_subnet = "tap_plugin.aws_core.falsifiers.SubnetFalsifier"`. `requires_tap`
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
- **Neither `AwsAccount` nor `AwsOrganization` has a falsifier.** `Boto3Collector.run()`
  already treats credential/region-scope/account-identity failure as unrecoverable —
  `self._abort(..., "STS_UNREACHABLE", ...)` / `self._abort(..., "ACCOUNT_MISMATCH", ...)` —
  mirroring `tap-plugin-github-core`'s foundation-layer abort pattern
  (`specs/spec-github-core-reliability.md`, `req-github-core-reliability-absence`: a
  foundation failure aborts the run rather than degrading one surface and continuing).
  `AwsOrganization` additionally has no collector at all yet (`req-aws-core-organizations`:
  "design vocabulary... no collector emits them yet"), so it can never produce a completeness
  surface for a candidate to come from.
- **Candidates do not flow from a live run yet.** `boto3_collector` does not produce
  per-surface completeness statements (`req-aws-collector-reconcile`,
  `specs/spec-aws-core-collector-v0.md`, still Backlog) — that is the separate seam that would
  let `tap_grid.candidates.derive_candidates` actually emit a subnet candidate for
  `SubnetFalsifier` to judge. This requirement builds and proves the JUDGING layer
  (`tap_grid.falsifier_testing.run_four_cases` against a fake `ec2` client,
  `tap_plugin/aws_core/tests/test_falsifiers.py`); wiring the collector to produce
  completeness statements is future work, named so the omission is not mistaken for an
  oversight.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-aws-core-reconcile-falsifiers-1 | Manifest Table | Implemented | `tap-plugin.toml` declares `[falsifiers]` with `aws_core__aws_subnet`; `requires_tap` is `>=0.2.1`. | |
| req-aws-core-reconcile-falsifiers-2 | Four Proof Cases | Implemented | `SubnetFalsifier` produces `PRESENT_AT_PROBE` / `DROPPED_FROM_OBSERVATION` / `UNDETERMINED(forbidden)` / `REIDENTIFIED` against a fake `ec2` client, run through `tap_grid.falsifier_testing.run_four_cases`. | |
| req-aws-core-reconcile-falsifiers-3 | Single-Account Scope Check | Implemented | A candidate whose `aws_account` dimension does not match the falsifier's resolved credential account is `UNDETERMINED(scope_unknown)` without a probe. | |
| req-aws-core-reconcile-falsifiers-4 | Account/Org Declare No Containment | Implemented | `AwsAccount.CONTAINMENT_EDGES == ()` and `AwsOrganization.CONTAINMENT_EDGES == ()`, each explicitly declared with a citing comment. | |
| req-aws-core-reconcile-falsifiers-5 | Account/Org Have No Falsifier | Implemented | Neither type is registered in `[falsifiers]`; the reasoning (foundation-layer abort, no collector for Organization) is documented in this section and in `falsifiers.py`'s module docstring. | |
| req-aws-core-reconcile-falsifiers-6 | Completeness Statements — First Surfaces (tap-plugin-aws-core#49) | Implemented | `boto3_collector` now produces per-region completeness surfaces for its four `containment`-declared entries (`req-aws-core-regional-containment`); every other listing still records none. | Full listing coverage remains open; see [Region-Scoped Containment](#region-scoped-containment). |

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
- **A real, DOCUMENTED cross-PR dependency, not an oversight.** Three of the four child types'
  falsifiers — `VpcFalsifier`, `Ec2InstanceFalsifier`, `SecurityGroupFalsifier` — are built on
  the sibling PR tap-plugin-aws-core#44, not on this one. `validate_plugin --level loads
  --strict` is therefore RED on those three targets on this branch alone TODAY; it goes green
  the moment #44 merges into this PR's ancestry, with no further change needed here.
  `regional.py`'s `PENDING_FALSIFIER_PR` names exactly which PR and which falsifier for each,
  and `tests/test_regional_containment.py::TestEveryRegionalChild::
  test_falsifier_registered_or_pending_a_named_sibling_pr` asserts every containment target is
  EITHER registered OR named there — never neither. Only `SubnetFalsifier` (also on this PR's
  base, #46) is live on this branch.
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
| req-aws-core-regional-containment-1 | Account-Region Footprint | Implemented | `aws_core__aws_account_region`, keyed on `(account_id, region_code)`, emitted for every region in the run's scope. | |
| req-aws-core-regional-containment-2 | One Containment Edge Per Child Type | Implemented | `REGIONAL_CHILDREN` declares `HOSTS_VPC` / `HOSTS_SUBNET` / `HOSTS_EC2_INSTANCE` / `HOSTS_SECURITY_GROUP`; `AwsAccountRegion.CONTAINMENT_EDGES` and every `.edge.json` file agree, checked by `test_regional_containment.py`. | |
| req-aws-core-regional-containment-3 | Per-Region Completeness, Not Observed-Empty | Implemented | A disabled or unknown-status region's listing is never called / never counted complete when empty; `region_disabled` / `empty_unverified` reasons are recorded. | |
| req-aws-core-regional-containment-4 | GovCloud Partition-Aware | Implemented | `partition_of` derives `aws-us-gov` from `us-gov-*`; a mixed-partition scope is warned once. | |
| req-aws-core-regional-containment-5 | RAM Share Observed, Not Hosted | Implemented | `owner_path` on a containment entry routes `BELONGS_TO_ACCOUNT` to the real owner and withholds the `HOSTS_*` edge when it differs from the observing account. | |
| req-aws-core-regional-containment-6 | Cross-PR Falsifier Dependency Named | Implemented | `PENDING_FALSIFIER_PR` names tap-plugin-aws-core#44 for VPC/EC2-instance/security-group; `validate_plugin --strict` is red on those three on this branch alone until #44 merges, by design. | Retarget/merge-order note mirrors this PR's own relationship to #46. |
| req-aws-core-regional-containment-7 | Remaining Regional Types Named, Not Silently Skipped | Proposed | `NOT_YET_WIRED` names 8 region-scoped types with no containment yet, each blocked on pairing a new row with a new falsifier. | Backlog. |
