# Wave 1c cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (the provider is created in under a minute; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| IAM SAML provider | 1 | no charge | $0 | $0 | E |

**Total for one hour: $0.** Standing cost left running by mistake: $0.

Seeded: `IAM::SAMLProvider`. Its metadata is a public self-signed certificate for `seed-idp.example.invalid`; the private
key was destroyed when the certificate was made and exists nowhere.

Not seeded, and why:

- `AccessAnalyzer::ArchiveRule` (and the unused-access analyzer it needs): the analyzer is billed at $0.20 per IAM role
  or user analysed per month, about $9 for this account if a partial month is not prorated. Left out until that spend is
  approved. The archive rule's key (`<analyzer ARN>/archive-rule/<name>`) also needs a `concat` value spec in `expected.py`.
- `Config::ConfigRule`, `Config::ConfigurationAggregator`, `Config::ConformancePack`: the provider has resources for
  them, but the manifest has no entry for `aws_config_rule`, `aws_config_aggregator` or `aws_config_conformance_pack`
  (only the organization variants), and `compare.py` stops on a type the manifest lacks.
- `Config::StoredQuery`, `Backup::LegalHold`, `S3::StorageLensGroup`: the manifest collects them, but provider 6.71.0
  has no resource for any of them.
- `EC2::SecurityGroupEgress`: the manifest has one entity, `aws_ec2_security_group_rule`, for ingress and egress rules,
  and the catalog allows one CloudFormation type per entity type (`AWS::EC2::SecurityGroupIngress` holds it, wave 1b).
- `KMS::ReplicaKey`: collected as `aws_kms_key`, which `AWS::KMS::Key` already holds in the catalog, and a replica
  lives in a second region while `compare.py` collects `us-gov-west-1` only.
- GuardDuty, Security Hub, Inspector, Organizations, the Config recorder and delivery channel, and CloudTrail Lake:
  handled elsewhere.
