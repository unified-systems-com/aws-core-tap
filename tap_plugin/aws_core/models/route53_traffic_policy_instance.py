"""AWS Route53 Traffic Policy Instance — an AWS Route53 Traffic Policy Instance."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Route53TrafficPolicyInstance(BaseModel):
    """An AWS Route53 Traffic Policy Instance, listed by ListTrafficPolicyInstances. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_route53_traffic_policy_instance"
    ENTITY_NAME: ClassVar[str] = "AWS Route53 Traffic Policy Instance"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Route53 Traffic Policy Instance."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The traffic policy instance's Id: ListTrafficPolicyInstances returns no ARN, and a Route 53 instance id is unique across accounts.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("route53_traffic_policy_instance_id",)
    ARN_RESOURCE: ClassVar[str | None] = "route53:trafficpolicyinstance"

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "route53_traffic_policy_instance_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    route53_traffic_policy_instance_id = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_route53_traffic_policy_instance"

    def get_name(self) -> str:
        return self.name or self.route53_traffic_policy_instance_id

    def __str__(self) -> str:
        return self.get_name()
