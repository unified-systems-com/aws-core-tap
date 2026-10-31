"""AWS CertificateManager Acme External Account Binding — an AWS CertificateManager Acme External Account Binding."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CertificatemanagerAcmeExternalAccountBinding(BaseModel):
    """An AWS CertificateManager Acme External Account Binding, listed by ListAcmeExternalAccountBindings. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_certificatemanager_acme_external_account_binding"
    ENTITY_NAME: ClassVar[str] = "AWS CertificateManager Acme External Account Binding"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS CertificateManager Acme External Account Binding."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (AcmeExternalAccountBindingArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("certificatemanager_acme_external_account_binding_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "certificatemanager_acme_external_account_binding_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    certificatemanager_acme_external_account_binding_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_certificatemanager_acme_external_account_binding"

    def get_name(self) -> str:
        return self.name or self.certificatemanager_acme_external_account_binding_arn

    def __str__(self) -> str:
        return self.get_name()
