"""Identity Center Application — an application registered with IAM Identity Center."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class IdentityCenterApplication(BaseModel):
    """An IAM Identity Center application: a SaaS or custom application users sign in to through Identity Center. Its assignments decide who can reach it."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_identity_center_application"
    ENTITY_NAME: ClassVar[str] = "Identity Center Application"
    ENTITY_DESCRIPTION: ClassVar[str] = "An application registered with IAM Identity Center."
    ENTITY_ICON: ClassVar[str] = "aws-identity-center"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The application's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("application_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "ellipse", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "application_arn": {"type": "string"},
        "instance_arn": {"type": ["string", "null"]},
        "provider_arn": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "application_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "instance_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "provider_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    application_arn = models.CharField(max_length=512, blank=True, default="")
    # The Identity Center instance the application is registered in. NULL = not observed.
    instance_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The application provider (the SaaS or custom application type). NULL = not observed.
    provider_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # ENABLED or DISABLED. NULL = not observed.
    status = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_identity_center_application"

    def get_name(self) -> str:
        return self.name or self.application_arn

    def __str__(self) -> str:
        return self.get_name()
