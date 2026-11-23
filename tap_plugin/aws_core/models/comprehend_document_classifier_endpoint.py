"""AWS Comprehend Document Classifier Endpoint — an AWS Comprehend Document Classifier Endpoint."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class ComprehendDocumentClassifierEndpoint(BaseModel):
    """An AWS Comprehend Document Classifier Endpoint, listed by ListEndpoints. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_comprehend_document_classifier_endpoint"
    ENTITY_NAME: ClassVar[str] = "AWS Comprehend Document Classifier Endpoint"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Comprehend Document Classifier Endpoint."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (EndpointArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("comprehend_document_classifier_endpoint_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "comprehend:document-classifier-endpoint"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): when AWS created it (ListEndpoints
    # EndpointPropertiesList[].CreationTime, a botocore timestamp), read from configuration['CreationTime'], where the
    # collector stores it as AWS sent it. AWS states no end for it.
    EVENT_TIME: ClassVar[Interval] = Interval(start="configuration", kind="created", member="CreationTime")

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "comprehend_document_classifier_endpoint_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    comprehend_document_classifier_endpoint_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_comprehend_document_classifier_endpoint"

    def get_name(self) -> str:
        return self.name or self.comprehend_document_classifier_endpoint_arn

    def __str__(self) -> str:
        return self.get_name()
