"""Lambda Code Signing Config — an AWS Lambda code signing configuration."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class LambdaCodeSigningConfig(BaseModel):
    """An AWS Lambda code signing configuration: the signing profiles whose code a function may deploy, and what happens to unsigned code. Warn lets unsigned code through; Enforce blocks it."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_lambda_code_signing_config"
    ENTITY_NAME: ClassVar[str] = "Lambda Code Signing Config"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Lambda code signing configuration."
    ENTITY_ICON: ClassVar[str] = "aws-lambda"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The configuration's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("code_signing_config_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F9D7B7", "border": "#ED7100", "label": "#421F00"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "code_signing_config_arn": {"type": "string"},
        "untrusted_artifact_on_deployment": {"type": ["string", "null"]},
        "signing_profile_version_arns": {"type": ["array", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "code_signing_config_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "untrusted_artifact_on_deployment": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "signing_profile_version_arns": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    code_signing_config_arn = models.CharField(max_length=512, blank=True, default="")
    # Warn or Enforce. NULL = not observed.
    untrusted_artifact_on_deployment = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Signing profile versions whose code is allowed. NULL = not observed.
    signing_profile_version_arns = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_lambda_code_signing_config"

    def get_name(self) -> str:
        return self.name or self.code_signing_config_arn

    def __str__(self) -> str:
        return self.get_name()
