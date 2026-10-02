"""AWS Config conformance pack — one conformance pack in one account and region, with its compliance."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsConfigConformancePack(BaseModel):
    """One AWS Config conformance pack.

    Read with ``config:DescribeConformancePacks`` (no names: every pack) to its last page, and its
    compliance with ``GetConformancePackComplianceSummary`` (five names per call). Keyed by the
    pack's ARN. Contained by its footprint (``HOSTS_CONFORMANCE_PACK``). ``compliance_status`` is null
    when the summary read failed before naming the pack. The pack's input parameters and template
    are not stored.

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-findings)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_config_conformance_pack"
    ENTITY_NAME: ClassVar[str] = "AWS Config Conformance Pack"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Config conformance pack in one account and region: a deployed set of Config rules and "
        "its overall compliance."
    )
    ENTITY_ICON: ClassVar[str] = "aws-config"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("pack_arn",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "pack_arn": {"type": "string"},
        "pack_name": {"type": "string"},
        "pack_id": {"type": "string"},
        "created_by": {"type": "string"},
        "delivery_s3_bucket": {"type": "string"},
        "last_update_requested_at": {"type": "string"},
        # COMPLIANT, NON_COMPLIANT or INSUFFICIENT_DATA, verbatim; null when unread.
        "compliance_status": {"type": ["string", "null"]},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    pack_arn = models.CharField(max_length=2048, blank=True, default="", db_index=True)
    pack_name = models.CharField(max_length=256, blank=True, default="")
    pack_id = models.CharField(max_length=1024, blank=True, default="")
    created_by = models.CharField(max_length=256, blank=True, default="")
    delivery_s3_bucket = models.CharField(max_length=63, blank=True, default="")
    last_update_requested_at = models.CharField(max_length=40, blank=True, default="")
    compliance_status = models.CharField(max_length=32, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    # AWS tags, canonical flat {str: str}. Source: config:ListTagsForResource (`Tags`, list_kv).
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_config_conformance_pack"

    def get_name(self) -> str:
        return self.name or self.pack_name or self.pack_arn

    def __str__(self) -> str:
        return self.get_name()
