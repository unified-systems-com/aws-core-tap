"""A natural key names one resource across every partition, account and region (req-aws-collector-identity-8).

Issue 224: a bare name (``default.dax1.0``, which AWS creates in every region) or a composite of names
(``<log group>:<filter>``) was one identity in every region, so a multi-region run kept the first and dropped the
rest, and across runs the regions overwrote one another's row. Every manifest entry is now keyed one of three ways,
and this file holds the line so a new entry cannot regress:

- on an ARN, which carries partition, account and region (a member whose name says ARN, or a ``derive`` that builds
  one, or a composite that leads with one);
- on an id AWS generates, which no other account or region is handed (listed below, each with its reason);
- on a composite led by ``{partition}:{account}:{region}:`` (``{partition}:{account}:global:`` for a global entry,
  whose run region is only where the call was made).
"""

from __future__ import annotations

import re
import uuid

import pytest
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries

SCOPED = "{partition}:{account}:{region}:"
SCOPED_GLOBAL = "{partition}:{account}:global:"

#: Keyed on an id AWS generates (or under one), so already unique everywhere. A name the customer chooses, or a name
#: AWS gives the same default in every region, never belongs here: it takes the scoped prefix.
GLOBALLY_UNIQUE: dict[str, str] = {
    "account": "the account id: one per account, in every partition",
    "route53_zone": "Id, an id AWS generates",
    "route53_record_set": "under the hosted zone id, which Route 53 generates, then the record name, type and set identifier",
    "cognito_user_pool": "Id, an id AWS generates",
    "vpc": "VpcId, an id AWS generates",
    "subnet": "SubnetId, an id AWS generates",
    "ec2_instance": "InstanceId, an id AWS generates",
    "security_group": "GroupId, an id AWS generates",
    "iam_virtual_mfa_device": "the serial number is the device's ARN",
    "elastic_ip": "AllocationId, an id AWS generates",
    "internet_gateway": "InternetGatewayId, an id AWS generates",
    "nat_gateway": "NatGatewayId, an id AWS generates",
    "network_acl": "NetworkAclId, an id AWS generates",
    "route_table": "RouteTableId, an id AWS generates",
    "ebs_volume": "VolumeId, an id AWS generates",
    "vpc_endpoint": "VpcEndpointId, an id AWS generates",
    "elb": "the DNS name AWS assigns, which carries the region and a generated suffix",
    "dx_connection": "connectionId, an id AWS generates",
    "dx_virtual_interface": "virtualInterfaceId, an id AWS generates",
    "dx_gateway": "directConnectGatewayId, an id AWS generates",
    "vpc_endpoint_service": "ServiceId, an id AWS generates",
    "route53_resolver_firewall_rule_group": "Id, an id AWS generates",
    "transit_gateway": "TransitGatewayId, an id AWS generates",
    "transit_gateway_attachment": "TransitGatewayAttachmentId, an id AWS generates",
    "identity_center_user": "under the identity store id (d-...) that IAM Identity Center generates, then the generated user id",
    "identity_center_application_assignment": "under the application ARN",
    "lambda_function_url": "the function URL, whose host is a url-id Lambda generates",
    "guardduty_filter": "under the detector id GuardDuty generates",
    "guardduty_ip_set": "under the detector id GuardDuty generates",
    "guardduty_threat_intel_set": "under the detector id GuardDuty generates",
    "guardduty_publishing_destination": "under the detector id GuardDuty generates",
    "guardduty_member": "under the detector id GuardDuty generates",
    "efs_mount_target": "MountTargetId, an id AWS generates",
    "cognito_identity_pool": "IdentityPoolId, an id AWS generates",
    "cognito_user_pool_client": "under the user pool id Cognito generates (<region>_<random>)",
    "cognito_identity_provider": "under the user pool id Cognito generates (<region>_<random>)",
    "cognito_user_pool_group": "under the user pool id Cognito generates (<region>_<random>)",
    "cognito_user_pool_resource_server": "under the user pool id Cognito generates (<region>_<random>)",
    "cognito_user_pool_domain": "under the user pool id Cognito generates (<region>_<random>)",
    "ec2_application_status_check": "ApplicationStatusCheckId, an id AWS generates",
    "ec2_capacity_manager_data_export": "CapacityManagerDataExportId, an id AWS generates",
    "ec2_carrier_gateway": "CarrierGatewayId, an id AWS generates",
    "ec2_client_vpn_endpoint": "ClientVpnEndpointId, an id AWS generates",
    "ec2_customer_gateway": "CustomerGatewayId, an id AWS generates",
    "ec2_dhcp_options": "DhcpOptionsId, an id AWS generates",
    "ec2_fleet": "FleetId, an id AWS generates",
    "ec2_egress_only_internet_gateway": "EgressOnlyInternetGatewayId, an id AWS generates",
    "ec2_flow_log": "FlowLogId, an id AWS generates",
    "ec2_fpga_image": "FpgaImageId, an id AWS generates",
    "ec2_host": "HostId, an id AWS generates",
    "ec2_ipam_pool_cidr": "IpamPoolCidrId, an id AWS generates",
    "ec2_ipv4_pool": "PoolId, an id AWS generates",
    "ec2_instance_event_window": "InstanceEventWindowId, an id AWS generates",
    "ec2_key_pair": "KeyPairId, an id AWS generates",
    "ec2_launch_template": "LaunchTemplateId, an id AWS generates",
    "ec2_local_gateway_route_table_vpc_association": "LocalGatewayRouteTableVpcAssociationId, an id AWS generates",
    "ec2_lgw_route_table_vif_group_association": "LocalGatewayRouteTableVirtualInterfaceGroupAssociationId, an id AWS generates",
    "ec2_network_interface": "NetworkInterfaceId, an id AWS generates",
    "ec2_route_server": "RouteServerId, an id AWS generates",
    "ec2_route_server_endpoint": "RouteServerEndpointId, an id AWS generates",
    "ec2_route_server_peer": "RouteServerPeerId, an id AWS generates",
    "ec2_spot_fleet": "SpotFleetRequestId, an id AWS generates",
    "ec2_traffic_mirror_filter": "TrafficMirrorFilterId, an id AWS generates",
    "ec2_traffic_mirror_filter_rule": "TrafficMirrorFilterRuleId, an id AWS generates",
    "ec2_traffic_mirror_session": "TrafficMirrorSessionId, an id AWS generates",
    "ec2_traffic_mirror_target": "TrafficMirrorTargetId, an id AWS generates",
    "ec2_transit_gateway_connect": "TransitGatewayAttachmentId, an id AWS generates",
    "ec2_transit_gateway_connect_peer": "TransitGatewayConnectPeerId, an id AWS generates",
    "ec2_transit_gateway_metering_policy": "TransitGatewayMeteringPolicyId, an id AWS generates",
    "ec2_transit_gateway_peering_attachment": "TransitGatewayAttachmentId, an id AWS generates",
    "ec2_transit_gateway_policy_table": "TransitGatewayPolicyTableId, an id AWS generates",
    "ec2_transit_gateway_route_table": "TransitGatewayRouteTableId, an id AWS generates",
    "ec2_transit_gateway_vpc_attachment": "TransitGatewayAttachmentId, an id AWS generates",
    "ec2_vpc_block_public_access_exclusion": "ExclusionId, an id AWS generates",
    "ec2_vpc_encryption_control": "VpcEncryptionControlId, an id AWS generates",
    "ec2_vpc_endpoint_connection_notification": "ConnectionNotificationId, an id AWS generates",
    "ec2_vpc_peering_connection": "VpcPeeringConnectionId, an id AWS generates",
    "ec2_vpn_concentrator": "VpnConcentratorId, an id AWS generates",
    "ec2_vpn_connection": "VpnConnectionId, an id AWS generates",
    "ec2_vpn_gateway": "VpnGatewayId, an id AWS generates",
    "ec2_verified_access_endpoint": "VerifiedAccessEndpointId, an id AWS generates",
    "ec2_verified_access_instance": "VerifiedAccessInstanceId, an id AWS generates",
    "ec2_verified_access_trust_provider": "VerifiedAccessTrustProviderId, an id AWS generates",
    "route53resolver_firewall_config": "Id, an id AWS generates",
    "route53resolver_resolver_config": "Id, an id AWS generates",
    "route53resolver_resolver_dnssec_config": "Id, an id AWS generates",
    "wafregional_byte_match_set": "ByteMatchSetId, an id AWS generates",
    "wafregional_geo_match_set": "GeoMatchSetId, an id AWS generates",
    "wafregional_ip_set": "IPSetId, an id AWS generates",
    "wafregional_regex_pattern_set": "RegexPatternSetId, an id AWS generates",
    "wafregional_size_constraint_set": "SizeConstraintSetId, an id AWS generates",
    "wafregional_sql_injection_match_set": "SqlInjectionMatchSetId, an id AWS generates",
    "wafregional_xss_match_set": "XssMatchSetId, an id AWS generates",
    "wellarchitected_agent_context": "id, an id AWS generates",
    "wellarchitected_agent_goal": "id, an id AWS generates",
    "route53_delegation_set": "Id, an id AWS generates",
    "route53_health_check": "Id, an id AWS generates",
    "route53_query_logging_config": "Id, an id AWS generates",
    "route53_traffic_policy_instance": "Id, an id AWS generates",
    "ssm_association": "AssociationId, an id AWS generates",
    "ssm_cloud_connector": "CloudConnectorId, an id AWS generates",
    "ssm_maintenance_window": "WindowId, an id AWS generates",
    "ssm_patch_baseline": "BaselineId, an id AWS generates",
    "servicecatalog_service_action": "Id, an id AWS generates",
    "servicecatalog_tag_option": "Id, an id AWS generates",
    "cloudformation_stack": "StackId, an id AWS generates",
    "cloudformation_generated_template": "GeneratedTemplateId, an id AWS generates",
    "cloudformation_stack_set": "StackSetId, an id AWS generates",
    "cloudformation_change_set": "ChangeSetId, an id AWS generates",
    "cloudhsm_cluster": "ClusterId, an id AWS generates",
    "dlm_lifecycle_policy": "PolicyId, an id AWS generates",
    "directoryservice_directory": "DirectoryId, an id AWS generates",
    "rds_blue_green_deployment": "BlueGreenDeploymentIdentifier, an id AWS generates",
    "rum_app_monitor": "Id, an id AWS generates",
    "serverlessrepo_application": "ApplicationId, an id AWS generates",
    "opensearchserverless_vpc_endpoint": "id, an id AWS generates",
    "networkmanager_attachment": "AttachmentId, an id AWS generates",
    "networkmanager_connect_peer": "ConnectPeerId, an id AWS generates",
    "networkmanager_transit_gateway_peering": "PeeringId, an id AWS generates",
    "backup_backup_selection": "SelectionId, an id AWS generates",
    "grafana_workspace": "id, an id AWS generates",
    "logs_query_definition": "queryDefinitionId, an id AWS generates",
    "workspaces_connection_alias": "AliasId, an id AWS generates",
    "workspaces_directory": "DirectoryId, an id AWS generates",
    "workspaces_workspace": "WorkspaceId, an id AWS generates",
    "workspaces_workspace_ip_group": "groupId, an id AWS generates",
    "verifiedpermissions_identity_source": "under the policy store id Verified Permissions generates",
    "verifiedpermissions_policy": "under the policy store id Verified Permissions generates",
    "verifiedpermissions_policy_template": "under the policy store id Verified Permissions generates",
    "bedrock_data_source": "under the knowledge base id Bedrock generates",
    "athena_named_query": "NamedQueryId, an id AWS generates",
    "glue_schema_version": "SchemaVersionId, an id AWS generates",
    "lex_bot_version": "under the bot id Lex generates",
}

