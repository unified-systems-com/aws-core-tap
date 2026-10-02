"""AWS Security Hub hub — Security Hub turned on in one account and region."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsSecurityHubHub(BaseModel):
    """One Security Hub hub.

    Read with ``securityhub:DescribeHub``, ``GetEnabledStandards`` (to its last page) and
    ``GetAdministratorAccount``. ``enabled_standards`` is null when any page of the standards
    listing failed (``req-aws-collector-pagination-2``); ``administrator_account_id`` is null when
    its read failed and ``""`` when there is no administrator. Contained by its footprint
    (``HOSTS_SECURITYHUB_HUB``).

    It contains its enabled standards (``HOLDS_STANDARDS_SUBSCRIPTION``) and its active findings
    (``HOLDS_SECURITYHUB_FINDING``), and carries per-severity-label counts of those findings
    (aws-core-tap#76): exact for every label read to its end, a lower bound once the cap is reached.

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-security-services)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_securityhub_hub"
    ENTITY_NAME: ClassVar[str] = "AWS Security Hub"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "AWS Security Hub enabled in one account and region: its enabled standards and the "
        "administrator account it reports to."
    )
    ENTITY_ICON: ClassVar[str] = "aws-security-hub"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("hub_arn",)

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "aws_core__aws_account"}], "edges": [{"type": "REPORTS_TO_ADMINISTRATOR__aws_core"}]},
        {
            "nodes": [{"type": "aws_core__aws_securityhub_finding"}],
            "edges": [{"type": "HOLDS_SECURITYHUB_FINDING__aws_core"}],
        },
        {
            "nodes": [{"type": "aws_core__aws_securityhub_standards_subscription"}],
            "edges": [{"type": "HOLDS_STANDARDS_SUBSCRIPTION__aws_core"}],
        },
    ]
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = (
        "HOLDS_SECURITYHUB_FINDING__aws_core",
        "HOLDS_STANDARDS_SUBSCRIPTION__aws_core",
    )

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "hub_arn": {"type": "string"},
        "subscribed_at": {"type": "string"},
        "auto_enable_controls": {"type": ["boolean", "null"]},
        "control_finding_generator": {"type": "string"},
        # [{"standards_arn": str, "status": str}]; null when the listing did not finish.
        "enabled_standards": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {"standards_arn": {"type": "string"}, "status": {"type": "string"}},
                "additionalProperties": False,
            },
        },
        "administrator_account_id": {"type": ["string", "null"]},
        # Active findings (aws-core-tap#76): {label: count}. Exact when
        # active_finding_counts_complete is true; otherwise a lower bound over the capped read.
        # Null when nothing was read.
        "active_finding_counts": {
            "type": ["object", "null"],
            "additionalProperties": {"type": "integer", "minimum": 0},
        },
        "active_finding_counts_complete": {"type": ["boolean", "null"]},
        # True when the read stopped at the findings cap; null when the listing itself failed.
        "active_findings_truncated": {"type": ["boolean", "null"]},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    hub_arn = models.CharField(max_length=2048, blank=True, default="", db_index=True)
    subscribed_at = models.CharField(max_length=40, blank=True, default="")
    auto_enable_controls = models.BooleanField(null=True, blank=True, default=None)
    control_finding_generator = models.CharField(max_length=32, blank=True, default="")
    enabled_standards = models.JSONField(null=True, blank=True, default=None)
    administrator_account_id = models.CharField(max_length=12, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read", "" is "no administrator"
    # Active findings (aws-core-tap#76; collectors/boto3_collector/findings.py). Null is "not read".
    active_finding_counts = models.JSONField(null=True, blank=True, default=None)
    active_finding_counts_complete = models.BooleanField(null=True, blank=True, default=None)
    active_findings_truncated = models.BooleanField(null=True, blank=True, default=None)
    # AWS tags, canonical flat {str: str}. Source: securityhub:ListTagsForResource (`Tags` map).
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_securityhub_hub"

    def get_name(self) -> str:
        return self.name or self.hub_arn

    def __str__(self) -> str:
        return self.get_name()
