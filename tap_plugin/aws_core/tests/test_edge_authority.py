"""Per-anchor read status for the edge readers, and the authority claims built from it.

Spec: specs/spec-aws-core-collector-v0.md (req-aws-collector-edge-authority), aws-core-tap#77. The consumer
is tap's req-grid-reconcile-edge-authority: only ``read: complete`` lets tap propose removing an edge, so
every reader that feeds an edge rule has to tell four cases apart per anchor: complete with edges,
complete and empty, partial, and failed. Each reader is driven here with canned boto responses (the
house fakes: a client object whose methods return or raise), and the read is judged through the same
``anchor_reads`` the collector calls.
"""

from __future__ import annotations

import ast
import inspect
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector import authority, customfns
from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
from tap_plugin.aws_core.collectors.boto3_collector.authority import (
    COMPLETE,
    EDGE_READS,
    FAILED,
    PARTIAL,
    anchor_reads,
    claims_for,
    merge_claims,
    shared_scopes,
    with_edge_reads,
    worst,
)
from tap_plugin.aws_core.collectors.boto3_collector.batch import assemble_batch
from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    apigateway_http_apis_detailed,
    eventbridge_rules_with_targets,
    iam_roles_described,
    iam_users_described,
    read_sub_listing,
    route53_zones_with_alias_targets,
    s3_buckets_hydrated,
)
from tap_plugin.aws_core.collectors.boto3_collector.edges import emit_edges
from tap_plugin.aws_core.collectors.boto3_collector.identity import node_entity_id
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
from tap_plugin.aws_core.collectors.boto3_collector.transforms import build_transform_registry

from tap_cares.collectors.config import CollectorConfig

from .test_boto3_collector_slice import _CANNED, _CannedClient, _stub_aws  # noqa: F401 (fixture)

_ACCOUNT = "111122223333"
_LAMBDA_ARN = f"arn:aws:lambda:us-east-1:{_ACCOUNT}:function:worker"
_ROLE_ARN = f"arn:aws:iam::{_ACCOUNT}:role/worker"
_POLICY_ARN = f"arn:aws:iam::{_ACCOUNT}:policy/worker-policy"
_KMS_ARN = f"arn:aws:kms:us-east-1:{_ACCOUNT}:key/1234abcd-12ab-34cd-56ef-1234567890ab"
_ENTRIES = manifest_entries()
_MODELED = {e["entity_type"] for e in _ENTRIES}
_TRANSFORMS = build_transform_registry()


def _entry(entity_type: str) -> dict[str, Any]:
    return next(e for e in _ENTRIES if e["entity_type"] == entity_type)


def _reads(entity_type: str, item: dict[str, Any]) -> dict[tuple[str, str], str]:
    """The per-scope reads the collector would compute for one item of ``entity_type``."""
    entry = _entry(entity_type)
    return anchor_reads(project_item(entry, item), entry, modeled_types=_MODELED, transforms=_TRANSFORMS)


def _denied(op: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, op)


class _Client:
    """A boto3-client stand-in: ``responses`` maps a method to a payload, or to an exception to raise."""

    def __init__(self, responses: dict[str, Any], *, region: str = "us-east-1") -> None:
        self._responses = responses
        self.meta = type("Meta", (), {"region_name": region, "partition": "aws"})()

    def can_paginate(self, _method: str) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name not in self._responses:
            raise AttributeError(name)
        response = self._responses[name]

        def _call(**_kw: Any) -> Any:
            if isinstance(response, Exception):
                raise response
            return response

        return _call


# ---------------------------------------------------------------------------
# The three values
# ---------------------------------------------------------------------------


