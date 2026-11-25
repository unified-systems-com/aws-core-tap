# Changelog

## [0.9.3](https://github.com/unified-systems-com/aws-core-tap/compare/v0.9.2...v0.9.3) (2026-11-25)


### Bug Fixes

* ship the history event-time migration on the tap v0.5.0 floor ([fd83bc0](https://github.com/unified-systems-com/aws-core-tap/commit/fd83bc0c2ee77ba34be85019d1550fa598b80988))
* ship the history event-time migration on the tap v0.5.0 floor ([85fcc79](https://github.com/unified-systems-com/aws-core-tap/commit/85fcc7972914fc29fc47686a1127c675578719cf))

## [0.9.2](https://github.com/unified-systems-com/aws-core-tap/compare/v0.9.1...v0.9.2) (2026-11-25)


### Features

* **iam:** credential hygiene — access keys, SSH keys, signing certificates, service credentials, root user, password policy ([f508109](https://github.com/unified-systems-com/aws-core-tap/commit/f5081095a01b1c19c0dd0f93637c3c4958ccb86e))
* **models:** tag the credential types with tap.computing.credential ([b0a9384](https://github.com/unified-systems-com/aws-core-tap/commit/b0a9384ed48cd76e4d8d7d309bed3cda1c3c5800))
* **ssm:** patch and compliance state, baselines, defaults and patch groups, compliance_core projection ([01f6de2](https://github.com/unified-systems-com/aws-core-tap/commit/01f6de237ff495b9eaa883ba67d3e66c9b1a4c52))


### Bug Fixes

* **ssm:** a presigned InstallOverrideList keeps its location, not its signature ([a5b9ff9](https://github.com/unified-systems-com/aws-core-tap/commit/a5b9ff97798b67a1b25b1962ff6bcf8e19c45a93))
* **ssm:** a secret-named value in a compliance item's Details reaches no field ([60e7e94](https://github.com/unified-systems-com/aws-core-tap/commit/60e7e9409c94027b30ed067707c387a09ae3288e))
* **ssm:** an unscanned instance claims no scope whole; a run that wrote no instances resolves nothing ([fbca5ea](https://github.com/unified-systems-com/aws-core-tap/commit/fbca5eac0ad4c474fc0fec17d6bc557b9e70f024))


### Documentation

* **iam:** the managed policies already grant GenerateCredentialReport ([62ecf63](https://github.com/unified-systems-com/aws-core-tap/commit/62ecf6395a7ed4d315fdda0610ab620b0a7e1ce1))

## [0.9.1](https://github.com/unified-systems-com/aws-core-tap/compare/v0.9.0...v0.9.1) (2026-11-25)


### Bug Fixes

* **grift:** write the format "1" header from core's build_header ([94b67f6](https://github.com/unified-systems-com/aws-core-tap/commit/94b67f66204a29615490da3873f07c1678c10bbb))
* **grift:** write the format "1" header from core's build_header ([42cebb0](https://github.com/unified-systems-com/aws-core-tap/commit/42cebb0d4f45d41b583fb073170a4b7f72e61318))

## [0.9.0](https://github.com/unified-systems-com/aws-core-tap/compare/v0.8.7...v0.9.0) (2026-11-24)


### ⚠ BREAKING CHANGES

* **aws_core:** spine version 2 on tap 0.4.9: spine copies, no typed batch_id, GRIFT format 1
* **aws_core:** image host keyed on computing_core's tap.computing.host_type dimension, not the retired realm

### Features

* **aws_core:** image host keyed on computing_core's tap.computing.host_type dimension, not the retired realm ([6fc4f9d](https://github.com/unified-systems-com/aws-core-tap/commit/6fc4f9d15629c3a7cabaed0df1fdb0453e7c9405))
* **aws_core:** spine version 2 on tap 0.4.9: spine copies, no typed batch_id, GRIFT format 1 ([faebde2](https://github.com/unified-systems-com/aws-core-tap/commit/faebde20910466d777ab826b49bd743871284b5f))
* **edges:** USES_SECURITY_GROUP, EC2 instance or network interface to security group ([0ba5dcf](https://github.com/unified-systems-com/aws-core-tap/commit/0ba5dcf252891765ff74e5b0c1a42b34d343bf14))
* **edges:** USES_SECURITY_GROUP, EC2 instance or network interface to security group ([cccb37d](https://github.com/unified-systems-com/aws-core-tap/commit/cccb37d97c2b3df75b519a0cf0536a36d1c641cb))
* **lambda:** read each function's, alias's and version's resource policy (lambda:GetPolicy) ([b57567d](https://github.com/unified-systems-com/aws-core-tap/commit/b57567d8d207e6443699b221a64c943f713181a9))
* **lambda:** read each function's, alias's and version's resource policy (lambda:GetPolicy) ([608cfd7](https://github.com/unified-systems-com/aws-core-tap/commit/608cfd771937118938598c63f6e9de4596c671f5))
* **models:** an API Gateway stage reads its creation time under either service's spelling ([3a66f71](https://github.com/unified-systems-com/aws-core-tap/commit/3a66f71688637a515dd38e9dc39d86e95819d6f8))
* **models:** an API Gateway stage reads its creation time under either service's spelling ([a69ee7c](https://github.com/unified-systems-com/aws-core-tap/commit/a69ee7c8c2c032fab2a43d262362033aa24a677e))
* **models:** declare event time on the pending types through core's member paths and readers ([455eeba](https://github.com/unified-systems-com/aws-core-tap/commit/455eeba9935028d97bb2d59e342bca861c5a61ab))
* **models:** declare event time on the pending types through core's member paths and readers ([631b4b7](https://github.com/unified-systems-com/aws-core-tap/commit/631b4b79106d3b854c0a9912b44b2ceddc317da7))
* **models:** typed results for Network Access Analyzer and Reachability Analyzer runs ([2b58ca0](https://github.com/unified-systems-com/aws-core-tap/commit/2b58ca0a083bccc2ce57ae2ddcf01b9850b42a4e))
* **models:** typed results for Network Access Analyzer and Reachability Analyzer runs ([89008a5](https://github.com/unified-systems-com/aws-core-tap/commit/89008a5006672d3dd08d8532e6a35259305c2025))
* **network:** Network Access Analyzer findings and Reachability Analyzer paths as compound edges ([db6cecb](https://github.com/unified-systems-com/aws-core-tap/commit/db6cecbc5895cd8294520aec9d413370b17c7a3b))
* **network:** Network Access Analyzer findings and Reachability Analyzer paths as compound edges ([9d9ba92](https://github.com/unified-systems-com/aws-core-tap/commit/9d9ba92729f04bde35587f0a220d25bf733e69df))


### Bug Fixes

* **collector:** render only a typed field's datetime; name the ENI count as AWS does ([86eec48](https://github.com/unified-systems-com/aws-core-tap/commit/86eec48b5bb35184733f02dd4bc6467fe4acace1))
* **lambda:** a principal that names no account leaves the policy summary unread ([7414be0](https://github.com/unified-systems-com/aws-core-tap/commit/7414be0e404dbfb55e6f6abcece6ca8d2d95f577))
* **migrations:** 0062 depends on 0061_lambda_resource_policy, not 0060 ([f7ec3d9](https://github.com/unified-systems-com/aws-core-tap/commit/f7ec3d918573aa792b08c10012b75db219157bed))
* **migrations:** renumber the finding table's migration to 0062, after main's 0061 ([5e8485f](https://github.com/unified-systems-com/aws-core-tap/commit/5e8485f4281ee4ed87970719a6a436f9093594d8))

## [0.8.7](https://github.com/unified-systems-com/aws-core-tap/compare/v0.8.6...v0.8.7) (2026-11-23)


### Features

* **models:** declare core's event time on aws_core's models ([be42b8a](https://github.com/unified-systems-com/aws-core-tap/commit/be42b8aeceff5c0f9bfc769f3dc136faa4c716c2))
* **models:** declare core's event time on aws_core's models ([69dcb65](https://github.com/unified-systems-com/aws-core-tap/commit/69dcb65a8e3671934c26f7a1269a93e75bc19c8c))


### Bug Fixes

* **models:** leave types with an unreadable AWS time undeclared, not timeless ([f0146e2](https://github.com/unified-systems-com/aws-core-tap/commit/f0146e2b5e1fcb6647ec34ddf8db64a9c8d94cb9))
* **models:** read each type's event time from its own record, not a parent's ([68ee354](https://github.com/unified-systems-com/aws-core-tap/commit/68ee354134c3481fb262b2d329f0b8fb5ed4866a))

## [0.8.6](https://github.com/unified-systems-com/aws-core-tap/compare/v0.8.5...v0.8.6) (2026-11-22)


### Bug Fixes

* **collector:** a late UndescribedError keeps the items its reader already yielded ([#279](https://github.com/unified-systems-com/aws-core-tap/issues/279)) ([adc905b](https://github.com/unified-systems-com/aws-core-tap/commit/adc905b320d32708f8ec63fe98e49550dbcc800d))

## [0.8.5](https://github.com/unified-systems-com/aws-core-tap/compare/v0.8.4...v0.8.5) (2026-11-21)


### Bug Fixes

* **collector:** build every endpoint-probe client from one shared session ([#276](https://github.com/unified-systems-com/aws-core-tap/issues/276)) ([a483a69](https://github.com/unified-systems-com/aws-core-tap/commit/a483a69b5d3cad7ca5c544186c2d31a2e024c46d))

## [0.8.4](https://github.com/unified-systems-com/aws-core-tap/compare/v0.8.3...v0.8.4) (2026-11-21)


### Features

* **ecs:** a Docker Hub image reference makes its tag, stored canonical by computing_core 0.10.9 ([#268](https://github.com/unified-systems-com/aws-core-tap/issues/268)) ([92cd7e0](https://github.com/unified-systems-com/aws-core-tap/commit/92cd7e090f5d12f0e57ee213042807ed5b8d94cb))
* **ecs:** containers run their image hosts; tasks use their task definitions, which reference secrets ([#262](https://github.com/unified-systems-com/aws-core-tap/issues/262)) ([5f9b3b7](https://github.com/unified-systems-com/aws-core-tap/commit/5f9b3b7d455bb5a945870af413a124d04ab80d20))
* **findings:** keep what aws_core dropped: finding detail, closed findings, wider GuardDuty links, reviewed redactions ([#267](https://github.com/unified-systems-com/aws-core-tap/issues/267)) ([51a96cb](https://github.com/unified-systems-com/aws-core-tap/commit/51a96cb501ad76f8195df3ac7a7ee8326bc64529))
* **inspector:** Amazon Inspector v2 findings, reachability compound edge, optional compliance_core projection ([#270](https://github.com/unified-systems-com/aws-core-tap/issues/270)) ([21333f4](https://github.com/unified-systems-com/aws-core-tap/commit/21333f4305b42ba3368c0b31c20cdbe858799338))


### Bug Fixes

* **deps:** update aws sdk to v1.44.7 ([8c8355b](https://github.com/unified-systems-com/aws-core-tap/commit/8c8355b98f7ab0b779b5782d7ba8385d3c81fac3))
* **deps:** update aws sdk to v1.44.7 ([b2fdb6b](https://github.com/unified-systems-com/aws-core-tap/commit/b2fdb6b922a32be6f816d2f5940b5fe1093608f9))

## [0.8.3](https://github.com/unified-systems-com/aws-core-tap/compare/v0.8.2...v0.8.3) (2026-11-19)


### Features

* **history:** published-version types keep no grid history; adopt tap 0.4.0's dimension storage ([#244](https://github.com/unified-systems-com/aws-core-tap/issues/244)) ([2e50ecb](https://github.com/unified-systems-com/aws-core-tap/commit/2e50ecb68c3896061c0e6a22c5daf9c60defa2ba))
* **identity:** declare non-ARN identity, check it against CloudFormation, resolve ARNs onto native keys ([#254](https://github.com/unified-systems-com/aws-core-tap/issues/254)) ([da80942](https://github.com/unified-systems-com/aws-core-tap/commit/da80942f9372ba2b9171742fd9f9943c0bf084ca))


### Bug Fixes

* **identity:** read returned ARNs, drop Pinpoint Email duplicates, key the OpenSearch data source natively ([#251](https://github.com/unified-systems-com/aws-core-tap/issues/251)) ([#255](https://github.com/unified-systems-com/aws-core-tap/issues/255)) ([9cf60cf](https://github.com/unified-systems-com/aws-core-tap/commit/9cf60cf7e8fab4c2e20c1ee1a28ebfd39bf2993f))

## [0.8.2](https://github.com/unified-systems-com/aws-core-tap/compare/v0.8.1...v0.8.2) (2026-11-18)


### Features

* **findings:** a Security Hub finding concerns any ARN-keyed resource ([#245](https://github.com/unified-systems-com/aws-core-tap/issues/245)) ([2c04347](https://github.com/unified-systems-com/aws-core-tap/commit/2c04347ee5bef0b12d322e0afcef2be25bbd8d0a))


### Bug Fixes

* **collector:** read agent profile tags by side call; pin the AWS SDK ([#238](https://github.com/unified-systems-com/aws-core-tap/issues/238)) ([ffcde87](https://github.com/unified-systems-com/aws-core-tap/commit/ffcde8750a368558cbb28f3324c727153aaf53dc))
* **collector:** read agent profile tags with GetAgentProfile ([#241](https://github.com/unified-systems-com/aws-core-tap/issues/241)) ([841027f](https://github.com/unified-systems-com/aws-core-tap/commit/841027fe3aea53782c92fe28dfd4a90c6f923943))
* **deps:** depend on computing_core, which declares the dimension aws_core stamps ([#239](https://github.com/unified-systems-com/aws-core-tap/issues/239)) ([8263b9e](https://github.com/unified-systems-com/aws-core-tap/commit/8263b9e3aa5ee3f604b825141a24b509051e34f2))
* **migrations:** ship the migrations the squash replaces, so a v0.8.0 database can upgrade ([#236](https://github.com/unified-systems-com/aws-core-tap/issues/236)) ([6378be2](https://github.com/unified-systems-com/aws-core-tap/commit/6378be2920635dd3ea855a683863e09f749fb863))

## [0.8.1](https://github.com/unified-systems-com/aws-core-tap/compare/v0.8.0...v0.8.1) (2026-11-16)


### Features

* API Gateway REST and HTTP/WebSocket types (eight types, twelve rows) ([#134](https://github.com/unified-systems-com/aws-core-tap/issues/134)) ([539f772](https://github.com/unified-systems-com/aws-core-tap/commit/539f772bda6445d848bec539e297d1e468cbd388))
* **aws_core:** ~400 more types, engine forms for the hard ones, fast bulk migrations ([#155](https://github.com/unified-systems-com/aws-core-tap/issues/155)) ([643e63f](https://github.com/unified-systems-com/aws-core-tap/commit/643e63f19f7b75b0720cedd085281f1d9c8dc267))
* **aws_core:** 14 parent-scoped types (APS, EKS, IoT, QBusiness, Step Functions, Notifications) ([#151](https://github.com/unified-systems-com/aws-core-tap/issues/151)) ([29cdba5](https://github.com/unified-systems-com/aws-core-tap/commit/29cdba53f4270a910ad58982a582d62e19e75ab8))
* **aws_core:** 16 QuickSight types, via $account_id in source params ([#154](https://github.com/unified-systems-com/aws-core-tap/issues/154)) ([ecd8332](https://github.com/unified-systems-com/aws-core-tap/commit/ecd8332d39216b22828d62d06ca616dc4b7a150f))
* **aws_core:** 43 parent-scoped types via source.per (Connect, Greengrass, Transfer, MSK, others) ([#150](https://github.com/unified-systems-com/aws-core-tap/issues/150)) ([eb83684](https://github.com/unified-systems-com/aws-core-tap/commit/eb83684b68871ee8f8019362c6c698073e8a4252))
* **aws_core:** apply the 11-01 rulings — 26 exclusions, numbered-version types ([#156](https://github.com/unified-systems-com/aws-core-tap/issues/156)) ([9d35a40](https://github.com/unified-systems-com/aws-core-tap/commit/9d35a4002f06bd8887604a2246d9096548a72c1f))
* **aws_core:** declare a Dimension node for every dimension key written ([#228](https://github.com/unified-systems-com/aws-core-tap/issues/228)) ([4723bed](https://github.com/unified-systems-com/aws-core-tap/commit/4723bedf4af1a2f8b4013cf1ba959f0d3c04ca7a))
* **aws_core:** detail enrichment, generated collector IAM policy, drop replaced migrations ([#208](https://github.com/unified-systems-com/aws-core-tap/issues/208)) ([c7afb5f](https://github.com/unified-systems-com/aws-core-tap/commit/c7afb5f33e8c13affde168d046e156e0ba65e99f))
* **aws_core:** ECS stopped tasks recorded, and a retirement path for tasks and containers ([#216](https://github.com/unified-systems-com/aws-core-tap/issues/216)) ([40c001a](https://github.com/unified-systems-com/aws-core-tap/commit/40c001ac6980973f255e5a45868dc1a84a7bbe73))
* **aws_core:** every model names its ARN's resource type; ARN formats vendored ([06c1d8a](https://github.com/unified-systems-com/aws-core-tap/commit/06c1d8aa8b62890c5d850f10a1bdbcb73e15c6bb))
* **aws_core:** every model names its ARN's resource type; ARN formats vendored ([472d5af](https://github.com/unified-systems-com/aws-core-tap/commit/472d5af6d8124f83a146a45ab004f7f43937d4d7))
* **aws_core:** gap sweep — unmapped fields, new edges, ROUTES_TRAFFIC, not_taggable, unobserved is null ([#209](https://github.com/unified-systems-com/aws-core-tap/issues/209)) ([3d261d3](https://github.com/unified-systems-com/aws-core-tap/commit/3d261d333b542ec37f2236dda3c50b54092578ed))
* **aws_core:** listeners and rules as nodes; Classic targets with health ([#226](https://github.com/unified-systems-com/aws-core-tap/issues/226)) ([5fd4d49](https://github.com/unified-systems-com/aws-core-tap/commit/5fd4d4977817d99491ff1eb1f228c0b5c0e13e89))
* **aws_core:** load balancers route through target groups, one edge per rule ([#221](https://github.com/unified-systems-com/aws-core-tap/issues/221)) ([a1c970e](https://github.com/unified-systems-com/aws-core-tap/commit/a1c970ec01787dafb5d218e10507cd92f5377b39))
* **aws_core:** rename dimension keys (tap.computing.cloud, aws.account, aws.region); aws.account is the owner ([#229](https://github.com/unified-systems-com/aws-core-tap/issues/229)) ([857f6c6](https://github.com/unified-systems-com/aws-core-tap/commit/857f6c6300b789fa37d05b5fb5dc099ffbacaef9))
* **aws_core:** Route 53 record sets as nodes between a zone and what they resolve to ([#223](https://github.com/unified-systems-com/aws-core-tap/issues/223)) ([33668f4](https://github.com/unified-systems-com/aws-core-tap/commit/33668f47338c260fee71df87e5d632523dd1d565))
* CloudWatch, Logs and Security Hub detective-control types (fourteen) ([#133](https://github.com/unified-systems-com/aws-core-tap/issues/133)) ([bbb8a3c](https://github.com/unified-systems-com/aws-core-tap/commit/bbb8a3cb64d9ff5b17a766902cc20cbb28ec2f39))
* collect Direct Connect, transit gateways, endpoint services, DNS Firewall rule groups, Private CAs, CodeBuild and CodePipeline ([#127](https://github.com/unified-systems-com/aws-core-tap/issues/127)) ([7065173](https://github.com/unified-systems-com/aws-core-tap/commit/706517300c98f8466a39b4a7184cfd04510eea97))
* collect EKS, RDS, ElastiCache, Elasticsearch, ECR, SageMaker, Network Firewall and SSM parameters ([#126](https://github.com/unified-systems-com/aws-core-tap/issues/126)) ([1448123](https://github.com/unified-systems-com/aws-core-tap/commit/1448123796034fefaab9be32fc8310a23474f4b2))
* **collector:** a per-entry list of what a partition does not offer ([#199](https://github.com/unified-systems-com/aws-core-tap/issues/199)) ([06dcf95](https://github.com/unified-systems-com/aws-core-tap/commit/06dcf953229d5ec50060a4e3c9002a7e52a61091))
* **collector:** a selected run emits no edge to an unselected type ([#198](https://github.com/unified-systems-com/aws-core-tap/issues/198)) ([5fbde88](https://github.com/unified-systems-com/aws-core-tap/commit/5fbde88c312342efc268c603d9ea2be83ce14cf0))
* **collector:** account membership is the aws_account dimension, not an edge to every resource ([968e7a9](https://github.com/unified-systems-com/aws-core-tap/commit/968e7a9e0a803d950369251b4537470b85e809b1))
* **collector:** account membership is the aws_account dimension, not an edge to every resource [via aws-build] ([b13dc05](https://github.com/unified-systems-com/aws-core-tap/commit/b13dc050119b386420455cfed74d997a035e3f98))
* **collector:** collection selection, types and a single account ([#194](https://github.com/unified-systems-com/aws-core-tap/issues/194)) ([0bacbf8](https://github.com/unified-systems-com/aws-core-tap/commit/0bacbf85423b8d393e33f59f5dc59c9825115638))
* **collector:** progress lines in the process log ([#201](https://github.com/unified-systems-com/aws-core-tap/issues/201)) ([6e9d594](https://github.com/unified-systems-com/aws-core-tap/commit/6e9d59472dad79272e68370eb7ca9db56ea8fc73))
* **collector:** source.per runs a list call once per parent ([#149](https://github.com/unified-systems-com/aws-core-tap/issues/149)) ([14acf63](https://github.com/unified-systems-com/aws-core-tap/commit/14acf638b5896ecddb8f3cb57822a1828af6f2a5))
* **collector:** store everything AWS returns; remove only secret material ([#207](https://github.com/unified-systems-com/aws-core-tap/issues/207)) ([46a333f](https://github.com/unified-systems-com/aws-core-tap/commit/46a333f4797b7ac71844be66b36233f9011773b9))
* **coverage:** record the 19 collection-gap actions as known misses, not policy ([#173](https://github.com/unified-systems-com/aws-core-tap/issues/173)) ([0cbb414](https://github.com/unified-systems-com/aws-core-tap/commit/0cbb4147693a7562ce99642689c7afc98195f0ae))
* **coverage:** the read actions the collector's role is denied, and a policy to close them ([#171](https://github.com/unified-systems-com/aws-core-tap/issues/171)) ([d81b1e1](https://github.com/unified-systems-com/aws-core-tap/commit/d81b1e155a1bb85d7079ecd11e1542534ae60e37))
* **coverage:** weighted service hit list with falsifier, reconcile and Config columns ([#166](https://github.com/unified-systems-com/aws-core-tap/issues/166)) ([588b19b](https://github.com/unified-systems-com/aws-core-tap/commit/588b19b78c207bc9b88c65cec0a6814c9f562a08))
* **crosscheck:** CloudFormation specification verifier ([#168](https://github.com/unified-systems-com/aws-core-tap/issues/168)) ([c7556a5](https://github.com/unified-systems-com/aws-core-tap/commit/c7556a56f81e20b1c0f63928b1644099e5931f6d))
* **crosscheck:** static comparison of aws_core with Cartography's AWS model ([#157](https://github.com/unified-systems-com/aws-core-tap/issues/157)) ([6123285](https://github.com/unified-systems-com/aws-core-tap/commit/6123285457bfdf9db6a36e6087008c36b203896b))
* **crosscheck:** Terraform AWS provider as a second reference ([#160](https://github.com/unified-systems-com/aws-core-tap/issues/160)) ([3688acf](https://github.com/unified-systems-com/aws-core-tap/commit/3688acf50bc48119a1db105bd16b2c864923424a))
* **ec2:** collect Elastic IPs, internet gateways, NAT gateways, network ACLs, route tables, EBS volumes, VPC endpoints ([#124](https://github.com/unified-systems-com/aws-core-tap/issues/124)) ([5abfe00](https://github.com/unified-systems-com/aws-core-tap/commit/5abfe00c8e48cc5b30bbe03b94aa85c7050cd0b3))
* EFS, ELB listeners, AWS Backup and Cognito pool types (fourteen) ([#132](https://github.com/unified-systems-com/aws-core-tap/issues/132)) ([0cee25b](https://github.com/unified-systems-com/aws-core-tap/commit/0cee25bef61b7ecd470bee252873336a582ea776))
* **elb:** collect Application, Network, Gateway and Classic load balancers and target groups ([#125](https://github.com/unified-systems-com/aws-core-tap/issues/125)) ([4ad2db9](https://github.com/unified-systems-com/aws-core-tap/commit/4ad2db95bf93cd7cea2ded02a0075e2a835883c9))
* first generated batch — 7 types (APS, Batch) ([#136](https://github.com/unified-systems-com/aws-core-tap/issues/136)) ([f053690](https://github.com/unified-systems-com/aws-core-tap/commit/f0536905d4000d1169b3e43724a3d679e6de7ba0))
* generated batch 2 — 24 SageMaker types ([#137](https://github.com/unified-systems-com/aws-core-tap/issues/137)) ([c4d5126](https://github.com/unified-systems-com/aws-core-tap/commit/c4d51264f38ce1f66c4a969556d37931d9a281a7))
* generated batch 3 — 36 types (ApiGatewayV2 to Logs) ([#138](https://github.com/unified-systems-com/aws-core-tap/issues/138)) ([95e0f2a](https://github.com/unified-systems-com/aws-core-tap/commit/95e0f2a9f4ca9a60c902101c9fa25d1aebe231fe))
* generated batch 4 — 35 types (M2 to Translate) ([#139](https://github.com/unified-systems-com/aws-core-tap/issues/139)) ([b1e1eb9](https://github.com/unified-systems-com/aws-core-tap/commit/b1e1eb9944b315f0a9326928af902c9fdc7916b1))
* generated batch 5 — 14 types held back for sensitive members ([#141](https://github.com/unified-systems-com/aws-core-tap/issues/141)) ([ae118eb](https://github.com/unified-systems-com/aws-core-tap/commit/ae118eb8e9ae1665d1f19664275659bda3af6502))
* generated batch 6 — 35 types (AmazonMQ to EC2) ([#142](https://github.com/unified-systems-com/aws-core-tap/issues/142)) ([c503869](https://github.com/unified-systems-com/aws-core-tap/commit/c5038697549f61cdb930c82ea90ab8e37e2d8e05))
* generated batch 7 — 42 types (ECS to IoT) ([#147](https://github.com/unified-systems-com/aws-core-tap/issues/147)) ([725c7fd](https://github.com/unified-systems-com/aws-core-tap/commit/725c7fd6de5ba984d5cf62aa187389b1da176693))
* generated batches 8-10 — 95 types (IoTSiteWise to VerifiedPermissions, plus side-call tag reads) ([#148](https://github.com/unified-systems-com/aws-core-tap/issues/148)) ([fbfcbd7](https://github.com/unified-systems-com/aws-core-tap/commit/fbfcbd79e442909eaf9bce88985392a1b75a692f))
* GuardDuty, WAFv2 and S3 access point types (ten) ([#131](https://github.com/unified-systems-com/aws-core-tap/issues/131)) ([08aee40](https://github.com/unified-systems-com/aws-core-tap/commit/08aee4050ae7a445a9e9c55380824384c08f9844))
* **iam:** collect groups, instance profiles, SAML providers, server certificates, virtual MFA devices ([#122](https://github.com/unified-systems-com/aws-core-tap/issues/122)) ([8df33ae](https://github.com/unified-systems-com/aws-core-tap/commit/8df33ae09ffd345d621c4f92b933ea3e6b961e87))
* **iam:** five IAM identity models, modeled ahead of their collectors [via aws-build] ([#116](https://github.com/unified-systems-com/aws-core-tap/issues/116)) ([4367f94](https://github.com/unified-systems-com/aws-core-tap/commit/4367f94e0eddb477061ec088eeb236b6c2825148))
* **ledger:** commit the generated AWS coverage ledger; a corrupt bundle is a refusal, not a traceback ([#114](https://github.com/unified-systems-com/aws-core-tap/issues/114)) ([4b8de70](https://github.com/unified-systems-com/aws-core-tap/commit/4b8de7057ad7f8668cafeb0892034d76c9d0e181))
* **ledger:** exclude 119 non-resource types from a mechanical pre-screen, read by hand [via aws-build] ([#118](https://github.com/unified-systems-com/aws-core-tap/issues/118)) ([8d1f9de](https://github.com/unified-systems-com/aws-core-tap/commit/8d1f9de24c9596ecc3166743375e38145444ad02))
* **ledger:** generate the AWS coverage ledger from CloudFormation schemas and botocore [via aws-build] ([#113](https://github.com/unified-systems-com/aws-core-tap/issues/113)) ([5b6fe55](https://github.com/unified-systems-com/aws-core-tap/commit/5b6fe550339cd7fc7abdbe36e2769dad3dd0da13))
* **ledger:** tag_findings in decisions; classify the IAM rows that are not nodes ([#115](https://github.com/unified-systems-com/aws-core-tap/issues/115)) ([4688901](https://github.com/unified-systems-com/aws-core-tap/commit/4688901bc51eb7985929470148ee680fcf8796eb))
* **ledger:** tranche 1, classify KMS replica keys, Secrets Manager and CloudTrail policy rows ([#117](https://github.com/unified-systems-com/aws-core-tap/issues/117)) ([54cb4d7](https://github.com/unified-systems-com/aws-core-tap/commit/54cb4d73a061e2ac169c3cab431a94924701ffb8))
* **models:** tags is nullable and starts null (not read) ([#121](https://github.com/unified-systems-com/aws-core-tap/issues/121)) ([f1cd6e1](https://github.com/unified-systems-com/aws-core-tap/commit/f1cd6e1b7f14e9064b0f8f5faf1886aff0cb4039))
* RDS family — ten types (clusters, snapshots, groups, proxies, subscriptions) ([#135](https://github.com/unified-systems-com/aws-core-tap/issues/135)) ([359878b](https://github.com/unified-systems-com/aws-core-tap/commit/359878b28c54131e2a587191fd88750a7ce0526d))
* **rds:** endpoint and port fields on rds_instance and rds_db_cluster ([#206](https://github.com/unified-systems-com/aws-core-tap/issues/206)) ([676038d](https://github.com/unified-systems-com/aws-core-tap/commit/676038db36049633759ce61812ad3b3f60a554c7))
* **seed:** wave 1 Terraform seeds, seed catalog and comparison harness ([#169](https://github.com/unified-systems-com/aws-core-tap/issues/169)) ([e5536ed](https://github.com/unified-systems-com/aws-core-tap/commit/e5536ed680ce2506d4be5268948807fffbb4fb3c))
* **seed:** wave 1b, 21 types, 27 of 27 compared pass ([#179](https://github.com/unified-systems-com/aws-core-tap/issues/179)) ([9768084](https://github.com/unified-systems-com/aws-core-tap/commit/976808404c3d2516fb0b51d674ca6f4be92bc4f5))
* **seed:** wave 1c, the IAM SAML provider passes ([#181](https://github.com/unified-systems-com/aws-core-tap/issues/181)) ([bd532f0](https://github.com/unified-systems-com/aws-core-tap/commit/bd532f0f771aa1ac159e801815a7023167ae4288))
* **seed:** wave 2 seeds and records, RDS 20 of 20 and Network Firewall 5 of 6 ([#177](https://github.com/unified-systems-com/aws-core-tap/issues/177)) ([199e10f](https://github.com/unified-systems-com/aws-core-tap/commit/199e10fb27b020159aedf44038eff916b3859713))
* **seed:** wave 3a, Redshift, ElastiCache, EKS and OpenSearch, 26 types pass ([#180](https://github.com/unified-systems-com/aws-core-tap/issues/180)) ([2be38c6](https://github.com/unified-systems-com/aws-core-tap/commit/2be38c6d7867ae75a88815928c6221b165d981fc))
* **seed:** wave 3b application and developer services, 21 types pass ([#189](https://github.com/unified-systems-com/aws-core-tap/issues/189)) ([1d03be2](https://github.com/unified-systems-com/aws-core-tap/commit/1d03be281e080f1064446ea1bbea4e4abf512d0c))
* **seed:** wave 3b batch 1, Connect, Transfer and small free definitions, 29 types pass ([#193](https://github.com/unified-systems-com/aws-core-tap/issues/193)) ([a898f96](https://github.com/unified-systems-com/aws-core-tap/commit/a898f96f438678898209ec23291eddb7eeceaeb9))
* **seed:** wave 3b batch 2, more small definitions and account/region keys, 19 types pass ([#195](https://github.com/unified-systems-com/aws-core-tap/issues/195)) ([ea10e6f](https://github.com/unified-systems-com/aws-core-tap/commit/ea10e6f49e7663a49d70f772d003b0cd310006f8))
* **seed:** wave 3b batch 3, compute, RUM, Lex, Scheduler and Bedrock versions, 20 types pass ([#197](https://github.com/unified-systems-com/aws-core-tap/issues/197)) ([5205496](https://github.com/unified-systems-com/aws-core-tap/commit/52054967391ae62c4e18e4b2ef96ef0c1d982cde))
* **seed:** wave 3b Bedrock, 5 types pass ([#185](https://github.com/unified-systems-com/aws-core-tap/issues/185)) ([ee27570](https://github.com/unified-systems-com/aws-core-tap/commit/ee275709293e946c7522edb4f0eddea16d84a513))
* **seed:** wave 3b compute and network, 20 types pass ([#184](https://github.com/unified-systems-com/aws-core-tap/issues/184)) ([400c2b4](https://github.com/unified-systems-com/aws-core-tap/commit/400c2b4dd59c05bf553ac2cbae664824259c8922))
* **seed:** wave 3b data and application services, 41 types pass ([#188](https://github.com/unified-systems-com/aws-core-tap/issues/188)) ([c14fd95](https://github.com/unified-systems-com/aws-core-tap/commit/c14fd9528aae21e2719eb2e454b72fcc955032da))
* **seed:** wave 3b DNS and streaming, 20 types pass ([#187](https://github.com/unified-systems-com/aws-core-tap/issues/187)) ([50bb6ff](https://github.com/unified-systems-com/aws-core-tap/commit/50bb6ff3a8c8862acef924c8868b6f4135b2b658))
* **seed:** wave 3b EC2 and VPC extras, 19 types pass ([#191](https://github.com/unified-systems-com/aws-core-tap/issues/191)) ([6629cdb](https://github.com/unified-systems-com/aws-core-tap/commit/6629cdba612cac78bfabc2e931c1c7e703ba6665))
* **seed:** wave 3b edge services, 27 types pass ([#183](https://github.com/unified-systems-com/aws-core-tap/issues/183)) ([6a9f981](https://github.com/unified-systems-com/aws-core-tap/commit/6a9f981e3b34b01f13fe7099e18f34d09b771980))
* **seed:** wave 3b operations, 22 types pass ([#182](https://github.com/unified-systems-com/aws-core-tap/issues/182)) ([cec7795](https://github.com/unified-systems-com/aws-core-tap/commit/cec77956bccd7bf1c20622b2d47a4dff60c46603))
* **seed:** wave 3b SageMaker definitions, 9 types pass ([#192](https://github.com/unified-systems-com/aws-core-tap/issues/192)) ([41f8f76](https://github.com/unified-systems-com/aws-core-tap/commit/41f8f769da5ef0a10504240885efdea325becdd6))
* **seed:** wave 3b service definitions, 15 types pass ([#190](https://github.com/unified-systems-com/aws-core-tap/issues/190)) ([50d32b8](https://github.com/unified-systems-com/aws-core-tap/commit/50d32b85b01162bd2ed2c90f1518acfc0e186cc8))
* SNS, EventBridge and Lambda security types (ten) ([#130](https://github.com/unified-systems-com/aws-core-tap/issues/130)) ([e6a14fc](https://github.com/unified-systems-com/aws-core-tap/commit/e6a14fc62cf48b41e5428b6e5b06e2353517845b))
* tranche 1 (A) - KMS aliases, CloudTrail Lake, Config organization types, five classifications ([#128](https://github.com/unified-systems-com/aws-core-tap/issues/128)) ([cc9c917](https://github.com/unified-systems-com/aws-core-tap/commit/cc9c917dae60407d34de385e83a2a918665a8f23))
* tranche 1 (B) - Identity Center users/applications/assignments, Access Analyzer archive rules, Config connectors ([#129](https://github.com/unified-systems-com/aws-core-tap/issues/129)) ([11bd987](https://github.com/unified-systems-com/aws-core-tap/commit/11bd987346e01aaf42d6e99eed206fe83f9b54d1))
* **validate:** wave 0 live smoke over every manifest-driven type, with its first run record ([#161](https://github.com/unified-systems-com/aws-core-tap/issues/161)) ([c80195f](https://github.com/unified-systems-com/aws-core-tap/commit/c80195f8bb2ff36caed22f0101c79fe5545644d0))


### Bug Fixes

* **aws_core:** --refresh-arns rebuilds the ARN formats alone ([43b0f5c](https://github.com/unified-systems-com/aws-core-tap/commit/43b0f5c078422b60b41fd430acc79cdd3efb58bc))
* **aws_core:** an ARN refresh missing a named type refuses and writes nothing ([237169f](https://github.com/unified-systems-com/aws-core-tap/commit/237169f9c25a3f6f2c5393f35a17a711edd48f24))
* **aws_core:** an ARN refresh refuses a type with no usable format and replaces the file whole ([1082a78](https://github.com/unified-systems-com/aws-core-tap/commit/1082a788eeae72bc4bade89d5425071d9b35c9e8))
* **aws_core:** detail enrichment stores raw datetimes; one enriched resource rejects the whole batch ([#214](https://github.com/unified-systems-com/aws-core-tap/issues/214)) ([a2f0263](https://github.com/unified-systems-com/aws-core-tap/commit/a2f02636932aefbcd34c54db4d9a85d20607def2))
* **aws_core:** list only custom Aurora cluster endpoints ([#175](https://github.com/unified-systems-com/aws-core-tap/issues/175)) ([6a3a4b8](https://github.com/unified-systems-com/aws-core-tap/commit/6a3a4b8e0db53e7e3b322eced376389768157ef9))
* **aws_core:** make configuration JSON-safe once, at the node envelope ([#217](https://github.com/unified-systems-com/aws-core-tap/issues/217)) ([af245d9](https://github.com/unified-systems-com/aws-core-tap/commit/af245d93cadd85d14fb8e37bba3f14c77dc0c583))
* **aws_core:** name not-configured, unsupported and throttled outcomes; fix request bugs and client timeouts ([#163](https://github.com/unified-systems-com/aws-core-tap/issues/163)) ([095a7dc](https://github.com/unified-systems-com/aws-core-tap/commit/095a7dc2391ffc5eafd13192aaee2fa6de73caa9))
* **aws_core:** natural keys unique across partition, account and region ([#224](https://github.com/unified-systems-com/aws-core-tap/issues/224)) ([#225](https://github.com/unified-systems-com/aws-core-tap/issues/225)) ([37c0964](https://github.com/unified-systems-com/aws-core-tap/commit/37c09643484b1de01e5dbad3c63b05f0031e55ae))
* **aws_core:** provisioned product has no reference type; account names organizations:account ([e7b7896](https://github.com/unified-systems-com/aws-core-tap/commit/e7b7896f827096570bbdc866695ea3a8e640e7f3))
* **aws_core:** read a Storage Lens configuration's tags with its own call ([#178](https://github.com/unified-systems-com/aws-core-tap/issues/178)) ([220264c](https://github.com/unified-systems-com/aws-core-tap/commit/220264c742ed1d41eb246a1442589dd371a4ba4b))
* **aws_core:** S3 Outposts and Object Lambda resource types; DMS wildcard formats quarantined ([056ef41](https://github.com/unified-systems-com/aws-core-tap/commit/056ef412b47fb8a263831bb0ab8179bfda318328))
* **aws_core:** the refresh checks each ARN format as a whole template ([00b9fa5](https://github.com/unified-systems-com/aws-core-tap/commit/00b9fa5911f7378e6705985e01183cfe6b33cf8a))
* **collector:** ecs task sets are read from the ARNs DescribeServices returns ([#196](https://github.com/unified-systems-com/aws-core-tap/issues/196)) ([2053e55](https://github.com/unified-systems-com/aws-core-tap/commit/2053e55596b4f80716df44a645d735897738fd65))
* **collector:** omit tags when a tag read did not answer ([#120](https://github.com/unified-systems-com/aws-core-tap/issues/120)) ([08b1bd2](https://github.com/unified-systems-com/aws-core-tap/commit/08b1bd2b8db22d11ce323b2de9c3a5ce4610f967))
* **coverage:** the role-gap list had eight denied actions missing ([#176](https://github.com/unified-systems-com/aws-core-tap/issues/176)) ([4232a94](https://github.com/unified-systems-com/aws-core-tap/commit/4232a94e0f139c852e6ef8eec66053b921172cc3))
* **falsifiers:** ask the IAM endpoint of the ARN's own partition ([#164](https://github.com/unified-systems-com/aws-core-tap/issues/164)) ([c405b8a](https://github.com/unified-systems-com/aws-core-tap/commit/c405b8add3cce82f82664b0708716fc30aa51964))
* **falsifiers:** recognise the not-found codes the live probes saw ([#170](https://github.com/unified-systems-com/aws-core-tap/issues/170)) ([fa51249](https://github.com/unified-systems-com/aws-core-tap/commit/fa51249deb6dca737d541cddc2e04623f8bdc023))
* **ledger:** a type a custom reader emits is collected, not modeled ([#123](https://github.com/unified-systems-com/aws-core-tap/issues/123)) ([8dd1a2e](https://github.com/unified-systems-com/aws-core-tap/commit/8dd1a2eec55ca5009136a5fcfb82594fe4f4d6bb))
* **manifest:** do not list the tables of the AWS-managed keyspaces ([#203](https://github.com/unified-systems-com/aws-core-tap/issues/203)) ([563043d](https://github.com/unified-systems-com/aws-core-tap/commit/563043dd847680213a31591283d4875245e401bc))
* **manifest:** plugin_version is the bare number, 0.8.0, not the tag v0.8.0 ([#233](https://github.com/unified-systems-com/aws-core-tap/issues/233)) ([564def5](https://github.com/unified-systems-com/aws-core-tap/commit/564def5e1b3cc92adf09797216b977316b4c6d95))
* **outcomes:** name transcribe Call Analytics as unsupported in GovCloud ([#204](https://github.com/unified-systems-com/aws-core-tap/issues/204)) ([ee45ed2](https://github.com/unified-systems-com/aws-core-tap/commit/ee45ed2dc643659cc33f2d6c9b5f4edfe76ed87d))
* **panel:** drop an f-string with no placeholders ([f251f06](https://github.com/unified-systems-com/aws-core-tap/commit/f251f06bf3adaa04be1d6fce6b6b8fd8bba23caf))
* **validate:** wave 0 labels non-ok entries with the collector's own outcomes; re-run record ([#174](https://github.com/unified-systems-com/aws-core-tap/issues/174)) ([8d7fae6](https://github.com/unified-systems-com/aws-core-tap/commit/8d7fae63b74fcdbc6dda6283f712310d0e079860))


### Documentation

* **aws_core:** req-aws-collector-tags-17 names the not_readable outcome ([#210](https://github.com/unified-systems-com/aws-core-tap/issues/210)) ([34267db](https://github.com/unified-systems-com/aws-core-tap/commit/34267db1ae760adb23483a9811881f22bd30a991))
* **spec:** a layered, verifiable record of what is available in a region ([#162](https://github.com/unified-systems-com/aws-core-tap/issues/162)) ([616b03b](https://github.com/unified-systems-com/aws-core-tap/commit/616b03b8b47d029ff7f0ba64ba34909f9fd99b70))
* **spec:** add a not-enumerable ledger state so missing list operations are not read as not-a-node ([680ef2c](https://github.com/unified-systems-com/aws-core-tap/commit/680ef2cd4b4276a84cfaea7de6143a815dd515cc))
* **spec:** collection oracle — an independent, standalone check of what the grid holds (Proposed) ([#140](https://github.com/unified-systems-com/aws-core-tap/issues/140)) ([000ae42](https://github.com/unified-systems-com/aws-core-tap/commit/000ae42c9eef8fb7d4ca4d2d290c5af53571e803))
* **spec:** generalise the crosscheck spec to any reference ([#159](https://github.com/unified-systems-com/aws-core-tap/issues/159)) ([d0691f4](https://github.com/unified-systems-com/aws-core-tap/commit/d0691f4333c64eb30815e711d855aa792ad3bd59))
* **spec:** live validation of the collector in waves ([#158](https://github.com/unified-systems-com/aws-core-tap/issues/158)) ([ac435a8](https://github.com/unified-systems-com/aws-core-tap/commit/ac435a8c101215baa5f3b164bfaae36120a9b2af))
* **spec:** propose the AWS coverage ledger (denominator, row states, tag evidence, tranches) ([27e569a](https://github.com/unified-systems-com/aws-core-tap/commit/27e569a5dee5f0129f5f24842951340b55f4dfab))
* **spec:** propose the AWS coverage ledger [via aws-build] ([76c6b79](https://github.com/unified-systems-com/aws-core-tap/commit/76c6b79ec73d17aa2b9e5066744b509f7caddc55))
* **spec:** require a positive source for untaggable, split tag evidence from treatment ([026f9b7](https://github.com/unified-systems-com/aws-core-tap/commit/026f9b7f16a635f2772b1f44b5d3353217c63698))
