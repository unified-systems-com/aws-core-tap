"""AWS SSM Patch Baseline — an account's own patch baseline, or one of AWS's, shared per region (Q139a)."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import NO_EVENT_TIME, NoEventTime
from tap_grid.models import BaseModel


class SsmPatchBaseline(BaseModel):
    """An AWS SSM Patch Baseline, listed by DescribePatchBaselines with no filter (req-aws-core-ssm-baselines). An account's own baseline is keyed by the pb- id SSM generates for it and carries its tags. An AWS-owned baseline is keyed by its ARN, which names AWS's account: one node per region shared by every account that lists it, carrying AWS's account in its aws.account dimension, never the collecting account's (ruling Q139a option 2). Which baseline is an account's default for an operating system is the aws_ssm_default_patch_baseline node, not a field here."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ssm_patch_baseline"
    ENTITY_NAME: ClassVar[str] = "AWS SSM Patch Baseline"
    ENTITY_DESCRIPTION: ClassVar[str] = "An SSM patch baseline: an account's own, or one of AWS's, shared by every account in its region."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The baseline's BaselineId: DescribePatchBaselines returns no ARN, and a patch baseline id is service-generated.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("ssm_patch_baseline_id",)
    ARN_RESOURCE: ClassVar[str | None] = "ssm:patchbaseline"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): no typed field of this model says when
    # the thing happened in the world; EVENT_TIME_REASON says why.
    EVENT_TIME: ClassVar[NoEventTime] = NO_EVENT_TIME
    EVENT_TIME_REASON: ClassVar[str] = (
        "AWS returns no time in its own record (DescribePatchBaselines BaselineIdentities[])."
    )

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "ssm_patch_baseline_id": {"type": "string"},
        "operating_system": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "aws_owned": {"type": ["boolean", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    ssm_patch_baseline_id = models.CharField(max_length=2048, blank=True, default="")
    # The SSM OperatingSystem the baseline patches (WINDOWS, AMAZON_LINUX_2023 and so on).
    operating_system = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    description = models.TextField(null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    # True for AWS's baseline (its id is an ARN under AWS's account), False for the account's own.
    aws_owned = models.BooleanField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ssm_patch_baseline"

    def get_name(self) -> str:
        return self.name or self.ssm_patch_baseline_id

    def __str__(self) -> str:
        return self.get_name()
