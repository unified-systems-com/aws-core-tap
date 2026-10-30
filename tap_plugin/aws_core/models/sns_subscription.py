"""SNS Subscription — an Amazon SNS subscription."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class SnsSubscription(BaseModel):
    """An Amazon SNS subscription: one endpoint that receives a topic's messages. The endpoint (an email address, a phone number, a URL) is personal data or can carry credentials, so it is never collected; the protocol is."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_sns_subscription"
    ENTITY_NAME: ClassVar[str] = "SNS Subscription"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon SNS subscription."
    ENTITY_ICON: ClassVar[str] = "aws-sqs"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The subscription's ARN. A subscription still awaiting confirmation has none and is not collected.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("subscription_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "subscription_arn": {"type": "string"},
        "topic_arn": {"type": "string"},
        "protocol": {"type": ["string", "null"]},
        "owner": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "subscription_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "topic_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "protocol": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "owner": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    subscription_arn = models.CharField(max_length=512, blank=True, default="")
    # The topic the subscription belongs to.
    topic_arn = models.CharField(max_length=512, blank=True, default="")
    # How messages are delivered (email, sms, http, https, sqs, lambda, ...). NULL = not observed.
    protocol = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The account id that owns the subscription. NULL = not observed.
    owner = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_sns_subscription"

    def get_name(self) -> str:
        return self.name or self.subscription_arn

    def __str__(self) -> str:
        return self.get_name()
