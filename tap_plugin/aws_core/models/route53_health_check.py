"""AWS Route53 Health Check — an AWS Route53 Health Check."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Route53HealthCheck(BaseModel):
    """An AWS Route53 Health Check, listed by ListHealthChecks. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_route53_health_check"
    ENTITY_NAME: ClassVar[str] = "AWS Route53 Health Check"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Route53 Health Check."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The health check's Id: ListHealthChecks returns no ARN, and a Route 53 health check id is unique across accounts.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("route53_health_check_id",)
    ARN_RESOURCE: ClassVar[str | None] = "route53:healthcheck"

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "route53_health_check_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    route53_health_check_id = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_route53_health_check"

    def get_name(self) -> str:
        return self.name or self.route53_health_check_id

    def __str__(self) -> str:
        return self.get_name()
