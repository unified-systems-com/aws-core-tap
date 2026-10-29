"""IAM Group — an AWS IAM group of users."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class IamGroup(BaseModel):
    """An AWS IAM group.

    A group has no tag operations in IAM (the service defines no ListGroupTags), so ``tags`` is always ``{}``.
    Its members are users and are read through the group, not stored here."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_group"
    ENTITY_NAME: ClassVar[str] = "IAM Group"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS IAM group of users."
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The group's ARN: a group name is unique only within an account.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("group_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "group_arn": {"type": "string"},
        "path": {"type": "string"},
        "group_id": {"type": ["string", "null"]},
        "attached_policy_arns": {"type": ["array", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "group_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "path": {"validation": "jsonschema", "schema": {"type": "string"}},
        "group_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "attached_policy_arns": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    group_arn = models.CharField(max_length=512, blank=True, default="")
    path = models.CharField(max_length=512, blank=True, default="/")
    # AWS's immutable group id (AGPA...); NULL = not observed.
    group_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Managed policies attached to the group. NULL = not observed; [] = observed, none.
    attached_policy_arns = models.JSONField(blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iam_group"

    def get_name(self) -> str:
        return self.name or self.group_arn

    def __str__(self) -> str:
        return self.get_name()
