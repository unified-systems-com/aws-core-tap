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
    # A task contains its containers (aws-core-tap#211): retiring a task cascades to them. Literals, for
    # validate_plugin's AST reader.
    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "aws_core__aws_ecs_container"}], "edges": [{"type": "RUNS_CONTAINER__aws_core"}]},
    ]
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = ("RUNS_CONTAINER__aws_core",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F9D7B7", "border": "#ED7100", "label": "#421F00"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "task_arn": {"type": "string"},
        "task_definition_arn": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "launch_type": {"type": ["string", "null"]},
        # Null is unobserved (req-aws-core-fields-3): ECS omits these until the task has them.
        "cluster_arn": {"type": ["string", "null"]},
        "last_status": {"type": ["string", "null"]},
        "desired_status": {"type": ["string", "null"]},
        "started_at": {"type": ["string", "null"]},
        "platform_version": {"type": ["string", "null"]},
        "group": {"type": ["string", "null"]},
        # Read only for a stopped task (req-aws-collector-ecs-15); null on a running one.
        "stopped_at": {"type": ["string", "null"]},
        "stopped_reason": {"type": ["string", "null"]},
        "stop_code": {"type": ["string", "null"]},
        "tags": {"type": ["object", "null"]},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string"}},
        "task_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "task_definition_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "launch_type": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "cluster_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "last_status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "desired_status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "started_at": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "platform_version": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "group": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "stopped_at": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "stopped_reason": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "stop_code": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["task_arn"]

    name = models.CharField(max_length=255, blank=True, default="")
    task_arn = models.CharField(max_length=512, blank=True, default="")
    task_definition_arn = models.CharField(max_length=512, null=True, blank=True, default=None)
    status = models.CharField(max_length=64, null=True, blank=True, default=None)
    launch_type = models.CharField(max_length=64, null=True, blank=True, default=None)
    # Null is "not reported", distinct from "" (observed empty).
    cluster_arn = models.CharField(max_length=512, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    last_status = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    desired_status = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    # ISO 8601 UTC, as the envelope renders a datetime; ECS omits it until the task has started.
    started_at = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not started/read"
    platform_version = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    # "service:<name>" for a service-launched task; "family:<name>" or "" otherwise.
    group = models.CharField(max_length=255, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    # Set only once ECS reports the task stopped; ISO 8601 UTC like started_at. stopped_reason is ECS's own text.
    stopped_at = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not stopped/read"
    stopped_reason = models.TextField(null=True, blank=True, default=None)  # noqa: DJ001 — null is "not stopped/read"
    stop_code = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not stopped/read"
    tags = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ecs_task"

    def get_name(self) -> str:
        return self.name or self.task_arn.rsplit("/", 1)[-1] if self.task_arn else ""

    def __str__(self) -> str:
        return self.get_name()
