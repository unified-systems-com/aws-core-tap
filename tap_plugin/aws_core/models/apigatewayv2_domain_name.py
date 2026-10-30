"""API Gateway HTTP/WebSocket Domain Name — a custom domain name of Amazon API Gateway HTTP or WebSocket APIs."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Apigatewayv2DomainName(BaseModel):
    """An API Gateway custom domain name for HTTP and WebSocket APIs, with its TLS policies, certificates and optional mutual TLS truststore."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_apigatewayv2_domain_name"
    ENTITY_NAME: ClassVar[str] = "API Gateway HTTP/WebSocket Domain Name"
    ENTITY_DESCRIPTION: ClassVar[str] = "A custom domain name of Amazon API Gateway HTTP or WebSocket APIs."
    ENTITY_ICON: ClassVar[str] = "aws-apigateway"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The domain name's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("domain_name_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "domain_name_arn": {"type": "string"},
        "security_policies": {"type": ["array", "null"]},
        "certificate_arns": {"type": ["array", "null"]},
        "mutual_tls_truststore_uri": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "domain_name_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "security_policies": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "certificate_arns": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "mutual_tls_truststore_uri": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    domain_name_arn = models.CharField(max_length=2048, blank=True, default="")
    # TLS security policies across the domain's configurations. NULL = not observed.
    security_policies = models.JSONField(null=True, blank=True, default=None)
    # ACM certificates the domain presents. NULL = not observed.
    certificate_arns = models.JSONField(null=True, blank=True, default=None)
    # The S3 truststore for mutual TLS. NULL = mutual TLS is off, or not observed.
    mutual_tls_truststore_uri = models.CharField(max_length=2048, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_apigatewayv2_domain_name"

    def get_name(self) -> str:
        return self.name or self.domain_name_arn

    def __str__(self) -> str:
        return self.get_name()
