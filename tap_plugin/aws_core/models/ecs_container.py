"""ECS Container — one container of a running ECS task, with the image and digest ECS reports."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class EcsContainer(BaseModel):
    """A container inside an Amazon ECS task (req-aws-collector-ecs-3)."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ecs_container"
    ENTITY_NAME: ClassVar[str] = "ECS Container"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "A container of an ECS task: the image reference from the task definition and the image digest ECS "
        "resolved when it pulled, which names the build that is actually running."
    )
    ENTITY_ICON: ClassVar[str] = "aws-ecs"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): the container's ARN, unique across tasks and clusters.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("container_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F9D7B7", "border": "#ED7100", "label": "#421F00"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "container_arn": {"type": "string"},
        # image is the reference in the task definition (may be a movable tag); image_digest is what ran.
        # Both are stored as ECS reports them; null is "not reported" (req-aws-collector-ecs-4, -5).
        "image": {"type": ["string", "null"]},
        "image_digest": {"type": ["string", "null"]},
        "runtime_id": {"type": ["string", "null"]},
        "last_status": {"type": ["string", "null"]},
        "tags": {"type": "object"},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "container_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "image": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "image_digest": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "runtime_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "last_status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "tags": {"validation": "jsonschema", "schema": {"type": "object"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    container_arn = models.CharField(max_length=512, blank=True, default="")
    image = models.CharField(max_length=2048, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    image_digest = models.CharField(max_length=256, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not reported"
    runtime_id = models.CharField(max_length=256, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    last_status = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    tags = models.JSONField(default=dict, blank=True)
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ecs_container"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
