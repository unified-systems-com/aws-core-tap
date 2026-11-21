"""Amazon Inspector v2 package- or code-vulnerability finding — one finding, active or recently closed, in one account and region."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsInspector2Finding(BaseModel):
    """One Amazon Inspector v2 ``PACKAGE_VULNERABILITY`` or ``CODE_VULNERABILITY`` finding: active, or closed in
    the last 30 days.

    Read with ``inspector2:ListFindings`` twice per region and type for the run's own account (ACTIVE findings most
    severe first, and findings CLOSED in the last 30 days, each to its end unless the operator limits it;
    aws-core-tap#261). A code finding keeps its CWEs, detector, rule and file location (``cwes``, ``detector_*``,
    ``rule_id``, ``code_*``); a package finding its vulnerability fields. Keyed by
    the finding's ARN. ``status`` is Inspector's own field, verbatim (``ACTIVE``, ``SUPPRESSED``, ``CLOSED``).
    Contained by the account's region footprint (``HOSTS_INSPECTOR2_FINDING``); ``CONCERNS_RESOURCE`` points at
    the EC2 instance, Lambda function or ECR repository it names, and for an ECR image also at computing_core's
    ``oci-digest`` image host. The targets are a closed list.

    The vendor record is kept losslessly so a projection can change without re-collecting: every CVSS entry
    (``cvss``), the environment-adjusted score (``adjusted_cvss``), EPSS, the exploit and fix flags and every
    vulnerable package, each in Inspector's own shape. ``resources[].details`` is not stored: the node the
    finding concerns holds those facts. ``package_identities`` is derived: the computing_core package key each
    vulnerable package got, or why it got none (``req-aws-landing-zone-inspector-packages``).

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-inspector)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_inspector2_finding"
    ENTITY_NAME: ClassVar[str] = "Amazon Inspector Finding"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An Amazon Inspector v2 package- or code-vulnerability finding, active or recently closed: a CVE or "
        "advisory Inspector matched against a package on an EC2 instance, ECR image or Lambda function, with its "
        "CVSS entries, fix and exploit flags and vulnerable packages, or a weakness its code scan found, with its "
        "CWEs, detector and file location."
    )
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("finding_arn",)
    # The service reference's inspector2 Finding (arn:...:inspector2:<region>:<account>:finding/<id>); the key is the
    # ARN ListFindings returns.
    ARN_RESOURCE: ClassVar[str | None] = "inspector2:Finding"

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        # The resource resources[0] names (collectors/boto3_collector/inspector.py, CONCERNS_TARGETS; a test keeps
        # the two equal).
        {
            "nodes": [
                {"type": "aws_core__aws_ec2_instance"},
                {"type": "aws_core__aws_lambda"},
                {"type": "aws_core__aws_ecr_repository"},
                {"type": "computing_core__host"},
            ],
            "edges": [{"type": "CONCERNS_RESOURCE__aws_core"}],
        },
    ]

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "finding_arn": {"type": "string"},
        "account_id": {"type": ["string", "null"]},
        "region": {"type": ["string", "null"]},
        # PACKAGE_VULNERABILITY or CODE_VULNERABILITY.
        "finding_type": {"type": ["string", "null"]},
        # ACTIVE, SUPPRESSED or CLOSED, verbatim.
        "status": {"type": ["string", "null"]},
        # INFORMATIONAL, LOW, MEDIUM, HIGH, CRITICAL or UNTRIAGED, verbatim.
        "severity": {"type": ["string", "null"]},
        "inspector_score": {"type": ["number", "null"]},
        "title": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "remediation": {"type": ["string", "null"]},
        "remediation_url": {"type": ["string", "null"]},
        "first_observed_at": {"type": ["string", "null"]},
        "last_observed_at": {"type": ["string", "null"]},
        "updated_at": {"type": ["string", "null"]},
        "vulnerability_id": {"type": ["string", "null"]},
        "related_vulnerabilities": {"type": ["array", "null"], "items": {"type": "string"}},
        "vulnerability_source": {"type": ["string", "null"]},
        "source_url": {"type": ["string", "null"]},
        "vendor_severity": {"type": ["string", "null"]},
        "vendor_created_at": {"type": ["string", "null"]},
        "vendor_updated_at": {"type": ["string", "null"]},
        "reference_urls": {"type": ["array", "null"], "items": {"type": "string"}},
        # packageVulnerabilityDetails.cvss, verbatim: [{baseScore, scoringVector, version, source}].
        "cvss": {"type": ["array", "null"], "items": {"type": "object"}},
        # inspectorScoreDetails.adjustedCvss, verbatim.
        "adjusted_cvss": {"type": ["object", "null"]},
        # YES, NO or PARTIAL; YES or NO.
        "fix_available": {"type": ["string", "null"]},
        "exploit_available": {"type": ["string", "null"]},
        "last_known_exploit_at": {"type": ["string", "null"]},
        "epss_score": {"type": ["number", "null"]},
        # packageVulnerabilityDetails.vulnerablePackages, verbatim.
        "vulnerable_packages": {"type": ["array", "null"], "items": {"type": "object"}},
        # Derived: per vulnerable package, the computing_core package key it got or why none.
        "package_identities": {"type": ["array", "null"], "items": {"type": "object"}},
        "resource_type": {"type": ["string", "null"]},
        "resource_id": {"type": ["string", "null"]},
        # An ECR image's digest (sha256:<hex>), read from the resource id; null for any other resource.
        "image_digest": {"type": ["string", "null"]},
        # A CODE_VULNERABILITY finding's codeVulnerabilityDetails (null for a package finding).
        "cwes": {"type": ["array", "null"], "items": {"type": "string"}},
        "detector_id": {"type": ["string", "null"]},
        "detector_name": {"type": ["string", "null"]},
        "detector_tags": {"type": ["array", "null"], "items": {"type": "string"}},
        "rule_id": {"type": ["string", "null"]},
        "code_file_name": {"type": ["string", "null"]},
        "code_file_path": {"type": ["string", "null"]},
        "code_start_line": {"type": ["integer", "null"]},
        "code_end_line": {"type": ["integer", "null"]},
        "code_source_lambda_layer_arn": {"type": ["string", "null"]},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    finding_arn = models.CharField(max_length=2048, blank=True, default="", db_index=True)
    account_id = models.CharField(max_length=12, null=True, blank=True, default=None)
    region = models.CharField(max_length=32, null=True, blank=True, default=None)
    finding_type = models.CharField(max_length=32, null=True, blank=True, default=None)
    status = models.CharField(max_length=16, null=True, blank=True, default=None, db_index=True)
    severity = models.CharField(max_length=16, null=True, blank=True, default=None)
    inspector_score = models.FloatField(null=True, blank=True, default=None)
    title = models.CharField(max_length=1024, null=True, blank=True, default=None)
    description = models.TextField(null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    remediation = models.TextField(null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    remediation_url = models.CharField(max_length=2048, null=True, blank=True, default=None)
    first_observed_at = models.CharField(max_length=40, null=True, blank=True, default=None)
    last_observed_at = models.CharField(max_length=40, null=True, blank=True, default=None)
    updated_at = models.CharField(max_length=40, null=True, blank=True, default=None)
    vulnerability_id = models.CharField(max_length=128, null=True, blank=True, default=None, db_index=True)
    # Source: inspector2:ListFindings findings[].packageVulnerabilityDetails.relatedVulnerabilities.
    related_vulnerabilities = models.JSONField(null=True, blank=True, default=None)
    vulnerability_source = models.CharField(max_length=128, null=True, blank=True, default=None)
    source_url = models.CharField(max_length=2048, null=True, blank=True, default=None)
    vendor_severity = models.CharField(max_length=64, null=True, blank=True, default=None)
    vendor_created_at = models.CharField(max_length=40, null=True, blank=True, default=None)
    vendor_updated_at = models.CharField(max_length=40, null=True, blank=True, default=None)
    # Source: findings[].packageVulnerabilityDetails.referenceUrls.
    reference_urls = models.JSONField(null=True, blank=True, default=None)
    # Source: findings[].packageVulnerabilityDetails.cvss.
    cvss = models.JSONField(null=True, blank=True, default=None)
    # Source: findings[].inspectorScoreDetails.adjustedCvss.
    adjusted_cvss = models.JSONField(null=True, blank=True, default=None)
    fix_available = models.CharField(max_length=16, null=True, blank=True, default=None)
    exploit_available = models.CharField(max_length=16, null=True, blank=True, default=None)
    last_known_exploit_at = models.CharField(max_length=40, null=True, blank=True, default=None)
    epss_score = models.FloatField(null=True, blank=True, default=None)
    # Source: findings[].packageVulnerabilityDetails.vulnerablePackages.
    vulnerable_packages = models.JSONField(null=True, blank=True, default=None)
    # Source: derived from vulnerablePackages and the image's transient platform (inspector.py, package_identities).
    package_identities = models.JSONField(null=True, blank=True, default=None)
    resource_type = models.CharField(max_length=64, null=True, blank=True, default=None)
    resource_id = models.CharField(max_length=2048, null=True, blank=True, default=None)
    image_digest = models.CharField(max_length=71, null=True, blank=True, default=None)
    # Source: findings[].codeVulnerabilityDetails.cwes.
    cwes = models.JSONField(null=True, blank=True, default=None)
    detector_id = models.CharField(max_length=255, null=True, blank=True, default=None)
    detector_name = models.CharField(max_length=255, null=True, blank=True, default=None)
    # Source: findings[].codeVulnerabilityDetails.detectorTags.
    detector_tags = models.JSONField(null=True, blank=True, default=None)
    rule_id = models.CharField(max_length=255, null=True, blank=True, default=None)
    code_file_name = models.CharField(max_length=1024, null=True, blank=True, default=None)
    code_file_path = models.CharField(max_length=2048, null=True, blank=True, default=None)
    code_start_line = models.IntegerField(null=True, blank=True, default=None)
    code_end_line = models.IntegerField(null=True, blank=True, default=None)
    code_source_lambda_layer_arn = models.CharField(max_length=2048, null=True, blank=True, default=None)
    # AWS cannot tag a finding: always {} (tag_lanes.json, lane `none`).
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_inspector2_finding"

    def get_name(self) -> str:
        return self.name or self.vulnerability_id or self.finding_arn

    def __str__(self) -> str:
        return self.get_name()
