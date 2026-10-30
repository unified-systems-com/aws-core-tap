"""KMS Alias — a friendly name for an AWS KMS key."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class KmsAlias(BaseModel):
    """An AWS KMS alias: a name that points at one KMS key. Policies and applications refer to keys through aliases, so an alias that is repointed silently changes which key they use."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_kms_alias"
    ENTITY_NAME: ClassVar[str] = "KMS Alias"
    ENTITY_DESCRIPTION: ClassVar[str] = "A friendly name for an AWS KMS key."
    ENTITY_ICON: ClassVar[str] = "aws-kms"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The alias's ARN: an alias name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("alias_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "alias_arn": {"type": "string"},
        "alias_name": {"type": "string"},
        "target_key_id": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "alias_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "alias_name": {"validation": "jsonschema", "schema": {"type": "string"}},
        "target_key_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    alias_arn = models.CharField(max_length=512, blank=True, default="")
    # The alias as AWS names it, including the alias/ prefix.
    alias_name = models.CharField(max_length=512, blank=True, default="")
    # The id of the key the alias points at. NULL = not observed.
    target_key_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_kms_alias"

    def get_name(self) -> str:
        return self.name or self.alias_arn

    def __str__(self) -> str:
        return self.get_name()
