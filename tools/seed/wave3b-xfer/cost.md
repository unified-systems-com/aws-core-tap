# Wave 3b xfer cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (the Transfer server takes a few minutes to come online; the rest is created in seconds; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| Transfer Family server, SFTP, VPC endpoint | 1 | about $0.30 per protocol-hour; no data moves | $0.30 | $0.30 | E |
| Transfer user and workflow | 1 each | no charge while unused | $0 | $0 | E |
| Pinpoint app, AppStream stack | 1 each | no charge while unused | $0 | $0 | E |
| VPC, subnet, security group with no rules, IAM role | 1 each | no charge | $0 | $0 | E |

**Total for one hour: about $0.30.** Standing cost left running by mistake: about $0.30 per hour, $7.20 per day.

Not seeded, and why: `DMS::DataProvider` and `DMS::InstanceProfile` (`AccessDeniedException: Feature is not accessible`) and the other DMS types (an instance bills by the hour and needs `dms-vpc-role`; an endpoint needs credentials); `Pinpoint::EmailTemplate` and the other Pinpoint engagement features (`ForbiddenException`: AWS ended support for them on October 30, 2026); `MSK::Configuration` (it applies, but the collector's read of its tags answers `tags-unread`, so it cannot pass; the cause is not established); MSK clusters (billed by the hour), AppStream fleets and image builders (billed while running), Transfer connectors, agreements, profiles, certificates and host keys (they need certificates or key material), Comprehend classifiers and recognizers (they train on data), and the types with no Terraform resource (DataBrew, Mail Manager).
