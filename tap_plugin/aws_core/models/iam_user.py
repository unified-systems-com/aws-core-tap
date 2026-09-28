"""IAM User — an AWS Identity and Access Management user."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class IamUser(BaseModel):
    """An AWS IAM user."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_user"
    ENTITY_NAME: ClassVar[str] = "IAM User"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS IAM user identity."
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The user's ARN: a user name is unique only within an
    # account.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("user_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "user_arn": {"type": "string"},
        "path": {"type": "string"},
        "mfa_enabled": {"type": ["boolean", "null"]},
        "user_id": {"type": ["string", "null"]},
        "permissions_boundary_arn": {"type": ["string", "null"]},
        "password_last_used": {"type": ["string", "null"]},
        "attached_policy_arns": {"type": ["array", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "user_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "path": {"validation": "jsonschema", "schema": {"type": "string"}},
        "mfa_enabled": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "user_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "permissions_boundary_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "password_last_used": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "attached_policy_arns": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    user_arn = models.CharField(max_length=512, blank=True, default="")
    path = models.CharField(max_length=512, blank=True, default="/")
    # NULL = not observed (ListMFADevices denied or failed); False = observed, no MFA device registered.
    mfa_enabled = models.BooleanField(blank=True, null=True, default=None)
    # AWS's immutable user id (AIDA...); see IamRole.role_id for why the ARN alone cannot tell a recreated user
    # from the same one. NULL = not observed.
    user_id = models.CharField(max_length=64, blank=True, null=True, default=None, db_index=True)
    # NULL = GetUser did not answer; "" = answered, no permissions boundary. ListUsers omits the attribute.
    permissions_boundary_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # ISO 8601 UTC console-password last-use time; "" = observed, never used (or no console password);
    # NULL = not observed.
    password_last_used = models.CharField(max_length=32, blank=True, null=True, default=None)
    # Managed policies attached directly to the user. NULL = not observed; [] = observed, none.
    attached_policy_arns = models.JSONField(blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iam_user"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