#: Scoped in code, where the manifest cannot see: the custom_fn builds ``_key`` with ``customfns._scoped_key``
#: (pinned by ``test_the_logs_filters_are_keyed_under_the_run_scope`` below).
SCOPED_IN_CODE: frozenset[str] = frozenset({"logs_metric_filter", "logs_subscription_filter"})


def _short(entry: dict) -> str:
    return entry["entity_type"].removeprefix("aws_core__aws_")


def _how_keyed(entry: dict) -> str | None:
    """"arn", "scoped" or None, from the manifest alone."""
    key = entry["natural_key"]
    template = (entry.get("derive") or {}).get(key)
    if template is None:
        return "arn" if re.search("arn", key, re.IGNORECASE) else None
    if template.startswith("arn:{partition}:"):
        return "arn"
    if template.startswith(SCOPED_GLOBAL if entry["scope"] == "global" else SCOPED):
        return "scoped"
    lead = re.match(r"\{([^{}]+)\}", template)
    return "arn" if lead and re.search("arn", lead.group(1), re.IGNORECASE) else None


def test_every_entry_is_keyed_on_an_arn_a_generated_id_or_the_scoped_prefix() -> None:
    loose = [
        f"{_short(e)} ({e['natural_key']})"
        for e in manifest_entries()
        if _how_keyed(e) is None and _short(e) not in GLOBALLY_UNIQUE and _short(e) not in SCOPED_IN_CODE
    ]
    assert not loose, (
        "these keys could repeat in another region or account (req-aws-collector-identity-8): key on the ARN, or add "
        "a derive led by {partition}:{account}:{region}:, or, for an id AWS generates, list it in GLOBALLY_UNIQUE "
        "with the reason: " + ", ".join(loose)
    )


