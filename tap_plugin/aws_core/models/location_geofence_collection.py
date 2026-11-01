"""AWS Location Geofence Collection — an AWS Location Geofence Collection."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class LocationGeofenceCollection(BaseModel):
    """An AWS Location Geofence Collection, read by ListGeofenceCollections. Only its identity, name and tags are collected; the rest of the response is not stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_location_geofence_collection"
    ENTITY_NAME: ClassVar[str] = "AWS Location Geofence Collection"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Location Geofence Collection."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The resource's ARN, built as arn:{partition}:geo:{region}:{account}:geofence-collection/{CollectionName} (the AWS Service Authorization Reference 'geo' geofence-collection resource); the listing carries no ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("location_geofence_collection_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "location_geofence_collection_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    location_geofence_collection_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_location_geofence_collection"

    def get_name(self) -> str:
        return self.name or self.location_geofence_collection_arn

    def __str__(self) -> str:
        return self.get_name()
