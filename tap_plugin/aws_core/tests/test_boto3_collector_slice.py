"""End-to-end vertical-slice proof: canned AWS payload -> real grid.

Drives the real Boto3Collector.run() pipeline (credentials -> manifest ->
source -> projection -> two-phase edges -> one GRIFT batch -> submit_grift)
with the AWS boundary stubbed by canned ListFunctions + ListRoles
responses, and asserts the typed nodes and the non-dangling ASSUMES_ROLE
edge actually landed on the grid, found by natural key.

This is the make-it-work proof for the aws_op path; fan-out (S3, Route 53
custom_fn) and the hydrate seam are the next increment.
"""

from __future__ import annotations

import json
import uuid

import pytest
from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred
from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.tests.grid_keys import edge_between, node_id

from tap_cares.collectors.config import CollectorConfig
from tap_cares.secrets.models import Secret, SecretRef

_ACCOUNT = "111122223333"
_FN_ARN = f"arn:aws:lambda:us-east-1:{_ACCOUNT}:function:sam-handler"
_ROLE_ARN = f"arn:aws:iam::{_ACCOUNT}:role/sam-exec"
_DIST_ARN = f"arn:aws:cloudfront::{_ACCOUNT}:distribution/E1ABCDEF"
_LOG_GROUP = "/aws/lambda/sam-handler"  # == the Lambda's LoggingConfig.LogGroup
# The log group's natural key: its ARN without the ``:*`` suffix (req-aws-collector-identity-2).
_LOG_GROUP_ARN = f"arn:aws:logs:us-east-1:{_ACCOUNT}:log-group:{_LOG_GROUP}"
_ZONE_ID = "/hostedzone/ZSLICE000001"
_CF_DOMAIN = "d111abcdef.cloudfront.net"  # == _CANNED list_distributions DomainName
_ENV_CANARY = "canary-db-password-5f1e"  # a Lambda env value that must never persist
_BUCKET = "sam-site"
# Secret-shaped canaries planted at each manifest-declared credential location
# whose entry has persist_configuration: false. None may persist anywhere.
_CF_CANARY = "canary-origin-verify-9c2a"
_APIGW_CANARY = "canary-backend-api-key-41d7"
_COGNITO_CANARY = "canary-sns-external-id-7b30"
_API_ID = "sliceapi01"
_API_ARN = f"arn:aws:apigateway:::/apis/{_API_ID}"  # canned clients carry no region
_POOL_ID = "us-east-1_Slice0001"
_BUCKET_ARN = f"arn:aws:s3:::{_BUCKET}"
_FN_NO_VPC_ARN = f"arn:aws:lambda:us-east-1:{_ACCOUNT}:function:sam-edge"

