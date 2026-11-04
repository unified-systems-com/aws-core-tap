# Wave 3b net cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in under ten minutes; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| Route 53 Resolver outbound endpoint, two IP addresses | 2 | about $0.125 per network interface-hour | $0.25 | $0.25 | E |
| Resolver rule, query log configuration, DNS Firewall domain list, rule group, rule, association, three per-VPC settings | 1 each | no charge with no query; a firewall association is about $0.60 per month | under $0.001 | under $0.001 | E |
| Kinesis stream, provisioned, one shard | 1 | about $0.015 per shard-hour; nothing is put | $0.015 | $0.015 | E |
| CloudWatch Logs destination, destination policy, subscription filter, two log groups | 1 each | no charge while nothing is ingested | $0 | $0 | E |
| Firehose delivery stream and its S3 bucket | 1 each | per GB ingested and stored; none | $0 | $0 | E |
| CloudWatch metric stream | 1 | per metric update; its filter names a namespace nothing publishes to | $0 | $0 | E |
| VPC, two subnets, a security group with no rules | 1 | no charge | $0 | $0 | E |

**Total for one hour: about $0.27.** Standing cost left running by mistake: about $0.27 per hour, $6.50 per day.

The delivery bucket is not emptied by a destroy (`force_destroy` is off), on purpose: the metric stream's filter names a
namespace (`SeedW3n<run id>`) that nothing publishes to, so no object should be written. If one is, the destroy fails
on the bucket and names it, and the leftover check below finds it.

Not seeded, and why: `Route53Resolver::OutpostResolver` (needs an Outpost), `Kinesis::StreamConsumer` (enhanced fan-out is
billed per consumer-shard-hour and per GB; left for a later module), `Logs::*` types listed in the ops note that this module
does not cover, `Route53Resolver` rule and query log associations (not collected types, so nothing to compare).

Leftover check for this module: `aws resolver list-resolver-endpoints`, `aws kinesis list-streams`,
`aws logs describe-destinations` and `aws firehose list-delivery-streams`, looking for names starting `seed-w3n-<run id>`;
then the tag sweep.
