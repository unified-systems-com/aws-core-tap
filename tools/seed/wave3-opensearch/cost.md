# Wave 3 OpenSearch cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **P** = price read from the AWS Price List file for `us-gov-west-1` on 2026-11-02 (`AmazonES` 20261026173153); **E** = my estimate or recollection, no price file read for it.

Time box 2 hours (a domain takes 15 to 30 minutes to create; E)

| Resource | Quantity | Rate | Per hour | 2 hours | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| OpenSearch `t3.small.search` instance | 1 | $0.043 per instance-hour | $0.04300 | $0.08600 | P |
| gp2 storage for it (gp3 is offered too, at $0.1464 per GB-month) | 10 GiB | $0.162 per GB-month, /730 h | $0.00222 | $0.00444 | P |
| VPC, subnet, security group | 1 set | no charge | $0 | $0 | E |

**Total for two hours: about $0.09.** With a doubled duration: under $0.20.
Standing cost left running by mistake: about $0.045 per hour, $1.10 per day.

Seeded: `OpenSearchService::Domain`. Not seeded: the OpenSearch Serverless `AccessPolicy`, `SecurityPolicy` and
`LifecyclePolicy` (free, and the provider has all three, but the collector keys them `{account}/{region}/{type}/{name}`,
which the catalog cannot yet derive from the state: `expected.py` has no value spec that builds a key from the account
and region), `OpenSearchServerless::VpcEndpoint` (a PrivateLink endpoint, billed by the hour; E), `Collection` (2 OCU
minimum at $0.302 per OCU-hour, P), `Elasticsearch::Domain` (the same domain read through the Elasticsearch API; the
catalog names one entity per Terraform type), `OpenSearchService::Application` and `OpenSearch::DataSource` (not asked
for).
