"""Security Hub Automation Rule — a Security Hub automation rule."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class SecurityhubAutomationRule(BaseModel):
    """A Security Hub automation rule: criteria and actions that update or suppress findings as they arrive. A terminal rule that suppresses findings decides what never reaches a reviewer."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_securityhub_automation_rule"
    ENTITY_NAME: ClassVar[str] = "Security Hub Automation Rule"
    ENTITY_DESCRIPTION: ClassVar[str] = "A Security Hub automation rule."
    ENTITY_ICON: ClassVar[str] = "aws-security-hub"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The rule's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("rule_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "rule_arn": {"type": "string"},
        "rule_status": {"type": ["string", "null"]},
        "rule_order": {"type": ["integer", "null"]},
        "is_terminal": {"type": ["boolean", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "rule_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "rule_status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "rule_order": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "is_terminal": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    rule_arn = models.CharField(max_length=512, blank=True, default="")
    # ENABLED or DISABLED. NULL = not observed.
    rule_status = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The rule's order among automation rules. NULL = not observed.
    rule_order = models.IntegerField(null=True, blank=True, default=None)
    # Whether no later rule runs after this one matches. NULL = not observed.
    is_terminal = models.BooleanField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_securityhub_automation_rule"

    def get_name(self) -> str:
        return self.name or self.rule_arn

    def __str__(self) -> str:
        return self.get_name()
