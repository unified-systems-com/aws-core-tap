# seed

Terraform seeds, the expected inventory and the comparison harness for live validation of the collector
(`specs/spec-aws-core-live-validation.md`: Seeding, Seed Catalog, Verdict And Promotion, Safety). Nothing here is part
of the plugin wheel.

| File | What it is |
| --- | --- |
| `wave3b-bedrock/` | Terraform root for wave 3b, Bedrock (free): a guardrail, a prompt, a flow and an application inference profile; nothing is invoked. Prefix `w3m`, tag `tap-seed=wave3b-bedrock`; `wave3b-bedrock/cost.md` |
| `wave3b-compute/` | Terraform root for wave 3b, compute and network (cheap, about $0.18 an hour): ECS, EFS, application and classic load balancers, VPC endpoints and Transit Gateway. Prefix `w3k`, tag `tap-seed=wave3b-compute`; `wave3b-compute/cost.md` |
| `wave3b-net/` | Terraform root for wave 3b, DNS and streaming (cheap, about $0.27 an hour): a Route 53 Resolver outbound endpoint with a rule, DNS Firewall, a Kinesis stream with a Logs destination and subscription filter, and a Firehose stream with a metric stream. Prefix `w3n`, tag `tap-seed=wave3b-net`; `wave3b-net/cost.md` |
| `wave3b-data/` | Terraform root for wave 3b, data and application services (free while idle): Glue, Athena, Step Functions, AppConfig, DocumentDB, Neptune and MemoryDB configuration objects, Service Catalog and Managed Prometheus; no database is created. Prefix `w3d`, tag `tap-seed=wave3b-data`; `wave3b-data/cost.md` |
| `wave3b-dev/` | Terraform root for wave 3b, application and developer services (free while idle): a Lambda layer and alias, Batch (unmanaged), CodeBuild, CodePipeline, Cloud Map and Network Manager. Prefix `w3v`, tag `tap-seed=wave3b-dev`; `wave3b-dev/cost.md` |
| `wave3b-svc/` | Terraform root for wave 3b, service definitions (free while idle): IoT Core, SES v2, a Rekognition collection and Transcribe vocabularies. Prefix `w3s`, tag `tap-seed=wave3b-svc`; `wave3b-svc/cost.md` |
| `wave3b-vpc/` | Terraform root for wave 3b, EC2 and VPC extras (about $0.10 an hour): key pair, placement group, prefix list, DHCP options, VPN, peering, launch template, traffic mirror filter, network insights path and a NAT gateway. Prefix `w3x`, tag `tap-seed=wave3b-vpc`; `wave3b-vpc/cost.md` |
| `wave3b-ml/` | Terraform root for wave 3b, SageMaker definitions (free): a pipeline, model package group, model card, hub, code repository, app image configuration and two lifecycle configurations; nothing runs. Prefix `w3l`, tag `tap-seed=wave3b-ml`; `wave3b-ml/cost.md` |
| `wave3b-connect/` | Terraform root for wave 3b, Amazon Connect (free while unused): a SAML instance with hours, queue, quick connect, routing and security profiles, user, hierarchy group, contact flow and flow module. Prefix `w3h`, tag `tap-seed=wave3b-connect`; `wave3b-connect/cost.md` |
| `wave3b-xfer/` | Terraform root for wave 3b, transfer definitions (cheap, about $0.30 an hour): a Transfer Family SFTP server on a VPC endpoint with a user and a workflow, a Pinpoint app and an AppStream stack. Prefix `w3t`, tag `tap-seed=wave3b-xfer`; `wave3b-xfer/cost.md` |
| `wave3b-misc/` | Terraform root for wave 3b, small free definitions: Scheduler group, X-Ray group and rule, Resource Groups, Signer profile, CodeCommit, RAM share, Synthetics group, CodeConnections and a Recycle Bin rule. Prefix `w3y`, tag `tap-seed=wave3b-misc`; `wave3b-misc/cost.md` |
| `wave3b-misc2/` | Terraform root for wave 3b, more small free definitions: OpenSearch Serverless policies, EMR security configuration, Route 53 delegation set, Direct Connect gateway, CodeDeploy configuration, DAX groups. Prefix `w3z`, tag `tap-seed=wave3b-misc2`; `wave3b-misc2/cost.md` |
| `wave3b-ops2/` | Terraform root for wave 3b, more operations definitions: an ECR repository creation template, an Auto Scaling lifecycle hook and a Contributor Insights rule. Prefix `w3q`, tag `tap-seed=wave3b-ops2`; `wave3b-ops2/cost.md` |
| `wave3b-compute2/` | Terraform root for wave 3b, more compute definitions: a Lambda code signing configuration, an ECS external-deployment service with a task set of scale zero, and a disabled DLM policy. Prefix `w3j`, tag `tap-seed=wave3b-compute2`; `wave3b-compute2/cost.md` |
| `wave3b-misc3/` | Terraform root for wave 3b, more small definitions: a CloudWatch RUM app monitor, a Lex V2 bot and a disabled Scheduler schedule aimed at an empty queue. Prefix `w3u`, tag `tap-seed=wave3b-misc3`; `wave3b-misc3/cost.md` |
| `wave3b-edge/` | Terraform root for wave 3b, edge services (about $0.004 an hour): Cognito, API Gateway (REST and HTTP), Route 53 and WAF Classic. Prefix `w3g`, tag `tap-seed=wave3b-edge`; `wave3b-edge/cost.md` |
| `wave3b-ops/` | Terraform root for wave 3b, operations (free while idle): 16 types across SNS, CloudWatch, Logs, EventBridge, Systems Manager, CloudFormation, Auto Scaling and ECR. Prefix `w3p`, tag `tap-seed=wave3b-ops`; `wave3b-ops/cost.md` |
| `wave3-redshift/` | Terraform root for wave 3a, Redshift (costly): one `ra3.large` node and 10 more Redshift and Redshift Serverless types. Prefix `w3r`, tag `tap-seed=wave3-redshift`; `wave3-redshift/cost.md` |
| `wave3-elasticache/` | Terraform root for wave 3a, ElastiCache: a Valkey replication group and a Redis OSS cluster, both `cache.t4g.micro`, a serverless cache and 4 more types. Prefix `w3c`, tag `tap-seed=wave3-elasticache`; `wave3-elasticache/cost.md` |
| `wave3-eks/` | Terraform root for wave 3a, EKS (costly): one control plane, one `t3.medium` node and 4 more EKS types. Prefix `w3e`, tag `tap-seed=wave3-eks`; `wave3-eks/cost.md` |
| `wave3-opensearch/` | Terraform root for wave 3a, OpenSearch: one `t3.small.search` domain in a private subnet. Prefix `w3o`, tag `tap-seed=wave3-opensearch`; `wave3-opensearch/cost.md` |
| `wave2-rds/` | Terraform root for wave 2, RDS (weight 5, costly): 14 of the 18 RDS types. Own state, own provider tag `tap-seed=wave2-rds`; `wave2-rds/cost.md` |
| `wave1b/` | Terraform root for wave 1b: 21 types wave 1 could not seed in one root (Backup, WAFv2, S3 access points, Storage Lens, Access Grants, flow log, network interface, trail, Config aggregation authorization, Security Hub action target and insight). Own state, tag `tap-seed=wave1b`; `wave1b/cost.md`. Not seeded: CloudTrail Lake (closed to new customers), Backup restore testing (create refused), the OIDC provider and virtual MFA device (the seeder policy refuses them) |
| `wave1c/` | Terraform root for wave 1c: an IAM SAML provider (metadata with a public certificate whose private key was never written to disk). Free. Prefix `w1c`, tag `tap-seed=wave1c`; `wave1c/cost.md` |
| `wave2-nfw/` | Terraform root for wave 2, Network Firewall: firewall, policy, rule group and a second endpoint, with the one costly resource that must be destroyed as soon as the check has run; tag `tap-seed=wave2-nfw`; `wave2-nfw/cost.md` |
| `wave1/` | Terraform root for wave 1 (weight 5, free or cheap). Provider `hashicorp/aws` pinned to exactly 6.71.0, region `us-gov-west-1`. `wave1/cost.md` is its cost estimate |
| `seeding.json` | The seed catalog: per CloudFormation type, the entity type, Terraform resource, cost class, needs, the manifest fields to compare and where each expected value lives in the state |
| `expected.py` | Reads `terraform show -json` of the applied state and writes the expected inventory (standard library only) |
| `compare.py` | Runs in the web container: collects the seeded types through the real engine path and writes the per-type verdict |
| `tests/` | Unit tests for all of the above; none needs AWS (`python3 -I -m pytest tools/seed/tests`) |

