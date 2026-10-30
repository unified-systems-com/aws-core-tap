"""Backup Legal Hold — an AWS Backup legal hold."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class BackupLegalHold(BaseModel):
    """An AWS Backup legal hold: recovery points that match it cannot be deleted until the hold is cancelled."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_backup_legal_hold"
    ENTITY_NAME: ClassVar[str] = "Backup Legal Hold"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Backup legal hold."
    ENTITY_ICON: ClassVar[str] = "aws-s3"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The legal hold's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("hold_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#D9E4BD", "border": "#7AA116", "label": "#222D06"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "hold_arn": {"type": "string"},
        "hold_id": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "hold_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "hold_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    hold_arn = models.CharField(max_length=512, blank=True, default="")
    # AWS's legal hold id. NULL = not observed.
    hold_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # AWS's status (ACTIVE, CANCELED, ...). NULL = not observed.
    status = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_backup_legal_hold"

    def get_name(self) -> str:
        return self.name or self.hold_arn

    def __str__(self) -> str:
        return self.get_name()
