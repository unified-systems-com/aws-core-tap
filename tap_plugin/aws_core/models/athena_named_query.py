"""AWS Athena Named Query — an AWS Athena Named Query."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AthenaNamedQuery(BaseModel):
    """An AWS Athena Named Query, listed by ListWorkGroups, ListNamedQueries and GetNamedQuery. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_athena_named_query"
    ENTITY_NAME: ClassVar[str] = "AWS Athena Named Query"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Athena Named Query."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The named query's id (NamedQueryId), the CloudFormation primary identifier of the type; the AWS Service Authorization Reference lists no ARN for it. Unique within the account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("athena_named_query_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "athena_named_query_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    athena_named_query_id = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_athena_named_query"

    def get_name(self) -> str:
        return self.name or self.athena_named_query_id

    def __str__(self) -> str:
        return self.get_name()
