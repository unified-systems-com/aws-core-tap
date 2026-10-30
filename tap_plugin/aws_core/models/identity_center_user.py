"""Identity Center User — a user in an IAM Identity Center identity store."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class IdentityCenterUser(BaseModel):
    """An IAM Identity Center user: a person (or service identity) that can be assigned to accounts and applications. Only the identifying names are typed; emails, phone numbers, addresses and every other profile attribute are personal data and are never collected."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_identity_center_user"
    ENTITY_NAME: ClassVar[str] = "Identity Center User"
    ENTITY_DESCRIPTION: ClassVar[str] = "A user in an IAM Identity Center identity store."
    ENTITY_ICON: ClassVar[str] = "aws-identity-center"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The user's identity store id and user id together (identity_store_id:user_id): a user id is unique only within its identity store.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("user_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "ellipse", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "user_key": {"type": "string"},
        "identity_store_id": {"type": "string"},
        "user_id": {"type": "string"},
        "user_name": {"type": ["string", "null"]},
        "display_name": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "user_key": {"validation": "jsonschema", "schema": {"type": "string"}},
        "identity_store_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "user_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "user_name": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "display_name": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    user_key = models.CharField(max_length=512, blank=True, default="")
    # The identity store the user belongs to.
    identity_store_id = models.CharField(max_length=512, blank=True, default="")
    # AWS's user id within the identity store.
    user_id = models.CharField(max_length=512, blank=True, default="")
    # The user name (botocore marks it sensitive; it is often an email address). NULL = not observed.
    user_name = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The display name (botocore marks it sensitive). NULL = not observed.
    display_name = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_identity_center_user"

    def get_name(self) -> str:
        return self.name or self.user_key

    def __str__(self) -> str:
        return self.get_name()
