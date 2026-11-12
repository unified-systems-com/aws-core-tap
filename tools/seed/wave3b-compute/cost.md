# Wave 3b compute cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it. GovCloud
rates are usually a little above the commercial ones, so each figure below is rounded up by 20 percent.

Time box 1 hour (the balancers and the Transit Gateway attachments take 3 to 10 minutes to create and to delete; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| Application load balancer, internal, no traffic | 1 | $0.0225 per hour | $0.027 | $0.027 | E |
| Classic load balancer, internal, no traffic | 1 | $0.025 per hour | $0.030 | $0.030 | E |
| Transit Gateway VPC attachment and connect attachment | 2 | $0.05 per attachment-hour | $0.120 | $0.120 | E |
| Transit Gateway, route table, multicast domain (no association) | 1 each | no charge | $0 | $0 | E |
| ECS cluster, task definition, service (desired 0) | 1 each | no charge with no task | $0 | $0 | E |
| EFS file system, mount target, access point (empty) | 1 each | $0.30 per GB-month stored; nothing stored | $0 | $0 | E |
| VPC gateway endpoint to S3 | 1 | no charge | $0 | $0 | E |
| VPC, two subnets, security group | 1 set | no charge | $0 | $0 | E |

**Total for one hour: about $0.18.** With a doubled duration: under $0.40.
Standing cost left running by mistake: about $0.18 per hour, $4.30 per day.

Not seeded, and why: `ECS::CapacityProvider` (ECS tags the Auto Scaling group it names `AmazonECSManaged=true`, and the catalog has one tag rule for Auto Scaling groups, which the ops module's group already uses), `EC2::VPCEndpointService` and `VPCEndpointConnectionNotification` (an endpoint service needs a network balancer, and the collector's balancer entity holds application balancers only: a network balancer is not collected), `ECS::TaskSet` (needs a service with the external deployment controller and a running task),
`ECS::Daemon`, `ECS::DaemonTaskDefinition` and `ECS::Gateway` (not asked for), `ElasticLoadBalancingV2::TrustStore` (needs a CA
bundle in S3), `EC2::ClientVpnEndpoint` (needs a server certificate in ACM), `EC2::TransitGatewayPeeringAttachment` (needs a
second transit gateway in another region), `EC2::TransitGatewayConnectPeer` (needs a running peer address), `EC2::TransitGatewayPolicyTable` and
`TransitGatewayMeteringPolicy` (not seeded yet), `EC2::TransitGatewayVpcAttachment` (held under the generic attachment type; the
catalog allows one CloudFormation type per Terraform resource type).
