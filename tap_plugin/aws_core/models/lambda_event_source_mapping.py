"""Lambda Event Source Mapping — an AWS Lambda event source mapping."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class LambdaEventSourceMapping(BaseModel):
    """An AWS Lambda event source mapping: Lambda polling a queue, stream or broker and invoking a function with what it finds. It is how data from a source reaches code."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_lambda_event_source_mapping"
    ENTITY_NAME: ClassVar[str] = "Lambda Event Source Mapping"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Lambda event source mapping."
    ENTITY_ICON: ClassVar[str] = "aws-lambda"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The mapping's ARN (AWS's, or built from the function ARN and the mapping UUID).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("mapping_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F9D7B7", "border": "#ED7100", "label": "#421F00"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "mapping_arn": {"type": "string"},
        "uuid": {"type": ["string", "null"]},
        "state": {"type": ["string", "null"]},
        "event_source_arn": {"type": ["string", "null"]},
        "function_arn": {"type": ["string", "null"]},
        "batch_size": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "mapping_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "uuid": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "state": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "event_source_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "function_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "batch_size": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    mapping_arn = models.CharField(max_length=512, blank=True, default="")
    # AWS's mapping id. NULL = not observed.
    uuid = models.CharField(max_length=512, blank=True, null=True, default=None)
    # AWS's mapping state (Enabled, Disabled, Creating, ...). NULL = not observed.
    state = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The queue, stream or broker the mapping reads. NULL = not observed (a self-managed source has none).
    event_source_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The function the mapping invokes. NULL = not observed.
    function_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Records per invocation. NULL = not observed.
    batch_size = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_lambda_event_source_mapping"

    def get_name(self) -> str:
        return self.name or self.mapping_arn

    def __str__(self) -> str:
        return self.get_name()
