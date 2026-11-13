"""AWS Service Catalog Service Action — an AWS Service Catalog Service Action."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ServicecatalogServiceAction(BaseModel):
    """An AWS Service Catalog Service Action, listed by ListServiceActions. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_servicecatalog_service_action"
    ENTITY_NAME: ClassVar[str] = "AWS Service Catalog Service Action"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Service Catalog Service Action."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The service action's Id: ListServiceActions returns no ARN, and a service action id is service-generated.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("servicecatalog_service_action_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "servicecatalog_service_action_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    servicecatalog_service_action_id = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_servicecatalog_service_action"

    def get_name(self) -> str:
        return self.name or self.servicecatalog_service_action_id

    def __str__(self) -> str:
        return self.get_name()
