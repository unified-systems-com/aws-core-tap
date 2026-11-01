"""AWS VerifiedPermissions Policy Template — an AWS VerifiedPermissions Policy Template."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class VerifiedpermissionsPolicyTemplate(BaseModel):
    """An AWS VerifiedPermissions Policy Template, read by ListPolicyTemplates. Only its identity, name and tags are collected; the rest of the response is not stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_verifiedpermissions_policy_template"
    ENTITY_NAME: ClassVar[str] = "AWS VerifiedPermissions Policy Template"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS VerifiedPermissions Policy Template."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The policy store id and the template id (PolicyStoreId and PolicyTemplateId, the CloudFormation primary identifier): AWS gives a template no ARN, and a policy store id is unique to its store.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("verifiedpermissions_policy_template_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "verifiedpermissions_policy_template_key": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    verifiedpermissions_policy_template_key = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_verifiedpermissions_policy_template"

    def get_name(self) -> str:
        return self.name or self.verifiedpermissions_policy_template_key

    def __str__(self) -> str:
        return self.get_name()
