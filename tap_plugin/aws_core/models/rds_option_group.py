"""RDS Option Group — an Amazon RDS option group."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class RdsOptionGroup(BaseModel):
    """An RDS option group: engine features enabled for instances (native backup to S3, TDE, SSL for Oracle). Its options carry settings that can name resources."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_rds_option_group"
    ENTITY_NAME: ClassVar[str] = "RDS Option Group"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon RDS option group."
    ENTITY_ICON: ClassVar[str] = "aws-rds"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The option group's ARN: a name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("option_group_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "option_group_arn": {"type": "string"},
        "engine_name": {"type": ["string", "null"]},
        "major_engine_version": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    option_group_arn = models.CharField(max_length=2048, blank=True, default="")
    # The engine. NULL = not observed.
    engine_name = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # The major engine version. NULL = not observed.
    major_engine_version = models.CharField(max_length=2048, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_rds_option_group"

    def get_name(self) -> str:
        return self.name or self.option_group_arn

    def __str__(self) -> str:
        return self.get_name()
