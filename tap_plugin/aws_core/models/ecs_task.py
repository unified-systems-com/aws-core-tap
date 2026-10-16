"""ECS Task — an Amazon ECS task (running container group)."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class EcsTask(BaseModel):
    """An Amazon ECS task instance."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ecs_task"
    ENTITY_NAME: ClassVar[str] = "ECS Task"
    ENTITY_DESCRIPTION: ClassVar[str] = "A running ECS task (container group)."
    ENTITY_ICON: ClassVar[str] = "aws-ecs"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The task's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("task_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F9D7B7", "border": "#ED7100", "label": "#421F00"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "task_arn": {"type": "string"},
        "task_definition_arn": {"type": "string"},
        "status": {"type": "string"},
        "launch_type": {"type": "string"},
        # Null is unobserved (req-aws-core-fields-3): ECS omits these until the task has them.
        "cluster_arn": {"type": ["string", "null"]},
        "last_status": {"type": ["string", "null"]},
        "desired_status": {"type": ["string", "null"]},
        "started_at": {"type": ["string", "null"]},
        "platform_version": {"type": ["string", "null"]},
        "group": {"type": ["string", "null"]},
        "tags": {"type": "object"},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string"}},
        "task_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "task_definition_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "status": {"validation": "jsonschema", "schema": {"type": "string"}},
        "launch_type": {"validation": "jsonschema", "schema": {"type": "string"}},
        "cluster_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "last_status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "desired_status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "started_at": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "platform_version": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "group": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "tags": {"validation": "jsonschema", "schema": {"type": "object"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["task_arn"]

    name = models.CharField(max_length=255, blank=True, default="")
    task_arn = models.CharField(max_length=512, blank=True, default="")
    task_definition_arn = models.CharField(max_length=512, blank=True, default="")
    status = models.CharField(max_length=64, blank=True, default="")
    launch_type = models.CharField(max_length=64, blank=True, default="")
    # Null is "not reported", distinct from "" (observed empty).
    cluster_arn = models.CharField(max_length=512, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    last_status = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    desired_status = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    # ISO 8601 UTC, as the envelope renders a datetime; ECS omits it until the task has started.
    started_at = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not started/read"
    platform_version = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    # "service:<name>" for a service-launched task; "family:<name>" or "" otherwise.
    group = models.CharField(max_length=255, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    tags = models.JSONField(default=dict, blank=True)
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ecs_task"

    def get_name(self) -> str:
        return self.name or self.task_arn.rsplit("/", 1)[-1] if self.task_arn else ""

    def __str__(self) -> str:
        return self.get_name()