_CANNED = {
    "list_functions": {
        "Functions": [
            {
                "FunctionName": "sam-handler",
                "FunctionArn": _FN_ARN,
                "Runtime": "python3.13",
                "Handler": "app.handler",
                "MemorySize": 256,
                "Timeout": 30,
                "Role": _ROLE_ARN,
                "LoggingConfig": {"LogGroup": "/aws/lambda/sam-handler"},
                "LastModified": "2026-01-02T03:04:05.000+0000",
                # Secret-shaped environment: the Lambda manifest entry has
                # persist_configuration: false, so none of this may be stored.
                "Environment": {"Variables": {"DB_PASSWORD": _ENV_CANARY, "STAGE": "prod"}},
                "VpcConfig": {
                    "SubnetIds": ["subnet-0aaa1111", "subnet-0bbb2222"],
                    "SecurityGroupIds": ["sg-0ccc3333"],
                    "VpcId": "vpc-0ddd4444",
                },
            },
            {
                # Not in a VPC: ListFunctions returns empty VpcConfig lists.
                "FunctionName": "sam-edge",
                "FunctionArn": _FN_NO_VPC_ARN,
                "Runtime": "python3.13",
                "Handler": "edge.handler",
                "VpcConfig": {"SubnetIds": [], "SecurityGroupIds": [], "VpcId": ""},
            },
        ]
    },
    "list_roles": {
        "Roles": [
            {
                "RoleName": "sam-exec",
                "Arn": _ROLE_ARN,
                "Path": "/",
                "MaxSessionDuration": 3600,
            }
        ]
    },
    # Exercises CloudFront's RETRIEVES_CONTENT_FROM edge rule and its
    # s3_bucket_name_from_origin_domain transform (now registered); the
    # classify-skip regression test forces an empty registry to re-trigger
    # the EdgeError path deterministically.
    "list_distributions": {
        "DistributionList": {
            "Items": [
                {
                    "ARN": _DIST_ARN,
                    "DomainName": "d111abcdef.cloudfront.net",
                    "Status": "Deployed",
                    "Enabled": True,
                    "Origins": {
                        "Items": [
                            {
                                "Id": "sam-site-s3",
                                "DomainName": "sam-site.s3.amazonaws.com",
                                "OriginAccessControlId": "E2SLICEOAC0001",
                                "CustomHeaders": {
                                    "Quantity": 1,
                                    "Items": [{"HeaderName": "X-Origin-Verify", "HeaderValue": _CF_CANARY}],
                                },
                            },
                            {
                                # A custom origin with no OAC or OAI, and no custom
                                # header (ListDistributions reports Quantity 0).
                                "Id": "sam-api",
                                "DomainName": "api.samsite.example",
                                "CustomOriginConfig": {"OriginProtocolPolicy": "https-only"},
                                "CustomHeaders": {"Quantity": 0},
                            },
                        ]
                    },
                    "ViewerCertificate": {},
                }
            ]
        }
    },
    # CloudWatch log group — proves the WRITES_LOGS edge resolves
    # (req-aws-collector-edges-7): the log group is keyed by its ARN, and the
    # Lambda's bare LoggingConfig.LogGroup name is placed in the Lambda's own
    # region and account by the source-aware log_group_arn transform, so both
    # ends derive the identical natural_key and the edge is non-dangling.
    "describe_log_groups": {
        "logGroups": [
            {
                "logGroupName": _LOG_GROUP,
                "arn": f"arn:aws:logs:us-east-1:{_ACCOUNT}:log-group:{_LOG_GROUP}:*",
                "logGroupArn": f"arn:aws:logs:us-east-1:{_ACCOUNT}:log-group:{_LOG_GROUP}",
                "retentionInDays": 14,
            }
        ]
    },
    # Route 53: a hosted zone whose A-alias targets the canned CloudFront
    # distribution — proves ROUTES_TRAFFIC resolves non-dangling via the
    # route53 custom_fn's domain->ARN cross-join (req-aws-collector-edges-7;
    # no transform — the custom_fn does the join, edge keyed by CF ARN).
    "list_hosted_zones": {
        "HostedZones": [
            {
                "Id": _ZONE_ID,
                "Name": "samsite.unified-systems.com.",
                "Config": {"PrivateZone": False},
                "ResourceRecordSetCount": 2,
            }
        ]
    },
    "list_resource_record_sets": {
        "ResourceRecordSets": [
            {  # IPv4 alias -> CloudFront
                "Name": "samsite.unified-systems.com.",
                "Type": "A",
                "AliasTarget": {"DNSName": f"{_CF_DOMAIN}."},
            },
            {  # IPv6 alias -> same CloudFront (the standard pair; must
                # dedupe to ONE edge or GRIFT rejects on duplicate_entity_id)
                "Name": "samsite.unified-systems.com.",
                "Type": "AAAA",
                "AliasTarget": {"DNSName": f"{_CF_DOMAIN}."},
            },
            {  # non-alias record — ignored by the custom_fn
                "Name": "txt.samsite.unified-systems.com.",
                "Type": "TXT",
                "ResourceRecords": [{"Value": '"v=spf1 -all"'}],
            },
        ]
    },
    # S3 bucket + hydrate posture — the persist_configuration: true side of
    # the per-entry flag. get_bucket_versioning / get_bucket_policy_status /
    # get_bucket_location fall through to {} (a successful empty response).
    "list_buckets": {"Buckets": [{"Name": _BUCKET, "BucketArn": _BUCKET_ARN}]},
    "get_bucket_encryption": {
        "ServerSideEncryptionConfiguration": {
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        }
    },
    "get_public_access_block": {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        }
    },
    # API Gateway v2 HTTP API with a static header mapping carrying a key.
    # get_stages / get_authorizers fall through to {} (no items).
    "get_apis": {"Items": [{"ApiId": _API_ID, "Name": "sam-api", "ProtocolType": "HTTP"}]},
    "get_routes": {
        "Items": [
            {"RouteId": "r1", "RouteKey": "POST /orders", "AuthorizationType": "JWT", "AuthorizerId": "a1"},
            {"RouteId": "r2", "RouteKey": "GET /health", "AuthorizationType": "NONE"},
        ]
    },
    "get_integrations": {
        "Items": [
            {
                "IntegrationId": "int1",
                "IntegrationType": "HTTP_PROXY",
                "IntegrationUri": "https://backend.example.com",
                "RequestParameters": {"append:header.x-api-key": _APIGW_CANARY},
            }
        ]
    },
    # Cognito user pool whose SMS role assumption uses an external id.
    "list_user_pools": {"UserPools": [{"Id": _POOL_ID, "Name": "sam-pool"}]},
    "describe_user_pool": {
        "UserPool": {
            "Id": _POOL_ID,
            "Name": "sam-pool",
            "Arn": f"arn:aws:cognito-idp:us-east-1:{_ACCOUNT}:userpool/{_POOL_ID}",
            "MfaConfiguration": "OFF",
            "SmsConfiguration": {
                "SnsCallerArn": f"arn:aws:iam::{_ACCOUNT}:role/sam-sms",
                "ExternalId": _COGNITO_CANARY,
            },
        }
    },
    # IAM role tags — service side-quest (RGTA excludes IAM roles).
    "list_role_tags": {"Tags": [{"Key": "Owner", "Value": "sam-aydlette"}, {"Key": "Env", "Value": "prod"}]},
    # RGTA sweep result: the Lambda (rgta-source) tagged by its FunctionArn.
    "_rgta_pages": [
        {
            "ResourceTagMappingList": [
                {"ResourceARN": _FN_ARN, "Tags": [{"Key": "Owner", "Value": "sam"}]},
            ]
        }
    ],
}


