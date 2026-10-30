"""CloudTrail Channel — a CloudTrail Lake channel that ingests events from outside AWS."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CloudtrailChannel(BaseModel):
    """A CloudTrail Lake channel: the intake that brings events from a partner or from your own sources into an event data store."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cloudtrail_channel"
    ENTITY_NAME: ClassVar[str] = "CloudTrail Channel"
    ENTITY_DESCRIPTION: ClassVar[str] = "A CloudTrail Lake channel that ingests events from outside AWS."
    ENTITY_ICON: ClassVar[str] = "aws-cloudtrail"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The channel's ARN: a name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("channel_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "channel_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "channel_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    channel_arn = models.CharField(max_length=512, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cloudtrail_channel"

    def get_name(self) -> str:
        return self.name or self.channel_arn

    def __str__(self) -> str:
        return self.get_name()
