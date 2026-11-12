"""Every aws_core model names the AWS resource type its ARN belongs to, or says why it has none
(req-aws-collector-identity-11).

George's rulings (Q21b and after): the ARN is the identifier AWS gives a resource, so the grid uses it wherever it
exists. A model whose resource type has an ARN declares ``ARN_RESOURCE = "<service>:<resource>"``, naming the resource
type in AWS's Service Authorization Reference; ``arn_formats.json`` vendors that resource type's ARN formats, so
building an ARN reads the same checked-in data every time. A type whose ARN AWS returns but which the reference lists
no resource type for declares ``ARN_RESOURCE = None`` (RETURNED_ONLY below): its ARN is kept, never built. A type with
no ARN at all declares nothing (NO_ARN below). Each list line carries its reason.

This file checks the declarations and the vendored data only; nothing here changes what the collector writes.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from tap_plugin.aws_core.collectors.boto3_collector import iam_policy

MODELS = Path(iam_policy.MODELS_DIR)
FORMATS = json.loads(iam_policy.ARN_FORMATS.read_text())["resources"]

#: A resource type with no ARN of its own: the model declares no ARN_RESOURCE and keeps its scoped key.
NO_ARN: dict[str, str] = {
    "access_analyzer_finding": "the service reference defines no ARN for an Access Analyzer finding",
    "account_region": "an account's footprint in one Region, which the collector records; not an AWS resource",
    "appstream_directory_config": "the service reference defines no ARN for a directory config",
    "appstream_entitlement": "the service reference defines no ARN for an entitlement",
    "athena_named_query": "the service reference defines no ARN for a named query",
    "autoscaling_lifecycle_hook": "the service reference defines no ARN for a lifecycle hook",
    "autoscalingplans_scaling_plan": "the service reference defines no AWS Auto Scaling Plans resources",
    "az": "an Availability Zone has no ARN in the service reference",
    "backup_backup_selection": "the service reference defines no ARN for a backup selection",
    "backup_restore_testing_selection": "the service reference defines no ARN for a restore testing selection",
    "bedrock_data_source": "the service reference defines no ARN for a knowledge base data source",
    "bedrock_flow_version": "the service reference defines no ARN for a flow version; its arn member is the flow's",
    "bedrock_guardrail_version": "the service reference defines no ARN for a guardrail version; its arn member is the guardrail's",
    "cassandra_type": "the service reference defines no ARN for a user-defined type",
    "cognito_identity_provider": "the service reference defines no ARN for a user pool identity provider",
    "cognito_user_pool_client": "the service reference defines no ARN for a user pool client",
    "cognito_user_pool_domain": "the service reference defines no ARN for a user pool domain",
    "cognito_user_pool_group": "the service reference defines no ARN for a user pool group",
    "cognito_user_pool_resource_server": "the service reference defines no ARN for a resource server",
    "config_delivery_channel": "the service reference defines no ARN for a delivery channel",
    "dax_parameter_group": "the service reference defines an ARN for a DAX cluster only",
    "dax_subnet_group": "the service reference defines an ARN for a DAX cluster only",
    "delegated_administration": "a delegated-administrator registration, which has no ARN",
    "ec2_ipam_pool_cidr": "the service reference defines no ARN for an IPAM pool CIDR",
    "ec2_network_performance_metric_subscription": "the service reference defines no ARN for a metric subscription",
    "ec2_vpc_endpoint_connection_notification": "the service reference defines no ARN for a connection notification; ConnectionNotificationArn is its SNS topic",
    "ecr_repository_creation_template": "the service reference defines no ARN for a repository creation template",
    "efs_mount_target": "the service reference defines no ARN for a mount target",
    "eks_certificate_authority": "the service reference defines no ARN for a cluster's certificate authority",
    "emr_security_configuration": "the service reference defines no ARN for a security configuration",
    "fsx_s3_access_point_attachment": "the service reference defines no ARN for an S3 access point attachment",
    "glue_schema_version": "the service reference defines no ARN for a schema version",
    "glue_security_configuration": "the service reference defines no ARN for a security configuration",
    "guardduty_member": "the service reference defines no ARN for a GuardDuty member",
    "identity_center_account_assignment": "the service reference defines no ARN for an account assignment",
    "identity_center_application_assignment": "the service reference defines no ARN for an application assignment",
    "lakeformation_data_cells_filter": "the service reference defines no Lake Formation resource ARNs",
    "lakeformation_tag": "the service reference defines no Lake Formation resource ARNs",
    "lambda_function_url": "the service reference defines no ARN for a function URL; it carries the function's",
    "lex_bot_version": "the service reference's bot-version ARN is Lex V1's, by bot name; a V2 version has none",
    "logs_integration": "the service reference defines no ARN for a Logs integration",
    "logs_metric_filter": "the service reference defines no ARN for a metric filter",
    "logs_query_definition": "the service reference defines no ARN for a query definition",
    "logs_subscription_filter": "the service reference defines no ARN for a subscription filter",
    "opensearchserverless_access_policy": "the service reference defines no ARN for a serverless policy",
    "opensearchserverless_lifecycle_policy": "the service reference defines no ARN for a serverless policy",
    "opensearchserverless_security_config": "the service reference defines no ARN for a serverless security configuration",
    "opensearchserverless_security_policy": "the service reference defines no ARN for a serverless policy",
    "opensearch_data_source": "the reference's es:datasource is a direct-query data source (opensearch:…:datasource/…); it lists no resource type for a domain's data source, whose key the manifest builds under the domain",
    "opensearchserverless_vpc_endpoint": "the service reference defines no ARN for a serverless VPC endpoint",
    "policy_statement": "a statement inside a policy document, which has no ARN of its own",
    "redshift_cluster_security_group": "the service reference's securitygroup ARN names an EC2 group's ingress into it, not the group",
    "redshift_endpoint_access": "the service reference defines no ARN for an endpoint access",
    "redshift_scheduled_action": "the service reference defines no ARN for a scheduled action",
    "region": "a Region has no ARN in the service reference",
    "resiliencehubv2_service_function": "the service reference defines no ARN for a service function",
    "resiliencehubv2_user_journey": "the service reference defines no ARN for a user journey",
    "route53_record_set": "the service reference defines no ARN for a record set",
    "securityhub_finding": "the service reference defines no ARN for a Security Hub finding",
    "servicecatalog_service_action": "the service reference defines no ARN for a service action",
    "servicecatalog_tag_option": "the service reference defines no ARN for a TagOption",
    "ses_receipt_filter": "the service reference defines no ARN for a receipt filter",
    "ses_receipt_rule_set": "the service reference defines no ARN for a receipt rule set",
    "tag_policy_rule": "a rule inside a tag policy, which has no ARN of its own",
    "verifiedpermissions_identity_source": "the service reference defines an ARN for the policy store only",
    "verifiedpermissions_policy": "the service reference defines an ARN for the policy store only",
    "verifiedpermissions_policy_template": "the service reference defines an ARN for the policy store only",
    "wellarchitected_agent_context": "the service reference defines no ARN for an agent context",
    "wellarchitected_agent_goal": "the service reference defines no ARN for an agent goal",
}

#: AWS returns an ARN, but the reference lists no resource type (or has no file) for it: ARN_RESOURCE = None.
RETURNED_ONLY: dict[str, str] = {
    "applicationautoscaling_scaling_policy": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "autoscaling_scaling_policy": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "autoscaling_scheduled_action": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "cloudformation_hook_version": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "cloudformation_module_version": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "cloudformation_resource_version": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "codebuild_source_credential": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "connect_contact_flow_module_alias": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "connect_contact_flow_module_version": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "connect_contact_flow_version": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "connect_test_case": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "ecs_container": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "guardduty_finding": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "inspector_assessment_target": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "inspector_assessment_template": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "lakeformation_resource": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "securityhub_action_target": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "securityhub_insight": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "securityhub_standards_subscription": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "sns_subscription": "the service reference lists no resource type for it; the ARN AWS returns is kept",
    "servicecatalog_provisioned_product": "the service reference lists no resource type for a provisioned product (servicecatalog:Product is the catalog product, a different ARN); the ARN AWS returns is kept",
}

#: A type that names its ARN resource type but keeps a key that is not the ARN, because some of its rows have no ARN.
KEY_NOT_ARN: dict[str, str] = {
    "account": "an account has an ARN only as a member of an Organization (the format needs the organization id); a "
    "standalone account has none, so the key stays the 12-digit account id and the ARN is stored when Organizations returns it",
}

#: Resource types whose only reference format ends in a policy wildcard (``…:cert:*``): it names every resource of the
#: type at once, so an ARN is never built from it. The models still name the resource type; the ARN AWS returns is used.
WILDCARD_ONLY: dict[str, str] = {
    resource: "the reference gives only an IAM policy wildcard for the resource id; the ARN AWS returns is used"
    for resource in (
        "dms:Certificate",
        "dms:DataMigration",
        "dms:DataProvider",
        "dms:Endpoint",
        "dms:InstanceProfile",
        "dms:MigrationProject",
        "dms:ReplicationConfig",
        "dms:ReplicationInstance",
        "dms:ReplicationTask",
    )
}

_UNSET = object()


def _declarations() -> dict[str, object]:
    """Each model's short entity type -> its ARN_RESOURCE (a string, None, or _UNSET when not declared)."""
    out: dict[str, object] = {}
    for path in sorted(MODELS.glob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, ast.ClassDef):
                continue
            entity_type, resource = None, _UNSET
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    if stmt.target.id == "ENTITY_TYPE":
                        entity_type = stmt.value.value
                    elif stmt.target.id == "ARN_RESOURCE":
                        resource = stmt.value.value
            if entity_type:
                out[entity_type.removeprefix("aws_core__aws_")] = resource
    return out


