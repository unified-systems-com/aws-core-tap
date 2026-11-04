# Wave 3b data cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in under two minutes; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| Glue database, table, registry, schema, crawler, job, trigger, workflow, security configuration | 1 each | no charge for definitions; a crawler or job bills only when it runs, and none is started | $0 | $0 | E |
| Athena work group, Glue data catalog, saved query | 1 each | per query; none is run | $0 | $0 | E |
| Step Functions activity, state machine, alias | 1 each | per state transition; none is started | $0 | $0 | E |
| AppConfig application, environment, configuration profile, deployment strategy | 1 each | per configuration request; none | $0 | $0 | E |
| DocumentDB subnet group, cluster parameter group, event subscription, global cluster | 1 each | no charge with no cluster | $0 | $0 | E |
| Neptune subnet group, cluster and instance parameter groups, event subscription | 1 each | no charge with no cluster | $0 | $0 | E |
| MemoryDB subnet group, parameter group, user, access control list | 1 each | no charge with no cluster | $0 | $0 | E |
| Service Catalog portfolio, tag option, service action | 1 each | no charge | $0 | $0 | E |
| Managed Prometheus workspace and rule groups namespace | 1 each | per sample ingested and stored; none | $0 | $0 | E |
| SNS topic, S3 bucket (empty), VPC and two subnets | 1 each | no charge | $0 | $0 | E |

**Total for one hour: $0.** Standing cost left running by mistake: about $0 per hour (the workspace, the buckets and the groups
bill only for use).

Types the module tried and does not seed, and why:

- `Glue::Connection` and `Glue::DataQualityRuleset`: the collector's role is denied `glue:GetConnections` and
  `glue:ListDataQualityRulesets` (both are in `tools/coverage/extended-read-actions.json`), so the collector's read fails
  with `AccessDeniedException` and the type cannot pass. They were created and compared once; both failed on the read.
- `VerifiedPermissions::PolicyStore`: the policy store lists, but reading its tags answers `AccessDeniedException` for the
  collector's role (`verifiedpermissions:ListTagsForResource`), so the compare stops at `tags-unread`. That action is not in
  `extended-read-actions.json` yet. Checked with a store created for the purpose and deleted afterwards, one call as the
  collector's credential.
- `Neptune::GlobalCluster`: CreateGlobalCluster answers "Global clusters are not supported for engine: neptune" in GovCloud.
- `StepFunctions::StateMachineVersion` (the catalog allows one CloudFormation type per Terraform resource, and the state
  machine's resource holds the machine), `AppConfig::Extension` and `ExtensionAssociation` (need a Lambda, SNS or EventBridge
  action with its own role), `Glue` ML transform, session, blueprint, dev endpoint and usage profile (billed, or no Terraform
  resource), `Athena::CapacityReservation` (billed per DPU-hour), the DocumentDB, Neptune and MemoryDB clusters and
  snapshots (billed by the hour; left for a costed module), `ServiceCatalog` product and provisioned product (need a
  template), `VerifiedPermissions` policy, template and identity source (need the store, which is not seeded), and
  `Config::StoredQuery` (the Terraform provider has no resource for it).

Leftover check for this module: `aws glue get-databases`, `get-jobs`, `get-crawlers`, `get-triggers`, `list-registries`,
`aws athena list-work-groups`, `aws stepfunctions list-state-machines`, `aws appconfig list-applications`,
`aws docdb describe-db-subnet-groups`, `describe-global-clusters`, `aws neptune describe-db-subnet-groups`,
`aws memorydb describe-subnet-groups`, `describe-users`, `describe-acls`, `aws servicecatalog list-portfolios`,
`aws amp list-workspaces` and `aws s3api list-buckets`, looking for names starting `seed-w3d-<run id>`; then the tag sweep.
