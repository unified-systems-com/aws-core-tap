"""AWS Bedrock Guardrail Version — a numbered Bedrock Guardrail Version."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class BedrockGuardrailVersion(BaseModel):
    """An AWS Bedrock Guardrail Version, a numbered version only (never the mutable DRAFT), listed by ListGuardrails. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_bedrock_guardrail_version"
    ENTITY_NAME: ClassVar[str] = "AWS Bedrock Guardrail Version"
    ENTITY_DESCRIPTION: ClassVar[str] = "A numbered Bedrock Guardrail Version."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The guardrail ARN and the numbered version joined with a colon (arn:...:guardrail/<id>:<n>). The Service Authorization Reference defines no ARN for a guardrail version, so this composite mirrors the CloudFormation primary identifier (GuardrailId, Version). Unique within the account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("bedrock_guardrail_version_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "bedrock_guardrail_version_key": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    bedrock_guardrail_version_key = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_bedrock_guardrail_version"

    def get_name(self) -> str:
        return self.name or self.bedrock_guardrail_version_key

    def __str__(self) -> str:
        return self.get_name()
