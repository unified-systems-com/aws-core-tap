"""Logs Subscription Filter — a CloudWatch Logs subscription filter."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class LogsSubscriptionFilter(BaseModel):
    """A CloudWatch Logs subscription filter: it streams a log group's events to a Kinesis stream, a Lambda function or another account's destination, which is a path for log data to leave the account."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_logs_subscription_filter"
    ENTITY_NAME: ClassVar[str] = "Logs Subscription Filter"
    ENTITY_DESCRIPTION: ClassVar[str] = "A CloudWatch Logs subscription filter."
    ENTITY_ICON: ClassVar[str] = "aws-cloudwatch"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The log group name and the filter name together (group:filter): a filter name is unique only within a log group.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("filter_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "filter_key": {"type": "string"},
        "log_group_name": {"type": ["string", "null"]},
        "destination_arn": {"type": ["string", "null"]},
        "role_arn": {"type": ["string", "null"]},
        "distribution": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "filter_key": {"validation": "jsonschema", "schema": {"type": "string"}},
        "log_group_name": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "destination_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "role_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "distribution": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    filter_key = models.CharField(max_length=512, blank=True, default="")
    # The log group the filter reads. NULL = not observed.
    log_group_name = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Where events are streamed to. NULL = not observed.
    destination_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The role CloudWatch Logs assumes to deliver. NULL = none, or not observed.
    role_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Random or ByLogStream. NULL = not observed.
    distribution = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_logs_subscription_filter"

    def get_name(self) -> str:
        return self.name or self.filter_key

    def __str__(self) -> str:
        return self.get_name()
