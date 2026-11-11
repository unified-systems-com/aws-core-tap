"""AWS OpenSearchServerless Security Config — an AWS OpenSearchServerless Security Config."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class OpensearchserverlessSecurityConfig(BaseModel):
    """An AWS OpenSearchServerless Security Config, read by ListSecurityConfigs. Only its identity, name and tags are collected; the rest of the response is not stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_opensearchserverless_security_config"
    ENTITY_NAME: ClassVar[str] = "AWS OpenSearchServerless Security Config"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS OpenSearchServerless Security Config."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The account, the region and the configuration id (Id, the CloudFormation primary identifier): AWS gives it no ARN, and a bare name repeats across accounts and regions, so the key is the account, the region and the id. The key leads with <partition>:<account>:<region>: (req-aws-collector-identity-8), because these names repeat in other regions and accounts (issue 224).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("opensearchserverless_security_config_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "opensearchserverless_security_config_key": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    opensearchserverless_security_config_key = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_opensearchserverless_security_config"

    def get_name(self) -> str:
        return self.name or self.opensearchserverless_security_config_key

    def __str__(self) -> str:
        return self.get_name()
