"""Every aws_core model declares its event time (req-aws-core-models-5; tap req-grid-entity-event-time).

Core copies the value a model declares into ``Entity.event_start``/``event_end``/``event_precision`` and stamps the
kind as the row's ``tap.time`` dimension. Every model is in exactly one of three states, and these tests hold them:

- declared: exactly the types below, each saying what it declares. Most read AWS's creation time from a member of
  ``configuration`` (core rules 29 and 30), where the collector stores the AWS answer as sent; a few read it through a
  reader function (core rules 23 to 28): core's epoch helpers, or ``tap_plugin.aws_core.times``;
- ``NO_EVENT_TIME``: AWS states no time for the thing itself, and ``EVENT_TIME_REASON`` says why;
- undeclared, on purpose: AWS states a time but it cannot be read truthfully (no zone, an unstated unit, an undocumented
  form, two spellings, or stored nowhere), and ``EVENT_TIME_PENDING`` says which (unified-systems-com/aws-core-tap#287).
  Plugin validation reports exactly these, and nothing else;
- every declared member path names a member of the botocore output shape the type's configuration holds;
- a time read from AWS reaches the spine as AWS stated it.
"""

from __future__ import annotations

import functools
import uuid
from datetime import UTC, datetime
from typing import Any

import botocore.session
import pytest
from botocore.utils import parse_timestamp
from django.apps import apps

import tap_plugin.aws_core.models  # noqa: F401 — registers the models
from tap.plugin_testing import find_plugin_source_root
from tap_grid import event_time
from tap_grid.caller_context import CallerContext
from tap_grid.dimension_names import view
from tap_grid.event_time import (
    NO_EVENT_TIME,
    Interval,
    declaration_problems,
    from_epoch_milliseconds,
    from_epoch_seconds,
)
from tap_grid.models import Entity
from tap_grid.services import create_node
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    iam_saml_providers_described,
    lambda_layer_versions_described,
    sqs_queues_described,
)
from tap_plugin.aws_core.collectors.boto3_collector.listing import ListingWalk
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
from tap_plugin.aws_core.times import offset_without_colon
from tap_plugins.validate.service import validate_plugin

PLUGIN_ROOT = find_plugin_source_root(__file__)
# Not an account number: the ARNs below only need to be well formed for the field they fill.
ACCOUNT = "0000"

#: The types that declare an event time on a typed field, and what each declares.
DECLARED: dict[str, Interval] = {
    "aws_core__aws_access_analyzer": Interval(start="created_at", kind="created"),
    "aws_core__aws_access_analyzer_finding": Interval(start="created_at", kind="created"),
    "aws_core__aws_delegated_administration": Interval(start="delegation_enabled_at", kind="created"),
    "aws_core__aws_ecs_task": Interval(start="started_at", kind="occurred", end="stopped_at"),
    "aws_core__aws_guardduty_finding": Interval(start="created_at", kind="created"),
    "aws_core__aws_iam_saml_provider": Interval(start="created_at", kind="created", end="valid_until"),
    "aws_core__aws_iam_server_certificate": Interval(start="upload_date", kind="created", end="expiration"),
    "aws_core__aws_identity_center_permission_set": Interval(start="created_at", kind="created"),
    "aws_core__aws_inspector2_finding": Interval(start="first_observed_at", kind="first_seen"),
    "aws_core__aws_inspector2_reachability_finding": Interval(start="first_observed_at", kind="first_seen"),
    "aws_core__aws_lambda_layer_version": Interval(start="created_date", kind="created", reader=offset_without_colon),
    "aws_core__aws_rds_db_cluster_snapshot": Interval(start="created_at", kind="created"),
    "aws_core__aws_rds_db_snapshot": Interval(start="created_at", kind="created"),
    "aws_core__aws_securityhub_finding": Interval(start="created_at", kind="created"),
    "aws_core__aws_securityhub_hub": Interval(start="subscribed_at", kind="created"),
    "aws_core__aws_ssm_managed_instance": Interval(start="registration_date", kind="created"),
}


