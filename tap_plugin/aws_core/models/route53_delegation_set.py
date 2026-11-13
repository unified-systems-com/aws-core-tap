"""AWS Route53 Delegation Set — an AWS Route53 Delegation Set."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Route53DelegationSet(BaseModel):
    """An AWS Route53 Delegation Set, listed by ListReusableDelegationSets. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_route53_delegation_set"
    ENTITY_NAME: ClassVar[str] = "AWS Route53 Delegation Set"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Route53 Delegation Set."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The delegation set's Id: ListReusableDelegationSets returns no ARN, and a Route 53 delegation set id is unique across accounts.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("route53_delegation_set_id",)
    ARN_RESOURCE: ClassVar[str | None] = "route53:delegationset"

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "route53_delegation_set_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    route53_delegation_set_id = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_route53_delegation_set"

    def get_name(self) -> str:
        return self.name or self.route53_delegation_set_id

    def __str__(self) -> str:
        return self.get_name()
