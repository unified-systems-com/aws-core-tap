"""EventBridge Archive — an Amazon EventBridge archive."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class EventbridgeArchive(BaseModel):
    """An Amazon EventBridge archive: a store of events from a bus, kept for replay. Its retention decides how long event payloads (which can carry business data) remain."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_eventbridge_archive"
    ENTITY_NAME: ClassVar[str] = "EventBridge Archive"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon EventBridge archive."
    ENTITY_ICON: ClassVar[str] = "aws-eventbridge"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The archive's ARN, built from its source bus's ARN: an archive name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("archive_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "archive_arn": {"type": "string"},
        "event_source_arn": {"type": ["string", "null"]},
        "state": {"type": ["string", "null"]},
        "retention_days": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "archive_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "event_source_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "state": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "retention_days": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    archive_arn = models.CharField(max_length=512, blank=True, default="")
    # The bus the archive stores events from. NULL = not observed.
    event_source_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # AWS's archive state (ENABLED, DISABLED, CREATING, ...). NULL = not observed.
    state = models.CharField(max_length=512, blank=True, null=True, default=None)
    # How many days events are kept; 0 means indefinitely. NULL = not observed.
    retention_days = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_eventbridge_archive"

    def get_name(self) -> str:
        return self.name or self.archive_arn

    def __str__(self) -> str:
        return self.get_name()