class _RgtaPaginator:
    def paginate(self, **_kw):
        yield from _CANNED["_rgta_pages"]


class _CannedClient:
    """A boto3-client stand-in: canned ops return payloads, others empty."""

    def can_paginate(self, _method: str) -> bool:
        return False

    def get_paginator(self, _name: str) -> _RgtaPaginator:
        return _RgtaPaginator()

    def __getattr__(self, name: str):
        return lambda **_kw: _CANNED.get(name, {})


class _FakeEvents:
    """No-op botocore event emitter (fake clients fire no real events)."""

    def register(self, _name: str, _handler: object) -> None:
        return None


class _FakeSession:
    """Stands in for a boto3 Session for custom_fn (S3) paths."""

    events = _FakeEvents()

    def client(self, _service: str, **_kwargs: object) -> _CannedClient:
        return _CannedClient()


@pytest.fixture
def _stub_aws(monkeypatch):
    secret = Secret(
        ref=SecretRef(scope="aws_core", key="boto_collector"),
        kind="aws_static_access_key",
        description="test",
        data={
            "access_key_id": "AKIA",
            "secret_access_key": "shh",
            "regions_allowed": ["us-east-1"],
        },
        metadata={},
        source_path=__import__("pathlib").Path("/dev/null"),
    )
    monkeypatch.setattr(cred, "resolve_secret", lambda _ref: secret)
    monkeypatch.setattr(collector_mod, "build_session", lambda _data: _FakeSession())
    monkeypatch.setattr(collector_mod, "client_factory", lambda _s, _r: (lambda _svc: _CannedClient()))
    monkeypatch.setattr(collector_mod, "caller_account_id", lambda *a, **k: _ACCOUNT)


