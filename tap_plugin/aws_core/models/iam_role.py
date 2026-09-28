"""IAM Role — an AWS Identity and Access Management role."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class IamRole(BaseModel):
    """An AWS IAM role."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_role"
    ENTITY_NAME: ClassVar[str] = "IAM Role"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS IAM role for service or cross-account access."
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The role's ARN, the boto3 collector's identity for it.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("role_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "role_arn": {"type": "string"},
        "path": {"type": "string"},
        "max_session_duration": {"type": ["integer", "null"]},
        "role_id": {"type": ["string", "null"]},
        "permissions_boundary_arn": {"type": ["string", "null"]},
        "last_used_at": {"type": ["string", "null"]},
        "attached_policy_arns": {"type": ["array", "null"]},
        "trusted_account_ids": {"type": ["array", "null"]},
        "trusted_services": {"type": ["array", "null"]},
        "trusts_wildcard_principal": {"type": ["boolean", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "role_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "path": {"validation": "jsonschema", "schema": {"type": "string"}},
        "max_session_duration": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "role_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "permissions_boundary_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "last_used_at": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "attached_policy_arns": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "trusted_account_ids": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "trusted_services": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "trusts_wildcard_principal": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    role_arn = models.CharField(max_length=512, blank=True, default="")
    path = models.CharField(max_length=512, blank=True, default="/")
    max_session_duration = models.IntegerField(blank=True, null=True)
    # AWS's immutable role id (AROA...). The ARN is the natural key and is reused when a role is deleted and
    # recreated under the same name and path; the RoleId is not, so it is what tells a recreation from the same
    # role (the falsifier's REIDENTIFIED case). NULL = not observed, never "has no id".
    role_id = models.CharField(max_length=64, blank=True, null=True, default=None, db_index=True)
    # NULL = GetRole did not answer (ListRoles omits this attribute by AWS's own contract, so it is read per
    # role); "" = GetRole answered and the role has no permissions boundary.
    permissions_boundary_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # RoleLastUsed.LastUsedDate from GetRole, ISO 8601 UTC; "" = observed, never used; NULL = not observed.
    last_used_at = models.CharField(max_length=32, blank=True, null=True, default=None)
    # ARNs of the managed policies attached to the role (AWS-managed and customer-managed alike). NULL = not
    # observed; [] = observed, none attached. The graph edge ATTACHES_POLICY__aws_core covers only the
    # customer-managed ones, whose nodes this collector holds.
    attached_policy_arns = models.JSONField(blank=True, null=True, default=None)
    # The trust policy, summarised over its Allow statements. trusted_account_ids are the OTHER accounts (never
    # the role's own) whose principals may assume the role: the cross-account assume-role targets, and the
    # source of the TRUSTS_ACCOUNT edge. trusted_services are service principals (lambda.amazonaws.com ...).
    # trusts_wildcard_principal is true when an Allow statement names Principal "*" (or {"AWS": "*"}), whether
    # or not a Condition narrows it: the field says the door is unnamed, the trust policy says what guards it.
    trusted_account_ids = models.JSONField(blank=True, null=True, default=None)
    trusted_services = models.JSONField(blank=True, null=True, default=None)
    trusts_wildcard_principal = models.BooleanField(blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iam_role"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