class TestTheThreeValues:
    def test_worst_is_the_most_severe(self):
        assert worst([COMPLETE, COMPLETE]) == COMPLETE
        assert worst([COMPLETE, PARTIAL]) == PARTIAL
        assert worst([PARTIAL, FAILED, COMPLETE]) == FAILED

    def test_nothing_said_is_never_complete(self):
        assert worst([]) == PARTIAL

    def test_an_unknown_value_counts_as_failed(self):
        assert worst([COMPLETE, "ok"]) == FAILED

    def test_a_declaration_outside_the_closed_set_is_refused(self):
        with pytest.raises(ValueError, match="read status"):
            with_edge_reads({}, {"_x": "empty"})

    def test_sub_listing_complete_empty_partial_failed(self):
        assert read_sub_listing(_Client({"list_x": {"Items": [1]}}), "list_x", "Items").status == COMPLETE
        empty = read_sub_listing(_Client({"list_x": {"Items": []}}), "list_x", "Items")
        assert (empty.status, empty.items) == (COMPLETE, [])
        partial = read_sub_listing(_Client({"list_x": {"Items": [1], "NextToken": "t"}}), "list_x", "Items")
        assert (partial.status, partial.items) == (PARTIAL, [1])
        failed = read_sub_listing(_Client({"list_x": _denied("ListX")}), "list_x", "Items")
        assert (failed.status, failed.items) == (FAILED, [])
        assert "AccessDenied" in failed.reason


# ---------------------------------------------------------------------------
# EventBridge: the defect the plan names (a failed ListTargetsByRule read as [])
# ---------------------------------------------------------------------------

_RULE = {
    "Name": "nightly",
    "Arn": f"arn:aws:events:us-east-1:{_ACCOUNT}:rule/nightly",
    "EventBusName": "default",
    "RoleArn": _ROLE_ARN,
}
_EVENTBRIDGE = "aws_core__aws_eventbridge_rule"
_INVOKES = ("INVOKES_LAMBDA__aws_core", "outbound")
_ASSUMES = ("ASSUMES_ROLE__aws_core", "outbound")


def _rule_item(targets: Any) -> dict[str, Any]:
    client = _Client({"list_rules": {"Rules": [_RULE]}, "list_targets_by_rule": targets})
    return next(iter(eventbridge_rules_with_targets(None, client_for=lambda _svc: client)))


class TestEventbridgeRuleReads:
    def test_complete_with_a_target(self):
        item = _rule_item({"Targets": [{"Id": "t", "Arn": _LAMBDA_ARN}]})
        assert item["_lambda_target_arns"] == [_LAMBDA_ARN]
        assert _reads(_EVENTBRIDGE, item)[_INVOKES] == COMPLETE

    def test_complete_and_empty(self):
        item = _rule_item({"Targets": []})
        assert item["_lambda_target_arns"] == []
        assert _reads(_EVENTBRIDGE, item)[_INVOKES] == COMPLETE

    def test_failed_targets_listing_is_failed_not_empty(self):
        item = _rule_item(_denied("ListTargetsByRule"))
        # The rule still collects with no target edges, as before ...
        assert item["Name"] == "nightly"
        assert item["_lambda_target_arns"] == []
        # ... but the read says it could not look.
        assert item[EDGE_READS]["_lambda_target_arns"] == FAILED
        assert _reads(_EVENTBRIDGE, item)[_INVOKES] == FAILED

    def test_a_targets_page_that_says_more_is_partial(self):
        item = _rule_item({"Targets": [{"Id": "t", "Arn": _LAMBDA_ARN}], "NextToken": "more"})
        assert _reads(_EVENTBRIDGE, item)[_INVOKES] == PARTIAL

    def test_the_role_is_the_rule_s_own_field(self):
        # ASSUMES_ROLE reads ListRules' own record, so a failed target listing does not touch it.
        item = _rule_item(_denied("ListTargetsByRule"))
        assert _reads(_EVENTBRIDGE, item)[_ASSUMES] == COMPLETE


# ---------------------------------------------------------------------------
# API Gateway: integrations and authorizers are per-API sub-listings
# ---------------------------------------------------------------------------

_APIGW = "aws_core__aws_apigateway_http_api"
_API_INVOKES = ("INVOKES_LAMBDA__aws_core", "outbound")
_API_AUTH = ("AUTHENTICATES_VIA_USER_POOL__aws_core", "outbound")
_LAMBDA_URI = f"arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/{_LAMBDA_ARN}/invocations"
_POOL_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Pool0001"


