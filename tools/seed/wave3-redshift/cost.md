# Wave 3 Redshift cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **P** = price read from the AWS Price List file for `us-gov-west-1` on 2026-11-02 (`AmazonRedshift` 20260911124505; KMS and Secrets Manager from the wave 1 note); **E** = my estimate or recollection, no price file read for it.

Time box 90 minutes (a ra3.large cluster takes about 10 minutes to create; E)

| Resource | Quantity | Rate | Per hour | 90 minutes | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| Redshift `ra3.large` node, single-node cluster (`dc2.large` is refused for new clusters in GovCloud) | 1 | $0.543 per node-hour | $0.54300 | $0.81450 | P |
| Serverless workgroup at 8 RPU base capacity, no query run | 1 | $0.375 per RPU-hour, billed only while it runs queries | $0 | $0 | P for the rate, E that an idle workgroup bills nothing |
| Manual snapshot of the empty cluster, serverless managed storage | under 1 GiB | $0.024 per GB-month (managed storage); $0.039 per GB-month (serverless snapshots) | under $0.001 | under $0.001 | P |
| Secrets Manager secret holding the master password | 1 | $0.40 per secret-month, /730 h | $0.00055 | $0.00082 | P (wave 1 note) |
| KMS customer managed key for the snapshot copy grant | 1 | $1 per key-month, /730 h | $0.00137 | $0.00205 | P (wave 1 note) |
| Subnet group, parameter group, snapshot schedule, usage limit, scheduled action (disabled), event subscription, snapshot copy grant, serverless namespace, SNS topic, VPC, 3 subnets, security group, IAM role and policy | 1 each | no standing charge | $0 | $0 | E |

**Total for 90 minutes: about $0.83.** With every "under $0.001" counted as $0.001 and a doubled duration: under $1.70.
Standing cost left running by mistake: about $0.54 per hour, $13 per day. Destroy it when the time box ends.

After destroy the KMS key is only scheduled for deletion (7 days, the shortest KMS allows), as in wave 1.

Seeded: 11 Redshift and Redshift Serverless types (cluster, parameter group, subnet group, snapshot, snapshot schedule,
usage limit, scheduled action, event subscription, snapshot copy grant, serverless namespace and workgroup). Not seeded:
`EndpointAccess` (a Redshift-managed VPC endpoint needs an RA3 cluster: `ra3.large` is $0.543 an hour, P, which would
nearly double this module), `Integration` and `RedshiftIdcApplication` / `QEV2IdcApplication` (need a zero-ETL source or
IAM Identity Center), `ClusterSecurityGroup` (EC2-Classic), `RedshiftServerless::Snapshot` (not asked for; possible later
on the empty namespace).
