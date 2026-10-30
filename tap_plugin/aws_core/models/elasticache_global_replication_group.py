"""AWS ElastiCache Global Replication Group — an AWS ElastiCache Global Replication Group."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ElasticacheGlobalReplicationGroup(BaseModel):
    """An AWS ElastiCache Global Replication Group, listed by DescribeGlobalReplicationGroups. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_elasticache_global_replication_group"
    ENTITY_NAME: ClassVar[str] = "AWS ElastiCache Global Replication Group"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS ElastiCache Global Replication Group."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (ARN): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("elasticache_global_replication_group_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "elasticache_global_replication_group_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    elasticache_global_replication_group_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_elasticache_global_replication_group"

    def get_name(self) -> str:
        return self.name or self.elasticache_global_replication_group_arn

    def __str__(self) -> str:
        return self.get_name()
