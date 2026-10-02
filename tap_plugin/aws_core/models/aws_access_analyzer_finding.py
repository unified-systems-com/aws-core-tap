"""AWS IAM Access Analyzer finding — one active finding of one analyzer."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsAccessAnalyzerFinding(BaseModel):
    """One active IAM Access Analyzer finding.

    Read with ``accessanalyzer:ListFindings`` for an external-access analyzer (``ACCOUNT``,
    ``ORGANIZATION``) and ``ListFindingsV2`` for the others, filtered to ``status`` ACTIVE on the run's
    own account's resources, capped. Keyed by (analyzer ARN, finding id). Contained by its analyzer
    (``HOLDS_ACCESS_ANALYZER_FINDING``). ``CONCERNS_RESOURCE`` points at the S3 bucket, IAM role or IAM
    user it names, by ARN.

    ``principal``, ``actions``, ``is_public`` and ``condition_keys`` come from the external-access
    summary and are null for a v2 summary, which carries none. ``condition_keys`` is the condition
    summary: the condition's keys only, never its values.

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-findings)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_access_analyzer_finding"
    ENTITY_NAME: ClassVar[str] = "AWS IAM Access Analyzer Finding"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An active IAM Access Analyzer finding: a resource reachable from outside its zone of trust, "
        "or unused or internal access, on one resource."
    )
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("analyzer_arn", "finding_id")

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {
            "nodes": [
                {"type": "aws_core__aws_s3_bucket"},
                {"type": "aws_core__aws_iam_role"},
                {"type": "aws_core__aws_iam_user"},
            ],
            "edges": [{"type": "CONCERNS_RESOURCE__aws_core"}],
        }
    ]

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "finding_id": {"type": "string"},
        "analyzer_arn": {"type": "string"},
        "resource_arn": {"type": "string"},
        # AWS::S3::Bucket, AWS::IAM::Role, ... verbatim.
        "resource_type": {"type": "string"},
        "resource_owner_account": {"type": "string"},
        # ExternalAccess, UnusedIAMRole, UnusedPermission, InternalAccess, ... verbatim.
        "finding_type": {"type": "string"},
        "status": {"type": "string"},
        "is_public": {"type": ["boolean", "null"]},
        "principal": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
        "actions": {"type": ["array", "null"], "items": {"type": "string"}},
        "condition_keys": {"type": ["array", "null"], "items": {"type": "string"}},
        "error": {"type": "string"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "analyzed_at": {"type": "string"},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    finding_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    analyzer_arn = models.CharField(max_length=2048, blank=True, default="")
    resource_arn = models.CharField(max_length=2048, blank=True, default="")
    resource_type = models.CharField(max_length=64, blank=True, default="")
    resource_owner_account = models.CharField(max_length=12, blank=True, default="")
    finding_type = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, blank=True, default="")
    is_public = models.BooleanField(null=True, blank=True, default=None)
    principal = models.JSONField(null=True, blank=True, default=None)
    actions = models.JSONField(null=True, blank=True, default=None)
    condition_keys = models.JSONField(null=True, blank=True, default=None)
    error = models.CharField(max_length=255, blank=True, default="")
    created_at = models.CharField(max_length=40, blank=True, default="")
    updated_at = models.CharField(max_length=40, blank=True, default="")
    analyzed_at = models.CharField(max_length=40, blank=True, default="")
    # AWS cannot tag a finding: always {} (tag_lanes.json, lane `none`).
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_access_analyzer_finding"

    def get_name(self) -> str:
        return self.name or self.finding_id

    def __str__(self) -> str:
        return self.get_name()
