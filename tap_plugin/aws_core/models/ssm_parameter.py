"""SSM Parameter — an AWS Systems Manager Parameter Store parameter."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class SsmParameter(BaseModel):
    """An AWS Systems Manager Parameter Store parameter."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ssm_parameter"
    ENTITY_NAME: ClassVar[str] = "SSM Parameter"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Systems Manager Parameter Store parameter."
    ENTITY_ICON: ClassVar[str] = "aws-ssm"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The parameter's ARN: a parameter name is unique only
    # within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("parameter_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "parameter_arn": {"type": "string"},
        "type": {"type": "string"},
        "tier": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "parameter_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "type": {"validation": "jsonschema", "schema": {"type": "string"}},
        "tier": {"validation": "jsonschema", "schema": {"type": "string"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    parameter_arn = models.CharField(max_length=512, blank=True, default="")
    type = models.CharField(max_length=32, blank=True, default="")
    tier = models.CharField(max_length=32, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ssm_parameter"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
