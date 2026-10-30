"""AWS SageMaker Code Repository — an AWS SageMaker Code Repository."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class SagemakerCodeRepository(BaseModel):
    """An AWS SageMaker Code Repository, listed by ListCodeRepositories. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_sagemaker_code_repository"
    ENTITY_NAME: ClassVar[str] = "AWS SageMaker Code Repository"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS SageMaker Code Repository."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (CodeRepositoryArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("code_repository_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "code_repository_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    code_repository_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_sagemaker_code_repository"

    def get_name(self) -> str:
        return self.name or self.code_repository_arn

    def __str__(self) -> str:
        return self.get_name()
