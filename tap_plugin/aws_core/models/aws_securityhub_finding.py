"""AWS Security Hub finding — one finding, active or recently archived, in one account and region, control results included."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class AwsSecurityHubFinding(BaseModel):
    """One Security Hub finding (ASFF): its record active, or archived in the last 30 days.

    Read with ``securityhub:GetFindings``, filtered to the run's own account and the hub's region:
    ``RecordState`` ACTIVE, one capped read per severity label from CRITICAL down, and ``RecordState``
    ARCHIVED with ``UpdatedAt`` in the last 30 days, capped on its own (aws-core-tap#264, ruling
    Q115a). ``record_state`` is Security Hub's own state (ARCHIVED: the product closed it, or the
    resource is gone), beside ``workflow_status``, an operator's triage state. Keyed by
    (``ProductArn``, ``Id``), which is how ASFF identifies a finding. Contained by its hub
    (``HOLDS_SECURITYHUB_FINDING``). A control finding carries its compliance status and security
    control id, and ``EVALUATED_UNDER_STANDARD`` points at each enabled standard it is evaluated
    under. ``CONCERNS_RESOURCE`` points at each resource it names that an aws_core type is keyed by:
    any ARN-keyed type by its ARN, and an EC2 instance by the instance id in its ARN.

    What the finding says about itself is kept (aws-core-tap#264, ruling Q114c), each part in ASFF's
    own shape: ``description``, ``types``, ``severity_normalized``, ``remediation``, ``network``,
    ``malware``, ``vulnerabilities`` (CVE ids, CVSS, packages, fix availability), ``product_fields``,
    ``compliance_status_reasons`` and ``finding_provider_fields``; each JSON part is null when the
    finding carries none. The rest of the ASFF document (process, threats, resource details, notes)
    is not stored.

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-findings)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_securityhub_finding"
    ENTITY_NAME: ClassVar[str] = "AWS Security Hub Finding"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Security Hub finding, active or recently archived: a control result or an integrated "
        "product's finding, with its severity, workflow status, compliance status and detail."
    )
    ENTITY_ICON: ClassVar[str] = "aws-security-hub"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("product_arn", "finding_id")
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): CreatedAt, when the provider created the finding
    # (core rule 13: a finding at its creation). An interval with no end: the thing holds from then on and AWS states no
    # end (core rule 8).
    EVENT_TIME: ClassVar[Interval] = Interval(start="created_at", kind="created")
    # Identity (req-aws-collector-identity-13): no manifest entry collects this type, so its declaration lives
    # here, in the shape of a manifest entry's `identity` block, checked against the CloudFormation ledger by
    # tests/test_identity_declarations.py.
    AWS_IDENTITY: ClassVar[dict[str, object]] = {
        "cfn_type": None,
        "reason": "not a CloudFormation resource: a Security Hub finding, named by the product ARN and finding id ASFF identifies it by",
    }

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {
            "nodes": [{"type": "aws_core__aws_securityhub_standards_subscription"}],
            "edges": [{"type": "EVALUATED_UNDER_STANDARD__aws_core"}],
        },
        # Open: any aws_core node keyed by the ARN the finding names (aws-core-tap#242).
        {"edges": [{"type": "CONCERNS_RESOURCE__aws_core"}]},
    ]

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "finding_id": {"type": "string"},
        "product_arn": {"type": "string"},
        "product_name": {"type": ["string", "null"]},
        "generator_id": {"type": ["string", "null"]},
        "aws_account_id": {"type": ["string", "null"]},
        "region": {"type": ["string", "null"]},
        "title": {"type": ["string", "null"]},
        # INFORMATIONAL, LOW, MEDIUM, HIGH or CRITICAL, verbatim.
        "severity_label": {"type": ["string", "null"]},
        # NEW, NOTIFIED, RESOLVED or SUPPRESSED, verbatim.
        "workflow_status": {"type": ["string", "null"]},
        "record_state": {"type": ["string", "null"]},
        # PASSED, WARNING, FAILED or NOT_AVAILABLE on a control finding; "" otherwise.
        "compliance_status": {"type": ["string", "null"]},
        "security_control_id": {"type": ["string", "null"]},
        # Compliance.AssociatedStandards[].StandardsId: the resource portion of each standard's ARN.
        "associated_standards": {"type": "array", "items": {"type": "string"}},
        "resource_types": {"type": "array", "items": {"type": "string"}},
        "resource_ids": {"type": "array", "items": {"type": "string"}},
        "first_observed_at": {"type": ["string", "null"]},
        "last_observed_at": {"type": ["string", "null"]},
        "created_at": {"type": ["string", "null"]},
        "updated_at": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        # Types[]: the ASFF type taxonomy (namespace/category/classifier), verbatim.
        "types": {"type": "array", "items": {"type": "string"}},
        # Severity.Normalized, 0-100.
        "severity_normalized": {"type": ["integer", "null"]},
        # Remediation, Network, Malware[], Vulnerabilities[], ProductFields, Compliance.StatusReasons[]
        # and FindingProviderFields, each verbatim.
        "remediation": {"type": ["object", "null"]},
        "network": {"type": ["object", "null"]},
        "malware": {"type": ["array", "null"], "items": {"type": "object"}},
        "vulnerabilities": {"type": ["array", "null"], "items": {"type": "object"}},
        "product_fields": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
        "compliance_status_reasons": {"type": ["array", "null"], "items": {"type": "object"}},
        "finding_provider_fields": {"type": ["object", "null"]},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    finding_id = models.CharField(max_length=512, blank=True, default="", db_index=True)
    product_arn = models.CharField(max_length=2048, blank=True, default="")
    product_name = models.CharField(max_length=255, null=True, blank=True, default=None)
    generator_id = models.CharField(max_length=512, null=True, blank=True, default=None)
    aws_account_id = models.CharField(max_length=12, null=True, blank=True, default=None)
    region = models.CharField(max_length=32, null=True, blank=True, default=None)
    title = models.CharField(max_length=1024, null=True, blank=True, default=None)
    severity_label = models.CharField(max_length=16, null=True, blank=True, default=None)
    workflow_status = models.CharField(max_length=16, null=True, blank=True, default=None)
    record_state = models.CharField(max_length=16, null=True, blank=True, default=None)
    compliance_status = models.CharField(max_length=16, null=True, blank=True, default=None)
    security_control_id = models.CharField(max_length=64, null=True, blank=True, default=None)
    associated_standards = models.JSONField(default=list, blank=True)
    resource_types = models.JSONField(default=list, blank=True)
    resource_ids = models.JSONField(default=list, blank=True)
    first_observed_at = models.CharField(max_length=40, null=True, blank=True, default=None)
    last_observed_at = models.CharField(max_length=40, null=True, blank=True, default=None)
    created_at = models.CharField(max_length=40, null=True, blank=True, default=None)
    updated_at = models.CharField(max_length=40, null=True, blank=True, default=None)
    description = models.TextField(null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    types = models.JSONField(default=list, blank=True)
    severity_normalized = models.IntegerField(null=True, blank=True, default=None)
    # Sources: securityhub:GetFindings Findings[].Remediation, .Network, .Malware, .Vulnerabilities,
    # .ProductFields, .Compliance.StatusReasons and .FindingProviderFields.
    remediation = models.JSONField(null=True, blank=True, default=None)
    network = models.JSONField(null=True, blank=True, default=None)
    malware = models.JSONField(null=True, blank=True, default=None)
    vulnerabilities = models.JSONField(null=True, blank=True, default=None)
    product_fields = models.JSONField(null=True, blank=True, default=None)
    compliance_status_reasons = models.JSONField(null=True, blank=True, default=None)
    finding_provider_fields = models.JSONField(null=True, blank=True, default=None)
    # AWS cannot tag a finding: always {} (tag_lanes.json, lane `none`).
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_securityhub_finding"

    def get_name(self) -> str:
        return self.name or self.finding_id

    def __str__(self) -> str:
        return self.get_name()
