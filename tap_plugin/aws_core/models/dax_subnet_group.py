"""AWS DAX Subnet Group — an AWS DAX Subnet Group."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class DaxSubnetGroup(BaseModel):
    """An AWS DAX Subnet Group, read by DescribeSubnetGroups. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_dax_subnet_group"
    ENTITY_NAME: ClassVar[str] = "AWS DAX Subnet Group"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS DAX Subnet Group."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): the subnet group name: unique within the account and Region, and the Service Authorization Reference for dax defines only a cache (cluster) ARN, no subnet group ARN. The key leads with <partition>:<account>:<region>: (req-aws-collector-identity-8), because these names repeat in other regions and accounts (issue 224).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("dax_subnet_group_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "dax_subnet_group_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    dax_subnet_group_id = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_dax_subnet_group"

    def get_name(self) -> str:
        return self.name or self.dax_subnet_group_id

    def __str__(self) -> str:
        return self.get_name()
