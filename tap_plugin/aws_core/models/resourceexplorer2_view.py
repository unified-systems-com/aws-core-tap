"""AWS ResourceExplorer2 View — an AWS ResourceExplorer2 View."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Resourceexplorer2View(BaseModel):
    """An AWS ResourceExplorer2 View, read by GetView. Only its identity, name and tags are collected; the rest of the response is not stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_resourceexplorer2_view"
    ENTITY_NAME: ClassVar[str] = "AWS ResourceExplorer2 View"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS ResourceExplorer2 View."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The view's ARN (ViewArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("resourceexplorer2_view_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "resource-explorer-2:view"

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "resourceexplorer2_view_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    resourceexplorer2_view_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_resourceexplorer2_view"

    def get_name(self) -> str:
        return self.name or self.resourceexplorer2_view_arn

    def __str__(self) -> str:
        return self.get_name()
