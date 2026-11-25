"""Identity and null defaults for every aws_core model (req-aws-core-fields-7, req-aws-core-fields-8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.apps import apps

MANIFEST = Path(__file__).resolve().parents[1] / "collectors" / "boto3_collector" / "aws_resource_manifest.json"


def _aws_models():
    return [m for m in apps.get_app_config("aws_core").get_models() if getattr(m, "ENTITY_TYPE", "").startswith("aws_core__") and not m.__name__.startswith("Historical")]


def _entries():
    return json.loads(MANIFEST.read_text())["entries"]


def test_every_model_declares_a_natural_key_on_its_own_fields() -> None:
    """req-aws-core-fields-7: every type says how one of it is found again, on fields it carries."""
    for model in _aws_models():
        key = model.__dict__.get("NATURAL_KEY") or getattr(model, "NATURAL_KEY", None)
        assert key, model.ENTITY_TYPE
        fields = {f.name for f in model._meta.get_fields()}
        assert all(k in fields for k in key), (model.ENTITY_TYPE, key)


#: A multi-column type that belongs to no account, so its batch ref is scoped by partition only: (prefix, reason).
SHARED_ACROSS_ACCOUNTS: dict[str, tuple[str, str]] = {
    "aws_core__aws_ssm_patch": (
        "{partition}:",
        (
            "a vendor patch, keyed (partition, operating system, KBId), one node for every instance, region and account "
            "that reports it (ruling B2, aws-core-tap#281)"
        ),
    ),
}


def test_collected_types_key_on_what_the_collector_keys_on() -> None:
    """req-aws-core-fields-7: where the boto3 manifest collects a type, the model's key is the field the manifest's
    natural_key path projects to, so the model and the collector name the same fact."""
    by_type = {m.ENTITY_TYPE: m for m in _aws_models()}
    for entry in _entries():
        model = by_type[entry["entity_type"]]
        if len(model.NATURAL_KEY) > 1:
            # A multi-column key (CloudFormation's identifier for a type AWS gives no ARN, aws-core-tap#251): every
            # column is projected by the entry, and its natural_key is a scoped composite of them, the batch ref only.
            assert set(model.NATURAL_KEY) <= set(entry["fields"]), (entry["entity_type"], model.NATURAL_KEY)
            assert entry["natural_key"] not in entry["fields"].values(), entry["entity_type"]
            # A global entry puts the literal ``global`` in the region place (req-aws-collector-identity-8): the IAM
            # credentials of aws-core-tap#282.
            regional = "{partition}:{account}:global:" if entry["scope"] == "global" else "{partition}:{account}:{region}:"
            scope = SHARED_ACROSS_ACCOUNTS.get(entry["entity_type"], (regional, ""))[0]
            assert entry["derive"][entry["natural_key"]].startswith(scope), entry["entity_type"]
            continue
        projected = [field for field, path in entry["fields"].items() if path == entry["natural_key"]]
        assert projected, entry["entity_type"]
        assert tuple(model.NATURAL_KEY) == (projected[0],), (entry["entity_type"], model.NATURAL_KEY, projected)


@pytest.mark.parametrize(
    ("entity_type", "field"),
    [
        ("aws_core__aws_lambda", "vpc_subnet_ids"),
        ("aws_core__aws_lambda", "vpc_security_group_ids"),
        ("aws_core__aws_cloudfront_distribution", "origin_access"),
    ],
)
def test_structured_security_facts_default_to_null(entity_type: str, field: str) -> None:
    """req-aws-core-fields-8: null is not observed; an empty list or map is an observation, so it is never the default."""
    model = next(m for m in _aws_models() if m.ENTITY_TYPE == entity_type)
    f = model._meta.get_field(field)
    assert f.null and f.default is None
    assert "null" in model.FIELD_CRUD_SCHEMA[field]["type"]
    assert "null" in model.FIELD_VALIDATION_SCHEMA[field]["schema"]["type"]
