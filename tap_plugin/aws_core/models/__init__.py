"""AWS Core plugin models package."""

from tap_plugin.aws_core.models.acm_certificate import AcmCertificate
from tap_plugin.aws_core.models.acm_private_ca import AcmPrivateCa
from tap_plugin.aws_core.models.alb import Alb
from tap_plugin.aws_core.models.apigateway_http_api import ApiGatewayHttpApi
from tap_plugin.aws_core.models.availability_zone import AvailabilityZone
from tap_plugin.aws_core.models.aws_access_analyzer import AwsAccessAnalyzer
from tap_plugin.aws_core.models.aws_access_analyzer_finding import AwsAccessAnalyzerFinding
from tap_plugin.aws_core.models.aws_account import AwsAccount
from tap_plugin.aws_core.models.aws_account_region import AwsAccountRegion
from tap_plugin.aws_core.models.aws_config_aggregator import AwsConfigAggregator
from tap_plugin.aws_core.models.aws_config_conformance_pack import AwsConfigConformancePack
from tap_plugin.aws_core.models.aws_config_delivery_channel import AwsConfigDeliveryChannel
from tap_plugin.aws_core.models.aws_config_recorder import AwsConfigRecorder
from tap_plugin.aws_core.models.aws_config_rule import AwsConfigRule
from tap_plugin.aws_core.models.aws_controltower_enabled_baseline import AwsControlTowerEnabledBaseline
from tap_plugin.aws_core.models.aws_controltower_enabled_control import AwsControlTowerEnabledControl
from tap_plugin.aws_core.models.aws_controltower_landing_zone import AwsControlTowerLandingZone
from tap_plugin.aws_core.models.aws_delegated_administration import AwsDelegatedAdministration
from tap_plugin.aws_core.models.aws_guardduty_detector import AwsGuardDutyDetector
from tap_plugin.aws_core.models.aws_guardduty_finding import AwsGuardDutyFinding
from tap_plugin.aws_core.models.aws_identity_center_account_assignment import AwsIdentityCenterAccountAssignment
from tap_plugin.aws_core.models.aws_identity_center_group import AwsIdentityCenterGroup
from tap_plugin.aws_core.models.aws_identity_center_instance import AwsIdentityCenterInstance
from tap_plugin.aws_core.models.aws_identity_center_permission_set import AwsIdentityCenterPermissionSet
from tap_plugin.aws_core.models.aws_organization import AwsOrganization
from tap_plugin.aws_core.models.aws_organizational_unit import AwsOrganizationalUnit
from tap_plugin.aws_core.models.aws_organizations_policy import AwsOrganizationsPolicy
from tap_plugin.aws_core.models.aws_policy_statement import AwsPolicyStatement
from tap_plugin.aws_core.models.aws_region import AwsRegion
from tap_plugin.aws_core.models.aws_securityhub_finding import AwsSecurityHubFinding
from tap_plugin.aws_core.models.aws_securityhub_hub import AwsSecurityHubHub
from tap_plugin.aws_core.models.aws_securityhub_standards_subscription import AwsSecurityHubStandardsSubscription
from tap_plugin.aws_core.models.aws_service_control_policy import AwsServiceControlPolicy
from tap_plugin.aws_core.models.aws_tag_policy_rule import AwsTagPolicyRule
from tap_plugin.aws_core.models.bedrock_model import BedrockModel
from tap_plugin.aws_core.models.cloudfront_distribution import CloudfrontDistribution
from tap_plugin.aws_core.models.cloudtrail_trail import CloudtrailTrail
from tap_plugin.aws_core.models.cloudwatch_log_group import CloudwatchLogGroup
from tap_plugin.aws_core.models.codebuild_project import CodebuildProject
from tap_plugin.aws_core.models.codepipeline_pipeline import CodepipelinePipeline
from tap_plugin.aws_core.models.cognito_user_pool import CognitoUserPool
from tap_plugin.aws_core.models.dx_connection import DxConnection
from tap_plugin.aws_core.models.dx_gateway import DxGateway
from tap_plugin.aws_core.models.dx_virtual_interface import DxVirtualInterface
from tap_plugin.aws_core.models.dynamodb_table import DynamoDbTable
from tap_plugin.aws_core.models.ebs_volume import EbsVolume
from tap_plugin.aws_core.models.ec2_instance import Ec2Instance
from tap_plugin.aws_core.models.ecr_repository import EcrRepository
from tap_plugin.aws_core.models.ecs_cluster import EcsCluster
from tap_plugin.aws_core.models.ecs_container import EcsContainer
from tap_plugin.aws_core.models.ecs_service import EcsService
from tap_plugin.aws_core.models.ecs_task import EcsTask
from tap_plugin.aws_core.models.eks_cluster import EksCluster
from tap_plugin.aws_core.models.elastic_ip import ElasticIp
from tap_plugin.aws_core.models.elasticache_cluster import ElasticacheCluster
from tap_plugin.aws_core.models.elasticsearch_domain import ElasticsearchDomain
from tap_plugin.aws_core.models.elb import Elb
from tap_plugin.aws_core.models.eventbridge_rule import EventbridgeRule
from tap_plugin.aws_core.models.iam_group import IamGroup
from tap_plugin.aws_core.models.iam_instance_profile import IamInstanceProfile
from tap_plugin.aws_core.models.iam_oidc_provider import IamOidcProvider
from tap_plugin.aws_core.models.iam_policy import IamPolicy
from tap_plugin.aws_core.models.iam_role import IamRole
from tap_plugin.aws_core.models.iam_saml_provider import IamSamlProvider
from tap_plugin.aws_core.models.iam_server_certificate import IamServerCertificate
from tap_plugin.aws_core.models.iam_user import IamUser
from tap_plugin.aws_core.models.iam_virtual_mfa_device import IamVirtualMfaDevice
from tap_plugin.aws_core.models.internet_gateway import InternetGateway
from tap_plugin.aws_core.models.kms_key import KmsKey
from tap_plugin.aws_core.models.lambda_function import LambdaFunction
from tap_plugin.aws_core.models.nat_gateway import NatGateway
from tap_plugin.aws_core.models.network_acl import NetworkAcl
from tap_plugin.aws_core.models.network_firewall import NetworkFirewall
from tap_plugin.aws_core.models.rds_instance import RdsInstance
from tap_plugin.aws_core.models.route53_hosted_zone import Route53HostedZone
from tap_plugin.aws_core.models.route53_resolver_firewall_rule_group import Route53ResolverFirewallRuleGroup
from tap_plugin.aws_core.models.route_table import RouteTable
from tap_plugin.aws_core.models.s3_bucket import S3Bucket
from tap_plugin.aws_core.models.sagemaker_endpoint import SagemakerEndpoint
from tap_plugin.aws_core.models.secrets_manager_secret import SecretsManagerSecret
from tap_plugin.aws_core.models.security_group import SecurityGroup
from tap_plugin.aws_core.models.sqs_queue import SqsQueue
from tap_plugin.aws_core.models.ssm_parameter import SsmParameter
from tap_plugin.aws_core.models.subnet import Subnet
from tap_plugin.aws_core.models.target_group import TargetGroup
from tap_plugin.aws_core.models.transit_gateway import TransitGateway
from tap_plugin.aws_core.models.transit_gateway_attachment import TransitGatewayAttachment
from tap_plugin.aws_core.models.vpc import Vpc
from tap_plugin.aws_core.models.vpc_endpoint import VpcEndpoint
from tap_plugin.aws_core.models.vpc_endpoint_service import VpcEndpointService
from tap_plugin.aws_core.models.kms_alias import KmsAlias
from tap_plugin.aws_core.models.cloudtrail_event_data_store import CloudtrailEventDataStore
from tap_plugin.aws_core.models.cloudtrail_channel import CloudtrailChannel
from tap_plugin.aws_core.models.cloudtrail_dashboard import CloudtrailDashboard
from tap_plugin.aws_core.models.config_aggregation_authorization import ConfigAggregationAuthorization
from tap_plugin.aws_core.models.config_organization_rule import ConfigOrganizationRule
from tap_plugin.aws_core.models.config_organization_conformance_pack import ConfigOrganizationConformancePack
from tap_plugin.aws_core.models.config_stored_query import ConfigStoredQuery
from tap_plugin.aws_core.models.identity_center_user import IdentityCenterUser
from tap_plugin.aws_core.models.identity_center_application import IdentityCenterApplication
from tap_plugin.aws_core.models.identity_center_application_assignment import IdentityCenterApplicationAssignment
from tap_plugin.aws_core.models.access_analyzer_archive_rule import AccessAnalyzerArchiveRule
from tap_plugin.aws_core.models.config_connector import ConfigConnector
from tap_plugin.aws_core.models.sns_topic import SnsTopic
from tap_plugin.aws_core.models.sns_subscription import SnsSubscription
from tap_plugin.aws_core.models.eventbridge_event_bus import EventbridgeEventBus
from tap_plugin.aws_core.models.eventbridge_archive import EventbridgeArchive
from tap_plugin.aws_core.models.eventbridge_connection import EventbridgeConnection
from tap_plugin.aws_core.models.eventbridge_api_destination import EventbridgeApiDestination
from tap_plugin.aws_core.models.lambda_function_url import LambdaFunctionUrl
from tap_plugin.aws_core.models.lambda_layer_version import LambdaLayerVersion
from tap_plugin.aws_core.models.lambda_code_signing_config import LambdaCodeSigningConfig
from tap_plugin.aws_core.models.lambda_event_source_mapping import LambdaEventSourceMapping
from tap_plugin.aws_core.models.guardduty_filter import GuarddutyFilter
from tap_plugin.aws_core.models.guardduty_ip_set import GuarddutyIpSet
from tap_plugin.aws_core.models.guardduty_threat_intel_set import GuarddutyThreatIntelSet
from tap_plugin.aws_core.models.guardduty_publishing_destination import GuarddutyPublishingDestination
from tap_plugin.aws_core.models.guardduty_member import GuarddutyMember
from tap_plugin.aws_core.models.wafv2_web_acl import Wafv2WebAcl
from tap_plugin.aws_core.models.wafv2_rule_group import Wafv2RuleGroup
from tap_plugin.aws_core.models.wafv2_ip_set import Wafv2IpSet
from tap_plugin.aws_core.models.wafv2_regex_pattern_set import Wafv2RegexPatternSet
from tap_plugin.aws_core.models.s3_access_point import S3AccessPoint
from tap_plugin.aws_core.models.efs_file_system import EfsFileSystem
from tap_plugin.aws_core.models.efs_access_point import EfsAccessPoint
from tap_plugin.aws_core.models.efs_mount_target import EfsMountTarget
from tap_plugin.aws_core.models.elb_listener import ElbListener
from tap_plugin.aws_core.models.backup_vault import BackupVault
from tap_plugin.aws_core.models.backup_plan import BackupPlan
from tap_plugin.aws_core.models.backup_framework import BackupFramework
from tap_plugin.aws_core.models.backup_legal_hold import BackupLegalHold
from tap_plugin.aws_core.models.cognito_identity_pool import CognitoIdentityPool
from tap_plugin.aws_core.models.cognito_user_pool_client import CognitoUserPoolClient
from tap_plugin.aws_core.models.cognito_identity_provider import CognitoIdentityProvider
from tap_plugin.aws_core.models.cognito_user_pool_group import CognitoUserPoolGroup
from tap_plugin.aws_core.models.cognito_user_pool_resource_server import CognitoUserPoolResourceServer
from tap_plugin.aws_core.models.cognito_user_pool_domain import CognitoUserPoolDomain
from tap_plugin.aws_core.models.cloudwatch_alarm import CloudwatchAlarm
from tap_plugin.aws_core.models.cloudwatch_composite_alarm import CloudwatchCompositeAlarm
from tap_plugin.aws_core.models.cloudwatch_dashboard import CloudwatchDashboard
from tap_plugin.aws_core.models.cloudwatch_metric_stream import CloudwatchMetricStream
from tap_plugin.aws_core.models.logs_metric_filter import LogsMetricFilter
from tap_plugin.aws_core.models.logs_subscription_filter import LogsSubscriptionFilter
from tap_plugin.aws_core.models.logs_destination import LogsDestination
from tap_plugin.aws_core.models.logs_delivery_source import LogsDeliverySource
from tap_plugin.aws_core.models.logs_delivery_destination import LogsDeliveryDestination
from tap_plugin.aws_core.models.logs_delivery import LogsDelivery
from tap_plugin.aws_core.models.securityhub_action_target import SecurityhubActionTarget
from tap_plugin.aws_core.models.securityhub_automation_rule import SecurityhubAutomationRule
from tap_plugin.aws_core.models.securityhub_finding_aggregator import SecurityhubFindingAggregator
from tap_plugin.aws_core.models.securityhub_insight import SecurityhubInsight

