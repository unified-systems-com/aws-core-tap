# Wave 3b misc4 cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in seconds; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| Bedrock guardrail and one published version | 1 each | billed per text unit assessed; none | $0 | $0 | E |
| CloudWatch metric alarm | 1 | about $0.10 per alarm-month, billed by the hour | under $0.001 | under $0.001 | E |
| CloudWatch alarm mute rule | 1 | no charge | $0 | $0 | E |

**Total for one hour: under $0.01.** Standing cost left running by mistake: under $0.01 per hour.

Not seeded, and why: the other uncovered Bedrock types (an agent, a knowledge base, a flow alias or version, a prompt version) need an agent, a vector store or a role named by the service's own rule, none of which this seed provides.
