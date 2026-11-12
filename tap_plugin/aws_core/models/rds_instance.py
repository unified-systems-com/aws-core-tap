"""RDS Instance — an Amazon Relational Database Service instance."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class RdsInstance(BaseModel):
    """An Amazon RDS database instance."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_rds_instance"
    ENTITY_NAME: ClassVar[str] = "RDS Instance"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon RDS database instance."
    ENTITY_ICON: ClassVar[str] = "aws-rds"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The DB instance's ARN: db_instance_id is chosen by its
    # owner and unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("db_instance_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "rds:db"
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "db_instance_id": {"type": ["string", "null"]},
        "db_instance_arn": {"type": "string"},
        "engine": {"type": ["string", "null"]},
        "engine_version": {"type": ["string", "null"]},
        "instance_class": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "multi_az": {"type": ["boolean", "null"]},
        "encrypted": {"type": ["boolean", "null"]},
        "publicly_accessible": {"type": ["boolean", "null"]},
        "deletion_protection": {"type": ["boolean", "null"]},
        "iam_database_auth_enabled": {"type": ["boolean", "null"]},
        "backup_retention_days": {"type": ["integer", "null"]},
        "endpoint_address": {"type": ["string", "null"]},
        "endpoint_port": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "db_instance_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "db_instance_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "engine": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "engine_version": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "instance_class": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "multi_az": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "encrypted": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "publicly_accessible": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "deletion_protection": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "iam_database_auth_enabled": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "backup_retention_days": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "endpoint_address": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "endpoint_port": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    db_instance_id = models.CharField(max_length=255, db_index=True, null=True, blank=True, default=None)
    # The DB instance's ARN (DBInstanceArn), its identity across accounts and regions. Blank until observed.
    db_instance_arn = models.CharField(max_length=512, blank=True, default="", db_index=True)
    engine = models.CharField(max_length=64, null=True, blank=True, default=None)
    engine_version = models.CharField(max_length=64, null=True, blank=True, default=None)
    instance_class = models.CharField(max_length=64, null=True, blank=True, default=None)
    status = models.CharField(max_length=64, null=True, blank=True, default=None)
    multi_az = models.BooleanField(null=True, blank=True, default=None)
    encrypted = models.BooleanField(null=True, blank=True, default=None)
    # Whether the instance has a public endpoint (PubliclyAccessible). NULL = not observed.
    publicly_accessible = models.BooleanField(null=True, blank=True, default=None)
    # Whether deletion protection is on (DeletionProtection). NULL = not observed.
    deletion_protection = models.BooleanField(null=True, blank=True, default=None)
    # Whether IAM database authentication is on (IAMDatabaseAuthenticationEnabled). NULL = not observed.
    iam_database_auth_enabled = models.BooleanField(null=True, blank=True, default=None)
    # Automated backup retention in days (BackupRetentionPeriod); 0 means automated backups are off. NULL = not observed.
    backup_retention_days = models.IntegerField(null=True, blank=True, default=None)
    # The DNS name clients connect to (Endpoint.Address). NULL = not observed, or the instance has no endpoint yet.
    endpoint_address = models.CharField(max_length=2048, null=True, blank=True, default=None)
    # The port the instance listens on (Endpoint.Port). NULL = not observed, or the instance has no endpoint yet.
    endpoint_port = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_rds_instance"

    def get_name(self) -> str:
        return self.name or self.db_instance_id

    def __str__(self) -> str:
        return self.get_name()