The state is the expected inventory. The collector never reads it. Both the expected inventory and the verdict are
written under `tools/seed/out/`, which is ignored by git: the expected inventory holds ARNs and so the account number,
and this repository is public. Never commit anything from `out/`, any `*.tfstate`, any plan, or any variable file.

## Running a wave

Two identities, never mixed. The **seeder** profile (default `tap-seeder-git-serious`, set with `-var profile=...`) is
used only by the Terraform commands and the leftover check below. The collector's read-only identity is used only by
`compare.py`, inside the container. Keys are never written to a file, a state backend, a report or a message.

Work from the repository root. Step 0 sets variables; type the account number at the prompt so that it is not in shell
history. It does reach files under `out/`: Terraform's state and saved plans and the expected inventory hold it (in
input values and ARNs). They stay in the git-ignored `out/<run id>` and are deleted at the end (steps 4, 7 and 9).

```
cd tools/seed/wave1
export PROFILE=tap-seeder-git-serious
export RUN_ID=w1$(date +%m%d%H%M)                       # 3-12 lowercase letters/digits; unique per run
read -r -s -p "account: " TF_VAR_expected_account_id; echo; export TF_VAR_expected_account_id
export TF_VAR_run_id=$RUN_ID TF_VAR_profile=$PROFILE
RUN_DIR="$PWD/../out/$RUN_ID"; mkdir -p "$RUN_DIR"
export TF_DATA_DIR="$RUN_DIR/tfdata"                    # per-run plugin and backend directory, so runs never share state
```

