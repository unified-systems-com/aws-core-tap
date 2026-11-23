"""AWS MSK Channel — an AWS MSK Channel."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class MskChannel(BaseModel):
    """An AWS MSK Channel, listed by ListChannels. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_msk_channel"
    ENTITY_NAME: ClassVar[str] = "AWS MSK Channel"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS MSK Channel."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (ChannelArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("msk_channel_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "kafka:channel"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): when AWS created it (ListChannels
    # Channels[].CreationTime, a botocore timestamp), read from configuration['CreationTime'], where the collector
    # stores it as AWS sent it. AWS states no end for it.
    EVENT_TIME: ClassVar[Interval] = Interval(start="configuration", kind="created", member="CreationTime")

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "msk_channel_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    msk_channel_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_msk_channel"

    def get_name(self) -> str:
        return self.name or self.msk_channel_arn

    def __str__(self) -> str:
        return self.get_name()
