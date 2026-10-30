"""Collection of the types added from existing models, one canned AWS item per type.

For each type: the item projects to the model's typed fields, the node payload imports under the model's
create schema (``additionalProperties: false``, the v0.4.0 failure), the tags read as declared, and every edge
rule names a declared edge type that allows the pair. Fake items, no network. Add a case here with each type a
manifest entry is written for.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from django.apps import apps
from tap_plugin.aws_core.collectors.boto3_collector.batch import node_envelope
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.paths import eval_path
from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
from tap_plugin.aws_core.collectors.boto3_collector.tags import normalize_tags
from tap_plugin.aws_core.tests.test_trial_run_live import _create_verb_schema, _prepare_null_payload

ACCOUNT = "123456789012"
KEY_ARN = f"arn:aws:kms:us-east-1:{ACCOUNT}:key/1234abcd-12ab-34cd-56ef-1234567890ab"
TAGS = [{"Key": "owner", "Value": "net-team"}]

# entity_type -> (raw item, typed fields the entry must project)
CASES: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "aws_core__aws_elastic_ip": (
        {"AllocationId": "eipalloc-0a1", "PublicIp": "203.0.113.7", "AssociationId": "eipassoc-1", "Tags": TAGS},
        {"allocation_id": "eipalloc-0a1", "public_ip": "203.0.113.7", "association_id": "eipassoc-1"},
    ),
    "aws_core__aws_internet_gateway": (
        {"InternetGatewayId": "igw-0a1", "Attachments": [{"VpcId": "vpc-0a1", "State": "available"}], "Tags": TAGS},
        {"igw_id": "igw-0a1"},
    ),
    "aws_core__aws_nat_gateway": (
        {
            "NatGatewayId": "nat-0a1",
            "SubnetId": "subnet-0a1",
            "State": "available",
            "ConnectivityType": "public",
            "Tags": TAGS,
        },
        {"nat_gateway_id": "nat-0a1", "state": "available", "connectivity_type": "public"},
    ),
    "aws_core__aws_network_acl": (
        {"NetworkAclId": "acl-0a1", "VpcId": "vpc-0a1", "IsDefault": True, "Entries": [], "Tags": TAGS},
        {"network_acl_id": "acl-0a1", "is_default": True},
    ),
    "aws_core__aws_route_table": (
        {"RouteTableId": "rtb-0a1", "VpcId": "vpc-0a1", "Routes": [], "Tags": TAGS},
        {"route_table_id": "rtb-0a1"},
    ),
    "aws_core__aws_ebs_volume": (
        {
            "VolumeId": "vol-0a1",
            "VolumeType": "gp3",
            "Size": 100,
            "State": "in-use",
            "Encrypted": True,
            "KmsKeyId": KEY_ARN,
            "Tags": TAGS,
        },
        {"volume_id": "vol-0a1", "volume_type": "gp3", "size_gb": 100, "state": "in-use", "encrypted": True},
    ),
    "aws_core__aws_alb": (
        {
            "LoadBalancerArn": f"arn:aws:elasticloadbalancing:us-east-1:{ACCOUNT}:loadbalancer/app/web/50dc6c495c0c9188",
            "LoadBalancerName": "web",
            "DNSName": "web-1.us-east-1.elb.amazonaws.com",
            "Scheme": "internet-facing",
            "Type": "application",
            "_state": "active",
            "_subnet_ids": ["subnet-0a1", "subnet-0a2"],
            "_tags": {"owner": "net-team"},
        },
        {"name": "web", "dns_name": "web-1.us-east-1.elb.amazonaws.com", "scheme": "internet-facing", "state": "active"},
    ),
    "aws_core__aws_elb": (
        {
            "LoadBalancerName": "legacy",
            "DNSName": "legacy-1.us-east-1.elb.amazonaws.com",
            "Scheme": "internal",
            "_lb_type": "classic",
            "_subnet_ids": ["subnet-0a1"],
            "_tags": {"owner": "net-team"},
        },
        {"name": "legacy", "dns_name": "legacy-1.us-east-1.elb.amazonaws.com", "scheme": "internal", "lb_type": "classic"},
    ),
    "aws_core__aws_target_group": (
        {
            "TargetGroupArn": f"arn:aws:elasticloadbalancing:us-east-1:{ACCOUNT}:targetgroup/web/73e2d6bc24d8a067",
            "TargetGroupName": "web",
            "Protocol": "HTTPS",
            "Port": 443,
            "TargetType": "ip",
            "HealthCheckPath": "/healthz",
            "VpcId": "vpc-0a1",
            "_tags": {"owner": "net-team"},
        },
        {"name": "web", "protocol": "HTTPS", "port": 443, "target_type": "ip", "health_check_path": "/healthz"},
    ),
    "aws_core__aws_vpc_endpoint": (
        {
            "VpcEndpointId": "vpce-0a1b2c3d4e5f60718",
            "VpcEndpointType": "Interface",
            "ServiceName": "com.amazonaws.us-east-1.s3",
            "PrivateDnsEnabled": True,
            "VpcId": "vpc-0a1",
            "SubnetIds": ["subnet-0a1", "subnet-0a2"],
            "PolicyDocument": '{"Statement": []}',
            "Tags": TAGS,
        },
        {
            "vpc_endpoint_id": "vpce-0a1b2c3d4e5f60718",
            "endpoint_type": "Interface",
            "service_name": "com.amazonaws.us-east-1.s3",
            "private_dns_enabled": True,
        },
    ),
}


def _entry(entity_type: str) -> dict[str, Any]:
    return next(e for e in manifest_entries() if e["entity_type"] == entity_type)


def _model(entity_type: str) -> type:
    return next(m for m in apps.get_app_config("aws_core").get_models() if getattr(m, "ENTITY_TYPE", "") == entity_type)


def _edge_json(slug: str) -> dict[str, Any]:
    path = Path(__file__).resolve().parent.parent / "edges" / f"{slug.removesuffix('__aws_core')}.edge.json"
    return json.loads(path.read_text())  # type: ignore[no-any-return]


@pytest.mark.parametrize("entity_type", sorted(CASES))
class TestBatchTypes:
    def test_the_item_projects_to_the_typed_fields(self, entity_type: str) -> None:
        item, expected = CASES[entity_type]
        node = project_item(_entry(entity_type), item)
        for field, value in expected.items():
            assert node.fields[field] == value, field

    def test_the_payload_imports_under_the_model_schema(self, entity_type: str) -> None:
        item, _ = CASES[entity_type]
        entry = _entry(entity_type)
        tags = normalize_tags(eval_path(item, entry["tags"]["from"]), entry["tags"]["shape"])
        payload = node_envelope(
            project_item(entry, item), {}, tags, persist_configuration=entry["persist_configuration"]
        )["node"]
        schema = _create_verb_schema(_model(entity_type))
        jsonschema.validate(_prepare_null_payload(payload, schema), schema)
        assert payload["tags"] == {"owner": "net-team"}

    def test_the_tags_are_read_from_the_item_with_no_second_fetch(self, entity_type: str) -> None:
        tags = _entry(entity_type)["tags"]
        assert tags["source"] == "field"
        assert (tags["from"], tags["shape"]) in (("Tags[]", "list_kv"), ("_tags", "map"))

    def test_every_edge_rule_resolves_and_names_an_edge_that_allows_the_pair(self, entity_type: str) -> None:
        item, _ = CASES[entity_type]
        for rule in _entry(entity_type).get("edges", []):
            assert eval_path(item, rule["value_path"]), rule
            edge = _edge_json(rule["edge_type"])
            assert entity_type in edge["sources"], (entity_type, rule["edge_type"])
            assert rule["target_type"] in edge["targets"], (entity_type, rule["edge_type"])

    def test_configuration_is_stored_only_when_the_entry_says_so(self, entity_type: str) -> None:
        item, _ = CASES[entity_type]
        entry = _entry(entity_type)
        node = project_item(entry, item)
        stored = node_envelope(node, {}, {}, persist_configuration=True)["node"]["configuration"]
        assert stored and node_envelope(node, {}, {}, persist_configuration=False)["node"]["configuration"] == {}
        assert entry["persist_configuration"] is True


@pytest.mark.parametrize("entry", manifest_entries(), ids=lambda e: e["entity_type"])
def test_every_collected_model_declares_the_configuration_the_envelope_always_carries(entry: dict[str, Any]) -> None:
    """``node_envelope`` writes ``configuration`` on every node (the full envelope, or ``{}``), so a model
    without the field has its whole batch rejected at import, as v0.4.0 did for ``tags``."""
    model = _model(entry["entity_type"])
    assert "configuration" in model.FIELD_CRUD_SCHEMA and "configuration" in model.FIELD_VALIDATION_SCHEMA
    assert any(f.name == "configuration" for f in model._meta.get_fields())
