"""AWS WorkSpaces Connection Alias — an AWS WorkSpaces Connection Alias."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class WorkspacesConnectionAlias(BaseModel):
    """An AWS WorkSpaces Connection Alias, listed by DescribeConnectionAliases. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_workspaces_connection_alias"
    ENTITY_NAME: ClassVar[str] = "AWS WorkSpaces Connection Alias"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS WorkSpaces Connection Alias."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The service-assigned id (AliasId): the service generates it when the object is created and it does not change.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("workspaces_connection_alias_id",)
    ARN_RESOURCE: ClassVar[str | None] = "workspaces:connectionalias"

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "workspaces_connection_alias_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    workspaces_connection_alias_id = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_workspaces_connection_alias"

    def get_name(self) -> str:
        return self.name or self.workspaces_connection_alias_id

    def __str__(self) -> str:
        return self.get_name()
