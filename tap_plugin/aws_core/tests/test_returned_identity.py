"""A key AWS returns is read, never built; a key AWS does not return is never invented (req-aws-collector-identity-12).

aws-core-tap#251 (part of the Q94 identity epic, aws-core-tap#250): ten types built their ARN from a summary although the
detail call returns it, Redshift snapshots built theirs under the caller's account although each item carries its own
``SnapshotArn``, the two Pinpoint Email types keyed one SES resource a second time, and the OpenSearch data source was
keyed on an ARN AWS does not define. The two Bedrock version types still build theirs: botocore does not establish
that the ARN their listing returns names the version (``PromptSummary.arn`` is "the prompt or the prompt version",
``AutomatedReasoningPolicySummary.policyArn`` is "the policy").
"""

from __future__ import annotations

import ast
from pathlib import Path

import botocore.session
import pytest
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries

MODELS = Path(__file__).resolve().parents[1] / "models"

#: Each type whose ARN a response the collector reads returns, and the member that carries it.
RETURNED: dict[str, str] = {
    "kendraranking_execution_plan": "Arn",
    "sagemaker_space": "SpaceArn",
    "sagemaker_user_profile": "UserProfileArn",
    "sagemaker_inference_experiment": "Arn",
    "location_geofence_collection": "CollectionArn",
    "location_map": "MapArn",
    "location_tracker": "TrackerArn",
    "guardduty_malware_protection_plan": "Arn",
    "qbusiness_application": "applicationArn",
    "wafregional_web_acl": "WebACLArn",
    "redshift_snapshot": "SnapshotArn",
}


def _entries() -> dict[str, dict]:
    return {e["entity_type"].removeprefix("aws_core__aws_"): e for e in manifest_entries()}


def _item_shape(entry: dict):
    model = botocore.session.get_session().get_service_model(entry["service"])
    shape = model.operation_model(entry["source"]["aws_op"]).output_shape
    for segment in entry["items_path"].split("."):
        name = segment.removesuffix("[]")
        if name:
            shape = shape.members[name]
        if segment.endswith("[]"):
            shape = shape.member
    return shape


@pytest.mark.parametrize(("name", "member"), sorted(RETURNED.items()))
def test_a_type_whose_response_returns_its_arn_is_keyed_on_it(name: str, member: str) -> None:
    entry = _entries()[name]
    assert entry["natural_key"] == member
    assert member not in (entry.get("derive") or {}), "the key AWS returns is never overwritten by a built one"
    assert "_arn" not in (entry.get("derive") or {})
    # The member is in what the call the entry reads returns (the detail call, for a summary that lacks it).
    assert member in _item_shape(entry).members, (entry["source"]["aws_op"], member)
    arn_fields = [field for field, path in entry["fields"].items() if path == member]
    assert arn_fields == [f"{name}_arn"]


def _arn_resource(path: Path) -> object:
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "ARN_RESOURCE" and node.value is not None:
            return ast.literal_eval(node.value)
    return None


@pytest.mark.parametrize(("resource", "owner"), [("ses:configuration-set", "ses_configuration_set"), ("ses:identity", "ses_email_identity")])
def test_one_ses_resource_is_one_type_not_a_second_pinpoint_email_one(resource: str, owner: str) -> None:
    """Two types claiming one ARN resource type land one resource as two nodes, and the ARN resolver refuses both."""
    claims = sorted(p.stem for p in MODELS.glob("*.py") if _arn_resource(p) == resource)
    assert claims == [owner]
    assert not [e for e in manifest_entries() if e["service"] == "pinpoint-email"]


def test_the_opensearch_data_source_is_keyed_on_its_own_columns_with_no_arn_built() -> None:
    entry = _entries()["opensearch_data_source"]
    assert not any(template.startswith("arn:") for template in (entry.get("derive") or {}).values())
    assert {"account_id", "region", "domain_name", "data_source_name"} <= set(entry["fields"])
    assert entry["fields"]["domain_name"] == "_parent.DomainName" and entry["fields"]["data_source_name"] == "Name"
    tree = ast.parse((MODELS / "opensearch_data_source.py").read_text())
    key = next(
        ast.literal_eval(n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", None) == "NATURAL_KEY"
    )
    assert key == ("account_id", "region", "domain_name", "data_source_name")
