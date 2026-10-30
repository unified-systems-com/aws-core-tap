"""Cognito Identity Pool — an Amazon Cognito identity pool."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CognitoIdentityPool(BaseModel):
    """An Amazon Cognito identity pool: it exchanges a sign-in (or, if allowed, no sign-in at all) for temporary AWS credentials. With unauthenticated identities allowed, anyone can obtain credentials for the pool's unauthenticated role."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cognito_identity_pool"
    ENTITY_NAME: ClassVar[str] = "Cognito Identity Pool"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon Cognito identity pool."
    ENTITY_ICON: ClassVar[str] = "aws-cognito"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The pool's id (region:uuid), unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("identity_pool_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "identity_pool_id": {"type": "string"},
        "allow_unauthenticated_identities": {"type": ["boolean", "null"]},
        "allow_classic_flow": {"type": ["boolean", "null"]},
        "developer_provider_name": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "identity_pool_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "allow_unauthenticated_identities": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "allow_classic_flow": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "developer_provider_name": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    identity_pool_id = models.CharField(max_length=512, blank=True, default="")
    # Whether callers with no sign-in may get credentials. NULL = not observed.
    allow_unauthenticated_identities = models.BooleanField(null=True, blank=True, default=None)
    # Whether the classic (basic) authentication flow is allowed. NULL = not observed.
    allow_classic_flow = models.BooleanField(null=True, blank=True, default=None)
    # The developer authenticated identity provider name, if set. NULL = none, or not observed.
    developer_provider_name = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cognito_identity_pool"

    def get_name(self) -> str:
        return self.name or self.identity_pool_id

    def __str__(self) -> str:
        return self.get_name()
