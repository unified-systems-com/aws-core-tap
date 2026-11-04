# Wave 3b vpc cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in under ten minutes; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| NAT gateway | 1 | about $0.045 per hour; nothing passes through it | $0.045 | $0.045 | E |
| Site-to-Site VPN connection | 1 | about $0.05 per hour; no tunnel ever comes up | $0.05 | $0.05 | E |
| Elastic IP, attached to the NAT gateway and used as the customer gateway address | 1 | no charge while attached; about $0.005 per hour if left unattached | $0 | $0 | E |
| Key pair, placement group, prefix list, DHCP options, egress-only gateway, customer gateway, virtual private gateway, peering, launch template, traffic mirror filter and rule, network insights path, internet gateway, two network interfaces, two VPCs, a subnet | 1 each | no charge | $0 | $0 | E |

**Total for one hour: about $0.10.** Standing cost left running by mistake: about $0.10 per hour, $2.30 per day.

Not seeded, and why: `EC2::TrafficMirrorTarget` and `EC2::TrafficMirrorSession` (an interface must be attached to a supported instance, which is refused for a detached one), the IPAM types, Verified Access, Client VPN, Instance Connect endpoint, route server and capacity reservation types (billed by the hour at rates that need George's approval, or they need a certificate or an instance), and the local gateway, carrier gateway and Wavelength types (no such zone or device in this account).

Leftover check for this module: the tagging API lists the tagged resources by `tap-seed-run`; the NAT gateway lingers in `deleted` state for about an hour and the tagging API can list it, so confirm with `aws ec2 describe-nat-gateways` that none is `available`.