def test_a_global_entry_never_puts_the_run_region_in_its_key() -> None:
    """A global entry is read from one region of the run, which can change between runs: a key holding it would
    re-key the resource whenever the operator's region list does."""
    leaky = [
        _short(e)
        for e in manifest_entries()
        if e["scope"] == "global"
        and "{region}" in ((e.get("derive") or {}).get(e["natural_key"]) or "")
        and not ((e.get("derive") or {}).get(e["natural_key"]) or "").startswith("arn:")
    ]
    assert not leaky


def test_the_allowlists_hold_only_entries_that_need_them() -> None:
    """An allowlisted entry that is gone, or is now keyed on an ARN or the prefix, is a stale line."""
    entries = {_short(e): e for e in manifest_entries()}
    stale = [name for name in (*GLOBALLY_UNIQUE, *SCOPED_IN_CODE) if name not in entries or _how_keyed(entries[name])]
    assert not stale
    assert not set(GLOBALLY_UNIQUE) & SCOPED_IN_CODE


@pytest.mark.parametrize(
    ("name", "member"),
    [
        ("dax_parameter_group", "ParameterGroupName"),
        ("dax_subnet_group", "SubnetGroupName"),
        ("redshift_cluster_security_group", "ClusterSecurityGroupName"),
        ("redshift_endpoint_access", "EndpointName"),
        ("redshift_scheduled_action", "ScheduledActionName"),
        ("glue_security_configuration", "Name"),
        ("lakeformation_tag", "TagKey"),
    ],
)
def test_a_name_aws_repeats_in_every_region_is_one_resource_per_region(name: str, member: str) -> None:
    """The same name in two regions (AWS's own default.dax1.0) builds two keys."""
    from tap_plugin.aws_core.collectors.boto3_collector.source import render_template

    [entry] = [e for e in manifest_entries() if _short(e) == name]
    template = entry["derive"][entry["natural_key"]]
    item = {member: "default.dax1.0"}
    east = render_template(template, item, {"partition": "aws", "account": "123456789012", "region": "us-east-1"})
    west = render_template(template, item, {"partition": "aws", "account": "123456789012", "region": "us-west-2"})
    assert east == "aws:123456789012:us-east-1:default.dax1.0"
    assert east != west