def test_every_model_names_its_arn_resource_or_says_why_it_has_none() -> None:
    wrong = []
    for name, resource in _declarations().items():
        if resource is _UNSET:
            if name not in NO_ARN:
                wrong.append(f"{name}: declares no ARN_RESOURCE and is not in NO_ARN")
        elif resource is None:
            if name not in RETURNED_ONLY:
                wrong.append(f"{name}: ARN_RESOURCE = None but not in RETURNED_ONLY")
        elif resource not in FORMATS:
            wrong.append(f"{name}: {resource!r} is not in arn_formats.json (run iam_policy.py --refresh)")
    assert not wrong, "\n".join(wrong)


def test_the_lists_hold_only_types_that_need_them() -> None:
    declared = _declarations()
    stale = [n for n in NO_ARN if declared.get(n, None) is not _UNSET]
    stale += [n for n in RETURNED_ONLY if declared.get(n, _UNSET) is not None]
    assert not stale
    assert not set(NO_ARN) & set(RETURNED_ONLY)


def test_a_type_keyed_off_its_arn_still_names_its_arn_resource() -> None:
    """KEY_NOT_ARN is for a type that has an ARN resource type, not a way out of naming one."""
    declared = _declarations()
    assert all(isinstance(declared.get(n), str) for n in KEY_NOT_ARN)
    assert not set(KEY_NOT_ARN) & (set(NO_ARN) | set(RETURNED_ONLY))