1. **Verify the account and region before apply** (the provider also refuses any other account, and a precondition
   refuses any other partition or region):

   ```
   test "$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)" = "$TF_VAR_expected_account_id" && echo account-ok
   aws sts get-caller-identity --profile "$PROFILE" --query Arn --output text | grep -q '^arn:aws-us-gov:' && echo partition-ok
   ```

   Stop if either line is missing. The wave acts only in `us-gov-west-1`. Read `wave1/cost.md` and decide the time box.

2. **Init** with the run's own state file:

   ```
   terraform init -input=false -backend-config="path=$RUN_DIR/terraform.tfstate"
   ```

3. **Plan** and read it. It must show only resources named `seed-w1-$RUN_ID-*` or `/seed-w1-$RUN_ID/*`, in the VPC
   `10.99.0.0/16`, and nothing to change or destroy:

   ```
   terraform plan -input=false -out="$RUN_DIR/plan.tfplan"
   ```

4. **Apply** that plan (`apply` of a saved plan creates exactly what was reviewed):

   ```
   terraform apply -input=false "$RUN_DIR/plan.tfplan"
   rm -f "$RUN_DIR/plan.tfplan"                                       # a saved plan holds the input variables, the account number among them
   ```

5. **Expected inventory** from the state:

   ```
   terraform show -json > "$RUN_DIR/show.json"
   python3 -I ../expected.py "$RUN_DIR/show.json" --out "$RUN_DIR/expected.json"
   ```

   `unseeded_resources` in the output lists state entries the catalog does not name (attachments, rules: expected).
   Give EC2 and IAM a minute to settle before step 6.

