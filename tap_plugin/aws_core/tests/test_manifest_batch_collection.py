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
    "aws_core__aws_eks_cluster": (
        {
            "arn": f"arn:aws:eks:us-east-1:{ACCOUNT}:cluster/prod",
            "name": "prod",
            "status": "ACTIVE",
            "version": "1.31",
            "endpoint": "https://ABC.gr7.us-east-1.eks.amazonaws.com",
            "resourcesVpcConfig": {"subnetIds": ["subnet-0a1", "subnet-0a2"], "endpointPublicAccess": True},
            "tags": {"owner": "net-team"},
        },
        {"name": "prod", "status": "ACTIVE", "kubernetes_version": "1.31"},
    ),
    "aws_core__aws_rds_instance": (
        {
            "DBInstanceIdentifier": "db1",
            "DBInstanceArn": f"arn:aws:rds:us-east-1:{ACCOUNT}:db:db1",
            "Engine": "postgres",
            "EngineVersion": "16.4",
            "DBInstanceClass": "db.t3.micro",
            "DBInstanceStatus": "available",
            "MultiAZ": True,
            "StorageEncrypted": True,
            "PubliclyAccessible": False,
            "DeletionProtection": True,
            "IAMDatabaseAuthenticationEnabled": True,
            "BackupRetentionPeriod": 7,
            "KmsKeyId": KEY_ARN,
            "DBSubnetGroup": {"Subnets": [{"SubnetIdentifier": "subnet-0a1"}]},
            "PendingModifiedValues": {"MasterUserPassword": "never-stored"},
            "TagList": TAGS,
        },
        {
            "db_instance_id": "db1",
            "engine": "postgres",
            "multi_az": True,
            "encrypted": True,
            "publicly_accessible": False,
            "deletion_protection": True,
            "iam_database_auth_enabled": True,
            "backup_retention_days": 7,
        },
    ),
    "aws_core__aws_elasticache_cluster": (
        {
            "CacheClusterId": "cache1",
            "ARN": f"arn:aws:elasticache:us-east-1:{ACCOUNT}:cluster:cache1",
            "Engine": "redis",
            "EngineVersion": "7.1",
            "CacheNodeType": "cache.t3.micro",
            "NumCacheNodes": 1,
            "CacheClusterStatus": "available",
        },
        {"cluster_id": "cache1", "engine": "redis", "node_type": "cache.t3.micro", "num_nodes": 1},
    ),
    "aws_core__aws_elasticsearch_domain": (
        {
            "DomainName": "logs",
            "ARN": f"arn:aws:es:us-east-1:{ACCOUNT}:domain/logs",
            "ElasticsearchVersion": "7.10",
            "ElasticsearchClusterConfig": {"InstanceType": "m5.large.elasticsearch", "InstanceCount": 3},
            "EncryptionAtRestOptions": {"Enabled": True},
            "VPCOptions": {"SubnetIds": ["subnet-0a1"]},
            "AccessPolicies": "{}",
        },
        {"name": "logs", "node_type": "m5.large.elasticsearch", "instance_count": 3, "encrypted": True},
    ),
    "aws_core__aws_ecr_repository": (
        {
            "repositoryName": "app",
            "repositoryArn": f"arn:aws:ecr:us-east-1:{ACCOUNT}:repository/app",
            "repositoryUri": f"{ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com/app",
        },
        {"name": "app", "repository_uri": f"{ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com/app"},
    ),
    "aws_core__aws_sagemaker_endpoint": (
        {
            "EndpointName": "m1",
            "EndpointArn": f"arn:aws:sagemaker:us-east-1:{ACCOUNT}:endpoint/m1",
            "EndpointStatus": "InService",
        },
        {"name": "m1", "status": "InService"},
    ),
    "aws_core__aws_network_firewall": (
        {
            "FirewallName": "edge",
            "FirewallArn": f"arn:aws:network-firewall:us-east-1:{ACCOUNT}:firewall/edge",
            "SubnetMappings": [{"SubnetId": "subnet-0a1"}],
            "_status": "READY",
            "Tags": TAGS,
        },
        {"name": "edge", "status": "READY"},
    ),
    "aws_core__aws_ssm_parameter": (
        {
            "Name": "/app/db/url",
            "ARN": f"arn:aws:ssm:us-east-1:{ACCOUNT}:parameter/app/db/url",
            "Type": "SecureString",
            "Tier": "Standard",
        },
        {"name": "/app/db/url", "type": "SecureString", "tier": "Standard"},
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
        payload = node_envelope(
            project_item(entry, item), {}, _read_tags(entry, item), persist_configuration=entry["persist_configuration"]
        )["node"]
        schema = _create_verb_schema(_model(entity_type))
        jsonschema.validate(_prepare_null_payload(payload, schema), schema)
        assert payload["tags"] == {"owner": "net-team"}

    def test_the_tags_are_read_by_a_declared_lane(self, entity_type: str) -> None:
        tags = _entry(entity_type)["tags"]
        if tags["source"] == "rgta":
            # Joined by ARN from the region's one sweep; the item must carry the ARN it is joined on.
            item, _ = CASES[entity_type]
            assert eval_path(item, tags["arn_from"]), tags
            return
        assert tags["source"] == "field"
        assert (tags["from"], tags["shape"]) in (
            ("Tags[]", "list_kv"),
            ("TagList", "list_kv"),
            ("_tags", "map"),
            ("tags", "map"),
        )

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
        envelope = node_envelope(node, {}, {}, persist_configuration=entry["persist_configuration"])["node"]
        assert bool(envelope["configuration"]) is entry["persist_configuration"]
        if not entry["persist_configuration"]:
            assert envelope["configuration"] == {}
            assert "never-stored" not in json.dumps(envelope, default=str)


def _read_tags(entry: dict[str, Any], item: dict[str, Any]) -> dict[str, str]:
    """The tags the entry's lane would resolve for ``item``: the item's own, or the sweep's map for an rgta lane."""
    block = entry["tags"]
    if block["source"] == "rgta":
        return {"owner": "net-team"}
    return normalize_tags(eval_path(item, block["from"]), block["shape"])


@pytest.mark.parametrize("entry", manifest_entries(), ids=lambda e: e["entity_type"])
def test_every_collected_model_declares_the_configuration_the_envelope_always_carries(entry: dict[str, Any]) -> None:
    """``node_envelope`` writes ``configuration`` on every node (the full envelope, or ``{}``), so a model
    without the field has its whole batch rejected at import, as v0.4.0 did for ``tags``."""
    model = _model(entry["entity_type"])
    assert "configuration" in model.FIELD_CRUD_SCHEMA and "configuration" in model.FIELD_VALIDATION_SCHEMA
    assert any(f.name == "configuration" for f in model._meta.get_fields())
