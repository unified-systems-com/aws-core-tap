"""AWS Config Organization Conformance Pack — an AWS Config conformance pack deployed to the accounts of an organization."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ConfigOrganizationConformancePack(BaseModel):
    """An AWS Config organization conformance pack: a bundle of rules and remediations deployed to every member account. Read only from the organization's management or delegated administrator account."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_config_organization_conformance_pack"
    ENTITY_NAME: ClassVar[str] = "AWS Config Organization Conformance Pack"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Config conformance pack deployed to the accounts of an organization."
    ENTITY_ICON: ClassVar[str] = "aws-config"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The organization conformance pack's ARN: a name is unique only within the organization.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("pack_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "pack_arn": {"type": "string"},
        "excluded_accounts": {"type": ["array", "null"]},
        "delivery_s3_bucket": {"type": ["string", "null"]},
        "last_update_time": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "pack_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "excluded_accounts": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "delivery_s3_bucket": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "last_update_time": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    pack_arn = models.CharField(max_length=512, blank=True, default="")
    # Account ids the pack is not deployed to. NULL = not observed; [] = observed, none excluded.
    excluded_accounts = models.JSONField(null=True, blank=True, default=None)
    # The bucket the pack's deployment details are delivered to. NULL = not observed.
    delivery_s3_bucket = models.CharField(max_length=512, blank=True, null=True, default=None)
    # When the pack was last changed (ISO 8601 UTC). NULL = not observed.
    last_update_time = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_config_organization_conformance_pack"

    def get_name(self) -> str:
        return self.name or self.pack_arn

    def __str__(self) -> str:
        return self.get_name()
