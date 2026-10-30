"""WAFv2 Web ACL — an AWS WAF (WAFv2) web ACL."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Wafv2WebAcl(BaseModel):
    """An AWS WAF web ACL: the ordered rules and default action applied to requests for the CloudFront distributions, load balancers and API stages it is associated with. The default action decides what happens to a request no rule matches."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_wafv2_web_acl"
    ENTITY_NAME: ClassVar[str] = "WAFv2 Web ACL"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS WAF (WAFv2) web ACL."
    ENTITY_ICON: ClassVar[str] = "aws-security-hub"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The web ACL's ARN: a name is unique only within an account, region and scope.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("web_acl_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "web_acl_arn": {"type": "string"},
        "scope": {"type": ["string", "null"]},
        "default_action": {"type": ["string", "null"]},
        "rule_count": {"type": ["integer", "null"]},
        "capacity": {"type": ["integer", "null"]},
        "managed_by_firewall_manager": {"type": ["boolean", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "web_acl_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "scope": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "default_action": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "rule_count": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "capacity": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "managed_by_firewall_manager": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    web_acl_arn = models.CharField(max_length=512, blank=True, default="")
    # REGIONAL, or CLOUDFRONT for a global (CloudFront) object read through us-east-1. NULL = not observed.
    scope = models.CharField(max_length=512, blank=True, null=True, default=None)
    # ALLOW or BLOCK: what happens to a request no rule matches. NULL = not observed.
    default_action = models.CharField(max_length=512, blank=True, null=True, default=None)
    # How many rules the web ACL holds. NULL = not observed.
    rule_count = models.IntegerField(null=True, blank=True, default=None)
    # The web ACL's capacity units in use. NULL = not observed.
    capacity = models.IntegerField(null=True, blank=True, default=None)
    # Whether AWS Firewall Manager manages the web ACL. NULL = not observed.
    managed_by_firewall_manager = models.BooleanField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_wafv2_web_acl"

    def get_name(self) -> str:
        return self.name or self.web_acl_arn

    def __str__(self) -> str:
        return self.get_name()
