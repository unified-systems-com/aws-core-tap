"""CloudTrail Event Data Store — a CloudTrail Lake event data store."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CloudtrailEventDataStore(BaseModel):
    """A CloudTrail Lake event data store: the immutable, queryable store audit events are kept in. Its retention and termination protection decide how long an investigation can look back."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cloudtrail_event_data_store"
    ENTITY_NAME: ClassVar[str] = "CloudTrail Event Data Store"
    ENTITY_DESCRIPTION: ClassVar[str] = "A CloudTrail Lake event data store."
    ENTITY_ICON: ClassVar[str] = "aws-cloudtrail"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The event data store's ARN: a name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("event_data_store_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "event_data_store_arn": {"type": "string"},
        "status": {"type": ["string", "null"]},
        "multi_region_enabled": {"type": ["boolean", "null"]},
        "organization_enabled": {"type": ["boolean", "null"]},
        "retention_period_days": {"type": ["integer", "null"]},
        "termination_protection_enabled": {"type": ["boolean", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "event_data_store_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "multi_region_enabled": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "organization_enabled": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "retention_period_days": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "termination_protection_enabled": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    event_data_store_arn = models.CharField(max_length=512, blank=True, default="")
    # AWS's status (ENABLED, CREATED, PENDING_DELETION, ...). NULL = not observed.
    status = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Whether the store collects events from every region. NULL = not observed.
    multi_region_enabled = models.BooleanField(null=True, blank=True, default=None)
    # Whether the store collects events for every account of the organization. NULL = not observed.
    organization_enabled = models.BooleanField(null=True, blank=True, default=None)
    # How long events are kept, in days. NULL = not observed.
    retention_period_days = models.IntegerField(null=True, blank=True, default=None)
    # Whether the store is protected from deletion. NULL = not observed.
    termination_protection_enabled = models.BooleanField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cloudtrail_event_data_store"

    def get_name(self) -> str:
        return self.name or self.event_data_store_arn

    def __str__(self) -> str:
        return self.get_name()
