"""AWS Control Tower enabled baseline — one baseline applied to one OU or account."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsControlTowerEnabledBaseline(BaseModel):
    """One enabled baseline: a Control Tower baseline applied to one target.

    Collected from ``controltower:ListEnabledBaselines(includeChildren=true)`` with no filter: the
    call defaults to omitting child enabled baselines, which would read as their absence
    (``req-aws-core-contained-type-triple-6``). A child baseline's ``parentIdentifier`` is kept as
    ``parent_identifier``. Contained by its landing zone (``HOLDS_ENABLED_BASELINE``).

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-control-tower)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_controltower_enabled_baseline"
    ENTITY_NAME: ClassVar[str] = "AWS Control Tower Enabled Baseline"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Control Tower baseline (a set of resources and configuration Control Tower deploys) "
        "enabled on one organizational unit or account."
    )
    ENTITY_ICON: ClassVar[str] = "aws-control-tower"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("enabled_baseline_arn",)

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {
            "nodes": [{"type": "aws_core__aws_organizational_unit"}, {"type": "aws_core__aws_account"}],
            "edges": [{"type": "APPLIES_TO_TARGET__aws_core"}],
        }
    ]

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "enabled_baseline_arn": {"type": "string"},
        "baseline_identifier": {"type": "string"},
        "baseline_version": {"type": "string"},
        # The OU or account ARN the baseline is enabled on, verbatim.
        "target_identifier": {"type": "string"},
        # The parent enabled baseline's ARN for a child baseline; "" for a top-level one.
        "parent_identifier": {"type": "string"},
        "status": {"type": "string"},
        "drift_status": {"type": "string"},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    enabled_baseline_arn = models.CharField(max_length=2048, blank=True, default="", db_index=True)
    baseline_identifier = models.CharField(max_length=2048, blank=True, default="")
    baseline_version = models.CharField(max_length=32, blank=True, default="")
    target_identifier = models.CharField(max_length=2048, blank=True, default="")
    parent_identifier = models.CharField(max_length=2048, blank=True, default="")
    status = models.CharField(max_length=32, blank=True, default="")
    drift_status = models.CharField(max_length=32, blank=True, default="")
    # AWS tags, canonical flat {str: str}. Source: controltower:ListTagsForResource (`tags` map).
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_controltower_enabled_baseline"

    def get_name(self) -> str:
        return self.name or self.enabled_baseline_arn

    def __str__(self) -> str:
        return self.get_name()
