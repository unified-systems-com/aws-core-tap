"""API Gateway VPC Link — an Amazon API Gateway REST VPC link."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ApigatewayVpcLink(BaseModel):
    """An API Gateway VPC link: the private path from a REST API to a Network Load Balancer in a VPC."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_apigateway_vpc_link"
    ENTITY_NAME: ClassVar[str] = "API Gateway VPC Link"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon API Gateway REST VPC link."
    ENTITY_ICON: ClassVar[str] = "aws-apigateway"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The link's ARN (built from the link id).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("vpc_link_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "vpc_link_arn": {"type": "string"},
        "status": {"type": ["string", "null"]},
        "target_arns": {"type": ["array", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    vpc_link_arn = models.CharField(max_length=2048, blank=True, default="")
    # AVAILABLE, PENDING, DELETING or FAILED. NULL = not observed.
    status = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # The Network Load Balancer ARNs the link targets. NULL = not observed.
    target_arns = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_apigateway_vpc_link"

    def get_name(self) -> str:
        return self.name or self.vpc_link_arn

    def __str__(self) -> str:
        return self.get_name()
