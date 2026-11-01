"""AWS Redshift Endpoint Access — an AWS Redshift Endpoint Access."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class RedshiftEndpointAccess(BaseModel):
    """An AWS Redshift Endpoint Access, read by DescribeEndpointAccess. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_redshift_endpoint_access"
    ENTITY_NAME: ClassVar[str] = "AWS Redshift Endpoint Access"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Redshift Endpoint Access."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): the endpoint name: unique within the account and Region, and the item carries no ARN (the Service Authorization Reference for redshift defines no endpoint-access resource)
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("redshift_endpoint_access_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "redshift_endpoint_access_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    redshift_endpoint_access_id = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_redshift_endpoint_access"

    def get_name(self) -> str:
        return self.name or self.redshift_endpoint_access_id

    def __str__(self) -> str:
        return self.get_name()
