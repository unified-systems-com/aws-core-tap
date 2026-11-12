# Wave 4 gap sweep cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read. GovCloud rates
are usually a little above commercial ones, so each figure is rounded up by 20 percent.

Time box 1 hour (the load balancers and the cache node take a few minutes to create and to delete; E)

| Resource | Quantity | Rate | Per hour | Source |
| --- | ---: | --- | ---: | :---: |
| `t3.nano` instance (the standalone one) and the one the Auto Scaling group runs | 2 | $0.0052 per hour | $0.013 | E |
| Network and application load balancer, internal, no traffic | 2 | $0.0225 per hour | $0.054 | E |
| `cache.t4g.micro` Memcached node | 1 | $0.016 per hour | $0.020 | E |
| 1 GB gp3 volume, two 8 GB instance root volumes | 3 | about $0.08 per GB-month | $0.002 | E |
| Private hosted zone | 1 | $0.50 per month | $0.001 | E |
| VPC, subnets, groups, rule, network interface, launch template | 1 set | no charge | $0 | E |

**Total for one hour: about $0.09.** Standing cost left running by mistake: about $0.09 per hour, $2.20 per day.
