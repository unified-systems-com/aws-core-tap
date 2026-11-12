"""AWS Security Hub standards subscription — one standard enabled on one hub."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsSecurityHubStandardsSubscription(BaseModel):
    """One enabled Security Hub standard (for example AWS Foundational Security Best Practices or
    NIST SP 800-53) on one hub.

    Read with ``securityhub:GetEnabledStandards`` (unfiltered, to its last page), the same listing
    the hub's ``enabled_standards`` field is read from. Keyed by ``StandardsSubscriptionArn``.
    Contained by its hub (``HOLDS_STANDARDS_SUBSCRIPTION``). A control finding evaluated under the
    standard points here (``EVALUATED_UNDER_STANDARD``), matched on ``standards_id``. The
    ``StandardsInput`` parameters are not stored.

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-findings)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_securityhub_standards_subscription"
    ENTITY_NAME: ClassVar[str] = "AWS Security Hub Enabled Standard"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "A security standard enabled on an AWS Security Hub hub, whose controls produce control findings."
    )
    ENTITY_ICON: ClassVar[str] = "aws-security-hub"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("subscription_arn",)
    # The ARN AWS returns is this resource's own; the service reference lists no resource type for it,
    # so it cannot be built when absent.
    ARN_RESOURCE: ClassVar[str | None] = None

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "subscription_arn": {"type": "string"},
        "standards_arn": {"type": ["string", "null"]},
        # The resource portion of standards_arn: what a control finding's AssociatedStandards names.
        "standards_id": {"type": ["string", "null"]},
        # PENDING, READY, FAILED, DELETING or INCOMPLETE, verbatim.
        "status": {"type": ["string", "null"]},
        "status_reason": {"type": ["string", "null"]},
        "controls_updatable": {"type": ["string", "null"]},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    subscription_arn = models.CharField(max_length=2048, blank=True, default="", db_index=True)
    standards_arn = models.CharField(max_length=2048, null=True, blank=True, default=None)
    standards_id = models.CharField(max_length=512, null=True, blank=True, default=None)
    status = models.CharField(max_length=16, null=True, blank=True, default=None)
    status_reason = models.CharField(max_length=64, null=True, blank=True, default=None)
    controls_updatable = models.CharField(max_length=32, null=True, blank=True, default=None)
    # AWS cannot tag a standards subscription: always {} (tag_lanes.json, lane `none`).
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_securityhub_standards_subscription"

    def get_name(self) -> str:
        return self.name or self.subscription_arn

    def __str__(self) -> str:
        return self.get_name()