#: The types that read AWS's creation time from a member of ``configuration``: the member path (dotted), the reader
#: function's name or None, and the end's member path or None. The kind is always ``created`` (core rule 8): each is
#: a long-lived thing that holds from its creation, until the end AWS states where it states one (core rule 7).
CONFIGURATION_DECLARED: dict[str, tuple[str, str | None, str | None]] = {
    "aws_core__aws_access_analyzer_archive_rule": ("createdAt", None, None),
    "aws_core__aws_acm_certificate": ("_hydrate.detail.data.Certificate.CreatedAt", None, "_hydrate.detail.data.Certificate.NotAfter"),
    "aws_core__aws_acm_private_ca": ("CreatedAt", None, "NotAfter"),
    "aws_core__aws_alb": ("CreatedTime", None, None),
    "aws_core__aws_amazonmq_broker": ("_hydrate.detail.data.Created", None, None),
    "aws_core__aws_amazonmq_configuration": ("Created", None, None),
    "aws_core__aws_apigateway_api_key": ("createdDate", None, None),
    "aws_core__aws_apigateway_client_certificate": ("createdDate", None, None),
    "aws_core__aws_apigateway_http_api": ("CreatedDate", None, None),
    "aws_core__aws_apigateway_rest_api": ("createdDate", None, None),
    "aws_core__aws_appconfig_experiment_definition": ("CreatedAt", None, None),
    "aws_core__aws_applicationautoscaling_scalable_target": ("CreationTime", None, None),
    "aws_core__aws_applicationautoscaling_scaling_policy": ("CreationTime", None, None),
    "aws_core__aws_appstream_app_block": ("CreatedTime", None, None),
    "aws_core__aws_appstream_app_block_builder": ("CreatedTime", None, None),
    "aws_core__aws_appstream_application": ("CreatedTime", None, None),
    "aws_core__aws_appstream_directory_config": ("CreatedTime", None, None),
    "aws_core__aws_appstream_entitlement": ("CreatedTime", None, None),
    "aws_core__aws_appstream_fleet": ("CreatedTime", None, None),
    "aws_core__aws_appstream_image_builder": ("CreatedTime", None, None),
    "aws_core__aws_appstream_stack": ("CreatedTime", None, None),
    "aws_core__aws_aps_anomaly_detector": ("createdAt", None, None),
    "aws_core__aws_aps_rule_groups_namespace": ("createdAt", None, None),
    "aws_core__aws_aps_scraper": ("createdAt", None, None),
    "aws_core__aws_aps_workspace": ("createdAt", None, None),
    "aws_core__aws_athena_capacity_reservation": ("CreationTime", None, None),
    "aws_core__aws_athena_work_group": ("CreationTime", None, None),
    "aws_core__aws_autoscaling_auto_scaling_group": ("CreatedTime", None, None),
    "aws_core__aws_autoscaling_launch_configuration": ("CreatedTime", None, None),
    "aws_core__aws_autoscalingplans_scaling_plan": ("CreationTime", None, None),
    "aws_core__aws_backup_backup_selection": ("CreationDate", None, None),
    "aws_core__aws_backup_framework": ("CreationTime", None, None),
    "aws_core__aws_backup_legal_hold": ("CreationDate", None, None),
    "aws_core__aws_backup_logically_air_gapped_backup_vault": ("_hydrate.detail.data.CreationDate", None, None),
    "aws_core__aws_backup_plan": ("CreationDate", None, None),
    "aws_core__aws_backup_report_plan": ("CreationTime", None, None),
    "aws_core__aws_backup_restore_testing_plan": ("CreationTime", None, None),
    "aws_core__aws_backup_restore_testing_selection": ("CreationTime", None, None),
    "aws_core__aws_backup_tiering_configuration": ("CreationTime", None, None),
    "aws_core__aws_backup_vault": ("CreationDate", None, None),
    "aws_core__aws_bedrock_agent": ("createdAt", None, None),
    "aws_core__aws_bedrock_agent_alias": ("createdAt", None, None),
    "aws_core__aws_bedrock_application_inference_profile": ("createdAt", None, None),
    "aws_core__aws_bedrock_automated_reasoning_policy": ("createdAt", None, None),
    "aws_core__aws_bedrock_automated_reasoning_policy_version": ("createdAt", None, None),
    "aws_core__aws_bedrock_blueprint": ("_hydrate.detail.data.blueprint.creationTime", None, None),
    "aws_core__aws_bedrock_data_automation_library": ("_hydrate.detail.data.library.creationTime", None, None),
    "aws_core__aws_bedrock_data_automation_project": ("_hydrate.detail.data.project.creationTime", None, None),
    "aws_core__aws_bedrock_flow": ("createdAt", None, None),
    "aws_core__aws_bedrock_flow_alias": ("createdAt", None, None),
    "aws_core__aws_bedrock_flow_version": ("createdAt", None, None),
    "aws_core__aws_bedrock_guardrail": ("createdAt", None, None),
    "aws_core__aws_bedrock_guardrail_version": ("createdAt", None, None),
    "aws_core__aws_bedrock_intelligent_prompt_router": ("createdAt", None, None),
    "aws_core__aws_bedrock_knowledge_base": ("createdAt", None, None),
    "aws_core__aws_bedrock_prompt": ("createdAt", None, None),
    "aws_core__aws_bedrock_prompt_version": ("createdAt", None, None),
    "aws_core__aws_bedrock_retrieval_instruction": ("_hydrate.detail.data.createdAt", None, None),
    "aws_core__aws_certificatemanager_acme_domain_validation": ("CreatedAt", None, None),
    "aws_core__aws_certificatemanager_acme_endpoint": ("CreatedAt", None, None),
    "aws_core__aws_certificatemanager_acme_external_account_binding": ("CreatedAt", None, "ExpiresAt"),
    "aws_core__aws_cloudformation_change_set": ("CreationTime", None, None),
    "aws_core__aws_cloudformation_generated_template": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_cloudformation_hook_version": ("TimeCreated", None, None),
    "aws_core__aws_cloudformation_module_version": ("TimeCreated", None, None),
    "aws_core__aws_cloudformation_resource_version": ("TimeCreated", None, None),
    "aws_core__aws_cloudformation_stack": ("CreationTime", None, "DeletionTime"),
    "aws_core__aws_cloudhsm_cluster": ("CreateTimestamp", None, None),
    "aws_core__aws_cloudtrail_event_data_store": ("CreatedTimestamp", None, None),
    "aws_core__aws_cloudwatch_log_group": ("creationTime", "from_epoch_milliseconds", None),
    "aws_core__aws_cloudwatch_metric_stream": ("CreationDate", None, None),
    "aws_core__aws_cloudwatch_omni_dashboard": ("createdAt", None, None),
    "aws_core__aws_codebuild_fleet": ("created", None, None),
    "aws_core__aws_codebuild_project": ("created", None, None),
    "aws_core__aws_codebuild_report_group": ("created", None, None),
    "aws_core__aws_codecommit_repository": ("creationDate", None, None),
    "aws_core__aws_codedeploy_application": ("createTime", None, None),
    "aws_core__aws_codedeploy_deployment_config": ("createTime", None, None),
    "aws_core__aws_cognito_identity_provider": ("CreationDate", None, None),
    "aws_core__aws_cognito_user_pool": ("CreationDate", None, None),
    "aws_core__aws_cognito_user_pool_client": ("CreationDate", None, None),
    "aws_core__aws_cognito_user_pool_group": ("CreationDate", None, None),
    "aws_core__aws_comprehend_document_classifier_endpoint": ("CreationTime", None, None),
    "aws_core__aws_comprehend_entity_recognizer_endpoint": ("CreationTime", None, None),
    "aws_core__aws_comprehend_flywheel": ("_hydrate.detail.data.FlywheelProperties.CreationTime", None, None),
    "aws_core__aws_config_aggregation_authorization": ("CreationTime", None, None),
    "aws_core__aws_config_connector": ("createdTime", None, None),
    "aws_core__aws_connect_evaluation_form": ("CreatedTime", None, None),
    "aws_core__aws_connect_instance": ("CreatedTime", None, None),
    "aws_core__aws_connect_notification": ("CreatedAt", None, "ExpiresAt"),
    "aws_core__aws_connect_rule": ("CreatedTime", None, None),
    "aws_core__aws_connect_task_template": ("CreatedTime", None, None),
    "aws_core__aws_databrew_dataset": ("CreateDate", None, None),
    "aws_core__aws_databrew_job": ("CreateDate", None, None),
    "aws_core__aws_databrew_project": ("CreateDate", None, None),
    "aws_core__aws_databrew_recipe": ("CreateDate", None, None),
    "aws_core__aws_databrew_ruleset": ("CreateDate", None, None),
    "aws_core__aws_databrew_schedule": ("CreateDate", None, None),
    "aws_core__aws_datasync_agent": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_datasync_task": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_datazone_domain": ("createdAt", None, None),
    "aws_core__aws_detective_graph": ("CreatedTime", None, None),
    "aws_core__aws_directoryservice_directory": ("LaunchTime", None, None),
    "aws_core__aws_dms_certificate": ("CertificateCreationDate", None, None),
    "aws_core__aws_dms_data_migration": ("DataMigrationCreateTime", None, None),
    "aws_core__aws_dms_data_provider": ("DataProviderCreationTime", None, None),
    "aws_core__aws_dms_instance_profile": ("InstanceProfileCreationTime", None, None),
    "aws_core__aws_dms_migration_project": ("MigrationProjectCreationTime", None, None),
    "aws_core__aws_dms_replication_config": ("ReplicationConfigCreateTime", None, None),
    "aws_core__aws_dms_replication_instance": ("InstanceCreateTime", None, None),
    "aws_core__aws_dms_replication_task": ("ReplicationTaskCreationDate", None, None),
    "aws_core__aws_drs_recovery_plan": ("createdAt", None, None),
    "aws_core__aws_dynamodb_table": ("CreationDateTime", None, None),
    "aws_core__aws_ebs_volume": ("CreateTime", None, None),
    "aws_core__aws_ec2_application_status_check": ("CreationTime", None, "DeletionTime"),
    "aws_core__aws_ec2_capacity_manager_data_export": ("CreateTime", None, None),
    "aws_core__aws_ec2_capacity_reservation": ("CreateDate", None, "EndDate"),
    "aws_core__aws_ec2_capacity_reservation_fleet": ("CreateTime", None, "EndDate"),
    "aws_core__aws_ec2_fleet": ("CreateTime", None, "ValidUntil"),
    "aws_core__aws_ec2_flow_log": ("CreationTime", None, None),
    "aws_core__aws_ec2_fpga_image": ("CreateTime", None, None),
    "aws_core__aws_ec2_instance": ("LaunchTime", None, None),
    "aws_core__aws_ec2_instance_connect_endpoint": ("CreatedAt", None, None),
    "aws_core__aws_ec2_key_pair": ("CreateTime", None, None),
    "aws_core__aws_ec2_launch_template": ("CreateTime", None, None),
    "aws_core__aws_ec2_network_insights_access_scope": ("CreatedDate", None, None),
    "aws_core__aws_ec2_network_insights_path": ("CreatedDate", None, None),
    "aws_core__aws_ec2_spot_fleet": ("CreateTime", None, "SpotFleetRequestConfig.ValidUntil"),
    "aws_core__aws_ec2_transit_gateway_connect": ("CreationTime", None, None),
    "aws_core__aws_ec2_transit_gateway_connect_peer": ("CreationTime", None, None),
    "aws_core__aws_ec2_transit_gateway_multicast_domain": ("CreationTime", None, None),
    "aws_core__aws_ec2_transit_gateway_peering_attachment": ("CreationTime", None, None),
    "aws_core__aws_ec2_transit_gateway_policy_table": ("CreationTime", None, None),
    "aws_core__aws_ec2_transit_gateway_route_table": ("CreationTime", None, None),
    "aws_core__aws_ec2_transit_gateway_vpc_attachment": ("CreationTime", None, None),
    "aws_core__aws_ec2_vpc_block_public_access_exclusion": ("CreationTimestamp", None, "DeletionTimestamp"),
    "aws_core__aws_ecr_public_repository": ("createdAt", None, None),
    "aws_core__aws_ecr_repository": ("createdAt", None, None),
    "aws_core__aws_ecr_repository_creation_template": ("createdAt", None, None),
    "aws_core__aws_ecs_daemon": ("_hydrate.detail.data.daemon.createdAt", None, None),
    "aws_core__aws_ecs_daemon_task_definition": ("registeredAt", None, None),
    "aws_core__aws_ecs_gateway": ("createdAt", None, None),
    "aws_core__aws_ecs_service": ("createdAt", None, None),
    "aws_core__aws_ecs_task_definition": ("registeredAt", None, None),
    "aws_core__aws_ecs_task_set": ("createdAt", None, None),
    "aws_core__aws_efs_file_system": ("CreationTime", None, None),
    "aws_core__aws_eks_access_entry": ("createdAt", None, None),
    "aws_core__aws_eks_addon": ("createdAt", None, None),
    "aws_core__aws_eks_capability": ("createdAt", None, None),
    "aws_core__aws_eks_certificate_authority": ("createdAt", None, None),
    "aws_core__aws_eks_cluster": ("createdAt", None, None),
    "aws_core__aws_eks_fargate_profile": ("createdAt", None, None),
    "aws_core__aws_eks_nodegroup": ("createdAt", None, None),
    "aws_core__aws_elasticache_cluster": ("CacheClusterCreateTime", None, None),
    "aws_core__aws_elasticache_replication_group": ("ReplicationGroupCreateTime", None, None),
    "aws_core__aws_elasticache_serverless_cache": ("CreateTime", None, None),
    "aws_core__aws_elasticache_serverless_cache_snapshot": ("CreateTime", None, "ExpiryTime"),
    "aws_core__aws_elasticbeanstalk_application": ("DateCreated", None, None),
    "aws_core__aws_elasticbeanstalk_application_version": ("DateCreated", None, None),
    "aws_core__aws_elasticbeanstalk_environment": ("DateCreated", None, None),
    "aws_core__aws_elb": ("CreatedTime", None, None),
    "aws_core__aws_emr_cluster": ("Status.Timeline.CreationDateTime", None, "Status.Timeline.EndDateTime"),
    "aws_core__aws_emr_security_configuration": ("CreationDateTime", None, None),
    "aws_core__aws_emr_studio": ("CreationTime", None, None),
    "aws_core__aws_emrcontainers_endpoint": ("createdAt", None, None),
    "aws_core__aws_emrcontainers_job_template": ("createdAt", None, None),
    "aws_core__aws_emrcontainers_security_configuration": ("createdAt", None, None),
    "aws_core__aws_emrcontainers_virtual_cluster": ("createdAt", None, None),
    "aws_core__aws_emrserverless_application": ("createdAt", None, None),
    "aws_core__aws_eventbridge_api_destination": ("CreationTime", None, None),
    "aws_core__aws_eventbridge_archive": ("CreationTime", None, None),
    "aws_core__aws_eventbridge_connection": ("CreationTime", None, None),
    "aws_core__aws_eventbridge_event_bus": ("CreationTime", None, None),
    "aws_core__aws_events_endpoint": ("CreationTime", None, None),
    "aws_core__aws_fsx_backup": ("CreationTime", None, None),
    "aws_core__aws_fsx_data_repository_association": ("CreationTime", None, None),
    "aws_core__aws_fsx_file_cache": ("CreationTime", None, None),
    "aws_core__aws_fsx_file_system": ("CreationTime", None, None),
    "aws_core__aws_fsx_s3_access_point_attachment": ("CreationTime", None, None),
    "aws_core__aws_fsx_snapshot": ("CreationTime", None, None),
    "aws_core__aws_fsx_storage_virtual_machine": ("CreationTime", None, None),
    "aws_core__aws_fsx_volume": ("CreationTime", None, None),
    "aws_core__aws_glue_blueprint": ("CreatedOn", None, None),
    "aws_core__aws_glue_catalog": ("CreateTime", None, None),
    "aws_core__aws_glue_connection": ("CreationTime", None, None),
    "aws_core__aws_glue_crawler": ("CreationTime", None, None),
    "aws_core__aws_glue_data_quality_ruleset": ("CreatedOn", None, None),
    "aws_core__aws_glue_database": ("CreateTime", None, None),
    "aws_core__aws_glue_dev_endpoint": ("CreatedTimestamp", None, None),
    "aws_core__aws_glue_integration": ("CreateTime", None, None),
    "aws_core__aws_glue_job": ("CreatedOn", None, None),
    "aws_core__aws_glue_ml_transform": ("CreatedOn", None, None),
    "aws_core__aws_glue_security_configuration": ("CreatedTimeStamp", None, None),
    "aws_core__aws_glue_session": ("CreatedOn", None, None),
    "aws_core__aws_glue_table": ("CreateTime", None, None),
    "aws_core__aws_glue_usage_profile": ("CreatedOn", None, None),
    "aws_core__aws_glue_workflow": ("CreatedOn", None, None),
    "aws_core__aws_grafana_workspace": ("created", None, None),
    "aws_core__aws_greengrass_connector_definition": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_connector_definition_version": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_core_definition": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_core_definition_version": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_device_definition": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_device_definition_version": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_function_definition": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_function_definition_version": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_group": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_group_version": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_logger_definition": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_logger_definition_version": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_resource_definition": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_resource_definition_version": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_subscription_definition": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_greengrass_subscription_definition_version": ("CreationTimestamp", "from_epoch_milliseconds", None),
    "aws_core__aws_guardduty_custom_detection_rule_association": ("CreatedAt", None, "ExpiresAt"),
    "aws_core__aws_guardduty_filter": ("CreatedAt", None, None),
    "aws_core__aws_guardduty_malware_protection_plan": ("CreatedAt", None, None),
    "aws_core__aws_guardduty_threat_entity_set": ("CreatedAt", None, None),
    "aws_core__aws_guardduty_trusted_entity_set": ("CreatedAt", None, None),
    "aws_core__aws_iam_group": ("CreateDate", None, None),
    "aws_core__aws_iam_instance_profile": ("CreateDate", None, None),
    "aws_core__aws_iam_oidc_provider": ("CreateDate", None, None),
    "aws_core__aws_iam_policy": ("CreateDate", None, None),
    "aws_core__aws_iam_role": ("_hydrate.role.data.Role.CreateDate", None, None),
    "aws_core__aws_iam_user": ("_hydrate.user.data.User.CreateDate", None, None),
    "aws_core__aws_identity_center_application": ("CreatedDate", None, None),
    "aws_core__aws_inspector_assessment_target": ("createdAt", None, None),
    "aws_core__aws_inspector_assessment_template": ("createdAt", None, None),
    "aws_core__aws_inspectorv2_code_security_integration": ("createdOn", None, None),
    "aws_core__aws_inspectorv2_connector": ("createdAt", None, None),
    "aws_core__aws_inspectorv2_filter": ("createdAt", None, None),
    "aws_core__aws_internetmonitor_monitor": ("_hydrate.detail.data.CreatedAt", None, None),
    "aws_core__aws_iot_authorizer": ("_hydrate.detail.data.authorizerDescription.creationDate", None, None),
    "aws_core__aws_iot_billing_group": ("_hydrate.detail.data.billingGroupMetadata.creationDate", None, None),
    "aws_core__aws_iot_ca_certificate": ("creationDate", None, None),
    "aws_core__aws_iot_certificate": ("creationDate", None, None),
    "aws_core__aws_iot_certificate_provider": ("_hydrate.detail.data.creationDate", None, None),
    "aws_core__aws_iot_command": ("_hydrate.detail.data.createdAt", None, None),
    "aws_core__aws_iot_custom_metric": ("creationDate", None, None),
    "aws_core__aws_iot_dimension": ("creationDate", None, None),
    "aws_core__aws_iot_fleet_metric": ("_hydrate.detail.data.creationDate", None, None),
    "aws_core__aws_iot_job_template": ("_hydrate.detail.data.createdAt", None, None),
    "aws_core__aws_iot_mitigation_action": ("_hydrate.detail.data.creationDate", None, None),
    "aws_core__aws_iot_ota_update": ("creationDate", None, None),
    "aws_core__aws_iot_policy": ("_hydrate.detail.data.creationDate", None, None),
    "aws_core__aws_iot_provisioning_template": ("_hydrate.detail.data.creationDate", None, None),
    "aws_core__aws_iot_role_alias": ("creationDate", None, None),
    "aws_core__aws_iot_software_package": ("creationDate", None, None),
    "aws_core__aws_iot_software_package_version": ("creationDate", None, None),
    "aws_core__aws_iot_stream": ("_hydrate.detail.data.streamInfo.createdAt", None, None),
    "aws_core__aws_iot_thing_group": ("_hydrate.detail.data.thingGroupMetadata.creationDate", None, None),
    "aws_core__aws_iot_thing_type": ("thingTypeMetadata.creationDate", None, None),
    "aws_core__aws_iot_topic_rule": ("createdAt", None, None),
    "aws_core__aws_iot_topic_rule_destination": ("createdAt", None, None),
    "aws_core__aws_iotsecuretunneling_tunnel": ("_hydrate.detail.data.tunnel.createdAt", None, None),
    "aws_core__aws_iotsitewise_access_policy": ("creationDate", None, None),
    "aws_core__aws_iotsitewise_application": ("_hydrate.detail.data.createdAt", None, None),
    "aws_core__aws_iotsitewise_asset": ("creationDate", None, None),
    "aws_core__aws_iotsitewise_asset_model": ("creationDate", None, None),
    "aws_core__aws_iotsitewise_computation_model": ("creationDate", None, None),
    "aws_core__aws_iotsitewise_dashboard": ("creationDate", None, None),
    "aws_core__aws_iotsitewise_dataset": ("creationDate", None, None),
    "aws_core__aws_iotsitewise_gateway": ("creationDate", None, None),
    "aws_core__aws_iotsitewise_pipeline": ("createdAt", None, None),
    "aws_core__aws_iotsitewise_portal": ("creationDate", None, None),
    "aws_core__aws_iotsitewise_project": ("creationDate", None, None),
    "aws_core__aws_iotsitewise_task": ("createdAt", None, None),
    "aws_core__aws_iotsitewise_workspace": ("createdAt", None, None),
    "aws_core__aws_iottwinmaker_component_type": ("creationDateTime", None, None),
    "aws_core__aws_iottwinmaker_entity": ("creationDateTime", None, None),
    "aws_core__aws_iottwinmaker_scene": ("creationDateTime", None, None),
    "aws_core__aws_iottwinmaker_sync_job": ("creationDateTime", None, None),
    "aws_core__aws_iottwinmaker_workspace": ("creationDateTime", None, None),
    "aws_core__aws_kafkaconnect_connector": ("creationTime", None, None),
    "aws_core__aws_kafkaconnect_custom_plugin": ("creationTime", None, None),
    "aws_core__aws_kafkaconnect_worker_configuration": ("creationTime", None, None),
    "aws_core__aws_kendra_data_source": ("CreatedAt", None, None),
    "aws_core__aws_kendra_faq": ("CreatedAt", None, None),
    "aws_core__aws_kendra_index": ("CreatedAt", None, None),
    "aws_core__aws_kendra_query_suggestions_block_list": ("CreatedAt", None, None),
    "aws_core__aws_kendra_thesaurus": ("CreatedAt", None, None),
    "aws_core__aws_kendraranking_execution_plan": ("CreatedAt", None, None),
    "aws_core__aws_kinesis_channel": ("_hydrate.detail.data.ChannelDescription.ChannelCreationTimestamp", None, None),
    "aws_core__aws_kinesis_stream": ("StreamCreationTimestamp", None, None),
    "aws_core__aws_kinesis_stream_consumer": ("ConsumerCreationTimestamp", None, None),
    "aws_core__aws_kinesisanalytics_application": ("_hydrate.detail.data.ApplicationDetail.CreateTimestamp", None, None),
    "aws_core__aws_kinesisanalyticsv2_application": ("_hydrate.detail.data.ApplicationDetail.CreateTimestamp", None, None),
    "aws_core__aws_kinesisfirehose_delivery_stream": ("CreateTimestamp", None, None),
    "aws_core__aws_kinesisvideo_signaling_channel": ("CreationTime", None, None),
    "aws_core__aws_kinesisvideo_stream": ("CreationTime", None, None),
    "aws_core__aws_kms_alias": ("CreationDate", None, None),
    "aws_core__aws_kms_key": ("CreationDate", None, None),
    "aws_core__aws_lambda_function_url": ("CreationTime", "offset_without_colon", None),
    "aws_core__aws_lex_bot_alias": ("creationDateTime", None, None),
    "aws_core__aws_lex_bot_version": ("creationDateTime", None, None),
    "aws_core__aws_licensemanager_license": ("CreateTime", None, None),
    "aws_core__aws_licensemanager_usersub_license_server_endpoint": ("CreationTime", None, None),
    "aws_core__aws_location_api_key": ("CreateTime", None, "ExpireTime"),
    "aws_core__aws_location_geofence_collection": ("CreateTime", None, None),
    "aws_core__aws_location_map": ("CreateTime", None, None),
    "aws_core__aws_location_place_index": ("CreateTime", None, None),
    "aws_core__aws_location_route_calculator": ("CreateTime", None, None),
    "aws_core__aws_location_tracker": ("CreateTime", None, None),
    "aws_core__aws_logs_destination": ("creationTime", "from_epoch_milliseconds", None),
    "aws_core__aws_logs_metric_filter": ("creationTime", "from_epoch_milliseconds", None),
    "aws_core__aws_logs_subscription_filter": ("creationTime", "from_epoch_milliseconds", None),
    "aws_core__aws_m2_application": ("_hydrate.detail.data.creationTime", None, None),
    "aws_core__aws_m2_environment": ("_hydrate.detail.data.creationTime", None, None),
    "aws_core__aws_managedblockchain_accessor": ("CreationDate", None, None),
    "aws_core__aws_managedblockchain_member": ("CreationDate", None, None),
    "aws_core__aws_managedblockchain_node": ("CreationDate", None, None),
    "aws_core__aws_mediaconvert_job_template": ("CreatedAt", None, None),
    "aws_core__aws_mediaconvert_preset": ("CreatedAt", None, None),
    "aws_core__aws_mediaconvert_queue": ("CreatedAt", None, None),
    "aws_core__aws_mgn_network_migration_definition": ("_hydrate.detail.data.createdAt", None, None),
    "aws_core__aws_mgn_wave": ("creationDateTime", None, None),
    "aws_core__aws_msk_channel": ("CreationTime", None, None),
    "aws_core__aws_msk_cluster": ("CreationTime", None, None),
    "aws_core__aws_msk_configuration": ("CreationTime", None, None),
    "aws_core__aws_msk_replicator": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_msk_serverless_cluster": ("CreationTime", None, None),
    "aws_core__aws_msk_vpc_connection": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_nat_gateway": ("CreateTime", None, None),
    "aws_core__aws_networkmanager_attachment": ("CreatedAt", None, None),
    "aws_core__aws_networkmanager_connect_peer": ("CreatedAt", None, None),
    "aws_core__aws_networkmanager_core_network": ("_hydrate.detail.data.CoreNetwork.CreatedAt", None, None),
    "aws_core__aws_networkmanager_device": ("CreatedAt", None, None),
    "aws_core__aws_networkmanager_global_network": ("CreatedAt", None, None),
    "aws_core__aws_networkmanager_link": ("CreatedAt", None, None),
    "aws_core__aws_networkmanager_site": ("CreatedAt", None, None),
    "aws_core__aws_networkmanager_transit_gateway_peering": ("CreatedAt", None, None),
    "aws_core__aws_notifications_event_rule": ("creationTime", None, None),
    "aws_core__aws_notifications_notification_configuration": ("creationTime", None, None),
    "aws_core__aws_opensearchservice_application": ("_hydrate.detail.data.createdAt", None, None),
    "aws_core__aws_osis_pipeline": ("_hydrate.detail.data.Pipeline.CreatedAt", None, None),
    "aws_core__aws_pinpoint_app": ("CreationDate", None, None),
    "aws_core__aws_pinpoint_campaign": ("CreationDate", None, None),
    "aws_core__aws_pinpoint_email_template": ("CreationDate", None, None),
    "aws_core__aws_pinpoint_in_app_template": ("CreationDate", None, None),
    "aws_core__aws_pinpoint_push_template": ("CreationDate", None, None),
    "aws_core__aws_pinpoint_segment": ("CreationDate", None, None),
    "aws_core__aws_pinpoint_sms_template": ("CreationDate", None, None),
    "aws_core__aws_qbusiness_application": ("createdAt", None, None),
    "aws_core__aws_qbusiness_data_accessor": ("createdAt", None, None),
    "aws_core__aws_qbusiness_data_source": ("createdAt", None, None),
    "aws_core__aws_qbusiness_index": ("createdAt", None, None),
    "aws_core__aws_qbusiness_plugin": ("createdAt", None, None),
    "aws_core__aws_qbusiness_web_experience": ("createdAt", None, None),
    "aws_core__aws_quicksight_action_connector": ("CreatedTime", None, None),
    "aws_core__aws_quicksight_agent": ("CreatedAt", None, None),
    "aws_core__aws_quicksight_analysis": ("CreatedTime", None, None),
    "aws_core__aws_quicksight_approval_policy": ("CreatedAt", None, None),
    "aws_core__aws_quicksight_brand": ("CreatedTime", None, None),
    "aws_core__aws_quicksight_dashboard": ("CreatedTime", None, None),
    "aws_core__aws_quicksight_data_set": ("CreatedTime", None, None),
    "aws_core__aws_quicksight_data_source": ("CreatedTime", None, None),
    "aws_core__aws_quicksight_dlp_setting": ("CreatedAt", None, None),
    "aws_core__aws_quicksight_flow": ("CreatedTime", None, None),
    "aws_core__aws_quicksight_folder": ("CreatedTime", None, None),
    "aws_core__aws_quicksight_knowledge_base": ("CreatedAt", None, None),
    "aws_core__aws_quicksight_limits_profile": ("createdAt", None, None),
    "aws_core__aws_quicksight_o_auth_client_application": ("CreatedTime", None, None),
    "aws_core__aws_quicksight_space": ("createdAt", None, None),
    "aws_core__aws_quicksight_template": ("CreatedTime", None, None),
    "aws_core__aws_quicksight_theme": ("CreatedTime", None, None),
    "aws_core__aws_quicksight_vpc_connection": ("CreatedTime", None, None),
    "aws_core__aws_ram_permission": ("creationTime", None, None),
    "aws_core__aws_ram_resource_share": ("creationTime", None, None),
    "aws_core__aws_rds_blue_green_deployment": ("CreateTime", None, None),
    "aws_core__aws_rds_db_cluster": ("ClusterCreateTime", None, None),
    "aws_core__aws_rds_db_proxy": ("CreatedDate", None, None),
    "aws_core__aws_rds_db_proxy_endpoint": ("CreatedDate", None, None),
    "aws_core__aws_rds_db_proxy_target_group": ("CreatedDate", None, None),
    "aws_core__aws_rds_instance": ("InstanceCreateTime", None, None),
    "aws_core__aws_rds_integration": ("CreateTime", None, None),
    "aws_core__aws_redshift_cluster": ("ClusterCreateTime", None, None),
    "aws_core__aws_redshift_endpoint_access": ("EndpointCreateTime", None, None),
    "aws_core__aws_redshift_event_subscription": ("SubscriptionCreationTime", None, None),
    "aws_core__aws_redshift_integration": ("CreateTime", None, None),
    "aws_core__aws_redshift_snapshot": ("SnapshotCreateTime", None, None),
    "aws_core__aws_redshiftserverless_namespace": ("creationDate", None, None),
    "aws_core__aws_redshiftserverless_snapshot": ("snapshotCreateTime", None, None),
    "aws_core__aws_redshiftserverless_workgroup": ("creationDate", None, None),
    "aws_core__aws_rekognition_collection": ("CreationTimestamp", None, None),
    "aws_core__aws_rekognition_dataset": ("CreationTimestamp", None, None),
    "aws_core__aws_rekognition_project": ("CreationTimestamp", None, None),
    "aws_core__aws_rekognition_stream_processor": ("CreationTimestamp", None, None),
    "aws_core__aws_resiliencehub_app": ("_hydrate.detail.data.app.creationTime", None, None),
    "aws_core__aws_resiliencehub_resiliency_policy": ("creationTime", None, None),
    "aws_core__aws_resiliencehubv2_policy": ("_hydrate.detail.data.policy.createdAt", None, None),
    "aws_core__aws_resiliencehubv2_service": ("_hydrate.detail.data.service.createdAt", None, None),
    "aws_core__aws_resiliencehubv2_service_function": ("createdAt", None, None),
    "aws_core__aws_resiliencehubv2_system": ("createdAt", None, None),
    "aws_core__aws_resiliencehubv2_user_journey": ("createdAt", None, None),
    "aws_core__aws_resourcegroups_tag_sync_task": ("CreatedAt", None, None),
    "aws_core__aws_rolesanywhere_crl": ("createdAt", None, None),
    "aws_core__aws_rolesanywhere_profile": ("createdAt", None, None),
    "aws_core__aws_rolesanywhere_trust_anchor": ("createdAt", None, None),
    "aws_core__aws_route53profiles_profile": ("_hydrate.detail.data.Profile.CreationTime", None, None),
    "aws_core__aws_route53profiles_profile_association": ("CreationTime", None, None),
    "aws_core__aws_s3_access_grant": ("CreatedAt", None, None),
    "aws_core__aws_s3_access_grants_instance": ("CreatedAt", None, None),
    "aws_core__aws_s3_access_grants_location": ("CreatedAt", None, None),
    "aws_core__aws_s3_bucket": ("CreationDate", None, None),
    "aws_core__aws_s3outposts_bucket": ("CreationDate", None, None),
    "aws_core__aws_s3outposts_endpoint": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_ai_workload_config": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_algorithm": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_app_image_config": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_cluster": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_cluster_scheduler_config": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_code_repository": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_compute_quota": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_data_quality_job_definition": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_device_fleet": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_domain": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_endpoint": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_endpoint_config": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_experiment": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_feature_group": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_hub": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_human_task_ui": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_image": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_image_version": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_inference_component": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_inference_experiment": ("CreationTime", None, "Schedule.EndTime"),
    "aws_core__aws_sagemaker_mlflow_app": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_mlflow_tracking_server": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_model": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_model_bias_job_definition": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_model_card": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_model_explainability_job_definition": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_model_package": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_model_package_group": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_model_quality_job_definition": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_monitoring_schedule": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_notebook_instance": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_notebook_instance_lifecycle_config": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_partner_app": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_pipeline": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_processing_job": ("_hydrate.detail.data.CreationTime", None, "_hydrate.detail.data.ProcessingEndTime"),
    "aws_core__aws_sagemaker_project": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_sagemaker_space": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_studio_lifecycle_config": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_trial_component": ("_hydrate.detail.data.CreationTime", None, "_hydrate.detail.data.EndTime"),
    "aws_core__aws_sagemaker_user_profile": ("CreationTime", None, None),
    "aws_core__aws_sagemaker_workforce": ("CreateDate", None, None),
    "aws_core__aws_sagemaker_workteam": ("CreateDate", None, None),
    "aws_core__aws_scheduler_schedule": ("_hydrate.detail.data.CreationDate", None, "_hydrate.detail.data.EndDate"),
    "aws_core__aws_scheduler_schedule_group": ("CreationDate", None, None),
    "aws_core__aws_secrets_manager_secret": ("CreatedDate", None, None),
    "aws_core__aws_securityhub_automation_rule": ("CreatedAt", None, None),
    "aws_core__aws_securityhub_automation_rule_v2": ("CreatedAt", None, None),
    "aws_core__aws_securityhub_connector": ("CreatedAt", None, None),
    "aws_core__aws_securityhub_connector_v2": ("CreatedAt", None, None),
    "aws_core__aws_securityhub_hub_v2": ("SubscribedAt", None, None),
    "aws_core__aws_securitylake_subscriber": ("createdAt", None, None),
    "aws_core__aws_servicecatalog_portfolio": ("CreatedTime", None, None),
    "aws_core__aws_servicecatalog_product": ("CreatedTime", None, None),
    "aws_core__aws_servicecatalog_provisioned_product": ("CreatedTime", None, None),
    "aws_core__aws_servicecatalogappregistry_application": ("creationTime", None, None),
    "aws_core__aws_servicecatalogappregistry_attribute_group": ("creationTime", None, None),
    "aws_core__aws_servicediscovery_http_namespace": ("CreateDate", None, None),
    "aws_core__aws_servicediscovery_private_dns_namespace": ("CreateDate", None, None),
    "aws_core__aws_servicediscovery_public_dns_namespace": ("CreateDate", None, None),
    "aws_core__aws_servicediscovery_service": ("CreateDate", None, None),
    "aws_core__aws_ses_mail_manager_addon_instance": ("CreatedTimestamp", None, None),
    "aws_core__aws_ses_mail_manager_addon_subscription": ("CreatedTimestamp", None, None),
    "aws_core__aws_ses_mail_manager_address_list": ("CreatedTimestamp", None, None),
    "aws_core__aws_ses_mail_manager_archive": ("CreatedTimestamp", None, None),
    "aws_core__aws_ses_mail_manager_ingress_point": ("CreatedTimestamp", None, None),
    "aws_core__aws_ses_mail_manager_relay": ("CreatedTimestamp", None, None),
    "aws_core__aws_ses_mail_manager_rule_set": ("CreatedDate", None, None),
    "aws_core__aws_ses_mail_manager_traffic_policy": ("CreatedTimestamp", None, None),
    "aws_core__aws_ses_multi_region_endpoint": ("CreatedTimestamp", None, None),
    "aws_core__aws_ses_receipt_rule_set": ("CreatedTimestamp", None, None),
    "aws_core__aws_ses_template": ("CreatedTimestamp", None, None),
    "aws_core__aws_ses_tenant": ("CreatedTimestamp", None, None),
    "aws_core__aws_sqs_queue": ("CreatedTimestamp", "from_epoch_seconds", None),
    "aws_core__aws_ssm_cloud_connector": ("CreatedAt", None, None),
    "aws_core__aws_ssm_document": ("_hydrate.detail.data.Document.CreatedDate", None, None),
    "aws_core__aws_ssm_resource_data_sync": ("SyncCreatedTime", None, None),
    "aws_core__aws_stepfunctions_activity": ("creationDate", None, None),
    "aws_core__aws_stepfunctions_state_machine": ("_hydrate.detail.data.creationDate", None, None),
    "aws_core__aws_stepfunctions_state_machine_alias": ("creationDate", None, None),
    "aws_core__aws_stepfunctions_state_machine_version": ("creationDate", None, None),
    "aws_core__aws_synthetics_canary": ("Timeline.Created", None, None),
    "aws_core__aws_synthetics_group": ("_hydrate.detail.data.Group.CreatedTime", None, None),
    "aws_core__aws_textract_adapter": ("_hydrate.detail.data.CreationTime", None, None),
    "aws_core__aws_timestream_database": ("CreationTime", None, None),
    "aws_core__aws_timestream_influx_db_backup": ("createdAt", None, None),
    "aws_core__aws_timestream_scheduled_query": ("_hydrate.detail.data.ScheduledQuery.CreationTime", None, None),
    "aws_core__aws_timestream_table": ("CreationTime", None, None),
    "aws_core__aws_transcribe_call_analytics_category": ("CreateTime", None, None),
    "aws_core__aws_transfer_host_key": ("DateImported", None, None),
    "aws_core__aws_transit_gateway": ("CreationTime", None, None),
    "aws_core__aws_transit_gateway_attachment": ("CreationTime", None, None),
    "aws_core__aws_translate_parallel_data": ("CreatedAt", None, None),
    "aws_core__aws_translate_terminology": ("CreatedAt", None, None),
    "aws_core__aws_verifiedpermissions_identity_source": ("createdDate", None, None),
    "aws_core__aws_verifiedpermissions_policy": ("createdDate", None, None),
    "aws_core__aws_verifiedpermissions_policy_store": ("_hydrate.detail.data.createdDate", None, None),
    "aws_core__aws_verifiedpermissions_policy_store_alias": ("createdAt", None, None),
    "aws_core__aws_verifiedpermissions_policy_template": ("createdDate", None, None),
    "aws_core__aws_vpc_endpoint": ("CreationTimestamp", None, None),
    "aws_core__aws_wellarchitected_agent_context": ("createdAt", None, None),
    "aws_core__aws_wellarchitected_agent_goal": ("createdAt", None, None),
    "aws_core__aws_wellarchitected_agent_profile": ("createdAt", None, None),
    "aws_core__aws_wellarchitected_lens": ("CreatedAt", None, None),
    "aws_core__aws_wellarchitected_profile": ("_hydrate.detail.data.Profile.CreatedAt", None, None),
    "aws_core__aws_xray_sampling_rule": ("CreatedAt", None, None),
}

