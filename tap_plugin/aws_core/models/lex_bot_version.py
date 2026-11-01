"""AWS Lex Bot Version — a numbered Lex Bot Version."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class LexBotVersion(BaseModel):
    """An AWS Lex Bot Version, a numbered version only (never the mutable DRAFT), listed by ListBotVersions. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_lex_bot_version"
    ENTITY_NAME: ClassVar[str] = "AWS Lex Bot Version"
    ENTITY_DESCRIPTION: ClassVar[str] = "A numbered Lex Bot Version."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The bot id and the numbered version joined with a colon, the CloudFormation primary identifier of AWS::Lex::BotVersion (BotId, BotVersion); the Service Authorization Reference's bot version ARN is name-based (Lex V1) and a V2 listing carries no such ARN. Unique within the account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("lex_bot_version_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "lex_bot_version_key": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    lex_bot_version_key = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_lex_bot_version"

    def get_name(self) -> str:
        return self.name or self.lex_bot_version_key

    def __str__(self) -> str:
        return self.get_name()
