# Wave 2 Network Firewall cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **P** = price read from the AWS Price List file for `us-gov-west-1` on 2026-11-02 (`AmazonRDS` 20261029070635, `AWSNetworkFirewall` 20260911124604); **E** = my estimate or recollection, no price file read for it.

Time box 90 minutes (a firewall takes 10 to 15 minutes to create)

| Resource | Quantity | Rate | Per hour | 90 minutes | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| Firewall endpoint (one subnet) | 1 | $0.474 per endpoint hour | $0.47400 | $0.71100 | P |
| Secondary endpoint (VPC endpoint association, in the second VPC) | 1 | $0.190 per secondary endpoint hour | $0.19000 | $0.28500 | P |
| Traffic processed | 0 GB | $0.078 per GB | $0 | $0 | P (nothing is sent) |
| Firewall policy, stateless rule group, two VPCs and subnets | 1 each | no charge listed in the price file | $0 | $0 | P for the rule group and policy; E for the VPCs |

**Total for 90 minutes: about $1.00.**
Standing cost left running by mistake: **$0.66 per hour, about $16 per day.** This is the module that needs the
hard time box and a watchdog.


Seeded: four `AWS::NetworkFirewall::*` types (firewall, firewall policy, rule group, VPC endpoint association). Not seeded: `TLSInspectionConfiguration` (needs a certificate), `ContainerAssociation` (the collector role is refused its list call), `LoggingConfiguration` (needs a log destination). The standing cost of this module left running by mistake is about $0.66 an hour, $16 a day: destroy it as soon as the check has run.
