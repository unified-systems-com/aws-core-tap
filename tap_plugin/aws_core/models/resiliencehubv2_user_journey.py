"""AWS ResilienceHubV2 User Journey — an AWS ResilienceHubV2 User Journey."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Resiliencehubv2UserJourney(BaseModel):
    """An AWS ResilienceHubV2 User Journey, read by ListUserJourneys. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_resiliencehubv2_user_journey"
    ENTITY_NAME: ClassVar[str] = "AWS ResilienceHubV2 User Journey"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS ResilienceHubV2 User Journey."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): the system's ARN and the userJourneyId joined with '|' (the CloudFormation primary identifier of AWS::ResilienceHubV2::UserJourney is SystemIdentifier and UserJourneyId): a journey id is scoped to its system and the item carries no ARN of its own
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("resiliencehubv2_user_journey_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "resiliencehubv2_user_journey_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    resiliencehubv2_user_journey_id = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_resiliencehubv2_user_journey"

    def get_name(self) -> str:
        return self.name or self.resiliencehubv2_user_journey_id

    def __str__(self) -> str:
        return self.get_name()
