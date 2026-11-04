# Wave 3b connect cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (the instance takes a few minutes to become active; the rest is created in seconds; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| Connect instance, SAML identity, calls off | 1 | billed by call minutes, chat messages and agent use; none | $0 | $0 | E |
| Hours of operation, queue, quick connect, routing profile, security profile, user, hierarchy group, contact flow, flow module | 1 each | no charge while unused | $0 | $0 | E |

**Total for one hour: under $0.01.** Standing cost left running by mistake: under $0.01 per hour.

The first instance in an account may create the service-linked role `AWSServiceRoleForAmazonConnect`; none was found under `connect.amazonaws.com` after the run.

No phone number is claimed (a number bills monthly and needs a quota). Not seeded, and why: `Connect::Vocabulary` (the collector role is denied the read: `SearchVocabularies` answers `AccessDeniedException`; the action is not yet in `tools/coverage/extended-read-actions.json`); the other Connect types have no Terraform resource, or need a claimed phone number, a Lambda function, an integration or a task to have happened.