def _api_item(**overrides: Any) -> dict[str, Any]:
    responses: dict[str, Any] = {
        "get_apis": {"Items": [{"ApiId": "api1", "Name": "api"}]},
        "get_stages": {"Items": []},
        "get_routes": {"Items": [{"RouteKey": "GET /", "AuthorizationType": "JWT"}]},
        "get_integrations": {"Items": [{"IntegrationType": "AWS_PROXY", "IntegrationUri": _LAMBDA_URI}]},
        "get_authorizers": {"Items": [{"JwtConfiguration": {"Issuer": _POOL_ISSUER}}]},
    }
    responses.update(overrides)
    client = _Client(responses)
    return next(iter(apigateway_http_apis_detailed(None, client_for=lambda _svc: client)))


class TestApiGatewayReads:
    def test_complete_with_edges(self):
        item = _api_item()
        assert item["_integration_lambda_arns"] == [_LAMBDA_ARN]
        assert _reads(_APIGW, item) == {_API_INVOKES: COMPLETE, _API_AUTH: COMPLETE}

    def test_complete_and_empty(self):
        item = _api_item(get_integrations={"Items": []}, get_authorizers={"Items": []})
        assert _reads(_APIGW, item) == {_API_INVOKES: COMPLETE, _API_AUTH: COMPLETE}

    def test_failed_integrations(self):
        item = _api_item(get_integrations=_denied("GetIntegrations"))
        assert item["_integration_lambda_arns"] == []
        assert _reads(_APIGW, item)[_API_INVOKES] == FAILED
        assert _reads(_APIGW, item)[_API_AUTH] == COMPLETE

    def test_failed_authorizers(self):
        item = _api_item(get_authorizers=_denied("GetAuthorizers"))
        assert _reads(_APIGW, item)[_API_AUTH] == FAILED

    def test_truncated_integrations_are_partial(self):
        item = _api_item(get_integrations={"Items": [], "NextToken": "more"})
        assert _reads(_APIGW, item)[_API_INVOKES] == PARTIAL

    def test_a_lambda_integration_the_parser_cannot_name_is_partial(self):
        # A Lambda-proxy integration whose URI does not parse (here a stage-variable reference): the API
        # invokes a Lambda the edge cannot name, which is not "invokes nothing".
        unparsed = {"Items": [{"IntegrationType": "AWS_PROXY", "IntegrationUri": "${stageVariables.fn}"}]}
        assert _reads(_APIGW, _api_item(get_integrations=unparsed))[_API_INVOKES] == PARTIAL

    def test_non_lambda_integrations_are_out_of_scope_not_partial(self):
        other = {
            "Items": [
                {"IntegrationType": "HTTP_PROXY", "IntegrationUri": "https://backend.example.com"},
                {"IntegrationType": "AWS_PROXY", "IntegrationSubtype": "SQS-SendMessage"},
            ]
        }
        assert _reads(_APIGW, _api_item(get_integrations=other))[_API_INVOKES] == COMPLETE

    def test_truncated_routes_leave_the_authorization_map_unknown(self):
        item = _api_item(get_routes={"Items": [{"RouteKey": "GET /"}], "NextToken": "more"})
        assert item["_route_authorization_types"] is None


# ---------------------------------------------------------------------------
# IAM roles and users: hydrate-slot listings and the trust policy
# ---------------------------------------------------------------------------

_IAM_ROLE = "aws_core__aws_iam_role"
_IAM_USER = "aws_core__aws_iam_user"
_ATTACHES = ("ATTACHES_POLICY__aws_core", "outbound")
_FEDERATES = ("FEDERATES_INTO_ROLE__aws_core", "inbound")
_TRUSTS = ("TRUSTS_ACCOUNT__aws_core", "outbound")
_TRUST_DOC = {
    "Statement": [
        {"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::444455556666:root"}, "Action": "sts:AssumeRole"}
    ]
}


def _role_item(attached: Any, *, trust: Any = None) -> dict[str, Any]:
    trust = _TRUST_DOC if trust is None else trust
    role = {"RoleName": "worker", "Arn": _ROLE_ARN, "AssumeRolePolicyDocument": trust}
    client = _Client(
        {
            "list_roles": {"Roles": [role]},
            "get_account_summary": {"SummaryMap": {"Roles": 1}},
            "get_role": {"Role": role},
            "list_attached_role_policies": attached,
        }
    )
    return next(iter(iam_roles_described(None, client_for=lambda _svc: client)))


