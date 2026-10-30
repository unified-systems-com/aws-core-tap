"""AWS Config Stored Query — a saved AWS Config advanced query."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ConfigStoredQuery(BaseModel):
    """An AWS Config stored query: a saved advanced query. Only its identity is typed; the query text is operator-authored and is not collected."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_config_stored_query"
    ENTITY_NAME: ClassVar[str] = "AWS Config Stored Query"
    ENTITY_DESCRIPTION: ClassVar[str] = "A saved AWS Config advanced query."
    ENTITY_ICON: ClassVar[str] = "aws-config"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The stored query's ARN: a name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("query_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "query_arn": {"type": "string"},
        "query_id": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "query_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "query_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    query_arn = models.CharField(max_length=512, blank=True, default="")
    # AWS's query id. NULL = not observed.
    query_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_config_stored_query"

    def get_name(self) -> str:
        return self.name or self.query_arn

    def __str__(self) -> str:
        return self.get_name()