@pytest.mark.django_db
def test_canned_lambda_and_role_land_on_grid(_stub_aws):
    from tap_grid.services import get_edge, get_node

    collector = Boto3Collector(
        CollectorConfig(
            collector_entity_id=uuid.uuid7(),
            collection_job_entity_id=uuid.uuid7(),
        )
    )
    collector.run()

    # Pipeline completed cleanly: a batch imported, no structured errors.
    assert collector.results["error"] == []
    assert any(disposition == "imported" for _, disposition in collector._produced_batches)
    assert "Collected" in collector.summary

    # The audit ledger drained as exactly one structured run-log entry
    # (req-aws-collector-audit-ledger). Fake clients don't fire botocore
    # events, so `calls` is empty here — the live run is the real proof;
    # this guards the drain wiring + shape.
    ledger_entries = [e for e in collector.results["info"] if e["message_code"] == "AWS_CALL_LEDGER"]
    assert len(ledger_entries) == 1
    assert isinstance(ledger_entries[0]["message_data"]["calls"], list)

    # The Lambda node landed, typed, found by its natural key. Its manifest
    # entry has persist_configuration: false, so configuration is empty while
    # every typed field is still projected.
    fn = get_node(node_id("aws_core__aws_lambda", _FN_ARN))
    assert fn.name == "sam-handler"
    assert fn.function_arn == _FN_ARN
    assert fn.runtime == "python3.13"
    assert fn.handler == "app.handler"
    assert fn.memory_size == 256
    assert fn.timeout == 30
    assert fn.configuration == {}

    # Lambda tags came via the RGTA path (joined by FunctionArn).
    assert fn.tags == {"Owner": "sam"}

    # The IAM role node landed (global-scope entry).
    role = get_node(node_id("aws_core__aws_iam_role", _ROLE_ARN))
    assert role.name == "sam-exec"
    assert role.role_arn == _ROLE_ARN
    # IAM role tags came via the service side-quest (ListRoleTags, list_kv).
    assert role.tags == {"Owner": "sam-aydlette", "Env": "prod"}

    # The ASSUMES_ROLE edge resolved by identity — non-dangling because both
    # endpoints were collected this run (two-phase, identity-resolved).
    edge = get_edge(
        edge_between("ASSUMES_ROLE__aws_core", "aws_core__aws_lambda", _FN_ARN, "aws_core__aws_iam_role", _ROLE_ARN).entity_id
    )
    assert edge.edge_type == "ASSUMES_ROLE__aws_core"
    assert str(edge.from_entity_id) == str(node_id("aws_core__aws_lambda", _FN_ARN))
    assert str(edge.to_entity_id) == str(node_id("aws_core__aws_iam_role", _ROLE_ARN))

    # WRITES_LOGS resolves non-dangling (req-aws-collector-edges-7): the log group is keyed by
    # its ARN, and the Lambda's bare LoggingConfig.LogGroup name becomes that same ARN through the
    # source-aware log_group_arn transform (region and account from the Lambda's own ARN).
    lg = get_node(node_id("aws_core__aws_cloudwatch_log_group", _LOG_GROUP_ARN))
    assert lg.name == _LOG_GROUP
    assert lg.log_group_arn == _LOG_GROUP_ARN
    log_edge = get_edge(
        edge_between(
            "WRITES_LOGS__aws_core", "aws_core__aws_lambda", _FN_ARN, "aws_core__aws_cloudwatch_log_group", _LOG_GROUP_ARN
        ).entity_id
    )
    assert log_edge.edge_type == "WRITES_LOGS__aws_core"
    assert str(log_edge.from_entity_id) == str(node_id("aws_core__aws_lambda", _FN_ARN))
    assert str(log_edge.to_entity_id) == str(node_id("aws_core__aws_cloudwatch_log_group", _LOG_GROUP_ARN))

    # ROUTES_TRAFFIC resolves non-dangling through the route53 custom_fn's
    # CloudFront cross-join: the zone's A-alias domain -> the already-
    # collected CloudFront node by ARN identity. No transform — the
    # custom_fn did the domain->ARN join (req-aws-collector-edges-7). Note
    # the manifest-registered type is aws_route53_zone (model + plugin),
    # which the collector manifest was reconciled to.
    zone = get_node(node_id("aws_core__aws_route53_zone", _ZONE_ID))
    assert zone.name == "samsite.unified-systems.com."
    route_edge = get_edge(
        edge_between(
            "ROUTES_TRAFFIC__aws_core", "aws_core__aws_route53_zone", _ZONE_ID, "aws_core__aws_cloudfront_distribution", _DIST_ARN
        ).entity_id
    )
    assert route_edge.edge_type == "ROUTES_TRAFFIC__aws_core"
    assert str(route_edge.from_entity_id) == str(node_id("aws_core__aws_route53_zone", _ZONE_ID))
    assert str(route_edge.to_entity_id) == str(node_id("aws_core__aws_cloudfront_distribution", _DIST_ARN))


