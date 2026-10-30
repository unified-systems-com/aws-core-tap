"""Lambda Layer Version — a version of an AWS Lambda layer."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class LambdaLayerVersion(BaseModel):
    """A version of an AWS Lambda layer: shared code a function loads at start. A layer is code that runs inside every function that uses it, so who can publish and use a version matters."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_lambda_layer_version"
    ENTITY_NAME: ClassVar[str] = "Lambda Layer Version"
    ENTITY_DESCRIPTION: ClassVar[str] = "A version of an AWS Lambda layer."
    ENTITY_ICON: ClassVar[str] = "aws-lambda"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The layer version's ARN: a layer name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("layer_version_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F9D7B7", "border": "#ED7100", "label": "#421F00"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "layer_version_arn": {"type": "string"},
        "layer_arn": {"type": ["string", "null"]},
        "version": {"type": ["integer", "null"]},
        "compatible_runtimes": {"type": ["array", "null"]},
        "created_date": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "layer_version_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "layer_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "version": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "compatible_runtimes": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "created_date": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    layer_version_arn = models.CharField(max_length=512, blank=True, default="")
    # The layer the version belongs to. NULL = not observed.
    layer_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The version number. NULL = not observed.
    version = models.IntegerField(null=True, blank=True, default=None)
    # Runtimes the version supports. NULL = not observed.
    compatible_runtimes = models.JSONField(null=True, blank=True, default=None)
    # When the version was published (ISO 8601). NULL = not observed.
    created_date = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_lambda_layer_version"

    def get_name(self) -> str:
        return self.name or self.layer_version_arn

    def __str__(self) -> str:
        return self.get_name()
