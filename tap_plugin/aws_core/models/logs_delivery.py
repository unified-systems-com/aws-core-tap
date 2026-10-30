"""Logs Delivery — a CloudWatch Logs delivery."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class LogsDelivery(BaseModel):
    """A CloudWatch Logs delivery: a link between a delivery source and a delivery destination."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_logs_delivery"
    ENTITY_NAME: ClassVar[str] = "Logs Delivery"
    ENTITY_DESCRIPTION: ClassVar[str] = "A CloudWatch Logs delivery."
    ENTITY_ICON: ClassVar[str] = "aws-cloudwatch"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("delivery_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "delivery_arn": {"type": "string"},
        "delivery_id": {"type": ["string", "null"]},
        "source_name": {"type": ["string", "null"]},
        "destination_arn": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "delivery_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "delivery_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "source_name": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "destination_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    delivery_arn = models.CharField(max_length=512, blank=True, default="")
    # AWS's delivery id. NULL = not observed.
    delivery_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The delivery source. NULL = not observed.
    source_name = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The delivery destination. NULL = not observed.
    destination_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_logs_delivery"

    def get_name(self) -> str:
        return self.name or self.delivery_arn

    def __str__(self) -> str:
        return self.get_name()
