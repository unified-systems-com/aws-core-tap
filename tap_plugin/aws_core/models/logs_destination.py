"""Logs Destination — a CloudWatch Logs destination."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class LogsDestination(BaseModel):
    """A CloudWatch Logs destination: a receiver other accounts' subscription filters can send log events to, controlled by an access policy."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_logs_destination"
    ENTITY_NAME: ClassVar[str] = "Logs Destination"
    ENTITY_DESCRIPTION: ClassVar[str] = "A CloudWatch Logs destination."
    ENTITY_ICON: ClassVar[str] = "aws-cloudwatch"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The destination's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("destination_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "destination_arn": {"type": "string"},
        "target_arn": {"type": ["string", "null"]},
        "role_arn": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "destination_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "target_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "role_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    destination_arn = models.CharField(max_length=512, blank=True, default="")
    # The Kinesis stream or Firehose the destination delivers to. NULL = not observed.
    target_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The role CloudWatch Logs assumes to deliver. NULL = not observed.
    role_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_logs_destination"

    def get_name(self) -> str:
        return self.name or self.destination_arn

    def __str__(self) -> str:
        return self.get_name()
