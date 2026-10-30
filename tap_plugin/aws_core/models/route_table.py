"""Route Table — an Amazon VPC route table."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class RouteTable(BaseModel):
    """An Amazon VPC route table."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_route_table"
    ENTITY_NAME: ClassVar[str] = "Route Table"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon VPC route table."
    ENTITY_ICON: ClassVar[str] = "aws-route-table"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The route table ID (rtb-…). AWS assigns it, but does not
    # document it as unique across accounts and regions, so a clash there would surface as
    # AmbiguousIdentity from the generated search, never as a silent merge. The key moves to the ARN
    # if a collector records one.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("route_table_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "route_table_id": {"type": "string"},
        "is_main": {"type": "boolean"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string"}},
        "route_table_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "is_main": {"validation": "jsonschema", "schema": {"type": "boolean"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["route_table_id"]

    name = models.CharField(max_length=255, blank=True, default="")
    route_table_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    is_main = models.BooleanField(default=False)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_route_table"

    def get_name(self) -> str:
        return self.name or self.route_table_id

    def __str__(self) -> str:
        return self.get_name()
