"""Amazon GuardDuty finding — one active GuardDuty finding in one account and region."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsGuardDutyFinding(BaseModel):
    """One active (unarchived) GuardDuty finding.

    Read with ``guardduty:ListFindings`` (filtered to unarchived findings of the run's own account,
    most severe first, capped) and ``GetFindings``. Keyed by the finding's ARN. Contained by its
    detector (``HOLDS_GUARDDUTY_FINDING``); ``CONCERNS_RESOURCE`` points at the EC2 instance, S3
    bucket or IAM user it names, by that resource's natural key.

    Only typed fields are kept: the finding's description, its action and network details (remote
    IPs, ports, domains) and its evidence are not stored. ``severity_label`` is GuardDuty's documented
    band for ``severity``. ``count`` and ``archived`` are null when GuardDuty did not return them.

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-findings)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_guardduty_finding"
    ENTITY_NAME: ClassVar[str] = "Amazon GuardDuty Finding"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An active Amazon GuardDuty finding: a threat GuardDuty detected in one account and region, "
        "with its type, severity and the resource it concerns."
    )
    ENTITY_ICON: ClassVar[str] = "aws-guardduty"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("finding_arn",)

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {
            "nodes": [
                {"type": "aws_core__aws_ec2_instance"},
                {"type": "aws_core__aws_s3_bucket"},
                {"type": "aws_core__aws_iam_user"},
            ],
            "edges": [{"type": "CONCERNS_RESOURCE__aws_core"}],
        }
    ]

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "finding_arn": {"type": "string"},
        "finding_id": {"type": "string"},
        "detector_id": {"type": "string"},
        "account_id": {"type": "string"},
        "region": {"type": "string"},
        "finding_type": {"type": "string"},
        "severity": {"type": ["number", "null"]},
        # LOW, MEDIUM, HIGH or CRITICAL; "" when GuardDuty returned no number.
        "severity_label": {"type": "string"},
        "title": {"type": "string"},
        "resource_type": {"type": "string"},
        # The instance id, bucket name(s), access-key user name or EKS cluster name, as the finding names it.
        "resource_id": {"type": "string"},
        "first_seen": {"type": "string"},
        "last_seen": {"type": "string"},
        "count": {"type": ["integer", "null"]},
        "archived": {"type": ["boolean", "null"]},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    finding_arn = models.CharField(max_length=2048, blank=True, default="", db_index=True)
    finding_id = models.CharField(max_length=300, blank=True, default="")
    detector_id = models.CharField(max_length=300, blank=True, default="")
    account_id = models.CharField(max_length=12, blank=True, default="")
    region = models.CharField(max_length=32, blank=True, default="")
    finding_type = models.CharField(max_length=255, blank=True, default="")
    severity = models.FloatField(null=True, blank=True, default=None)
    severity_label = models.CharField(max_length=16, blank=True, default="")
    title = models.CharField(max_length=1024, blank=True, default="")
    resource_type = models.CharField(max_length=64, blank=True, default="")
    resource_id = models.CharField(max_length=1024, blank=True, default="")
    first_seen = models.CharField(max_length=40, blank=True, default="")
    last_seen = models.CharField(max_length=40, blank=True, default="")
    count = models.IntegerField(null=True, blank=True, default=None)
    archived = models.BooleanField(null=True, blank=True, default=None)
    created_at = models.CharField(max_length=40, blank=True, default="")
    updated_at = models.CharField(max_length=40, blank=True, default="")
    # AWS cannot tag a finding: always {} (tag_lanes.json, lane `none`).
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_guardduty_finding"

    def get_name(self) -> str:
        return self.name or self.finding_type or self.finding_arn

    def __str__(self) -> str:
        return self.get_name()
