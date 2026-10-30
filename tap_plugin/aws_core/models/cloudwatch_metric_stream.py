"""CloudWatch Metric Stream — an Amazon CloudWatch metric stream."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CloudwatchMetricStream(BaseModel):
    """An Amazon CloudWatch metric stream: a continuous export of metrics to a Kinesis Data Firehose delivery stream, often in another account or a third-party tool."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cloudwatch_metric_stream"
    ENTITY_NAME: ClassVar[str] = "CloudWatch Metric Stream"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon CloudWatch metric stream."
    ENTITY_ICON: ClassVar[str] = "aws-cloudwatch"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The stream's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("stream_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "stream_arn": {"type": "string"},
        "firehose_arn": {"type": ["string", "null"]},
        "state": {"type": ["string", "null"]},
        "output_format": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "stream_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "firehose_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "state": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "output_format": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    stream_arn = models.CharField(max_length=512, blank=True, default="")
    # The Firehose delivery stream the metrics go to. NULL = not observed.
    firehose_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # running or stopped. NULL = not observed.
    state = models.CharField(max_length=512, blank=True, null=True, default=None)
    # json, opentelemetry0.7 or opentelemetry1.0. NULL = not observed.
    output_format = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cloudwatch_metric_stream"

    def get_name(self) -> str:
        return self.name or self.stream_arn

    def __str__(self) -> str:
        return self.get_name()
