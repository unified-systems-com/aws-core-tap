"""AWS Bedrock Flow Version — an AWS Bedrock Flow Version."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class BedrockFlowVersion(BaseModel):
    """An AWS Bedrock Flow Version, read by ListFlowVersions. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_bedrock_flow_version"
    ENTITY_NAME: ClassVar[str] = "AWS Bedrock Flow Version"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Bedrock Flow Version."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): the CloudFormation primary identifier of AWS::Bedrock::FlowVersion, FlowArn and Version joined with '|': the summary's arn is the flow's ARN (botocore FlowVersionSummary: 'the flow that the version belongs to'), shared by every version, and the Service Authorization Reference defines no flow-version ARN
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("bedrock_flow_version_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "bedrock_flow_version_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    bedrock_flow_version_id = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_bedrock_flow_version"

    def get_name(self) -> str:
        return self.name or self.bedrock_flow_version_id

    def __str__(self) -> str:
        return self.get_name()
