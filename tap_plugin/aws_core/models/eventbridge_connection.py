"""EventBridge Connection — an Amazon EventBridge connection."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class EventbridgeConnection(BaseModel):
    """An Amazon EventBridge connection: stored credentials (API key, basic auth or OAuth) that API destinations call an external endpoint with. The credentials are never collected."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_eventbridge_connection"
    ENTITY_NAME: ClassVar[str] = "EventBridge Connection"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon EventBridge connection."
    ENTITY_ICON: ClassVar[str] = "aws-eventbridge"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The connection's ARN: a name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("connection_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "connection_arn": {"type": "string"},
        "authorization_type": {"type": ["string", "null"]},
        "connection_state": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "connection_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "authorization_type": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "connection_state": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    connection_arn = models.CharField(max_length=512, blank=True, default="")
    # API_KEY, BASIC or OAUTH_CLIENT_CREDENTIALS. NULL = not observed.
    authorization_type = models.CharField(max_length=512, blank=True, null=True, default=None)
    # AWS's connection state (AUTHORIZED, DEAUTHORIZED, ...). NULL = not observed.
    connection_state = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_eventbridge_connection"

    def get_name(self) -> str:
        return self.name or self.connection_arn

    def __str__(self) -> str:
        return self.get_name()
