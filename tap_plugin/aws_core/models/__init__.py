"""AWS Core plugin models package."""

from tap_plugin.aws_core.models.acm_certificate import AcmCertificate
from tap_plugin.aws_core.models.acm_private_ca import AcmPrivateCa
from tap_plugin.aws_core.models.alb import Alb
from tap_plugin.aws_core.models.apigateway_http_api import ApiGatewayHttpApi
from tap_plugin.aws_core.models.availability_zone import AvailabilityZone
from tap_plugin.aws_core.models.aws_access_analyzer import AwsAccessAnalyzer
from tap_plugin.aws_core.models.aws_account import AwsAccount
from tap_plugin.aws_core.models.aws_account_region import AwsAccountRegion
from tap_plugin.aws_core.models.aws_config_aggregator import AwsConfigAggregator
from tap_plugin.aws_core.models.aws_config_delivery_channel import AwsConfigDeliveryChannel
from tap_plugin.aws_core.models.aws_config_recorder import AwsConfigRecorder
from tap_plugin.aws_core.models.aws_controltower_enabled_baseline import AwsControlTowerEnabledBaseline
from tap_plugin.aws_core.models.aws_controltower_enabled_control import AwsControlTowerEnabledControl
from tap_plugin.aws_core.models.aws_controltower_landing_zone import AwsControlTowerLandingZone
from tap_plugin.aws_core.models.aws_delegated_administration import AwsDelegatedAdministration
from tap_plugin.aws_core.models.aws_guardduty_detector import AwsGuardDutyDetector
from tap_plugin.aws_core.models.aws_identity_center_account_assignment import AwsIdentityCenterAccountAssignment
from tap_plugin.aws_core.models.aws_identity_center_group import AwsIdentityCenterGroup
from tap_plugin.aws_core.models.aws_identity_center_instance import AwsIdentityCenterInstance
from tap_plugin.aws_core.models.aws_identity_center_permission_set import AwsIdentityCenterPermissionSet
from tap_plugin.aws_core.models.aws_organization import AwsOrganization
from tap_plugin.aws_core.models.aws_organizational_unit import AwsOrganizationalUnit
from tap_plugin.aws_core.models.aws_organizations_policy import AwsOrganizationsPolicy
from tap_plugin.aws_core.models.aws_policy_statement import AwsPolicyStatement
from tap_plugin.aws_core.models.aws_region import AwsRegion
from tap_plugin.aws_core.models.aws_securityhub_hub import AwsSecurityHubHub
from tap_plugin.aws_core.models.aws_service_control_policy import AwsServiceControlPolicy
from tap_plugin.aws_core.models.aws_tag_policy_rule import AwsTagPolicyRule
from tap_plugin.aws_core.models.bedrock_model import BedrockModel
from tap_plugin.aws_core.models.cloudfront_distribution import CloudfrontDistribution
from tap_plugin.aws_core.models.cloudtrail_trail import CloudtrailTrail
from tap_plugin.aws_core.models.cloudwatch_log_group import CloudwatchLogGroup
from tap_plugin.aws_core.models.cognito_user_pool import CognitoUserPool
from tap_plugin.aws_core.models.dx_connection import DxConnection
from tap_plugin.aws_core.models.dx_gateway import DxGateway
from tap_plugin.aws_core.models.dx_virtual_interface import DxVirtualInterface
from tap_plugin.aws_core.models.dynamodb_table import DynamoDbTable
from tap_plugin.aws_core.models.ebs_volume import EbsVolume
from tap_plugin.aws_core.models.ec2_instance import Ec2Instance
from tap_plugin.aws_core.models.ecr_repository import EcrRepository
from tap_plugin.aws_core.models.ecs_cluster import EcsCluster
from tap_plugin.aws_core.models.ecs_service import EcsService
from tap_plugin.aws_core.models.ecs_task import EcsTask
from tap_plugin.aws_core.models.eks_cluster import EksCluster
from tap_plugin.aws_core.models.elastic_ip import ElasticIp
from tap_plugin.aws_core.models.elasticache_cluster import ElasticacheCluster
from tap_plugin.aws_core.models.elasticsearch_domain import ElasticsearchDomain
from tap_plugin.aws_core.models.elb import Elb
from tap_plugin.aws_core.models.eventbridge_rule import EventbridgeRule
from tap_plugin.aws_core.models.iam_oidc_provider import IamOidcProvider
from tap_plugin.aws_core.models.iam_policy import IamPolicy
from tap_plugin.aws_core.models.iam_role import IamRole
from tap_plugin.aws_core.models.iam_user import IamUser
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

__all__ = [
    "AcmCertificate",
    "AcmPrivateCa",
    "Alb",
    "ApiGatewayHttpApi",
    "AvailabilityZone",
    "AwsAccessAnalyzer",
    "AwsAccount",
    "AwsAccountRegion",
    "AwsConfigAggregator",
    "AwsConfigDeliveryChannel",
    "AwsConfigRecorder",
    "AwsControlTowerEnabledBaseline",
    "AwsControlTowerEnabledControl",
    "AwsControlTowerLandingZone",
    "AwsDelegatedAdministration",
    "AwsGuardDutyDetector",
    "AwsIdentityCenterAccountAssignment",
    "AwsIdentityCenterGroup",
    "AwsIdentityCenterInstance",
    "AwsIdentityCenterPermissionSet",
    "AwsOrganization",
    "AwsOrganizationalUnit",
    "AwsOrganizationsPolicy",
    "AwsPolicyStatement",
    "AwsRegion",
    "AwsSecurityHubHub",
    "AwsServiceControlPolicy",
    "AwsTagPolicyRule",
    "BedrockModel",
    "CloudfrontDistribution",
    "CloudtrailTrail",
    "CloudwatchLogGroup",
    "CognitoUserPool",
    "DxConnection",
    "DxGateway",
    "DxVirtualInterface",
    "DynamoDbTable",
    "EbsVolume",
    "Ec2Instance",
    "EcrRepository",
    "EcsCluster",
    "EcsService",
    "EcsTask",
    "EksCluster",
    "ElasticIp",
    "ElasticacheCluster",
    "ElasticsearchDomain",
    "Elb",
    "EventbridgeRule",
    "IamOidcProvider",
    "IamPolicy",
    "IamRole",
    "IamUser",
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
