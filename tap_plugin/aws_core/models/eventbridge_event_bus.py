"""EventBridge Event Bus — an Amazon EventBridge event bus."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class EventbridgeEventBus(BaseModel):
    """An Amazon EventBridge event bus: where events are delivered and matched against rules. A bus policy that allows other accounts to put events makes the bus a cross-account entry point."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_eventbridge_event_bus"
    ENTITY_NAME: ClassVar[str] = "EventBridge Event Bus"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon EventBridge event bus."
    ENTITY_ICON: ClassVar[str] = "aws-eventbridge"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The bus's ARN: a bus name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("bus_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "bus_arn": {"type": "string"},
        "managed_by": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "bus_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "managed_by": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    bus_arn = models.CharField(max_length=512, blank=True, default="")
    # The AWS service that manages the bus, if one does. NULL = not observed.
    managed_by = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_eventbridge_event_bus"

    def get_name(self) -> str:
        return self.name or self.bus_arn

    def __str__(self) -> str:
        return self.get_name()
