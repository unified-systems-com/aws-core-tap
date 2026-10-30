"""Cognito User Pool Resource Server — an OAuth resource server of an Amazon Cognito user pool."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CognitoUserPoolResourceServer(BaseModel):
    """A Cognito user pool resource server: an API whose custom OAuth scopes the pool can grant to app clients."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cognito_user_pool_resource_server"
    ENTITY_NAME: ClassVar[str] = "Cognito User Pool Resource Server"
    ENTITY_DESCRIPTION: ClassVar[str] = "An OAuth resource server of an Amazon Cognito user pool."
    ENTITY_ICON: ClassVar[str] = "aws-cognito"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The user pool id and the server identifier together (pool:identifier): an identifier is unique only within a pool.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("server_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "server_key": {"type": "string"},
        "user_pool_id": {"type": ["string", "null"]},
        "identifier": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "server_key": {"validation": "jsonschema", "schema": {"type": "string"}},
        "user_pool_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "identifier": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    server_key = models.CharField(max_length=512, blank=True, default="")
    # The user pool the server belongs to. NULL = not observed.
    user_pool_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The server's identifier (usually a URL). NULL = not observed.
    identifier = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cognito_user_pool_resource_server"

    def get_name(self) -> str:
        return self.name or self.server_key

    def __str__(self) -> str:
        return self.get_name()
