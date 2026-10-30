"""NAT Gateway — an Amazon VPC NAT gateway."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class NatGateway(BaseModel):
    """An Amazon VPC NAT gateway."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_nat_gateway"
    ENTITY_NAME: ClassVar[str] = "NAT Gateway"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon VPC NAT gateway for outbound internet access."
    ENTITY_ICON: ClassVar[str] = "aws-nat-gateway"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The NAT gateway ID (nat-…). AWS assigns it, but does not
    # document it as unique across accounts and regions, so a clash there would surface as
    # AmbiguousIdentity from the generated search, never as a silent merge. The key moves to the ARN
    # if a collector records one.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("nat_gateway_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "nat_gateway_id": {"type": "string"},
        "state": {"type": "string"},
        "connectivity_type": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string"}},
        "nat_gateway_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "state": {"validation": "jsonschema", "schema": {"type": "string"}},
        "connectivity_type": {"validation": "jsonschema", "schema": {"type": "string"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["nat_gateway_id"]

    name = models.CharField(max_length=255, blank=True, default="")
    nat_gateway_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    state = models.CharField(max_length=32, blank=True, default="")
    connectivity_type = models.CharField(max_length=32, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_nat_gateway"

    def get_name(self) -> str:
        return self.name or self.nat_gateway_id

    def __str__(self) -> str:
        return self.get_name()