@pytest.mark.django_db
def test_unregistered_custom_fn_is_classified_not_fatal(_stub_aws, monkeypatch):
    """An unregistered custom_fn classifies-and-skips; the run still succeeds.

    route53_zones_with_alias_targets and s3_buckets_hydrated now ship
    registered (#19), so — exactly like the transform regression below —
    this forces an empty custom_fn registry to re-trigger the
    classify-and-skip path deterministically, independent of which
    custom_fns ship registered.
    """
    from tap_plugin.aws_core.collectors.boto3_collector.source import CustomFnRegistry

    monkeypatch.setattr(collector_mod, "build_custom_fn_registry", CustomFnRegistry)

    collector = Boto3Collector(
        CollectorConfig(
            collector_entity_id=uuid.uuid7(),
            collection_job_entity_id=uuid.uuid7(),
        )
    )
    collector.run()
    assert collector.results["error"] == []
    assert collector._produced_batches  # run reached submit_grift
    skips = [w for w in collector.results["warn"] if w["message_code"] == "ENTRY_SKIPPED"]
    assert any("route53_zones_with_alias_targets" in s["message"] for s in skips)


@pytest.mark.django_db
def test_unregistered_edge_transform_is_classified_not_fatal(_stub_aws, monkeypatch):
    """Regression (found on a live run): an EdgeError from the edge pass

    (a manifest transform with no registered callable) must be
    classified-and-skipped exactly like an unregistered custom_fn — it must
    not escape and abort the whole run before submit_grift. Forced
    deterministically with an empty transform registry, independent of which
    transforms ship registered.
    """
    from tap_plugin.aws_core.collectors.boto3_collector.edges import TransformRegistry

    from tap_grid.services import get_node

    # build_transform_registry now takes the run's partition (GovCloud readiness,
    # tap-plugin-aws-core#GovCloud); the empty-registry substitution just needs to accept and
    # discard it.
    monkeypatch.setattr(collector_mod, "build_transform_registry", lambda _partition=None: TransformRegistry())

    collector = Boto3Collector(
        CollectorConfig(
            collector_entity_id=uuid.uuid7(),
            collection_job_entity_id=uuid.uuid7(),
        )
    )
    collector.run()

    assert collector.results["error"] == []
    assert collector._produced_batches  # run reached submit_grift
    skips = [w for w in collector.results["warn"] if w["message_code"] == "ENTRY_SKIPPED"]
    assert any("s3_bucket_name_from_origin_domain" in s["message"] for s in skips)

    # The distribution node still landed — it is appended before the edge
    # pass runs, so the skipped edge does not lose the node.
    dist = get_node(node_id("aws_core__aws_cloudfront_distribution", _DIST_ARN))
    assert dist.distribution_arn == _DIST_ARN


@pytest.mark.django_db
def test_rejected_grift_batch_fails_loudly_not_silently(_stub_aws, monkeypatch):
    """Regression (found live): GRIFT rejects a batch atomically on a hard
    error (e.g. duplicate_entity_id) -> imported=[] skipped=[]. A rejected
    batch is otherwise invisible (0 imported, 0 errors, false green). The
    abort-on-rejection guard now lives in CollectorBase.submit_grift
    (on_rejection="abort" default, req-tap-cares-collector-grift-import-9):
    it records GRIFT_BATCH_REJECTED on the collector's results and raises
    GriftRejectedError, which the task body turns into FAILED. End-to-end
    proof that the base guard fires through the real aws_core run path.
    """
    from tap_cares.exceptions import GriftRejectedError

    class _Issue:
        code = "duplicate_entity_id"
        message = "Duplicate entity_id 'deadbeef'"

    class _Counts:
        batches_imported = 0

    class _Result:
        imported_batches: list = []
        skipped_batches: list = []
        errors = [_Issue()]
        counts = _Counts()

    monkeypatch.setattr("tap_grid.grift.grift_import", lambda *a, **k: _Result())

    collector = Boto3Collector(
        CollectorConfig(
            collector_entity_id=uuid.uuid7(),
            collection_job_entity_id=uuid.uuid7(),
        )
    )
    with pytest.raises(GriftRejectedError):
        collector.run()

    errs = [e for e in collector.results["error"] if e["message_code"] == "GRIFT_BATCH_REJECTED"]
    assert len(errs) == 1
    assert "duplicate_entity_id" in errs[0]["message"]
    assert "nothing landed" in errs[0]["message"]


