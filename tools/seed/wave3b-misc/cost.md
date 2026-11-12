# Wave 3b misc cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in seconds; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| Scheduler group, X-Ray group and sampling rule, Resource Groups group | 1 each | no charge while unused | $0 | $0 | E |
| Signer profile, CodeCommit repository, RAM share, Synthetics group, CodeConnections connection, Recycle Bin rule | 1 each | no charge while unused (CodeCommit bills per active user; none is added) | $0 | $0 | E |

**Total for one hour: under $0.01.** Standing cost left running by mistake: under $0.01 per hour.

Not seeded, and why: `ServiceCatalogAppRegistry::Application` and `AttributeGroup` (`AccessDeniedException`: AppRegistry is in maintenance mode and no longer available to new customers); `Oam::Sink` (it applies, but the collector role cannot read its tags: `tags-unread`; the denied action is not established and is not in `tools/coverage/extended-read-actions.json`); this module holds only types with a Terraform resource that needs nothing else; the rest of the uncovered types in these services either need a certificate, a role and a target, a running resource, or an account-wide setting (a Resource Explorer index, a Security Hub setting) that should not be created and removed by a seed.

Leftover note: a Signer signing profile cannot be deleted. A destroy cancels it, and it stays listed as `Canceled` under its name for good (one per run).
