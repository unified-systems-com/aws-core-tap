"""Subnet — an Amazon VPC subnet."""

from typing import Any, ClassVar

from django.db import models
from tap_grid.models import BaseModel


class Subnet(BaseModel):
    """An Amazon VPC subnet."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_subnet"
    ENTITY_NAME: ClassVar[str] = "Subnet"
    ENTITY_DESCRIPTION: ClassVar[str] = "A subnet within an Amazon VPC."
    ENTITY_ICON: ClassVar[str] = "aws-subnet"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The subnet ID (subnet-…). AWS assigns it, but does not
    # document it as unique across accounts and regions, so a clash there would surface as
    # AmbiguousIdentity from the generated search, never as a silent merge. The key moves to the ARN
    # if a collector records one.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("subnet_id",)
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "round-rectangle",
            "colors": {"fill": "#DAE5D3", "border": "#7BA362", "label": "#222D1B"},
            "label": {"valign": "top", "halign": "center", "position": "outside"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "subnet_id": {"type": "string"},
        "cidr_block": {"type": "string"},
        "availability_zone": {"type": "string"},
        "public": {"type": "boolean"},
        "configuration": {"type": "object"},
        "tags": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string"}},
        "subnet_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "cidr_block": {"validation": "jsonschema", "schema": {"type": "string"}},
        "availability_zone": {"validation": "jsonschema", "schema": {"type": "string"}},
        "public": {"validation": "jsonschema", "schema": {"type": "boolean"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    # subnet_id is NOT required at create: a designed subnet (dcom=design) exists before AWS mints it.
    # Blank (the field default) means not observed. A collected subnet always carries it.
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    subnet_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    cidr_block = models.CharField(max_length=64, blank=True, default="")
    availability_zone = models.CharField(max_length=64, blank=True, default="")
    public = models.BooleanField(default=False)
    configuration = models.JSONField(default=dict, blank=True)
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: the Describe call's own Tags.
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_subnet"

    def get_name(self) -> str:
        return self.name or self.subnet_id

    def __str__(self) -> str:
        return self.get_name()