def _run_collector():
    collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
    collector.run()
    assert collector.results["error"] == []


def _entry(entity_type: str) -> dict:
    return next(e for e in manifest_entries() if e["entity_type"] == entity_type)


@pytest.mark.django_db
def test_s3_bucket_persists_its_configuration_with_posture(_stub_aws):
    """A persist_configuration: true entry stores the full envelope,
    hydrate posture and _source included."""
    from tap_grid.services import get_node

    assert _entry("aws_core__aws_s3_bucket")["persist_configuration"] is True
    _run_collector()
    bucket = get_node(node_id("aws_core__aws_s3_bucket", _BUCKET_ARN))
    config = bucket.configuration
    assert config["BucketArn"] == _BUCKET_ARN
    assert config["_source"]["op"] == "s3_buckets_hydrated"
    assert config["_hydrate"]["encryption"]["status"] == "ok"
    rule = config["_hydrate"]["encryption"]["data"]["ServerSideEncryptionConfiguration"]["Rules"][0]
    assert rule["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] == "AES256"
    pab = config["_hydrate"]["public_access_block"]["data"]["PublicAccessBlockConfiguration"]
    assert pab["BlockPublicPolicy"] is True
    # The typed field is projected from that slot (req-aws-core-fields-9): all four flags on.
    assert bucket.public_access_blocked is True
    assert config["_hydrate_mapping"]["policy"]["op"] == "GetBucketPolicy"


# (entity_type, natural_key, canary, typed field name, expected typed value)
_OFF_CASES = [
    ("aws_core__aws_lambda", _FN_ARN, _ENV_CANARY, "runtime", "python3.13"),
    ("aws_core__aws_cloudfront_distribution", _DIST_ARN, _CF_CANARY, "domain_name", _CF_DOMAIN),
    ("aws_core__aws_apigateway_http_api", _API_ARN, _APIGW_CANARY, "api_id", _API_ID),
    ("aws_core__aws_cognito_user_pool", _POOL_ID, _COGNITO_CANARY, "mfa_configuration", "OFF"),
]
_OFF_IDS = [case[0] for case in _OFF_CASES]


def _row_dump(node) -> str:
    """Every concrete column value on the node row plus its history rows."""
    values = [getattr(node, f.attname) for f in node._meta.concrete_fields]
    values += [getattr(h, f.attname) for h in node.history.all() for f in h._meta.concrete_fields]
    return json.dumps(values, default=str)


@pytest.mark.django_db
@pytest.mark.parametrize(("entity_type", "natural_key", "canary", "field", "value"), _OFF_CASES, ids=_OFF_IDS)
def test_credential_canary_is_not_persisted(_stub_aws, monkeypatch, entity_type, natural_key, canary, field, value):
    """A persist_configuration: false entry stores none of its raw response.

    Checked at both boundaries: the GRIFT document handed to submit_grift,
    and the stored node row with its history rows. Typed fields still land.
    """
    from tap_grid.services import get_node

    assert _entry(entity_type)["persist_configuration"] is False
    submitted: list[str] = []
    real_submit = Boto3Collector.submit_grift

    def _capture(self, document, **kwargs):
        submitted.append(json.dumps(document, default=str))
        return real_submit(self, document, **kwargs)

    monkeypatch.setattr(Boto3Collector, "submit_grift", _capture)
    _run_collector()

    assert len(submitted) == 1
    assert canary not in submitted[0]

    node = get_node(node_id(entity_type, natural_key))
    assert node.configuration == {}
    assert getattr(node, field) == value  # typed projection unaffected
    assert canary not in _row_dump(node)


@pytest.mark.django_db
@pytest.mark.parametrize(("entity_type", "natural_key", "canary", "field", "value"), _OFF_CASES, ids=_OFF_IDS)
def test_flag_is_what_keeps_the_canary_out(_stub_aws, monkeypatch, entity_type, natural_key, canary, field, value):
    """The entry's flag is the only control, and the canary really is in the
    canned response: set true, the canary is stored; back to false (the
    shipped value), the next collection replaces it with ``{}``."""
    from tap_grid.services import get_node

    entry = _entry(entity_type)
    monkeypatch.setitem(entry, "persist_configuration", True)
    _run_collector()
    node = get_node(node_id(entity_type, natural_key))
    assert canary in json.dumps(node.configuration)
    assert node.configuration["_source"]["why"] == entry["why"]

    monkeypatch.setitem(entry, "persist_configuration", False)
    _run_collector()
    node = get_node(node_id(entity_type, natural_key))
    assert node.configuration == {}
    assert getattr(node, field) == value


@pytest.mark.django_db
def test_promoted_security_facts_land_while_configuration_stays_empty(_stub_aws):
    """The security facts the off types would lose
    with configuration not stored are typed fields, and configuration is still
    ``{}`` for all four off types."""
    from tap_grid.services import get_node

    _run_collector()

    fn = get_node(node_id("aws_core__aws_lambda", _FN_ARN))
    assert fn.vpc_subnet_ids == ["subnet-0aaa1111", "subnet-0bbb2222"]
    assert fn.vpc_security_group_ids == ["sg-0ccc3333"]
    edge_fn = get_node(node_id("aws_core__aws_lambda", _FN_NO_VPC_ARN))
    assert edge_fn.vpc_subnet_ids == []  # not in a VPC
    assert edge_fn.vpc_security_group_ids == []

    dist = get_node(node_id("aws_core__aws_cloudfront_distribution", _DIST_ARN))
    assert dist.origin_access == {"sam-site-s3": "oac", "sam-api": "none"}

    api = get_node(node_id("aws_core__aws_apigateway_http_api", _API_ARN))
    assert api.route_authorization_types == {"POST /orders": "JWT", "GET /health": "NONE"}

    for node in (fn, edge_fn, dist, api):
        assert node.configuration == {}
    assert get_node(node_id("aws_core__aws_cognito_user_pool", _POOL_ID)).configuration == {}


@pytest.mark.django_db
def test_denied_routes_listing_stores_null_over_an_earlier_map(_stub_aws, monkeypatch):
    """A later denied GetRoutes must replace the stored map with NULL, not
    leave the last map in place: a stale map could hide a newly open route."""
    from botocore.exceptions import ClientError

    from tap_grid.services import get_node

    _run_collector()
    api_id = node_id("aws_core__aws_apigateway_http_api", _API_ARN)
    assert get_node(api_id).route_authorization_types == {"POST /orders": "JWT", "GET /health": "NONE"}

    def _denied(self, **_kw):
        raise ClientError({"Error": {"Code": "AccessDeniedException"}}, "GetRoutes")

    monkeypatch.setattr(_CannedClient, "get_routes", _denied, raising=False)
    _run_collector()
    assert get_node(api_id).route_authorization_types is None


@pytest.mark.django_db
def test_origin_header_presence_lands_and_the_value_never_does(_stub_aws, monkeypatch):
    """Each origin's custom-header presence is a typed
    field; the secret-shaped header value (and the header name) appears in no
    field, not in the GRIFT batch, and not in the stored row or its history.
    An origin without headers records ``False``, an observed absence, not a
    missing key or ``null``."""
    from tap_grid.services import get_node

    submitted: list[str] = []
    real_submit = Boto3Collector.submit_grift

    def _capture(self, document, **kwargs):
        submitted.append(json.dumps(document, default=str))
        return real_submit(self, document, **kwargs)

    monkeypatch.setattr(Boto3Collector, "submit_grift", _capture)
    _run_collector()

    dist = get_node(node_id("aws_core__aws_cloudfront_distribution", _DIST_ARN))
    assert dist.origin_custom_headers_present == {"sam-site-s3": True, "sam-api": False}
    assert dist.origin_custom_headers_present["sam-api"] is False  # absence, not unobserved

    assert len(submitted) == 1
    for secret in (_CF_CANARY, "X-Origin-Verify"):
        assert secret not in json.dumps(dist.origin_custom_headers_present)
        assert secret not in submitted[0]
        assert secret not in _row_dump(dist)
    assert dist.history.exists()
