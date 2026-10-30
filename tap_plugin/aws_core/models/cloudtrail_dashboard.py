"""CloudTrail Dashboard — a CloudTrail Lake dashboard."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CloudtrailDashboard(BaseModel):
    """A CloudTrail Lake dashboard: saved queries over event data stores, on a refresh schedule."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cloudtrail_dashboard"
    ENTITY_NAME: ClassVar[str] = "CloudTrail Dashboard"
    ENTITY_DESCRIPTION: ClassVar[str] = "A CloudTrail Lake dashboard."
    ENTITY_ICON: ClassVar[str] = "aws-cloudtrail"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The dashboard's ARN: a name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("dashboard_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "dashboard_arn": {"type": "string"},
        "dashboard_type": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "dashboard_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "dashboard_type": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    dashboard_arn = models.CharField(max_length=512, blank=True, default="")
    # AWS's dashboard type (MANAGED or CUSTOM). NULL = not observed.
    dashboard_type = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cloudtrail_dashboard"

    def get_name(self) -> str:
        return self.name or self.dashboard_arn

    def __str__(self) -> str:
        return self.get_name()
