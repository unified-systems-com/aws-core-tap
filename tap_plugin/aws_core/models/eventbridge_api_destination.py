"""EventBridge API Destination — an Amazon EventBridge API destination."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class EventbridgeApiDestination(BaseModel):
    """An Amazon EventBridge API destination: an external HTTP endpoint that rules can call, with the credentials of a connection. It is a path for event data to leave the account."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_eventbridge_api_destination"
    ENTITY_NAME: ClassVar[str] = "EventBridge API Destination"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon EventBridge API destination."
    ENTITY_ICON: ClassVar[str] = "aws-eventbridge"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The destination's ARN: a name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("destination_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "destination_arn": {"type": "string"},
        "invocation_endpoint": {"type": ["string", "null"]},
        "http_method": {"type": ["string", "null"]},
        "state": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "destination_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "invocation_endpoint": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "http_method": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "state": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    destination_arn = models.CharField(max_length=512, blank=True, default="")
    # The external URL the destination calls. NULL = not observed.
    invocation_endpoint = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The HTTP method used. NULL = not observed.
    http_method = models.CharField(max_length=512, blank=True, null=True, default=None)
    # ACTIVE or INACTIVE. NULL = not observed.
    state = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_eventbridge_api_destination"

    def get_name(self) -> str:
        return self.name or self.destination_arn

    def __str__(self) -> str:
        return self.get_name()
