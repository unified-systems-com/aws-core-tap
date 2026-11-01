"""AWS ResilienceHubV2 Service Function — an AWS ResilienceHubV2 Service Function."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Resiliencehubv2ServiceFunction(BaseModel):
    """An AWS ResilienceHubV2 Service Function, read by ListServiceFunctions. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_resiliencehubv2_service_function"
    ENTITY_NAME: ClassVar[str] = "AWS ResilienceHubV2 Service Function"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS ResilienceHubV2 Service Function."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): the CloudFormation primary identifier of AWS::ResilienceHubV2::ServiceFunction, ServiceArn and ServiceFunctionId joined with '|': a function id is scoped to its service and the item carries no ARN of its own
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("resiliencehubv2_service_function_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "resiliencehubv2_service_function_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    resiliencehubv2_service_function_id = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_resiliencehubv2_service_function"

    def get_name(self) -> str:
        return self.name or self.resiliencehubv2_service_function_id

    def __str__(self) -> str:
        return self.get_name()