__all__ = [
    "SecurityhubInsight",
    "SecurityhubFindingAggregator",
    "SecurityhubAutomationRule",
    "SecurityhubActionTarget",
    "LogsDelivery",
    "LogsDeliveryDestination",
    "LogsDeliverySource",
    "LogsDestination",
    "LogsSubscriptionFilter",
    "LogsMetricFilter",
    "CloudwatchMetricStream",
    "CloudwatchDashboard",
    "CloudwatchCompositeAlarm",
    "CloudwatchAlarm",
    "CognitoUserPoolDomain",
    "CognitoUserPoolResourceServer",
    "CognitoUserPoolGroup",
    "CognitoIdentityProvider",
    "CognitoUserPoolClient",
    "CognitoIdentityPool",
    "BackupLegalHold",
    "BackupFramework",
    "BackupPlan",
    "BackupVault",
    "ElbListener",
    "EfsMountTarget",
    "EfsAccessPoint",
    "EfsFileSystem",
    "S3AccessPoint",
    "Wafv2RegexPatternSet",
    "Wafv2IpSet",
    "Wafv2RuleGroup",
    "Wafv2WebAcl",
    "GuarddutyMember",
    "GuarddutyPublishingDestination",
    "GuarddutyThreatIntelSet",
    "GuarddutyIpSet",
    "GuarddutyFilter",
    "LambdaEventSourceMapping",
    "LambdaCodeSigningConfig",
    "LambdaLayerVersion",
    "LambdaFunctionUrl",
    "EventbridgeApiDestination",
    "EventbridgeConnection",
    "EventbridgeArchive",
    "EventbridgeEventBus",
    "SnsSubscription",
    "SnsTopic",
    "ConfigConnector",
    "AccessAnalyzerArchiveRule",
    "IdentityCenterApplicationAssignment",
    "IdentityCenterApplication",
    "IdentityCenterUser",
    "ConfigStoredQuery",
    "ConfigOrganizationConformancePack",
    "ConfigOrganizationRule",
    "ConfigAggregationAuthorization",
    "CloudtrailDashboard",
    "CloudtrailChannel",
    "CloudtrailEventDataStore",
    "KmsAlias",
    "AcmCertificate",
    "AcmPrivateCa",
    "Alb",
    "ApiGatewayHttpApi",
    "AvailabilityZone",
    "AwsAccessAnalyzer",
    "AwsAccessAnalyzerFinding",
    "AwsAccount",
    "AwsAccountRegion",
    "AwsConfigAggregator",
    "AwsConfigConformancePack",
    "AwsConfigDeliveryChannel",
    "AwsConfigRecorder",
    "AwsConfigRule",
    "AwsControlTowerEnabledBaseline",
    "AwsControlTowerEnabledControl",
    "AwsControlTowerLandingZone",
    "AwsDelegatedAdministration",
    "AwsGuardDutyDetector",
    "AwsGuardDutyFinding",
    "AwsIdentityCenterAccountAssignment",
    "AwsIdentityCenterGroup",
    "AwsIdentityCenterInstance",
    "AwsIdentityCenterPermissionSet",
    "AwsOrganization",
    "AwsOrganizationalUnit",
    "AwsOrganizationsPolicy",
    "AwsPolicyStatement",
    "AwsRegion",
    "AwsSecurityHubFinding",
    "AwsSecurityHubHub",
    "AwsSecurityHubStandardsSubscription",
    "AwsServiceControlPolicy",
    "AwsTagPolicyRule",
    "BedrockModel",
    "CloudfrontDistribution",
    "CloudtrailTrail",
    "CloudwatchLogGroup",
    "CodebuildProject",
    "CodepipelinePipeline",
    "CognitoUserPool",
    "DxConnection",
    "DxGateway",
    "DxVirtualInterface",
    "DynamoDbTable",
    "EbsVolume",
    "Ec2Instance",
    "EcrRepository",
    "EcsCluster",
    "EcsContainer",
    "EcsService",
    "EcsTask",
    "EksCluster",
    "ElasticIp",
    "ElasticacheCluster",
    "ElasticsearchDomain",
    "Elb",
    "EventbridgeRule",
    "IamGroup",
    "IamInstanceProfile",
    "IamOidcProvider",
    "IamPolicy",
    "IamRole",
    "IamSamlProvider",
    "IamServerCertificate",
    "IamUser",
    "IamVirtualMfaDevice",
    "InternetGateway",
    "KmsKey",
    "LambdaFunction",
    "NatGateway",
    "NetworkAcl",
    "NetworkFirewall",
    "RdsInstance",
    "Route53HostedZone",
    "Route53ResolverFirewallRuleGroup",
    "RouteTable",
    "S3Bucket",
    "SagemakerEndpoint",
    "SecretsManagerSecret",
    "SecurityGroup",
    "SqsQueue",
    "SsmParameter",
    "Subnet",
    "TargetGroup",
    "TransitGateway",
    "TransitGatewayAttachment",
    "Vpc",
    "VpcEndpoint",
    "VpcEndpointService",
]
