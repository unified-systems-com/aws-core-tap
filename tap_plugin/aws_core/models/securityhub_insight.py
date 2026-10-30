"""Security Hub Insight — a Security Hub insight."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class SecurityhubInsight(BaseModel):
    """A Security Hub insight: a saved filter and grouping over findings. Only its identity is typed; the filters are stored with the configuration."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_securityhub_insight"
    ENTITY_NAME: ClassVar[str] = "Security Hub Insight"
    ENTITY_DESCRIPTION: ClassVar[str] = "A Security Hub insight."
    ENTITY_ICON: ClassVar[str] = "aws-security-hub"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The insight's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("insight_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "insight_arn": {"type": "string"},
        "group_by_attribute": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "insight_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "group_by_attribute": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    insight_arn = models.CharField(max_length=512, blank=True, default="")
    # The finding attribute the insight groups by. NULL = not observed.
    group_by_attribute = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_securityhub_insight"

    def get_name(self) -> str:
        return self.name or self.insight_arn

    def __str__(self) -> str:
        return self.get_name()
