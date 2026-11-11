"""AWS AppStream Entitlement — an AWS AppStream Entitlement."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AppstreamEntitlement(BaseModel):
    """An AWS AppStream Entitlement, read by DescribeEntitlements. Only its identity, name and tags are collected; the rest of the response is not stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_appstream_entitlement"
    ENTITY_NAME: ClassVar[str] = "AWS AppStream Entitlement"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS AppStream Entitlement."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The account, the region, the stack name and the entitlement name (StackName and Name, the CloudFormation primary identifier): AWS gives it no ARN, and a bare name repeats across accounts and regions, so the key is the account, the region and both names. The key leads with <partition>:<account>:<region>: (req-aws-collector-identity-8), because these names repeat in other regions and accounts (issue 224).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("appstream_entitlement_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "appstream_entitlement_key": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    appstream_entitlement_key = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_appstream_entitlement"

    def get_name(self) -> str:
        return self.name or self.appstream_entitlement_key

    def __str__(self) -> str:
        return self.get_name()
