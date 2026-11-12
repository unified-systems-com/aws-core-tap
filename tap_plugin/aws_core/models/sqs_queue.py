"""SQS Queue — an Amazon Simple Queue Service queue."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class SqsQueue(BaseModel):
    """An Amazon SQS queue."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_sqs_queue"
    ENTITY_NAME: ClassVar[str] = "SQS Queue"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An Amazon SQS queue — an asynchronous message buffer (work queues, "
        "dead-letter queues) between producers and consumers."
    )
    ENTITY_ICON: ClassVar[str] = "aws-sqs"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The queue's ARN, the boto3 collector's identity for it.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("queue_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "sqs:queue"

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "queue_arn": {"type": "string"},
        "queue_url": {"type": ["string", "null"]},
        "visibility_timeout": {"type": ["string", "null"]},
        "message_retention_period": {"type": ["string", "null"]},
        "tags": {"type": ["object", "null"]},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "queue_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "queue_url": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "visibility_timeout": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "message_retention_period": {
            "validation": "jsonschema",
            "schema": {"type": ["string", "null"]},
        },
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    queue_arn = models.CharField(max_length=512, blank=True, default="")
    queue_url = models.CharField(max_length=512, null=True, blank=True, default=None)
    # SQS returns every attribute as a string; stored verbatim (seconds).
    visibility_timeout = models.CharField(max_length=16, null=True, blank=True, default=None)
    message_retention_period = models.CharField(max_length=16, null=True, blank=True, default=None)
    tags = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_sqs_queue"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
