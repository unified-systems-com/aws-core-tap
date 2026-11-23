"""AWS KendraRanking Execution Plan — an AWS KendraRanking Execution Plan."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class KendrarankingExecutionPlan(BaseModel):
    """An AWS KendraRanking Execution Plan, listed by ListRescoreExecutionPlans and read by DescribeRescoreExecutionPlan. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_kendraranking_execution_plan"
    ENTITY_NAME: ClassVar[str] = "AWS KendraRanking Execution Plan"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS KendraRanking Execution Plan."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The ARN DescribeRescoreExecutionPlan returns (Arn), read for each resource ListRescoreExecutionPlans names; it is never built, because AWS returns it (aws-core-tap#251).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("kendraranking_execution_plan_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "kendra-ranking:rescore-execution-plan"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): when AWS created it (DescribeRescoreExecutionPlan
    # CreatedAt, a botocore timestamp), read from configuration['CreatedAt'], where the collector stores it as AWS sent
    # it. AWS states no end for it.
    EVENT_TIME: ClassVar[Interval] = Interval(start="configuration", kind="created", member="CreatedAt")

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "kendraranking_execution_plan_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    kendraranking_execution_plan_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_kendraranking_execution_plan"

    def get_name(self) -> str:
        return self.name or self.kendraranking_execution_plan_arn

    def __str__(self) -> str:
        return self.get_name()
