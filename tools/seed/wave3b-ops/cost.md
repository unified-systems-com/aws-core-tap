# Wave 3b ops cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in under two minutes; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| SQS queue, SNS topic and its subscription, log group, metric filter, saved query | 1 each | no charge while idle | $0 | $0 | E |
| CloudWatch metric alarm and composite alarm | 2 | about $0.10 per alarm-month, billed by the hour | under $0.001 | under $0.001 | E |
| CloudWatch dashboard | 1 | free for the first three per account; $3.00 per month after | $0 | $0 | E |
| EventBridge bus and archive | 1 each | no charge with no events | $0 | $0 | E |
| Systems Manager document, maintenance window, patch baseline, association | 1 each | no charge | $0 | $0 | E |
| CloudFormation stack (a wait condition handle) | 1 | no charge | $0 | $0 | E |
| launch template, Auto Scaling group (capacity 0), policy, scheduled action; VPC and subnet | 1 each | no charge | $0 | $0 | E |
| ECR repository, no image | 1 | $0.10 per GB-month stored; nothing stored | $0 | $0 | E |

**Total for one hour: under $0.01.** Standing cost left running by mistake: under $0.01 per hour.

Not seeded, and why: `Logs::LogAnomalyDetector` (CreateLogAnomalyDetector answers UnknownOperationException in GovCloud), `Events::Connection` and `Events::ApiDestination` (CreateConnection: "Operation is disabled in this region"), `AutoScaling::LaunchConfiguration` (not available to this account; launch templates only), `Logs::Destination`, `Logs::SubscriptionFilter` (a destination needs a Kinesis stream, an IAM role and a destination
policy; left for a later module), `Logs::DeliverySource`, `Logs::DeliveryDestination`, `Logs::Delivery`, `Logs::Integration`,
`Logs::ScheduledQuery`, `CloudWatch::MetricStream` (needs a Firehose stream), `CloudWatch::InsightRule`, `Events::Endpoint`
(needs buses in two regions), `SSM::ResourceDataSync`, `CloudFormation::StackSet` and the other CloudFormation types,
`AutoScaling::LifecycleHook` and `ECR::RepositoryCreationTemplate` (their keys are `{account}/{region}/...`, which the
catalog cannot yet build), and `ECR::PublicRepository` (ECR Public is not in GovCloud).

Leftover check for this module: the tagging API does not list the Auto Scaling group, which carries no `tap-seed-run` tag
(the provider resource has no `tags_all`, and the catalog can only expect tags it reads from `tags_all`), so after the
tag sweep also run `aws autoscaling describe-auto-scaling-groups` and `aws ec2 describe-launch-templates` and look for names
starting `seed-w3p-<run id>`; the group is created with capacity 0 and holds no instance.
