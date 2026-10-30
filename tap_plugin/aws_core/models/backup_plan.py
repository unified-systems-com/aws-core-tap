"""Backup Plan — an AWS Backup plan."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class BackupPlan(BaseModel):
    """An AWS Backup plan: schedules and lifecycle rules that say what is backed up, how often and where it is written."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_backup_plan"
    ENTITY_NAME: ClassVar[str] = "Backup Plan"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Backup plan."
    ENTITY_ICON: ClassVar[str] = "aws-s3"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The plan's ARN: a plan id is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("plan_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#D9E4BD", "border": "#7AA116", "label": "#222D06"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "plan_arn": {"type": "string"},
        "plan_id": {"type": ["string", "null"]},
        "rule_count": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "plan_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "plan_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "rule_count": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    plan_arn = models.CharField(max_length=512, blank=True, default="")
    # AWS's plan id. NULL = not observed.
    plan_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # How many rules the plan has. NULL = not observed.
    rule_count = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_backup_plan"

    def get_name(self) -> str:
        return self.name or self.plan_arn

    def __str__(self) -> str:
        return self.get_name()
