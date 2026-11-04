# Wave 3b misc3 cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in seconds; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| CloudWatch RUM app monitor | 1 | billed per event collected; none | $0 | $0 | E |
| Lex V2 bot (no locale), EventBridge Scheduler schedule (disabled), SQS queue | 1 each | no charge while unused | $0 | $0 | E |
| IAM roles (two) and one inline policy | | no charge | $0 | $0 | E |

**Total for one hour: under $0.01.** Standing cost left running by mistake: under $0.01 per hour.

Not seeded, and why: `InternetMonitor::Monitor` (no Internet Monitor endpoint resolves in this region: `no such host`), `CloudTrail::EventDataStore` (`InvalidParameterException`: CloudTrail Lake is no longer accepting new customers), `Bedrock::Agent` (the API requires the agent's role to be named `AmazonBedrockExecutionRoleForAgents_...`, which the seed's role-name rule, `seed-...`, does not allow; a different rule for one role would need the seeder's IAM policy to allow that prefix), `CloudWatch::AlarmMuteRule` (not tried: it needs alarms to mute), the rest of the uncovered Bedrock agent types (they need an agent or a knowledge base).
