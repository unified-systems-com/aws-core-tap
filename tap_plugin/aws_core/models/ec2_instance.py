"""EC2 Instance — an Amazon Elastic Compute Cloud virtual server."""

from typing import Any, ClassVar

from django.db import models
from tap_grid.models import BaseModel


class Ec2Instance(BaseModel):
    """An Amazon EC2 virtual server instance."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ec2_instance"
    ENTITY_NAME: ClassVar[str] = "EC2 Instance"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon EC2 virtual server instance."
    ENTITY_ICON: ClassVar[str] = "aws-ec2"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The instance ID (i-…). AWS assigns it, but does not
    # document it as unique across accounts and regions, so a clash there would surface as
    # AmbiguousIdentity from the generated search, never as a silent merge. The key moves to the ARN
    # if a collector records one.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("instance_id",)
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F9D7B7", "border": "#ED7100", "label": "#421F00"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "instance_id": {"type": "string"},
        "ec2_type": {"type": "string"},
        "state": {"type": "string"},
        "private_ip": {"type": ["string", "null"]},
        "public_ip": {"type": ["string", "null"]},
        "ami_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string"}},
        "instance_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "ec2_type": {"validation": "jsonschema", "schema": {"type": "string"}},
        "state": {"validation": "jsonschema", "schema": {"type": "string"}},
        "private_ip": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "public_ip": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "ami_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    # Nothing is required at create. A designed instance (dcom=design) exists before AWS mints its
    # instance_id; a collected one can be untagged, so it may have no name. Blank means not observed.
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    instance_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    ec2_type = models.CharField(max_length=64, blank=True, default="")
    state = models.CharField(max_length=32, blank=True, default="")
    private_ip = models.GenericIPAddressField(blank=True, null=True)
    public_ip = models.GenericIPAddressField(blank=True, null=True)
    ami_id = models.CharField(max_length=64, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: the Describe call's own Tags.
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ec2_instance"

    def get_name(self) -> str:
        return self.name or self.instance_id

    def __str__(self) -> str:
        return self.get_name()
