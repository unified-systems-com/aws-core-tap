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
from tap_plugin.aws_core.models.apigateway_rest_api import ApigatewayRestApi
from tap_plugin.aws_core.models.apigateway_usage_plan import ApigatewayUsagePlan
from tap_plugin.aws_core.models.apigateway_api_key import ApigatewayApiKey
from tap_plugin.aws_core.models.apigateway_client_certificate import ApigatewayClientCertificate
from tap_plugin.aws_core.models.apigateway_stage import ApigatewayStage
from tap_plugin.aws_core.models.apigateway_authorizer import ApigatewayAuthorizer
from tap_plugin.aws_core.models.apigateway_domain_name import ApigatewayDomainName
from tap_plugin.aws_core.models.apigateway_vpc_link import ApigatewayVpcLink
from tap_plugin.aws_core.models.rds_db_cluster import RdsDbCluster
from tap_plugin.aws_core.models.rds_db_snapshot import RdsDbSnapshot
from tap_plugin.aws_core.models.rds_db_cluster_snapshot import RdsDbClusterSnapshot
from tap_plugin.aws_core.models.rds_db_subnet_group import RdsDbSubnetGroup
from tap_plugin.aws_core.models.rds_db_parameter_group import RdsDbParameterGroup
from tap_plugin.aws_core.models.rds_db_cluster_parameter_group import RdsDbClusterParameterGroup
from tap_plugin.aws_core.models.rds_option_group import RdsOptionGroup
from tap_plugin.aws_core.models.rds_db_proxy import RdsDbProxy
from tap_plugin.aws_core.models.rds_event_subscription import RdsEventSubscription
from tap_plugin.aws_core.models.rds_global_cluster import RdsGlobalCluster
from tap_plugin.aws_core.models.aps_scraper import ApsScraper
from tap_plugin.aws_core.models.aps_workspace import ApsWorkspace
from tap_plugin.aws_core.models.batch_compute_environment import BatchComputeEnvironment
from tap_plugin.aws_core.models.batch_consumable_resource import BatchConsumableResource
from tap_plugin.aws_core.models.batch_job_queue import BatchJobQueue
from tap_plugin.aws_core.models.batch_scheduling_policy import BatchSchedulingPolicy
from tap_plugin.aws_core.models.batch_service_environment import BatchServiceEnvironment
from tap_plugin.aws_core.models.sagemaker_ai_workload_config import SagemakerAiWorkloadConfig
from tap_plugin.aws_core.models.sagemaker_algorithm import SagemakerAlgorithm
from tap_plugin.aws_core.models.sagemaker_cluster import SagemakerCluster
from tap_plugin.aws_core.models.sagemaker_cluster_scheduler_config import SagemakerClusterSchedulerConfig
from tap_plugin.aws_core.models.sagemaker_code_repository import SagemakerCodeRepository
from tap_plugin.aws_core.models.sagemaker_compute_quota import SagemakerComputeQuota
from tap_plugin.aws_core.models.sagemaker_endpoint_config import SagemakerEndpointConfig
from tap_plugin.aws_core.models.sagemaker_hub import SagemakerHub
from tap_plugin.aws_core.models.sagemaker_human_task_ui import SagemakerHumanTaskUi
from tap_plugin.aws_core.models.sagemaker_image import SagemakerImage
from tap_plugin.aws_core.models.sagemaker_inference_component import SagemakerInferenceComponent
from tap_plugin.aws_core.models.sagemaker_mlflow_app import SagemakerMlflowApp
from tap_plugin.aws_core.models.sagemaker_model import SagemakerModel
from tap_plugin.aws_core.models.sagemaker_model_package import SagemakerModelPackage
from tap_plugin.aws_core.models.sagemaker_model_package_group import SagemakerModelPackageGroup
from tap_plugin.aws_core.models.sagemaker_monitoring_schedule import SagemakerMonitoringSchedule
from tap_plugin.aws_core.models.sagemaker_notebook_instance import SagemakerNotebookInstance
from tap_plugin.aws_core.models.sagemaker_notebook_instance_lifecycle_config import SagemakerNotebookInstanceLifecycleConfig
from tap_plugin.aws_core.models.sagemaker_partner_app import SagemakerPartnerApp
from tap_plugin.aws_core.models.sagemaker_processing_job import SagemakerProcessingJob
from tap_plugin.aws_core.models.sagemaker_project import SagemakerProject
from tap_plugin.aws_core.models.sagemaker_trial_component import SagemakerTrialComponent
from tap_plugin.aws_core.models.sagemaker_workforce import SagemakerWorkforce
from tap_plugin.aws_core.models.sagemaker_workteam import SagemakerWorkteam
from tap_plugin.aws_core.models.apigatewayv2_portal_product import Apigatewayv2PortalProduct
from tap_plugin.aws_core.models.appstream_app_block import AppstreamAppBlock
from tap_plugin.aws_core.models.appstream_application import AppstreamApplication
from tap_plugin.aws_core.models.backup_report_plan import BackupReportPlan
from tap_plugin.aws_core.models.backupgateway_hypervisor import BackupgatewayHypervisor
from tap_plugin.aws_core.models.certificatemanager_acme_endpoint import CertificatemanagerAcmeEndpoint
from tap_plugin.aws_core.models.codestarconnections_connection import CodestarconnectionsConnection
from tap_plugin.aws_core.models.codestarconnections_repository_link import CodestarconnectionsRepositoryLink
from tap_plugin.aws_core.models.datasync_agent import DatasyncAgent
from tap_plugin.aws_core.models.datasync_task import DatasyncTask
from tap_plugin.aws_core.models.detective_graph import DetectiveGraph
from tap_plugin.aws_core.models.ec2_ipam_external_resource_verification_token import Ec2IpamExternalResourceVerificationToken
from tap_plugin.aws_core.models.ec2_ipam_internet_registry_association import Ec2IpamInternetRegistryAssociation
from tap_plugin.aws_core.models.ec2_secondary_network import Ec2SecondaryNetwork
from tap_plugin.aws_core.models.ecs_daemon import EcsDaemon
from tap_plugin.aws_core.models.emrcontainers_security_configuration import EmrcontainersSecurityConfiguration
from tap_plugin.aws_core.models.elasticache_serverless_cache_snapshot import ElasticacheServerlessCacheSnapshot
from tap_plugin.aws_core.models.elasticache_snapshot import ElasticacheSnapshot
from tap_plugin.aws_core.models.eventschemas_discoverer import EventschemasDiscoverer
from tap_plugin.aws_core.models.eventschemas_registry import EventschemasRegistry
from tap_plugin.aws_core.models.fsx_file_cache import FsxFileCache
from tap_plugin.aws_core.models.inspectorv2_connector import Inspectorv2Connector
from tap_plugin.aws_core.models.inspectorv2_filter import Inspectorv2Filter
from tap_plugin.aws_core.models.iot_ota_update import IotOtaUpdate
from tap_plugin.aws_core.models.iot_topic_rule_destination import IotTopicRuleDestination
from tap_plugin.aws_core.models.iotsecuretunneling_tunnel import IotsecuretunnelingTunnel
from tap_plugin.aws_core.models.iotsitewise_application import IotsitewiseApplication
from tap_plugin.aws_core.models.kafkaconnect_connector import KafkaconnectConnector
from tap_plugin.aws_core.models.kafkaconnect_custom_plugin import KafkaconnectCustomPlugin
from tap_plugin.aws_core.models.kafkaconnect_worker_configuration import KafkaconnectWorkerConfiguration
from tap_plugin.aws_core.models.kinesis_channel import KinesisChannel
from tap_plugin.aws_core.models.licensemanager_license import LicensemanagerLicense
from tap_plugin.aws_core.models.licensemanager_license_asset_group import LicensemanagerLicenseAssetGroup
from tap_plugin.aws_core.models.licensemanager_license_configuration import LicensemanagerLicenseConfiguration
from tap_plugin.aws_core.models.logs_log_anomaly_detector import LogsLogAnomalyDetector
from tap_plugin.aws_core.models.logs_scheduled_query import LogsScheduledQuery
from tap_plugin.aws_core.models.m2_application import M2Application
from tap_plugin.aws_core.models.m2_environment import M2Environment
from tap_plugin.aws_core.models.msk_configuration import MskConfiguration
from tap_plugin.aws_core.models.msk_replicator import MskReplicator
from tap_plugin.aws_core.models.memorydb_snapshot import MemorydbSnapshot
from tap_plugin.aws_core.models.networkfirewall_vpc_endpoint_association import NetworkfirewallVpcEndpointAssociation
from tap_plugin.aws_core.models.notifications_notification_configuration import NotificationsNotificationConfiguration
from tap_plugin.aws_core.models.osis_pipeline import OsisPipeline
from tap_plugin.aws_core.models.oam_link import OamLink
from tap_plugin.aws_core.models.oam_sink import OamSink
from tap_plugin.aws_core.models.outposts_outpost import OutpostsOutpost
from tap_plugin.aws_core.models.outposts_site import OutpostsSite
from tap_plugin.aws_core.models.ram_permission import RamPermission
from tap_plugin.aws_core.models.rds_db_cluster_endpoint import RdsDbClusterEndpoint
from tap_plugin.aws_core.models.rds_integration import RdsIntegration
from tap_plugin.aws_core.models.redshift_integration import RedshiftIntegration
from tap_plugin.aws_core.models.redshift_redshift_idc_application import RedshiftRedshiftIdcApplication
from tap_plugin.aws_core.models.resiliencehub_app import ResiliencehubApp
from tap_plugin.aws_core.models.resiliencehubv2_policy import Resiliencehubv2Policy
from tap_plugin.aws_core.models.resiliencehubv2_service import Resiliencehubv2Service
from tap_plugin.aws_core.models.resiliencehubv2_system import Resiliencehubv2System
from tap_plugin.aws_core.models.resourceexplorer2_index import Resourceexplorer2Index
from tap_plugin.aws_core.models.resourcegroups_tag_sync_task import ResourcegroupsTagSyncTask
from tap_plugin.aws_core.models.securityhub_configuration_policy import SecurityhubConfigurationPolicy
from tap_plugin.aws_core.models.securityhub_connector import SecurityhubConnector
from tap_plugin.aws_core.models.securitylake_subscriber import SecuritylakeSubscriber
from tap_plugin.aws_core.models.signer_signing_profile import SignerSigningProfile
from tap_plugin.aws_core.models.storagegateway_tape import StoragegatewayTape
from tap_plugin.aws_core.models.storagegateway_tape_pool import StoragegatewayTapePool
from tap_plugin.aws_core.models.storagegateway_volume import StoragegatewayVolume
from tap_plugin.aws_core.models.timestream_scheduled_query import TimestreamScheduledQuery
from tap_plugin.aws_core.models.transfer_server import TransferServer
from tap_plugin.aws_core.models.transfer_web_app import TransferWebApp
from tap_plugin.aws_core.models.translate_parallel_data import TranslateParallelData
from tap_plugin.aws_core.models.translate_terminology import TranslateTerminology
from tap_plugin.aws_core.models.bedrock_automated_reasoning_policy import BedrockAutomatedReasoningPolicy
from tap_plugin.aws_core.models.connect_instance import ConnectInstance
from tap_plugin.aws_core.models.drs_launch_configuration_template import DrsLaunchConfigurationTemplate
from tap_plugin.aws_core.models.drs_replication_configuration_template import DrsReplicationConfigurationTemplate
from tap_plugin.aws_core.models.drs_source_network import DrsSourceNetwork
from tap_plugin.aws_core.models.emrcontainers_job_template import EmrcontainersJobTemplate
from tap_plugin.aws_core.models.fsx_backup import FsxBackup
from tap_plugin.aws_core.models.mgn_connector import MgnConnector
from tap_plugin.aws_core.models.mgn_launch_configuration_template import MgnLaunchConfigurationTemplate
from tap_plugin.aws_core.models.mgn_network_migration_definition import MgnNetworkMigrationDefinition
from tap_plugin.aws_core.models.mgn_replication_configuration_template import MgnReplicationConfigurationTemplate
from tap_plugin.aws_core.models.mgn_wave import MgnWave
from tap_plugin.aws_core.models.resiliencehub_resiliency_policy import ResiliencehubResiliencyPolicy
from tap_plugin.aws_core.models.wellarchitected_agent_profile import WellarchitectedAgentProfile
from tap_plugin.aws_core.models.amazonmq_broker import AmazonmqBroker
from tap_plugin.aws_core.models.amazonmq_configuration import AmazonmqConfiguration
from tap_plugin.aws_core.models.appconfig_extension import AppconfigExtension
from tap_plugin.aws_core.models.appstream_app_block_builder import AppstreamAppBlockBuilder
from tap_plugin.aws_core.models.appstream_fleet import AppstreamFleet
from tap_plugin.aws_core.models.appstream_image_builder import AppstreamImageBuilder
from tap_plugin.aws_core.models.appstream_stack import AppstreamStack
from tap_plugin.aws_core.models.autoscaling_auto_scaling_group import AutoscalingAutoScalingGroup
from tap_plugin.aws_core.models.backup_restore_testing_plan import BackupRestoreTestingPlan
from tap_plugin.aws_core.models.backup_tiering_configuration import BackupTieringConfiguration
from tap_plugin.aws_core.models.batch_job_definition import BatchJobDefinition
from tap_plugin.aws_core.models.bedrock_guardrail import BedrockGuardrail
from tap_plugin.aws_core.models.cloudwatch_alarm_mute_rule import CloudwatchAlarmMuteRule
from tap_plugin.aws_core.models.codepipeline_webhook import CodepipelineWebhook
from tap_plugin.aws_core.models.comprehend_document_classifier import ComprehendDocumentClassifier
from tap_plugin.aws_core.models.comprehend_entity_recognizer import ComprehendEntityRecognizer
from tap_plugin.aws_core.models.comprehend_flywheel import ComprehendFlywheel
from tap_plugin.aws_core.models.connect_traffic_distribution_group import ConnectTrafficDistributionGroup
from tap_plugin.aws_core.models.dax_cluster import DaxCluster
from tap_plugin.aws_core.models.drs_recovery_plan import DrsRecoveryPlan
from tap_plugin.aws_core.models.datazone_domain import DatazoneDomain
from tap_plugin.aws_core.models.docdb_db_cluster_parameter_group import DocdbDbClusterParameterGroup
from tap_plugin.aws_core.models.docdb_db_subnet_group import DocdbDbSubnetGroup
from tap_plugin.aws_core.models.docdb_event_subscription import DocdbEventSubscription
from tap_plugin.aws_core.models.ec2_capacity_reservation import Ec2CapacityReservation
from tap_plugin.aws_core.models.ec2_capacity_reservation_fleet import Ec2CapacityReservationFleet
from tap_plugin.aws_core.models.ec2_instance_connect_endpoint import Ec2InstanceConnectEndpoint
from tap_plugin.aws_core.models.ec2_local_gateway_route_table import Ec2LocalGatewayRouteTable
from tap_plugin.aws_core.models.ec2_local_gateway_virtual_interface import Ec2LocalGatewayVirtualInterface
from tap_plugin.aws_core.models.ec2_local_gateway_virtual_interface_group import Ec2LocalGatewayVirtualInterfaceGroup
from tap_plugin.aws_core.models.ec2_network_insights_access_scope import Ec2NetworkInsightsAccessScope
from tap_plugin.aws_core.models.ec2_network_insights_path import Ec2NetworkInsightsPath
from tap_plugin.aws_core.models.ec2_placement_group import Ec2PlacementGroup
from tap_plugin.aws_core.models.ec2_transit_gateway_multicast_domain import Ec2TransitGatewayMulticastDomain
from tap_plugin.aws_core.models.ec2_verified_access_group import Ec2VerifiedAccessGroup
from tap_plugin.aws_core.models.ecs_daemon_task_definition import EcsDaemonTaskDefinition
from tap_plugin.aws_core.models.ecs_gateway import EcsGateway
from tap_plugin.aws_core.models.emrcontainers_virtual_cluster import EmrcontainersVirtualCluster
from tap_plugin.aws_core.models.emrserverless_application import EmrserverlessApplication
from tap_plugin.aws_core.models.elasticache_global_replication_group import ElasticacheGlobalReplicationGroup
from tap_plugin.aws_core.models.elasticache_replication_group import ElasticacheReplicationGroup
from tap_plugin.aws_core.models.elasticache_serverless_cache import ElasticacheServerlessCache
from tap_plugin.aws_core.models.elasticache_user import ElasticacheUser
from tap_plugin.aws_core.models.elasticache_user_group import ElasticacheUserGroup
from tap_plugin.aws_core.models.events_endpoint import EventsEndpoint
from tap_plugin.aws_core.models.fms_policy import FmsPolicy
from tap_plugin.aws_core.models.glue_registry import GlueRegistry
from tap_plugin.aws_core.models.glue_schema import GlueSchema
from tap_plugin.aws_core.models.greengrass_connector_definition import GreengrassConnectorDefinition
from tap_plugin.aws_core.models.greengrass_core_definition import GreengrassCoreDefinition
from tap_plugin.aws_core.models.greengrass_device_definition import GreengrassDeviceDefinition
from tap_plugin.aws_core.models.greengrass_function_definition import GreengrassFunctionDefinition
from tap_plugin.aws_core.models.greengrass_group import GreengrassGroup
from tap_plugin.aws_core.models.greengrass_logger_definition import GreengrassLoggerDefinition
from tap_plugin.aws_core.models.greengrass_resource_definition import GreengrassResourceDefinition
from tap_plugin.aws_core.models.greengrass_subscription_definition import GreengrassSubscriptionDefinition
from tap_plugin.aws_core.models.guardduty_custom_detection_rule_association import GuarddutyCustomDetectionRuleAssociation
from tap_plugin.aws_core.models.inspectorv2_code_security_integration import Inspectorv2CodeSecurityIntegration
from tap_plugin.aws_core.models.internetmonitor_monitor import InternetmonitorMonitor
from tap_plugin.aws_core.models.iot_authorizer import IotAuthorizer
from tap_plugin.aws_core.models.iot_billing_group import IotBillingGroup
from tap_plugin.aws_core.models.iot_ca_certificate import IotCaCertificate
from tap_plugin.aws_core.models.iot_certificate import IotCertificate
from tap_plugin.aws_core.models.iot_certificate_provider import IotCertificateProvider
from tap_plugin.aws_core.models.iot_command import IotCommand
from tap_plugin.aws_core.models.iot_domain_configuration import IotDomainConfiguration
from tap_plugin.aws_core.models.iot_fleet_metric import IotFleetMetric
from tap_plugin.aws_core.models.iot_job_template import IotJobTemplate
from tap_plugin.aws_core.models.iot_mitigation_action import IotMitigationAction
from tap_plugin.aws_core.models.iot_policy import IotPolicy
from tap_plugin.aws_core.models.iot_provisioning_template import IotProvisioningTemplate
from tap_plugin.aws_core.models.iot_scheduled_audit import IotScheduledAudit
from tap_plugin.aws_core.models.iot_security_profile import IotSecurityProfile
from tap_plugin.aws_core.models.iot_stream import IotStream
from tap_plugin.aws_core.models.iot_thing_group import IotThingGroup
from tap_plugin.aws_core.models.iot_thing_type import IotThingType
from tap_plugin.aws_core.models.iot_topic_rule import IotTopicRule

