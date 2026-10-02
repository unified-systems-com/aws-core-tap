"""Security findings and Config rule compliance, collect-only (aws-core-tap#76, spec-aws-core-landing-zone.md).

The same three layers as ``test_landing_zone.py``, over the same canned GovCloud management account
(``govcloud()``), extended with findings: the reader against a PAGINATING fake (no grid); one run of
the real ``Boto3Collector`` whose batch the grid must accept; and the six new falsifiers against real
grid rows and a fake client. No AWS call is made.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from tap_plugin.aws_core.collectors.boto3_collector import findings as findings_mod
from tap_plugin.aws_core.collectors.boto3_collector.findings import (
    ACCESS_ANALYZER_FINDING,
    CONCERNS_RESOURCE,
    CONFIG_RULE,
    CONFORMANCE_PACK,
    EVALUATED_UNDER_STANDARD,
    GUARDDUTY_FINDING,
    HOLDS_ACCESS_ANALYZER_FINDING,
    HOLDS_GUARDDUTY_FINDING,
    HOLDS_SECURITYHUB_FINDING,
    HOLDS_STANDARDS_SUBSCRIPTION,
    HOSTS_CONFIG_RULE,
    HOSTS_CONFORMANCE_PACK,
    SECURITYHUB_FINDING,
    SECURITYHUB_SEVERITY_LABELS,
    STANDARDS_SUBSCRIPTION,
    analyzer_finding_key,
    guardduty_severity_label,
    redact_ips,
    securityhub_finding_key,
)
from tap_plugin.aws_core.collectors.boto3_collector.landing_zone import (
    ACCESS_ANALYZER,
    CONTAINMENT_SURFACES,
    GUARDDUTY_DETECTOR,
    READER,
    SECURITYHUB_HUB,
    regional_key,
)
from tap_plugin.aws_core.falsifiers import (
    AccessAnalyzerFindingFalsifier,
    ConfigRuleFalsifier,
    ConformancePackFalsifier,
    GuardDutyFindingFalsifier,
    SecurityHubFindingFalsifier,
    StandardsSubscriptionFalsifier,
)

from tap_grid.falsifier_testing import CASE_DROPPED, CASE_FORBIDDEN, CASE_PRESENT, CASE_REIDENTIFIED, run_four_cases
from tap_grid.falsifiers import DROPPED_FROM_OBSERVATION, PRESENT_AT_PROBE, UNDETERMINED, unsupported
from tap_grid.services import get_node

from .test_landing_zone import (
    ANALYZER_ARN,
    DETECTOR_ID,
    EAST,
    HUB_ARN,
    MGMT,
    PARTITION,
    REGIONS,
    UNUSED_ANALYZER_ARN,
    WEST,
    FakeAws,
    ProbeSession,
    _cand,
    _codes,
    _ctx,
    _edges,
    _err,
    _id,
    _nodes,
    _one,
    _parent,
    _regional,
    _row,
    _Session,
    _supported,
    by,
    collect,
    govcloud,
    paged,
)

DETECTOR_KEY = regional_key(MGMT, WEST, DETECTOR_ID)
INSTANCE_ID = "i-0abc1234def567890"
BUCKET_NAME = "gov-data-bucket"
BUCKET_ARN = f"arn:{PARTITION}:s3:::{BUCKET_NAME}"
ROLE_ARN = f"arn:{PARTITION}:iam::{MGMT}:role/CrossAccountAudit"
CANARY_IP = "198.51.100.77"
CANARY_TEXT = "canary-description-must-not-be-stored"

FSBP_ID = "standards/aws-foundational-security-best-practices/v/1.0.0"
NIST_ID = "standards/nist-800-53/v/5.0.0"
FSBP_SUB = f"arn:{PARTITION}:securityhub:{WEST}:{MGMT}:subscription/aws-foundational-security-best-practices/v/1.0.0"
NIST_SUB = f"arn:{PARTITION}:securityhub:{WEST}:{MGMT}:subscription/nist-800-53/v/5.0.0"
SH_PRODUCT = f"arn:{PARTITION}:securityhub:{WEST}::product/aws/securityhub"
RULE_ARN = f"arn:{PARTITION}:config:{WEST}:{MGMT}:config-rule/config-rule-aaaa11"
LINKED_RULE_ARN = (
    f"arn:{PARTITION}:config:{WEST}:{MGMT}:config-rule/aws-service-rule/securityhub.amazonaws.com/config-rule-bbbb22"
)
PACK_ARN = f"arn:{PARTITION}:config:{WEST}:{MGMT}:conformance-pack/gw-baseline/conformance-pack-cccc33"


def _gd_arn(finding_id: str) -> str:
    return f"arn:{PARTITION}:guardduty:{WEST}:{MGMT}:detector/{DETECTOR_ID}/finding/{finding_id}"


def _gd_finding(finding_id: str, severity: float, **extra: Any) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "Id": finding_id,
        "Arn": _gd_arn(finding_id),
        "AccountId": MGMT,
        "Region": WEST,
        "Type": "Recon:EC2/PortProbeUnprotectedPort",
        "Severity": severity,
        "Title": f"Unprotected port on EC2 instance {INSTANCE_ID} is being probed.",
        "Description": CANARY_TEXT,
        "CreatedAt": "2026-10-01T00:00:00.000Z",
        "UpdatedAt": "2026-10-02T00:00:00.000Z",
        "Resource": {"ResourceType": "Instance", "InstanceDetails": {"InstanceId": INSTANCE_ID}},
        "Service": {
            "Archived": False,
            "Count": 7,
            "EventFirstSeen": "2026-10-01T00:00:00.000Z",
            "EventLastSeen": "2026-10-02T00:00:00.000Z",
            "Action": {"NetworkConnectionAction": {"RemoteIpDetails": {"IpAddressV4": CANARY_IP}}},
        },
    }
    finding.update(extra)
    return finding


GD_FINDINGS = {
    "gd-high": _gd_finding("gd-high", 8.0),
    "gd-medium": _gd_finding(
        "gd-medium",
        5.0,
        Type="Policy:S3/BucketBlockPublicAccessDisabled",
        Resource={"ResourceType": "S3Bucket", "S3BucketDetails": [{"Name": BUCKET_NAME, "Arn": BUCKET_ARN}]},
    ),
    "gd-low": _gd_finding(
        "gd-low",
        2.0,
        Type="Recon:IAMUser/UserPermissions",
        Resource={
            "ResourceType": "AccessKey",
            "AccessKeyDetails": {"UserName": "ci-deployer", "UserType": "IAMUser", "AccessKeyId": "AKIAEXAMPLE"},
        },
    ),
}


def _sh_finding(finding_id: str, label: str, **extra: Any) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "SchemaVersion": "2018-10-08",
        "Id": f"arn:{PARTITION}:securityhub:{WEST}:{MGMT}:security-control/{finding_id}/finding/1",
        "ProductArn": SH_PRODUCT,
        "ProductName": "Security Hub",
        "GeneratorId": f"security-control/{finding_id}",
        "AwsAccountId": MGMT,
        "Region": WEST,
        "Title": f"Control {finding_id}",
        "Description": CANARY_TEXT,
        "Severity": {"Label": label},
        "Workflow": {"Status": "NEW"},
        "RecordState": "ACTIVE",
        "FirstObservedAt": "2026-09-30T00:00:00.000Z",
        "LastObservedAt": "2026-10-02T00:00:00.000Z",
        "CreatedAt": "2026-09-30T00:00:00.000Z",
        "UpdatedAt": "2026-10-02T00:00:00.000Z",
        "Resources": [{"Type": "AwsEc2Instance", "Id": f"arn:{PARTITION}:ec2:{WEST}:{MGMT}:instance/{INSTANCE_ID}"}],
        "Network": {"SourceIpV4": CANARY_IP},
    }
    finding.update(extra)
    return finding


SH_CONTROL = _sh_finding(
    "EC2.8",
    "HIGH",
    Compliance={
        "Status": "FAILED",
        "SecurityControlId": "EC2.8",
        "AssociatedStandards": [
            {"StandardsId": FSBP_ID},
            {"StandardsId": NIST_ID},
            {"StandardsId": "standards/not-enabled/v/1"},
        ],
    },
)
SH_PASSED = _sh_finding(
    "S3.1",
    "INFORMATIONAL",
    Compliance={"Status": "PASSED", "SecurityControlId": "S3.1", "AssociatedStandards": [{"StandardsId": FSBP_ID}]},
    Resources=[{"Type": "AwsS3Bucket", "Id": BUCKET_ARN}],
)


def _sh_handler(table: dict[str, list[list[dict[str, Any]]]]) -> Any:
    """Security Hub GetFindings: answers by the SeverityLabel filter, paginated."""

    def handler(region: str, kwargs: dict[str, Any]) -> Any:
        label = kwargs["Filters"]["SeverityLabel"][0]["Value"]
        pages = table.get(label) or [[]]
        return paged("Findings", *pages)(region, kwargs)

    return handler


def with_findings(aws: FakeAws | None = None) -> FakeAws:
    """``govcloud()`` with findings in us-gov-west-1, Config rules and a conformance pack."""
    aws = aws or govcloud()
    aws.on("guardduty", "list_findings", paged("FindingIds", ["gd-high", "gd-medium"], ["gd-low"]), region=WEST)
    aws.on(
        "guardduty",
        "get_findings",
        lambda _r, kw: {"Findings": [GD_FINDINGS[i] for i in kw["FindingIds"] if i in GD_FINDINGS]},
    )
    aws.on(
        "guardduty",
        "get_findings_statistics",
        {
            "FindingStatistics": {
                "GroupedBySeverity": [
                    {"Severity": 8.0, "TotalFindings": 4},
                    {"Severity": 7.5, "TotalFindings": 1},
                    {"Severity": 5.0, "TotalFindings": 2},
                    {"Severity": 2.0, "TotalFindings": 9},
                ]
            }
        },
    )
    aws.on(
        "securityhub",
        "get_enabled_standards",
        paged(
            "StandardsSubscriptions",
            [
                {
                    "StandardsSubscriptionArn": FSBP_SUB,
                    "StandardsArn": f"arn:{PARTITION}:securityhub:{WEST}::{FSBP_ID}",
                    "StandardsStatus": "READY",
                    "StandardsInput": {"secret-ish": "not stored"},
                }
            ],
            [
                {
                    "StandardsSubscriptionArn": NIST_SUB,
                    "StandardsArn": f"arn:{PARTITION}:securityhub:{WEST}::{NIST_ID}",
                    "StandardsStatus": "READY",
                    "StandardsControlsUpdatable": "READY_FOR_UPDATES",
                }
            ],
        ),
    )
    aws.on(
        "securityhub",
        "get_findings",
        _sh_handler({"HIGH": [[SH_CONTROL]], "INFORMATIONAL": [[], [SH_PASSED]]}),
        region=WEST,
    )
    aws.on(
        "accessanalyzer",
        "list_findings",
        paged(
            "findings",
            [
                {
                    "id": "aa-ext-1",
                    "resource": BUCKET_ARN,
                    "resourceType": "AWS::S3::Bucket",
                    "resourceOwnerAccount": MGMT,
                    "status": "ACTIVE",
                    "isPublic": False,
                    "principal": {"AWS": "999999999999"},
                    "action": ["s3:GetObject", "s3:ListBucket"],
                    "condition": {"aws:SourceIp": CANARY_IP},
                    "createdAt": "2026-10-01T00:00:00Z",
                    "analyzedAt": "2026-10-01T00:00:00Z",
                    "updatedAt": "2026-10-01T00:00:00Z",
                }
            ],
            token="nextToken",
        ),
    )
    aws.on(
        "accessanalyzer",
        "list_findings_v2",
        paged(
            "findings",
            [
                {
                    "id": "aa-unused-1",
                    "resource": ROLE_ARN,
                    "resourceType": "AWS::IAM::Role",
                    "resourceOwnerAccount": MGMT,
                    "status": "ACTIVE",
                    "findingType": "UnusedIAMRole",
                    "createdAt": "2026-10-01T00:00:00Z",
                    "analyzedAt": "2026-10-01T00:00:00Z",
                    "updatedAt": "2026-10-01T00:00:00Z",
                }
            ],
            token="nextToken",
        ),
    )
    aws.on(
        "config",
        "describe_config_rules",
        paged(
            "ConfigRules",
            [
                {
                    "ConfigRuleName": "s3-bucket-public-read-prohibited",
                    "ConfigRuleArn": RULE_ARN,
                    "ConfigRuleId": "config-rule-aaaa11",
                    "Description": "Checks public read",
                    "Source": {"Owner": "AWS", "SourceIdentifier": "S3_BUCKET_PUBLIC_READ_PROHIBITED"},
                    "InputParameters": '{"canary": "' + CANARY_TEXT + '"}',
                    "ConfigRuleState": "ACTIVE",
                }
            ],
            [
                {
                    "ConfigRuleName": "securityhub-ec2-imdsv2-check-1a2b3c",
                    "ConfigRuleArn": LINKED_RULE_ARN,
                    "Source": {"Owner": "AWS", "SourceIdentifier": "EC2_IMDSV2_CHECK"},
                    "ConfigRuleState": "ACTIVE",
                    "CreatedBy": "securityhub.amazonaws.com",
                }
            ],
        ),
        region=WEST,
    )
    aws.on(
        "config",
        "describe_compliance_by_config_rule",
        paged(
            "ComplianceByConfigRules",
            [
                {
                    "ConfigRuleName": "s3-bucket-public-read-prohibited",
                    "Compliance": {
                        "ComplianceType": "NON_COMPLIANT",
                        "ComplianceContributorCount": {"CappedCount": 3, "CapExceeded": False},
                    },
                }
            ],
        ),
        region=WEST,
    )
    aws.on(
        "config",
        "describe_conformance_packs",
        paged(
            "ConformancePackDetails",
            [
                {
                    "ConformancePackName": "gw-baseline",
                    "ConformancePackArn": PACK_ARN,
                    "ConformancePackId": "conformance-pack-cccc33",
                    "DeliveryS3Bucket": "gw-conformance",
                    "ConformancePackInputParameters": [{"ParameterName": "p", "ParameterValue": CANARY_TEXT}],
                }
            ],
        ),
        region=WEST,
    )
    aws.on(
        "config",
        "get_conformance_pack_compliance_summary",
        lambda _r, kw: {
            "ConformancePackComplianceSummaryList": [
                {"ConformancePackName": n, "ConformancePackComplianceStatus": "NON_COMPLIANT"}
                for n in kw["ConformancePackNames"]
            ]
        },
    )
    return aws


def _surface_dict(read: Any, edge_type: str, subject: str) -> dict[str, Any]:
    return _parent(read, edge_type, subject).surface([])


# ---------------------------------------------------------------------------
# GuardDuty
# ---------------------------------------------------------------------------


class TestGuardDuty:
    @pytest.mark.spec("req-aws-landing-zone-findings-1", "req-aws-landing-zone-findings-5")
    def test_active_findings_are_contained_by_the_detector(self) -> None:
        aws = with_findings()
        read = collect(aws)
        findings = {n["node"]["finding_id"]: n["node"] for n in _nodes(read, GUARDDUTY_FINDING)}
        assert set(findings) == {"gd-high", "gd-medium", "gd-low"}, "ListFindings is read to its last page"
        high = findings["gd-high"]
        assert (high["severity"], high["severity_label"], high["count"], high["archived"]) == (8.0, "HIGH", 7, False)
        assert (high["resource_type"], high["resource_id"], high["detector_id"]) == (
            "Instance",
            INSTANCE_ID,
            DETECTOR_ID,
        )
        assert high["first_seen"] == "2026-10-01T00:00:00.000Z" and high["tags"] == {}
        detector = _id(GUARDDUTY_DETECTOR, DETECTOR_KEY)
        assert {f for f, _ in _edges(read, HOLDS_GUARDDUTY_FINDING)} == {detector}
        assert len(_edges(read, HOLDS_GUARDDUTY_FINDING)) == 3

    @pytest.mark.spec("req-aws-landing-zone-findings-1")
    def test_the_read_is_unarchived_own_account_most_severe_first(self) -> None:
        aws = with_findings()
        collect(aws)
        [first, *_] = [kw for s, r, op, kw in aws.calls if (s, op) == ("guardduty", "list_findings")]
        assert first["FindingCriteria"] == {
            "Criterion": {"service.archived": {"Equals": ["false"]}, "accountId": {"Equals": [MGMT]}}
        }
        assert first["SortCriteria"] == {"AttributeName": "severity", "OrderBy": "DESC"}
        assert first["MaxResults"] == 50
        gets = [kw for s, r, op, kw in aws.calls if (s, op) == ("guardduty", "get_findings")]
        assert all(len(kw["FindingIds"]) <= 50 for kw in gets)

    @pytest.mark.spec("req-aws-landing-zone-findings-2")
    def test_references_to_the_instance_bucket_and_user_by_natural_key(self) -> None:
        read = collect(with_findings())
        targets = {to for _f, to in _edges(read, CONCERNS_RESOURCE)}
        assert _id("aws_core__aws_ec2_instance", INSTANCE_ID) in targets
        assert _id("aws_core__aws_s3_bucket", BUCKET_ARN) in targets
        assert _id("aws_core__aws_iam_user", f"arn:{PARTITION}:iam::{MGMT}:user/ci-deployer") in targets

    @pytest.mark.spec("req-aws-landing-zone-findings-4")
    def test_detector_carries_exact_severity_totals_from_statistics(self) -> None:
        detector = _one(collect(with_findings()), GUARDDUTY_DETECTOR)
        assert detector["active_finding_counts"] == {"HIGH": 5, "MEDIUM": 2, "LOW": 9}
        assert (detector["active_finding_counts_complete"], detector["active_findings_truncated"]) == (True, False)

    @pytest.mark.spec("req-aws-landing-zone-findings-3", "req-aws-landing-zone-findings-4")
    def test_cap_truncates_and_failed_statistics_fall_back_to_a_lower_bound(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(findings_mod, "FINDINGS_CAP", 2)
        aws = with_findings()
        aws.on("guardduty", "get_findings_statistics", _err("BadRequestException"))
        read = collect(aws)
        assert {n["node"]["finding_id"] for n in _nodes(read, GUARDDUTY_FINDING)} == {"gd-high", "gd-medium"}
        detector = _one(read, GUARDDUTY_DETECTOR)
        assert detector["active_finding_counts"] == {"HIGH": 1, "MEDIUM": 1}
        assert (detector["active_finding_counts_complete"], detector["active_findings_truncated"]) == (False, True)
        surface = _surface_dict(read, HOLDS_GUARDDUTY_FINDING, _id(GUARDDUTY_DETECTOR, DETECTOR_KEY))
        assert surface["enumeration_complete"] is False
        assert surface["reasons"]["truncated"].startswith("truncated: the read stopped at the cap of 2")

    @pytest.mark.spec("req-aws-landing-zone-findings-3", "req-grid-reconcile-evidence-4")
    def test_surface_is_filtered_uncontrolled_and_never_complete(self) -> None:
        read = collect(with_findings())
        surface = _surface_dict(read, HOLDS_GUARDDUTY_FINDING, _id(GUARDDUTY_DETECTOR, DETECTOR_KEY))
        assert surface["filter"] == f"guardduty:ListFindings service.archived=false, accountId={MGMT}"
        assert surface["filter_control"] is None
        assert surface["enumeration_complete"] is False and surface["scope_authorized"] is True
        assert surface["reasons"]["enumeration_complete"].startswith("filter_uncontrolled")
        assert "truncated" not in surface["reasons"]
        assert surface["count_observed"] == 3 and surface["admitted"] is True

    def test_a_failed_get_findings_withdraws_admitted(self) -> None:
        aws = with_findings()
        aws.on("guardduty", "get_findings", _err("InternalServerErrorException"))
        read = collect(aws)
        assert _nodes(read, GUARDDUTY_FINDING) == []
        surface = _parent(read, HOLDS_GUARDDUTY_FINDING, _id(GUARDDUTY_DETECTOR, DETECTOR_KEY))
        assert surface.admitted is False

    def test_a_failed_listing_leaves_truncation_unknown(self) -> None:
        aws = with_findings()
        aws.on(
            "guardduty",
            "list_findings",
            paged("FindingIds", ["gd-high"], _err("InternalServerErrorException")),
            region=WEST,
        )
        read = collect(aws)
        detector = _one(read, GUARDDUTY_DETECTOR)
        assert detector["active_findings_truncated"] is None
        assert detector["active_finding_counts_complete"] is True, "statistics still answered"
        surface = _parent(read, HOLDS_GUARDDUTY_FINDING, _id(GUARDDUTY_DETECTOR, DETECTOR_KEY))
        assert surface.complete is False and "truncated" not in surface.reasons

    @pytest.mark.parametrize(
        ("score", "label"),
        [
            (9.0, "CRITICAL"),
            (8.9, "HIGH"),
            (7.0, "HIGH"),
            (6.9, "MEDIUM"),
            (4.0, "MEDIUM"),
            (3.9, "LOW"),
            (1.0, "LOW"),
            (None, ""),
            (True, ""),
        ],
    )
    def test_severity_bands(self, score: Any, label: str) -> None:
        assert guardduty_severity_label(score) == label


# ---------------------------------------------------------------------------
# Security Hub
# ---------------------------------------------------------------------------


class TestSecurityHub:
    @pytest.mark.spec("req-aws-landing-zone-findings-1", "req-aws-landing-zone-findings-6")
    def test_control_finding_with_compliance_and_its_standards(self) -> None:
        read = collect(with_findings())
        findings = {n["node"]["security_control_id"]: n["node"] for n in _nodes(read, SECURITYHUB_FINDING)}
        assert set(findings) == {"EC2.8", "S3.1"}, "every label's listing is read to its last page"
        control = findings["EC2.8"]
        assert (control["compliance_status"], control["severity_label"], control["workflow_status"]) == (
            "FAILED",
            "HIGH",
            "NEW",
        )
        assert control["record_state"] == "ACTIVE" and control["product_name"] == "Security Hub"
        assert control["associated_standards"] == sorted([FSBP_ID, NIST_ID, "standards/not-enabled/v/1"])
        assert control["resource_types"] == ["AwsEc2Instance"]
        key = securityhub_finding_key(SH_PRODUCT, SH_CONTROL["Id"])
        evaluated = {to for f, to in _edges(read, EVALUATED_UNDER_STANDARD) if f == _id(SECURITYHUB_FINDING, key)}
        assert evaluated == {_id(STANDARDS_SUBSCRIPTION, FSBP_SUB), _id(STANDARDS_SUBSCRIPTION, NIST_SUB)}
        concerns = {to for f, to in _edges(read, CONCERNS_RESOURCE) if f == _id(SECURITYHUB_FINDING, key)}
        assert concerns == {_id("aws_core__aws_ec2_instance", INSTANCE_ID)}
        hub = _id(SECURITYHUB_HUB, HUB_ARN)
        assert {f for f, _ in _edges(read, HOLDS_SECURITYHUB_FINDING)} == {hub}

    @pytest.mark.spec("req-aws-landing-zone-findings-6")
    def test_enabled_standards_are_nodes_contained_by_the_hub(self) -> None:
        read = collect(with_findings())
        subs = {n["node"]["subscription_arn"]: n["node"] for n in _nodes(read, STANDARDS_SUBSCRIPTION)}
        assert set(subs) == {FSBP_SUB, NIST_SUB}
        assert subs[FSBP_SUB]["standards_id"] == FSBP_ID and subs[FSBP_SUB]["status"] == "READY"
        assert "StandardsInput" not in json.dumps(subs)
        surface = _parent(read, HOLDS_STANDARDS_SUBSCRIPTION, _id(SECURITYHUB_HUB, HUB_ARN))
        assert (surface.complete, surface.admitted, surface.count, surface.filter) == (True, True, 2, None)

    @pytest.mark.spec("req-aws-landing-zone-findings-1", "req-aws-landing-zone-findings-4")
    def test_one_read_per_label_most_severe_first_with_exact_counts(self) -> None:
        aws = with_findings()
        read = collect(aws)
        labels = [
            kw["Filters"]["SeverityLabel"][0]["Value"]
            for s, r, op, kw in aws.calls
            if (s, op, r) == ("securityhub", "get_findings", WEST) and "NextToken" not in kw
        ]
        assert labels == list(SECURITYHUB_SEVERITY_LABELS)
        [first, *_] = [kw for s, r, op, kw in aws.calls if (s, op) == ("securityhub", "get_findings")]
        assert first["Filters"]["AwsAccountId"] == [{"Value": MGMT, "Comparison": "EQUALS"}]
        assert first["Filters"]["Region"] == [{"Value": WEST, "Comparison": "EQUALS"}]
        assert first["Filters"]["RecordState"] == [{"Value": "ACTIVE", "Comparison": "EQUALS"}]
        hub = _one(read, SECURITYHUB_HUB)
        assert hub["active_finding_counts"] == {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 0, "LOW": 0, "INFORMATIONAL": 1}
        assert (hub["active_finding_counts_complete"], hub["active_findings_truncated"]) == (True, False)

    @pytest.mark.spec("req-aws-landing-zone-findings-3")
    def test_the_cap_is_shared_across_labels_and_drops_the_least_severe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(findings_mod, "FINDINGS_CAP", 1)
        aws = with_findings()
        read = collect(aws)
        assert [n["node"]["security_control_id"] for n in _nodes(read, SECURITYHUB_FINDING)] == ["EC2.8"]
        hub = _one(read, SECURITYHUB_HUB)
        assert (hub["active_finding_counts_complete"], hub["active_findings_truncated"]) == (False, True)
        surface = _surface_dict(read, HOLDS_SECURITYHUB_FINDING, _id(SECURITYHUB_HUB, HUB_ARN))
        assert surface["enumeration_complete"] is False and "truncated" in surface["reasons"]

    def test_a_withheld_hub_writes_no_findings_and_no_surface(self) -> None:
        aws = with_findings()
        aws.on("securityhub", "list_tags_for_resource", _err("AccessDeniedException"))
        read = collect(aws)
        assert _nodes(read, SECURITYHUB_HUB) == []
        assert _nodes(read, SECURITYHUB_FINDING) == [] and _nodes(read, STANDARDS_SUBSCRIPTION) == []
        assert not [
            s for s in read.listings if s.edge_type in (HOLDS_SECURITYHUB_FINDING, HOLDS_STANDARDS_SUBSCRIPTION)
        ]

    def test_not_subscribed_region_reads_no_findings(self) -> None:
        aws = with_findings()
        collect(aws)
        assert not [c for c in aws.calls if c[0] == "securityhub" and c[1] == EAST and c[2] == "get_findings"]


# ---------------------------------------------------------------------------
# Access Analyzer
# ---------------------------------------------------------------------------


class TestAccessAnalyzer:
    @pytest.mark.spec("req-aws-landing-zone-findings-1", "req-aws-landing-zone-findings-7")
    def test_external_access_findings_carry_the_condition_summary_keys_only(self) -> None:
        aws = with_findings()
        read = collect(aws)
        finding = next(
            n["node"] for n in _nodes(read, ACCESS_ANALYZER_FINDING) if n["node"]["analyzer_arn"] == ANALYZER_ARN
        )
        assert (finding["finding_type"], finding["resource_type"], finding["resource_arn"]) == (
            "ExternalAccess",
            "AWS::S3::Bucket",
            BUCKET_ARN,
        )
        assert finding["condition_keys"] == ["aws:SourceIp"]
        assert finding["principal"] == {"AWS": "999999999999"} and finding["is_public"] is False
        assert finding["actions"] == ["s3:GetObject", "s3:ListBucket"]
        calls = {
            (op, kw["analyzerArn"]): kw
            for s, r, op, kw in aws.calls
            if s == "accessanalyzer" and op.startswith("list_findings")
        }
        assert set(calls) == {("list_findings", ANALYZER_ARN), ("list_findings_v2", UNUSED_ANALYZER_ARN)}
        assert calls[("list_findings", ANALYZER_ARN)]["filter"] == {
            "status": {"eq": ["ACTIVE"]},
            "resourceOwnerAccount": {"eq": [MGMT]},
        }

    @pytest.mark.spec("req-aws-landing-zone-findings-2", "req-aws-landing-zone-findings-4")
    def test_unused_access_findings_through_v2_with_counts_by_type(self) -> None:
        read = collect(with_findings())
        key = analyzer_finding_key(UNUSED_ANALYZER_ARN, "aa-unused-1")
        finding = next(
            n["node"] for n in _nodes(read, ACCESS_ANALYZER_FINDING) if n["node"]["finding_id"] == "aa-unused-1"
        )
        assert finding["finding_type"] == "UnusedIAMRole"
        assert (finding["condition_keys"], finding["principal"], finding["is_public"]) == (None, None, None)
        assert (_id(ACCESS_ANALYZER_FINDING, key), _id("aws_core__aws_iam_role", ROLE_ARN)) in _edges(
            read, CONCERNS_RESOURCE
        )
        analyzers = {n["node"]["analyzer_arn"]: n["node"] for n in _nodes(read, ACCESS_ANALYZER)}
        assert analyzers[UNUSED_ANALYZER_ARN]["active_finding_counts"] == {"UnusedIAMRole": 1}
        assert analyzers[ANALYZER_ARN]["active_finding_counts"] == {"ExternalAccess": 1}
        assert analyzers[ANALYZER_ARN]["active_finding_counts_complete"] is True
        surface = _surface_dict(read, HOLDS_ACCESS_ANALYZER_FINDING, _id(ACCESS_ANALYZER, UNUSED_ANALYZER_ARN))
        assert (
            surface["filter"].startswith("accessanalyzer:ListFindingsV2") and surface["enumeration_complete"] is False
        )


# ---------------------------------------------------------------------------
# Config rules and conformance packs
# ---------------------------------------------------------------------------


class TestConfigRules:
    @pytest.mark.spec("req-aws-landing-zone-findings-8")
    def test_rules_with_compliance_contained_by_the_footprint(self) -> None:
        read = collect(with_findings())
        rules = {n["node"]["rule_arn"]: n["node"] for n in _nodes(read, CONFIG_RULE)}
        assert set(rules) == {RULE_ARN, LINKED_RULE_ARN}, "the service-linked rule on page two is listed"
        rule = rules[RULE_ARN]
        assert (rule["source_owner"], rule["source_identifier"], rule["compliance_type"]) == (
            "AWS",
            "S3_BUCKET_PUBLIC_READ_PROHIBITED",
            "NON_COMPLIANT",
        )
        assert (rule["non_compliant_resource_count"], rule["non_compliant_count_capped"]) == (3, False)
        assert rules[LINKED_RULE_ARN]["created_by"] == "securityhub.amazonaws.com"
        assert rules[LINKED_RULE_ARN]["compliance_type"] == "", "read to its end and not named: not evaluated"
        assert rule["tags"] == {"aws-control-tower": "managed-by-control-tower"}
        surface = _regional(read, HOSTS_CONFIG_RULE, WEST)
        assert (surface["enumeration_complete"], surface["count_observed"]) == (True, 2)
        assert (
            _regional(read, HOSTS_CONFIG_RULE, EAST)["enumeration_complete"],
            _regional(read, HOSTS_CONFIG_RULE, EAST)["count_observed"],
        ) == (True, 0)
        assert len(_edges(read, "HOSTS_CONFIG_RULE__aws_core")) == 2

    def test_failed_compliance_read_is_null_never_compliant(self) -> None:
        aws = with_findings()
        aws.on("config", "describe_compliance_by_config_rule", _err("AccessDeniedException"), region=WEST)
        read = collect(aws)
        assert {n["node"]["compliance_type"] for n in _nodes(read, CONFIG_RULE)} == {None}
        assert "CONFIG_RULE_COMPLIANCE_INCOMPLETE" in _codes(read)

    @pytest.mark.spec("req-aws-landing-zone-findings-8")
    def test_conformance_pack_with_its_compliance_summary(self) -> None:
        read = collect(with_findings())
        pack = _one(read, CONFORMANCE_PACK)
        assert (pack["pack_name"], pack["compliance_status"], pack["delivery_s3_bucket"]) == (
            "gw-baseline",
            "NON_COMPLIANT",
            "gw-conformance",
        )
        assert _regional(read, HOSTS_CONFORMANCE_PACK, WEST)["enumeration_complete"] is True

    def test_failed_summary_is_null(self) -> None:
        aws = with_findings()
        aws.on("config", "get_conformance_pack_compliance_summary", _err("ThrottlingException"))
        assert _one(collect(aws), CONFORMANCE_PACK)["compliance_status"] is None


# ---------------------------------------------------------------------------
# Declarations, sensitivity, triple
# ---------------------------------------------------------------------------


_NEW_TYPES = (
    GUARDDUTY_FINDING,
    SECURITYHUB_FINDING,
    STANDARDS_SUBSCRIPTION,
    ACCESS_ANALYZER_FINDING,
    CONFIG_RULE,
    CONFORMANCE_PACK,
)


class TestDeclarations:
    @pytest.mark.spec("req-aws-landing-zone-findings-7", "req-aws-collector-manifest-6")
    def test_no_description_ip_condition_value_or_parameter_is_stored(self) -> None:
        aws = with_findings()
        titled = {
            **GD_FINDINGS,
            "gd-high": _gd_finding("gd-high", 8.0, Title=f"Instance is communicating with {CANARY_IP} (ip-10-0-1-5)."),
        }
        aws.on(
            "guardduty",
            "get_findings",
            lambda _r, kw: {"Findings": [titled[i] for i in kw["FindingIds"] if i in titled]},
        )
        noisy = {
            **SH_CONTROL,
            "Title": f"Traffic from {CANARY_IP} and 2001:db8::7 to the instance",
            "Resources": [*SH_CONTROL["Resources"], {"Type": "Other", "Id": "2001:db8::7"}],
        }
        aws.on(
            "securityhub", "get_findings", _sh_handler({"HIGH": [[noisy]], "INFORMATIONAL": [[SH_PASSED]]}), region=WEST
        )
        read = collect(aws)
        dumped = json.dumps([n["node"] for n in read.nodes])
        for planted in (CANARY_IP, CANARY_TEXT, "not stored", "2001:db8::7", "ip-10-0-1-5"):
            assert planted not in dumped, planted
        gd = next(n["node"] for n in _nodes(read, GUARDDUTY_FINDING) if n["node"]["finding_id"] == "gd-high")
        assert gd["title"] == "Instance is communicating with [ip] ([ip])."
        sh = next(n["node"] for n in _nodes(read, SECURITYHUB_FINDING) if n["node"]["security_control_id"] == "EC2.8")
        assert sh["title"] == "Traffic from [ip] and [ip] to the instance" and "[ip]" in sh["resource_ids"]

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("probe from 203.0.113.9.", "probe from [ip]."),
            ("host ip-10-0-1-5.ec2.internal", "host [ip].ec2.internal"),
            ("v6 fe80::1 and 2001:db8:0:0:0:0:0:1", "v6 [ip] and [ip]"),
            (f"arn:{PARTITION}:s3:::bucket", f"arn:{PARTITION}:s3:::bucket"),
            (
                f"arn:{PARTITION}:ec2:{WEST}:{MGMT}:instance/{INSTANCE_ID}",
                f"arn:{PARTITION}:ec2:{WEST}:{MGMT}:instance/{INSTANCE_ID}",
            ),
            ("at 12:30:45 on 999.1.1.1", "at 12:30:45 on 999.1.1.1"),
            (f"AWS::::Account:{MGMT}", f"AWS::::Account:{MGMT}"),
            ("cafe bad face 1234 a:b", "cafe bad face 1234 a:b"),
            ("mapped ::ffff:192.0.2.1 here", "mapped [ip] here"),
            ("embedded 2001:db8::192.0.2.1 tail", "embedded [ip] tail"),
            ("plain 2001:db8:85a3::8a2e:370:7334 v6", "plain [ip] v6"),
            ("v6 at sentence end fe80::1.", "v6 at sentence end [ip]."),
            ("plain 10.20.30.40 v4", "plain [ip] v4"),
            ("node ip-172-31-5-9 down", "node [ip] down"),
            ("No address here: just text, 3.5 stars, v1.2.3", "No address here: just text, 3.5 stars, v1.2.3"),
        ],
    )
    def test_redact_ips(self, text: str, expected: str) -> None:
        assert redact_ips(text) == expected

    @pytest.mark.spec("req-aws-collector-tags-14")
    def test_every_new_type_is_emitted_with_one_lane_and_a_sensitivity_row(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.organizations import reader_sensitivity

        here = Path(__file__).resolve().parents[1] / "collectors" / "boto3_collector"
        lanes = [r for r in json.loads((here / "tag_lanes.json").read_text())["lanes"] if r["reader"] == READER]
        read = collect(with_findings())
        emitted = {n["entity"]["entity_type"] for n in read.nodes}
        assert set(_NEW_TYPES) <= emitted
        declared = reader_sensitivity(READER)
        for entity_type in _NEW_TYPES:
            assert [r["entity_type"] for r in lanes].count(entity_type) == 1, entity_type
            assert declared[entity_type]["status"] in ("reviewed_may_contain", "reviewed_none_known"), entity_type

    @pytest.mark.spec("req-aws-core-contained-type-triple-1", "req-aws-landing-zone-findings-5")
    def test_every_observed_parent_records_every_containment_surface(self) -> None:
        read = collect(with_findings())
        recorded = {(s.subject, s.edge_type) for s in read.listings} | {
            (s["subject"], s["edge_type"]) for s in read.regional_surfaces
        }
        for node in read.nodes:
            for edge in CONTAINMENT_SURFACES.get(node["entity"]["entity_type"], ()):
                assert (node["entity"]["entity_id"], edge) in recorded, (node["entity"]["entity_type"], edge)
        for region in REGIONS:
            for edge in (HOSTS_CONFIG_RULE, HOSTS_CONFORMANCE_PACK):
                assert _regional(read, edge, region)
        # No findings surface is ever complete.
        for listing in read.listings:
            if listing.edge_type in (HOLDS_GUARDDUTY_FINDING, HOLDS_SECURITYHUB_FINDING, HOLDS_ACCESS_ANALYZER_FINDING):
                assert listing.complete is False and listing.filter

    def test_every_new_call_is_in_the_walked_tables(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.landing_zone import PAGINATED_OPERATIONS, SINGLE_OPERATIONS

        aws = with_findings()
        collect(aws)
        used = {(svc, op) for svc, _r, op, _kw in aws.calls}
        assert used <= set(PAGINATED_OPERATIONS) | set(SINGLE_OPERATIONS)
        assert {
            ("guardduty", "get_findings_statistics"),
            ("accessanalyzer", "list_findings_v2"),
            ("config", "get_conformance_pack_compliance_summary"),
        } <= used

    def test_recorded_surfaces_validate_against_the_completeness_schema(self) -> None:
        import jsonschema

        from tap_grid import completeness

        schema_path = Path(completeness.__file__).resolve().parent / "schemas" / "completeness.schema.json"
        schema = json.loads(schema_path.read_text())
        surface_schema = {**schema["$defs"]["surface"], "$defs": schema["$defs"]}
        authored = dict(surface_schema)
        authored["required"] = [r for r in surface_schema["required"] if r not in ("applied", "reconcilable")]
        read = collect(with_findings())
        for listing in read.listings:
            jsonschema.validate(listing.surface([]), authored)


# ---------------------------------------------------------------------------
# One real collector run: the grid accepts the batch
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_collector_run_lands_every_new_type(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
    from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred
    from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector
    from tap_plugin.aws_core.collectors.boto3_collector.identity import node_entity_id

    from tap_cares.collectors.config import CollectorConfig
    from tap_cares.secrets.models import Secret, SecretRef

    aws = with_findings()
    aws.on(
        "ec2",
        "describe_regions",
        {"Regions": [{"RegionName": r, "OptInStatus": "opt-in-not-required"} for r in REGIONS]},
    )
    aws.on("organizations", "describe_organization", _err("AWSOrganizationsNotInUseException"))
    secret = Secret(
        ref=SecretRef(scope="aws_core", key="boto_collector"),
        kind="aws_static_access_key",
        description="test",
        data={"access_key_id": "AKIA", "secret_access_key": "shh", "regions_allowed": REGIONS},
        metadata={},
        source_path=Path("/dev/null"),
    )
    monkeypatch.setattr(cred, "resolve_secret", lambda _ref: secret)
    monkeypatch.setattr(collector_mod, "build_session", lambda _data: _Session(aws))
    monkeypatch.setattr(
        collector_mod, "client_factory", lambda _s, region: lambda service: aws.client_for(service, region)
    )
    monkeypatch.setattr(collector_mod, "caller_account_id", lambda *a, **k: MGMT)
    collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
    collector.run()
    assert collector.results["error"] == []
    assert not [w for w in collector.results["warn"] if w["message_code"] == "LANDING_ZONE_READ_FAILED"]
    for entity_type, key in (
        (GUARDDUTY_FINDING, _gd_arn("gd-high")),
        (SECURITYHUB_FINDING, securityhub_finding_key(SH_PRODUCT, SH_CONTROL["Id"])),
        (STANDARDS_SUBSCRIPTION, FSBP_SUB),
        (ACCESS_ANALYZER_FINDING, analyzer_finding_key(ANALYZER_ARN, "aa-ext-1")),
        (CONFIG_RULE, RULE_ARN),
        (CONFORMANCE_PACK, PACK_ARN),
    ):
        assert get_node(node_entity_id(entity_type, key)) is not None, entity_type
    detector = get_node(node_entity_id(GUARDDUTY_DETECTOR, DETECTOR_KEY))
    assert detector.active_finding_counts == {"HIGH": 5, "MEDIUM": 2, "LOW": 9}
    filtered = [s for s in collector._surfaces if s.get("filter")]
    assert filtered and all(s["enumeration_complete"] is False and s["filter_control"] is None for s in filtered)


# ---------------------------------------------------------------------------
# The falsifiers — real grid rows, fake client
# ---------------------------------------------------------------------------


def _verdict(falsifier: Any, entity_type: str, payload: dict[str, Any], aws: FakeAws) -> Any:
    [verdict] = falsifier(session=ProbeSession(aws), allowed_regions=REGIONS, account_id=MGMT).batch_falsify(
        [_cand(_row(entity_type, payload), entity_type)], _ctx()
    )
    return verdict


@pytest.mark.django_db
class TestFindingFalsifiers:
    @pytest.mark.spec("req-aws-landing-zone-findings-5", "req-grid-reconcile-falsifier-6")
    def test_guardduty_finding(self) -> None:
        payload = {
            "name": "f",
            "finding_arn": _gd_arn("gd-high"),
            "finding_id": "gd-high",
            "detector_id": DETECTOR_ID,
            "region": WEST,
        }
        archived = _gd_finding("gd-high", 8.0)
        archived["Service"] = {"Archived": True}
        for answer, expected in (
            ({"Findings": [_gd_finding("gd-high", 8.0)]}, PRESENT_AT_PROBE),
            ({"Findings": []}, DROPPED_FROM_OBSERVATION),
            ({"Findings": [archived]}, DROPPED_FROM_OBSERVATION),
            (_err("AccessDeniedException"), UNDETERMINED),
            (_err("BadRequestException"), UNDETERMINED),
        ):
            aws = FakeAws()
            aws.on("guardduty", "get_findings", answer)
            verdict = _verdict(GuardDutyFindingFalsifier, GUARDDUTY_FINDING, payload, aws)
            assert verdict.verdict == expected, (answer, verdict.note)
            assert unsupported(verdict) is None

    @pytest.mark.spec("req-aws-landing-zone-findings-5")
    def test_securityhub_finding(self) -> None:
        payload = {"name": "f", "finding_id": SH_CONTROL["Id"], "product_arn": SH_PRODUCT, "region": WEST}
        for answer, expected in (
            ({"Findings": [SH_CONTROL]}, PRESENT_AT_PROBE),
            ({"Findings": []}, DROPPED_FROM_OBSERVATION),
            ({"Findings": [{**SH_CONTROL, "RecordState": "ARCHIVED"}]}, DROPPED_FROM_OBSERVATION),
            (_err("InvalidAccessException"), UNDETERMINED),
        ):
            aws = FakeAws()
            aws.on("securityhub", "get_findings", answer)
            verdict = _verdict(SecurityHubFindingFalsifier, SECURITYHUB_FINDING, payload, aws)
            assert verdict.verdict == expected, (answer, verdict.note)
            assert unsupported(verdict) is None

    @pytest.mark.spec("req-aws-landing-zone-findings-5")
    def test_access_analyzer_finding(self) -> None:
        payload = {"name": "f", "finding_id": "aa-ext-1", "analyzer_arn": ANALYZER_ARN}
        for answer, expected in (
            ({"id": "aa-ext-1", "status": "ACTIVE"}, PRESENT_AT_PROBE),
            ({"id": "aa-ext-1", "status": "ARCHIVED"}, DROPPED_FROM_OBSERVATION),
            ({"id": "aa-ext-1", "status": "RESOLVED"}, DROPPED_FROM_OBSERVATION),
            (_err("ResourceNotFoundException"), DROPPED_FROM_OBSERVATION),
            (_err("AccessDeniedException"), UNDETERMINED),
        ):
            aws = FakeAws()
            aws.on("accessanalyzer", "get_finding_v2", answer)
            verdict = _verdict(AccessAnalyzerFindingFalsifier, ACCESS_ANALYZER_FINDING, payload, aws)
            assert verdict.verdict == expected, (answer, verdict.note)
            assert unsupported(verdict) is None
            assert {r for _s, r, _o, _k in aws.calls} == {WEST}

    @pytest.mark.spec("req-aws-landing-zone-findings-5", "req-aws-collector-pagination-1")
    @pytest.mark.parametrize(
        ("falsifier", "entity_type", "payload", "op", "key", "item"),
        [
            (
                StandardsSubscriptionFalsifier,
                STANDARDS_SUBSCRIPTION,
                {"name": "s", "subscription_arn": FSBP_SUB},
                ("securityhub", "get_enabled_standards"),
                "StandardsSubscriptions",
                lambda a: {"StandardsSubscriptionArn": a},
            ),
            (
                ConfigRuleFalsifier,
                CONFIG_RULE,
                {"name": "r", "rule_arn": RULE_ARN},
                ("config", "describe_config_rules"),
                "ConfigRules",
                lambda a: {"ConfigRuleArn": a},
            ),
        ],
        ids=["standards_subscription", "config_rule"],
    )
    def test_listing_falsifiers(
        self, falsifier: Any, entity_type: str, payload: dict[str, Any], op: tuple[str, str], key: str, item: Any
    ) -> None:
        arn = next(v for k, v in payload.items() if k.endswith("_arn"))
        for handler, expected in (
            (paged(key, [item("arn:other")], [item(arn)]), PRESENT_AT_PROBE),
            (paged(key, [item("arn:other")]), DROPPED_FROM_OBSERVATION),
            (paged(key, [], _err("ThrottlingException")), UNDETERMINED),
            (_err("AccessDeniedException"), UNDETERMINED),
        ):
            aws = FakeAws()
            aws.on(*op, handler)
            verdict = _verdict(falsifier, entity_type, payload, aws)
            assert verdict.verdict == expected, (expected, verdict.note)
            assert unsupported(verdict) is None

    @pytest.mark.spec("req-aws-landing-zone-findings-5", "req-grid-reconcile-falsifier-6")
    def test_conformance_pack_four_cases(self) -> None:
        def pack_arn(i: int) -> str:
            return f"arn:{PARTITION}:config:{WEST}:{MGMT}:conformance-pack/pack{i}/conformance-pack-{i:06d}"

        arns = {
            case: pack_arn(i) for i, case in enumerate((CASE_PRESENT, CASE_DROPPED, CASE_FORBIDDEN, CASE_REIDENTIFIED))
        }
        cases = {
            case: _cand(
                _row(CONFORMANCE_PACK, {"name": "p", "pack_arn": arn, "pack_name": arn.rsplit("/", 2)[-2]}),
                CONFORMANCE_PACK,
            )
            for case, arn in arns.items()
        }
        table = {
            "pack0": {"ConformancePackDetails": [{"ConformancePackArn": arns[CASE_PRESENT]}]},
            "pack1": _err("NoSuchConformancePackException"),
            "pack2": _err("AccessDeniedException"),
            "pack3": {"ConformancePackDetails": [{"ConformancePackArn": pack_arn(99)}]},
        }
        aws = FakeAws()
        aws.on("config", "describe_conformance_packs", by(lambda kw: kw["ConformancePackNames"][0], table))
        falsifier = ConformancePackFalsifier(session=ProbeSession(aws), allowed_regions=REGIONS, account_id=MGMT)
        _supported(run_four_cases(falsifier, cases, _ctx()))


def test_new_falsifiers_are_wired_and_construct_with_no_arguments() -> None:
    import tomllib

    toml = tomllib.loads((Path(__file__).resolve().parents[1] / "tap-plugin.toml").read_text())
    expected = {
        GUARDDUTY_FINDING: GuardDutyFindingFalsifier,
        SECURITYHUB_FINDING: SecurityHubFindingFalsifier,
        STANDARDS_SUBSCRIPTION: StandardsSubscriptionFalsifier,
        ACCESS_ANALYZER_FINDING: AccessAnalyzerFindingFalsifier,
        CONFIG_RULE: ConfigRuleFalsifier,
        CONFORMANCE_PACK: ConformancePackFalsifier,
    }
    for entity_type, cls in expected.items():
        assert toml["falsifiers"][entity_type] == f"{cls.__module__}.{cls.__qualname__}", entity_type
        assert cls() is not None, entity_type
