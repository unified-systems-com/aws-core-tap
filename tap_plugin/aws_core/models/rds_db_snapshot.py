"""RDS DB Snapshot — an Amazon RDS DB instance snapshot."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class RdsDbSnapshot(BaseModel):
    """A snapshot of an RDS DB instance: a copy of the database. A manual snapshot shared with 'all' is public, readable by every AWS account."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_rds_db_snapshot"
    ENTITY_NAME: ClassVar[str] = "RDS DB Snapshot"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon RDS DB instance snapshot."
    ENTITY_ICON: ClassVar[str] = "aws-rds"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The snapshot's ARN: a snapshot identifier is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("db_snapshot_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "db_snapshot_arn": {"type": "string"},
        "db_instance_identifier": {"type": ["string", "null"]},
        "engine": {"type": ["string", "null"]},
        "snapshot_type": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "encrypted": {"type": ["boolean", "null"]},
        "is_public": {"type": ["boolean", "null"]},
        "created_at": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    db_snapshot_arn = models.CharField(max_length=2048, blank=True, default="")
    # The instance the snapshot was taken of. NULL = not observed.
    db_instance_identifier = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # The database engine. NULL = not observed.
    engine = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # manual, automated, shared, public, awsbackup, ... NULL = not observed.
    snapshot_type = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # AWS's snapshot status. NULL = not observed.
    status = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # Whether the snapshot is encrypted. NULL = not observed.
    encrypted = models.BooleanField(null=True, blank=True, default=None)
    # Whether a manual snapshot is shared with everyone (restore attribute 'all'). NULL = not observed.
    is_public = models.BooleanField(null=True, blank=True, default=None)
    # When the snapshot was taken (ISO 8601 UTC). NULL = not observed.
    created_at = models.CharField(max_length=2048, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_rds_db_snapshot"

    def get_name(self) -> str:
        return self.name or self.db_snapshot_arn

    def __str__(self) -> str:
        return self.get_name()
