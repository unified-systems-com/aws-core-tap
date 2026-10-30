"""Access Analyzer Archive Rule — an IAM Access Analyzer archive rule that hides matching findings."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AccessAnalyzerArchiveRule(BaseModel):
    """An IAM Access Analyzer archive rule: findings that match it are archived automatically, so a rule decides which exposure never reaches a reviewer."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_access_analyzer_archive_rule"
    ENTITY_NAME: ClassVar[str] = "Access Analyzer Archive Rule"
    ENTITY_DESCRIPTION: ClassVar[str] = "An IAM Access Analyzer archive rule that hides matching findings."
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The analyzer's ARN plus /archive-rule/ and the rule name: AWS gives a rule no ARN in its API, and the name is unique only within an analyzer.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("rule_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "rule_arn": {"type": "string"},
        "analyzer_arn": {"type": "string"},
        "rule_name": {"type": "string"},
        "filter": {"type": ["object", "null"]},
        "updated_at": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "rule_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "analyzer_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "rule_name": {"validation": "jsonschema", "schema": {"type": "string"}},
        "filter": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
        "updated_at": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    rule_arn = models.CharField(max_length=512, blank=True, default="")
    # The analyzer the rule belongs to.
    analyzer_arn = models.CharField(max_length=512, blank=True, default="")
    # The rule's name.
    rule_name = models.CharField(max_length=512, blank=True, default="")
    # The criteria a finding must match to be archived (operator-authored; may name resources and accounts). NULL = not observed.
    filter = models.JSONField(null=True, blank=True, default=None)
    # When the rule was last changed (ISO 8601 UTC). NULL = not observed.
    updated_at = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_access_analyzer_archive_rule"

    def get_name(self) -> str:
        return self.name or self.rule_arn

    def __str__(self) -> str:
        return self.get_name()
