# validate

Live validation of the collector against a real account, in waves
(`specs/spec-aws-core-live-validation.md`). Nothing here is part of the plugin wheel.

## Wave 0: call-path smoke (`wave0_smoke.py`)

A read-only pass over every manifest-driven type, with the collector's own read-only identity. For each type and
region it drives the real engine path (`iter_source`, `project_item`, `resolve_node_tags`) and records the outcome,
the row count, the AWS calls made, the seconds taken and the error class. It builds no batch, writes nothing to the
grid and nothing to AWS; a guard (`readguard.py`, standard library only, unit-tested) refuses any operation whose name is not a read verb, any
read-named operation that returns credentials (`GetSecretValue`, `GetSessionToken`, `GetPasswordData` and the rest of
its list), and any request that asks the service to reveal a secret (`WithDecryption`, `includeValue`), and refuses `GetConnection(s)` unless `HidePassword` is true. The refused-operation list is a deny list of known credential-returning names, not a proof that no other read returns a secret: `test_readguard.py` checks every operation the manifest names against it, and the by-product operations below are the known exceptions. It is a botocore `before-parameter-build` handler (`readguard.install(session)`, tested against real botocore clients: a write, a credential-returning read and a revealing request are refused before anything is sent), and it must be installed before any client is built, because a client copies the session's handlers when it is created. It is registered on the session, so any client built from that session is covered (a client built from another session, or with `boto3.client`, would not be). It does not stop an operation the collector itself makes that returns a secret as a by-product of describing something else (`DescribeUserPoolClient`, `DescribeListeners`, `DescribeVerifiedAccessTrustProviders`, listed in `readguard.BY_PRODUCT_SECRETS`): the manifest drops those fields, so the smoke test holds them in memory as production does and never writes them. A zero-row result proves the
call path only (see the spec's three layers).

Run it inside the stack's web container, which holds the collector's secret:

```
scripts/dc exec -T web uv run python manage.py shell -c \
  "exec(open('/app/_dev-plugins/aws_core/tools/validate/wave0_smoke.py').read())"
```

`WAVE0_ONLY` takes comma-separated `fnmatch` patterns on the entity type, `WAVE0_LIMIT` the first N entries,
`WAVE0_OUT` a JSON path inside the container, `WAVE0_MESSAGES=1` records error messages for local debugging only. The result is printed between `WAVE0_JSON_BEGIN` and
`WAVE0_JSON_END`.

## Run records (`runs/`)

One file per run: counts, operation names and error codes only. An entry that made no AWS call (a parent-dependent type with no parent resources) is `not-exercised`, never `empty`: it is not evidence that its call path works. From the run after this change a result also carries `calls_made`, every `service.operation` the entry made, so a successful call can be audited; `wave0-2026-11-01.json` predates it and records operation names for failed calls only (`failed_calls`). Never resource content, never error messages (they can
name resources), and account numbers removed because this repository is public. A record is the merge of the first
pass and a re-run of the entries that did not come back clean (the re-run replaces the first result), so it is not
the raw output of one invocation of the script. The ledger decisions cite these files as the evidence for a type's
live state.

| File | What |
| --- | --- |
| `runs/wave0-2026-11-01.json` | Wave 0 over 898 manifest-driven types, `us-gov-west-1`, GovCloud staging account |
| `runs/wave0-2026-11-02.json` | The same wave re-run on main after the outcome work (#163): same ok, empty and denied sets, non-ok entries labelled by the collector's own classifier (103 access-denied, 68 unsupported-in-partition, 26 not-configured, 3 throttled, 13 still unclassified) |
| `runs/wave1-2026-11-01.json` | Wave 1 first cycle: 24 entity types seeded with Terraform, collected and compared; 23 pass, one S3 failure that was a wrong expectation (the service default for a bucket's public access block) |
| `runs/wave1-2026-11-02.json` | Wave 1 on the fixed harness: 24 of 24 pass; three S3 buckets (public access block on, default, off), the S3 encryption edge checked; torn down from the run's own state |
| `runs/wave2-rds-2026-11-02.json` | Wave 2, RDS: 14 entity types (20 compared with the types the module needs), all pass on the second cycle; the first cycle failed `aws_rds_db_cluster_endpoint` (fixed in #175) |
| `runs/wave2-nfw-2026-11-02.json` | Wave 2, Network Firewall: firewall, policy and rule group pass; the VPC endpoint association fails because the collector role is refused its list call (a known miss, #172) |
| `runs/wave1b-2026-11-02.json` | Wave 1b, the remaining wave 1 types (Backup, WAFv2, S3 access points, Storage Lens and Access Grants, flow log, network interface, trail, Config aggregation authorization, Security Hub action target and insight): 21 entity types (27 compared with the types the module needs), all pass on the third cycle; the second cycle failed Storage Lens tags (fixed in #178) |
| `runs/wave3-redshift-2026-11-02.json` | Wave 3a, Redshift: 11 entity types (18 compared with the types the module needs), all pass; the node is `ra3.large` because GovCloud refuses `dc2.large` for new clusters |
| `runs/wave3-elasticache-2026-11-02.json` | Wave 3a, ElastiCache: 7 entity types (10 compared), all pass; Valkey users use IAM authentication and the standalone cache cluster runs Redis OSS |
| `runs/wave3-eks-2026-11-02.json` | Wave 3a, EKS: 6 entity types (11 compared), all pass; the Fargate profile is not seeded because IAM rejects the Fargate service principal here |
| `runs/wave3-opensearch-2026-11-02.json` | Wave 3a, OpenSearch: the VPC domain (4 compared), passes |
| `runs/wave1c-2026-11-02.json` | Wave 1c, the IAM SAML provider (the one weight-5 leftover type that could be created at no cost and compared), passes |
| `runs/wave3b-ops-2026-11-03.json` | Wave 3b, operations: 22 types compared across SNS, CloudWatch, Logs, EventBridge, Systems Manager, CloudFormation, Auto Scaling and ECR, all pass; four types the account or region refuses are not seeded |
| `runs/wave3b-edge-2026-11-03.json` | Wave 3b, edge services: 27 types compared across Cognito, API Gateway, Route 53 and WAF Classic, all pass; types the account or region refuses are not seeded |
| `runs/wave3b-compute-2026-11-03.json` | Wave 3b, compute and network: 20 types compared across ECS, EFS, load balancers, VPC endpoints and Transit Gateway, all pass; four types the first run failed are explained in the run note |
| `runs/wave3b-bedrock-2026-11-03.json` | Wave 3b, Bedrock: 5 types compared (guardrail, prompt, flow, application inference profile and the flow's IAM role), all pass; agents cannot be created (maintenance mode) |
| `runs/wave3b-net-2026-11-03.json` | Wave 3b, DNS and streaming: 20 types compared (Route 53 Resolver and DNS Firewall, Kinesis, Logs destination and subscription filter, Firehose, metric stream, and the VPC, subnets, log groups, bucket and roles under them), all pass |
| `runs/wave3b-data-2026-11-03.json` | Wave 3b, data and application services: 41 types compared (Glue, Athena, Step Functions, AppConfig, DocumentDB, Neptune and MemoryDB configuration objects, Service Catalog, Managed Prometheus, and the bucket, topic and roles under them), all pass; four types the collector's role cannot read or GovCloud refuses are not seeded |
| `runs/wave3b-dev-2026-11-03.json` | Wave 3b, application and developer services: 21 types compared (Lambda layer and alias, Batch, CodeBuild, CodePipeline, Cloud Map, Network Manager, and the function, bucket, roles and VPC under them), all pass; Lambda function URLs and event source mappings are not seeded |
| `runs/wave3b-svc-2026-11-04.json` | Wave 3b, service definitions: 15 types compared (IoT Core, SES v2, Rekognition collection, Transcribe, and the IAM role), all pass; the Location types and the Rekognition project cannot pass and are not seeded |
| `runs/wave3b-vpc-2026-11-04.json` | Wave 3b, EC2 and VPC extras: 19 types compared (key pair, placement group, prefix list, DHCP options, egress-only gateway, customer and virtual private gateways, VPN connection, peering, launch template, traffic mirror filter and rule, network insights path, Elastic IP and NAT gateway, with the module's VPCs, subnet and gateway), all pass; the traffic mirror target is refused for a detached interface and is not seeded |
| `runs/wave3b-ml-2026-11-04.json` | Wave 3b, SageMaker definitions: 9 types compared (pipeline, model package group, model card, hub, code repository, app image configuration, two lifecycle configurations, and the IAM role), all pass; the model, endpoint configuration, feature group and human task UI cannot be created here and are not seeded |
| `runs/wave3b-connect-2026-11-04.json` | Wave 3b, Amazon Connect: 10 types compared (instance, hours of operation, queue, quick connect, routing profile, security profile, user, hierarchy group, contact flow, flow module), all pass; the vocabulary cannot be read by the collector role and is not seeded |
| `runs/wave3b-xfer-2026-11-04.json` | Wave 3b, transfer definitions: 9 types compared (Transfer Family server, user and workflow, Pinpoint app, AppStream stack, and the IAM role, VPC, subnet and security group), all pass; the DMS data provider and instance profile, the Pinpoint email template and the MSK configuration cannot pass and are not seeded |
| `runs/wave3b-misc-2026-11-04.json` | Wave 3b, small free definitions: 10 types compared (Scheduler group, X-Ray group and sampling rule, Resource Groups group, Signer profile, CodeCommit repository, RAM share, Synthetics group, CodeConnections connection, Recycle Bin rule), all pass; AppRegistry and the OAM sink cannot pass and are not seeded |
| `runs/wave3b-misc2-2026-11-04.json` | Wave 3b, more small free definitions: 11 types compared (OpenSearch Serverless encryption, access and lifecycle policies, EMR security configuration, Route 53 delegation set, Direct Connect gateway, CodeDeploy deployment configuration, DAX subnet and parameter groups, and the VPC and subnet), all pass; the SES receipt types and the License Manager configuration cannot pass and are not seeded |
| `runs/wave3b-ops2-2026-11-04.json` | Wave 3b, more operations definitions: 8 types compared (ECR repository creation template, Auto Scaling lifecycle hook and group, Contributor Insights rule, launch template, VPC, subnet, log group), all pass; the SSM data sync and the Logs delivery destination are not seeded |
| `runs/wave3b-compute2-2026-11-04.json` | Wave 3b, more compute definitions: 11 types compared (Lambda code signing configuration, ECS task set with its cluster, task definition and service, DLM lifecycle policy, and the VPC, subnet, security group, IAM role and Signer profile), all pass; the task set passes only with the fix in #196; the IAM OIDC provider and the ECS capacity provider are not seeded |

Not covered by wave 0: the hand-written readers (landing zone, Organizations, findings), which run only through the
full collector.
