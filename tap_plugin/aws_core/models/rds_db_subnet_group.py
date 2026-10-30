"""RDS DB Subnet Group — an Amazon RDS DB subnet group."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class RdsDbSubnetGroup(BaseModel):
    """A DB subnet group: the subnets a database may be placed in, which decides its network exposure."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_rds_db_subnet_group"
    ENTITY_NAME: ClassVar[str] = "RDS DB Subnet Group"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon RDS DB subnet group."
    ENTITY_ICON: ClassVar[str] = "aws-rds"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The subnet group's ARN: a name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("db_subnet_group_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "db_subnet_group_arn": {"type": "string"},
        "vpc_id": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "subnet_ids": {"type": ["array", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    db_subnet_group_arn = models.CharField(max_length=2048, blank=True, default="")
    # The VPC the subnets are in. NULL = not observed.
    vpc_id = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # AWS's status (Complete, ...). NULL = not observed.
    status = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # The subnets in the group. NULL = not observed.
    subnet_ids = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_rds_db_subnet_group"

    def get_name(self) -> str:
        return self.name or self.db_subnet_group_arn

    def __str__(self) -> str:
        return self.get_name()
