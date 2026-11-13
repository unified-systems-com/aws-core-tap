"""AWS LakeFormation Tag — an AWS LakeFormation Tag."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class LakeformationTag(BaseModel):
    """An AWS LakeFormation Tag, listed by ListLFTags. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_lakeformation_tag"
    ENTITY_NAME: ClassVar[str] = "AWS LakeFormation Tag"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS LakeFormation Tag."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The LF-tag's key, the CloudFormation primary identifier of the type; the item carries no ARN. Unique within the account and region. The key leads with <partition>:<account>:<region>: (req-aws-collector-identity-8), because these names repeat in other regions and accounts (issue 224).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("lakeformation_tag_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "lakeformation_tag_key": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    lakeformation_tag_key = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_lakeformation_tag"

    def get_name(self) -> str:
        return self.name or self.lakeformation_tag_key

    def __str__(self) -> str:
        return self.get_name()
