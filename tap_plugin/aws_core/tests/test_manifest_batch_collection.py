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

# Edge types whose source (or target) list is open by design, with the ends left open.
OPEN_ENDED_EDGES: dict[str, tuple[str, ...]] = {"INVOKES_LAMBDA__aws_core": ("sources",)}

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
    "aws_core__aws_dx_connection": (
        {
            "connectionId": "dxcon-fg5678gh",
            "connectionName": "colo-1",
            "location": "EqDC2",
            "bandwidth": "10Gbps",
            "tags": [{"key": "owner", "value": "net-team"}],
        },
        {"connection_id": "dxcon-fg5678gh", "name": "colo-1", "location": "EqDC2", "bandwidth": "10Gbps"},
    ),
    "aws_core__aws_dx_virtual_interface": (
        {
            "virtualInterfaceId": "dxvif-ffhhk74f",
            "virtualInterfaceName": "vif-1",
            "virtualInterfaceType": "private",
            "vlan": 101,
            "asn": 65001,
            "connectionId": "dxcon-fg5678gh",
            "directConnectGatewayId": "5f294f92-bafb-4011-916d-9b0bb4a1b2c3",
            "authKey": "never-stored",
            "tags": [{"key": "owner", "value": "net-team"}],
        },
        {"virtual_interface_type": "private", "vlan": 101, "customer_asn": 65001, "name": "vif-1"},
    ),
    "aws_core__aws_dx_gateway": (
        {
            "directConnectGatewayId": "5f294f92-bafb-4011-916d-9b0bb4a1b2c3",
            "directConnectGatewayName": "gw-1",
            "amazonSideAsn": 64512,
            "_tags": {"owner": "net-team"},
        },
        {"name": "gw-1", "amazon_side_asn": 64512},
    ),
    "aws_core__aws_vpc_endpoint_service": (
        {
            "ServiceId": "vpce-svc-0123456789abcdef0",
            "ServiceName": "com.amazonaws.vpce.us-east-1.vpce-svc-0123456789abcdef0",
            "AcceptanceRequired": True,
            "PrivateDnsName": "svc.example.com",
            "Tags": TAGS,
        },
        {"service_id": "vpce-svc-0123456789abcdef0", "acceptance_required": True, "private_dns_name": "svc.example.com"},
    ),
    "aws_core__aws_route53_resolver_firewall_rule_group": (
        {"Id": "rslvr-frg-0123456789abcdef", "Name": "egress", "Arn": f"arn:aws:route53resolver:us-east-1:{ACCOUNT}:firewall-rule-group/rslvr-frg-0123456789abcdef"},
        {"name": "egress", "rule_group_id": "rslvr-frg-0123456789abcdef"},
    ),
    "aws_core__aws_transit_gateway": (
        {
            "TransitGatewayId": "tgw-0a1b2c3d4e5f60718",
            "OwnerId": ACCOUNT,
            "Options": {"AmazonSideAsn": 64512},
            "_auto_accept_shared_attachments": False,
            "_default_route_table_association": True,
            "_default_route_table_propagation": True,
            "Tags": [{"Key": "owner", "Value": "net-team"}, {"Key": "Name", "Value": "hub"}],
        },
        {
            "transit_gateway_id": "tgw-0a1b2c3d4e5f60718",
            "owner_account_id": ACCOUNT,
            "amazon_side_asn": 64512,
            "auto_accept_shared_attachments": False,
            "default_route_table_association": True,
            "name": "hub",
        },
    ),
    "aws_core__aws_transit_gateway_attachment": (
        {
            "TransitGatewayAttachmentId": "tgw-attach-0a1b2c3d4e5f60718",
            "TransitGatewayId": "tgw-0a1b2c3d4e5f60718",
            "ResourceType": "vpc",
            "ResourceId": "vpc-0a1",
            "ResourceOwnerId": ACCOUNT,
            "_vpc_id": "vpc-0a1",
            "_dx_gateway_id": None,
            "_peer_transit_gateway_id": None,
            "Tags": TAGS,
        },
        {"attachment_id": "tgw-attach-0a1b2c3d4e5f60718", "resource_type": "vpc", "resource_owner_account_id": ACCOUNT},
    ),
    "aws_core__aws_acm_private_ca": (
        {
            "Arn": f"arn:aws:acm-pca:us-east-1:{ACCOUNT}:certificate-authority/12345678-1234-1234-1234-123456789012",
            "Type": "SUBORDINATE",
            "Status": "ACTIVE",
            "UsageMode": "GENERAL_PURPOSE",
            "CertificateAuthorityConfiguration": {"KeyAlgorithm": "RSA_2048", "Subject": {"CommonName": "Issuing CA 1"}},
        },
        {"ca_type": "SUBORDINATE", "key_algorithm": "RSA_2048", "status": "ACTIVE", "subject_common_name": "Issuing CA 1", "name": "Issuing CA 1"},
    ),
    "aws_core__aws_codebuild_project": (
        {
            "name": "build",
            "arn": f"arn:aws:codebuild:us-east-1:{ACCOUNT}:project/build",
            "source": {"type": "GITHUB"},
            "environment": {"image": "aws/codebuild/standard:7.0", "computeType": "BUILD_GENERAL1_SMALL", "privilegedMode": False},
            "serviceRole": f"arn:aws:iam::{ACCOUNT}:role/build",
            "_vpc_attached": False,
            "tags": [{"key": "owner", "value": "net-team"}],
        },
        {"name": "build", "environment_image": "aws/codebuild/standard:7.0", "source_type": "GITHUB", "vpc_attached": False, "privileged_mode": False},
    ),
    "aws_core__aws_codepipeline_pipeline": (
        {
            "name": "release",
            "roleArn": f"arn:aws:iam::{ACCOUNT}:role/release",
            "pipelineType": "V2",
            "executionMode": "QUEUED",
            "_arn": f"arn:aws:codepipeline:us-east-1:{ACCOUNT}:release",
            "_stage_names": ["Source", "Build"],
            "_codebuild_project_arns": [f"arn:aws:codebuild:us-east-1:{ACCOUNT}:project/build"],
            "_s3_source_bucket_arns": ["arn:aws:s3:::src"],
            "_tags": {"owner": "net-team"},
        },
        {"name": "release", "stage_names": ["Source", "Build"], "pipeline_type": "V2", "execution_mode": "QUEUED"},
    ),
    "aws_core__aws_kms_alias": (
        {
            "AliasName": "alias/app",
            "AliasArn": f"arn:aws:kms:us-east-1:{ACCOUNT}:alias/app",
            "TargetKeyId": "1234abcd-12ab-34cd-56ef-1234567890ab",
            "_target_key_arn": KEY_ARN,
        },
        {"name": "alias/app", "alias_name": "alias/app", "target_key_id": "1234abcd-12ab-34cd-56ef-1234567890ab"},
    ),
    "aws_core__aws_cloudtrail_event_data_store": (
        {
            "EventDataStoreArn": f"arn:aws:cloudtrail:us-east-1:{ACCOUNT}:eventdatastore/abc",
            "Name": "audit",
            "_name": "audit",
            "Status": "ENABLED",
            "MultiRegionEnabled": True,
            "OrganizationEnabled": False,
            "RetentionPeriod": 2557,
            "TerminationProtectionEnabled": True,
            "_tags": {"owner": "net-team"},
        },
        {"name": "audit", "status": "ENABLED", "multi_region_enabled": True, "retention_period_days": 2557, "termination_protection_enabled": True},
    ),
    "aws_core__aws_cloudtrail_channel": (
        {"ChannelArn": f"arn:aws:cloudtrail:us-east-1:{ACCOUNT}:channel/abc", "Name": "partner", "_name": "partner", "_tags": {"owner": "net-team"}},
        {"name": "partner"},
    ),
    "aws_core__aws_cloudtrail_dashboard": (
        {"DashboardArn": f"arn:aws:cloudtrail:us-east-1:{ACCOUNT}:dashboard/abc", "Type": "CUSTOM", "_name": "abc", "_tags": {"owner": "net-team"}},
        {"dashboard_type": "CUSTOM"},
    ),
    "aws_core__aws_config_aggregation_authorization": (
        {
            "AggregationAuthorizationArn": f"arn:aws:config:us-east-1:{ACCOUNT}:aggregation-authorization/999988887777/us-east-1",
            "AuthorizedAccountId": "999988887777",
            "AuthorizedAwsRegion": "us-east-1",
        },
        {"authorized_account_id": "999988887777", "authorized_region": "us-east-1"},
    ),
    "aws_core__aws_config_organization_rule": (
        {
            "OrganizationConfigRuleName": "org-s3-public",
            "OrganizationConfigRuleArn": f"arn:aws:config:us-east-1:{ACCOUNT}:organization-config-rule/org-s3-public-abc",
            "ExcludedAccounts": ["999988887777"],
            "_last_update_time": "2026-10-01T00:00:00Z",
        },
        {"name": "org-s3-public", "excluded_accounts": ["999988887777"], "last_update_time": "2026-10-01T00:00:00Z"},
    ),
    "aws_core__aws_config_organization_conformance_pack": (
        {
            "OrganizationConformancePackName": "org-pack",
            "OrganizationConformancePackArn": f"arn:aws:config:us-east-1:{ACCOUNT}:organization-conformance-pack/org-pack-abc",
            "ExcludedAccounts": [],
            "DeliveryS3Bucket": "awsconfigconforms-org",
            "_last_update_time": "2026-10-01T00:00:00Z",
        },
        {"name": "org-pack", "excluded_accounts": [], "delivery_s3_bucket": "awsconfigconforms-org"},
    ),
    "aws_core__aws_config_stored_query": (
        {"QueryId": "q-1", "QueryArn": f"arn:aws:config:us-east-1:{ACCOUNT}:stored-query/open-sgs/q-1", "QueryName": "open-sgs"},
        {"name": "open-sgs", "query_id": "q-1"},
    ),
    "aws_core__aws_identity_center_user": (
        {
            "IdentityStoreId": "d-1234567890",
            "UserId": "90671a2b-1111-2222-3333-444455556666",
            "UserName": "alice@example.com",
            "DisplayName": "Alice Example",
            "_key": "d-1234567890:90671a2b-1111-2222-3333-444455556666",
        },
        {"identity_store_id": "d-1234567890", "user_id": "90671a2b-1111-2222-3333-444455556666", "user_name": "alice@example.com", "display_name": "Alice Example"},
    ),
    "aws_core__aws_identity_center_application": (
        {
            "ApplicationArn": "arn:aws:sso::123456789012:application/ssoins-1/apl-1",
            "InstanceArn": "arn:aws:sso:::instance/ssoins-1",
            "ApplicationProviderArn": "arn:aws:sso::aws:applicationProvider/custom",
            "Name": "wiki",
            "Status": "ENABLED",
        },
        {"name": "wiki", "status": "ENABLED", "instance_arn": "arn:aws:sso:::instance/ssoins-1"},
    ),
    "aws_core__aws_identity_center_application_assignment": (
        {
            "ApplicationArn": "arn:aws:sso::123456789012:application/ssoins-1/apl-1",
            "PrincipalType": "GROUP",
            "PrincipalId": "g-1",
            "_key": "arn:aws:sso::123456789012:application/ssoins-1/apl-1|GROUP|g-1",
        },
        {"principal_type": "GROUP", "principal_id": "g-1"},
    ),
    "aws_core__aws_access_analyzer_archive_rule": (
        {
            "ruleName": "ignore-known",
            "filter": {"resourceType": {"eq": ["AWS::S3::Bucket"]}},
            "_analyzer_arn": f"arn:aws:access-analyzer:us-east-1:{ACCOUNT}:analyzer/acct",
            "_arn": f"arn:aws:access-analyzer:us-east-1:{ACCOUNT}:analyzer/acct/archive-rule/ignore-known",
            "_updated_at": "2026-10-01T00:00:00Z",
        },
        {"name": "ignore-known", "rule_name": "ignore-known", "filter": {"resourceType": {"eq": ["AWS::S3::Bucket"]}}},
    ),
    "aws_core__aws_config_connector": (
        {"arn": f"arn:aws:config:us-east-1:{ACCOUNT}:connector/c1", "name": "azure-prod", "provider": "AZURE", "tenantIdentifier": "tenant-1"},
        {"name": "azure-prod", "provider": "AZURE", "tenant_identifier": "tenant-1"},
    ),
    "aws_core__aws_sns_topic": (
        {'TopicArn': 'arn:aws:sns:us-east-1:123456789012:alerts', '_name': 'alerts', 'Attributes': {'FifoTopic': 'false'}, '_kms_master_key_id': 'arn:aws:kms:us-east-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab', '_fifo_topic': False, '_subscriptions_confirmed': 3, '_subscriptions_pending': 0, '_tags': {'owner': 'net-team'}},
        {'name': 'alerts', 'topic_arn': 'arn:aws:sns:us-east-1:123456789012:alerts', 'fifo_topic': False, 'subscriptions_confirmed': 3, 'subscriptions_pending': 0},
    ),
    "aws_core__aws_sns_subscription": (
        {'SubscriptionArn': 'arn:aws:sns:us-east-1:123456789012:alerts:11111111-2222-3333-4444-555555555555', 'TopicArn': 'arn:aws:sns:us-east-1:123456789012:alerts', 'Protocol': 'https', 'Owner': '123456789012'},
        {'protocol': 'https', 'owner': '123456789012'},
    ),
    "aws_core__aws_eventbridge_event_bus": (
        {'Name': 'default', 'Arn': 'arn:aws:events:us-east-1:123456789012:event-bus/default', 'Policy': '{}'},
        {'name': 'default', 'bus_arn': 'arn:aws:events:us-east-1:123456789012:event-bus/default'},
    ),
    "aws_core__aws_eventbridge_archive": (
        {'ArchiveName': 'all', 'EventSourceArn': 'arn:aws:events:us-east-1:123456789012:event-bus/default', 'State': 'ENABLED', 'RetentionDays': 30, '_arn': 'arn:aws:events:us-east-1:123456789012:archive/all'},
        {'name': 'all', 'state': 'ENABLED', 'retention_days': 30},
    ),
    "aws_core__aws_eventbridge_connection": (
        {'ConnectionArn': 'arn:aws:events:us-east-1:123456789012:connection/crm/abc', 'Name': 'crm', 'AuthorizationType': 'API_KEY', 'ConnectionState': 'AUTHORIZED'},
        {'name': 'crm', 'authorization_type': 'API_KEY', 'connection_state': 'AUTHORIZED'},
    ),
    "aws_core__aws_eventbridge_api_destination": (
        {'ApiDestinationArn': 'arn:aws:events:us-east-1:123456789012:api-destination/crm/abc', 'Name': 'crm', 'ApiDestinationState': 'ACTIVE', 'ConnectionArn': 'arn:aws:events:us-east-1:123456789012:connection/crm/abc', 'InvocationEndpoint': 'https://api.example.com/hook', 'HttpMethod': 'POST'},
        {'name': 'crm', 'state': 'ACTIVE', 'http_method': 'POST', 'invocation_endpoint': 'https://api.example.com/hook'},
    ),
    "aws_core__aws_lambda_function_url": (
        {'FunctionUrl': 'https://abc.lambda-url.us-east-1.on.aws/', 'FunctionArn': 'arn:aws:lambda:us-east-1:123456789012:function:fn', 'AuthType': 'NONE', 'InvokeMode': 'BUFFERED', 'Cors': {'AllowOrigins': ['*']}, '_allow_origins': ['*']},
        {'function_url': 'https://abc.lambda-url.us-east-1.on.aws/', 'auth_type': 'NONE', 'cors_allow_origins': ['*']},
    ),
    "aws_core__aws_lambda_layer_version": (
        {'LayerVersionArn': 'arn:aws:lambda:us-east-1:123456789012:layer:deps:3', 'Version': 3, 'CompatibleRuntimes': ['python3.13'], 'CreatedDate': '2026-10-01T00:00:00.000+0000', '_layer_arn': 'arn:aws:lambda:us-east-1:123456789012:layer:deps', '_layer_name': 'deps'},
        {'name': 'deps', 'version': 3, 'compatible_runtimes': ['python3.13']},
    ),
    "aws_core__aws_lambda_code_signing_config": (
        {'CodeSigningConfigArn': 'arn:aws:lambda:us-east-1:123456789012:code-signing-config:csc-0abc', 'CodeSigningPolicies': {'UntrustedArtifactOnDeployment': 'Enforce'}, 'AllowedPublishers': {'SigningProfileVersionArns': ['arn:aws:signer:us-east-1:1:/signing-profiles/p/abc']}},
        {'untrusted_artifact_on_deployment': 'Enforce'},
    ),
    "aws_core__aws_lambda_event_source_mapping": (
        {'UUID': '14e0db71-5d35-4eb5-b481-8945cf9d10c2', 'State': 'Enabled', 'EventSourceArn': 'arn:aws:sqs:us-east-1:123456789012:jobs', 'FunctionArn': 'arn:aws:lambda:us-east-1:123456789012:function:fn', 'BatchSize': 10, '_arn': 'arn:aws:lambda:us-east-1:123456789012:event-source-mapping:14e0db71-5d35-4eb5-b481-8945cf9d10c2'},
        {'state': 'Enabled', 'batch_size': 10},
    ),
    "aws_core__aws_guardduty_filter": (
        {'Name': 'known-scanner', 'Action': 'ARCHIVE', 'Rank': 1, 'DetectorId': '12abc34d567e8fa901bc2d34e56789f0', 'FilterName': 'known-scanner', 'Tags': {'owner': 'net-team'}, '_key': '12abc34d567e8fa901bc2d34e56789f0/filter/known-scanner', '_detector_key': '123456789012:us-east-1:12abc34d567e8fa901bc2d34e56789f0'},
        {'name': 'known-scanner', 'detector_id': '12abc34d567e8fa901bc2d34e56789f0', 'action': 'ARCHIVE', 'rank': 1},
    ),
    "aws_core__aws_guardduty_ip_set": (
        {'Name': 'office', 'Format': 'TXT', 'Location': 'https://s3.amazonaws.com/lists/office.txt', 'Status': 'ACTIVE', 'DetectorId': '12abc34d567e8fa901bc2d34e56789f0', 'IpSetId': 'set-1', 'Tags': {'owner': 'net-team'}, '_key': '12abc34d567e8fa901bc2d34e56789f0/ipset/set-1', '_detector_key': '123456789012:us-east-1:12abc34d567e8fa901bc2d34e56789f0'},
        {'name': 'office', 'detector_id': '12abc34d567e8fa901bc2d34e56789f0', 'status': 'ACTIVE', 'format': 'TXT', 'location': 'https://s3.amazonaws.com/lists/office.txt'},
    ),
    "aws_core__aws_guardduty_threat_intel_set": (
        {'Name': 'office', 'Format': 'TXT', 'Location': 'https://s3.amazonaws.com/lists/office.txt', 'Status': 'ACTIVE', 'DetectorId': '12abc34d567e8fa901bc2d34e56789f0', 'ThreatIntelSetId': 'set-1', 'Tags': {'owner': 'net-team'}, '_key': '12abc34d567e8fa901bc2d34e56789f0/threatintelset/set-1', '_detector_key': '123456789012:us-east-1:12abc34d567e8fa901bc2d34e56789f0'},
        {'name': 'office', 'detector_id': '12abc34d567e8fa901bc2d34e56789f0', 'status': 'ACTIVE', 'format': 'TXT', 'location': 'https://s3.amazonaws.com/lists/office.txt'},
    ),
    "aws_core__aws_guardduty_publishing_destination": (
        {'DestinationId': 'd-1', 'DestinationType': 'S3', 'Status': 'PUBLISHING', 'DestinationProperties': {'DestinationArn': 'arn:aws:s3:::findings', 'KmsKeyArn': 'arn:aws:kms:us-east-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab'}, 'DetectorId': '12abc34d567e8fa901bc2d34e56789f0', 'Tags': {'owner': 'net-team'}, '_key': '12abc34d567e8fa901bc2d34e56789f0/destination/d-1', '_detector_key': '123456789012:us-east-1:12abc34d567e8fa901bc2d34e56789f0'},
        {'detector_id': '12abc34d567e8fa901bc2d34e56789f0', 'destination_type': 'S3', 'status': 'PUBLISHING', 'destination_arn': 'arn:aws:s3:::findings'},
    ),
    "aws_core__aws_guardduty_member": (
        {'AccountId': '999988887777', 'DetectorId': 'd2', 'RelationshipStatus': 'Enabled', 'AdministratorId': '123456789012', 'ParentDetectorId': '12abc34d567e8fa901bc2d34e56789f0', '_key': '12abc34d567e8fa901bc2d34e56789f0/member/999988887777', '_detector_key': '123456789012:us-east-1:12abc34d567e8fa901bc2d34e56789f0'},
        {'account_id': '999988887777', 'relationship_status': 'Enabled', 'administrator_id': '123456789012', 'detector_id': '12abc34d567e8fa901bc2d34e56789f0'},
    ),
    "aws_core__aws_wafv2_web_acl": (
        {'Name': 'edge-acl', 'Id': 'i-1', 'ARN': 'arn:aws:wafv2:us-east-1:123456789012:regional/webacl/edge-acl/i-1', 'Scope': 'REGIONAL', 'DefaultAction': {'Block': {}}, 'Rules': [{'Name': 'r1'}], 'Capacity': 50, 'ManagedByFirewallManager': False, '_arn': 'arn:aws:wafv2:us-east-1:123456789012:regional/webacl/edge-acl/i-1', '_default_action': 'BLOCK', '_rule_count': 1, '_tags': {'owner': 'net-team'}},
        {'name': 'edge-acl', 'scope': 'REGIONAL', 'default_action': 'BLOCK', 'rule_count': 1, 'capacity': 50, 'managed_by_firewall_manager': False},
    ),
    "aws_core__aws_wafv2_rule_group": (
        {'Name': 'shared', 'Id': 'g-1', 'ARN': 'arn:aws:wafv2:us-east-1:123456789012:regional/rulegroup/shared/g-1', 'Scope': 'REGIONAL', 'Rules': [{'Name': 'r1'}, {'Name': 'r2'}], 'Capacity': 100, '_arn': 'arn:aws:wafv2:us-east-1:123456789012:regional/rulegroup/shared/g-1', '_rule_count': 2, '_tags': {'owner': 'net-team'}},
        {'name': 'shared', 'scope': 'REGIONAL', 'rule_count': 2, 'capacity': 100},
    ),
    "aws_core__aws_wafv2_ip_set": (
        {'Name': 'office', 'Id': 's-1', 'ARN': 'arn:aws:wafv2:us-east-1:123456789012:regional/ipset/office/s-1', 'Scope': 'REGIONAL', 'IPAddressVersion': 'IPV4', 'Addresses': ['203.0.113.0/24', '198.51.100.7/32'], '_arn': 'arn:aws:wafv2:us-east-1:123456789012:regional/ipset/office/s-1', '_address_count': 2, '_tags': {'owner': 'net-team'}},
        {'name': 'office', 'scope': 'REGIONAL', 'ip_address_version': 'IPV4', 'address_count': 2},
    ),
    "aws_core__aws_wafv2_regex_pattern_set": (
        {'Name': 'bad-agents', 'Id': 'p-1', 'ARN': 'arn:aws:wafv2:us-east-1:123456789012:regional/regexpatternset/bad-agents/p-1', 'Scope': 'REGIONAL', 'RegularExpressionList': [{'RegexString': 'sqlmap'}], '_arn': 'arn:aws:wafv2:us-east-1:123456789012:regional/regexpatternset/bad-agents/p-1', '_pattern_count': 1, '_tags': {'owner': 'net-team'}},
        {'name': 'bad-agents', 'scope': 'REGIONAL', 'pattern_count': 1},
    ),
    "aws_core__aws_s3_access_point": (
        {'Name': 'ap1', 'Bucket': 'data', 'AccessPointArn': 'arn:aws:s3:us-east-1:123456789012:accesspoint/ap1', 'NetworkOrigin': 'Internet', 'Alias': 'ap1-abc-s3alias', '_account_id': '123456789012', '_is_public': True, '_vpc_id': None, '_bucket_arn': 'arn:aws:s3:::data'},
        {'name': 'ap1', 'bucket': 'data', 'network_origin': 'Internet', 'is_public': True},
    ),
    "aws_core__aws_efs_file_system": (
        {'FileSystemId': 'fs-0a1', 'FileSystemArn': 'arn:aws:elasticfilesystem:us-east-1:123456789012:file-system/fs-0a1', 'Name': 'shared', 'Encrypted': True, 'KmsKeyId': 'arn:aws:kms:us-east-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab', 'PerformanceMode': 'generalPurpose', 'ThroughputMode': 'elastic', 'LifeCycleState': 'available', 'NumberOfMountTargets': 2, 'Tags': [{'Key': 'owner', 'Value': 'net-team'}]},
        {'name': 'shared', 'file_system_id': 'fs-0a1', 'encrypted': True, 'throughput_mode': 'elastic', 'number_of_mount_targets': 2},
    ),
    "aws_core__aws_efs_access_point": (
        {'AccessPointId': 'fsap-0a1', 'AccessPointArn': 'arn:aws:elasticfilesystem:us-east-1:123456789012:access-point/fsap-0a1', 'FileSystemId': 'fs-0a1', 'Name': 'app', 'PosixUser': {'Uid': 1000, 'Gid': 1000}, 'RootDirectory': {'Path': '/app'}, 'LifeCycleState': 'available', 'Tags': [{'Key': 'owner', 'Value': 'net-team'}], '_file_system_arn': 'arn:aws:elasticfilesystem:us-east-1:123456789012:file-system/fs-0a1'},
        {'name': 'app', 'file_system_id': 'fs-0a1', 'posix_uid': 1000, 'root_directory_path': '/app'},
    ),
    "aws_core__aws_efs_mount_target": (
        {'MountTargetId': 'fsmt-0a1', 'FileSystemId': 'fs-0a1', 'SubnetId': 'subnet-0a1', 'VpcId': 'vpc-0a1', 'IpAddress': '10.0.1.5', 'LifeCycleState': 'available', '_file_system_arn': 'arn:aws:elasticfilesystem:us-east-1:123456789012:file-system/fs-0a1'},
        {'file_system_id': 'fs-0a1', 'subnet_id': 'subnet-0a1', 'ip_address': '10.0.1.5'},
    ),
    "aws_core__aws_elb_listener": (
        {'ListenerArn': 'arn:aws:elasticloadbalancing:us-east-1:123456789012:listener/app/web/abc/def', 'LoadBalancerArn': 'arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/web/abc', 'Port': 443, 'Protocol': 'HTTPS', 'SslPolicy': 'ELBSecurityPolicy-TLS13-1-2-2021-06', 'MutualAuthentication': {'Mode': 'off'}, '_certificate_arns': ['arn:aws:acm:us-east-1:123456789012:certificate/abc'], '_action_types': ['forward'], '_alb_arn': 'arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/web/abc', '_tags': {'owner': 'net-team'}},
        {'port': 443, 'protocol': 'HTTPS', 'ssl_policy': 'ELBSecurityPolicy-TLS13-1-2-2021-06', 'action_types': ['forward'], 'mutual_authentication_mode': 'off'},
    ),
    "aws_core__aws_backup_vault": (
        {'BackupVaultName': 'prod', 'BackupVaultArn': 'arn:aws:backup:us-east-1:123456789012:backup-vault:prod', 'EncryptionKeyArn': 'arn:aws:kms:us-east-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab', 'Locked': True, 'MinRetentionDays': 30, 'MaxRetentionDays': 3650, 'NumberOfRecoveryPoints': 12, '_tags': {'owner': 'net-team'}},
        {'name': 'prod', 'locked': True, 'min_retention_days': 30, 'number_of_recovery_points': 12},
    ),
    "aws_core__aws_backup_plan": (
        {'BackupPlanName': 'daily', 'BackupPlanArn': 'arn:aws:backup:us-east-1:123456789012:backup-plan:p-1', 'BackupPlanId': 'p-1', '_rule_count': 2, '_target_vault_arns': ['arn:aws:backup:us-east-1:123456789012:backup-vault:prod'], '_tags': {'owner': 'net-team'}},
        {'name': 'daily', 'plan_id': 'p-1', 'rule_count': 2},
    ),
    "aws_core__aws_backup_framework": (
        {'FrameworkName': 'policy', 'FrameworkArn': 'arn:aws:backup:us-east-1:123456789012:framework:policy-abc', 'DeploymentStatus': 'COMPLETED', 'NumberOfControls': 4, '_tags': {'owner': 'net-team'}},
        {'name': 'policy', 'deployment_status': 'COMPLETED', 'number_of_controls': 4},
    ),
    "aws_core__aws_backup_legal_hold": (
        {'Title': 'case-17', 'LegalHoldArn': 'arn:aws:backup:us-east-1:123456789012:legal-hold:h-1', 'LegalHoldId': 'h-1', 'Status': 'ACTIVE', '_tags': {'owner': 'net-team'}},
        {'name': 'case-17', 'hold_id': 'h-1', 'status': 'ACTIVE'},
    ),
    "aws_core__aws_cognito_identity_pool": (
        {'IdentityPoolId': 'us-east-1:11111111-2222-3333-4444-555555555555', 'IdentityPoolName': 'app', 'AllowUnauthenticatedIdentities': True, 'AllowClassicFlow': False, 'IdentityPoolTags': {'owner': 'net-team'}},
        {'name': 'app', 'allow_unauthenticated_identities': True, 'allow_classic_flow': False},
    ),
    "aws_core__aws_cognito_user_pool_client": (
        {'UserPoolId': 'us-east-1_Abc123', 'ClientId': 'abc123', 'ClientName': 'web', 'ClientSecret': 'never-stored', '_key': 'us-east-1_Abc123:abc123', '_has_secret': True, 'AllowedOAuthFlows': ['code'], 'AllowedOAuthScopes': ['openid'], 'CallbackURLs': ['https://app.example.com/cb'], 'ExplicitAuthFlows': ['ALLOW_USER_SRP_AUTH'], 'PreventUserExistenceErrors': 'ENABLED', 'EnableTokenRevocation': True},
        {'name': 'web', 'user_pool_id': 'us-east-1_Abc123', 'has_secret': True, 'allowed_oauth_flows': ['code'], 'callback_urls': ['https://app.example.com/cb'], 'prevent_user_existence_errors': 'ENABLED'},
    ),
    "aws_core__aws_cognito_identity_provider": (
        {'UserPoolId': 'us-east-1_Abc123', 'ProviderName': 'corp-idp', 'ProviderType': 'SAML', 'ProviderDetails': {'MetadataURL': 'https://idp.example.com/meta'}, '_key': 'us-east-1_Abc123:corp-idp'},
        {'name': 'corp-idp', 'user_pool_id': 'us-east-1_Abc123', 'provider_type': 'SAML'},
    ),
    "aws_core__aws_cognito_user_pool_group": (
        {'UserPoolId': 'us-east-1_Abc123', 'GroupName': 'admins', 'Precedence': 1, 'RoleArn': 'arn:aws:iam::123456789012:role/cognito-admins', '_key': 'us-east-1_Abc123:admins'},
        {'name': 'admins', 'precedence': 1, 'role_arn': 'arn:aws:iam::123456789012:role/cognito-admins'},
    ),
    "aws_core__aws_cognito_user_pool_resource_server": (
        {'UserPoolId': 'us-east-1_Abc123', 'Identifier': 'https://api.example.com', 'Name': 'api', 'Scopes': [{'ScopeName': 'read', 'ScopeDescription': 'read'}], '_key': 'us-east-1_Abc123:https://api.example.com'},
        {'name': 'api', 'user_pool_id': 'us-east-1_Abc123', 'identifier': 'https://api.example.com'},
    ),
    "aws_core__aws_cognito_user_pool_domain": (
        {'UserPoolId': 'us-east-1_Abc123', 'Domain': 'auth.example.com', 'Status': 'ACTIVE', 'CloudFrontDistribution': 'd111.cloudfront.net', 'CustomDomainConfig': {'CertificateArn': 'arn:aws:acm:us-east-1:123456789012:certificate/abc'}, '_key': 'us-east-1_Abc123:auth.example.com'},
        {'name': 'auth.example.com', 'user_pool_id': 'us-east-1_Abc123', 'status': 'ACTIVE', 'certificate_arn': 'arn:aws:acm:us-east-1:123456789012:certificate/abc'},
    ),
    "aws_core__aws_cloudwatch_alarm": (
        {'AlarmName': 'root-login', 'AlarmArn': 'arn:aws:cloudwatch:us-east-1:123456789012:alarm:root-login', 'StateValue': 'OK', 'ActionsEnabled': True, 'MetricName': 'RootUsage', 'Namespace': 'CISBenchmark', 'ComparisonOperator': 'GreaterThanOrEqualToThreshold', 'Threshold': 1.0, 'AlarmActions': ['arn:aws:sns:us-east-1:123456789012:alerts'], '_sns_topic_arns': ['arn:aws:sns:us-east-1:123456789012:alerts']},
        {'name': 'root-login', 'state_value': 'OK', 'actions_enabled': True, 'metric_name': 'RootUsage', 'namespace': 'CISBenchmark'},
    ),
    "aws_core__aws_cloudwatch_composite_alarm": (
        {'AlarmName': 'paging', 'AlarmArn': 'arn:aws:cloudwatch:us-east-1:123456789012:alarm:paging', 'StateValue': 'OK', 'ActionsEnabled': False, 'AlarmRule': 'ALARM(root-login)', 'AlarmActions': ['arn:aws:sns:us-east-1:123456789012:alerts'], '_sns_topic_arns': ['arn:aws:sns:us-east-1:123456789012:alerts']},
        {'name': 'paging', 'actions_enabled': False, 'alarm_rule': 'ALARM(root-login)'},
    ),
    "aws_core__aws_cloudwatch_dashboard": (
        {'DashboardName': 'ops', 'DashboardArn': 'arn:aws:cloudwatch::123456789012:dashboard/ops', 'Size': 2048},
        {'name': 'ops', 'size': 2048},
    ),
    "aws_core__aws_cloudwatch_metric_stream": (
        {'Name': 'to-vendor', 'Arn': 'arn:aws:cloudwatch:us-east-1:123456789012:metric-stream/to-vendor', 'FirehoseArn': 'arn:aws:firehose:us-east-1:123456789012:deliverystream/vendor', 'State': 'running', 'OutputFormat': 'json'},
        {'name': 'to-vendor', 'state': 'running', 'output_format': 'json'},
    ),
    "aws_core__aws_logs_metric_filter": (
        {'filterName': 'root-usage', 'logGroupName': '/aws/cloudtrail', 'filterPattern': '{ $.userIdentity.type = "Root" }', 'metricTransformations': [{'metricName': 'RootUsage', 'metricNamespace': 'CISBenchmark', 'metricValue': '1'}], '_key': '/aws/cloudtrail:root-usage', '_log_group_arn': 'arn:aws:logs:us-east-1:123456789012:log-group:/aws/cloudtrail', '_metric_name': 'RootUsage', '_metric_namespace': 'CISBenchmark'},
        {'name': 'root-usage', 'log_group_name': '/aws/cloudtrail', 'metric_name': 'RootUsage', 'metric_namespace': 'CISBenchmark'},
    ),
    "aws_core__aws_logs_subscription_filter": (
        {'filterName': 'to-siem', 'logGroupName': '/aws/app', 'destinationArn': 'arn:aws:logs:us-east-1:999988887777:destination:siem', 'roleArn': 'arn:aws:iam::123456789012:role/cwl', 'distribution': 'ByLogStream', '_key': '/aws/app:to-siem', '_log_group_arn': 'arn:aws:logs:us-east-1:123456789012:log-group:/aws/app'},
        {'name': 'to-siem', 'log_group_name': '/aws/app', 'destination_arn': 'arn:aws:logs:us-east-1:999988887777:destination:siem', 'distribution': 'ByLogStream'},
    ),
    "aws_core__aws_logs_destination": (
        {'destinationName': 'siem', 'arn': 'arn:aws:logs:us-east-1:123456789012:destination:siem', 'targetArn': 'arn:aws:kinesis:us-east-1:123456789012:stream/logs', 'roleArn': 'arn:aws:iam::123456789012:role/cwl', 'accessPolicy': '{}', '_tags': {'owner': 'net-team'}},
        {'name': 'siem', 'target_arn': 'arn:aws:kinesis:us-east-1:123456789012:stream/logs'},
    ),
    "aws_core__aws_logs_delivery_source": (
        {'name': 'waf', 'arn': 'arn:aws:logs:us-east-1:123456789012:delivery-source:waf', 'service': 'wafv2', 'logType': 'WAF_LOGS', 'resourceArns': ['arn:aws:wafv2:us-east-1:123456789012:regional/webacl/a/b'], 'tags': {'owner': 'net-team'}},
        {'name': 'waf', 'service': 'wafv2', 'log_type': 'WAF_LOGS'},
    ),
    "aws_core__aws_logs_delivery_destination": (
        {'name': 'to-s3', 'arn': 'arn:aws:logs:us-east-1:123456789012:delivery-destination:to-s3', 'deliveryDestinationType': 'S3', 'outputFormat': 'json', 'deliveryDestinationConfiguration': {'destinationResourceArn': 'arn:aws:s3:::logs'}, 'tags': {'owner': 'net-team'}},
        {'name': 'to-s3', 'destination_type': 'S3', 'destination_resource_arn': 'arn:aws:s3:::logs'},
    ),
    "aws_core__aws_logs_delivery": (
        {'id': 'd-1', 'arn': 'arn:aws:logs:us-east-1:123456789012:delivery:d-1', 'deliverySourceName': 'waf', 'deliveryDestinationArn': 'arn:aws:logs:us-east-1:123456789012:delivery-destination:to-s3', 'tags': {'owner': 'net-team'}},
        {'delivery_id': 'd-1', 'source_name': 'waf'},
    ),
    "aws_core__aws_securityhub_action_target": (
        {'ActionTargetArn': 'arn:aws:securityhub:us-east-1:123456789012:action/custom/page', 'Name': 'page', 'Description': 'Page oncall'},
        {'name': 'page'},
    ),
    "aws_core__aws_securityhub_automation_rule": (
        {'RuleArn': 'arn:aws:securityhub:us-east-1:123456789012:automation-rule/abc', 'RuleName': 'suppress-dev', 'RuleStatus': 'ENABLED', 'RuleOrder': 1, 'IsTerminal': True, 'Criteria': {}, 'Actions': [], '_tags': {'owner': 'net-team'}},
        {'name': 'suppress-dev', 'rule_status': 'ENABLED', 'rule_order': 1, 'is_terminal': True},
    ),
    "aws_core__aws_securityhub_finding_aggregator": (
        {'FindingAggregatorArn': 'arn:aws:securityhub:us-east-1:123456789012:finding-aggregator/abc', 'FindingAggregationRegion': 'us-east-1', 'RegionLinkingMode': 'ALL_REGIONS', 'Regions': []},
        {'region_linking_mode': 'ALL_REGIONS', 'regions': []},
    ),
    "aws_core__aws_securityhub_insight": (
        {'InsightArn': 'arn:aws:securityhub:us-east-1:123456789012:insight/123456789012/custom/abc', 'Name': 'open-critical', 'GroupByAttribute': 'ResourceId', 'Filters': {}},
        {'name': 'open-critical', 'group_by_attribute': 'ResourceId'},
    ),
    "aws_core__aws_apigateway_rest_api": (
        {'id': 'abc123', 'name': 'orders', '_arn': 'arn:aws:apigateway:us-east-1::/restapis/abc123', 'endpointConfiguration': {'types': ['REGIONAL']}, 'apiKeySource': 'HEADER', 'disableExecuteApiEndpoint': False, 'securityPolicy': 'TLS_1_2', 'tags': {'owner': 'net-team'}},
        {'name': 'orders', 'rest_api_id': 'abc123', 'endpoint_types': ['REGIONAL'], 'security_policy': 'TLS_1_2'},
    ),
    "aws_core__aws_apigateway_usage_plan": (
        {'id': 'u1', 'name': 'partner', 'quota': {'limit': 10000, 'period': 'DAY'}, 'throttle': {'rateLimit': 50.0, 'burstLimit': 100}, 'tags': {'owner': 'net-team'}, '_arn': 'arn:aws:apigateway:us-east-1::/usageplans/u1'},
        {'name': 'partner', 'quota_limit': 10000, 'quota_period': 'DAY', 'throttle_rate_limit': 50.0, 'throttle_burst_limit': 100},
    ),
    "aws_core__aws_apigateway_api_key": (
        {'id': 'k1', 'name': 'partner-key', 'enabled': True, 'stageKeys': ['abc123/prod'], 'tags': {'owner': 'net-team'}, '_arn': 'arn:aws:apigateway:us-east-1::/apikeys/k1'},
        {'name': 'partner-key', 'enabled': True, 'stage_keys': ['abc123/prod']},
    ),
    "aws_core__aws_apigateway_client_certificate": (
        {'clientCertificateId': 'cc1', 'pemEncodedCertificate': '-----BEGIN CERTIFICATE-----', 'expirationDate': 'x', '_expiration': '2027-10-01T00:00:00Z', 'tags': {'owner': 'net-team'}, '_arn': 'arn:aws:apigateway:us-east-1::/clientcertificates/cc1'},
        {'client_certificate_id': 'cc1', 'expiration': '2027-10-01T00:00:00Z'},
    ),
    "aws_core__aws_apigateway_stage": (
        {'stageName': 'prod', 'deploymentId': 'd1', 'variables': {'k': 'never-stored'}, '_arn': 'arn:aws:apigateway:us-east-1::/restapis/abc123/stages/prod', '_api_arn': 'arn:aws:apigateway:us-east-1::/restapis/abc123', '_api_kind': 'rest', '_rest_api_arn': 'arn:aws:apigateway:us-east-1::/restapis/abc123', '_http_api_arn': None, '_name': 'prod', '_tags': {'owner': 'net-team'}, '_web_acl_arn': 'arn:aws:wafv2:us-east-1:123456789012:regional/webacl/edge/i-1', '_deployment_id': 'd1', '_client_certificate_id': None, '_access_log_destination_arn': 'arn:aws:logs:us-east-1:123456789012:log-group:access', '_cache_cluster_enabled': False, '_tracing_enabled': True, '_auto_deploy': None},
        {'name': 'prod', 'api_kind': 'rest', 'tracing_enabled': True, 'cache_cluster_enabled': False, 'deployment_id': 'd1'},
    ),
    "aws_core__aws_apigateway_authorizer": (
        {'id': 'a1', '_arn': 'arn:aws:apigateway:us-east-1::/restapis/abc123/authorizers/a1', '_api_arn': 'arn:aws:apigateway:us-east-1::/restapis/abc123', '_api_kind': 'rest', '_rest_api_arn': 'arn:aws:apigateway:us-east-1::/restapis/abc123', '_http_api_arn': None, '_name': 'jwt', '_type': 'TOKEN', '_identity_source': ['method.request.header.Authorization'], '_result_ttl_seconds': 300, '_jwt_issuer': None},
        {'name': 'jwt', 'api_kind': 'rest', 'authorizer_type': 'TOKEN', 'result_ttl_seconds': 300, 'identity_source': ['method.request.header.Authorization']},
    ),
    "aws_core__aws_apigateway_domain_name": (
        {'domainName': 'api.example.com', 'domainNameArn': 'arn:aws:apigateway:us-east-1::/domainnames/api.example.com', '_api_kind': 'rest', '_arn': 'arn:aws:apigateway:us-east-1::/domainnames/api.example.com', '_name': 'api.example.com', '_tags': {'owner': 'net-team'}, '_certificate_arns': ['arn:aws:acm:us-east-1:123456789012:certificate/abc'], '_security_policies': ['TLS_1_2'], '_endpoint_types': ['REGIONAL'], '_truststore_uri': None},
        {'name': 'api.example.com', 'api_kind': 'rest', 'security_policies': ['TLS_1_2'], 'endpoint_types': ['REGIONAL']},
    ),
    "aws_core__aws_apigateway_vpc_link": (
        {'VpcLinkId': 'vl1', '_arn': 'arn:aws:apigateway:us-east-1::/vpclinks/vl1', '_api_kind': 'http', '_name': 'to-vpc', '_tags': {'owner': 'net-team'}, '_status': 'AVAILABLE', '_target_arns': None, '_subnet_ids': ['subnet-0a1'], '_security_group_ids': ['sg-0a1']},
        {'name': 'to-vpc', 'api_kind': 'http', 'status': 'AVAILABLE', 'subnet_ids': ['subnet-0a1']},
    ),
    "aws_core__aws_rds_db_cluster": (
        {'DBClusterIdentifier': 'orders', 'DBClusterArn': 'arn:aws:rds:us-east-1:123456789012:cluster:orders', 'Engine': 'aurora-postgresql', 'EngineVersion': '16.4', 'EngineMode': 'provisioned', 'Status': 'available', 'StorageEncrypted': True, 'IAMDatabaseAuthenticationEnabled': True, 'DeletionProtection': True, 'PubliclyAccessible': False, 'BackupRetentionPeriod': 14, 'MultiAZ': True, 'KmsKeyId': 'arn:aws:kms:us-east-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab', 'PendingModifiedValues': {'MasterUserPassword': 'never-stored'}, 'TagList': [{'Key': 'owner', 'Value': 'net-team'}]},
        {'name': 'orders', 'engine': 'aurora-postgresql', 'storage_encrypted': True, 'publicly_accessible': False, 'deletion_protection': True, 'backup_retention_days': 14},
    ),
    "aws_core__aws_rds_db_snapshot": (
        {'DBSnapshotIdentifier': 'pre-upgrade', 'DBSnapshotArn': 'arn:aws:rds:us-east-1:123456789012:snapshot:pre-upgrade', 'DBInstanceIdentifier': 'orders-db', 'Engine': 'postgres', 'SnapshotType': 'manual', 'Status': 'available', 'Encrypted': True, 'KmsKeyId': 'arn:aws:kms:us-east-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab', '_is_public': True, '_created_at': '2026-10-01T00:00:00Z', 'TagList': [{'Key': 'owner', 'Value': 'net-team'}], 'MasterUsername': 'never-stored'},
        {'name': 'pre-upgrade', 'snapshot_type': 'manual', 'encrypted': True, 'is_public': True, 'created_at': '2026-10-01T00:00:00Z'},
    ),
    "aws_core__aws_rds_db_cluster_snapshot": (
        {'DBClusterSnapshotIdentifier': 'nightly', 'DBClusterSnapshotArn': 'arn:aws:rds:us-east-1:123456789012:cluster-snapshot:nightly', 'DBClusterIdentifier': 'orders', 'Engine': 'aurora-postgresql', 'SnapshotType': 'automated', 'Status': 'available', 'StorageEncrypted': True, 'KmsKeyId': 'arn:aws:kms:us-east-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab', '_is_public': False, '_created_at': '2026-10-01T00:00:00Z', 'TagList': [{'Key': 'owner', 'Value': 'net-team'}]},
        {'name': 'nightly', 'snapshot_type': 'automated', 'storage_encrypted': True, 'is_public': False},
    ),
    "aws_core__aws_rds_db_subnet_group": (
        {'DBSubnetGroupName': 'db-private', 'DBSubnetGroupArn': 'arn:aws:rds:us-east-1:123456789012:subgrp:db-private', 'VpcId': 'vpc-0a1', 'SubnetGroupStatus': 'Complete', 'Subnets': [{'SubnetIdentifier': 'subnet-0a1'}, {'SubnetIdentifier': 'subnet-0a2'}]},
        {'name': 'db-private', 'vpc_id': 'vpc-0a1', 'status': 'Complete', 'subnet_ids': ['subnet-0a1', 'subnet-0a2']},
    ),
    "aws_core__aws_rds_db_parameter_group": (
        {'DBParameterGroupName': 'pg16-tls', 'DBParameterGroupArn': 'arn:aws:rds:us-east-1:123456789012:pg:pg16-tls', 'DBParameterGroupFamily': 'postgres16'},
        {'name': 'pg16-tls', 'family': 'postgres16'},
    ),
    "aws_core__aws_rds_db_cluster_parameter_group": (
        {'DBClusterParameterGroupName': 'aurora-tls', 'DBClusterParameterGroupArn': 'arn:aws:rds:us-east-1:123456789012:cluster-pg:aurora-tls', 'DBParameterGroupFamily': 'aurora-postgresql16'},
        {'name': 'aurora-tls', 'family': 'aurora-postgresql16'},
    ),
    "aws_core__aws_rds_option_group": (
        {'OptionGroupName': 'oracle-backup', 'OptionGroupArn': 'arn:aws:rds:us-east-1:123456789012:og:oracle-backup', 'EngineName': 'oracle-ee', 'MajorEngineVersion': '19'},
        {'name': 'oracle-backup', 'engine_name': 'oracle-ee', 'major_engine_version': '19'},
    ),
    "aws_core__aws_rds_db_proxy": (
        {'DBProxyName': 'orders-proxy', 'DBProxyArn': 'arn:aws:rds:us-east-1:123456789012:db-proxy:prx-0a1', 'Status': 'available', 'EngineFamily': 'POSTGRESQL', 'VpcId': 'vpc-0a1', 'RequireTLS': True, 'IdleClientTimeout': 1800, 'Endpoint': 'orders-proxy.proxy-abc.us-east-1.rds.amazonaws.com', 'VpcSubnetIds': ['subnet-0a1'], 'RoleArn': 'arn:aws:iam::123456789012:role/proxy'},
        {'name': 'orders-proxy', 'engine_family': 'POSTGRESQL', 'require_tls': True, 'idle_client_timeout_seconds': 1800},
    ),
    "aws_core__aws_rds_event_subscription": (
        {'CustSubscriptionId': 'failovers', 'EventSubscriptionArn': 'arn:aws:rds:us-east-1:123456789012:es:failovers', 'SnsTopicArn': 'arn:aws:sns:us-east-1:123456789012:alerts', 'SourceType': 'db-instance', 'Enabled': True, 'Status': 'active'},
        {'name': 'failovers', 'source_type': 'db-instance', 'enabled': True, 'status': 'active'},
    ),
    "aws_core__aws_rds_global_cluster": (
        {'GlobalClusterIdentifier': 'orders-global', 'GlobalClusterArn': 'arn:aws:rds::123456789012:global-cluster:orders-global', 'Engine': 'aurora-postgresql', 'EngineVersion': '16.4', 'StorageEncrypted': True, 'DeletionProtection': True, 'Status': 'available', 'TagList': [{'Key': 'owner', 'Value': 'net-team'}]},
        {'name': 'orders-global', 'engine': 'aurora-postgresql', 'storage_encrypted': True, 'deletion_protection': True},
    ),
    "aws_core__aws_aps_scraper": (
        {'arn': 'arn:aws:amp:us-east-1:123456789012:aps_scraper/gen-1', 'tags': {'owner': 'net-team'}},
        {},
    ),
    "aws_core__aws_aps_workspace": (
        {'arn': 'arn:aws:amp:us-east-1:123456789012:aps_workspace/gen-1', 'tags': {'owner': 'net-team'}},
        {},
    ),
    "aws_core__aws_batch_compute_environment": (
        {'computeEnvironmentArn': 'arn:aws:batch:us-east-1:123456789012:batch_compute_environment/gen-1', 'computeEnvironmentName': 'gen-1', 'tags': {'owner': 'net-team'}},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_batch_consumable_resource": (
        {'consumableResourceArn': 'arn:aws:batch:us-east-1:123456789012:batch_consumable_resource/gen-1', 'consumableResourceName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_batch_job_queue": (
        {'jobQueueArn': 'arn:aws:batch:us-east-1:123456789012:batch_job_queue/gen-1', 'jobQueueName': 'gen-1', 'tags': {'owner': 'net-team'}},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_batch_scheduling_policy": (
        {'arn': 'arn:aws:batch:us-east-1:123456789012:batch_scheduling_policy/gen-1'},
        {},
    ),
    "aws_core__aws_batch_service_environment": (
        {'serviceEnvironmentArn': 'arn:aws:batch:us-east-1:123456789012:batch_service_environment/gen-1', 'serviceEnvironmentName': 'gen-1', 'tags': {'owner': 'net-team'}},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_ai_workload_config": (
        {'AIWorkloadConfigArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_ai_workload_config/gen-1', 'AIWorkloadConfigName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_algorithm": (
        {'AlgorithmArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_algorithm/gen-1', 'AlgorithmName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_cluster": (
        {'ClusterArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_cluster/gen-1', 'ClusterName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_cluster_scheduler_config": (
        {'ClusterSchedulerConfigArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_cluster_scheduler_config/gen-1', 'Name': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_code_repository": (
        {'CodeRepositoryArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_code_repository/gen-1', 'CodeRepositoryName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_compute_quota": (
        {'ComputeQuotaArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_compute_quota/gen-1', 'Name': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_endpoint_config": (
        {'EndpointConfigArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_endpoint_config/gen-1', 'EndpointConfigName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_hub": (
        {'HubArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_hub/gen-1', 'HubName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_human_task_ui": (
        {'HumanTaskUiArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_human_task_ui/gen-1', 'HumanTaskUiName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_image": (
        {'ImageArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_image/gen-1', 'DisplayName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_inference_component": (
        {'InferenceComponentArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_inference_component/gen-1', 'InferenceComponentName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_mlflow_app": (
        {'Arn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_mlflow_app/gen-1', 'Name': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_model": (
        {'ModelArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_model/gen-1', 'ModelName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_model_package": (
        {'ModelPackageArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_model_package/gen-1', 'ModelPackageName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_model_package_group": (
        {'ModelPackageGroupArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_model_package_group/gen-1', 'ModelPackageGroupName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_monitoring_schedule": (
        {'MonitoringScheduleArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_monitoring_schedule/gen-1', 'MonitoringScheduleName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_notebook_instance": (
        {'NotebookInstanceArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_notebook_instance/gen-1', 'NotebookInstanceName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_notebook_instance_lifecycle_config": (
        {'NotebookInstanceLifecycleConfigArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_notebook_instance_lifecycle_config/gen-1', 'NotebookInstanceLifecycleConfigName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_partner_app": (
        {'Arn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_partner_app/gen-1', 'Name': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_processing_job": (
        {'ProcessingJobArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_processing_job/gen-1', 'ProcessingJobName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_project": (
        {'ProjectArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_project/gen-1', 'ProjectName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_trial_component": (
        {'TrialComponentArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_trial_component/gen-1', 'TrialComponentName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_workforce": (
        {'WorkforceArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_workforce/gen-1', 'WorkforceName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_sagemaker_workteam": (
        {'WorkteamArn': 'arn:aws:sagemaker:us-east-1:123456789012:sagemaker_workteam/gen-1', 'WorkteamName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_apigatewayv2_portal_product": (
        {'PortalProductArn': 'arn:aws:apigatewayv2:us-east-1:123456789012:apigatewayv2_portal_product/gen-1', 'DisplayName': 'gen-1', 'Tags': {'owner': 'net-team'}},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_appstream_app_block": (
        {'Arn': 'arn:aws:appstream:us-east-1:123456789012:appstream_app_block/gen-1', 'Name': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_appstream_application": (
        {'Arn': 'arn:aws:appstream:us-east-1:123456789012:appstream_application/gen-1', 'Name': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_backup_report_plan": (
        {'ReportPlanArn': 'arn:aws:backup:us-east-1:123456789012:backup_report_plan/gen-1', 'ReportPlanName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_backupgateway_hypervisor": (
        {'HypervisorArn': 'arn:aws:backup-gateway:us-east-1:123456789012:backupgateway_hypervisor/gen-1', 'Name': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_certificatemanager_acme_endpoint": (
        {'AcmeEndpointArn': 'arn:aws:acm:us-east-1:123456789012:certificatemanager_acme_endpoint/gen-1'},
        {},
    ),
    "aws_core__aws_codestarconnections_connection": (
        {'ConnectionArn': 'arn:aws:codestar-connections:us-east-1:123456789012:codestarconnections_connection/gen-1', 'ConnectionName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_codestarconnections_repository_link": (
        {'RepositoryLinkArn': 'arn:aws:codestar-connections:us-east-1:123456789012:codestarconnections_repository_link/gen-1'},
        {},
    ),
    "aws_core__aws_datasync_agent": (
        {'AgentArn': 'arn:aws:datasync:us-east-1:123456789012:datasync_agent/gen-1', 'Name': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_datasync_task": (
        {'TaskArn': 'arn:aws:datasync:us-east-1:123456789012:datasync_task/gen-1', 'Name': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_detective_graph": (
        {'Arn': 'arn:aws:detective:us-east-1:123456789012:detective_graph/gen-1'},
        {},
    ),
    "aws_core__aws_ec2_ipam_external_resource_verification_token": (
        {'IpamExternalResourceVerificationTokenArn': 'arn:aws:ec2:us-east-1:123456789012:ec2_ipam_external_resource_verification_token/gen-1', 'Tags': [{'Key': 'owner', 'Value': 'net-team'}]},
        {},
    ),
    "aws_core__aws_ec2_ipam_internet_registry_association": (
        {'IpamInternetRegistryAssociationArn': 'arn:aws:ec2:us-east-1:123456789012:ec2_ipam_internet_registry_association/gen-1', 'Tags': [{'Key': 'owner', 'Value': 'net-team'}]},
        {},
    ),
    "aws_core__aws_ec2_secondary_network": (
        {'SecondaryNetworkArn': 'arn:aws:ec2:us-east-1:123456789012:ec2_secondary_network/gen-1', 'Tags': [{'Key': 'owner', 'Value': 'net-team'}]},
        {},
    ),
    "aws_core__aws_ecs_daemon": (
        {'daemonArn': 'arn:aws:ecs:us-east-1:123456789012:ecs_daemon/gen-1'},
        {},
    ),
    "aws_core__aws_emrcontainers_security_configuration": (
        {'arn': 'arn:aws:emr-containers:us-east-1:123456789012:emrcontainers_security_configuration/gen-1', 'name': 'gen-1', 'tags': {'owner': 'net-team'}},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_elasticache_serverless_cache_snapshot": (
        {'ARN': 'arn:aws:elasticache:us-east-1:123456789012:elasticache_serverless_cache_snapshot/gen-1', 'ServerlessCacheSnapshotName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_elasticache_snapshot": (
        {'ARN': 'arn:aws:elasticache:us-east-1:123456789012:elasticache_snapshot/gen-1', 'SnapshotName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_eventschemas_discoverer": (
        {'DiscovererArn': 'arn:aws:schemas:us-east-1:123456789012:eventschemas_discoverer/gen-1', 'Tags': {'owner': 'net-team'}},
        {},
    ),
    "aws_core__aws_eventschemas_registry": (
        {'RegistryArn': 'arn:aws:schemas:us-east-1:123456789012:eventschemas_registry/gen-1', 'RegistryName': 'gen-1', 'Tags': {'owner': 'net-team'}},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_fsx_file_cache": (
        {'ResourceARN': 'arn:aws:fsx:us-east-1:123456789012:fsx_file_cache/gen-1'},
        {},
    ),
    "aws_core__aws_inspectorv2_connector": (
        {'connectorArn': 'arn:aws:inspector2:us-east-1:123456789012:inspectorv2_connector/gen-1', 'name': 'gen-1', 'tags': {'owner': 'net-team'}},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_inspectorv2_filter": (
        {'arn': 'arn:aws:inspector2:us-east-1:123456789012:inspectorv2_filter/gen-1', 'name': 'gen-1', 'tags': {'owner': 'net-team'}},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_iot_ota_update": (
        {'otaUpdateArn': 'arn:aws:iot:us-east-1:123456789012:iot_ota_update/gen-1'},
        {},
    ),
    "aws_core__aws_iot_topic_rule_destination": (
        {'arn': 'arn:aws:iot:us-east-1:123456789012:iot_topic_rule_destination/gen-1'},
        {},
    ),
    "aws_core__aws_iotsecuretunneling_tunnel": (
        {'tunnelArn': 'arn:aws:iotsecuretunneling:us-east-1:123456789012:iotsecuretunneling_tunnel/gen-1'},
        {},
    ),
    "aws_core__aws_iotsitewise_application": (
        {'arn': 'arn:aws:iotsitewise:us-east-1:123456789012:iotsitewise_application/gen-1', 'name': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_kafkaconnect_connector": (
        {'connectorArn': 'arn:aws:kafkaconnect:us-east-1:123456789012:kafkaconnect_connector/gen-1', 'connectorName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_kafkaconnect_custom_plugin": (
        {'customPluginArn': 'arn:aws:kafkaconnect:us-east-1:123456789012:kafkaconnect_custom_plugin/gen-1', 'name': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_kafkaconnect_worker_configuration": (
        {'workerConfigurationArn': 'arn:aws:kafkaconnect:us-east-1:123456789012:kafkaconnect_worker_configuration/gen-1', 'name': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_kinesis_channel": (
        {'ChannelARN': 'arn:aws:kinesis:us-east-1:123456789012:kinesis_channel/gen-1', 'ChannelName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_licensemanager_license": (
        {'LicenseArn': 'arn:aws:license-manager:us-east-1:123456789012:licensemanager_license/gen-1', 'LicenseName': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_licensemanager_license_asset_group": (
        {'LicenseAssetGroupArn': 'arn:aws:license-manager:us-east-1:123456789012:licensemanager_license_asset_group/gen-1', 'Name': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_licensemanager_license_configuration": (
        {'LicenseConfigurationArn': 'arn:aws:license-manager:us-east-1:123456789012:licensemanager_license_configuration/gen-1', 'Name': 'gen-1'},
        {'name': 'gen-1'},
    ),
    "aws_core__aws_logs_log_anomaly_detector": (
        {'anomalyDetectorArn': 'arn:aws:logs:us-east-1:123456789012:logs_log_anomaly_detector/gen-1'},
        {},
    ),
    "aws_core__aws_logs_scheduled_query": (
        {'scheduledQueryArn': 'arn:aws:logs:us-east-1:123456789012:logs_scheduled_query/gen-1', 'name': 'gen-1'},
        {'name': 'gen-1'},
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
        if entry["tags"]["source"] == "none":
            assert payload["tags"] == {}  # AWS has no tag operation for the type: observed, untagged
        else:
            assert payload["tags"].get("owner") == "net-team"

    def test_the_tags_are_read_by_a_declared_lane(self, entity_type: str) -> None:
        tags = _entry(entity_type)["tags"]
        if tags["source"] == "none":
            assert tags["why"]
            return
        if tags["source"] == "rgta":
            # Joined by ARN from the region's one sweep; the item must carry the ARN it is joined on.
            item, _ = CASES[entity_type]
            assert eval_path(item, tags["arn_from"]), tags
            return
        if tags["source"] == "service":
            # Read by a side call the engine makes by the item's own id or ARN.
            item, _ = CASES[entity_type]
            assert all(eval_path(item, p["from"]) for p in tags["params"].values() if "from" in p), tags
            return
        assert tags["source"] == "field"
        assert (tags["from"], tags["shape"]) in (
            ("Tags[]", "list_kv"),
            ("TagList", "list_kv"),
            ("tags[]", "list_kv_lower"),
            ("_tags", "map"),
            ("tags", "map"),
            ("Tags", "map"),
            ("IdentityPoolTags", "map"),
        )

    def test_every_edge_rule_names_an_edge_that_allows_the_pair_and_the_item_resolves_one(self, entity_type: str) -> None:
        item, _ = CASES[entity_type]
        rules = _entry(entity_type).get("edges", [])
        for rule in rules:
            edge = _edge_json(rule["edge_type"])
            # Most edge types name both ends. The few that leave one open on purpose (a source that any service
            # type may be) are listed here; any other edge type must declare its ends.
            open_ends = OPEN_ENDED_EDGES.get(rule["edge_type"], ())
            if "sources" not in open_ends:
                assert entity_type in edge["sources"], (entity_type, rule["edge_type"])
            if "targets" not in open_ends:
                assert rule["target_type"] in edge["targets"], (entity_type, rule["edge_type"])
        # A rule may be conditional on a sibling (a transit gateway attachment's VPC id exists only for a VPC
        # attachment), so the canned item need only resolve some rule, not all.
        assert not rules or any(eval_path(item, rule["value_path"]) for rule in rules)

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
    if block["source"] == "none":
        return {}
    if block["source"] in ("rgta", "service"):
        return {"owner": "net-team"}
    return normalize_tags(eval_path(item, block["from"]), block["shape"])


@pytest.mark.parametrize("entry", manifest_entries(), ids=lambda e: e["entity_type"])
def test_every_collected_model_declares_the_configuration_the_envelope_always_carries(entry: dict[str, Any]) -> None:
    """``node_envelope`` writes ``configuration`` on every node (the full envelope, or ``{}``), so a model
    without the field has its whole batch rejected at import, as v0.4.0 did for ``tags``."""
    model = _model(entry["entity_type"])
    assert "configuration" in model.FIELD_CRUD_SCHEMA and "configuration" in model.FIELD_VALIDATION_SCHEMA
    assert any(f.name == "configuration" for f in model._meta.get_fields())