#: The types left undeclared, each with why (unified-systems-com/aws-core-tap#287):
#: zoneless — text with a time of day and no zone AWS documents (core rule 24 lets no reader assume one);
#: unit — an epoch number whose unit AWS's documentation of the member does not state;
#: undocumented — a plain string whose form AWS documents nowhere;
#: r53r — Route 53 Resolver's Rfc3339TimeString shape that AWS's documentation calls Unix time, never seen stored;
#: not_stored / not_kept — the collector stores the time nowhere; two_spellings — no one member path reaches it.
PENDING: dict[str, str] = {
    "aws_core__aws_apigateway_stage": "two_spellings",
    "aws_core__aws_bedrock_model": "not_stored",
    "aws_core__aws_codepipeline_pipeline": "not_kept",
    "aws_core__aws_config_aggregator": "not_stored",
    "aws_core__aws_docdb_event_subscription": "zoneless",
    "aws_core__aws_ec2_client_vpn_endpoint": "zoneless",
    "aws_core__aws_ec2_verified_access_endpoint": "zoneless",
    "aws_core__aws_ec2_verified_access_group": "zoneless",
    "aws_core__aws_ec2_verified_access_instance": "zoneless",
    "aws_core__aws_ec2_verified_access_trust_provider": "zoneless",
    "aws_core__aws_glue_registry": "undocumented",
    "aws_core__aws_glue_schema": "undocumented",
    "aws_core__aws_glue_schema_version": "undocumented",
    "aws_core__aws_guardduty_detector": "not_stored",
    "aws_core__aws_identity_center_group": "not_stored",
    "aws_core__aws_identity_center_instance": "not_stored",
    "aws_core__aws_identity_center_user": "not_kept",
    "aws_core__aws_kendra_featured_results_set": "unit",
    "aws_core__aws_licensemanager_report_generator": "undocumented",
    "aws_core__aws_logs_scheduled_query": "unit",
    "aws_core__aws_neptune_event_subscription": "zoneless",
    "aws_core__aws_opensearchserverless_access_policy": "unit",
    "aws_core__aws_opensearchserverless_collection_group": "unit",
    "aws_core__aws_opensearchserverless_lifecycle_policy": "unit",
    "aws_core__aws_opensearchserverless_security_config": "unit",
    "aws_core__aws_opensearchserverless_security_policy": "unit",
    "aws_core__aws_rds_event_subscription": "zoneless",
    "aws_core__aws_route53_resolver_firewall_rule_group": "r53r",
    "aws_core__aws_route53resolver_firewall_domain_list": "r53r",
    "aws_core__aws_route53resolver_firewall_rule_group_association": "r53r",
    "aws_core__aws_route53resolver_outpost_resolver": "r53r",
    "aws_core__aws_route53resolver_resolver_endpoint": "r53r",
    "aws_core__aws_route53resolver_resolver_query_log_config": "r53r",
    "aws_core__aws_route53resolver_resolver_rule": "r53r",
    "aws_core__aws_rum_app_monitor": "zoneless",
    "aws_core__aws_serverlessrepo_application": "undocumented",
}

