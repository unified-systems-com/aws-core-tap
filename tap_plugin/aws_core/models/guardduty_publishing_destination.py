"""GuardDuty Publishing Destination — a GuardDuty findings export destination."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class GuarddutyPublishingDestination(BaseModel):
    """A GuardDuty publishing destination: the S3 bucket (and KMS key) findings are exported to. Findings carry resource and network detail, so where they land and how they are encrypted matters."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_guardduty_publishing_destination"
    ENTITY_NAME: ClassVar[str] = "GuardDuty Publishing Destination"
    ENTITY_DESCRIPTION: ClassVar[str] = "A GuardDuty findings export destination."
    ENTITY_ICON: ClassVar[str] = "aws-guardduty"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The detector id, 'destination' and the destination id: a destination id is unique only within a detector.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("destination_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "destination_key": {"type": "string"},
        "detector_id": {"type": ["string", "null"]},
        "destination_type": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "destination_arn": {"type": ["string", "null"]},
        "kms_key_arn": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "destination_key": {"validation": "jsonschema", "schema": {"type": "string"}},
        "detector_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "destination_type": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "destination_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "kms_key_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    destination_key = models.CharField(max_length=512, blank=True, default="")
    # The detector the destination belongs to. NULL = not observed.
    detector_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The kind of destination (S3). NULL = not observed.
    destination_type = models.CharField(max_length=512, blank=True, null=True, default=None)
    # AWS's status (PUBLISHING, UNABLE_TO_PUBLISH_FIX_DESTINATION_PROPERTY, ...). NULL = not observed.
    status = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The bucket findings are written to. NULL = not observed.
    destination_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The key that encrypts the export. NULL = not observed.
    kms_key_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_guardduty_publishing_destination"

    def get_name(self) -> str:
        return self.name or self.destination_key

    def __str__(self) -> str:
        return self.get_name()
