# Wave 3b dev cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in under two minutes; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| Lambda function, layer version, alias | 1 each | per request and per GB-second; none is invoked | $0 | $0 | E |
| Batch unmanaged compute environment, job queue, scheduling policy, job definition | 1 each | no charge; an unmanaged environment starts no instance, and nothing is submitted | $0 | $0 | E |
| CodeBuild project, report group | 1 each | per build minute; none is built | $0 | $0 | E |
| CodePipeline pipeline (V1, S3 source, manual approval) and a custom action type | 1 each | $1.00 per active pipeline per month, free for its first 30 days; E | $0 | $0 | E |
| Cloud Map private namespace, HTTP namespace, service | 1 each | per registered instance and per query; none | $0 | $0 | E |
| Network Manager global network, site, device, link | 1 each | no charge | $0 | $0 | E |
| S3 bucket (empty), VPC | 1 each | no charge | $0 | $0 | E |

**Total for one hour: $0.** Standing cost left running by mistake: about $0 per hour. If the pipeline were billed for a whole
month: $1.00 once.

Batch job definitions cannot be deleted, only deregistered. A destroy leaves one `INACTIVE` revision per run, which is free and
which the tagging API lists afterwards. A leftover check must look for `ACTIVE` ones.

Types the module tried and does not seed, and why:

- `Lambda::Url`: CreateFunctionUrlConfig answers 403 AccessDeniedException ("Unable to determine service/operation name to
  be authorized") for the seeder, and the collector's role is denied `lambda:ListFunctionUrlConfigs` (it is in the wave 0
  record), so function URLs do not work here.
- `Lambda::EventSourceMapping`: the mapping is created, but reading its tags fails for the collector's credential
  (`ListTags` answers InvalidParameterValueException) and the same call by the seeder also failed (its message was not
  kept), so the compare stops at `tags-unread`. The cause is not established.
- Not tried: `Lambda::CodeSigningConfig` (needs a signing profile), `Lambda::CapacityProvider`, `Lambda::Version`, `Batch`
  consumable resource, service environment and quota share (no Terraform resource in the pinned provider), `CodeBuild` fleet
  (billed by the hour) and source credential (a token), `CodePipeline` webhook (needs a GitHub connection),
  `ServiceDiscovery::PublicDnsNamespace` (public zones are closed in GovCloud) and the other Network Manager types
  (core network, attachments and peerings need a Transit Gateway or a policy document).

Leftover check for this module: `aws lambda list-functions` and `list-layers`, `aws batch describe-compute-environments`,
`describe-job-queues` and `describe-job-definitions --status ACTIVE`, `aws codebuild list-projects` and `list-report-groups`,
`aws codepipeline list-pipelines` and `list-action-types --action-owner-filter Custom`, `aws servicediscovery list-namespaces`,
`aws networkmanager describe-global-networks`, `aws s3api list-buckets` and `aws iam list-roles`, looking for names starting
`seed-w3v-<run id>`; then the tag sweep.
