"""AWS EC2 VPC Block Public Access Exclusion — an AWS EC2 VPC Block Public Access Exclusion."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class Ec2VpcBlockPublicAccessExclusion(BaseModel):
    """An AWS EC2 VPC Block Public Access Exclusion, listed by DescribeVpcBlockPublicAccessExclusions. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ec2_vpc_block_public_access_exclusion"
    ENTITY_NAME: ClassVar[str] = "AWS EC2 VPC Block Public Access Exclusion"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS EC2 VPC Block Public Access Exclusion."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's own id (ExclusionId), assigned by AWS and unique within its type.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("ec2_vpc_block_public_access_exclusion_id",)
    ARN_RESOURCE: ClassVar[str | None] = "ec2:vpc-block-public-access-exclusion"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): when AWS created it
    # (DescribeVpcBlockPublicAccessExclusions VpcBlockPublicAccessExclusions[].CreationTimestamp, a botocore timestamp),
    # read from configuration['CreationTimestamp'], where the collector stores it as AWS sent it. It holds until
    # configuration['DeletionTimestamp'], the end AWS states.
    EVENT_TIME: ClassVar[Interval] = Interval(
        start="configuration",
        kind="created",
        member="CreationTimestamp",
        end="configuration",
        end_member="DeletionTimestamp",
    )

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "ec2_vpc_block_public_access_exclusion_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    ec2_vpc_block_public_access_exclusion_id = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ec2_vpc_block_public_access_exclusion"

    def get_name(self) -> str:
        return self.name or self.ec2_vpc_block_public_access_exclusion_id

    def __str__(self) -> str:
        return self.get_name()