def test_the_logs_filters_are_keyed_under_the_run_scope() -> None:
    from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
        logs_metric_filters_described,
        logs_subscription_filters_described,
    )

    class _Logs:
        def __init__(self, region: str) -> None:
            self.meta = type("Meta", (), {"region_name": region})()

        def can_paginate(self, name: str) -> bool:
            return False

        def describe_metric_filters(self, **_: object) -> dict:
            return {"metricFilters": [{"filterName": "root", "logGroupName": "/aws/cloudtrail"}]}

        def describe_log_groups(self, **_: object) -> dict:
            return {"logGroups": [{"logGroupName": "/aws/cloudtrail"}]}

        def describe_subscription_filters(self, **_: object) -> dict:
            return {"subscriptionFilters": [{"filterName": "to-siem"}]}

    class _Sts:
        def get_caller_identity(self) -> dict:
            return {"Account": "123456789012"}

    def keys(fn, region: str) -> list[str]:
        clients = {"logs": _Logs(region), "sts": _Sts()}
        return [item["_key"] for item in fn(None, client_for=clients.__getitem__)]

    assert keys(logs_metric_filters_described, "us-gov-west-1") == ["aws-us-gov:123456789012:us-gov-west-1:/aws/cloudtrail:root"]
    assert keys(logs_metric_filters_described, "us-gov-east-1") == ["aws-us-gov:123456789012:us-gov-east-1:/aws/cloudtrail:root"]
    assert keys(logs_subscription_filters_described, "us-east-1") == ["aws:123456789012:us-east-1:/aws/cloudtrail:to-siem"]


