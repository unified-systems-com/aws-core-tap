"""Every aws_core type is keyed the way AWS identifies it, or is listed as pending its re-key
(req-aws-collector-identity-2, -12; aws-core-tap#252, George's Q94 ruling of 2026-11-19).

The rule. A type's key is the ARN when the API returns one. Otherwise it is the identifier CloudFormation declares
for the type (``primaryIdentifier`` in the resource schema bundle), multi-column where AWS makes it so, scoped by
account and region. The collector never invents a key, and an ARN the collector builds is a property used for
linking, never a key. A type whose native id already matches AWS (a VPC, a subnet, an instance) keeps it.

What this file holds the line on:

- a type keyed by an ARN the API returns needs nothing more;
- every other type declares its identity: the manifest entry's ``identity`` block, or the model's
  ``AWS_IDENTITY`` when no manifest entry collects it (``manifest.identity_declarations``). The declaration names
  the CloudFormation type it follows and maps each key field onto that type's ``primaryIdentifier``, read from
  ``ledger/aws_coverage_ledger.json`` (``cfn.primary_identifier``, built from the same bundle). A key that differs
  from the identifier says why;
- a type the rule says must be re-keyed, and is not yet, is on one of the PENDING lists below, with the issue that
  re-keys it. The lists may only shrink: a listed type that no longer needs its line fails
  ``test_the_pending_lists_hold_only_types_that_still_need_them``, and ``PENDING_CEILING`` caps their total.

No AWS call is made and nothing here changes what the collector writes.
"""

from __future__ import annotations

import json
import re
from typing import Any

import jsonschema
import pytest

from tap_plugin.aws_core.collectors.boto3_collector.arn_resolver import ARN_FORMATS, WHOLE_ARN, holds_arn, template_names
from tap_plugin.aws_core.collectors.boto3_collector.manifest import (
    MODEL_IDENTITY_ATTR,
    identity_declarations,
    identity_schema,
    manifest_entries,
)
from tap_plugin.aws_core.ledger.__main__ import LEDGER_PATH

PREFIX = "aws_core__aws_"
#: Fixed by the identity defects issue: the response already carries the ARN (or the type is removed, or re-keyed
#: natively). Merging that fix removes these lines.
FIXES_251 = "unified-systems-com/aws-core-tap#251"
#: Re-keyed to the CloudFormation identifier, keeping any built ARN as a stored property.
REKEY_253 = "unified-systems-com/aws-core-tap#253"

