"""Network Firewall — an AWS Network Firewall."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class NetworkFirewall(BaseModel):
    """An AWS Network Firewall."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_network_firewall"
    ENTITY_NAME: ClassVar[str] = "Network Firewall"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Network Firewall."
    ENTITY_ICON: ClassVar[str] = "aws-network-firewall"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The firewall's ARN: a firewall name is unique only
    # within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("firewall_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "firewall_arn": {"type": "string"},
        "status": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "firewall_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "status": {"validation": "jsonschema", "schema": {"type": "string"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    firewall_arn = models.CharField(max_length=512, blank=True, default="")
    status = models.CharField(max_length=64, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_network_firewall"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
