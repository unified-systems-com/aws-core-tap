"""API Gateway HTTP/WebSocket Authorizer — an authorizer of an Amazon API Gateway HTTP or WebSocket API."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Apigatewayv2Authorizer(BaseModel):
    """An authorizer of an API Gateway HTTP or WebSocket API: a JWT issuer or a Lambda function that decides whether a caller may invoke a route."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_apigatewayv2_authorizer"
    ENTITY_NAME: ClassVar[str] = "API Gateway HTTP/WebSocket Authorizer"
    ENTITY_DESCRIPTION: ClassVar[str] = "An authorizer of an Amazon API Gateway HTTP or WebSocket API."
    ENTITY_ICON: ClassVar[str] = "aws-apigateway"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The authorizer's ARN (the API's ARN plus /authorizers/<id>).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("authorizer_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "authorizer_arn": {"type": "string"},
        "authorizer_type": {"type": ["string", "null"]},
        "identity_source": {"type": ["array", "null"]},
        "jwt_issuer": {"type": ["string", "null"]},
        "result_ttl_seconds": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    authorizer_arn = models.CharField(max_length=2048, blank=True, default="")
    # JWT or REQUEST. NULL = not observed.
    authorizer_type = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # Where the caller's identity is read from. NULL = not observed.
    identity_source = models.JSONField(null=True, blank=True, default=None)
    # The issuer a JWT authorizer trusts. NULL = not a JWT authorizer, or not observed.
    jwt_issuer = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # How long a decision is cached. NULL = not set, or not observed.
    result_ttl_seconds = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_apigatewayv2_authorizer"

    def get_name(self) -> str:
        return self.name or self.authorizer_arn

    def __str__(self) -> str:
        return self.get_name()
