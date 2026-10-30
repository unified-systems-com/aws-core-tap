"""CloudWatch Composite Alarm — an Amazon CloudWatch composite alarm."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CloudwatchCompositeAlarm(BaseModel):
    """An Amazon CloudWatch composite alarm: an alarm whose state is a rule over other alarms, used to cut alert noise."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cloudwatch_composite_alarm"
    ENTITY_NAME: ClassVar[str] = "CloudWatch Composite Alarm"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon CloudWatch composite alarm."
    ENTITY_ICON: ClassVar[str] = "aws-cloudwatch"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The alarm's ARN: an alarm name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("alarm_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "alarm_arn": {"type": "string"},
        "state_value": {"type": ["string", "null"]},
        "actions_enabled": {"type": ["boolean", "null"]},
        "alarm_rule": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "alarm_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "state_value": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "actions_enabled": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "alarm_rule": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    alarm_arn = models.CharField(max_length=512, blank=True, default="")
    # OK, ALARM or INSUFFICIENT_DATA. NULL = not observed.
    state_value = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Whether the alarm's actions run. NULL = not observed.
    actions_enabled = models.BooleanField(null=True, blank=True, default=None)
    # The rule over other alarms. NULL = not observed.
    alarm_rule = models.TextField(blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cloudwatch_composite_alarm"

    def get_name(self) -> str:
        return self.name or self.alarm_arn

    def __str__(self) -> str:
        return self.get_name()
