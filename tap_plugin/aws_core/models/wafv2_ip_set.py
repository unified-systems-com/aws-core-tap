"""WAFv2 IP Set — an AWS WAF (WAFv2) IP set."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Wafv2IpSet(BaseModel):
    """An AWS WAF IP set: a list of addresses or ranges that rules allow or block."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_wafv2_ip_set"
    ENTITY_NAME: ClassVar[str] = "WAFv2 IP Set"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS WAF (WAFv2) IP set."
    ENTITY_ICON: ClassVar[str] = "aws-security-hub"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The IP set's ARN: a name is unique only within an account, region and scope.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("ip_set_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "ip_set_arn": {"type": "string"},
        "scope": {"type": ["string", "null"]},
        "ip_address_version": {"type": ["string", "null"]},
        "address_count": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "ip_set_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "scope": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "ip_address_version": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "address_count": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    ip_set_arn = models.CharField(max_length=512, blank=True, default="")
    # REGIONAL, or CLOUDFRONT for a global (CloudFront) object read through us-east-1. NULL = not observed.
    scope = models.CharField(max_length=512, blank=True, null=True, default=None)
    # IPV4 or IPV6. NULL = not observed.
    ip_address_version = models.CharField(max_length=512, blank=True, null=True, default=None)
    # How many addresses or ranges the set holds. NULL = not observed.
    address_count = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_wafv2_ip_set"

    def get_name(self) -> str:
        return self.name or self.ip_set_arn

    def __str__(self) -> str:
        return self.get_name()
