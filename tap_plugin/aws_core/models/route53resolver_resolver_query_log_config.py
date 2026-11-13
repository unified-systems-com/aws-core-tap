"""AWS Route 53 Resolver Resolver Query Log Config — an AWS Route 53 Resolver Resolver Query Log Config."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Route53resolverResolverQueryLogConfig(BaseModel):
    """An AWS Route 53 Resolver Resolver Query Log Config, listed by ListResolverQueryLogConfigs. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_route53resolver_resolver_query_log_config"
    ENTITY_NAME: ClassVar[str] = "AWS Route 53 Resolver Resolver Query Log Config"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Route 53 Resolver Resolver Query Log Config."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (Arn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("route53resolver_resolver_query_log_config_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "route53resolver:resolver-query-log-config"

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "route53resolver_resolver_query_log_config_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    route53resolver_resolver_query_log_config_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_route53resolver_resolver_query_log_config"

    def get_name(self) -> str:
        return self.name or self.route53resolver_resolver_query_log_config_arn

    def __str__(self) -> str:
        return self.get_name()