def _user_item(attached: Any) -> dict[str, Any]:
    user = {"UserName": "dev", "Arn": f"arn:aws:iam::{_ACCOUNT}:user/dev"}
    client = _Client(
        {
            "list_users": {"Users": [user]},
            "get_account_summary": {"SummaryMap": {"Users": 1}},
            "get_user": {"User": user},
            "list_attached_user_policies": attached,
            "list_mfa_devices": {"MFADevices": []},
        }
    )
    return next(iter(iam_users_described(None, client_for=lambda _svc: client)))


_ONE_POLICY = {"AttachedPolicies": [{"PolicyName": "p", "PolicyArn": _POLICY_ARN}], "IsTruncated": False}


class TestIamReads:
    @pytest.mark.parametrize(("make", "entity_type"), [(_role_item, _IAM_ROLE), (_user_item, _IAM_USER)])
    def test_attached_policies_four_ways(self, make, entity_type):
        assert _reads(entity_type, make(_ONE_POLICY))[_ATTACHES] == COMPLETE
        empty = make({"AttachedPolicies": [], "IsTruncated": False})
        assert empty["_attached_policy_arns"] == []
        assert _reads(entity_type, empty)[_ATTACHES] == COMPLETE
        truncated = make({**_ONE_POLICY, "IsTruncated": True, "Marker": "m"})
        assert _reads(entity_type, truncated)[_ATTACHES] == PARTIAL
        denied = make(_denied("ListAttachedPolicies"))
        assert denied["_attached_policy_arns"] is None
        assert _reads(entity_type, denied)[_ATTACHES] == FAILED

    def test_aws_managed_policies_are_out_of_scope_not_partial(self):
        managed = {"AttachedPolicies": [{"PolicyArn": "arn:aws:iam::aws:policy/ReadOnlyAccess"}], "IsTruncated": False}
        assert _reads(_IAM_ROLE, _role_item(managed))[_ATTACHES] == COMPLETE

    def test_a_decoded_trust_policy_is_complete(self):
        reads = _reads(_IAM_ROLE, _role_item(_ONE_POLICY))
        assert reads[_FEDERATES] == COMPLETE
        assert reads[_TRUSTS] == COMPLETE

    def test_an_encoded_trust_policy_is_partial_for_the_path_rule(self):
        # The FEDERATES_INTO_ROLE path walks a decoded document; a URL-encoded string yields no edge,
        # and that is not "trusts no identity provider". The trust summary decodes it, so TRUSTS_ACCOUNT
        # stays complete.
        encoded = "%7B%22Statement%22%3A%5B%5D%7D"
        reads = _reads(_IAM_ROLE, _role_item(_ONE_POLICY, trust=encoded))
        assert reads[_FEDERATES] == PARTIAL
        assert reads[_TRUSTS] == COMPLETE

    def test_an_unreadable_trust_policy_is_partial(self):
        reads = _reads(_IAM_ROLE, _role_item(_ONE_POLICY, trust="not json"))
        assert reads[_TRUSTS] == PARTIAL
        assert reads[_FEDERATES] == PARTIAL


# ---------------------------------------------------------------------------
# Route 53: an alias the collector cannot wire
# ---------------------------------------------------------------------------

_ZONE = "aws_core__aws_route53_zone"
_ROUTES = ("ROUTES_TRAFFIC__aws_core", "outbound")
_CF_ARN = f"arn:aws:cloudfront::{_ACCOUNT}:distribution/E1"


def _zone_item(records: dict[str, Any]) -> dict[str, Any]:
    client = _Client(
        {
            "list_distributions": {
                "DistributionList": {"Items": [{"DomainName": "d1.cloudfront.net", "ARN": _CF_ARN}]}
            },
            "list_hosted_zones": {"HostedZones": [{"Id": "/hostedzone/Z1", "Name": "example.com."}]},
            "list_resource_record_sets": records,
        }
    )
    return next(iter(route53_zones_with_alias_targets(None, client_for=lambda _svc: client)))


def _alias(domain: str) -> dict[str, Any]:
    return {"Name": "example.com.", "Type": "A", "AliasTarget": {"DNSName": f"{domain}."}}


