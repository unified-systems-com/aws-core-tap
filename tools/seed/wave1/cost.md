# Wave 1 cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Planned duration 2 hours, from apply start to destroy end.
The budget is $50 per day for the whole day; wave 1 is expected to cost about three cents.

Source key: **P** = price read from the AWS Price List file for `us-gov-west-1` on 2026-11-01 (the version stamps are in
the "Price file" column). **E** = my estimate or recollection, no price file read for it.

| Resource | Quantity | Rate | Per hour | 2 hours | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| EC2 `t3.micro`, Linux, shared tenancy, on demand | 1 | $0.0122 per instance hour | $0.01220 | $0.02440 | P (`AmazonEC2` 20261029175634) |
| EBS gp3 root volume of the instance | 8 GiB | $0.096 per GB-month, /730 h | $0.00105 | $0.00211 | P (same file) |
| EBS gp3 data volume, unattached | 1 GiB | $0.096 per GB-month, /730 h | $0.00013 | $0.00026 | P (same file) |
| gp3 IOPS and throughput | baseline | the 3,000 IOPS and 125 MiB/s baseline is included; nothing provisioned above it | $0 | $0 | E (the price file lists charges only for provisioned IOPS/throughput; I did not read the included baseline) |
| KMS customer managed key | 1 | $1 per key-month, prorated /730 h | $0.00137 | $0.00274 | P (`awskms` 20261026201814); that it is prorated hourly is E |
| Secrets Manager secret | 1 | $0.40 per secret-month, prorated /730 h | $0.00055 | $0.00110 | P (`AWSSecretsManager` 20260911124610); that it is prorated hourly is E |
| Secrets Manager, KMS and API requests | a few dozen | $0.05 per 10,000 requests (Secrets Manager); KMS request charges negligible at this count | under $0.001 | under $0.001 | P for Secrets Manager, E for KMS |
| S3 buckets (3), versioning on one, no objects | 3 | no standing charge while empty; a few requests | under $0.001 | under $0.001 | E |
| DynamoDB table, on demand | 1 | no standing charge with no reads or writes | $0 | $0 | E |
| SQS queue, SNS topic, Lambda function, CloudWatch log group, EventBridge rule (disabled), SSM standard parameter | 1 each | no standing charge; nothing is invoked, published, ingested or sent | $0 | $0 | E |
| VPC, 2 subnets, internet gateway, route table, network ACL, 2 security groups | 1 set | no charge | $0 | $0 | E |
| Public IPv4 addresses | 0 | the instance has no public address and no Elastic IP is created | $0 | $0 | E (by construction; checked in the Terraform, not on a bill) |
| IAM role, user, group, policy, instance profile | 1 each | no charge | $0 | $0 | E |
| NAT gateways, load balancers, databases, EKS, Redshift, search | 0 | none are declared (a test fails if one is added) | $0 | $0 | measured: grep of the Terraform |

**Total for two hours: about $0.032** (sum of the rows above, rounded). With every "under $0.001" counted as $0.001 and a
doubled duration (4 hours) it is still under $0.07. The standing cost of a wave left running by mistake is about
$0.0153 per hour, or about $0.37 per day.

After destroy: the KMS key is only scheduled for deletion (7-day window, the shortest KMS allows). That I expect a key
pending deletion not to be billed is E (I did not read it); if it is, the cost is under $0.03 for the window.
Secrets Manager secrets are deleted at once (`recovery_window_in_days = 0`).

Not in the estimate: data transfer (none is generated), CloudTrail or Config charges the account may already run, and any
other activity in the account.