__all__ = [
    "IotTopicRule",
    "IotThingType",
    "IotThingGroup",
    "IotStream",
    "IotSecurityProfile",
    "IotScheduledAudit",
    "IotProvisioningTemplate",
    "IotPolicy",
    "IotMitigationAction",
    "IotJobTemplate",
    "IotFleetMetric",
    "IotDomainConfiguration",
    "IotCommand",
    "IotCertificateProvider",
    "IotCertificate",
    "IotCaCertificate",
    "IotBillingGroup",
    "IotAuthorizer",
    "InternetmonitorMonitor",
    "Inspectorv2CodeSecurityIntegration",
    "GuarddutyCustomDetectionRuleAssociation",
    "GreengrassSubscriptionDefinition",
    "GreengrassResourceDefinition",
    "GreengrassLoggerDefinition",
    "GreengrassGroup",
    "GreengrassFunctionDefinition",
    "GreengrassDeviceDefinition",
    "GreengrassCoreDefinition",
    "GreengrassConnectorDefinition",
    "GlueSchema",
    "GlueRegistry",
    "FmsPolicy",
    "EventsEndpoint",
    "ElasticacheUserGroup",
    "ElasticacheUser",
    "ElasticacheServerlessCache",
    "ElasticacheReplicationGroup",
    "ElasticacheGlobalReplicationGroup",
    "EmrserverlessApplication",
    "EmrcontainersVirtualCluster",
    "EcsGateway",
    "EcsDaemonTaskDefinition",
    "Ec2VerifiedAccessGroup",
    "Ec2TransitGatewayMulticastDomain",
    "Ec2PlacementGroup",
    "Ec2NetworkInsightsPath",
    "Ec2NetworkInsightsAccessScope",
    "Ec2LocalGatewayVirtualInterfaceGroup",
    "Ec2LocalGatewayVirtualInterface",
    "Ec2LocalGatewayRouteTable",
    "Ec2InstanceConnectEndpoint",
    "Ec2CapacityReservationFleet",
    "Ec2CapacityReservation",
    "DocdbEventSubscription",
    "DocdbDbSubnetGroup",
    "DocdbDbClusterParameterGroup",
    "DatazoneDomain",
    "DrsRecoveryPlan",
    "DaxCluster",
    "ConnectTrafficDistributionGroup",
    "ComprehendFlywheel",
    "ComprehendEntityRecognizer",
    "ComprehendDocumentClassifier",
    "CodepipelineWebhook",
    "CloudwatchAlarmMuteRule",
    "BedrockGuardrail",
    "BatchJobDefinition",
    "BackupTieringConfiguration",
    "BackupRestoreTestingPlan",
    "AutoscalingAutoScalingGroup",
    "AppstreamStack",
    "AppstreamImageBuilder",
    "AppstreamFleet",
    "AppstreamAppBlockBuilder",
    "AppconfigExtension",
    "AmazonmqConfiguration",
    "AmazonmqBroker",
    "WellarchitectedAgentProfile",
    "ResiliencehubResiliencyPolicy",
    "MgnWave",
    "MgnReplicationConfigurationTemplate",
    "MgnNetworkMigrationDefinition",
    "MgnLaunchConfigurationTemplate",
    "MgnConnector",
    "FsxBackup",
    "EmrcontainersJobTemplate",
    "DrsSourceNetwork",
    "DrsReplicationConfigurationTemplate",
    "DrsLaunchConfigurationTemplate",
    "ConnectInstance",
    "BedrockAutomatedReasoningPolicy",
    "TranslateTerminology",
    "TranslateParallelData",
    "TransferWebApp",
    "TransferServer",
    "TimestreamScheduledQuery",
    "StoragegatewayVolume",
    "StoragegatewayTapePool",
    "StoragegatewayTape",
    "SignerSigningProfile",
    "SecuritylakeSubscriber",
    "SecurityhubConnector",
    "SecurityhubConfigurationPolicy",
    "ResourcegroupsTagSyncTask",
    "Resourceexplorer2Index",
    "Resiliencehubv2System",
    "Resiliencehubv2Service",
    "Resiliencehubv2Policy",
    "ResiliencehubApp",
    "RedshiftRedshiftIdcApplication",
    "RedshiftIntegration",
    "RdsIntegration",
    "RdsDbClusterEndpoint",
    "RamPermission",
    "OutpostsSite",
    "OutpostsOutpost",
    "OamSink",
    "OamLink",
    "OsisPipeline",
    "NotificationsNotificationConfiguration",
    "NetworkfirewallVpcEndpointAssociation",
    "MemorydbSnapshot",
    "MskReplicator",
    "MskConfiguration",
    "M2Environment",
    "M2Application",
    "LogsScheduledQuery",
    "LogsLogAnomalyDetector",
    "LicensemanagerLicenseConfiguration",
    "LicensemanagerLicenseAssetGroup",
    "LicensemanagerLicense",
    "KinesisChannel",
    "KafkaconnectWorkerConfiguration",
    "KafkaconnectCustomPlugin",
    "KafkaconnectConnector",
    "IotsitewiseApplication",
    "IotsecuretunnelingTunnel",
    "IotTopicRuleDestination",
    "IotOtaUpdate",
    "Inspectorv2Filter",
    "Inspectorv2Connector",
    "FsxFileCache",
    "EventschemasRegistry",
    "EventschemasDiscoverer",
    "ElasticacheSnapshot",
    "ElasticacheServerlessCacheSnapshot",
    "EmrcontainersSecurityConfiguration",
    "EcsDaemon",
    "Ec2SecondaryNetwork",
    "Ec2IpamInternetRegistryAssociation",
    "Ec2IpamExternalResourceVerificationToken",
    "DetectiveGraph",
    "DatasyncTask",
    "DatasyncAgent",
    "CodestarconnectionsRepositoryLink",
    "CodestarconnectionsConnection",
    "CertificatemanagerAcmeEndpoint",
    "BackupgatewayHypervisor",
    "BackupReportPlan",
    "AppstreamApplication",
    "AppstreamAppBlock",
    "Apigatewayv2PortalProduct",
    "SagemakerWorkteam",
    "SagemakerWorkforce",
    "SagemakerTrialComponent",
    "SagemakerProject",
    "SagemakerProcessingJob",
    "SagemakerPartnerApp",
    "SagemakerNotebookInstanceLifecycleConfig",
    "SagemakerNotebookInstance",
    "SagemakerMonitoringSchedule",
    "SagemakerModelPackageGroup",
    "SagemakerModelPackage",
    "SagemakerModel",
    "SagemakerMlflowApp",
    "SagemakerInferenceComponent",
    "SagemakerImage",
    "SagemakerHumanTaskUi",
    "SagemakerHub",
    "SagemakerEndpointConfig",
    "SagemakerComputeQuota",
    "SagemakerCodeRepository",
    "SagemakerClusterSchedulerConfig",
    "SagemakerCluster",
    "SagemakerAlgorithm",
    "SagemakerAiWorkloadConfig",
    "BatchServiceEnvironment",
    "BatchSchedulingPolicy",
    "BatchJobQueue",
    "BatchConsumableResource",
    "BatchComputeEnvironment",
    "ApsWorkspace",
    "ApsScraper",
    "RdsGlobalCluster",
    "RdsEventSubscription",
    "RdsDbProxy",
    "RdsOptionGroup",
    "RdsDbClusterParameterGroup",
    "RdsDbParameterGroup",
    "RdsDbSubnetGroup",
    "RdsDbClusterSnapshot",
    "RdsDbSnapshot",
    "RdsDbCluster",
    "ApigatewayVpcLink",
    "ApigatewayDomainName",
    "ApigatewayAuthorizer",
    "ApigatewayStage",
    "ApigatewayClientCertificate",
    "ApigatewayApiKey",
    "ApigatewayUsagePlan",
    "ApigatewayRestApi",
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
