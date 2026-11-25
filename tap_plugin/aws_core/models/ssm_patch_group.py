"""SSM Patch Group — a patch group registered with a patch baseline in one account and region (Q139b)."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import NO_EVENT_TIME, NoEventTime
from tap_grid.models import BaseModel


class SsmPatchGroup(BaseModel):
    """A patch group as DescribePatchGroups lists it: a name registered with one patch baseline per operating system. Reaches each registered baseline by REGISTERED_TO_PATCH_BASELINE; each managed instance whose last patch operation names the group reaches it by IN_PATCH_GROUP (ruling Q139b, req-aws-core-ssm-baselines)."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ssm_patch_group"
    ENTITY_NAME: ClassVar[str] = "SSM Patch Group"
    ENTITY_DESCRIPTION: ClassVar[str] = "An SSM patch group registered with a patch baseline, in one account and region."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): the group's name, scoped by partition, account and region; a patch
    # group is a tag value AWS gives no id or ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("partition", "account_id", "region", "patch_group")
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): no typed field of this model says when
    # the thing happened in the world; EVENT_TIME_REASON says why.
    EVENT_TIME: ClassVar[NoEventTime] = NO_EVENT_TIME
    EVENT_TIME_REASON: ClassVar[str] = "AWS states no time for a patch group (DescribePatchGroups Mappings[] states none)."

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "partition": {"type": "string"},
        "account_id": {"type": "string", "pattern": "^([0-9]{12})?$"},
        "region": {"type": "string"},
        "patch_group": {"type": "string"},
        "baseline_ids": {"type": ["array", "null"], "items": {"type": "string"}},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["patch_group"]

    name = models.CharField(max_length=255, blank=True, default="")
    partition = models.CharField(max_length=32, blank=True, default="")
    account_id = models.CharField(max_length=12, blank=True, default="")
    region = models.CharField(max_length=32, blank=True, default="")
    # The group's name: the value of the instances' Patch Group (or PatchGroup) tag, 1 to 256 characters.
    patch_group = models.CharField(max_length=256, blank=True, default="")
    # The BaselineId of every baseline registered for the group, one per operating system.
    baseline_ids = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ssm_patch_group"

    def get_name(self) -> str:
        return self.name or self.patch_group

    def __str__(self) -> str:
        return self.get_name()
