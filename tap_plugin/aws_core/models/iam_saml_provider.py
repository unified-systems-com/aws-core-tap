"""IAM SAML Provider — a SAML identity provider registered in AWS IAM."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class IamSamlProvider(BaseModel):
    """An AWS IAM SAML 2.0 identity provider.

    Registers an external SAML IdP as a trusted federated provider; roles can then trust it through
    ``sts:AssumeRoleWithSAML``. The metadata document is not a typed field."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_saml_provider"
    ENTITY_NAME: ClassVar[str] = "IAM SAML Provider"
    ENTITY_DESCRIPTION: ClassVar[str] = "A SAML identity provider registered in AWS IAM."
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The provider's ARN, the collector's identity for it.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("provider_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "provider_arn": {"type": "string"},
        "valid_until": {"type": ["string", "null"]},
        "created_at": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "provider_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "valid_until": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "created_at": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    provider_arn = models.CharField(max_length=512, blank=True, default="")
    # ISO 8601 UTC time the provider's metadata expires; NULL = not observed.
    valid_until = models.CharField(max_length=512, blank=True, null=True, default=None)
    # ISO 8601 UTC time the provider was created; NULL = not observed.
    created_at = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iam_saml_provider"

    def get_name(self) -> str:
        return self.name or self.provider_arn

    def __str__(self) -> str:
        return self.get_name()
