"""Security Hub Action Target — a Security Hub custom action."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class SecurityhubActionTarget(BaseModel):
    """A Security Hub custom action: a button on a finding that sends it to EventBridge, where a rule can route it to a ticket, a chat channel or a remediation."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_securityhub_action_target"
    ENTITY_NAME: ClassVar[str] = "Security Hub Action Target"
    ENTITY_DESCRIPTION: ClassVar[str] = "A Security Hub custom action."
    ENTITY_ICON: ClassVar[str] = "aws-security-hub"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The custom action's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("action_target_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "action_target_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "action_target_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    action_target_arn = models.CharField(max_length=512, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_securityhub_action_target"

    def get_name(self) -> str:
        return self.name or self.action_target_arn

    def __str__(self) -> str:
        return self.get_name()
