"""SNS Topic — an Amazon SNS topic."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class SnsTopic(BaseModel):
    """An Amazon SNS topic: a publish/subscribe channel. Its access policy decides who may publish and subscribe, and its key decides whether messages are encrypted at rest."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_sns_topic"
    ENTITY_NAME: ClassVar[str] = "SNS Topic"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon SNS topic."
    ENTITY_ICON: ClassVar[str] = "aws-sqs"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The topic's ARN: a topic name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("topic_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "topic_arn": {"type": "string"},
        "kms_master_key_id": {"type": ["string", "null"]},
        "fifo_topic": {"type": ["boolean", "null"]},
        "subscriptions_confirmed": {"type": ["integer", "null"]},
        "subscriptions_pending": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "topic_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "kms_master_key_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "fifo_topic": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "subscriptions_confirmed": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "subscriptions_pending": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    topic_arn = models.CharField(max_length=512, blank=True, default="")
    # The KMS key (id, ARN or alias) that encrypts messages at rest. NULL = no key, or not observed.
    kms_master_key_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Whether the topic is FIFO. NULL = not observed.
    fifo_topic = models.BooleanField(null=True, blank=True, default=None)
    # Confirmed subscriptions. NULL = not observed.
    subscriptions_confirmed = models.IntegerField(null=True, blank=True, default=None)
    # Subscriptions awaiting confirmation. NULL = not observed.
    subscriptions_pending = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_sns_topic"

    def get_name(self) -> str:
        return self.name or self.topic_arn

    def __str__(self) -> str:
        return self.get_name()