# --- the migration (0053) that re-keys rows already on the grid ---------------------------------------------------


def _migration():
    import importlib

    return importlib.import_module("tap_plugin.aws_core.migrations.0053_region_unique_natural_keys")


@pytest.mark.parametrize(
    ("old", "shape", "new"),
    [
        ("default.dax1.0", "plain", "aws-us-gov:123456789012:us-gov-west-1:default.dax1.0"),
        ("/aws/cloudtrail:root", "plain", "aws-us-gov:123456789012:us-gov-west-1:/aws/cloudtrail:root"),
        ("123456789012/us-gov-west-1/inbound", "account_region", "aws-us-gov:123456789012:us-gov-west-1:inbound"),
        # Already scoped: left as it is, so the migration can run twice.
        ("aws-us-gov:123456789012:us-gov-west-1:x", "plain", "aws-us-gov:123456789012:us-gov-west-1:x"),
        # An account/region key from another scope than the row's own dimensions is not guessed at.
        ("111122223333/us-gov-west-1/inbound", "account_region", None),
        ("", "plain", None),
    ],
)
def test_the_migration_scopes_each_old_key_from_the_rows_dimensions(old: str, shape: str, new: str | None) -> None:
    m = _migration()
    assert m.new_key(old, shape, "aws-us-gov", "123456789012", "us-gov-west-1") == new
    if new is not None and new != old:
        assert m.old_key(new, shape, "aws-us-gov", "123456789012", "us-gov-west-1") == old


def test_the_migration_names_every_re_keyed_model_and_its_key_column() -> None:
    """Every entry this change scoped is in the migration, under the column the model declares as its key."""
    from tap_grid.registry import get_model_class

    m = _migration()
    scoped = {e["entity_type"] for e in manifest_entries() if _how_keyed(e) == "scoped"} | {
        f"aws_core__aws_{n}" for n in SCOPED_IN_CODE
    }
    declared = {}
    for entity_type in scoped:
        model = get_model_class(entity_type)
        declared[model._meta.model_name] = model.NATURAL_KEY[0]
    assert {name: column for name, (column, _) in m.REKEYED.items()} == declared


@pytest.mark.django_db
def test_the_migration_re_keys_a_row_in_place_and_leaves_one_it_cannot_scope() -> None:
    from django.apps import apps as live_apps
    from tap_plugin.aws_core.models import DaxParameterGroup, SesReceiptRuleSet

    from tap_grid.caller_context import CallerContext
    from tap_grid.services import WriteOperation, write_batch

    def create(type_slug: str, payload: dict, dimensions: dict) -> uuid.UUID:
        [result] = write_batch(
            [WriteOperation(verb="create_node", type_slug=type_slug, payload=payload, dimensions=dimensions)],
            caller_context=CallerContext(),
        ).results
        assert result.success, result
        return result.entity_id

    scope = {"cloud": "aws", "aws_account": "123456789012", "aws_region": "us-gov-west-1"}
    dax = create("aws_core__aws_dax_parameter_group", {"name": "default.dax1.0", "dax_parameter_group_id": "default.dax1.0"}, scope)
    rules = create(
        "aws_core__aws_ses_receipt_rule_set",
        {"name": "inbound", "ses_receipt_rule_set_key": "123456789012/us-gov-west-1/inbound"},
        scope,
    )
    orphan = create("aws_core__aws_dax_parameter_group", {"name": "x", "dax_parameter_group_id": "x"}, {"cloud": "aws"})

    m = _migration()
    m.scope_keys(live_apps, None)
    assert DaxParameterGroup.all_objects.get(entity_id=dax).dax_parameter_group_id == "aws-us-gov:123456789012:us-gov-west-1:default.dax1.0"
    assert SesReceiptRuleSet.all_objects.get(entity_id=rules).ses_receipt_rule_set_key == "aws-us-gov:123456789012:us-gov-west-1:inbound"
    assert DaxParameterGroup.all_objects.get(entity_id=orphan).dax_parameter_group_id == "x"

    # The next collection finds the re-keyed row by the key it now builds: core's lookup reads the model column.
    assert DaxParameterGroup.find_existing(dax_parameter_group_id="aws-us-gov:123456789012:us-gov-west-1:default.dax1.0").entity_id == dax

    m.scope_keys(live_apps, None)  # idempotent
    m.unscope_keys(live_apps, None)
    assert DaxParameterGroup.all_objects.get(entity_id=dax).dax_parameter_group_id == "default.dax1.0"
    assert SesReceiptRuleSet.all_objects.get(entity_id=rules).ses_receipt_rule_set_key == "123456789012/us-gov-west-1/inbound"


