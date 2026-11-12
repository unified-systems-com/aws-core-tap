# Wave 3b compute2 cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in seconds; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| Lambda code signing configuration, Signer profile | 1 each | no charge | $0 | $0 | E |
| ECS cluster, task definition, external-deployment service (desired count 0), task set (scale 0) | 1 each | no charge; no task runs | $0 | $0 | E |
| Data Lifecycle Manager policy, disabled | 1 | no charge; it never runs | $0 | $0 | E |
| VPC, subnet, security group with no rules, one IAM role | 1 each | no charge | $0 | $0 | E |

**Total for one hour: under $0.01.** Standing cost left running by mistake: under $0.01 per hour.

A Signer profile cannot be deleted, only canceled; it stays listed as `Canceled` under its name (one per run).

Not seeded, and why: `IAM::OIDCProvider` (the seeder is denied `iam:CreateOpenIDConnectProvider`: `AccessDenied`; the seeder's policy would need that action), `ECS::CapacityProvider` (it applies and passes, but ECS tags the Auto Scaling group it manages with `AmazonECSManaged`, so the group's tags then differ from the catalog's expectation of none: `tags-differ` on `AutoScaling::AutoScalingGroup`; the harness cannot expect a tag the provider does not set), `Lambda::Version` (a published version is a property of the function, which another module's catalog entry already names; the catalog allows one entry per Terraform resource type), `ECS::Daemon` and `ECS::DaemonTaskDefinition` (not tried: a new ECS feature that this partition is unlikely to offer), the Lambda capacity provider (it needs an instance fleet).
