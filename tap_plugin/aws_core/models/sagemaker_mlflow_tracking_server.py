"""AWS SageMaker Mlflow Tracking Server — an AWS SageMaker Mlflow Tracking Server."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class SagemakerMlflowTrackingServer(BaseModel):
    """An AWS SageMaker Mlflow Tracking Server, listed by ListMlflowTrackingServers. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_sagemaker_mlflow_tracking_server"
    ENTITY_NAME: ClassVar[str] = "AWS SageMaker Mlflow Tracking Server"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS SageMaker Mlflow Tracking Server."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (TrackingServerArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("sagemaker_mlflow_tracking_server_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "sagemaker:mlflow-tracking-server"

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "sagemaker_mlflow_tracking_server_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    sagemaker_mlflow_tracking_server_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_sagemaker_mlflow_tracking_server"

    def get_name(self) -> str:
        return self.name or self.sagemaker_mlflow_tracking_server_arn

    def __str__(self) -> str:
        return self.get_name()
