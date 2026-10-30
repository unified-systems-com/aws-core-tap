"""RDS Global Cluster — an Amazon Aurora or Neptune global cluster."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class RdsGlobalCluster(BaseModel):
    """An Aurora or Neptune global cluster: a database replicated across regions, whose members are the regional clusters."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_rds_global_cluster"
    ENTITY_NAME: ClassVar[str] = "RDS Global Cluster"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon Aurora or Neptune global cluster."
    ENTITY_ICON: ClassVar[str] = "aws-rds"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The global cluster's ARN: an identifier is unique only within an account.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("global_cluster_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "global_cluster_arn": {"type": "string"},
        "engine": {"type": ["string", "null"]},
        "engine_version": {"type": ["string", "null"]},
        "storage_encrypted": {"type": ["boolean", "null"]},
        "deletion_protection": {"type": ["boolean", "null"]},
        "status": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    global_cluster_arn = models.CharField(max_length=2048, blank=True, default="")
    # aurora-mysql, aurora-postgresql or neptune. NULL = not observed.
    engine = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # The engine version. NULL = not observed.
    engine_version = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # Whether storage is encrypted. NULL = not observed.
    storage_encrypted = models.BooleanField(null=True, blank=True, default=None)
    # Whether deletion protection is on. NULL = not observed.
    deletion_protection = models.BooleanField(null=True, blank=True, default=None)
    # AWS's status. NULL = not observed.
    status = models.CharField(max_length=2048, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_rds_global_cluster"

    def get_name(self) -> str:
        return self.name or self.global_cluster_arn

    def __str__(self) -> str:
        return self.get_name()
