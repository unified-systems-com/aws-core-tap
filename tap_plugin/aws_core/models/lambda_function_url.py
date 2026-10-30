"""Lambda Function URL — an AWS Lambda function URL."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class LambdaFunctionUrl(BaseModel):
    """An AWS Lambda function URL: an HTTPS endpoint that invokes a function directly. With AuthType NONE it is callable by anyone on the internet."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_lambda_function_url"
    ENTITY_NAME: ClassVar[str] = "Lambda Function URL"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Lambda function URL."
    ENTITY_ICON: ClassVar[str] = "aws-lambda"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The URL itself: it is unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("function_url",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F9D7B7", "border": "#ED7100", "label": "#421F00"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "function_url": {"type": "string"},
        "function_arn": {"type": ["string", "null"]},
        "auth_type": {"type": ["string", "null"]},
        "invoke_mode": {"type": ["string", "null"]},
        "cors_allow_origins": {"type": ["array", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "function_url": {"validation": "jsonschema", "schema": {"type": "string"}},
        "function_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "auth_type": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "invoke_mode": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "cors_allow_origins": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    function_url = models.CharField(max_length=512, blank=True, default="")
    # The function the URL invokes. NULL = not observed.
    function_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # NONE (open to the internet) or AWS_IAM. NULL = not observed.
    auth_type = models.CharField(max_length=512, blank=True, null=True, default=None)
    # BUFFERED or RESPONSE_STREAM. NULL = not observed.
    invoke_mode = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Origins the URL's CORS configuration allows (['*'] allows any). NULL = not observed.
    cors_allow_origins = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_lambda_function_url"

    def get_name(self) -> str:
        return self.name or self.function_url

    def __str__(self) -> str:
        return self.get_name()
