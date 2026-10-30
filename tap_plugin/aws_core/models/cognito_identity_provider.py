"""Cognito Identity Provider — a federated identity provider of an Amazon Cognito user pool."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CognitoIdentityProvider(BaseModel):
    """A Cognito user pool identity provider: a SAML, OIDC or social provider users may sign in with. Its details hold the OAuth client secret, which is never collected."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cognito_identity_provider"
    ENTITY_NAME: ClassVar[str] = "Cognito Identity Provider"
    ENTITY_DESCRIPTION: ClassVar[str] = "A federated identity provider of an Amazon Cognito user pool."
    ENTITY_ICON: ClassVar[str] = "aws-cognito"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The user pool id and the provider name together (pool:provider): a provider name is unique only within a pool.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("provider_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "provider_key": {"type": "string"},
        "user_pool_id": {"type": ["string", "null"]},
        "provider_name": {"type": ["string", "null"]},
        "provider_type": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "provider_key": {"validation": "jsonschema", "schema": {"type": "string"}},
        "user_pool_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "provider_name": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "provider_type": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    provider_key = models.CharField(max_length=512, blank=True, default="")
    # The user pool the provider belongs to. NULL = not observed.
    user_pool_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The provider's name. NULL = not observed.
    provider_name = models.CharField(max_length=512, blank=True, null=True, default=None)
    # SAML, OIDC, Facebook, Google, ... NULL = not observed.
    provider_type = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cognito_identity_provider"

    def get_name(self) -> str:
        return self.name or self.provider_key

    def __str__(self) -> str:
        return self.get_name()