class TestRoute53Reads:
    def test_complete_with_a_resolved_alias(self):
        item = _zone_item({"ResourceRecordSets": [_alias("d1.cloudfront.net")]})
        assert item["alias_cloudfront_arns"] == [_CF_ARN]
        assert _reads(_ZONE, item)[_ROUTES] == COMPLETE

    def test_complete_and_empty(self):
        assert _reads(_ZONE, _zone_item({"ResourceRecordSets": []}))[_ROUTES] == COMPLETE

    def test_records_that_are_not_cloudfront_aliases_do_not_touch_the_read(self):
        # Only CloudFront aliases are in ROUTES_TRAFFIC's scope: a TXT record, or an alias to another
        # service, beside a resolved CloudFront alias leaves the read complete.
        txt = {"Name": "example.com.", "Type": "TXT", "ResourceRecords": [{"Value": "x"}]}
        elb = _alias("lb-1.us-east-1.elb.amazonaws.com")
        item = _zone_item({"ResourceRecordSets": [txt, elb, _alias("d1.cloudfront.net")]})
        assert item["alias_cloudfront_arns"] == [_CF_ARN]
        assert _reads(_ZONE, item)[_ROUTES] == COMPLETE

    def test_an_alias_to_a_distribution_not_listed_is_partial(self):
        item = _zone_item({"ResourceRecordSets": [_alias("d1.cloudfront.net"), _alias("elsewhere.cloudfront.net")]})
        assert _reads(_ZONE, item)[_ROUTES] == PARTIAL

    def test_a_record_page_that_says_more_is_partial(self):
        item = _zone_item({"ResourceRecordSets": [], "IsTruncated": True, "NextRecordName": "x"})
        assert _reads(_ZONE, item)[_ROUTES] == PARTIAL

    def test_a_failed_record_listing_still_fails_the_entry(self):
        # Unchanged: the entry is skipped, so no zone and no claim reach the batch.
        with pytest.raises(ClientError):
            _zone_item(_denied("ListResourceRecordSets"))


# ---------------------------------------------------------------------------
# S3: the edge reads a hydrate slot
# ---------------------------------------------------------------------------

_BUCKET = "aws_core__aws_s3_bucket"
_ENCRYPTED = ("ENCRYPTED_WITH_KEY__aws_core", "outbound")


class _S3Session:
    def __init__(self, client: _Client) -> None:
        self._client = client

    def client(self, service: str, **_kw: Any) -> _Client:
        return self._client if service == "s3" else _Client({"get_metric_data": {"MetricDataResults": []}})


def _bucket_item(encryption: Any) -> dict[str, Any]:
    client = _Client(
        {
            "list_buckets": {"Buckets": [{"Name": "b1", "BucketArn": "arn:aws:s3:::b1"}]},
            "get_bucket_location": {"LocationConstraint": "us-east-1"},
            "get_bucket_encryption": encryption,
            "get_public_access_block": {},
            "get_bucket_versioning": {},
            "get_bucket_policy_status": {},
            "get_bucket_policy": {},
        }
    )
    session = _S3Session(client)
    return next(iter(s3_buckets_hydrated(session, client_for=lambda _svc: client)))


def _sse(key_id: str) -> dict[str, Any]:
    return {
        "ServerSideEncryptionConfiguration": {
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms", "KMSMasterKeyID": key_id}}]
        }
    }


class TestS3Reads:
    def test_complete_with_a_key(self):
        assert _reads(_BUCKET, _bucket_item(_sse(_KMS_ARN)))[_ENCRYPTED] == COMPLETE

    def test_no_encryption_configuration_is_complete_and_empty(self):
        absent = ClientError(
            {"Error": {"Code": "ServerSideEncryptionConfigurationNotFoundError", "Message": "none"}},
            "GetBucketEncryption",
        )
        assert _reads(_BUCKET, _bucket_item(absent))[_ENCRYPTED] == COMPLETE

    def test_denied_encryption_read_is_failed(self):
        assert _reads(_BUCKET, _bucket_item(_denied("GetBucketEncryption")))[_ENCRYPTED] == FAILED

    def test_a_key_reference_that_is_not_an_arn_is_partial(self):
        # A bare key id names a real key the edge cannot be keyed to without a join: not "no key".
        assert _reads(_BUCKET, _bucket_item(_sse("1234abcd-12ab-34cd-56ef-1234567890ab")))[_ENCRYPTED] == PARTIAL


