"""AWS Control Tower landing zone — the governed multi-account environment Control Tower manages."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsControlTowerLandingZone(BaseModel):
    """One AWS Control Tower landing zone.

    Collected by ``Boto3Collector`` (``collectors/boto3_collector/landing_zone.py``) from
    ``controltower:ListLandingZones`` and ``GetLandingZone`` in the management account. Keyed by its
    ARN, emitted once, contained by the footprint of the region its ARN names
    (``HOSTS_LANDING_ZONE``). It contains its enabled controls and enabled baselines.

    Only typed fields are kept. ``GetLandingZone``'s ``manifest`` document is not stored; the
    governed regions are read out of it into ``governed_regions``.

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-control-tower)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_controltower_landing_zone"
    ENTITY_NAME: ClassVar[str] = "AWS Control Tower Landing Zone"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Control Tower landing zone: the multi-account environment Control Tower governs, "
        "with its version, status, drift status and governed regions."
    )
    ENTITY_ICON: ClassVar[str] = "aws-control-tower"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "round-rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("landing_zone_arn",)

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {
            "nodes": [{"type": "aws_core__aws_controltower_enabled_control"}],
            "edges": [{"type": "HOLDS_ENABLED_CONTROL__aws_core"}],
        },
        {
            "nodes": [{"type": "aws_core__aws_controltower_enabled_baseline"}],
            "edges": [{"type": "HOLDS_ENABLED_BASELINE__aws_core"}],
        },
    ]
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = (
        "HOLDS_ENABLED_CONTROL__aws_core",
        "HOLDS_ENABLED_BASELINE__aws_core",
    )

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "landing_zone_arn": {"type": "string"},
        # The region the ARN names: Control Tower's home region.
        "home_region": {"type": "string"},
        "version": {"type": "string"},
        "latest_available_version": {"type": "string"},
        "status": {"type": "string"},
        "drift_status": {"type": "string"},
        # The manifest's governedRegions; null when GetLandingZone did not return a readable manifest.
        "governed_regions": {"type": ["array", "null"], "items": {"type": "string"}},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    landing_zone_arn = models.CharField(max_length=2048, blank=True, default="", db_index=True)
    home_region = models.CharField(max_length=32, blank=True, default="")
    version = models.CharField(max_length=32, blank=True, default="")
    latest_available_version = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(max_length=32, blank=True, default="")
    drift_status = models.CharField(max_length=32, blank=True, default="")
    governed_regions = models.JSONField(null=True, blank=True, default=None)
    # AWS tags, canonical flat {str: str}. Source: controltower:ListTagsForResource (`tags` map).
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_controltower_landing_zone"

    def get_name(self) -> str:
        return self.name or self.landing_zone_arn

    def __str__(self) -> str:
        return self.get_name()
