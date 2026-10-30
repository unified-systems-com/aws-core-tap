"""CloudWatch Dashboard — an Amazon CloudWatch dashboard."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CloudwatchDashboard(BaseModel):
    """An Amazon CloudWatch dashboard: a saved view of metrics and logs. Only its identity is collected, not the widgets."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cloudwatch_dashboard"
    ENTITY_NAME: ClassVar[str] = "CloudWatch Dashboard"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon CloudWatch dashboard."
    ENTITY_ICON: ClassVar[str] = "aws-cloudwatch"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The dashboard's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("dashboard_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "dashboard_arn": {"type": "string"},
        "size": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "dashboard_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "size": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    dashboard_arn = models.CharField(max_length=512, blank=True, default="")
    # The size of the dashboard body in bytes. NULL = not observed.
    size = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cloudwatch_dashboard"

    def get_name(self) -> str:
        return self.name or self.dashboard_arn

    def __str__(self) -> str:
        return self.get_name()
