"""AWS Security Hub finding — one active finding in one account and region, control results included."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsSecurityHubFinding(BaseModel):
    """One active Security Hub finding (ASFF).

    Read with ``securityhub:GetFindings``, filtered to the run's own account, the hub's region and
    ``RecordState`` ACTIVE, one capped read per severity label from CRITICAL down. Keyed by
    (``ProductArn``, ``Id``), which is how ASFF identifies a finding. Contained by its hub
    (``HOLDS_SECURITYHUB_FINDING``). A control finding carries its compliance status and security
    control id, and ``EVALUATED_UNDER_STANDARD`` points at each enabled standard it is evaluated
    under. ``CONCERNS_RESOURCE`` points at an EC2 instance, S3 bucket, IAM user or IAM role it names.

    Only typed fields are kept: no ASFF document, description, remediation, network or process
    detail, product fields or resource details are stored.

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-findings)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_securityhub_finding"
    ENTITY_NAME: ClassVar[str] = "AWS Security Hub Finding"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An active AWS Security Hub finding: a control result or an integrated product's finding, "
        "with its severity, workflow status and compliance status."
    )
    ENTITY_ICON: ClassVar[str] = "aws-security-hub"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("product_arn", "finding_id")

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {
            "nodes": [{"type": "aws_core__aws_securityhub_standards_subscription"}],
            "edges": [{"type": "EVALUATED_UNDER_STANDARD__aws_core"}],
        },
        {
            "nodes": [
                {"type": "aws_core__aws_ec2_instance"},
                {"type": "aws_core__aws_s3_bucket"},
                {"type": "aws_core__aws_iam_user"},
                {"type": "aws_core__aws_iam_role"},
            ],
            "edges": [{"type": "CONCERNS_RESOURCE__aws_core"}],
        },
    ]

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "finding_id": {"type": "string"},
        "product_arn": {"type": "string"},
        "product_name": {"type": "string"},
        "generator_id": {"type": "string"},
        "aws_account_id": {"type": "string"},
        "region": {"type": "string"},
        "title": {"type": "string"},
        # INFORMATIONAL, LOW, MEDIUM, HIGH or CRITICAL, verbatim.
        "severity_label": {"type": "string"},
        # NEW, NOTIFIED, RESOLVED or SUPPRESSED, verbatim.
        "workflow_status": {"type": "string"},
        "record_state": {"type": "string"},
        # PASSED, WARNING, FAILED or NOT_AVAILABLE on a control finding; "" otherwise.
        "compliance_status": {"type": "string"},
        "security_control_id": {"type": "string"},
        # Compliance.AssociatedStandards[].StandardsId: the resource portion of each standard's ARN.
        "associated_standards": {"type": "array", "items": {"type": "string"}},
        "resource_types": {"type": "array", "items": {"type": "string"}},
        "resource_ids": {"type": "array", "items": {"type": "string"}},
        "first_observed_at": {"type": "string"},
        "last_observed_at": {"type": "string"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    finding_id = models.CharField(max_length=512, blank=True, default="", db_index=True)
    product_arn = models.CharField(max_length=2048, blank=True, default="")
    product_name = models.CharField(max_length=255, blank=True, default="")
    generator_id = models.CharField(max_length=512, blank=True, default="")
    aws_account_id = models.CharField(max_length=12, blank=True, default="")
    region = models.CharField(max_length=32, blank=True, default="")
    title = models.CharField(max_length=1024, blank=True, default="")
    severity_label = models.CharField(max_length=16, blank=True, default="")
    workflow_status = models.CharField(max_length=16, blank=True, default="")
    record_state = models.CharField(max_length=16, blank=True, default="")
    compliance_status = models.CharField(max_length=16, blank=True, default="")
    security_control_id = models.CharField(max_length=64, blank=True, default="")
    associated_standards = models.JSONField(default=list, blank=True)
    resource_types = models.JSONField(default=list, blank=True)
    resource_ids = models.JSONField(default=list, blank=True)
    first_observed_at = models.CharField(max_length=40, blank=True, default="")
    last_observed_at = models.CharField(max_length=40, blank=True, default="")
    created_at = models.CharField(max_length=40, blank=True, default="")
    updated_at = models.CharField(max_length=40, blank=True, default="")
    # AWS cannot tag a finding: always {} (tag_lanes.json, lane `none`).
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_securityhub_finding"

    def get_name(self) -> str:
        return self.name or self.finding_id

    def __str__(self) -> str:
        return self.get_name()
