"""CloudWatch Alarm — an Amazon CloudWatch metric alarm."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CloudwatchAlarm(BaseModel):
    """An Amazon CloudWatch metric alarm: a threshold on a metric and the actions to take when it is crossed. The detective controls that compliance frameworks ask for (root login, unauthorized API calls, security group changes) are alarms on log metric filters."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cloudwatch_alarm"
    ENTITY_NAME: ClassVar[str] = "CloudWatch Alarm"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon CloudWatch metric alarm."
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
        "metric_name": {"type": ["string", "null"]},
        "namespace": {"type": ["string", "null"]},
        "comparison_operator": {"type": ["string", "null"]},
        "threshold": {"type": ["number", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "alarm_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "state_value": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "actions_enabled": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "metric_name": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "namespace": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "comparison_operator": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "threshold": {"validation": "jsonschema", "schema": {"type": ["number", "null"]}},
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
    # The metric alarmed on (empty for a metric-math alarm). NULL = not observed.
    metric_name = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The metric's namespace. NULL = not observed.
    namespace = models.CharField(max_length=512, blank=True, null=True, default=None)
    # How the metric is compared with the threshold. NULL = not observed.
    comparison_operator = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The threshold the metric is compared with. NULL = not observed (a metric-math alarm may name it indirectly).
    threshold = models.FloatField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cloudwatch_alarm"

    def get_name(self) -> str:
        return self.name or self.alarm_arn

    def __str__(self) -> str:
        return self.get_name()
