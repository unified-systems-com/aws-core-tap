"""AWS Bedrock Prompt Version — a numbered Bedrock Prompt Version."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class BedrockPromptVersion(BaseModel):
    """An AWS Bedrock Prompt Version, a numbered version only (never the mutable DRAFT), listed by ListPrompts. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_bedrock_prompt_version"
    ENTITY_NAME: ClassVar[str] = "AWS Bedrock Prompt Version"
    ENTITY_DESCRIPTION: ClassVar[str] = "A numbered Bedrock Prompt Version."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The prompt version ARN, arn:<partition>:bedrock:<region>:<account>:prompt/<id>:<version>, built from the listed id and version (Service Authorization Reference resource prompt-version).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("bedrock_prompt_version_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "bedrock:prompt-version"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): when AWS created it (ListPrompts
    # promptSummaries[].createdAt, a botocore timestamp), read from configuration['createdAt'], where the collector
    # stores it as AWS sent it. AWS states no end for it.
    EVENT_TIME: ClassVar[Interval] = Interval(start="configuration", kind="created", member="createdAt")

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "bedrock_prompt_version_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    bedrock_prompt_version_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_bedrock_prompt_version"

    def get_name(self) -> str:
        return self.name or self.bedrock_prompt_version_arn

    def __str__(self) -> str:
        return self.get_name()
