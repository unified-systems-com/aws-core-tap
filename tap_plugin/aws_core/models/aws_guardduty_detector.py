"""Amazon GuardDuty detector — GuardDuty turned on in one account and region."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsGuardDutyDetector(BaseModel):
    """One GuardDuty detector.

    Read with ``guardduty:ListDetectors`` (to its last page), ``GetDetector`` and
    ``GetAdministratorAccount``. A detector id is unique only within its account and region, so it
    is keyed (account, region, detector id). ``REPORTS_TO_ADMINISTRATOR`` points at the
    administrator account when another account administers it. Tags come from ``GetDetector``'s own
    ``Tags`` map. Contained by its footprint (``HOSTS_GUARDDUTY_DETECTOR``).

    ``administrator_account_id`` is null when the administrator read failed, ``""`` when the
    detector has no administrator.

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-security-services)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_guardduty_detector"
    ENTITY_NAME: ClassVar[str] = "Amazon GuardDuty Detector"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An Amazon GuardDuty detector: GuardDuty threat detection in one account and region, and "
        "the administrator account it reports to."
    )
    ENTITY_ICON: ClassVar[str] = "aws-guardduty"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("account_id", "region", "detector_id")

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "aws_core__aws_account"}], "edges": [{"type": "REPORTS_TO_ADMINISTRATOR__aws_core"}]}
    ]

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "account_id": {"type": "string", "pattern": "^([0-9]{12})?$"},
        "region": {"type": "string"},
        "detector_id": {"type": "string"},
        # ENABLED or DISABLED, verbatim.
        "status": {"type": "string"},
        "finding_publishing_frequency": {"type": "string"},
        "administrator_account_id": {"type": ["string", "null"]},
        "relationship_status": {"type": "string"},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    account_id = models.CharField(max_length=12, blank=True, default="", db_index=True)
    region = models.CharField(max_length=32, blank=True, default="")
    detector_id = models.CharField(max_length=300, blank=True, default="", db_index=True)
    status = models.CharField(max_length=16, blank=True, default="")
    finding_publishing_frequency = models.CharField(max_length=32, blank=True, default="")
    administrator_account_id = models.CharField(max_length=12, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read", "" is "no administrator"
    relationship_status = models.CharField(max_length=64, blank=True, default="")
    # AWS tags, canonical flat {str: str}. Source: GetDetector `Tags` (map).
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_guardduty_detector"

    def get_name(self) -> str:
        return self.name or self.detector_id

    def __str__(self) -> str:
        return self.get_name()
