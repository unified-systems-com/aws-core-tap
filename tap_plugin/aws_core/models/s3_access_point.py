"""S3 Access Point — an Amazon S3 access point."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class S3AccessPoint(BaseModel):
    """An Amazon S3 access point: a named endpoint with its own policy and network origin in front of a bucket. An internet-origin access point with a permissive policy exposes the bucket even when its bucket policy is tight."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_s3_access_point"
    ENTITY_NAME: ClassVar[str] = "S3 Access Point"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon S3 access point."
    ENTITY_ICON: ClassVar[str] = "aws-s3"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The access point's ARN: a name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("access_point_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "access_point_arn": {"type": "string"},
        "bucket": {"type": ["string", "null"]},
        "network_origin": {"type": ["string", "null"]},
        "vpc_id": {"type": ["string", "null"]},
        "is_public": {"type": ["boolean", "null"]},
        "alias": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "access_point_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "bucket": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "network_origin": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "vpc_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "is_public": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "alias": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    access_point_arn = models.CharField(max_length=512, blank=True, default="")
    # The bucket the access point is in front of. NULL = not observed.
    bucket = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Internet or VPC. NULL = not observed.
    network_origin = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The VPC an access point is restricted to. NULL = none, or not observed.
    vpc_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Whether the access point's policy makes it public (GetAccessPointPolicyStatus). NULL = not observed.
    is_public = models.BooleanField(null=True, blank=True, default=None)
    # The access point's alias, usable where a bucket name is. NULL = not observed.
    alias = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_s3_access_point"

    def get_name(self) -> str:
        return self.name or self.access_point_arn

    def __str__(self) -> str:
        return self.get_name()