#: Keyed by an ARN the collector fills in (a ``derive`` template or a custom function's ``_arn``): built, or copied
#: into a collector field. The ARN stays as a property; the key becomes what AWS returns or CloudFormation declares.
PENDING_BUILT_ARN: dict[str, str] = {
    "access_analyzer_archive_rule": REKEY_253,
    "apigateway_api_key": REKEY_253,
    "apigateway_authorizer": REKEY_253,
    "apigateway_client_certificate": REKEY_253,
    "apigateway_domain_name": REKEY_253,
    "apigateway_http_api": REKEY_253,
    "apigateway_rest_api": REKEY_253,
    "apigateway_stage": REKEY_253,
    "apigateway_usage_plan": REKEY_253,
    "apigateway_vpc_link": REKEY_253,
    "appconfig_application": REKEY_253,
    "appconfig_configuration_profile": REKEY_253,
    "appconfig_deployment_strategy": REKEY_253,
    "appconfig_environment": REKEY_253,
    "appconfig_experiment_definition": REKEY_253,
    "athena_capacity_reservation": REKEY_253,
    "athena_data_catalog": REKEY_253,
    "athena_work_group": REKEY_253,
    "bedrock_agent_alias": REKEY_253,
    "bedrock_automated_reasoning_policy_version": FIXES_251,
    "bedrock_prompt_version": FIXES_251,
    "cloudwatch_insight_rule": REKEY_253,
    "codedeploy_application": REKEY_253,
    "codedeploy_deployment_config": REKEY_253,
    "codedeploy_deployment_group": REKEY_253,
    "codepipeline_custom_action_type": REKEY_253,
    "codepipeline_pipeline": REKEY_253,
    "directconnect_lag": REKEY_253,
    "eventbridge_archive": REKEY_253,
    "fms_resource_set": REKEY_253,
    "glue_blueprint": REKEY_253,
    "glue_connection": REKEY_253,
    "glue_connection_type": REKEY_253,
    "glue_crawler": REKEY_253,
    "glue_custom_entity_type": REKEY_253,
    "glue_data_quality_ruleset": REKEY_253,
    "glue_database": REKEY_253,
    "glue_dev_endpoint": REKEY_253,
    "glue_job": REKEY_253,
    "glue_ml_transform": REKEY_253,
    "glue_session": REKEY_253,
    "glue_table": REKEY_253,
    "glue_trigger": REKEY_253,
    "glue_usage_profile": REKEY_253,
    "glue_workflow": REKEY_253,
    "guardduty_malware_protection_plan": FIXES_251,
    "guardduty_threat_entity_set": REKEY_253,
    "guardduty_trusted_entity_set": REKEY_253,
    "iot_software_package": REKEY_253,
    "iot_software_package_version": REKEY_253,
    "iotsitewise_access_policy": REKEY_253,
    "iotsitewise_dashboard": REKEY_253,
    "iotsitewise_gateway": REKEY_253,
    "iotsitewise_portal": REKEY_253,
    "iotsitewise_project": REKEY_253,
    "kendra_data_source": REKEY_253,
    "kendra_faq": REKEY_253,
    "kendra_featured_results_set": REKEY_253,
    "kendra_index": REKEY_253,
    "kendra_query_suggestions_block_list": REKEY_253,
    "kendra_thesaurus": REKEY_253,
    "kendraranking_execution_plan": FIXES_251,
    "lambda_event_source_mapping": REKEY_253,
    "lex_bot": REKEY_253,
    "lex_bot_alias": REKEY_253,
    "location_api_key": REKEY_253,
    "location_geofence_collection": FIXES_251,
    "location_map": FIXES_251,
    "location_place_index": REKEY_253,
    "location_route_calculator": REKEY_253,
    "location_tracker": FIXES_251,
    "opensearch_data_source": FIXES_251,
    "pinpointemail_configuration_set": FIXES_251,
    "pinpointemail_identity": FIXES_251,
    "qbusiness_application": FIXES_251,
    "qbusiness_data_source": REKEY_253,
    "qbusiness_index": REKEY_253,
    "qbusiness_plugin": REKEY_253,
    "qbusiness_retriever": REKEY_253,
    "qbusiness_web_experience": REKEY_253,
    "redshift_cluster": REKEY_253,
    "redshift_cluster_parameter_group": REKEY_253,
    "redshift_cluster_subnet_group": REKEY_253,
    "redshift_event_subscription": REKEY_253,
    "redshift_snapshot": FIXES_251,
    "redshift_snapshot_copy_grant": REKEY_253,
    "redshift_snapshot_schedule": REKEY_253,
    "redshift_usage_limit": REKEY_253,
    "route53_traffic_policy": REKEY_253,
    "route53profiles_profile_association": REKEY_253,
    "sagemaker_inference_experiment": FIXES_251,
    "sagemaker_space": FIXES_251,
    "sagemaker_user_profile": FIXES_251,
    "ses_configuration_set": REKEY_253,
    "ses_contact_list": REKEY_253,
    "ses_custom_verification_email_template": REKEY_253,
    "ses_dedicated_ip_pool": REKEY_253,
    "ses_email_identity": REKEY_253,
    "ses_multi_region_endpoint": REKEY_253,
    "ses_template": REKEY_253,
    "ssm_document": REKEY_253,
    "ssm_resource_data_sync": REKEY_253,
    "synthetics_canary": REKEY_253,
    "textract_adapter": REKEY_253,
    "transcribe_call_analytics_category": REKEY_253,
    "transcribe_medical_vocabulary": REKEY_253,
    "transcribe_vocabulary": REKEY_253,
    "transcribe_vocabulary_filter": REKEY_253,
    "wafregional_rate_based_rule": REKEY_253,
    "wafregional_rule": REKEY_253,
    "wafregional_web_acl": FIXES_251,
    "wafv2_ip_set": REKEY_253,
    "wafv2_regex_pattern_set": REKEY_253,
    "wafv2_rule_group": REKEY_253,
    "wafv2_web_acl": REKEY_253,
}