#: For a type a custom_fn builds, the botocore call and items path whose item the custom_fn yields at the root of
#: configuration (read from the custom_fn; ``.`` is the whole response). The elb custom_fn yields two APIs' items.
CUSTOM_FN_ITEMS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "aws_core__aws_access_analyzer_archive_rule": (("accessanalyzer", "ListArchiveRules", "archiveRules[]"),),
    "aws_core__aws_alb": (("elbv2", "DescribeLoadBalancers", "LoadBalancers[]"),),
    "aws_core__aws_apigateway_api_key": (("apigateway", "GetApiKeys", "items[]"),),
    "aws_core__aws_apigateway_client_certificate": (("apigateway", "GetClientCertificates", "items[]"),),
    "aws_core__aws_apigateway_http_api": (("apigatewayv2", "GetApis", "Items[]"),),
    "aws_core__aws_apigateway_rest_api": (("apigateway", "GetRestApis", "items[]"),),
    "aws_core__aws_appconfig_experiment_definition": (("appconfig", "ListExperimentDefinitions", "Items[]"),),
    "aws_core__aws_backup_framework": (("backup", "ListFrameworks", "Frameworks[]"),),
    "aws_core__aws_backup_legal_hold": (("backup", "ListLegalHolds", "LegalHolds[]"),),
    "aws_core__aws_backup_plan": (("backup", "ListBackupPlans", "BackupPlansList[]"),),
    "aws_core__aws_backup_vault": (("backup", "ListBackupVaults", "BackupVaultList[]"),),
    "aws_core__aws_cloudtrail_event_data_store": (("cloudtrail", "ListEventDataStores", "EventDataStores[]"),),
    "aws_core__aws_cloudwatch_metric_stream": (("cloudwatch", "ListMetricStreams", "Entries[]"),),
    "aws_core__aws_codebuild_project": (("codebuild", "BatchGetProjects", "projects[]"),),
    "aws_core__aws_codecommit_repository": (("codecommit", "BatchGetRepositories", "repositories[]"),),
    "aws_core__aws_cognito_identity_provider": (("cognito-idp", "DescribeIdentityProvider", "IdentityProvider"),),
    "aws_core__aws_cognito_user_pool": (("cognito-idp", "DescribeUserPool", "UserPool"),),
    "aws_core__aws_cognito_user_pool_client": (("cognito-idp", "DescribeUserPoolClient", "UserPoolClient"),),
    "aws_core__aws_cognito_user_pool_group": (("cognito-idp", "ListGroups", "Groups[]"),),
    "aws_core__aws_dynamodb_table": (("dynamodb", "DescribeTable", "Table"),),
    "aws_core__aws_ecs_service": (("ecs", "DescribeServices", "services[]"),),
    "aws_core__aws_ecs_task_definition": (("ecs", "DescribeTaskDefinition", "taskDefinition"),),
    "aws_core__aws_eks_cluster": (("eks", "DescribeCluster", "cluster"),),
    "aws_core__aws_elb": (("elbv2", "DescribeLoadBalancers", "LoadBalancers[]"), ("elb", "DescribeLoadBalancers", "LoadBalancerDescriptions[]"),),
    "aws_core__aws_eventbridge_api_destination": (("events", "ListApiDestinations", "ApiDestinations[]"),),
    "aws_core__aws_eventbridge_archive": (("events", "ListArchives", "Archives[]"),),
    "aws_core__aws_eventbridge_connection": (("events", "ListConnections", "Connections[]"),),
    "aws_core__aws_eventbridge_event_bus": (("events", "ListEventBuses", "EventBuses[]"),),
    "aws_core__aws_guardduty_filter": (("guardduty", "GetFilter", "."),),
    "aws_core__aws_iam_group": (("iam", "ListGroups", "Groups[]"),),
    "aws_core__aws_iam_instance_profile": (("iam", "ListInstanceProfiles", "InstanceProfiles[]"),),
    "aws_core__aws_iam_oidc_provider": (("iam", "GetOpenIDConnectProvider", "."),),
    "aws_core__aws_iam_policy": (("iam", "ListPolicies", "Policies[]"),),
    "aws_core__aws_identity_center_application": (("sso-admin", "ListApplications", "Applications[]"),),
    "aws_core__aws_kms_alias": (("kms", "ListAliases", "Aliases[]"),),
    "aws_core__aws_kms_key": (("kms", "DescribeKey", "KeyMetadata"),),
    "aws_core__aws_lambda_function_url": (("lambda", "ListFunctionUrlConfigs", "FunctionUrlConfigs[]"),),
    "aws_core__aws_lex_bot_alias": (("lexv2-models", "ListBotAliases", "botAliasSummaries[]"),),
    "aws_core__aws_logs_destination": (("logs", "DescribeDestinations", "destinations[]"),),
    "aws_core__aws_logs_metric_filter": (("logs", "DescribeMetricFilters", "metricFilters[]"),),
    "aws_core__aws_logs_subscription_filter": (("logs", "DescribeSubscriptionFilters", "subscriptionFilters[]"),),
    "aws_core__aws_redshift_cluster": (("redshift", "DescribeClusters", "Clusters[]"),),
    "aws_core__aws_redshift_event_subscription": (("redshift", "DescribeEventSubscriptions", "EventSubscriptionsList[]"),),
    "aws_core__aws_rekognition_collection": (("rekognition", "DescribeCollection", "."),),
    "aws_core__aws_rekognition_stream_processor": (("rekognition", "DescribeStreamProcessor", "."),),
    "aws_core__aws_route53profiles_profile_association": (("route53profiles", "ListProfileAssociations", "ProfileAssociations[]"),),
    "aws_core__aws_s3_access_grant": (("s3control", "ListAccessGrants", "AccessGrantsList[]"),),
    "aws_core__aws_s3_access_grants_instance": (("s3control", "ListAccessGrantsInstances", "AccessGrantsInstancesList[]"),),
    "aws_core__aws_s3_access_grants_location": (("s3control", "ListAccessGrantsLocations", "AccessGrantsLocationsList[]"),),
    "aws_core__aws_s3_bucket": (("s3", "ListBuckets", "Buckets[]"),),
    "aws_core__aws_securityhub_automation_rule": (("securityhub", "ListAutomationRules", "AutomationRulesMetadata[]"),),
    "aws_core__aws_securityhub_hub_v2": (("securityhub", "DescribeSecurityHubV2", "."),),
    "aws_core__aws_ses_mail_manager_archive": (("mailmanager", "GetArchive", "."),),
    "aws_core__aws_ses_mail_manager_ingress_point": (("mailmanager", "GetIngressPoint", "."),),
    "aws_core__aws_ses_mail_manager_relay": (("mailmanager", "GetRelay", "."),),
    "aws_core__aws_ses_mail_manager_rule_set": (("mailmanager", "GetRuleSet", "."),),
    "aws_core__aws_ses_mail_manager_traffic_policy": (("mailmanager", "GetTrafficPolicy", "."),),
    "aws_core__aws_ses_multi_region_endpoint": (("sesv2", "ListMultiRegionEndpoints", "MultiRegionEndpoints[]"),),
    "aws_core__aws_ses_template": (("sesv2", "ListEmailTemplates", "TemplatesMetadata[]"),),
    "aws_core__aws_sqs_queue": (("sqs", "GetQueueAttributes", "Attributes"),),
    "aws_core__aws_synthetics_canary": (("synthetics", "DescribeCanaries", "Canaries[]"),),
    "aws_core__aws_transit_gateway": (("ec2", "DescribeTransitGateways", "TransitGateways[]"),),
    "aws_core__aws_transit_gateway_attachment": (("ec2", "DescribeTransitGatewayAttachments", "TransitGatewayAttachments[]"),),
    "aws_core__aws_xray_sampling_rule": (("xray", "GetSamplingRules", "SamplingRuleRecords[]"),),
}