6. **Compare**, in the stack's web container (it holds the collector's read-only secret). The container sees the
   repository at `/app/_dev-plugins/aws_core`, so `$RUN_DIR` (under `tools/seed/out/`) is visible there as it is. The
   catalog is found beside `compare.py` or at the mount path; `SEED_CATALOG` overrides it:

   ```
   scripts/dc exec -T \
     -e SEED_EXPECTED=/app/_dev-plugins/aws_core/tools/seed/out/$RUN_ID/expected.json \
     -e SEED_OUT=/app/_dev-plugins/aws_core/tools/seed/out/$RUN_ID/verdict.json web \
     uv run python manage.py shell -c "exec(open('/app/_dev-plugins/aws_core/tools/seed/compare.py').read())"
   ```

   Per type the verdict is `pass`, `fail` (the first mismatch is named, e.g. `field-differs:handler @ <key>`) or
   `call-path-only` (the type was read but nothing of it was seeded). `uncovered_edges` names manifest edges whose target
   type was seeded but which the catalog gives no expected target for: those were not checked. The record holds keys,
   compared field names and outcomes only, with any 12-digit run replaced. Promotion to `collected-verified` is a person
   reading this record (spec: Verdict And Promotion), not this script.

7. **Destroy** the wave, always, even if step 6 failed. Destroy acts on this run's own state and nothing else:

   ```
   test "$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)" = "$TF_VAR_expected_account_id" && echo account-ok
   terraform plan -destroy -input=false -out="$RUN_DIR/destroy.tfplan"      # read it: only this run's resources
   terraform apply -input=false "$RUN_DIR/destroy.tfplan"
   rm -f "$RUN_DIR/destroy.tfplan"
   ```

8. **Leftover check** (report only; it deletes nothing). Anything still tagged for this run is the wave's failure and
   goes to a person:

   ```
   aws resourcegroupstaggingapi get-resources --region us-gov-west-1 --profile "$PROFILE" \
     --tag-filters Key=tap-seed-run,Values="$RUN_ID" --query 'ResourceTagMappingList[].ResourceARN' --output text
   aws iam list-roles --profile "$PROFILE" --query "Roles[?starts_with(RoleName,'seed-w1-$RUN_ID')].RoleName" --output text
   aws iam list-users --profile "$PROFILE" --query "Users[?starts_with(UserName,'seed-w1-$RUN_ID')].UserName" --output text
   aws iam list-groups --profile "$PROFILE" --query "Groups[?starts_with(GroupName,'seed-w1-$RUN_ID')].GroupName" --output text
   aws iam list-policies --scope Local --profile "$PROFILE" --query "Policies[?starts_with(PolicyName,'seed-w1-$RUN_ID')].PolicyName" --output text
   aws iam list-instance-profiles --profile "$PROFILE" --query "InstanceProfiles[?starts_with(InstanceProfileName,'seed-w1-$RUN_ID')].InstanceProfileName" --output text
   ```

   The tagging API does not list IAM, hence the IAM lines. Expected, not a failure: the KMS key stays visible, in state
   `PendingDeletion` for 7 days (`aws kms describe-key --key-id <arn> --query KeyMetadata.KeyState`); its alias is gone.
   Also look for anything tagged `tap-seed` without a run id: `--tag-filters Key=tap-seed`.

9. **Remove the local state and outputs** only after step 7 succeeded and step 8 came back empty (apart from the key):
   the state can hold secrets, so it does not stay on disk. Keep `verdict.json` if it is the evidence for a ledger
   decision: copy it, with account numbers already removed, to `tools/validate/runs/`.

   ```
   rm -rf "$RUN_DIR"
   ```

## Other modules

