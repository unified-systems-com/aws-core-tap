# Wave 3 ElastiCache cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **P** = price read from the AWS Price List file for `us-gov-west-1` on 2026-11-02 (`AmazonElastiCache` 20261028192450); **E** = my estimate or recollection, no price file read for it.

Time box 90 minutes (a replication group and a cache cluster take 10 to 20 minutes to create; E)

| Resource | Quantity | Rate | Per hour | 90 minutes | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| `cache.t4g.micro` node: the Valkey replication group's primary ($0.0152 per node-hour) and a Redis OSS cluster ($0.019 per node-hour) | 2 | $0.0342 per hour together | $0.03420 | $0.05130 | P |
| Serverless Valkey data storage, billed on the 100 MB minimum | 0.1 GB | $0.101 per GB-hour | $0.01010 | $0.01515 | P for the rate, E for the 100 MB minimum |
| Serverless Valkey ECPUs | a few thousand (health checks only) | $0.0027 per million ECPUs | under $0.001 | under $0.001 | P |
| Subnet group, parameter group, two users, user group, VPC, 2 subnets, security group | 1 set | no standing charge | $0 | $0 | E |

**Total for 90 minutes: about $0.06.** With every "under $0.001" counted as $0.001 and a doubled duration: under $0.13.
Standing cost left running by mistake: about $0.041 per hour, $1 per day.

Seeded: 7 ElastiCache types (replication group, cache cluster, parameter group, subnet group, user, user group,
serverless cache). Not seeded: `Snapshot` and `ServerlessCacheSnapshot` (provider 6.71.0 has no resource for either; the
only Terraform road is a final snapshot on destroy, which would outlive the state), `GlobalReplicationGroup` (a global
datastore needs a larger node type than `cache.t4g.micro` and a second region; E), `SecurityGroup` (EC2-Classic).
