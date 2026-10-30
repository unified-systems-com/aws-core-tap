"""API Gateway Client Certificate — an Amazon API Gateway client certificate."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ApigatewayClientCertificate(BaseModel):
    """An API Gateway client certificate: the certificate a stage presents to its backend so the backend can verify the caller is API Gateway. Its expiry is a fact worth watching."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_apigateway_client_certificate"
    ENTITY_NAME: ClassVar[str] = "API Gateway Client Certificate"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon API Gateway client certificate."
    ENTITY_ICON: ClassVar[str] = "aws-apigateway"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The certificate's ARN (built from its id).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("client_certificate_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "client_certificate_arn": {"type": "string"},
        "client_certificate_id": {"type": ["string", "null"]},
        "expiration": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    client_certificate_arn = models.CharField(max_length=2048, blank=True, default="")
    # AWS's certificate id. NULL = not observed.
    client_certificate_id = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # When the certificate expires (ISO 8601 UTC). NULL = not observed.
    expiration = models.CharField(max_length=2048, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_apigateway_client_certificate"

    def get_name(self) -> str:
        return self.name or self.client_certificate_arn

    def __str__(self) -> str:
        return self.get_name()