#: Keyed by a string the collector makes (a ``_key`` or ``_id`` joined from parts, ``_scoped_key``,
#: ``_record_set_key``): CloudFormation's identifier for each is one or more columns, scoped by account and region.
PENDING_HOUSE_KEY: dict[str, str] = {
    "appstream_directory_config": REKEY_253,
    "appstream_entitlement": REKEY_253,
    "autoscaling_lifecycle_hook": REKEY_253,
    "autoscalingplans_scaling_plan": REKEY_253,
    "backup_restore_testing_selection": REKEY_253,
    "bedrock_data_source": REKEY_253,
    "bedrock_flow_version": REKEY_253,
    "bedrock_guardrail_version": REKEY_253,
    "cassandra_type": REKEY_253,
    "cognito_identity_provider": REKEY_253,
    "cognito_user_pool_client": REKEY_253,
    "cognito_user_pool_domain": REKEY_253,
    "cognito_user_pool_group": REKEY_253,
    "cognito_user_pool_resource_server": REKEY_253,
    "dax_parameter_group": REKEY_253,
    "dax_subnet_group": REKEY_253,
    "ec2_network_performance_metric_subscription": REKEY_253,
    "ecr_repository_creation_template": REKEY_253,
    "eks_certificate_authority": REKEY_253,
    "elb_classic_listener": REKEY_253,
    "emr_security_configuration": REKEY_253,
    "fsx_s3_access_point_attachment": REKEY_253,
    "glue_security_configuration": REKEY_253,
    "guardduty_filter": REKEY_253,
    "guardduty_ip_set": REKEY_253,
    "guardduty_member": REKEY_253,
    "guardduty_publishing_destination": REKEY_253,
    "guardduty_threat_intel_set": REKEY_253,
    "identity_center_application_assignment": REKEY_253,
    "identity_center_user": REKEY_253,
    "lakeformation_data_cells_filter": REKEY_253,
    "lakeformation_tag": REKEY_253,
    "lex_bot_version": REKEY_253,
    "logs_integration": REKEY_253,
    "logs_metric_filter": REKEY_253,
    "logs_subscription_filter": REKEY_253,
    "opensearchserverless_access_policy": REKEY_253,
    "opensearchserverless_lifecycle_policy": REKEY_253,
    "opensearchserverless_security_config": REKEY_253,
    "opensearchserverless_security_policy": REKEY_253,
    "redshift_cluster_security_group": REKEY_253,
    "redshift_endpoint_access": REKEY_253,
    "redshift_scheduled_action": REKEY_253,
    "resiliencehubv2_service_function": REKEY_253,
    "resiliencehubv2_user_journey": REKEY_253,
    "route53_record_set": REKEY_253,
    "ses_receipt_filter": REKEY_253,
    "ses_receipt_rule_set": REKEY_253,
    "verifiedpermissions_identity_source": REKEY_253,
    "verifiedpermissions_policy": REKEY_253,
    "verifiedpermissions_policy_template": REKEY_253,
}

#: Keyed by a value the response returns that is not CloudFormation's identifier, with no reason that would make it
#: an exception. #253 re-keys each, or gives it a declaration whose reason holds.
PENDING_DIFFERS: dict[str, tuple[str, str]] = {
    "ec2_key_pair": (REKEY_253, "keyed by KeyPairId; CloudFormation's identifier is KeyName"),
    "elb": (REKEY_253, "keyed by DNSName; CloudFormation's identifier is LoadBalancerName"),
    "lambda_function_url": (REKEY_253, "keyed by FunctionUrl; CloudFormation's identifier is FunctionArn, which the response returns"),
    "rum_app_monitor": (REKEY_253, "keyed by Id; CloudFormation's identifier is Name"),
}

#: The pending lists' total may only go down. Lower it with every re-key; never raise it.
PENDING_CEILING = 170

#: Scope columns a declaration may add to CloudFormation's identifier (the rule scopes it by account and region).
SCOPE_MARKERS = {"@account", "@region", "@partition"}


def _entity(short: str) -> str:
    return f"{PREFIX}{short}"


def _models() -> dict[str, type]:
    from tap_grid.registry import get_model_class, list_entity_types

    return {t: get_model_class(t) for t in list_entity_types() if t.startswith(PREFIX)}


def _entries() -> dict[str, dict[str, Any]]:
    return {str(e["entity_type"]): e for e in manifest_entries()}


def _ledger_identifiers() -> dict[str, dict[str, list[str]]]:
    """``{entity type: {CloudFormation type: [primaryIdentifier property names]}}`` for every ledger row that maps
    an aws_core type."""
    out: dict[str, dict[str, list[str]]] = {}
    for row in json.loads(LEDGER_PATH.read_text())["rows"]:
        pointers = (row.get("cfn") or {}).get("primary_identifier") or []
        for entity_type in row.get("entity_types") or []:
            out.setdefault(entity_type, {})[row["type_name"]] = [p.rsplit("/", 1)[-1] for p in pointers]
    return out