# ---------------------------------------------------------------------------
# aws_op items, fail-closed custom_fn keys, unmodeled targets, folding
# ---------------------------------------------------------------------------


class TestJudgingRules:
    def test_an_aws_op_item_is_its_own_record(self):
        fn = {
            "FunctionName": "worker",
            "FunctionArn": _LAMBDA_ARN,
            "Role": _ROLE_ARN,
            "LoggingConfig": {"LogGroup": "/aws/lambda/worker"},
        }
        reads = _reads("aws_core__aws_lambda", fn)
        assert reads == {
            ("ASSUMES_ROLE__aws_core", "outbound"): COMPLETE,
            ("WRITES_LOGS__aws_core", "outbound"): COMPLETE,
        }

    def test_a_transform_that_cannot_map_a_reference_makes_it_partial(self):
        # A queue encrypted under an alias: the key exists, the edge cannot name it.
        queue = {
            "QueueArn": f"arn:aws:sqs:us-east-1:{_ACCOUNT}:q",
            "KmsMasterKeyId": "alias/aws/sqs",
            EDGE_READS: {"KmsMasterKeyId": COMPLETE},
        }
        assert _reads("aws_core__aws_sqs_queue", queue)[_ENCRYPTED] == PARTIAL

    def test_an_undeclared_custom_fn_key_fails_closed(self):
        # A custom_fn item that does not say how it read the key a rule reads is never complete.
        queue = {"QueueArn": f"arn:aws:sqs:us-east-1:{_ACCOUNT}:q", "KmsMasterKeyId": _KMS_ARN}
        assert _reads("aws_core__aws_sqs_queue", queue)[_ENCRYPTED] == PARTIAL

    def test_an_unmodeled_target_is_partial(self):
        entry = _entry(_EVENTBRIDGE)
        node = project_item(entry, _rule_item({"Targets": []}))
        reads = anchor_reads(node, entry, modeled_types=_MODELED - {"aws_core__aws_lambda"}, transforms=_TRANSFORMS)
        assert reads[_INVOKES] == PARTIAL

    def test_every_edge_the_emitter_drops_with_a_warning_reads_partial(self):
        # emit_edges warns (EDGE_DROPPED) on exactly one path: a target type the collector does not
        # model. The same rule must never read complete, or a claim would cover an edge never sent.
        entry = _entry(_EVENTBRIDGE)
        node = project_item(entry, _rule_item({"Targets": [{"Id": "t", "Arn": _LAMBDA_ARN}]}))
        modeled = _MODELED - {"aws_core__aws_lambda"}
        emission = emit_edges(node, entry, modeled_types=modeled, transforms=_TRANSFORMS, dimensions={})
        assert emission.warnings
        assert not any(e["edge"]["edge_type"] == "INVOKES_LAMBDA__aws_core" for e in emission.envelopes)
        assert anchor_reads(node, entry, modeled_types=modeled, transforms=_TRANSFORMS)[_INVOKES] == PARTIAL

    def test_rules_of_one_type_and_direction_fold_to_the_worst(self):
        # CloudTrail has two WRITES_LOGS rules (bucket, log group); a log-group reference the transform
        # cannot map makes the ONE claim partial even though the bucket rule read complete.
        trail = {
            "TrailARN": f"arn:aws:cloudtrail:us-east-1:{_ACCOUNT}:trail/t",
            "S3BucketName": "logs",
            "CloudWatchLogsLogGroupArn": "arn:aws:s3:::not-a-log-group",
            EDGE_READS: {"S3BucketName": COMPLETE, "CloudWatchLogsLogGroupArn": COMPLETE, "KmsKeyId": COMPLETE},
        }
        reads = _reads("aws_core__aws_cloudtrail_trail", trail)
        assert reads[("WRITES_LOGS__aws_core", "outbound")] == PARTIAL
        assert reads[_ENCRYPTED] == COMPLETE


