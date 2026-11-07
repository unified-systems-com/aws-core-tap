"""The gap sweep: tag reads that cannot succeed, the ledger's error codes, fields the manifest left unmapped,
the load balancer and zone routing edges, and the new reference edges (no network, fake clients)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from botocore.exceptions import ClientError

from tap_plugin.aws_core.collectors.boto3_collector import customfns
from tap_plugin.aws_core.collectors.boto3_collector.collector import resolve_node_tags
from tap_plugin.aws_core.collectors.boto3_collector.edges import TransformRegistry
from tap_plugin.aws_core.collectors.boto3_collector.ledger import CallLedger
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.paths import eval_path
from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
from tap_plugin.aws_core.collectors.boto3_collector.transforms import build_transform_registry


def _entry(entity: str) -> dict[str, Any]:
    return next(e for e in manifest_entries() if e["entity_type"] == f"aws_core__aws_{entity}")


class _Refusing:
    """A client whose tag call is refused with one error."""

    def __init__(self, code: str, message: str, op: str) -> None:
        self._error = ClientError({"Error": {"Code": code, "Message": message}}, op)

    def list_tags_for_resource(self, **_kw: Any) -> Any:
        raise self._error

    list_tags = list_tags_for_resource


NOT_TAGGABLE = [
    ("appconfig_extension", {"Arn": "arn:aws-us-gov:appconfig:us-gov-west-1::extension/AWS.AppConfig.FeatureFlags/1"},
     "BadRequestException", "ARN arn:x is invalid due to not containing an account ID.", "ListTagsForResource"),
    ("route53resolver_resolver_rule", {"Arn": "arn:x"}, "InvalidRequestException", "[RSLVR-00903] Cannot tag Auto Defined Rule.", "ListTagsForResource"),
    ("route53resolver_firewall_domain_list", {"Arn": "arn:x"}, "InvalidParameterException",
     "[RSLVR-00907] You are not authorized to do this operation on shared resource", "ListTagsForResource"),
    ("sagemaker_hub", {"HubArn": "arn:x"}, "ValidationException", "Value 'arn:aws-us-gov:sagemaker:us-gov-west-1:aws:hub/SageMakerPublicHub' failed", "ListTags"),
    ("athena_data_catalog", {"Name": "AwsDataCatalog"}, "ResourceNotFoundException", "Could not find valid resource from ARN: arn:x:datacatalog/AwsDataCatalog", "ListTagsForResource"),
]


@pytest.mark.parametrize(("entity", "item", "code", "message", "op"), NOT_TAGGABLE)
def test_a_refused_tag_read_the_service_calls_untaggable_is_an_answer_not_a_gap(entity, item, code, message, op):
    entry = _entry(entity)
    # Fill every `from` path the entry's tag call reads so the call is made.
    item = {**{spec["from"]: "x" for spec in entry["tags"]["params"].values() if "from" in spec}, **item}
    tags, slot, _mapping = resolve_node_tags(entry, item, rgta_map={}, client_for=lambda _s: _Refusing(code, message, op))
    assert tags == {}
    assert slot["status"] == "not_taggable"
    assert slot["error_code"] == code


def test_an_unlisted_refusal_of_a_tag_read_is_still_a_failed_read():
    entry = _entry("appconfig_extension")
    tags, slot, _ = resolve_node_tags(
        entry, {"Arn": "x"}, rgta_map={}, client_for=lambda _s: _Refusing("BadRequestException", "something else entirely", "ListTagsForResource")
    )
    assert slot["status"] == "error"
    assert not isinstance(tags, dict)


def test_the_ledger_keeps_the_error_code_of_a_refused_call():
    ledger = CallLedger()
    context = {"_tap_audit": {"service": "appconfig", "operation": "ListTagsForResource"}}
    exc = SimpleNamespace(response={"Error": {"Code": "BadRequestException"}, "ResponseMetadata": {"HTTPStatusCode": 400}})
    ledger._after_call_error(exception=exc, context=context)
    assert ledger.entries[-1]["error_code"] == "BadRequestException"


def test_a_path_can_take_the_first_element_of_a_list():
    assert eval_path({"Attachments": [{"State": "available"}, {"State": "x"}]}, "Attachments[].State|first") == "available"
    assert eval_path({"Attachments": []}, "Attachments[].State|first") is None


def test_a_field_can_read_the_region_the_item_was_listed_in():
    node = project_item(_entry("vpc_endpoint"), {"VpcEndpointId": "vpce-0123456789abcdef0"}, {"region": "us-gov-west-1"})
    assert node.fields["region"] == "us-gov-west-1"


def test_the_unmapped_fields_now_read_their_source():
    assert project_item(_entry("acm_certificate"), {"CertificateArn": "a", "Type": "AMAZON_ISSUED"}).fields["type"] == "AMAZON_ISSUED"
    igw = project_item(_entry("internet_gateway"), {"InternetGatewayId": "igw-1", "Attachments": [{"VpcId": "v", "State": "available"}]})
    assert igw.fields["state"] == "available"


@pytest.mark.parametrize(
    ("slot", "expected"),
    [
        ({"status": "ok", "data": {"Status": "Enabled"}}, "Enabled"),
        ({"status": "ok", "data": {}}, ""),
        ({"status": "denied"}, None),
        (None, None),
    ],
)
def test_bucket_versioning_tells_never_enabled_from_unread(slot, expected):
    assert customfns.bucket_versioning(slot) == expected


@pytest.mark.parametrize(
    ("slot", "expected"),
    [
        ({"status": "ok", "data": {"ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}]}}}, "aws:kms"),
        ({"status": "absent"}, ""),
        ({"status": "denied"}, None),
    ],
)
def test_bucket_encryption_tells_unconfigured_from_unread(slot, expected):
    assert customfns.bucket_encryption(slot) == expected


class _Elbv2:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def can_paginate(self, _m: str) -> bool:
        return False

    def describe_target_groups(self, **_kw: Any) -> Any:
        if self.fail:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "DescribeTargetGroups")
        return {"TargetGroups": [{"TargetGroupArn": "tg1"}]}

    def describe_target_health(self, **_kw: Any) -> Any:
        targets = ["i-0abc", "10.0.0.5", "arn:aws-us-gov:lambda:us-gov-west-1:111122223333:function:f", "i-0abc"]
        return {"TargetHealthDescriptions": [{"Target": {"Id": t}} for t in targets]}


def test_a_load_balancer_routes_to_the_instances_and_functions_in_its_target_groups():
    item = customfns._with_routed_targets({}, _Elbv2(), "lb-arn")
    assert item["_target_instance_ids"] == ["i-0abc"]
    assert item["_target_lambda_arns"] == ["arn:aws-us-gov:lambda:us-gov-west-1:111122223333:function:f"]
    assert item["_edge_reads"]["_target_instance_ids"] == "complete"


def test_a_target_read_that_failed_is_not_an_absence():
    item = customfns._with_routed_targets({}, _Elbv2(fail=True), "lb-arn")
    assert item["_target_instance_ids"] == []
    assert item["_edge_reads"]["_target_instance_ids"] == "failed"


def test_the_sibling_arn_transforms_build_the_target_keys_from_the_referring_arn():
    registry: TransformRegistry = build_transform_registry("aws-us-gov")
    source = "arn:aws-us-gov:rds:us-gov-west-1:111122223333:snapshot:s1"
    assert registry.get("rds_instance_arn")("db1", source_key=source) == "arn:aws-us-gov:rds:us-gov-west-1:111122223333:db:db1"
    assert registry.get("rds_cluster_arn")("c1", source_key=source) == "arn:aws-us-gov:rds:us-gov-west-1:111122223333:cluster:c1"
    cache = "arn:aws-us-gov:elasticache:us-gov-west-1:111122223333:cluster:c"
    assert registry.get("elasticache_subnet_group_arn")("g", source_key=cache) == "arn:aws-us-gov:elasticache:us-gov-west-1:111122223333:subnetgroup:g"
    assert registry.get("rds_instance_arn")("db1", source_key="not-an-arn") is None


def test_the_listener_edge_reaches_a_network_load_balancer_by_its_dns_name():
    edges = {(e["value_path"], e["target_type"]) for e in _entry("elb_listener")["edges"]}
    assert ("_elb_dns_name", "aws_core__aws_elb") in edges


def test_every_nullable_column_accepts_null_in_both_of_its_schemas():
    """Unobserved is null (req-aws-core-fields-10): a column that may be null must pass service validation as null,
    enum and all; a schema that still says "string" or lists no null in its enum would reject the value the column holds."""
    import jsonschema
    from django.apps import apps

    rejected = []
    for model in apps.get_app_config("aws_core").get_models():
        if model._meta.model_name.startswith("historical") or not hasattr(model, "FIELD_CRUD_SCHEMA"):
            continue
        for column in model._meta.concrete_fields:
            if not column.null or column.name in ("tags", "configuration"):
                continue
            schemas = {
                "crud": model.FIELD_CRUD_SCHEMA.get(column.name),
                "validation": (model.FIELD_VALIDATION_SCHEMA.get(column.name) or {}).get("schema"),
            }
            for kind, schema in schemas.items():
                try:
                    jsonschema.validate(None, schema if schema is not None else {"type": "null"})
                    if schema is None:
                        rejected.append(f"{model.__name__}.{column.name} has no {kind} schema")
                except jsonschema.ValidationError:
                    rejected.append(f"{model.__name__}.{column.name} {kind}")
    assert not rejected, rejected


def test_the_regional_fields_that_were_never_filled_now_read_the_listing_region():
    for entity in ("codebuild_project", "dx_connection", "transit_gateway", "vpc_endpoint_service"):
        assert _entry(entity)["fields"]["region"] == "$region", entity
