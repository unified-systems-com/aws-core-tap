"""AWS IoT Stream — an AWS IoT Stream."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class IotStream(BaseModel):
    """An AWS IoT Stream, listed by ListStreams. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iot_stream"
    ENTITY_NAME: ClassVar[str] = "AWS IoT Stream"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS IoT Stream."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (streamArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("iot_stream_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "iot_stream_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    iot_stream_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iot_stream"

    def get_name(self) -> str:
        return self.name or self.iot_stream_arn

    def __str__(self) -> str:
        return self.get_name()
