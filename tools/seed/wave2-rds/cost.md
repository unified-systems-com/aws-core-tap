# Wave 2 RDS cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **P** = price read from the AWS Price List file for `us-gov-west-1` on 2026-11-02 (`AmazonRDS` 20261029070635, `AWSNetworkFirewall` 20260911124604); **E** = my estimate or recollection, no price file read for it.

Time box 2 hours (apply about 25 minutes, destroy about 10; measured on two runs)

| Resource | Quantity | Rate | Per hour | 2 hours | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| RDS `db.t4g.micro` PostgreSQL, Single-AZ | 1 | $0.018 per instance hour | $0.01800 | $0.03600 | P |
| gp2 storage for it (gp2 and gp3 are the same $0.138 per GB-month in the price file) | 20 GiB | $0.138 per GB-month, /730 h | $0.00378 | $0.00756 | P |
| Aurora PostgreSQL Serverless v2 instance at minimum capacity | 0.5 ACU | $0.14 per ACU-hour | $0.07000 | $0.14000 | P (that GovCloud allows a 0.5 ACU minimum is E) |
| Aurora consumed storage and I/O | about 1 GiB, a few requests | $0.13 per GB-month; $0.26 per million I/O | under $0.001 | under $0.001 | P |
| RDS Proxy on the t4g.micro instance | 2 vCPU | $0.018 per vCPU-hour | $0.03600 | $0.07200 | P (the 2 vCPU minimum is E) |
| Manual DB snapshot | 20 GiB | $0.095 per GB-month of backup storage | $0.00260 | $0.00520 | P |
| Aurora cluster snapshot | about 1 GiB | $0.036 per GB-month | under $0.001 | under $0.001 | P |
| Secrets Manager secret for the proxy | 1 | $0.40 per secret-month, /730 h | $0.00055 | $0.00110 | P (wave 1 note) |
| Subnet group, parameter groups (2), option group, event subscription, global cluster container, cluster endpoint, SNS topic, VPC and subnets | 1 each | no standing charge | $0 | $0 | E |

**Total for two hours: about $0.27.** With every "under $0.001" counted as $0.001 and a doubled duration: under $0.60.
Standing cost left running by mistake: about $0.13 per hour, $3 per day.


Seeded: 14 of the 18 `AWS::RDS::*` weight-5 types. Not seeded: `DBSecurityGroup` (EC2-Classic, E), `DBShardGroup` (Aurora Limitless, minimum 16 ACU, about $2.24 an hour), `Deployment` (blue/green copy and switchover), `Integration` (needs a Redshift or OpenSearch target).
