"""Lambda Function — an AWS Lambda serverless function."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class LambdaFunction(BaseModel):
    """An AWS Lambda serverless function."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_lambda"
    ENTITY_NAME: ClassVar[str] = "Lambda Function"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Lambda serverless function."
    ENTITY_ICON: ClassVar[str] = "aws-lambda"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The function's ARN, the boto3 collector's identity for
    # it.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("function_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F9D7B7", "border": "#ED7100", "label": "#421F00"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "function_arn": {"type": "string"},
        "runtime": {"type": "string"},
        "handler": {"type": "string"},
        "memory_size": {"type": ["integer", "null"]},
        "timeout": {"type": ["integer", "null"]},
        "vpc_subnet_ids": {"type": ["array", "null"], "items": {"type": "string", "minLength": 1}},
        "vpc_security_group_ids": {"type": ["array", "null"], "items": {"type": "string", "minLength": 1}},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "function_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "runtime": {"validation": "jsonschema", "schema": {"type": "string"}},
        "handler": {"validation": "jsonschema", "schema": {"type": "string"}},
        "memory_size": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "timeout": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "vpc_subnet_ids": {"validation": "jsonschema", "schema": {"type": ["array", "null"], "items": {"type": "string", "minLength": 1}}},
        "vpc_security_group_ids": {"validation": "jsonschema", "schema": {"type": ["array", "null"], "items": {"type": "string", "minLength": 1}}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    function_arn = models.CharField(max_length=512, blank=True, default="")
    runtime = models.CharField(max_length=64, blank=True, default="")
    handler = models.CharField(max_length=255, blank=True, default="")
    memory_size = models.IntegerField(blank=True, null=True)
    timeout = models.IntegerField(blank=True, null=True)
    # VPC attachment, from ListFunctions VpcConfig.SubnetIds / SecurityGroupIds.
    # Typed fields because this type's configuration is not stored (its
    # environment variables routinely hold credentials), and without them the
    # VPC attachment, a network-exposure fact, would be lost. Null means not
    # observed; both [] means observed and not in a VPC (the collector writes []
    # when VpcConfig is absent).
    vpc_subnet_ids = models.JSONField(null=True, blank=True, default=None)
    vpc_security_group_ids = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_lambda"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