def test_a_returned_only_reason_says_which_gap_it_is() -> None:
    """The reference either lists no resource type for it, or has no file for its service at all."""
    vague = [n for n, why in RETURNED_ONLY.items() if "no resource type" not in why and "no file" not in why]
    assert not vague


def test_the_vendored_formats_are_exactly_the_resources_the_models_name() -> None:
    named = {r for r in _declarations().values() if isinstance(r, str)}
    assert set(FORMATS) == named == iam_policy.arn_resources()


def test_every_vendored_format_is_an_arn_with_its_partition_left_open() -> None:
    bad = [
        (resource, fmt)
        for resource, formats in FORMATS.items()
        for fmt in formats or [""]
        if not re.match(r"arn:\$\{Partition\}:[a-z0-9-]+:", fmt)
    ]
    assert not bad


def test_a_wildcard_format_is_listed_so_no_arn_is_ever_built_from_it() -> None:
    """A format whose resource id is ``*`` would build one ARN for every resource of the type: each such resource type
    is listed, with every one of its formats a wildcard, and a listed type that gains a real format drops off."""
    wildcard = {r for r, formats in FORMATS.items() if formats and all("*" in f for f in formats)}
    partly = {r for r, formats in FORMATS.items() if any("*" in f for f in formats) and r not in wildcard}
    assert wildcard == set(WILDCARD_ONLY)
    assert not partly


