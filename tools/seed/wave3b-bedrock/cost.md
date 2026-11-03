# Wave 3b Bedrock cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in under two minutes; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| Guardrail, prompt, flow, application inference profile | 1 each | billed per model call or per text unit processed; none is made | $0 | $0 | E |
| IAM role with an inline policy | 1 | no charge | $0 | $0 | E |

**Total for one hour: $0.** Standing cost left running by mistake: $0.

Not seeded, and why: `Bedrock::Agent` and `AgentAlias` (CreateAgent: "Bedrock Agents is in Maintenance Mode. New agent creation is not available"), `Bedrock::KnowledgeBase` and `DataSource` (a vector store, billed by the hour), `FlowAlias` and `FlowVersion`
(no Terraform resource makes a flow version), `GuardrailVersion` and `PromptVersion` (versions have no resource that makes one at a
fixed key), `AutomatedReasoningPolicy` and its version, `Blueprint`, `DataAutomationLibrary`, `DataAutomationProject`,
`IntelligentPromptRouter` and `RetrievalInstruction` (no provider resource at 6.71.0, or not asked for).
