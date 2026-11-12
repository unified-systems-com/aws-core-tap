"""AWS FSx File System — an AWS FSx File System."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class FsxFileSystem(BaseModel):
    """An AWS FSx File System, listed by DescribeFileSystems. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_fsx_file_system"
    ENTITY_NAME: ClassVar[str] = "AWS FSx File System"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS FSx File System."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (ResourceARN): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("fsx_file_system_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "fsx:file-system"

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "fsx_file_system_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    fsx_file_system_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_fsx_file_system"

    def get_name(self) -> str:
        return self.name or self.fsx_file_system_arn

    def __str__(self) -> str:
        return self.get_name()
