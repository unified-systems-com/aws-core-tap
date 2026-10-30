"""RDS DB Cluster — an Amazon RDS, Aurora, DocumentDB or Neptune DB cluster."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class RdsDbCluster(BaseModel):
    """A DB cluster of Amazon RDS (Aurora and Multi-AZ clusters), Amazon DocumentDB or Amazon Neptune, which share the RDS control plane. Its exposure facts are public reachability, encryption, backups and deletion protection."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_rds_db_cluster"
    ENTITY_NAME: ClassVar[str] = "RDS DB Cluster"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon RDS, Aurora, DocumentDB or Neptune DB cluster."
    ENTITY_ICON: ClassVar[str] = "aws-rds"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The cluster's ARN: a cluster identifier is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("db_cluster_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "db_cluster_arn": {"type": "string"},
        "engine": {"type": ["string", "null"]},
        "engine_version": {"type": ["string", "null"]},
        "engine_mode": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "storage_encrypted": {"type": ["boolean", "null"]},
        "iam_database_auth_enabled": {"type": ["boolean", "null"]},
        "deletion_protection": {"type": ["boolean", "null"]},
        "publicly_accessible": {"type": ["boolean", "null"]},
        "backup_retention_days": {"type": ["integer", "null"]},
        "multi_az": {"type": ["boolean", "null"]},
        "global_cluster_identifier": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    db_cluster_arn = models.CharField(max_length=2048, blank=True, default="")
    # aurora-mysql, aurora-postgresql, docdb, neptune, mysql, postgres, ... NULL = not observed.
    engine = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # The engine version. NULL = not observed.
    engine_version = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # provisioned, serverless, parallelquery, global or multimaster. NULL = not observed.
    engine_mode = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # AWS's cluster status. NULL = not observed.
    status = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # Whether storage is encrypted. NULL = not observed.
    storage_encrypted = models.BooleanField(null=True, blank=True, default=None)
    # Whether IAM database authentication is on. NULL = not observed.
    iam_database_auth_enabled = models.BooleanField(null=True, blank=True, default=None)
    # Whether deletion protection is on. NULL = not observed.
    deletion_protection = models.BooleanField(null=True, blank=True, default=None)
    # Whether the cluster has a public endpoint. NULL = not observed.
    publicly_accessible = models.BooleanField(null=True, blank=True, default=None)
    # Automated backup retention in days. NULL = not observed.
    backup_retention_days = models.IntegerField(null=True, blank=True, default=None)
    # Whether the cluster spans several availability zones. NULL = not observed.
    multi_az = models.BooleanField(null=True, blank=True, default=None)
    # The global cluster the cluster belongs to. NULL = none, or not observed.
    global_cluster_identifier = models.CharField(max_length=2048, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_rds_db_cluster"

    def get_name(self) -> str:
        return self.name or self.db_cluster_arn

    def __str__(self) -> str:
        return self.get_name()
