"""AWS Region — a geographic region in the AWS global infrastructure."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import NO_EVENT_TIME, NoEventTime
from tap_grid.models import BaseModel


class AwsRegion(BaseModel):
    """An AWS geographic region (us-east-1, eu-west-1, etc.)."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_region"
    ENTITY_NAME: ClassVar[str] = "AWS Region"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS geographic region."
    ENTITY_ICON: ClassVar[str] = "aws-region"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The region code (us-gov-east-1): unique across
    # partitions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("region_code",)
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): no typed field of this model says when
    # the thing happened in the world; EVENT_TIME_REASON says why.
    EVENT_TIME: ClassVar[NoEventTime] = NO_EVENT_TIME
    EVENT_TIME_REASON: ClassVar[str] = (
        "Reference data this plugin seeds; AWS states no time for a Region (DescribeRegions)."
    )
    # Identity (req-aws-collector-identity-13): no manifest entry collects this type, so its declaration lives
    # here, in the shape of a manifest entry's `identity` block, checked against the CloudFormation ledger by
    # tests/test_identity_declarations.py.
    AWS_IDENTITY: ClassVar[dict[str, object]] = {
        "cfn_type": None,
        "reason": "not a CloudFormation resource: an AWS Region, named by the region code AWS gives it",
    }
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#B7E5E6", "border": "#00A4A6", "label": "#002D2E"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "region_code": {"type": "string", "minLength": 1},
        "geographic_area": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "region_code": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "geographic_area": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name", "region_code"]

    name = models.CharField(max_length=255, blank=True, default="")
    region_code = models.CharField(max_length=64, blank=True, default="", db_index=True)
    geographic_area = models.CharField(max_length=255, null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_region"

    def get_name(self) -> str:
        return self.name or self.region_code

    def __str__(self) -> str:
        return self.get_name()
