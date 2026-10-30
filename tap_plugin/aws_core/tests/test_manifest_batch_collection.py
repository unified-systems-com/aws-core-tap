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
