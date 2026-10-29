"""IAM Server Certificate — a server certificate stored in AWS IAM."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class IamServerCertificate(BaseModel):
    """An AWS IAM server certificate: an SSL/TLS certificate uploaded to IAM, mostly for legacy load balancers and CloudFront.

    Only the metadata is typed. The certificate body, chain and private key are never fields."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_server_certificate"
    ENTITY_NAME: ClassVar[str] = "IAM Server Certificate"
    ENTITY_DESCRIPTION: ClassVar[str] = "A server certificate stored in AWS IAM."
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The certificate's ARN: a name is unique only within an account.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("certificate_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "certificate_arn": {"type": "string"},
        "path": {"type": "string"},
        "certificate_id": {"type": ["string", "null"]},
        "expiration": {"type": ["string", "null"]},
        "upload_date": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "certificate_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "path": {"validation": "jsonschema", "schema": {"type": "string"}},
        "certificate_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "expiration": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "upload_date": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    certificate_arn = models.CharField(max_length=512, blank=True, default="")
    path = models.CharField(max_length=512, blank=True, default="/")
    # AWS's immutable certificate id (ASCA...); NULL = not observed.
    certificate_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # ISO 8601 UTC time the certificate expires; NULL = not observed.
    expiration = models.CharField(max_length=512, blank=True, null=True, default=None)
    # ISO 8601 UTC time the certificate was uploaded; NULL = not observed.
    upload_date = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iam_server_certificate"

    def get_name(self) -> str:
        return self.name or self.certificate_arn

    def __str__(self) -> str:
        return self.get_name()
