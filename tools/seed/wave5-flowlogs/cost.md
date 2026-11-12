# Wave 5 flow logs cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read. GovCloud rates
are usually a little above commercial ones, so each figure is rounded up by 20 percent.

Time box 2 hours (flow log records reach S3 several minutes after the traffic; the trial waits for them, then runs the
query a few times with different filters; E)

| Resource | Quantity | Rate | Per hour | Source |
| --- | ---: | --- | ---: | :---: |
| `t3.nano` instance (server and client) | 2 | $0.0052 per hour | $0.013 | E |
| Two 8 GB gp3 root volumes | 2 | about $0.08 per GB-month | $0.002 | E |
| Flow log delivery to S3 (a few MB an hour from two instances talking every 20 s) | under 0.01 GB | about $0.30 per GB, Parquet conversion included | $0.003 | E |
| Athena queries (each scans far less than its 10 MB minimum) | about 5 per hour | $5 per TB scanned, 10 MB minimum per query | $0.001 | E |
| S3 storage and requests, Glue catalog entries, the schedule (disabled by default) | 1 set | free tier or fractions of a cent | $0.001 | E |
| VPC, subnet, security group and rules, IAM role | 1 set | no charge | $0 | E |

With `edge_path = true` (E):

| Resource | Quantity | Rate | Per hour | Source |
| --- | ---: | --- | ---: | :---: |
| Application Load Balancer, idle traffic | 1 | about $0.027 per hour plus under 1 LCU at about $0.0096 | $0.04 | E |
| `t3.nano` visitor instance and its root volume | 1 | $0.0052 per hour, 8 GB gp3 | $0.007 | E |
| Public IPv4 address (the visitor's) | 1 | $0.005 per hour | $0.006 | E |
| DynamoDB on-demand table, a put every 20 s | 180 writes an hour | about $1.50 per million writes | under $0.001 | E |
| Internet gateway, gateway endpoint, route tables, IAM role and profile | 1 set | no charge | $0 | E |

**Total for two hours: about $0.04.** With `edge_path`, about $0.15 for two hours, and about $0.07 an hour left running. Standing cost left running by mistake: about $0.02 per hour, $0.50 per day.
