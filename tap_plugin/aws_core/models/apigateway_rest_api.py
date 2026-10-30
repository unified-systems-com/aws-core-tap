"""API Gateway REST API — an Amazon API Gateway REST API."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ApigatewayRestApi(BaseModel):
    """An Amazon API Gateway REST API: a public or private HTTP front for backends. Its endpoint type, resource policy and execute-api endpoint setting decide who can reach it."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_apigateway_rest_api"
    ENTITY_NAME: ClassVar[str] = "API Gateway REST API"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon API Gateway REST API."
    ENTITY_ICON: ClassVar[str] = "aws-apigateway"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The API's ARN (built from the API id): an API id is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("rest_api_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "rest_api_arn": {"type": "string"},
        "rest_api_id": {"type": ["string", "null"]},
        "endpoint_types": {"type": ["array", "null"]},
        "api_key_source": {"type": ["string", "null"]},
        "disable_execute_api_endpoint": {"type": ["boolean", "null"]},
        "security_policy": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "rest_api_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "rest_api_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "endpoint_types": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "api_key_source": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "disable_execute_api_endpoint": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "security_policy": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    rest_api_arn = models.CharField(max_length=2048, blank=True, default="")
    # AWS's API id. NULL = not observed.
    rest_api_id = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # EDGE, REGIONAL or PRIVATE. NULL = not observed.
    endpoint_types = models.JSONField(null=True, blank=True, default=None)
    # HEADER or AUTHORIZER. NULL = not observed.
    api_key_source = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # Whether the default execute-api endpoint is disabled. NULL = not observed.
    disable_execute_api_endpoint = models.BooleanField(null=True, blank=True, default=None)
    # The TLS security policy. NULL = not observed.
    security_policy = models.CharField(max_length=2048, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_apigateway_rest_api"

    def get_name(self) -> str:
        return self.name or self.rest_api_arn

    def __str__(self) -> str:
        return self.get_name()
