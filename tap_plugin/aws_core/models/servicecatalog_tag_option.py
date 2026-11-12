"""AWS Service Catalog Tag Option — an AWS Service Catalog Tag Option."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ServicecatalogTagOption(BaseModel):
    """An AWS Service Catalog Tag Option, listed by ListTagOptions. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_servicecatalog_tag_option"
    ENTITY_NAME: ClassVar[str] = "AWS Service Catalog Tag Option"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Service Catalog Tag Option."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The tag option's Id: ListTagOptions returns no ARN, and a tag option id is service-generated.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("servicecatalog_tag_option_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "servicecatalog_tag_option_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    servicecatalog_tag_option_id = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_servicecatalog_tag_option"

    def get_name(self) -> str:
        return self.name or self.servicecatalog_tag_option_id

    def __str__(self) -> str:
        return self.get_name()