Each module is its own Terraform root with its own state, and its catalog entries name it in `module`. Run it with the
steps above, changing three things: the directory (`cd tools/seed/wave2-rds`), the run id prefix (`w2r...`; the module's
names start `seed-w2r-`) and the cost note you read in step 1. The expected inventory records the module as the wave,
and `compare.py` fails a catalog type of that module that the state does not contain, so a partial apply cannot pass.
A catalog edge whose target is a list (a subnet group's subnets) gives one expected edge per member: `expected.py` flattens a join's list result, which wave 1 never needed and the RDS instance does. A module's catalog types need not be only its own: the VPC, subnets and roles it creates are wave 1 types and are
compared too. A **costly** module has a time box in its cost note; destroy it when the box ends whether or not the check
finished. Wave 2 ran on 2026-11-02: RDS passed 20 of 20 types on its second cycle (the first found the Aurora
cluster-endpoint defect fixed in #175), and Network Firewall passed 5 of 6 (the sixth, the VPC endpoint association, is
refused to the collector's role; see `tools/validate/runs/wave2-nfw-2026-11-02.json`).

## Providers

The wave uses two Terraform providers, both from the `hashicorp` namespace at exact versions with their hashes in
`wave1/.terraform.lock.hcl`: `aws` (everything it creates) and `archive` (zips the Lambda function's source on the
operator's machine; it makes no AWS call). Both run locally as the operator when Terraform runs. The lock file was
checked by regenerating it with `terraform providers lock` for darwin and linux on amd64 and arm64 in a clean
directory: every committed hash is among the registry-derived ones. Repeat that check before running a wave from
a lock file you did not make.

## Safety rules (spec: Safety)

- **Destroy only what the run's own state created.** The state is the allowlist. Never delete by tag, by name pattern or
  by console. A resource left by an earlier interrupted run is that run's to clean up, by its own `tap-seed-run`
  marker and its own state; a later run never sweeps it up. If the state of an interrupted run is lost, report the
  leftovers to a person.
- **Verify the account and region before apply and before destroy** (steps 1 and 7). The account number is read from
  `TF_VAR_expected_account_id` at run time; this tool never writes it to a file of its own, and the plan files that
  would carry it are deleted right after they are applied.
- The account already holds networking this repository does not declare. Nothing here references, imports or modifies
  any existing resource; the wave creates its own VPC and addresses nothing else.
- Seeder names: every IAM role, user, group, policy and instance profile starts with `seed-`, the only names the seeder
  may create. Every other resource is named `seed-w1-<run id>-...` as well.
- Wave 1 declares no NAT gateway, load balancer, database, EKS, Redshift or search domain; the costly modules declare
  only what their cost note prices (a test checks it). A quota or `unsupported-in-partition` error is recorded and not
  retried around.
- Terraform state is local to the run, never committed, and removed after destroy (step 9).

## The awkward cases wave 1 includes

| Case | Where |
| --- | --- |
| Tag keys and values with spaces, colons, slashes, `=`, `+`, `@`, unicode letters and an empty value | IAM user (read by the IAM tag side-call), S3 bucket A (read by the tagging API) |
| A resource with no tag of its own beyond the two defaults | SQS queue, Lambda function, bucket B and most others |
| A type that cannot be tagged at all (`{}` expected) | IAM group, KMS alias |
| A public setting: a rule open to `0.0.0.0/0` on port 49152 with nothing attached | security group `...-open` |
| A bucket with the bucket-level public access block absent, and one with it explicitly off | bucket B (the service default, blocked) and bucket C (all four flags off); bucket A has all four on |
| A second region | not in wave 1 |

## Choices to know about

- `seeding.json` keys on the CloudFormation type; the manifest keys on the entity type, so the catalog carries both.
- Values compare by their string form (the API returns some integers as strings) and lists as sets; an empty string in
  the state counts as absent (the public address of a private instance). A `null` is never equal to a value.
- The catalog gives expected edge targets only where the state names them; the verdict lists the rest as
  `uncovered_edges` instead of passing them.
- The Lambda runtime is `python3.12` and the AMI is the newest Amazon-owned `al2023-ami-2023.*-kernel-*-x86_64` image;
  neither has been checked against GovCloud, so if `plan` or `apply` rejects them, change them in `wave1/` and note it.

## Service-linked roles

The first use of Redshift, ElastiCache, EKS (cluster and node group) and OpenSearch in an account creates the service's
linked role (the seeder may create them, not delete them). They are AWS-managed, free and are left in place after a run.
