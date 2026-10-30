"""API Gateway Domain Name — a custom domain name of Amazon API Gateway REST, HTTP or WebSocket APIs."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ApigatewayDomainName(BaseModel):
    """An API Gateway custom domain name: the hostname APIs are served on, with its TLS policies, certificates and optional mutual TLS truststore."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_apigateway_domain_name"
    ENTITY_NAME: ClassVar[str] = "API Gateway Domain Name"
    ENTITY_DESCRIPTION: ClassVar[str] = "A custom domain name of Amazon API Gateway REST, HTTP or WebSocket APIs."
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
        "api_kind": {"type": ["string", "null"]},
        "security_policies": {"type": ["array", "null"]},
        "endpoint_types": {"type": ["array", "null"]},
        "certificate_arns": {"type": ["array", "null"]},
        "mutual_tls_truststore_uri": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    domain_name_arn = models.CharField(max_length=2048, blank=True, default="")
    # rest for a REST API, http for an HTTP or WebSocket API. NULL = not observed.
    api_kind = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # TLS security policies across the domain's configurations. NULL = not observed.
    security_policies = models.JSONField(null=True, blank=True, default=None)
    # EDGE, REGIONAL or PRIVATE. NULL = not observed.
    endpoint_types = models.JSONField(null=True, blank=True, default=None)
    # ACM certificates the domain presents. NULL = not observed.
    certificate_arns = models.JSONField(null=True, blank=True, default=None)
    # The S3 truststore for mutual TLS. NULL = mutual TLS is off, or not observed.
    mutual_tls_truststore_uri = models.CharField(max_length=2048, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_apigateway_domain_name"

    def get_name(self) -> str:
        return self.name or self.domain_name_arn

    def __str__(self) -> str:
        return self.get_name()
