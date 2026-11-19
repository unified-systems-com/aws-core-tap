"""AWS OpenSearch Data Source — an AWS OpenSearch Data Source."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class OpensearchDataSource(BaseModel):
    """An AWS OpenSearch Data Source, read by ListDataSources. Only its identity, name and tags are collected; the rest of the response is not stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_opensearch_data_source"
    ENTITY_NAME: ClassVar[str] = "AWS OpenSearch Data Source"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS OpenSearch Data Source."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): (account, region, domain name, data source name). ListDataSources returns
    # no ARN and the Service Authorization Reference defines no resource type for a domain's data source, so none is
    # built (aws-core-tap#251); the key is CloudFormation's additional identifier (DomainName, Name) scoped by the
    # account and region the data source was collected in.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("account_id", "region", "domain_name", "data_source_name")

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "account_id": {"type": "string", "pattern": "^([0-9]{12})?$"},
        "region": {"type": "string"},
        "domain_name": {"type": "string"},
        "data_source_name": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    account_id = models.CharField(max_length=12, blank=True, default="")
    region = models.CharField(max_length=32, blank=True, default="")
    domain_name = models.CharField(max_length=255, blank=True, default="")
    data_source_name = models.CharField(max_length=255, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_opensearch_data_source"

    def get_name(self) -> str:
        return self.name or self.data_source_name

    def __str__(self) -> str:
        return self.get_name()
