"""API Gateway HTTP/WebSocket Stage — a stage of an Amazon API Gateway HTTP or WebSocket API."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Apigatewayv2Stage(BaseModel):
    """A stage of an API Gateway HTTP or WebSocket API: a named deployment with its logging and throttling. Stage variables can hold secrets and are never stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_apigatewayv2_stage"
    ENTITY_NAME: ClassVar[str] = "API Gateway HTTP/WebSocket Stage"
    ENTITY_DESCRIPTION: ClassVar[str] = "A stage of an Amazon API Gateway HTTP or WebSocket API."
    ENTITY_ICON: ClassVar[str] = "aws-apigateway"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The stage's ARN (the API's ARN plus /stages/<name>).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("stage_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "stage_arn": {"type": "string"},
        "stage_name": {"type": ["string", "null"]},
        "auto_deploy": {"type": ["boolean", "null"]},
        "access_log_destination_arn": {"type": ["string", "null"]},
        "client_certificate_id": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    stage_arn = models.CharField(max_length=2048, blank=True, default="")
    # The stage's name. NULL = not observed.
    stage_name = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # Whether changes deploy automatically. NULL = not observed.
    auto_deploy = models.BooleanField(null=True, blank=True, default=None)
    # Where access logs are written. NULL = access logging is off, or not observed.
    access_log_destination_arn = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # The client certificate the stage presents. NULL = none, or not observed.
    client_certificate_id = models.CharField(max_length=2048, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_apigatewayv2_stage"

    def get_name(self) -> str:
        return self.name or self.stage_arn

    def __str__(self) -> str:
        return self.get_name()
