"""AWS Delegated Administration — one member account made the administrator of one AWS service."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsDelegatedAdministration(BaseModel):
    """One delegated administration in an AWS Organizations organization.

    AWS addresses a delegation by exactly (account, service principal):
    ``organizations:RegisterDelegatedAdministrator(AccountId, ServicePrincipal)`` creates it and
    ``DeregisterDelegatedAdministrator(AccountId, ServicePrincipal)`` removes it. So one node per
    (organization, account, service principal), contained by the organization
    (``HOLDS_DELEGATION``), with a ``DELEGATES_TO_ACCOUNT`` reference to the account.

    Collected by ``Boto3Collector`` (``collectors/boto3_collector/organizations.py``) from
    ``ListDelegatedAdministrators`` and one ``ListDelegatedServicesForAccount`` per delegated
    account. AWS cannot tag a delegation, so ``tags`` is always ``{}`` and its lane is declared
    ``none`` (``collectors/boto3_collector/tag_lanes.json``).

    Spec: specs/spec-aws-core-v0.md (req-aws-core-organizations-completeness-4, -13)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_delegated_administration"
    ENTITY_NAME: ClassVar[str] = "AWS Delegated Administration"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "A member account of an AWS Organizations organization registered as the delegated "
        "administrator of one AWS service (for example GuardDuty, Security Hub or Config)."
    )
    ENTITY_ICON: ClassVar[str] = "aws-organizations"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "round-rectangle",
            "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"},
        }
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("organization_id", "account_id", "service_principal")

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "aws_core__aws_account"}], "edges": [{"type": "DELEGATES_TO_ACCOUNT__aws_core"}]},
    ]

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "organization_id": {"type": "string", "pattern": "^(o-[a-z0-9]{10,32})?$"},
        "account_id": {"type": "string", "pattern": "^([0-9]{12})?$"},
        "service_principal": {"type": "string", "maxLength": 128},
        # DelegatedService.DelegationEnabledDate as ISO 8601 UTC; "" when not observed.
        "delegation_enabled_at": {"type": "string"},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    organization_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    account_id = models.CharField(max_length=12, blank=True, default="")
    service_principal = models.CharField(max_length=128, blank=True, default="")
    delegation_enabled_at = models.CharField(max_length=40, blank=True, default="")
    # Canonical {str: str} (req-aws-core-fields-4). AWS cannot tag a delegation: always {}.
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_delegated_administration"

    def get_name(self) -> str:
        return self.name or f"{self.service_principal} -> {self.account_id}"

    def __str__(self) -> str:
        return self.get_name()
