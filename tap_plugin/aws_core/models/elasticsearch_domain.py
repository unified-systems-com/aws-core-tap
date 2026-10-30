"""Elasticsearch Domain — an Amazon OpenSearch / Elasticsearch Service domain."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ElasticsearchDomain(BaseModel):
    """An Amazon OpenSearch (Elasticsearch) Service domain."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_elasticsearch_domain"
    ENTITY_NAME: ClassVar[str] = "Elasticsearch Domain"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon OpenSearch / Elasticsearch Service domain."
    ENTITY_ICON: ClassVar[str] = "aws-elasticsearch"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The domain's ARN: a domain name is unique only within an
    # account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("domain_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "domain_arn": {"type": "string"},
        "engine_version": {"type": "string"},
        "node_type": {"type": "string"},
        "instance_count": {"type": ["integer", "null"]},
        "encrypted": {"type": "boolean"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "domain_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "engine_version": {"validation": "jsonschema", "schema": {"type": "string"}},
        "node_type": {"validation": "jsonschema", "schema": {"type": "string"}},
        "instance_count": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "encrypted": {"validation": "jsonschema", "schema": {"type": "boolean"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    domain_arn = models.CharField(max_length=512, blank=True, default="")
    engine_version = models.CharField(max_length=64, blank=True, default="")
    node_type = models.CharField(max_length=64, blank=True, default="")
    instance_count = models.IntegerField(blank=True, null=True)
    encrypted = models.BooleanField(default=False)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_elasticsearch_domain"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
