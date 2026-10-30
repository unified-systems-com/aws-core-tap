"""GuardDuty Trusted IP List — a GuardDuty trusted IP list."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class GuarddutyIpSet(BaseModel):
    """A GuardDuty trusted IP list: addresses GuardDuty will not generate findings for. A list that is too broad is a blind spot."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_guardduty_ip_set"
    ENTITY_NAME: ClassVar[str] = "GuardDuty Trusted IP List"
    ENTITY_DESCRIPTION: ClassVar[str] = "A GuardDuty trusted IP list."
    ENTITY_ICON: ClassVar[str] = "aws-guardduty"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The detector id, 'ipset' and the list id: a list id is unique only within a detector.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("ip_set_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "ip_set_key": {"type": "string"},
        "detector_id": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "format": {"type": ["string", "null"]},
        "location": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "ip_set_key": {"validation": "jsonschema", "schema": {"type": "string"}},
        "detector_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "format": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "location": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    ip_set_key = models.CharField(max_length=512, blank=True, default="")
    # The detector the list belongs to. NULL = not observed.
    detector_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # AWS's status (ACTIVE, INACTIVE, ...). NULL = not observed.
    status = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The file format of the list (TXT, STIX, ...). NULL = not observed.
    format = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The S3 URL of the list file. NULL = not observed.
    location = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_guardduty_ip_set"

    def get_name(self) -> str:
        return self.name or self.ip_set_key

    def __str__(self) -> str:
        return self.get_name()