#: Declared members botocore types as a string that core reads with no reader: each is ISO 8601 text with a zone.
TEXT_WITH_ZONE: dict[str, str] = {
    "aws_core__aws_drs_recovery_plan": "botocore pattern ISO8601DatetimeString ends in Z",
    "aws_core__aws_mgn_wave": "botocore pattern ISO8601DatetimeString ends in Z",
    "aws_core__aws_licensemanager_license": "botocore pattern ISO8601DateTime ends in Z or an offset with a colon",
    "aws_core__aws_securityhub_hub_v2": "IsoString, the form DescribeHub's SubscribedAt has, which this plugin reads",
    "aws_core__aws_pinpoint_app": "Pinpoint's ISO 8601 CreationDate (CLI get-apps example token: 2019-07-16T14:38:53.903Z)",
    "aws_core__aws_pinpoint_campaign": "documented as ISO 8601",
    "aws_core__aws_pinpoint_email_template": "documented as ISO 8601",
    "aws_core__aws_pinpoint_in_app_template": "documented as ISO 8601",
    "aws_core__aws_pinpoint_push_template": "documented as ISO 8601",
    "aws_core__aws_pinpoint_segment": "Pinpoint's ISO 8601 CreationDate, as the app's",
    "aws_core__aws_pinpoint_sms_template": "documented as ISO 8601",
}

