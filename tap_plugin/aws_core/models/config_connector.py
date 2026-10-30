"""AWS Config Connector — a connector that lets AWS Config read resources in another cloud."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ConfigConnector(BaseModel):
    """An AWS Config connector: a standing link from AWS Config to a tenant in another cloud. Only the connector's identity is collected; GetConnector, whose client identifier is a credential reference, is never called."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_config_connector"
    ENTITY_NAME: ClassVar[str] = "AWS Config Connector"
    ENTITY_DESCRIPTION: ClassVar[str] = "A connector that lets AWS Config read resources in another cloud."
    ENTITY_ICON: ClassVar[str] = "aws-config"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The connector's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("connector_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "connector_arn": {"type": "string"},
        "provider": {"type": ["string", "null"]},
        "tenant_identifier": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "connector_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "provider": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "tenant_identifier": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    connector_arn = models.CharField(max_length=512, blank=True, default="")
    # The other cloud (AZURE). NULL = not observed.
    provider = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The other cloud's tenant id. NULL = not observed.
    tenant_identifier = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_config_connector"

    def get_name(self) -> str:
        return self.name or self.connector_arn

    def __str__(self) -> str:
        return self.get_name()
