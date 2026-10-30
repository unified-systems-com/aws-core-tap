"""RDS DB Proxy — an Amazon RDS Proxy."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class RdsDbProxy(BaseModel):
    """An RDS Proxy: a connection pool in front of databases, with its own authentication (a secret per user) and TLS requirement."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_rds_db_proxy"
    ENTITY_NAME: ClassVar[str] = "RDS DB Proxy"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon RDS Proxy."
    ENTITY_ICON: ClassVar[str] = "aws-rds"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The proxy's ARN: a name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("db_proxy_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "db_proxy_arn": {"type": "string"},
        "status": {"type": ["string", "null"]},
        "engine_family": {"type": ["string", "null"]},
        "vpc_id": {"type": ["string", "null"]},
        "require_tls": {"type": ["boolean", "null"]},
        "idle_client_timeout_seconds": {"type": ["integer", "null"]},
        "endpoint": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    db_proxy_arn = models.CharField(max_length=2048, blank=True, default="")
    # AWS's proxy status. NULL = not observed.
    status = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # MYSQL, POSTGRESQL or SQLSERVER. NULL = not observed.
    engine_family = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # The VPC the proxy runs in. NULL = not observed.
    vpc_id = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # Whether clients must use TLS. NULL = not observed.
    require_tls = models.BooleanField(null=True, blank=True, default=None)
    # How long an idle client connection is kept. NULL = not observed.
    idle_client_timeout_seconds = models.IntegerField(null=True, blank=True, default=None)
    # The proxy endpoint. NULL = not observed.
    endpoint = models.CharField(max_length=2048, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_rds_db_proxy"

    def get_name(self) -> str:
        return self.name or self.db_proxy_arn

    def __str__(self) -> str:
        return self.get_name()
