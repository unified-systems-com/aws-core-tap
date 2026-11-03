# Wave 3 EKS cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **P** = price read from the AWS Price List file for `us-gov-west-1` (`AmazonEKS` 20261027191639 read on 2026-11-02; `AmazonEC2` 20261029175634 read on 2026-11-01); **E** = my estimate or recollection, no price file read for it.

Time box 2 hours (the control plane takes about 10 minutes to create, the node group about 5, and the identity provider
association updates the control plane twice, on apply and on destroy, 15 to 30 minutes each; E)

| Resource | Quantity | Rate | Per hour | 2 hours | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| EKS cluster, standard support (the upgrade policy keeps it off extended support, $0.50 an hour more) | 1 | $0.10 per cluster-hour | $0.10000 | $0.20000 | P |
| EC2 `t3.medium` node, Linux, on demand | 1 | $0.0488 per instance-hour | $0.04880 | $0.09760 | P |
| Root volume of the node (gp2 or gp3, whichever EKS picks) | 20 GiB | at most $0.12 per GB-month, /730 h | $0.00329 | $0.00658 | P for the rate, E for the type |
| Public IPv4 address of the node | 1 | $0.005 per address-hour | $0.00500 | $0.01000 | E |
| Add-on, access entry, pod identity association, identity provider config | 1 each | no charge; nothing is scheduled | $0 | $0 | E |
| VPC, 4 subnets, internet gateway, route table, IAM roles | 1 set | no charge | $0 | $0 | E |

**Total for two hours: about $0.31** (the wave 3 note had $0.20, for 90 minutes of control plane and 60 of node; the
identity provider association makes the run longer). With a doubled duration: under $0.65.
Standing cost left running by mistake: about $0.16 per hour, $3.75 per day. Destroy it when the time box ends.

Seeded: 6 EKS types (cluster, node group, add-on, access entry, identity provider config, pod identity
association). Not seeded: `Capability` (new, unpriced), `CertificateAuthority` (EKS makes it with the cluster; there
is no Terraform resource for it).

Not seeded: Fargate profile (the Fargate pod execution role cannot be created: IAM rejects the service principal `eks-fargate-pods.amazonaws.com` in this partition).
