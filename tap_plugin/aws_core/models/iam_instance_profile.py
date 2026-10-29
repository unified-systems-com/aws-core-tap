"""IAM Instance Profile — an AWS IAM instance profile that passes a role to EC2 instances."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class IamInstanceProfile(BaseModel):
    """An AWS IAM instance profile: the container that hands an IAM role to an EC2 instance."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_instance_profile"
    ENTITY_NAME: ClassVar[str] = "IAM Instance Profile"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS IAM instance profile that passes a role to EC2 instances."
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The instance profile's ARN: a name is unique only within an account.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("instance_profile_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "instance_profile_arn": {"type": "string"},
        "path": {"type": "string"},
        "instance_profile_id": {"type": ["string", "null"]},
        "role_arns": {"type": ["array", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "instance_profile_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "path": {"validation": "jsonschema", "schema": {"type": "string"}},
        "instance_profile_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "role_arns": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    instance_profile_arn = models.CharField(max_length=512, blank=True, default="")
    path = models.CharField(max_length=512, blank=True, default="/")
    # AWS's immutable instance profile id (AIPA...); NULL = not observed.
    instance_profile_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # ARNs of the roles in the profile. NULL = not observed; [] = observed, no role.
    role_arns = models.JSONField(blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iam_instance_profile"

    def get_name(self) -> str:
        return self.name or self.instance_profile_arn

    def __str__(self) -> str:
        return self.get_name()
