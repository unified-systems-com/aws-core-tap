"""GuardDuty Member — a member account of a GuardDuty administrator."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class GuarddutyMember(BaseModel):
    """A GuardDuty member account: an account whose findings an administrator account can see. The member's email address is never collected."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_guardduty_member"
    ENTITY_NAME: ClassVar[str] = "GuardDuty Member"
    ENTITY_DESCRIPTION: ClassVar[str] = "A member account of a GuardDuty administrator."
    ENTITY_ICON: ClassVar[str] = "aws-guardduty"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The administrator's detector id, 'member' and the member account id: a member is unique per administrator.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("member_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "member_key": {"type": "string"},
        "detector_id": {"type": ["string", "null"]},
        "account_id": {"type": ["string", "null"]},
        "relationship_status": {"type": ["string", "null"]},
        "administrator_id": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "member_key": {"validation": "jsonschema", "schema": {"type": "string"}},
        "detector_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "account_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "relationship_status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "administrator_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    member_key = models.CharField(max_length=512, blank=True, default="")
    # The administrator's detector. NULL = not observed.
    detector_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The member account. NULL = not observed.
    account_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # AWS's relationship status (Enabled, Invited, Disabled, ...). NULL = not observed.
    relationship_status = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The account that administers the member. NULL = not observed.
    administrator_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_guardduty_member"

    def get_name(self) -> str:
        return self.name or self.member_key

    def __str__(self) -> str:
        return self.get_name()
