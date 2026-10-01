"""AWS IAM Identity Center group — a group in an Identity Center instance's identity store."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsIdentityCenterGroup(BaseModel):
    """One identity-store group.

    Collected from ``identitystore:ListGroups(IdentityStoreId)`` with no filter, read to its last
    page. Keyed by (identity store id, group id). Groups are nodes because the question asked is
    which group reaches which account; users are not (ruling 2026-10-01). ``external_ids`` carries
    the SCIM provider's ids (an Okta group, for example). AWS cannot tag a group, so ``tags`` is
    always ``{}`` (lane ``none``, ``collectors/boto3_collector/tag_lanes.json``). Contained by its
    instance (``HOLDS_IDENTITY_GROUP``).

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-identity-center)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_identity_center_group"
    ENTITY_NAME: ClassVar[str] = "AWS IAM Identity Center Group"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "A group in an IAM Identity Center identity store, often provisioned from an external "
        "identity provider over SCIM."
    )
    ENTITY_ICON: ClassVar[str] = "aws-identity-center"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "ellipse", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("identity_store_id", "group_id")

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "identity_store_id": {"type": "string"},
        "group_id": {"type": "string"},
        "display_name": {"type": "string"},
        "description": {"type": "string"},
        # [{"issuer": str, "id": str}] from Group.ExternalIds.
        "external_ids": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"issuer": {"type": "string"}, "id": {"type": "string"}},
                "additionalProperties": False,
            },
        },
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    identity_store_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    group_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    display_name = models.CharField(max_length=1024, blank=True, default="")
    description = models.CharField(max_length=1024, blank=True, default="")
    external_ids = models.JSONField(default=list, blank=True)
    # Canonical {str: str}. AWS cannot tag a group: always {}.
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_identity_center_group"

    def get_name(self) -> str:
        return self.name or self.display_name or self.group_id

    def __str__(self) -> str:
        return self.get_name()
