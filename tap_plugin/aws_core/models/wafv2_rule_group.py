"""WAFv2 Rule Group — an AWS WAF (WAFv2) rule group."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Wafv2RuleGroup(BaseModel):
    """An AWS WAF rule group: a reusable set of rules that web ACLs reference."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_wafv2_rule_group"
    ENTITY_NAME: ClassVar[str] = "WAFv2 Rule Group"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS WAF (WAFv2) rule group."
    ENTITY_ICON: ClassVar[str] = "aws-security-hub"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The rule group's ARN: a name is unique only within an account, region and scope.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("rule_group_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "rule_group_arn": {"type": "string"},
        "scope": {"type": ["string", "null"]},
        "rule_count": {"type": ["integer", "null"]},
        "capacity": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "rule_group_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "scope": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "rule_count": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "capacity": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    rule_group_arn = models.CharField(max_length=512, blank=True, default="")
    # REGIONAL, or CLOUDFRONT for a global (CloudFront) object read through us-east-1. NULL = not observed.
    scope = models.CharField(max_length=512, blank=True, null=True, default=None)
    # How many rules the group holds. NULL = not observed.
    rule_count = models.IntegerField(null=True, blank=True, default=None)
    # The group's capacity units. NULL = not observed.
    capacity = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_wafv2_rule_group"

    def get_name(self) -> str:
        return self.name or self.rule_group_arn

    def __str__(self) -> str:
        return self.get_name()
