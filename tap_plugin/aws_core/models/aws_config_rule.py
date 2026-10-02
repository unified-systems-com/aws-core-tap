"""AWS Config rule — one Config rule in one account and region, with its compliance."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsConfigRule(BaseModel):
    """One AWS Config rule: AWS managed, custom Lambda, custom policy, or service-linked (Security
    Hub's control rules, a conformance pack's rules).

    Read with ``config:DescribeConfigRules`` (no names, no filters: botocore documents that as every
    rule) and ``DescribeComplianceByConfigRule`` (every rule, every compliance type), each to its
    last page. Keyed by the rule's ARN. Contained by its footprint (``HOSTS_CONFIG_RULE``).

    ``compliance_type`` is null when the compliance listing failed before naming the rule, and ``""``
    when it read to its end without naming it. ``non_compliant_resource_count`` is AWS's capped count
    (``CappedCount``); ``non_compliant_count_capped`` says when AWS's own cap was exceeded. The
    rule's ``InputParameters`` are not stored.

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-findings)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_config_rule"
    ENTITY_NAME: ClassVar[str] = "AWS Config Rule"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Config rule in one account and region: its source and its current compliance."
    )
    ENTITY_ICON: ClassVar[str] = "aws-config"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("rule_arn",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "rule_arn": {"type": "string"},
        "rule_name": {"type": "string"},
        "rule_id": {"type": "string"},
        "description": {"type": "string"},
        # AWS, CUSTOM_LAMBDA or CUSTOM_POLICY, verbatim.
        "source_owner": {"type": "string"},
        # The managed rule's identifier (for example S3_BUCKET_PUBLIC_READ_PROHIBITED) or a Lambda ARN.
        "source_identifier": {"type": "string"},
        "state": {"type": "string"},
        # The service principal that created a service-linked rule; "" for a rule an operator made.
        "created_by": {"type": "string"},
        "maximum_execution_frequency": {"type": "string"},
        # COMPLIANT, NON_COMPLIANT, NOT_APPLICABLE or INSUFFICIENT_DATA, verbatim.
        "compliance_type": {"type": ["string", "null"]},
        "non_compliant_resource_count": {"type": ["integer", "null"]},
        "non_compliant_count_capped": {"type": ["boolean", "null"]},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    rule_arn = models.CharField(max_length=2048, blank=True, default="", db_index=True)
    rule_name = models.CharField(max_length=128, blank=True, default="")
    rule_id = models.CharField(max_length=64, blank=True, default="")
    description = models.CharField(max_length=256, blank=True, default="")
    source_owner = models.CharField(max_length=32, blank=True, default="")
    source_identifier = models.CharField(max_length=256, blank=True, default="")
    state = models.CharField(max_length=32, blank=True, default="")
    created_by = models.CharField(max_length=256, blank=True, default="")
    maximum_execution_frequency = models.CharField(max_length=32, blank=True, default="")
    compliance_type = models.CharField(max_length=32, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read", "" is "not evaluated"
    non_compliant_resource_count = models.IntegerField(null=True, blank=True, default=None)
    non_compliant_count_capped = models.BooleanField(null=True, blank=True, default=None)
    # AWS tags, canonical flat {str: str}. Source: config:ListTagsForResource (`Tags`, list_kv).
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_config_rule"

    def get_name(self) -> str:
        return self.name or self.rule_name or self.rule_arn

    def __str__(self) -> str:
        return self.get_name()
