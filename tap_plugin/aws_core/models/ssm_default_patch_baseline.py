"""SSM Default Patch Baseline — an account's default patch baseline for one operating system in one region (Q139a)."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import NO_EVENT_TIME, NoEventTime
from tap_grid.models import BaseModel


class SsmDefaultPatchBaseline(BaseModel):
    """Which patch baseline an account uses by default for one operating system in one region: a DescribePatchBaselines row whose DefaultBaseline is true. Reaches the baseline it names, AWS-owned or the account's own, by DEFAULTS_TO_PATCH_BASELINE (ruling Q139a option 2, req-aws-core-ssm-baselines)."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ssm_default_patch_baseline"
    ENTITY_NAME: ClassVar[str] = "SSM Default Patch Baseline"
    ENTITY_DESCRIPTION: ClassVar[str] = "An account's default SSM patch baseline for one operating system in one region."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): one default per partition, account, region and operating system; AWS
    # gives the setting no id or ARN of its own.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("partition", "account_id", "region", "operating_system")
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): no typed field of this model says when
    # the thing happened in the world; EVENT_TIME_REASON says why.
    EVENT_TIME: ClassVar[NoEventTime] = NO_EVENT_TIME
    EVENT_TIME_REASON: ClassVar[str] = (
        "AWS states no time for the default setting (DescribePatchBaselines BaselineIdentities[] states none, "
        "and neither does GetDefaultPatchBaseline)."
    )

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
        "operating_system": {"type": "string"},
        "baseline_id": {"type": ["string", "null"]},
        "baseline_name": {"type": ["string", "null"]},
        "aws_owned": {"type": ["boolean", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["operating_system"]

    name = models.CharField(max_length=255, blank=True, default="")
    partition = models.CharField(max_length=32, blank=True, default="")
    account_id = models.CharField(max_length=12, blank=True, default="")
    region = models.CharField(max_length=32, blank=True, default="")
    # The SSM OperatingSystem this default applies to.
    operating_system = models.CharField(max_length=64, blank=True, default="")
    # The default baseline's BaselineId: an ARN for AWS's, a pb- id for the account's own.
    baseline_id = models.CharField(max_length=2048, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    baseline_name = models.CharField(max_length=255, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    aws_owned = models.BooleanField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ssm_default_patch_baseline"

    def get_name(self) -> str:
        return self.name or f"default {self.operating_system}"

    def __str__(self) -> str:
        return self.get_name()
