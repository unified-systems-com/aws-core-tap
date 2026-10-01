"""Unit tests for the Sam-since-fork service types (boto3-free, no DB).

Covers the custom_fns and edge transforms added for API Gateway v2 HTTP
APIs, Cognito user pools, KMS keys, SQS queues, and CloudTrail trails
(plus the Secrets Manager KMS edge transform they share): enumeration
shaping, edge-key derivation (Lambda integration URIs, Cognito JWT
issuers), per-item fan-out degradation, and the natural-key discipline
(unqualified Lambda ARN, pool Id, key ARN, home-region-only trails).
"""

from __future__ import annotations

from types import SimpleNamespace

from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    _lambda_arn_from_integration_uri,
    apigateway_http_apis_detailed,
    cloudtrail_trails_described,
    cognito_user_pools_described,
    kms_keys_described,
    sqs_queues_described,
)
from tap_plugin.aws_core.collectors.boto3_collector.transforms import (
    kms_key_arn_or_none,
    log_group_arn,
    s3_bucket_arn_from_name,
)

_LAMBDA_ARN = "arn:aws:lambda:us-east-1:111122223333:function:silk-reeling"
_INTEGRATION_URI = "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/" f"{_LAMBDA_ARN}/invocations"
_KMS_ARN = "arn:aws:kms:us-east-1:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab"


