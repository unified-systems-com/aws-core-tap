"""Backup Vault — an AWS Backup vault."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class BackupVault(BaseModel):
    """An AWS Backup vault: where recovery points are stored. Its key, lock and retention bounds decide whether backups survive an attacker with account access."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_backup_vault"
    ENTITY_NAME: ClassVar[str] = "Backup Vault"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Backup vault."
    ENTITY_ICON: ClassVar[str] = "aws-s3"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The vault's ARN: a vault name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("vault_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#D9E4BD", "border": "#7AA116", "label": "#222D06"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "vault_arn": {"type": "string"},
        "vault_state": {"type": ["string", "null"]},
        "encryption_key_arn": {"type": ["string", "null"]},
        "locked": {"type": ["boolean", "null"]},
        "min_retention_days": {"type": ["integer", "null"]},
        "max_retention_days": {"type": ["integer", "null"]},
        "number_of_recovery_points": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "vault_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "vault_state": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "encryption_key_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "locked": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "min_retention_days": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "max_retention_days": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "number_of_recovery_points": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    vault_arn = models.CharField(max_length=512, blank=True, default="")
    # AWS's vault state. NULL = not observed.
    vault_state = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The key that encrypts the vault. NULL = not observed.
    encryption_key_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Whether Vault Lock is enabled. NULL = not observed.
    locked = models.BooleanField(null=True, blank=True, default=None)
    # Vault Lock's minimum retention in days. NULL = none, or not observed.
    min_retention_days = models.IntegerField(null=True, blank=True, default=None)
    # Vault Lock's maximum retention in days. NULL = none, or not observed.
    max_retention_days = models.IntegerField(null=True, blank=True, default=None)
    # How many recovery points the vault holds. NULL = not observed.
    number_of_recovery_points = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_backup_vault"

    def get_name(self) -> str:
        return self.name or self.vault_arn

    def __str__(self) -> str:
        return self.get_name()
