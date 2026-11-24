"""AWS SageMaker Algorithm — an AWS SageMaker Algorithm."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class SagemakerAlgorithm(BaseModel):
    """An AWS SageMaker Algorithm, listed by ListAlgorithms. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_sagemaker_algorithm"
    ENTITY_NAME: ClassVar[str] = "AWS SageMaker Algorithm"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS SageMaker Algorithm."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (AlgorithmArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("algorithm_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "sagemaker:algorithm"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): when AWS created it (DescribeAlgorithm
    # CreationTime, a botocore timestamp), read from configuration['_hydrate']['detail']['data']['CreationTime'], where
    # the collector stores it as AWS sent it. AWS states no end for it.
    EVENT_TIME: ClassVar[Interval] = Interval(
        start="configuration", kind="created", member=("_hydrate", "detail", "data", "CreationTime")
    )

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "algorithm_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    algorithm_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_sagemaker_algorithm"

    def get_name(self) -> str:
        return self.name or self.algorithm_arn

    def __str__(self) -> str:
        return self.get_name()
