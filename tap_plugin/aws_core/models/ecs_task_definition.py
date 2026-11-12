"""AWS ECS Task Definition — an AWS ECS Task Definition."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class EcsTaskDefinition(BaseModel):
    """An AWS ECS Task Definition, read by DescribeTaskDefinition. Only its identity, name and tags are collected; the rest of the response is not stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ecs_task_definition"
    ENTITY_NAME: ClassVar[str] = "AWS ECS Task Definition"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS ECS Task Definition."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The task definition revision's ARN (taskDefinitionArn): unique across accounts and regions, and one per revision.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("ecs_task_definition_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "ecs:task-definition"

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "ecs_task_definition_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    ecs_task_definition_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ecs_task_definition"

    def get_name(self) -> str:
        return self.name or self.ecs_task_definition_arn

    def __str__(self) -> str:
        return self.get_name()