def test_the_refresh_takes_each_wanted_resource_from_the_reference() -> None:
    docs = [
        {"Name": "ec2", "Resources": [{"Name": "vpc", "ARNFormats": ["arn:${Partition}:ec2:${Region}:${Account}:vpc/${VpcId}"]}, {"Name": "subnet", "ARNFormats": ["x"]}]},
        {"Name": "sns", "Resources": [{"Name": "topic", "ARNFormats": ["arn:${Partition}:sns:${Region}:${Account}:${TopicName}"]}]},
    ]
    got = iam_policy.arn_formats_from(docs, {"ec2:vpc", "sns:topic", "s3:missing"})["resources"]
    assert got == {
        "ec2:vpc": ["arn:${Partition}:ec2:${Region}:${Account}:vpc/${VpcId}"],
        "sns:topic": ["arn:${Partition}:sns:${Region}:${Account}:${TopicName}"],
    }


def test_the_arn_refresh_reads_only_named_services_and_writes_only_the_formats(monkeypatch, tmp_path) -> None:
    """Adding a model runs ``--refresh-arns``, which must not touch the IAM action data."""
    fetched: list[str] = []
    listing = [
        {"service": "ec2", "url": "u/ec2"},
        {"service": "unnamed", "url": "u/unnamed"},
    ]
    doc = {"Name": "ec2", "Resources": [{"Name": "vpc", "ARNFormats": ["arn:${Partition}:ec2:${Region}:${Account}:vpc/${VpcId}"]}]}

    def fake_fetch(url: str):
        fetched.append(url)
        return listing if url.endswith("service-list.json") else doc

    monkeypatch.setattr(iam_policy, "_fetch", fake_fetch)
    monkeypatch.setattr(iam_policy, "arn_resources", lambda: {"ec2:vpc"})
    monkeypatch.setattr(iam_policy, "ARN_FORMATS", tmp_path / "arn_formats.json")
    monkeypatch.setattr(iam_policy, "CATALOG", tmp_path / "iam_operation_actions.json")
    assert iam_policy.refresh_arn_formats() == 1
    assert "u/unnamed" not in fetched
    assert sorted(p.name for p in tmp_path.iterdir()) == ["arn_formats.json"]


def test_the_arn_refresh_refuses_and_writes_nothing_when_a_named_type_is_missing(monkeypatch, tmp_path) -> None:
    listing = [{"service": "ec2", "url": "u/ec2"}]
    doc = {"Name": "ec2", "Resources": [{"Name": "subnet", "ARNFormats": ["x"]}]}
    monkeypatch.setattr(iam_policy, "_fetch", lambda url: listing if url.endswith("service-list.json") else doc)
    monkeypatch.setattr(iam_policy, "arn_resources", lambda: {"ec2:vpc"})
    monkeypatch.setattr(iam_policy, "ARN_FORMATS", tmp_path / "arn_formats.json")
    with pytest.raises(SystemExit, match="ec2:vpc"):
        iam_policy.refresh_arn_formats()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("resource", [{"Name": "vpc"}, {"Name": "vpc", "ARNFormats": []}, {"Name": "vpc", "ARNFormats": ["vpc/${VpcId}"]}])
def test_the_arn_refresh_refuses_a_named_type_with_no_usable_format(monkeypatch, tmp_path, resource) -> None:
    sentinel = tmp_path / "arn_formats.json"
    sentinel.write_text("known good\n")
    monkeypatch.setattr(iam_policy, "arn_resources", lambda: {"ec2:vpc"})
    monkeypatch.setattr(iam_policy, "ARN_FORMATS", sentinel)
    with pytest.raises(SystemExit, match="ec2:vpc"):
        iam_policy.write_arn_formats([{"Name": "ec2", "Resources": [resource]}])
    assert sentinel.read_text() == "known good\n"
    assert [p.name for p in tmp_path.iterdir()] == ["arn_formats.json"]
