# Wave 3b ml cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in under two minutes; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| Pipeline (never started), model package group, model card, hub, code repository, app image configuration, two lifecycle configurations | 1 each | no charge while nothing runs | $0 | $0 | E |
| IAM role | 1 | no charge | $0 | $0 | E |

**Total for one hour: under $0.01.** Standing cost left running by mistake: under $0.01 per hour.

Not seeded, and why: `Model` and `EndpointConfig` (CreateModel checks that the role can pull the image and that the image exists, and no image can be pushed from here); `FeatureGroup` and `HumanTaskUi` (CreateFeatureGroup and CreateHumanTaskUi answer UnknownOperationException: not supported in this region); endpoints, notebook instances, domains, spaces, user profiles, clusters, MLflow servers, monitoring schedules, jobs and inference components (each bills by the hour, runs a container, or needs an image and data this account does not have); `Workforce` and `Workteam` (they need a Cognito user pool, client and domain); `Image` and `ImageVersion` (an image in a registry); the other types have no Terraform resource or need a job to have run.
