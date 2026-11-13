"""AWS ECR Repository Creation Template — an AWS ECR Repository Creation Template."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class EcrRepositoryCreationTemplate(BaseModel):
    """An AWS ECR Repository Creation Template, read by DescribeRepositoryCreationTemplates. Only its identity, name and tags are collected; the rest of the response is not stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ecr_repository_creation_template"
    ENTITY_NAME: ClassVar[str] = "AWS ECR Repository Creation Template"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS ECR Repository Creation Template."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The account, the region and the template prefix (prefix, the CloudFormation primary identifier): AWS gives it no ARN, and a bare name repeats across accounts and regions, so the key is the account, the region and the prefix. The key leads with <partition>:<account>:<region>: (req-aws-collector-identity-8), because these names repeat in other regions and accounts (issue 224).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("ecr_repository_creation_template_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "ecr_repository_creation_template_key": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    ecr_repository_creation_template_key = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ecr_repository_creation_template"

    def get_name(self) -> str:
        return self.name or self.ecr_repository_creation_template_key

    def __str__(self) -> str:
        return self.get_name()
