"""GuardDuty Filter — a GuardDuty filter that archives matching findings."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class GuarddutyFilter(BaseModel):
    """A GuardDuty filter: findings that match its criteria are archived automatically (action ARCHIVE), so a filter decides which threats never reach a reviewer."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_guardduty_filter"
    ENTITY_NAME: ClassVar[str] = "GuardDuty Filter"
    ENTITY_DESCRIPTION: ClassVar[str] = "A GuardDuty filter that archives matching findings."
    ENTITY_ICON: ClassVar[str] = "aws-guardduty"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The detector id, 'filter' and the filter name: a filter name is unique only within a detector.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("filter_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "filter_key": {"type": "string"},
        "detector_id": {"type": ["string", "null"]},
        "action": {"type": ["string", "null"]},
        "rank": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "filter_key": {"validation": "jsonschema", "schema": {"type": "string"}},
        "detector_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "action": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "rank": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    filter_key = models.CharField(max_length=512, blank=True, default="")
    # The detector the filter belongs to. NULL = not observed.
    detector_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # ARCHIVE (hide matching findings) or NOOP. NULL = not observed.
    action = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The filter's position among the detector's filters. NULL = not observed.
    rank = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_guardduty_filter"

    def get_name(self) -> str:
        return self.name or self.filter_key

    def __str__(self) -> str:
        return self.get_name()