_READERS = {
    "from_epoch_milliseconds": from_epoch_milliseconds,
    "from_epoch_seconds": from_epoch_seconds,
    "offset_without_colon": offset_without_colon,
}


def _path(dotted: str | None) -> tuple[str, ...] | None:
    return None if dotted is None else tuple(dotted.split("."))


def _configuration_declaration(member: str, reader: str | None, end_member: str | None) -> Interval:
    return Interval(
        start="configuration",
        kind="created",
        member=_path(member),
        reader=_READERS[reader] if reader else None,
        end="configuration" if end_member else None,
        end_member=_path(end_member),
    )


def _aws_models() -> list[type]:
    return [
        m
        for m in apps.get_app_config("aws_core").get_models()
        if getattr(m, "ENTITY_TYPE", "").startswith("aws_core__") and not m.__name__.startswith("Historical")
    ]


def _entry(entity_type: str) -> dict[str, Any]:
    return next(e for e in manifest_entries() if e["entity_type"] == entity_type)


def _create(entity_type: str, payload: dict[str, Any]) -> Entity:
    result = create_node(entity_type, payload, caller_context=CallerContext(batch_id=str(uuid.uuid7())))
    assert result.success, result.errors
    assert result.warnings == [], result.warnings
    return Entity.objects.get(pk=result.entity_id)


