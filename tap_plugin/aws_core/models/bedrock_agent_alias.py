"""AWS Bedrock Agent Alias — an AWS Bedrock Agent Alias."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class BedrockAgentAlias(BaseModel):
    """An AWS Bedrock Agent Alias, read by ListAgentAliases. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_bedrock_agent_alias"
    ENTITY_NAME: ClassVar[str] = "AWS Bedrock Agent Alias"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Bedrock Agent Alias."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (_arn), built by the manifest's derive from the scope and the item (agent-alias/<agentId>/<agentAliasId>, ids from the parent agent and the alias): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("bedrock_agent_alias_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "bedrock_agent_alias_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    bedrock_agent_alias_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_bedrock_agent_alias"

    def get_name(self) -> str:
        return self.name or self.bedrock_agent_alias_arn

    def __str__(self) -> str:
        return self.get_name()
