# Wave 1b cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Time box 1 hour (everything is created in minutes). Source key: **P** = price
read from a price list; **E** = estimate or recollection, no price file read for it.

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| WAFv2 web ACL (no rules, attached to nothing) | 1 | $5.00 per web ACL-month, prorated hourly | $0.00685 | $0.00685 | E (from the public WAF price page; no price file read) |
| WAFv2 rule group, IP set, regex set | 1 each | rule group $1.00 per month; sets no charge | $0.00137 | $0.00137 | E |
| Backup vault, plan, selection, report plan, restore-testing plan | 1 each | no charge for the definitions; nothing is backed up, reported or restored | $0 | $0 | E |
| Backup Audit Manager framework | 1 | per-control evaluation charge by AWS Config; a handful of evaluations | under $0.001 | under $0.001 | E |
| CloudTrail trail, switched off | 1 | records nothing | $0 | $0 | E |
| CloudTrail event data store, selector matching nothing | 1 | ingestion and storage charges only; nothing is ingested | $0 | $0 | E |
| S3 buckets (4, empty), access point, Storage Lens (default metrics), Access Grants instance, location and grant | 1 set | no standing charge while empty | $0 | $0 | E |
| VPC, subnet, security group with 2 rules, network interface, flow log to an empty bucket | 1 set | no charge; no traffic | $0 | $0 | E |
| IAM roles and policies | 1 set | no charge | $0 | $0 | E |
| Config aggregation authorisation, Security Hub custom action and insight | 1 each | no charge | $0 | $0 | E |

**Total for one hour: under $0.02.** Left running by mistake it is about $0.01 an hour, $0.25 a day. Nothing here is a
costly module; the only resource with a standing charge is the web ACL.

Not seeded, and why: the account is a Control Tower member with a GuardDuty detector, a Security Hub hub, a Config
recorder and delivery channel, trails and an Access Analyzer already in place. A second of any of them cannot be created,
and a child created on one of them (a GuardDuty filter or IP set, an Analyzer archive rule) would add content to an
object this run did not make, so those types are read against what the account has, not seeded. Inspector is disabled.
Organizations types are read-only here. Also left out: `IAM::SAMLProvider` and `IAM::ServerCertificate` (need a
certificate or metadata document), `IAM::OIDCProvider` and `IAM::VirtualMFADevice` (the seeder's IAM policy does not allow
them: tried on 2026-11-02, `AccessDenied` on `iam:CreateOpenIDConnectProvider` and `iam:CreateVirtualMFADevice`),
`Backup::RestoreTestingPlan` (the create call is refused, `AccessDeniedException`, and so is the collector's list),
`CloudTrail::EventDataStore` (CloudTrail Lake accepts no new customers), `KMS::ReplicaKey` (a second region), `Backup::LogicallyAirGappedBackupVault`
(a vault lock cannot be undone), `Backup::LegalHold`, `Backup::TieringConfiguration`, `Backup::RestoreTestingSelection`,
`S3::StorageLensGroup` and `Config::StoredQuery` (no Terraform resource in provider 6.71.0 or a key the manifest builds
from a composite), `CloudTrail::Channel` and `Dashboard`, `Config::ConfigRule`, `Config::Connector`,
`SecurityHub::AutomationRule` (the collector's list call is refused for the account), and every weight-5 type whose
manifest entry has no typed fields to compare.
