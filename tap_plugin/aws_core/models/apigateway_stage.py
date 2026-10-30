"""API Gateway Stage — a stage of an Amazon API Gateway REST, HTTP or WebSocket API."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ApigatewayStage(BaseModel):
    """A stage of an API Gateway API: a named deployment with its own logging, caching, tracing and (for REST) WAF association. REST and HTTP/WebSocket APIs are separate services; one type covers both and api_kind says which. Stage variables can hold secrets and are never stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_apigateway_stage"
    ENTITY_NAME: ClassVar[str] = "API Gateway Stage"
    ENTITY_DESCRIPTION: ClassVar[str] = "A stage of an Amazon API Gateway REST, HTTP or WebSocket API."
    ENTITY_ICON: ClassVar[str] = "aws-apigateway"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The stage's ARN (the API's ARN plus /stages/<name>): a stage name is unique only within an API.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("stage_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "stage_arn": {"type": "string"},
        "api_kind": {"type": ["string", "null"]},
        "stage_name": {"type": ["string", "null"]},
        "deployment_id": {"type": ["string", "null"]},
        "cache_cluster_enabled": {"type": ["boolean", "null"]},
        "tracing_enabled": {"type": ["boolean", "null"]},
        "auto_deploy": {"type": ["boolean", "null"]},
        "web_acl_arn": {"type": ["string", "null"]},
        "client_certificate_id": {"type": ["string", "null"]},
        "access_log_destination_arn": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    stage_arn = models.CharField(max_length=2048, blank=True, default="")
    # rest for a REST API, http for an HTTP or WebSocket API. NULL = not observed.
    api_kind = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # The stage's name. NULL = not observed.
    stage_name = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # The deployment the stage serves. NULL = not observed.
    deployment_id = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # Whether the stage has a cache cluster (REST only). NULL = not applicable, or not observed.
    cache_cluster_enabled = models.BooleanField(null=True, blank=True, default=None)
    # Whether X-Ray tracing is on (REST only). NULL = not applicable, or not observed.
    tracing_enabled = models.BooleanField(null=True, blank=True, default=None)
    # Whether changes deploy automatically (HTTP/WebSocket only). NULL = not applicable, or not observed.
    auto_deploy = models.BooleanField(null=True, blank=True, default=None)
    # The WAF web ACL protecting the stage (REST only). NULL = none, or not observed.
    web_acl_arn = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # The client certificate the stage presents to its backend. NULL = none, or not observed.
    client_certificate_id = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # Where access logs are written. NULL = access logging is off, or not observed.
    access_log_destination_arn = models.CharField(max_length=2048, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_apigateway_stage"

    def get_name(self) -> str:
        return self.name or self.stage_arn

    def __str__(self) -> str:
        return self.get_name()
