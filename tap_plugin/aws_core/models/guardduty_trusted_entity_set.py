"""AWS GuardDuty Trusted Entity Set — an AWS GuardDuty Trusted Entity Set."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class GuarddutyTrustedEntitySet(BaseModel):
    """An AWS GuardDuty Trusted Entity Set, listed by ListDetectors, ListTrustedEntitySets and GetTrustedEntitySet. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_guardduty_trusted_entity_set"
    ENTITY_NAME: ClassVar[str] = "AWS GuardDuty Trusted Entity Set"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS GuardDuty Trusted Entity Set."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN, built from the listing's name by the entry's derive template (the listing carries none): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("guardduty_trusted_entity_set_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "guardduty:trustedentityset"

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "guardduty_trusted_entity_set_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    guardduty_trusted_entity_set_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_guardduty_trusted_entity_set"

    def get_name(self) -> str:
        return self.name or self.guardduty_trusted_entity_set_arn

    def __str__(self) -> str:
        return self.get_name()