class TestClaims:
    def test_claim_shape(self):
        entry = _entry(_EVENTBRIDGE)
        node = project_item(entry, _rule_item(_denied("ListTargetsByRule")))
        reads = anchor_reads(node, entry, modeled_types=_MODELED, transforms=_TRANSFORMS)
        claims = claims_for(node, reads, unclaimable=frozenset())
        assert {
            "edge_type": "INVOKES_LAMBDA__aws_core",
            "anchor": {"entity_id": str(node.entity_id)},
            "direction": "outbound",
            "read": FAILED,
        } in claims
        assert all(set(c) == {"edge_type", "anchor", "direction", "read"} for c in claims)

    def test_a_scope_another_entry_writes_into_is_not_claimed(self):
        entries = [
            {"entity_type": "a", "edges": [{"edge_type": "T", "direction": "outbound", "target_type": "b"}]},
            {"entity_type": "b", "edges": [{"edge_type": "T", "direction": "inbound", "target_type": "a"}]},
        ]
        assert shared_scopes(entries) == {("b", "T", "inbound"), ("a", "T", "outbound")}
        node = project_item(_entry(_EVENTBRIDGE), _rule_item({"Targets": []}))
        unclaimable = frozenset({(_EVENTBRIDGE, "INVOKES_LAMBDA__aws_core", "outbound")})
        claims = claims_for(node, {_INVOKES: COMPLETE, _ASSUMES: COMPLETE}, unclaimable=unclaimable)
        assert [c["edge_type"] for c in claims] == ["ASSUMES_ROLE__aws_core"]

    def test_the_manifest_has_no_shared_scope(self):
        # Every claim the collector makes today is over a scope only its anchor's own rules write.
        scopes = {(e["entity_type"], r["edge_type"], r["direction"]) for e in _ENTRIES for r in e.get("edges", [])}
        assert scopes.isdisjoint(shared_scopes(_ENTRIES))

    def test_one_claim_per_scope_with_the_worst_read(self):
        anchor = {"entity_id": str(uuid.uuid7())}
        merged = merge_claims(
            [
                {"edge_type": "T", "anchor": anchor, "direction": "outbound", "read": COMPLETE},
                {"edge_type": "T", "anchor": dict(anchor), "direction": "outbound", "read": FAILED},
                {"edge_type": "T", "anchor": anchor, "direction": "inbound", "read": COMPLETE},
            ]
        )
        assert sorted((c["direction"], c["read"]) for c in merged) == [("inbound", COMPLETE), ("outbound", FAILED)]

    def test_batch_carries_the_section_only_when_there_are_claims(self):
        claim = {
            "edge_type": "T",
            "anchor": {"entity_id": str(uuid.uuid7())},
            "direction": "outbound",
            "read": COMPLETE,
        }
        kwargs = {
            "source": "s",
            "manifest_version": "1",
            "account_id": "1",
            "regions": [],
            "node_envelopes": [],
            "edge_envelopes": [],
        }
        assert "edge_cases" not in assemble_batch(**kwargs)["batches"][0]
        assert "edge_cases" not in assemble_batch(**kwargs, authority=[])["batches"][0]
        assert assemble_batch(**kwargs, authority=[claim])["batches"][0]["edge_cases"] == {"authority": [claim]}


class TestOtherEdgeProducers:
    """Claims are made only from manifest edge rules. An edge type another producer in this collector
    also writes could put edges into a claimed scope that the claim's read knows nothing about."""

    _MODULES = ("organizations", "landing_zone", "findings", "containment")

    def _constants(self, module: str) -> set[str]:
        path = Path(inspect.getfile(customfns)).with_name(f"{module}.py")
        tree = ast.parse(path.read_text())
        return {
            node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and node.value.value.endswith("__aws_core")
        }

    def test_only_writes_logs_is_shared_and_never_at_a_claimed_anchor_type(self):
        rule_types = {r["edge_type"] for e in _ENTRIES for r in e.get("edges", [])}
        containment_types = {e["containment"]["edge_type"] for e in _ENTRIES if e.get("containment")}
        shared = set().union(*(self._constants(m) for m in self._MODULES)) & rule_types
        assert shared == {"WRITES_LOGS__aws_core"}
        assert not (containment_types & rule_types)
        # The landing zone writes WRITES_LOGS from a Config delivery channel, which no manifest entry is,
        # so it can never fall inside a claim made at a Lambda or a trail.
        source = Path(inspect.getfile(customfns)).with_name("landing_zone.py").read_text()
        assert source.count("WRITES_LOGS,") == 1
        assert "WRITES_LOGS, CONFIG_DELIVERY_CHANNEL," in source
        claimed_anchor_types = {
            e["entity_type"]
            for e in _ENTRIES
            if any(r["edge_type"] == "WRITES_LOGS__aws_core" for r in e.get("edges", []))
        }
        assert "aws_core__aws_config_delivery_channel" not in claimed_anchor_types


