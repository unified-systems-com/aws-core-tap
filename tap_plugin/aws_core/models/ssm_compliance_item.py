"""SSM Compliance Item — one Association or Custom compliance item of a managed instance (req-aws-core-ssm-patch-state)."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import NO_EVENT_TIME, NoEventTime
from tap_grid.models import BaseModel


class SsmComplianceItem(BaseModel):
    """One ListComplianceItems row of a type other than Patch (whose items are read from DescribeInstancePatches: the ones that need action are the instance's REPORTS_PATCH edges). Held by its managed instance (HOLDS_COMPLIANCE_ITEM); an Association item concerns its association (CONCERNS_ASSOCIATION)."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ssm_compliance_item"
    ENTITY_NAME: ClassVar[str] = "SSM Compliance Item"
    ENTITY_DESCRIPTION: ClassVar[str] = "One Association or Custom compliance item a managed instance reports."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): Account, region, resource, compliance type and item id (a Custom item's title when it has no id).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("account_id", "region", "resource_type", "resource_id", "compliance_type", "item_id")
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): no typed field of this model says when
    # the thing happened in the world; EVENT_TIME_REASON says why.
    EVENT_TIME: ClassVar[NoEventTime] = NO_EVENT_TIME
    EVENT_TIME_REASON: ClassVar[str] = (
        "AWS states only ExecutionSummary.ExecutionTime (ListComplianceItems ComplianceItems[]), when the latest "
        "compliance execution that wrote the item ran, which the next execution replaces on this same item: a "
        "last-change time, and none of the four kinds names it (reported on unified-systems-com/tap#1289). It stays "
        "the typed execution_time field."
    )

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "account_id": {"type": "string", "pattern": "^([0-9]{12})?$"},
        "region": {"type": "string"},
        "resource_type": {"type": "string"},
        "resource_id": {"type": "string"},
        "compliance_type": {"type": "string"},
        "item_id": {"type": "string"},
        "title": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "severity": {"type": ["string", "null"]},
        "execution_time": {"type": ["string", "null"]},
        "execution_id": {"type": ["string", "null"]},
        "execution_type": {"type": ["string", "null"]},
        "details": {"type": ["object", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["item_id"]

    name = models.CharField(max_length=255, blank=True, default="")
    account_id = models.CharField(max_length=12, blank=True, default="")
    region = models.CharField(max_length=32, blank=True, default="")
    resource_type = models.CharField(max_length=64, blank=True, default="")
    resource_id = models.CharField(max_length=255, blank=True, default="")
    compliance_type = models.CharField(max_length=255, blank=True, default="")
    item_id = models.CharField(max_length=1024, blank=True, default="")
    title = models.TextField(null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    status = models.CharField(max_length=32, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    severity = models.CharField(max_length=32, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    execution_time = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    execution_id = models.CharField(max_length=255, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    execution_type = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    # The item's Details map as AWS returns it (string to string).
    details = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ssm_compliance_item"

    def get_name(self) -> str:
        return self.title or self.item_id

    def __str__(self) -> str:
        return self.get_name()
