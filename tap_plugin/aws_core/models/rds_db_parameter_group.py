"""RDS DB Parameter Group — an Amazon RDS or Neptune DB parameter group."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class RdsDbParameterGroup(BaseModel):
    """A DB parameter group: engine settings applied to instances, such as whether connections must use TLS. Only its identity and family are collected, not the parameters."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_rds_db_parameter_group"
    ENTITY_NAME: ClassVar[str] = "RDS DB Parameter Group"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon RDS or Neptune DB parameter group."
    ENTITY_ICON: ClassVar[str] = "aws-rds"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The parameter group's ARN: a name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("db_parameter_group_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "db_parameter_group_arn": {"type": "string"},
        "family": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    db_parameter_group_arn = models.CharField(max_length=2048, blank=True, default="")
    # The engine family (postgres16, mysql8.0, ...). NULL = not observed.
    family = models.CharField(max_length=2048, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_rds_db_parameter_group"

    def get_name(self) -> str:
        return self.name or self.db_parameter_group_arn

    def __str__(self) -> str:
        return self.get_name()