def _denied(op: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDeniedException"}}, op)


class TestTransforms:
    def test_kms_key_arn_passes_through(self):
        assert kms_key_arn_or_none(_KMS_ARN) == _KMS_ARN

    def test_kms_alias_bare_id_and_junk_drop(self):
        assert kms_key_arn_or_none("alias/aws/s3") is None
        assert kms_key_arn_or_none("1234abcd-12ab-34cd-56ef-1234567890ab") is None
        assert kms_key_arn_or_none(None) is None
        assert kms_key_arn_or_none(12) is None

    def test_s3_bucket_name_becomes_arn(self):
        assert s3_bucket_arn_from_name("audit-logs") == "arn:aws:s3:::audit-logs"

    def test_s3_arn_passes_through_and_empty_drops(self):
        assert s3_bucket_arn_from_name("arn:aws:s3:::audit-logs") == "arn:aws:s3:::audit-logs"
        assert s3_bucket_arn_from_name("  ") is None
        assert s3_bucket_arn_from_name(None) is None

    def test_log_group_arn_from_arn_drops_the_suffix(self):
        arn = "arn:aws:logs:us-east-1:111122223333:log-group:/aws/lambda/x"
        assert log_group_arn(arn + ":*") == arn
        assert log_group_arn(arn) == arn

    def test_log_group_arn_from_name_takes_region_and_account_from_the_source(self):
        """A Lambda names its log group by bare name; the key's region, account and partition come
        from the Lambda's own ARN (the referring node's natural key)."""
        gov_fn = "arn:aws-us-gov:lambda:us-gov-east-1:111122223333:function:x"
        assert log_group_arn("/aws/lambda/x", source_key=_LAMBDA_ARN) == (
            "arn:aws:logs:us-east-1:111122223333:log-group:/aws/lambda/x"
        )
        assert log_group_arn("/aws/lambda/x", source_key=gov_fn) == (
            "arn:aws-us-gov:logs:us-gov-east-1:111122223333:log-group:/aws/lambda/x"
        )

    def test_log_group_non_matching_drops(self):
        assert log_group_arn("arn:aws:s3:::not-logs") is None
        assert log_group_arn("arn:aws:logs:us-east-1:111122223333:log-group::*") is None
        assert log_group_arn(None) is None
        assert log_group_arn("  ") is None
        # A bare name with no regional ARN to place it in is not guessed.
        assert log_group_arn("/aws/lambda/x") is None
        assert log_group_arn("/aws/lambda/x", source_key="arn:aws:s3:::bucket") is None


class TestLambdaArnFromIntegrationUri:
    def test_proxy_uri_yields_unqualified_arn(self):
        assert _lambda_arn_from_integration_uri(_INTEGRATION_URI) == _LAMBDA_ARN

    def test_alias_qualifier_is_stripped(self):
        qualified = _INTEGRATION_URI.replace("/invocations", ":live/invocations")
        assert _lambda_arn_from_integration_uri(qualified) == _LAMBDA_ARN

    def test_non_lambda_uri_drops(self):
        assert _lambda_arn_from_integration_uri("https://example.org/backend") is None
        assert _lambda_arn_from_integration_uri("") is None


class _FakeApiGw:
    meta = SimpleNamespace(region_name="us-east-1")

    def __init__(self, *, routes_fail: bool = False):
        self._routes_fail = routes_fail

    def can_paginate(self, _m: str) -> bool:
        return False

    def get_apis(self, **_kw):
        return {
            "Items": [
                {
                    "ApiId": "a1b2c3",
                    "Name": "silk-reeling-api",
                    "ProtocolType": "HTTP",
                    "ApiEndpoint": "https://a1b2c3.execute-api.us-east-1.amazonaws.com",
                    "Tags": {"Project": "samsite"},
                }
            ]
        }

    def get_stages(self, **_kw):
        return {"Items": [{"StageName": "$default"}]}

    def get_routes(self, **_kw):
        if self._routes_fail:
            raise _denied("GetRoutes")
        return {
            "Items": [
                {"RouteKey": "POST /verify", "AuthorizationType": "JWT", "AuthorizerId": "auth1"},
                {"RouteKey": "POST /hook", "AuthorizationType": "CUSTOM", "AuthorizerId": "auth2"},
                {"RouteKey": "GET /health", "AuthorizationType": "NONE"},
                {"RouteKey": "$default"},  # AuthorizationType omitted: AWS default NONE
            ]
        }

    def get_integrations(self, **_kw):
        return {
            "Items": [
                {"IntegrationUri": _INTEGRATION_URI},
                {"IntegrationUri": _INTEGRATION_URI},  # dedup target
                {"IntegrationUri": "https://example.org/http-backend"},
            ]
        }

    def get_authorizers(self, **_kw):
        return {
            "Items": [
                {"JwtConfiguration": {"Issuer": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_AbCd1234"}},
                {"JwtConfiguration": {"Issuer": "https://accounts.example.org"}},
            ]
        }


class TestApiGatewayHttpApisDetailed:
    def _collect(self, client):
        return list(apigateway_http_apis_detailed(None, client_for=lambda _s: client))

    def test_arn_synthesized_and_edge_keys_derived(self):
        (api,) = self._collect(_FakeApiGw())
        assert api["_api_arn"] == "arn:aws:apigateway:us-east-1::/apis/a1b2c3"
        assert api["_integration_lambda_arns"] == [_LAMBDA_ARN]  # deduped, non-Lambda dropped
        assert api["_authorizer_user_pool_ids"] == ["us-east-1_AbCd1234"]  # non-Cognito dropped
        assert api["_stages"] == [{"StageName": "$default"}]

    def test_sub_listing_failure_degrades_not_fatal(self):
        (api,) = self._collect(_FakeApiGw(routes_fail=True))
        assert api["_routes"] == []
        assert api["_integration_lambda_arns"] == [_LAMBDA_ARN]

    def test_route_authorization_types_per_route(self):
        # Which routes require an authorizer, and of
        # which type, survives configuration being off as a typed field.
        (api,) = self._collect(_FakeApiGw())
        assert api["_route_authorization_types"] == {
            "POST /verify": "JWT",
            "POST /hook": "CUSTOM",
            "GET /health": "NONE",
            "$default": "NONE",
        }

    def test_denied_routes_listing_is_unobserved_not_open(self):
        # A failed GetRoutes must not read as "no routes" (and so "nothing
        # open"): the field is None, which the grid reads as unobserved.
        (api,) = self._collect(_FakeApiGw(routes_fail=True))
        assert api["_route_authorization_types"] is None


class _FakeCognito:
    def can_paginate(self, _m: str) -> bool:
        return False

    def list_user_pools(self, **_kw):
        return {"UserPools": [{"Id": "us-east-1_AbCd1234", "Name": "silk-users"}]}

    def describe_user_pool(self, *, UserPoolId):
        return {
            "UserPool": {
                "Id": UserPoolId,
                "Name": "silk-users",
                "Arn": f"arn:aws:cognito-idp:us-east-1:111122223333:userpool/{UserPoolId}",
                "MfaConfiguration": "ON",
                "Domain": "silk-auth",
                "UserPoolTags": {"Project": "samsite"},
            }
        }


class TestCognitoUserPoolsDescribed:
    def test_yields_described_pool_with_id_at_root(self):
        (pool,) = list(cognito_user_pools_described(None, client_for=lambda _s: _FakeCognito()))
        assert pool["Id"] == "us-east-1_AbCd1234"
        assert pool["MfaConfiguration"] == "ON"
        assert pool["UserPoolTags"] == {"Project": "samsite"}


class _FakeKms:
    def __init__(self, *, describe_denied: bool = False):
        self._describe_denied = describe_denied

    def can_paginate(self, _m: str) -> bool:
        return False

    def list_aliases(self, **_kw):
        return {
            "Aliases": [
                {"AliasName": "alias/samsite-at-rest", "TargetKeyId": "key-1"},
                {"AliasName": "alias/aws/s3", "TargetKeyId": "key-aws"},
            ]
        }

    def list_keys(self, **_kw):
        return {"Keys": [{"KeyId": "key-1", "KeyArn": _KMS_ARN}]}

    def describe_key(self, *, KeyId):
        if self._describe_denied:
            raise _denied("DescribeKey")
        return {
            "KeyMetadata": {
                "KeyId": KeyId,
                "Arn": _KMS_ARN,
                "KeyState": "Enabled",
                "KeyManager": "CUSTOMER",
                "Description": "samsite at-rest key",
            }
        }

    def list_resource_tags(self, **_kw):
        return {"Tags": [{"TagKey": "Project", "TagValue": "samsite"}]}


class TestKmsKeysDescribed:
    def test_alias_join_display_name_and_tag_normalization(self):
        (key,) = list(kms_keys_described(None, client_for=lambda _s: _FakeKms()))
        assert key["Arn"] == _KMS_ARN
        assert key["_aliases"] == ["alias/samsite-at-rest"]
        assert key["_display_name"] == "samsite-at-rest"
        assert key["_tags"] == {"Project": "samsite"}

    def test_describe_denied_falls_back_to_listing_shell(self):
        (key,) = list(kms_keys_described(None, client_for=lambda _s: _FakeKms(describe_denied=True)))
        assert key["Arn"] == _KMS_ARN  # ARN survives from ListKeys
        assert "KeyState" not in key


_QUEUE_ARN = "arn:aws:sqs:us-east-1:111122223333:opa-compliance-dlq"


class _FakeSqs:
    def __init__(self, *, tags_fail: bool = False):
        self._tags_fail = tags_fail

    def can_paginate(self, _m: str) -> bool:
        return False

    def list_queues(self, **_kw):
        return {"QueueUrls": ["https://sqs.us-east-1.amazonaws.com/111122223333/opa-compliance-dlq"]}

    def get_queue_attributes(self, **_kw):
        return {
            "Attributes": {
                "QueueArn": _QUEUE_ARN,
                "VisibilityTimeout": "30",
                "MessageRetentionPeriod": "1209600",
            }
        }

    def list_queue_tags(self, **_kw):
        if self._tags_fail:
            raise _denied("ListQueueTags")
        return {"Tags": {"Project": "samsite"}}


class TestSqsQueuesDescribed:
    def test_attributes_flattened_and_name_from_arn(self):
        (queue,) = list(sqs_queues_described(None, client_for=lambda _s: _FakeSqs()))
        assert queue["QueueArn"] == _QUEUE_ARN
        assert queue["_queue_name"] == "opa-compliance-dlq"
        assert queue["_tags"] == {"Project": "samsite"}

    def test_tag_fetch_failure_degrades(self):
        (queue,) = list(sqs_queues_described(None, client_for=lambda _s: _FakeSqs(tags_fail=True)))
        assert queue["_tags"] == {}


_TRAIL_ARN = "arn:aws:cloudtrail:us-east-1:111122223333:trail/samsite-audit"


class _FakeCloudTrail:
    meta = SimpleNamespace(region_name="us-east-1")

    def can_paginate(self, _m: str) -> bool:
        return False

    def describe_trails(self, **_kw):
        return {
            "trailList": [
                {
                    "Name": "samsite-audit",
                    "TrailARN": _TRAIL_ARN,
                    "HomeRegion": "us-east-1",
                    "S3BucketName": "samsite-audit-logs",
                    "IsMultiRegionTrail": True,
                },
                {
                    "Name": "elsewhere",
                    "TrailARN": "arn:aws:cloudtrail:eu-west-1:111122223333:trail/elsewhere",
                    "HomeRegion": "eu-west-1",
                },
            ]
        }

    def get_trail_status(self, **_kw):
        return {"IsLogging": True}

    def list_tags(self, **_kw):
        return {"ResourceTagList": [{"ResourceId": _TRAIL_ARN, "TagsList": [{"Key": "Project", "Value": "samsite"}]}]}


class TestCloudtrailTrailsDescribed:
    def test_home_region_only_status_and_tags(self):
        trails = list(cloudtrail_trails_described(None, client_for=lambda _s: _FakeCloudTrail()))
        assert [t["TrailARN"] for t in trails] == [_TRAIL_ARN]  # foreign home region filtered
        (trail,) = trails
        assert trail["_is_logging"] is True
        assert trail["_tags"] == {"Project": "samsite"}
