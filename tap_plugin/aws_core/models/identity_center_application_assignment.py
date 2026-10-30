"""Identity Center Application Assignment — a user or group assigned to an IAM Identity Center application."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class IdentityCenterApplicationAssignment(BaseModel):
    """An IAM Identity Center application assignment: one user or group that may sign in to one application."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_identity_center_application_assignment"
    ENTITY_NAME: ClassVar[str] = "Identity Center Application Assignment"
    ENTITY_DESCRIPTION: ClassVar[str] = "A user or group assigned to an IAM Identity Center application."
    ENTITY_ICON: ClassVar[str] = "aws-identity-center"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The application, principal type and principal id together (application_arn|principal_type|principal_id): an assignment has no ARN of its own.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("assignment_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "ellipse", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "assignment_key": {"type": "string"},
        "application_arn": {"type": "string"},
        "principal_type": {"type": ["string", "null"]},
        "principal_id": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "assignment_key": {"validation": "jsonschema", "schema": {"type": "string"}},
        "application_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "principal_type": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "principal_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    assignment_key = models.CharField(max_length=2048, blank=True, default="")
    # The application the principal is assigned to.
    application_arn = models.CharField(max_length=2048, blank=True, default="")
    # USER or GROUP. NULL = not observed.
    principal_type = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The user or group id in the identity store. NULL = not observed.
    principal_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_identity_center_application_assignment"

    def get_name(self) -> str:
        return self.name or self.assignment_key

    def __str__(self) -> str:
        return self.get_name()
