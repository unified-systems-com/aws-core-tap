"""CloudTrail Trail — an AWS CloudTrail trail."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CloudtrailTrail(BaseModel):
    """An AWS CloudTrail trail."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cloudtrail_trail"
    ENTITY_NAME: ClassVar[str] = "CloudTrail Trail"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS CloudTrail trail — the account's API audit log delivery pipeline "
        "into S3 and optionally CloudWatch Logs (AU-family evidence surface)."
    )
    ENTITY_ICON: ClassVar[str] = "aws-cloudtrail"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The trail's ARN, the boto3 collector's identity for it
    # (TrailARN).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("trail_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "trail_arn": {"type": "string"},
        "s3_bucket_name": {"type": "string"},
        "is_multi_region": {"type": "boolean"},
        "log_file_validation_enabled": {"type": "boolean"},
        "is_logging": {"type": "boolean"},
        "tags": {"type": ["object", "null"]},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "trail_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "s3_bucket_name": {"validation": "jsonschema", "schema": {"type": "string"}},
        "is_multi_region": {"validation": "jsonschema", "schema": {"type": "boolean"}},
        "log_file_validation_enabled": {
            "validation": "jsonschema",
            "schema": {"type": "boolean"},
        },
        "is_logging": {"validation": "jsonschema", "schema": {"type": "boolean"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    trail_arn = models.CharField(max_length=512, blank=True, default="")
    s3_bucket_name = models.CharField(max_length=255, blank=True, default="")
    is_multi_region = models.BooleanField(default=False)
    log_file_validation_enabled = models.BooleanField(default=False)
    is_logging = models.BooleanField(default=False)
    tags = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cloudtrail_trail"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
