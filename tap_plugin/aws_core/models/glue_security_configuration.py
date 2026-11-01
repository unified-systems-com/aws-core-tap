"""AWS Glue Security Configuration — an AWS Glue Security Configuration."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class GlueSecurityConfiguration(BaseModel):
    """An AWS Glue Security Configuration, listed by GetSecurityConfigurations. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_glue_security_configuration"
    ENTITY_NAME: ClassVar[str] = "AWS Glue Security Configuration"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Glue Security Configuration."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The configuration's name, the identifier GetSecurityConfiguration takes; the AWS Service Authorization Reference lists no ARN for a Glue security configuration. Unique within the account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("glue_security_configuration_name",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "glue_security_configuration_name": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    glue_security_configuration_name = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_glue_security_configuration"

    def get_name(self) -> str:
        return self.name or self.glue_security_configuration_name

    def __str__(self) -> str:
        return self.get_name()
