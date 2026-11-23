"""AWS Connect Queue — an AWS Connect Queue."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import NO_EVENT_TIME, NoEventTime
from tap_grid.models import BaseModel


class ConnectQueue(BaseModel):
    """An AWS Connect Queue, listed by ListQueues. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_connect_queue"
    ENTITY_NAME: ClassVar[str] = "AWS Connect Queue"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Connect Queue."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (Arn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("connect_queue_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "connect:queue"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): no typed field of this model says when
    # the thing happened in the world; EVENT_TIME_REASON says why.
    EVENT_TIME: ClassVar[NoEventTime] = NO_EVENT_TIME
    EVENT_TIME_REASON: ClassVar[str] = (
        "AWS returns no creation time in its own record (ListQueues QueueSummaryList[]); the times it does return there"
        " (LastModifiedTime) are held only inside configuration. The collector also reads ListInstances "
        "InstanceSummaryList[], whose CreatedTime is that record's, not this one's; AWS states no time for this one."
    )

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "connect_queue_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    connect_queue_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_connect_queue"

    def get_name(self) -> str:
        return self.name or self.connect_queue_arn

    def __str__(self) -> str:
        return self.get_name()
