# Wave 3b svc cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in under two minutes; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| IoT thing group, billing group, thing type, policy, topic rule (disabled), role alias, provisioning template (disabled) | 1 each | per message and per registry operation; none | $0 | $0 | E |
| SES v2 configuration set, contact list, domain identity (never verified), standard IP pool | 1 each | per message sent and per dedicated address; none | $0 | $0 | E |
| Rekognition face collection | 1 | per image analysed and per face stored; none | $0 | $0 | E |
| Transcribe vocabulary and vocabulary filter | 1 each | per second transcribed; none | $0 | $0 | E |
| IAM role | 1 | no charge | $0 | $0 | E |

**Total for one hour: $0.** Standing cost left running by mistake: about $0 per hour.

Types the module tried and does not seed, and why:

- `Location::GeofenceCollection`, `PlaceIndex`, `RouteCalculator`, `Tracker`: the collector's role is denied `geo:ListGeofenceCollections`, `ListPlaceIndexes`, `ListRouteCalculators` and `ListTrackers` (all four are in `tools/coverage/extended-read-actions.json`), so the read fails with `AccessDeniedException`.
- `Location::Map`: the map lists, but reading its tags fails for the collector's role (`tags-unread`). The denied action is not named in the compare output and is not in `extended-read-actions.json`; the cause is not established beyond the tag read failing.
- `Rekognition::Project`: `CreateProject` answers AccessDeniedException for the seeder, so the type cannot be created here.
- Not tried: IoT authorizer (needs a Lambda function), CA certificate, certificate, certificate provider, domain configuration, topic rule destination, OTA update, stream, job template, security profile, fleet metric, scheduled audit, mitigation action, custom metric, dimension, command and software package (no Terraform resource in the pinned provider, or a certificate or a function is needed), SES custom verification template, template, tenant and multi-region endpoint (no resource, or a verified identity is needed), Rekognition dataset and stream processor (need a project, or a video stream), and the Transcribe medical vocabulary and call analytics category (need an S3 object, or no resource).

Leftover check for this module: `aws iot list-thing-groups`, `list-billing-groups`, `list-thing-types`, `list-policies`, `list-topic-rules`, `list-role-aliases` and `list-provisioning-templates`, `aws sesv2 list-configuration-sets`, `list-contact-lists`, `list-email-identities` and `list-dedicated-ip-pools`, `aws rekognition list-collections`, `aws transcribe list-vocabularies` and `list-vocabulary-filters`, and `aws iam list-roles`, looking for names starting `seed-w3s-<run id>`; then the tag sweep.
