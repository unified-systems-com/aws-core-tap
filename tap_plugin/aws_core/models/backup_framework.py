"""Backup Framework — an AWS Backup audit framework."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class BackupFramework(BaseModel):
    """An AWS Backup audit framework: a set of controls that report whether the account's backups meet a stated policy."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_backup_framework"
    ENTITY_NAME: ClassVar[str] = "Backup Framework"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Backup audit framework."
    ENTITY_ICON: ClassVar[str] = "aws-s3"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The framework's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("framework_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#D9E4BD", "border": "#7AA116", "label": "#222D06"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "framework_arn": {"type": "string"},
        "deployment_status": {"type": ["string", "null"]},
        "number_of_controls": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "framework_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "deployment_status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "number_of_controls": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    framework_arn = models.CharField(max_length=512, blank=True, default="")
    # AWS's deployment status. NULL = not observed.
    deployment_status = models.CharField(max_length=512, blank=True, null=True, default=None)
    # How many controls the framework has. NULL = not observed.
    number_of_controls = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_backup_framework"

    def get_name(self) -> str:
        return self.name or self.framework_arn

    def __str__(self) -> str:
        return self.get_name()
