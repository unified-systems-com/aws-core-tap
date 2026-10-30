"""Logs Delivery Source — a CloudWatch Logs delivery source."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class LogsDeliverySource(BaseModel):
    """A CloudWatch Logs delivery source: an AWS resource (a WAF web ACL, a Route 53 resolver query log, a Bedrock agent) that vends logs through the delivery pipeline."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_logs_delivery_source"
    ENTITY_NAME: ClassVar[str] = "Logs Delivery Source"
    ENTITY_DESCRIPTION: ClassVar[str] = "A CloudWatch Logs delivery source."
    ENTITY_ICON: ClassVar[str] = "aws-cloudwatch"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("source_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "source_arn": {"type": "string"},
        "service": {"type": ["string", "null"]},
        "log_type": {"type": ["string", "null"]},
        "resource_arns": {"type": ["array", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "source_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "service": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "log_type": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "resource_arns": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    source_arn = models.CharField(max_length=512, blank=True, default="")
    # The AWS service that vends the logs. NULL = not observed.
    service = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The kind of log. NULL = not observed.
    log_type = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The resources the source covers. NULL = not observed.
    resource_arns = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_logs_delivery_source"

    def get_name(self) -> str:
        return self.name or self.source_arn

    def __str__(self) -> str:
        return self.get_name()