def _kind(row: Entity) -> Any:
    return view(row.dimensions).get(event_time.TIME_DIMENSION)


class _Client:
    """A fake boto3 client: each method answers with its canned value; a method nobody canned fails the test."""

    def __init__(self, **canned: Any) -> None:
        self._canned = canned

    def can_paginate(self, method: str) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        def call(**kwargs: Any) -> Any:
            if name not in self._canned:
                raise AssertionError(f"{name} was not expected")
            return self._canned[name]

        return call


# --- declarations -------------------------------------------------------------------------------------------------


def _pending() -> set[str]:
    return {m.ENTITY_TYPE for m in _aws_models() if "EVENT_TIME_PENDING" in m.__dict__}


@pytest.mark.django_db
def test_validation_reports_exactly_the_pending_types(monkeypatch: pytest.MonkeyPatch) -> None:
    """req-grid-entity-event-time-3: undeclared is a note, not a failure, until the switch is on."""
    monkeypatch.delenv(event_time.REQUIRE_DECLARATION_ENV, raising=False)
    result = validate_plugin(PLUGIN_ROOT, level="loads")
    check = next(c for c in result.checks if c.id == "event-time-declarations")
    undeclared = check.details["undeclared"]
    assert (set(undeclared), len(undeclared), check.details["required"]) == (_pending(), len(_pending()), False)
    assert check.status == "pass", check.messages


def test_every_type_is_declared_timeless_or_pending_and_only_one() -> None:
    models = _aws_models()
    assert len(models) == len({m.ENTITY_TYPE for m in models})
    declared = {
        m.ENTITY_TYPE: m.EVENT_TIME for m in models if m.__dict__.get("EVENT_TIME") not in (NO_EVENT_TIME, None)
    }
    expected = {**DECLARED, **{et: _configuration_declaration(*spec) for et, spec in CONFIGURATION_DECLARED.items()}}
    assert declared == expected
    assert _pending() == set(PENDING)
    timeless = [m for m in models if m.__dict__.get("EVENT_TIME") is NO_EVENT_TIME]
    assert (len(declared), len(PENDING), len(timeless), len(models)) == (527, 36, 371, 934)
    for model in models:
        declaration = model.__dict__.get("EVENT_TIME")
        reason = model.__dict__.get("EVENT_TIME_REASON")
        pending = model.__dict__.get("EVENT_TIME_PENDING")
        assert declaration_problems(model) == [], model.ENTITY_TYPE
        if declaration is NO_EVENT_TIME:
            # A reason cites where it was read: the AWS call, the policy document, or the reference data.
            assert isinstance(reason, str) and len(reason) > 40 and ("(" in reason or "derives" in reason), (
                model.ENTITY_TYPE
            )
            assert pending is None, model.ENTITY_TYPE
        elif declaration is None:
            # Not declared, on purpose: the note names the AWS member, why it is not read, and the issue.
            assert isinstance(pending, str) and "(" in pending and "unified-systems-com/aws-core-tap#287" in pending, (
                model.ENTITY_TYPE
            )
            assert reason is None, model.ENTITY_TYPE
        else:
            assert reason is None and pending is None, model.ENTITY_TYPE


def test_no_declared_field_is_a_time_the_grid_or_the_collector_made() -> None:
    """Core rule 9 and 13: never a collection time, a last-seen time or a last-change time."""
    for entity_type, declaration in DECLARED.items():
        for name in event_time.declared_fields(declaration):
            assert not name.startswith(("last_", "updated", "collected", "observed")), (entity_type, name)
    for entity_type, (member, _reader, end_member) in CONFIGURATION_DECLARED.items():
        for path in filter(None, (member, end_member)):
            assert not path.rsplit(".", 1)[-1].lower().startswith(("last", "updated", "modified")), (entity_type, path)


def test_an_end_is_read_from_the_same_record_as_its_start() -> None:
    """A type's end is a member of the same AWS answer as its start, never a parent's or another call's."""
    for entity_type, (member, _reader, end_member) in CONFIGURATION_DECLARED.items():
        if end_member is not None:
            assert member.split(".")[:-1] == end_member.split(".")[: len(member.split(".")) - 1], entity_type


# --- each member path is in the botocore shape the configuration holds ------------------------------------------


@functools.cache
def _service_model(service: str) -> Any:
    return botocore.session.get_session().get_service_model(service)


def _step(shape: Any, key: str) -> Any:
    if shape.type_name == "structure":
        assert key in shape.members, f"{key!r} is not a member of {shape.name}"
        return shape.members[key]
    # A map whose keys AWS enumerates (SQS's attributes): the custom_fn spreads it at the root.
    assert shape.type_name == "map" and key in (shape.key.enum or []), f"{key!r} is not a key of {shape.name}"
    return shape.value


def _item(service: str, op: str, items_path: str) -> Any:
    shape = _service_model(service).operation_model(op).output_shape
    if items_path == ".":
        return shape
    for segment in items_path.split("."):
        name = segment.removesuffix("[]")
        if name:
            shape = _step(shape, name)
        if segment.endswith("[]"):
            assert shape.type_name == "list", f"{segment!r} is not a list"
            shape = shape.member
    return shape


def _leaves(entity_type: str, member: tuple[str, ...]) -> list[Any]:
    """The botocore shape each place the configuration may hold ``member`` resolves to."""
    entry = _entry(entity_type)
    if member[0] == "_hydrate":
        # The detail call (enrich) or a hydrate slot: the call's whole response under ``_hydrate.<slot>.data``.
        slot, data, *rest = member[1:]
        assert data == "data", member
        hydrate = {h["key"]: h["op"] for h in entry.get("hydrate", [])}
        op = entry["enrich"]["op"] if slot == "detail" else hydrate[slot]
        roots = [(_service_model(entry["service"]).operation_model(op).output_shape, rest)]
    elif "custom_fn" in entry["source"]:
        roots = [(_item(*source), list(member)) for source in CUSTOM_FN_ITEMS[entity_type]]
    else:
        roots = [(_item(entry["service"], entry["source"]["aws_op"], entry["items_path"]), list(member))]
    leaves = []
    for shape, keys in roots:
        for key in keys:
            shape = _step(shape, key)
        leaves.append(shape)
    return leaves


def _check_member_shape(case: tuple[str, str, str | None]) -> None:
    entity_type, dotted, reader = case
    for leaf in _leaves(entity_type, tuple(dotted.split("."))):
        if reader is None:
            # Core reads it as it is stored: a botocore timestamp (stored as ISO 8601 UTC text), or ISO text with a zone.
            assert leaf.type_name == "timestamp" or (leaf.type_name == "string" and entity_type in TEXT_WITH_ZONE), (
                entity_type,
                dotted,
                leaf.type_name,
            )
        elif reader == "offset_without_colon":
            assert leaf.type_name == "string", (entity_type, dotted, leaf.type_name)
        else:
            assert leaf.type_name in ("long", "integer", "string"), (entity_type, dotted, leaf.type_name)


def _member_cases() -> list[Any]:
    cases = []
    for entity_type, (member, reader, end_member) in sorted(CONFIGURATION_DECLARED.items()):
        cases.append(pytest.param((entity_type, member, reader), id=f"{entity_type}:{member}"))
        if end_member is not None:
            cases.append(pytest.param((entity_type, end_member, None), id=f"{entity_type}:{end_member}"))
    return cases


@pytest.mark.parametrize("case", _member_cases())
def test_each_declared_member_path_is_in_the_types_botocore_output_shape(case: tuple[str, str, str | None]) -> None:
    _check_member_shape(case)


def test_a_custom_fn_item_table_entry_is_one_a_declared_type_needs() -> None:
    needed = {
        et
        for et, (member, _r, _e) in CONFIGURATION_DECLARED.items()
        if "custom_fn" in _entry(et)["source"] and not member.startswith("_hydrate.")
    }
    assert set(CUSTOM_FN_ITEMS) == needed


# --- the stored value keeps the source's form --------------------------------------------------------------------


def test_a_layer_versions_created_date_is_stored_as_lambda_sent_it() -> None:
    """Core rule 22: no conversion in the collector; the declared reader reads Lambda's form when the spine is derived."""
    arn = f"arn:aws:lambda:us-east-1:{ACCOUNT}:layer:deps"
    client = _Client(
        list_layers={"Layers": [{"LayerName": "deps", "LayerArn": arn}]},
        list_layer_versions={
            "LayerVersions": [{"LayerVersionArn": f"{arn}:3", "Version": 3, "CreatedDate": "2026-10-01T00:00:00.000+0000"}]
        },
    )
    (item,) = list(lambda_layer_versions_described(None, client_for=lambda service: client))
    node = project_item(_entry("aws_core__aws_lambda_layer_version"), item)
    assert node.fields["created_date"] == "2026-10-01T00:00:00.000+0000"


