"""AWS Pinpoint Campaign — an AWS Pinpoint Campaign."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class PinpointCampaign(BaseModel):
    """An AWS Pinpoint Campaign, listed by GetCampaigns. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_pinpoint_campaign"
    ENTITY_NAME: ClassVar[str] = "AWS Pinpoint Campaign"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Pinpoint Campaign."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (Arn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("pinpoint_campaign_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "mobiletargeting:campaign"

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "pinpoint_campaign_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    pinpoint_campaign_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_pinpoint_campaign"

    def get_name(self) -> str:
        return self.name or self.pinpoint_campaign_arn

    def __str__(self) -> str:
        return self.get_name()
