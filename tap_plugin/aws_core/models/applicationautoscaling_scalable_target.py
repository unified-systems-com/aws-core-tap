"""AWS ApplicationAutoScaling Scalable Target — an AWS ApplicationAutoScaling Scalable Target."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class ApplicationautoscalingScalableTarget(BaseModel):
    """An AWS ApplicationAutoScaling Scalable Target, read by DescribeScalableTargets. Only its identity, name and tags are collected; the rest of the response is not stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_applicationautoscaling_scalable_target"
    ENTITY_NAME: ClassVar[str] = "AWS ApplicationAutoScaling Scalable Target"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS ApplicationAutoScaling Scalable Target."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The scalable target's ARN (ScalableTargetARN): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("applicationautoscaling_scalable_target_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "application-autoscaling:ScalableTarget"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): when AWS created it (DescribeScalableTargets
    # ScalableTargets[].CreationTime, a botocore timestamp), read from configuration['CreationTime'], where the
    # collector stores it as AWS sent it. AWS states no end for it.
    EVENT_TIME: ClassVar[Interval] = Interval(start="configuration", kind="created", member="CreationTime")

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "applicationautoscaling_scalable_target_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    applicationautoscaling_scalable_target_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_applicationautoscaling_scalable_target"

    def get_name(self) -> str:
        return self.name or self.applicationautoscaling_scalable_target_arn

    def __str__(self) -> str:
        return self.get_name()
