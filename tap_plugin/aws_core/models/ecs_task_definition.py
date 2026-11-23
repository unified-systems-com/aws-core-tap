"""AWS ECS Task Definition — an AWS ECS Task Definition."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import NO_EVENT_TIME, NoEventTime
from tap_grid.models import BaseModel


class EcsTaskDefinition(BaseModel):
    """One ECS task definition revision, read by DescribeTaskDefinition (req-aws-collector-ecs-25).

    The typed fields are its identity, family name and tags. The whole ``taskDefinition`` object is stored too, in
    ``configuration`` (the manifest entry's ``persist_configuration``), with ``containerDefinitions[].repositoryCredentials``
    removed and any string whose key names a secret dropped, the value of an environment variable whose name names one
    included. Every other ``containerDefinitions[].environment`` value is stored as the operator wrote it. ``secrets[]``
    is stored: it names where each secret is read from (``valueFrom``), never its value, and is what
    ``REFERENCES_SECRET`` and ``REFERENCES_PARAMETER`` are drawn from.
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ecs_task_definition"
    ENTITY_NAME: ClassVar[str] = "AWS ECS Task Definition"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS ECS Task Definition."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The task definition revision's ARN (taskDefinitionArn): unique across accounts and regions, and one per revision.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("ecs_task_definition_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "ecs:task-definition"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): no typed field of this model says when
    # the thing happened in the world; EVENT_TIME_REASON says why.
    EVENT_TIME: ClassVar[NoEventTime] = NO_EVENT_TIME
    EVENT_TIME_REASON: ClassVar[str] = (
        "AWS states when it was created (DescribeTaskDefinition registeredAt), held only inside configuration: a "
        "declaration names a typed field, and this model has none for it (unified-systems-com/tap#1289)."
    )

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