# ---------------------------------------------------------------------------
# Through the collector
# ---------------------------------------------------------------------------


def _capture(monkeypatch) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    real_submit = Boto3Collector.submit_grift

    def _submit(self, document, **kwargs):
        documents.append(document)
        return real_submit(self, document, **kwargs)

    monkeypatch.setattr(Boto3Collector, "submit_grift", _submit)
    return documents


def _run() -> Boto3Collector:
    collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
    collector.run()
    assert collector.results["error"] == []
    return collector


_SLICE_RULE = {
    "Name": "slice-rule",
    "Arn": f"arn:aws:events:us-east-1:{_ACCOUNT}:rule/slice-rule",
    "EventBusName": "default",
}


@pytest.mark.django_db
@pytest.mark.usefixtures("_stub_aws")
class TestThroughTheCollector:
    def test_claims_are_judged_and_logged_but_not_sent_to_an_importer_without_the_section(self, monkeypatch):
        monkeypatch.setattr(collector_mod, "importer_accepts_edge_cases", lambda: False)
        documents = _capture(monkeypatch)
        collector = _run()
        assert "edge_cases" not in documents[0]["batches"][0]
        record = next(e for e in collector.results["info"] if e["message_code"] == "EDGE_AUTHORITY_CLAIMS")
        assert record["message_data"]["emitted"] is False
        assert sum(record["message_data"]["counts"].values()) > 0

    def test_a_failed_target_listing_is_sent_as_failed(self, monkeypatch):
        monkeypatch.setattr(collector_mod, "importer_accepts_edge_cases", lambda: True)
        monkeypatch.setitem(_CANNED, "list_rules", {"Rules": [_SLICE_RULE]})

        def _denied_targets(self, **_kw):
            raise _denied("ListTargetsByRule")

        monkeypatch.setattr(_CannedClient, "list_targets_by_rule", _denied_targets, raising=False)
        # Judge only: the document is captured and not imported (the next test imports one).
        documents: list[dict[str, Any]] = []

        def _judge_only(self, document, **_kw):
            documents.append(document)
            return SimpleNamespace(imported_batches=[], counts=SimpleNamespace(batches_imported=0))

        monkeypatch.setattr(Boto3Collector, "submit_grift", _judge_only)
        _run()
        claims = documents[0]["batches"][0]["edge_cases"]["authority"]
        rule_id = str(node_entity_id(_EVENTBRIDGE, _SLICE_RULE["Arn"]))
        rule_claims = {
            (c["edge_type"], c["direction"]): c["read"] for c in claims if c["anchor"]["entity_id"] == rule_id
        }
        assert rule_claims[_INVOKES] == FAILED
        # One claim per scope across the whole batch.
        scopes = [(c["edge_type"], c["anchor"]["entity_id"], c["direction"]) for c in claims]
        assert len(scopes) == len(set(scopes))
        # Every claim carries a read from the closed set; none is defaulted.
        assert {c["read"] for c in claims} <= {COMPLETE, PARTIAL, FAILED}

    @pytest.mark.skipif(not authority.importer_accepts_edge_cases(), reason="this tap's importer predates edge_cases")
    def test_the_importer_accepts_the_claims(self, monkeypatch):
        documents = _capture(monkeypatch)
        collector = _run()
        assert documents[0]["batches"][0]["edge_cases"]["authority"]
        assert any(disposition == "imported" for _, disposition in collector._produced_batches)