def _key(model: type) -> tuple[str, ...]:
    return tuple(getattr(model, "NATURAL_KEY", ()) or ())


def _arn_keyed(model: type) -> bool:
    key = _key(model)
    return len(key) == 1 and holds_arn(key[0])


def _collector_field(entry: dict[str, Any] | None) -> bool:
    """Whether the entry's key is read from a field the collector fills (``derive`` or a custom function), not a
    member AWS returns. A type no manifest entry collects is written by a reader that keys it on the response."""
    return entry is not None and str(entry["natural_key"]).startswith("_")


def _pending() -> dict[str, str]:
    out = dict(PENDING_BUILT_ARN) | dict(PENDING_HOUSE_KEY) | {k: v[0] for k, v in PENDING_DIFFERS.items()}
    return {_entity(k): v for k, v in out.items()}


@pytest.mark.spec("req-aws-collector-identity-12")
def test_every_key_is_an_arn_the_api_returns_a_declared_identity_or_pending() -> None:
    models, entries, declared, pending = _models(), _entries(), identity_declarations(), _pending()
    assert len(models) > 900
    wrong = []
    for entity_type, model in sorted(models.items()):
        entry = entries.get(entity_type)
        if _arn_keyed(model) and not _collector_field(entry):
            continue
        if entity_type in pending:
            continue
        if _arn_keyed(model):
            wrong.append(f"{entity_type}: keyed by an ARN the collector fills ({entry and entry['natural_key']}); "
                         "a built ARN is a property, not a key")
        elif entity_type not in declared:
            wrong.append(f"{entity_type}: keyed by {list(_key(model))}, not an ARN, and declares no identity")
    assert not wrong, "\n".join(wrong)


@pytest.mark.spec("req-aws-collector-identity-12")
def test_a_declaration_maps_exactly_the_models_key_fields() -> None:
    models, wrong = _models(), []
    for entity_type, declaration in identity_declarations().items():
        key = set(_key(models[entity_type]))
        for block in ("key", "arn_key"):
            if block in declaration and set(declaration[block]) != key:
                wrong.append(f"{entity_type}: {block} names {sorted(declaration[block])}, NATURAL_KEY is {sorted(key)}")
    assert not wrong, "\n".join(wrong)


@pytest.mark.spec("req-aws-collector-identity-12")
def test_a_declaration_follows_its_cloudformation_identifier_or_says_why() -> None:
    """The declared CloudFormation type is one the ledger maps to this entity type, and the key's columns, less its
    account and region scope, are that type's ``primaryIdentifier``. A key that differs carries a reason, and only
    one that differs does. A declaration with no CloudFormation type is for a type the ledger maps to none."""
    ledger, wrong = _ledger_identifiers(), []
    for entity_type, declaration in sorted(identity_declarations().items()):
        cfn_type, reason = declaration["cfn_type"], declaration.get("reason")
        mapped = ledger.get(entity_type, {})
        if cfn_type is None:
            if mapped:
                wrong.append(f"{entity_type}: no cfn_type, but the ledger maps it to {sorted(mapped)}")
            continue
        if cfn_type not in mapped:
            wrong.append(f"{entity_type}: {cfn_type} is not a ledger row mapping it (rows: {sorted(mapped)})")
            continue
        columns = {v for v in declaration["key"].values() if v not in SCOPE_MARKERS}
        identifier = set(mapped[cfn_type])
        if columns != identifier and not reason:
            wrong.append(f"{entity_type}: key columns {sorted(columns)} are not {cfn_type}'s identifier {sorted(identifier)}, and no reason says why")
        if columns == identifier and reason:
            wrong.append(f"{entity_type}: follows {cfn_type}'s identifier, so its reason has nothing to explain")
    assert not wrong, "\n".join(wrong)


