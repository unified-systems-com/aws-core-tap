# Wave 3b misc2 cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in seconds; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| OpenSearch Serverless encryption, access and lifecycle policies | 1 each | no charge; no collection exists | $0 | $0 | E |
| EMR security configuration Route 53 delegation set, Direct Connect gateway, CodeDeploy deployment configuration | 1 each | no charge while unused | $0 | $0 | E |
| DAX subnet group and parameter group | 1 each | no charge; no cluster exists | $0 | $0 | E |
| VPC and subnet | 1 each | no charge | $0 | $0 | E |

**Total for one hour: under $0.01.** Standing cost left running by mistake: under $0.01 per hour.

Not seeded, and why: `SES::ReceiptRuleSet` and `SES::ReceiptFilter` (`InvalidAction`: classic SES receiving is not available in this region); `LicenseManager::LicenseConfiguration` (`AccessDeniedException`: service role not found; License Manager needs a setup step in the account that this seed does not do); the other uncovered types in these services need a running resource (a collection, a cluster), a certificate, or a Lambda function.
