"""SSM Compliance Summary — one resource's compliance for one compliance type (req-aws-core-ssm-patch-state)."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import NO_EVENT_TIME, NoEventTime
from tap_grid.models import BaseModel


class SsmComplianceSummary(BaseModel):
    """One ListResourceComplianceSummaries row: a resource's status for one compliance type, with its compliant and non-compliant counts by severity and the last execution. Held by its managed instance (HOLDS_COMPLIANCE_SUMMARY)."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ssm_compliance_summary"
    ENTITY_NAME: ClassVar[str] = "SSM Compliance Summary"
    ENTITY_DESCRIPTION: ClassVar[str] = "One resource's compliance for one SSM compliance type (Patch, Association, Custom), with counts by severity."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): Account, region, resource type and id, and compliance type: a summary has no ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("account_id", "region", "resource_type", "resource_id", "compliance_type")
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): no typed field of this model says when
    # the thing happened in the world; EVENT_TIME_REASON says why.
    EVENT_TIME: ClassVar[NoEventTime] = NO_EVENT_TIME
    EVENT_TIME_REASON: ClassVar[str] = (
        "AWS states only ExecutionSummary.ExecutionTime (ListResourceComplianceSummaries "
        "ResourceComplianceSummaryItems[]), when the latest compliance execution ran, which the next execution "
        "replaces on this same summary: a last-change time, and none of the four kinds names it (reported on "
        "unified-systems-com/tap#1289). It stays the typed execution_time field."
    )

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "account_id": {"type": "string", "pattern": "^([0-9]{12})?$"},
        "region": {"type": "string"},
        "resource_type": {"type": "string"},
        "resource_id": {"type": "string"},
        "compliance_type": {"type": "string"},
        "status": {"type": ["string", "null"]},
        "overall_severity": {"type": ["string", "null"]},
        "execution_time": {"type": ["string", "null"]},
        "execution_id": {"type": ["string", "null"]},
        "execution_type": {"type": ["string", "null"]},
        "compliant_count": {"type": ["integer", "null"]},
        "compliant_critical_count": {"type": ["integer", "null"]},
        "compliant_high_count": {"type": ["integer", "null"]},
        "compliant_medium_count": {"type": ["integer", "null"]},
        "compliant_low_count": {"type": ["integer", "null"]},
        "compliant_informational_count": {"type": ["integer", "null"]},
        "compliant_unspecified_count": {"type": ["integer", "null"]},
        "non_compliant_count": {"type": ["integer", "null"]},
        "non_compliant_critical_count": {"type": ["integer", "null"]},
        "non_compliant_high_count": {"type": ["integer", "null"]},
        "non_compliant_medium_count": {"type": ["integer", "null"]},
        "non_compliant_low_count": {"type": ["integer", "null"]},
        "non_compliant_informational_count": {"type": ["integer", "null"]},
        "non_compliant_unspecified_count": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["resource_id"]

    name = models.CharField(max_length=255, blank=True, default="")
    account_id = models.CharField(max_length=12, blank=True, default="")
    region = models.CharField(max_length=32, blank=True, default="")
    resource_type = models.CharField(max_length=64, blank=True, default="")
    resource_id = models.CharField(max_length=255, blank=True, default="")
    # Patch, Association, or Custom:<name>.
    compliance_type = models.CharField(max_length=255, blank=True, default="")
    # COMPLIANT or NON_COMPLIANT.
    status = models.CharField(max_length=32, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    overall_severity = models.CharField(max_length=32, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    execution_time = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    execution_id = models.CharField(max_length=255, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    execution_type = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    compliant_count = models.IntegerField(null=True, blank=True, default=None)
    compliant_critical_count = models.IntegerField(null=True, blank=True, default=None)
    compliant_high_count = models.IntegerField(null=True, blank=True, default=None)
    compliant_medium_count = models.IntegerField(null=True, blank=True, default=None)
    compliant_low_count = models.IntegerField(null=True, blank=True, default=None)
    compliant_informational_count = models.IntegerField(null=True, blank=True, default=None)
    compliant_unspecified_count = models.IntegerField(null=True, blank=True, default=None)
    non_compliant_count = models.IntegerField(null=True, blank=True, default=None)
    non_compliant_critical_count = models.IntegerField(null=True, blank=True, default=None)
    non_compliant_high_count = models.IntegerField(null=True, blank=True, default=None)
    non_compliant_medium_count = models.IntegerField(null=True, blank=True, default=None)
    non_compliant_low_count = models.IntegerField(null=True, blank=True, default=None)
    non_compliant_informational_count = models.IntegerField(null=True, blank=True, default=None)
    non_compliant_unspecified_count = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ssm_compliance_summary"

    def get_name(self) -> str:
        return self.name or f"{self.resource_id} {self.compliance_type}"

    def __str__(self) -> str:
        return self.get_name()