@pytest.mark.spec("req-aws-collector-identity-12")
def test_an_arn_key_reads_only_placeholders_its_formats_have() -> None:
    """Each ``arn_key`` template reads placeholders of the model's ``ARN_RESOURCE`` formats (or of its declared
    ``other_ids``), all of them from one format, so the resolver can fill every key field from one match."""
    formats = json.loads(ARN_FORMATS.read_text())["resources"]
    models, wrong = _models(), []
    for entity_type, declaration in sorted(identity_declarations().items()):
        templates = declaration.get("arn_key")
        if not templates:
            continue
        resource = getattr(models[entity_type], "ARN_RESOURCE", None)
        shapes = list(formats.get(resource, [])) if isinstance(resource, str) else []
        shapes += list(declaration.get("other_ids") or [])
        needed = set().union(*(template_names(t) for t in templates.values()))
        if not any(needed <= set(re.findall(r"\$\{(\w+)\}", shape)) for shape in shapes):
            wrong.append(f"{entity_type}: arn_key reads {sorted(needed)}; no format of {resource!r} has them all")
        if WHOLE_ARN in templates.values() and not shapes:
            wrong.append(f"{entity_type}: {WHOLE_ARN} needs an ARN resource type to match")
    assert not wrong, "\n".join(wrong)


@pytest.mark.spec("req-aws-collector-identity-12")
def test_the_pending_lists_hold_only_types_that_still_need_them() -> None:
    models, entries, declared = _models(), _entries(), identity_declarations()
    pending = _pending()
    assert len(pending) == len(PENDING_BUILT_ARN) + len(PENDING_HOUSE_KEY) + len(PENDING_DIFFERS), "a type is listed twice"
    assert len(pending) <= PENDING_CEILING, "the pending lists only shrink: re-key, do not add"
    assert set(pending.values()) <= {FIXES_251, REKEY_253}
    stale = []
    for short in PENDING_BUILT_ARN:
        t = _entity(short)
        if t not in models or not (_arn_keyed(models[t]) and _collector_field(entries.get(t))):
            stale.append(f"{short}: no longer keyed by an ARN the collector fills")
    for short in PENDING_HOUSE_KEY:
        t = _entity(short)
        if t not in models or _arn_keyed(models[t]) or not _collector_field(entries.get(t)) or t in declared:
            stale.append(f"{short}: no longer keyed by a string the collector makes")
    for short in PENDING_DIFFERS:
        t = _entity(short)
        if t not in models or _arn_keyed(models[t]) or _collector_field(entries.get(t)) or t in declared:
            stale.append(f"{short}: re-keyed or declared")
    assert not stale, "remove the line (and lower PENDING_CEILING):\n" + "\n".join(stale)


@pytest.mark.spec("req-aws-collector-identity-12")
def test_a_type_collected_by_no_manifest_entry_declares_on_its_model() -> None:
    """The manifest carries the declarations of the types it collects; ``AWS_IDENTITY`` is only for the others."""
    entries, wrong = _entries(), []
    for entity_type, model in _models().items():
        if getattr(model, MODEL_IDENTITY_ATTR, None) is not None and entity_type in entries:
            wrong.append(f"{entity_type}: collected by a manifest entry, so its identity belongs there")
    assert not wrong, "\n".join(wrong)


@pytest.mark.spec("req-aws-collector-identity-12")
@pytest.mark.parametrize(
    ("declaration", "valid"),
    [
        ({"cfn_type": "AWS::EC2::VPC", "key": {"vpc_id": "VpcId"}, "arn_key": {"vpc_id": "${VpcId}"}}, True),
        ({"cfn_type": None, "reason": "not a CloudFormation resource"}, True),
        # A type with no CloudFormation type says what names it, and maps no key onto an identifier it lacks.
        ({"cfn_type": None}, False),
        ({"cfn_type": None, "reason": "x", "key": {"a": "A"}}, False),
        # A type with one maps its key.
        ({"cfn_type": "AWS::EC2::VPC"}, False),
        # A key column is a CloudFormation property or a scope marker.
        ({"cfn_type": "AWS::EC2::VPC", "key": {"vpc_id": "vpc id"}}, False),
        ({"cfn_type": "AWS::GuardDuty::Detector", "key": {"account_id": "@account", "detector_id": "Id"}}, True),
        # Other id forms are read through the ARN key's templates.
        ({"cfn_type": "AWS::Organizations::Account", "key": {"account_id": "AccountId"}, "other_ids": ["AWS::::Account:${AccountId}"]}, False),
        ({"cfn_type": "AWS::EC2::VPC", "key": {"vpc_id": "VpcId"}, "unknown": 1}, False),
    ],
)
def test_the_schema_holds_the_declarations_shape(declaration: dict[str, Any], valid: bool) -> None:
    errors = list(jsonschema.Draft202012Validator(identity_schema()).iter_errors(declaration))
    assert (not errors) is valid, [e.message for e in errors]
