"""Logs Delivery Destination — a CloudWatch Logs delivery destination."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class LogsDeliveryDestination(BaseModel):
    """A CloudWatch Logs delivery destination: where vended logs are written (a log group, an S3 bucket or a Firehose stream)."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_logs_delivery_destination"
    ENTITY_NAME: ClassVar[str] = "Logs Delivery Destination"
    ENTITY_DESCRIPTION: ClassVar[str] = "A CloudWatch Logs delivery destination."
    ENTITY_ICON: ClassVar[str] = "aws-cloudwatch"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("destination_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "destination_arn": {"type": "string"},
        "destination_type": {"type": ["string", "null"]},
        "output_format": {"type": ["string", "null"]},
        "destination_resource_arn": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "destination_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "destination_type": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "output_format": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "destination_resource_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    destination_arn = models.CharField(max_length=512, blank=True, default="")
    # CWL, S3 or FH. NULL = not observed.
    destination_type = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The log output format. NULL = not observed.
    output_format = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The log group, bucket or stream the logs are written to. NULL = not observed.
    destination_resource_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_logs_delivery_destination"

    def get_name(self) -> str:
        return self.name or self.destination_arn

    def __str__(self) -> str:
        return self.get_name()
