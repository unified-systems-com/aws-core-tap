"""VPC — an Amazon Virtual Private Cloud."""

from typing import Any, ClassVar

from django.db import models
from tap_grid.models import BaseModel


class Vpc(BaseModel):
    """An Amazon VPC."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_vpc"
    ENTITY_NAME: ClassVar[str] = "VPC"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon Virtual Private Cloud."
    ENTITY_ICON: ClassVar[str] = "aws-vpc"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The VPC ID (vpc-…). AWS assigns it, but does not
    # document it as unique across accounts and regions, so a clash there would surface as
    # AmbiguousIdentity from the generated search, never as a silent merge. The key moves to the ARN
    # if a collector records one.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("vpc_id",)
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "round-rectangle",
            "colors": {"fill": "#D0DECD", "border": "#5A8A4D", "label": "#192615"},
            "label": {"valign": "top", "halign": "center", "position": "outside"},
        }
    }

    # A subnet exists only inside its VPC, so retiring a VPC retires its subnets
    # (req-grid-service-delete-cascade; req-aws-core-placement). The cascade stops there: subnets
    # declare no containment, and VPC-wide resources (security groups, route tables) point at the VPC
    # with RESIDES_IN_VPC, which a cascade from the VPC cannot follow.
    # Declaring OUTBOUND_EDGES makes the VPC a constrained source: an edge type from another plugin
    # that leaves its sources undeclared can no longer start at a VPC. Edge types that list the VPC
    # (BELONGS_TO_ACCOUNT) or leave the source WILDCARD are unaffected (permission union).
    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "aws_core__aws_subnet"}], "edges": [{"type": "PARTITIONED_INTO_SUBNET__aws_core"}]},
    ]
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = ("PARTITIONED_INTO_SUBNET__aws_core",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "vpc_id": {"type": "string"},
        "cidr_block": {"type": "string"},
        "state": {"type": "string"},
        "is_default": {"type": "boolean"},
        "configuration": {"type": "object"},
        "tags": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string"}},
        "vpc_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "cidr_block": {"validation": "jsonschema", "schema": {"type": "string"}},
        "state": {"validation": "jsonschema", "schema": {"type": "string"}},
        "is_default": {"validation": "jsonschema", "schema": {"type": "boolean"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    # vpc_id is NOT required at create: a designed vpc (dcom=design) exists before AWS mints it.
    # Blank (the field default) means not observed. A collected vpc always carries it.
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    vpc_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    cidr_block = models.CharField(max_length=64, blank=True, default="")
    state = models.CharField(max_length=32, blank=True, default="")
    is_default = models.BooleanField(default=False)
    configuration = models.JSONField(default=dict, blank=True)
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: the Describe call's own Tags.
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_vpc"

    def get_name(self) -> str:
        return self.name or self.vpc_id

    def __str__(self) -> str:
        return self.get_name()
