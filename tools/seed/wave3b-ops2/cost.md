# Wave 3b ops2 cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in seconds; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| ECR repository creation template | 1 | no charge; no repository is created | $0 | $0 | E |
| Launch template, Auto Scaling group (capacity 0) and lifecycle hook | 1 each | no charge; no instance exists | $0 | $0 | E |
| CloudWatch Contributor Insights rule | 1 | about $0.50 per rule per month, plus per matched event; none match | under $0.001 | under $0.001 | E |
| VPC, subnet, log group | 1 each | no charge | $0 | $0 | E |

**Total for one hour: under $0.01.** Standing cost left running by mistake: under $0.01 per hour.

Not seeded, and why: `SSM::ResourceDataSync` (it applies, but the sync writes the account's managed-instance inventory into its bucket, content outside the state, which the seed's no-force-destroy rule (`test_nothing_outside_the_state_is_deleted_by_a_destroy`) correctly refuses to delete; a first run left a bucket of seven objects that I emptied and destroyed by hand), `Logs::DeliveryDestination` (it applies, but its tags read back different from the Terraform state: `tags-differ`; the cause is not established), `Events::Endpoint` (a global endpoint needs event buses in two regions), `Logs::DeliverySource` (needs a resource that produces logs to deliver), the other Logs delivery types, `CloudFormation::StackSet` and the other CloudFormation types (left for a later module).

