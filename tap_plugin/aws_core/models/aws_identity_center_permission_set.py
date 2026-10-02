"""AWS IAM Identity Center permission set — a template of access granted in an account."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsIdentityCenterPermissionSet(BaseModel):
    """One Identity Center permission set.

    Collected from ``sso-admin:ListPermissionSets``, ``DescribePermissionSet`` and
    ``ListManagedPoliciesInPermissionSet``, every listing read to its last page. A later page of
    the managed-policy listing that fails leaves ``managed_policy_arns`` null, never the pages read
    so far (``req-aws-collector-pagination-2``). The inline policy is not read. Contained by its
    instance (``HOLDS_PERMISSION_SET``).

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-identity-center)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_identity_center_permission_set"
    ENTITY_NAME: ClassVar[str] = "AWS IAM Identity Center Permission Set"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An IAM Identity Center permission set: the policies and session length a user or group "
        "receives in an AWS account it is assigned to."
    )
    ENTITY_ICON: ClassVar[str] = "aws-identity-center"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("permission_set_arn",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "permission_set_arn": {"type": "string"},
        "instance_arn": {"type": "string"},
        "description": {"type": "string"},
        # ISO 8601 duration, e.g. PT1H.
        "session_duration": {"type": "string"},
        "relay_state": {"type": "string"},
        "created_at": {"type": "string"},
        # AWS-managed policy ARNs attached to the permission set; null when the listing did not finish.
        "managed_policy_arns": {"type": ["array", "null"], "items": {"type": "string"}},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    permission_set_arn = models.CharField(max_length=1224, blank=True, default="", db_index=True)
    instance_arn = models.CharField(max_length=1224, blank=True, default="")
    description = models.CharField(max_length=700, blank=True, default="")
    session_duration = models.CharField(max_length=100, blank=True, default="")
    relay_state = models.CharField(max_length=240, blank=True, default="")
    created_at = models.CharField(max_length=40, blank=True, default="")
    managed_policy_arns = models.JSONField(null=True, blank=True, default=None)
    # AWS tags, canonical flat {str: str}. Source: sso-admin:ListTagsForResource (`Tags`, list_kv).
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_identity_center_permission_set"

    def get_name(self) -> str:
        return self.name or self.permission_set_arn

    def __str__(self) -> str:
        return self.get_name()