@pytest.mark.django_db
def test_going_back_never_recreates_the_collision_the_scoped_keys_removed() -> None:
    """Once default.dax1.0 is on the grid from two regions, both would return to the one bare name: neither does."""
    from django.apps import apps as live_apps
    from tap_plugin.aws_core.models import DaxParameterGroup

    from tap_grid.caller_context import CallerContext
    from tap_grid.services import WriteOperation, write_batch

    ids = []
    for region in ("us-gov-west-1", "us-gov-east-1"):
        key = f"aws-us-gov:123456789012:{region}:default.dax1.0"
        [result] = write_batch(
            [
                WriteOperation(
                    verb="create_node",
                    type_slug="aws_core__aws_dax_parameter_group",
                    payload={"name": "default.dax1.0", "dax_parameter_group_id": key},
                    dimensions={"cloud": "aws", "aws_account": "123456789012", "aws_region": region},
                )
            ],
            caller_context=CallerContext(),
        ).results
        assert result.success, result
        ids.append((result.entity_id, key))

    _migration().unscope_keys(live_apps, None)
    for entity_id, key in ids:
        assert DaxParameterGroup.all_objects.get(entity_id=entity_id).dax_parameter_group_id == key


@pytest.mark.django_db
def test_a_row_is_never_moved_onto_a_key_a_row_it_cannot_convert_already_holds() -> None:
    """Going forward, a new collector may already have written the scoped row; going back, a row with no dimensions
    may still hold the bare name. Either occupant blocks the move, and both rows keep their keys."""
    from django.apps import apps as live_apps
    from tap_plugin.aws_core.models import DaxParameterGroup

    from tap_grid.caller_context import CallerContext
    from tap_grid.services import WriteOperation, write_batch

    def create(key: str, dimensions: dict) -> uuid.UUID:
        [result] = write_batch(
            [
                WriteOperation(
                    verb="create_node",
                    type_slug="aws_core__aws_dax_parameter_group",
                    payload={"name": "default.dax1.0", "dax_parameter_group_id": key},
                    dimensions=dimensions,
                )
            ],
            caller_context=CallerContext(),
        ).results
        assert result.success, result
        return result.entity_id

    scope = {"cloud": "aws", "aws_account": "123456789012", "aws_region": "us-gov-west-1"}
    scoped = "aws-us-gov:123456789012:us-gov-west-1:default.dax1.0"
    old = create("default.dax1.0", scope)
    occupant = create(scoped, {"cloud": "aws"})  # written under the scoped key, but with no dimensions to undo it by
    m = _migration()

    m.scope_keys(live_apps, None)
    assert DaxParameterGroup.all_objects.get(entity_id=old).dax_parameter_group_id == "default.dax1.0"

    DaxParameterGroup.all_objects.filter(entity_id=old).update(dax_parameter_group_id=scoped + "-x")
    DaxParameterGroup.all_objects.filter(entity_id=occupant).update(dax_parameter_group_id="default.dax1.0-x")
    m.unscope_keys(live_apps, None)  # old would return to default.dax1.0-x, which the orphan holds
    assert DaxParameterGroup.all_objects.get(entity_id=old).dax_parameter_group_id == scoped + "-x"
    assert DaxParameterGroup.all_objects.get(entity_id=occupant).dax_parameter_group_id == "default.dax1.0-x"
