"""IAM Policy — an AWS Identity and Access Management policy."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class IamPolicy(BaseModel):
    """An AWS IAM policy document."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_policy"
    ENTITY_NAME: ClassVar[str] = "IAM Policy"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS IAM permission policy."
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The policy's ARN: AWS-managed policies share a name
    # across accounts but not an ARN with customer policies.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("policy_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "policy_arn": {"type": "string"},
        "path": {"type": "string"},
        "is_aws_managed": {"type": "boolean"},
        "policy_id": {"type": ["string", "null"]},
        "default_version_id": {"type": ["string", "null"]},
        "attachment_count": {"type": ["integer", "null"]},
        "is_attachable": {"type": ["boolean", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "policy_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "path": {"validation": "jsonschema", "schema": {"type": "string"}},
        "is_aws_managed": {"validation": "jsonschema", "schema": {"type": "boolean"}},
        "policy_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "default_version_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "attachment_count": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "is_attachable": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    policy_arn = models.CharField(max_length=512, blank=True, default="")
    path = models.CharField(max_length=512, blank=True, default="/")
    is_aws_managed = models.BooleanField(default=False)
    # AWS's immutable policy id (ANPA...); NULL = not observed. A policy is looked up by its full ARN, so the id
    # is what distinguishes a delete-and-recreate under the same ARN.
    policy_id = models.CharField(max_length=64, blank=True, null=True, default=None, db_index=True)
    default_version_id = models.CharField(max_length=32, blank=True, null=True, default=None)
    # How many principals the policy is attached to. NULL = not observed.
    attachment_count = models.IntegerField(blank=True, null=True, default=None)
    is_attachable = models.BooleanField(blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iam_policy"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
