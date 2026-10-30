"""WAFv2 Regex Pattern Set — an AWS WAF (WAFv2) regex pattern set."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Wafv2RegexPatternSet(BaseModel):
    """An AWS WAF regex pattern set: regular expressions that rules match request components against."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_wafv2_regex_pattern_set"
    ENTITY_NAME: ClassVar[str] = "WAFv2 Regex Pattern Set"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS WAF (WAFv2) regex pattern set."
    ENTITY_ICON: ClassVar[str] = "aws-security-hub"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The pattern set's ARN: a name is unique only within an account, region and scope.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("regex_pattern_set_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "regex_pattern_set_arn": {"type": "string"},
        "scope": {"type": ["string", "null"]},
        "pattern_count": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "regex_pattern_set_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "scope": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "pattern_count": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    regex_pattern_set_arn = models.CharField(max_length=512, blank=True, default="")
    # REGIONAL, or CLOUDFRONT for a global (CloudFront) object read through us-east-1. NULL = not observed.
    scope = models.CharField(max_length=512, blank=True, null=True, default=None)
    # How many patterns the set holds. NULL = not observed.
    pattern_count = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_wafv2_regex_pattern_set"

    def get_name(self) -> str:
        return self.name or self.regex_pattern_set_arn

    def __str__(self) -> str:
        return self.get_name()
