"""AWS VerifiedPermissions Policy — an AWS VerifiedPermissions Policy."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class VerifiedpermissionsPolicy(BaseModel):
    """An AWS VerifiedPermissions Policy, read by ListPolicies. Only its identity, name and tags are collected; the rest of the response is not stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_verifiedpermissions_policy"
    ENTITY_NAME: ClassVar[str] = "AWS VerifiedPermissions Policy"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS VerifiedPermissions Policy."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The policy store id and the policy id (PolicyStoreId and PolicyId, the CloudFormation primary identifier): AWS gives a policy no ARN, and a policy store id is unique to its store.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("verifiedpermissions_policy_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "verifiedpermissions_policy_key": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    verifiedpermissions_policy_key = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_verifiedpermissions_policy"

    def get_name(self) -> str:
        return self.name or self.verifiedpermissions_policy_key

    def __str__(self) -> str:
        return self.get_name()
