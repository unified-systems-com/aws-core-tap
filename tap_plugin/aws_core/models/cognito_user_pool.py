"""Cognito User Pool — an Amazon Cognito user pool."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CognitoUserPool(BaseModel):
    """An Amazon Cognito user pool."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cognito_user_pool"
    ENTITY_NAME: ClassVar[str] = "Cognito User Pool"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An Amazon Cognito user pool — a managed user directory and OIDC identity "
        "provider; the identity boundary that JWT authorizers validate against."
    )
    ENTITY_ICON: ClassVar[str] = "aws-cognito"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The user pool ID, the boto3 collector's identity for it
    # (region-prefixed, for example us-gov-west-1_Ab12).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("pool_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "pool_id": {"type": "string"},
        "pool_arn": {"type": "string"},
        "domain": {"type": "string"},
        "mfa_configuration": {"type": "string"},
        "tags": {"type": ["object", "null"]},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "pool_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "pool_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "domain": {"validation": "jsonschema", "schema": {"type": "string"}},
        "mfa_configuration": {"validation": "jsonschema", "schema": {"type": "string"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    pool_id = models.CharField(max_length=128, blank=True, default="")
    pool_arn = models.CharField(max_length=512, blank=True, default="")
    domain = models.CharField(max_length=255, blank=True, default="")
    mfa_configuration = models.CharField(max_length=32, blank=True, default="")
    tags = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cognito_user_pool"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