@pytest.mark.django_db
def test_a_layer_version_reaches_the_spine_through_its_reader() -> None:
    row = _create(
        "aws_core__aws_lambda_layer_version",
        {
            "name": "deps:3",
            "layer_version_arn": f"arn:aws:lambda:us-east-1:{ACCOUNT}:layer:deps:3",
            "created_date": "2026-10-01T02:03:04.123+0000",
        },
    )
    assert (row.event_start, row.event_end, row.event_precision, _kind(row)) == (
        datetime(2026, 10, 1, 2, 3, 4, 123000, tzinfo=UTC),
        None,
        "second",
        "created",
    )


def _configured(entity_type: str, key_field: str, key: str, configuration: dict[str, Any]) -> Entity:
    return _create(entity_type, {"name": key.rsplit(":", 1)[-1], key_field: key, "configuration": configuration})


@pytest.mark.django_db
def test_a_botocore_timestamp_in_configuration_lands_in_event_start() -> None:
    """The collector stores a botocore datetime as ISO 8601 UTC text (envelope.jsonable); core reads it from the member."""
    row = _configured(
        "aws_core__aws_ses_tenant",
        "ses_tenant_arn",
        f"arn:aws:ses:us-east-1:{ACCOUNT}:tenant/t-1",
        {"TenantName": "t-1", "CreatedTimestamp": "2026-03-04T05:06:07.250000Z"},
    )
    assert (row.event_start, row.event_end, row.event_precision, _kind(row)) == (
        datetime(2026, 3, 4, 5, 6, 7, 250000, tzinfo=UTC),
        None,
        "second",
        "created",
    )


@pytest.mark.django_db
def test_a_member_that_is_not_there_states_no_time_and_no_warning() -> None:
    """Core rule 30: an absent member is an empty event time, as an empty field is (``_create`` asserts no warning)."""
    row = _configured("aws_core__aws_ses_tenant", "ses_tenant_arn", f"arn:aws:ses:us-east-1:{ACCOUNT}:tenant/t-2", {})
    assert (row.event_start, row.event_end, row.event_precision, _kind(row)) == (None, None, None, None)


@pytest.mark.django_db
def test_a_certificate_holds_from_its_detail_calls_creation_until_its_not_after() -> None:
    """The detail call's answer sits under ``_hydrate.detail.data``; NotAfter is the end AWS states (core rule 7)."""
    detail = {"Certificate": {"CreatedAt": "2026-01-02T03:04:05Z", "NotAfter": "2027-01-02T03:04:05Z"}}
    row = _configured(
        "aws_core__aws_acm_certificate",
        "certificate_arn",
        f"arn:aws:acm:us-east-1:{ACCOUNT}:certificate/c-1",
        {"_hydrate": {"detail": {"status": "ok", "op": "DescribeCertificate", "data": detail}}},
    )
    assert (row.event_start, row.event_end, _kind(row)) == (
        datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        datetime(2027, 1, 2, 3, 4, 5, tzinfo=UTC),
        "created",
    )


@pytest.mark.django_db
def test_a_denied_detail_call_states_no_time() -> None:
    row = _configured(
        "aws_core__aws_acm_certificate",
        "certificate_arn",
        f"arn:aws:acm:us-east-1:{ACCOUNT}:certificate/c-2",
        {"_hydrate": {"detail": {"status": "denied", "op": "DescribeCertificate", "error_code": "AccessDenied"}}},
    )
    assert (row.event_start, _kind(row)) == (None, None)


@pytest.mark.django_db
def test_greengrass_milliseconds_as_text_are_read_by_cores_helper() -> None:
    """Greengrass V1 states CreationTimestamp as text, in milliseconds since the epoch (botocore documentation)."""
    row = _configured(
        "aws_core__aws_greengrass_group",
        "greengrass_group_arn",
        f"arn:aws:greengrass:us-east-1:{ACCOUNT}:/greengrass/groups/g-1",
        {"Id": "g-1", "CreationTimestamp": "1767225600123"},
    )
    assert (row.event_start, row.event_precision) == (datetime(2026, 1, 1, 0, 0, 0, 123000, tzinfo=UTC), "second")


@pytest.mark.django_db
def test_a_log_metric_filters_milliseconds_number_is_read_by_cores_helper() -> None:
    row = _configured(
        "aws_core__aws_logs_metric_filter",
        "filter_key",
        "aws:us-east-1:0000:group:filter",
        {"filterName": "filter", "creationTime": 1767225600000},
    )
    assert row.event_start == datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.django_db
def test_an_sqs_queues_creation_seconds_go_from_the_custom_fn_to_the_spine() -> None:
    """GetQueueAttributes answers CreatedTimestamp in epoch seconds as text; the custom_fn spreads the attributes at
    the root of the item, so the stored configuration holds it at the root."""
    arn = f"arn:aws:sqs:us-east-1:{ACCOUNT}:jobs"
    sqs = _Client(
        list_queues={"QueueUrls": ["https://sqs.us-east-1.amazonaws.com/0000/jobs"]},
        get_queue_attributes={"Attributes": {"QueueArn": arn, "CreatedTimestamp": "1767225600"}},
        list_queue_tags={"Tags": {}},
    )
    (item,) = list(sqs_queues_described(None, client_for=lambda service: sqs))
    node = project_item(_entry("aws_core__aws_sqs_queue"), item)
    assert node.configuration["CreatedTimestamp"] == "1767225600"
    row = _create("aws_core__aws_sqs_queue", {**node.fields, "configuration": node.configuration})
    assert (row.event_start, row.event_end, _kind(row)) == (datetime(2026, 1, 1, tzinfo=UTC), None, "created")


@pytest.mark.django_db
def test_a_function_urls_lambda_offset_is_read_through_the_plugins_reader() -> None:
    row = _configured(
        "aws_core__aws_lambda_function_url",
        "function_url",
        "https://abc.lambda-url.us-east-1.on.aws/",
        {"CreationTime": "2026-02-03T04:05:06.789+0000"},
    )
    assert row.event_start == datetime(2026, 2, 3, 4, 5, 6, 789000, tzinfo=UTC)


# --- on the spine -------------------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_creation_time_botocore_parsed_lands_in_event_start_at_second_precision() -> None:
    """GetSAMLProvider's CreateDate, as botocore parses it (an aware datetime), through the collector to the spine."""
    created = parse_timestamp("2026-03-04T05:06:07Z")
    expires = parse_timestamp("2027-03-04T05:06:07Z")
    assert created.tzinfo is not None
    provider = f"arn:aws:iam::{ACCOUNT}:saml-provider/Okta"
    iam = _Client(
        list_saml_providers={"SAMLProviderList": [{"Arn": provider, "CreateDate": created}]},
        get_saml_provider={"SAMLProviderUUID": "u-1", "CreateDate": created, "ValidUntil": expires},
    )
    (item,) = list(iam_saml_providers_described(None, client_for=lambda service: iam, walk=ListingWalk()))
    node = project_item(_entry("aws_core__aws_iam_saml_provider"), item)
    row = _create("aws_core__aws_iam_saml_provider", node.fields)
    assert row.event_start == datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
    assert row.event_precision == "second"
    # Rule 8: it holds from its creation until the expiration AWS states.
    assert row.event_end == datetime(2027, 3, 4, 5, 6, 7, tzinfo=UTC)
    assert _kind(row) == "created"


@pytest.mark.django_db
def test_an_inspector_finding_is_an_interval_from_its_first_observation() -> None:
    """The first observation starts it; the last is a last-seen time, which stays a typed field (core rule 14)."""
    row = _create(
        "aws_core__aws_inspector2_finding",
        {
            "name": "CVE-2026-0001 - openssl",
            "finding_arn": f"arn:aws:inspector2:us-east-1:{ACCOUNT}:finding/abc",
            "first_observed_at": "2026-01-02T03:04:05Z",
            "last_observed_at": "2026-02-03T04:05:06Z",
        },
    )
    assert (row.event_start, row.event_end, row.event_precision) == (
        datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        None,
        "second",
    )
    assert _kind(row) == "first_seen"


@pytest.mark.django_db
def test_a_stopped_ecs_task_is_the_interval_it_ran() -> None:
    row = _create(
        "aws_core__aws_ecs_task",
        {
            "name": "task",
            "task_arn": f"arn:aws:ecs:us-east-1:{ACCOUNT}:task/c/abc",
            "started_at": "2026-01-02T03:04:05Z",
            "stopped_at": "2026-01-02T04:00:00Z",
        },
    )
    assert (row.event_start, row.event_end, _kind(row)) == (
        datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        datetime(2026, 1, 2, 4, 0, 0, tzinfo=UTC),
        "occurred",
    )


@pytest.mark.django_db
def test_a_managed_instance_starts_at_its_registration_and_an_ec2_node_states_none() -> None:
    """A hybrid node's RegistrationDate is when its record came to exist; an EC2 node's record states no such time,
    and the EC2 instance's LaunchTime is not read onto it (each type from its own record)."""
    hybrid = _create(
        "aws_core__aws_ssm_managed_instance",
        {"name": "lab", "instance_id": "mi-0123456789abcdef0", "registration_date": "2026-01-02T03:04:05Z"},
    )
    assert (hybrid.event_start, hybrid.event_end, _kind(hybrid)) == (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), None, "created")
    ec2 = _create("aws_core__aws_ssm_managed_instance", {"name": "web", "instance_id": "i-0abc1234def567890"})
    assert (ec2.event_start, ec2.event_end, _kind(ec2)) == (None, None, None)


@pytest.mark.django_db
def test_a_type_with_no_event_time_has_none_on_the_spine() -> None:
    row = _create("aws_core__aws_vpc", {"name": "main", "vpc_id": "vpc-1"})
    assert (row.event_start, row.event_end, row.event_precision, _kind(row)) == (None, None, None, None)
