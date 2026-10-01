"""AWS IAM Identity Center account assignment — a principal granted a permission set in an account."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsIdentityCenterAccountAssignment(BaseModel):
    """One account assignment: (instance, account, permission set, principal type, principal id).

    That tuple is how AWS addresses it: ``CreateAccountAssignment`` and
    ``DeleteAccountAssignment`` take exactly these members. Collected from
    ``ListPermissionSetsProvisionedToAccount`` (no ``ProvisioningStatus`` filter) and
    ``ListAccountAssignments`` per (account, permission set), every call read to its last page.
    Contained by its instance (``HOLDS_ACCOUNT_ASSIGNMENT``), with ONE surface per instance across
    every nested listing (``req-aws-landing-zone-identity-center-5``).

    Users are not nodes (ruling 2026-10-01): a ``USER`` assignment carries ``principal_id`` only.
    A ``GROUP`` assignment also has ``GRANTED_TO_GROUP``. AWS cannot tag an assignment, so ``tags``
    is always ``{}``.

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-identity-center)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_identity_center_account_assignment"
    ENTITY_NAME: ClassVar[str] = "AWS IAM Identity Center Account Assignment"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An IAM Identity Center account assignment: a user or group granted one permission set in one AWS account."
    )
    ENTITY_ICON: ClassVar[str] = "aws-identity-center"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "diamond", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = (
        "instance_arn",
        "account_id",
        "permission_set_arn",
        "principal_type",
        "principal_id",
    )

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {
            "nodes": [{"type": "aws_core__aws_identity_center_permission_set"}],
            "edges": [{"type": "GRANTS_PERMISSION_SET__aws_core"}],
        },
        {"nodes": [{"type": "aws_core__aws_account"}], "edges": [{"type": "GRANTS_ACCESS_TO_ACCOUNT__aws_core"}]},
        {"nodes": [{"type": "aws_core__aws_identity_center_group"}], "edges": [{"type": "GRANTED_TO_GROUP__aws_core"}]},
    ]

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "instance_arn": {"type": "string"},
        "account_id": {"type": "string", "pattern": "^([0-9]{12})?$"},
        "permission_set_arn": {"type": "string"},
        # AWS's PrincipalType: USER or GROUP (kept verbatim).
        "principal_type": {"type": "string"},
        "principal_id": {"type": "string"},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    instance_arn = models.CharField(max_length=1224, blank=True, default="", db_index=True)
    account_id = models.CharField(max_length=12, blank=True, default="", db_index=True)
    permission_set_arn = models.CharField(max_length=1224, blank=True, default="")
    principal_type = models.CharField(max_length=16, blank=True, default="")
    principal_id = models.CharField(max_length=64, blank=True, default="")
    # Canonical {str: str}. AWS cannot tag an assignment: always {}.
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_identity_center_account_assignment"

    def get_name(self) -> str:
        return self.name or f"{self.principal_type} {self.principal_id} -> {self.account_id}"

    def __str__(self) -> str:
        return self.get_name()
