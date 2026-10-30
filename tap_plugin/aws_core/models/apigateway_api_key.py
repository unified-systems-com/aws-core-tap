"""API Gateway API Key — an Amazon API Gateway API key."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ApigatewayApiKey(BaseModel):
    """An API Gateway API key: a token callers send to identify themselves to a usage plan. The key value is never requested or stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_apigateway_api_key"
    ENTITY_NAME: ClassVar[str] = "API Gateway API Key"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon API Gateway API key."
    ENTITY_ICON: ClassVar[str] = "aws-apigateway"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The key's ARN (built from the key id).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("api_key_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "api_key_arn": {"type": "string"},
        "enabled": {"type": ["boolean", "null"]},
        "customer_id": {"type": ["string", "null"]},
        "stage_keys": {"type": ["array", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "api_key_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "enabled": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "customer_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "stage_keys": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    api_key_arn = models.CharField(max_length=2048, blank=True, default="")
    # Whether the key is enabled. NULL = not observed.
    enabled = models.BooleanField(null=True, blank=True, default=None)
    # The AWS Marketplace customer id, if any. NULL = none, or not observed.
    customer_id = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # The API stages the key is attached to. NULL = not observed.
    stage_keys = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_apigateway_api_key"

    def get_name(self) -> str:
        return self.name or self.api_key_arn

    def __str__(self) -> str:
        return self.get_name()
