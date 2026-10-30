"""Cognito User Pool Client — an app client of an Amazon Cognito user pool."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CognitoUserPoolClient(BaseModel):
    """An app client of a Cognito user pool: an application's registration, with its OAuth flows, scopes and callback URLs. A client secret, when it has one, is never collected."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cognito_user_pool_client"
    ENTITY_NAME: ClassVar[str] = "Cognito User Pool Client"
    ENTITY_DESCRIPTION: ClassVar[str] = "An app client of an Amazon Cognito user pool."
    ENTITY_ICON: ClassVar[str] = "aws-cognito"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The user pool id and the client id together (pool:client): a client id is unique only within a pool.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("client_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "client_key": {"type": "string"},
        "user_pool_id": {"type": ["string", "null"]},
        "client_id": {"type": ["string", "null"]},
        "has_secret": {"type": ["boolean", "null"]},
        "allowed_oauth_flows": {"type": ["array", "null"]},
        "allowed_oauth_scopes": {"type": ["array", "null"]},
        "callback_urls": {"type": ["array", "null"]},
        "explicit_auth_flows": {"type": ["array", "null"]},
        "prevent_user_existence_errors": {"type": ["string", "null"]},
        "enable_token_revocation": {"type": ["boolean", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "client_key": {"validation": "jsonschema", "schema": {"type": "string"}},
        "user_pool_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "client_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "has_secret": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "allowed_oauth_flows": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "allowed_oauth_scopes": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "callback_urls": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "explicit_auth_flows": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "prevent_user_existence_errors": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "enable_token_revocation": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    client_key = models.CharField(max_length=512, blank=True, default="")
    # The user pool the client belongs to. NULL = not observed.
    user_pool_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The client id (botocore marks it sensitive). NULL = not observed.
    client_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Whether the client has a secret (the secret itself is never stored). NULL = not observed.
    has_secret = models.BooleanField(null=True, blank=True, default=None)
    # OAuth flows the client may use (code, implicit, client_credentials). NULL = not observed.
    allowed_oauth_flows = models.JSONField(null=True, blank=True, default=None)
    # OAuth scopes the client may request. NULL = not observed.
    allowed_oauth_scopes = models.JSONField(null=True, blank=True, default=None)
    # URLs tokens may be redirected to. NULL = not observed.
    callback_urls = models.JSONField(null=True, blank=True, default=None)
    # Authentication flows enabled on the client. NULL = not observed.
    explicit_auth_flows = models.JSONField(null=True, blank=True, default=None)
    # ENABLED or LEGACY: whether sign-in errors reveal that a user exists. NULL = not observed.
    prevent_user_existence_errors = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Whether tokens can be revoked. NULL = not observed.
    enable_token_revocation = models.BooleanField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cognito_user_pool_client"

    def get_name(self) -> str:
        return self.name or self.client_key

    def __str__(self) -> str:
        return self.get_name()
