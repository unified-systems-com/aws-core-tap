"""AWS Bedrock Data Automation Blueprint — an AWS Bedrock Data Automation Blueprint."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class BedrockBlueprint(BaseModel):
    """An AWS Bedrock Data Automation Blueprint, listed by ListBlueprints. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_bedrock_blueprint"
    ENTITY_NAME: ClassVar[str] = "AWS Bedrock Data Automation Blueprint"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Bedrock Data Automation Blueprint."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (blueprintArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("bedrock_blueprint_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "bedrock_blueprint_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    bedrock_blueprint_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_bedrock_blueprint"

    def get_name(self) -> str:
        return self.name or self.bedrock_blueprint_arn

    def __str__(self) -> str:
        return self.get_name()
