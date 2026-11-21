"""The findings reads aws-core-tap#264 added, against botocore's own models (``botocore.stub.Stubber``).

``test_security_findings.py`` drives the landing-zone reader through a paginating fake that accepts any
parameters. Here every request the new reads make (the closed-findings reads of GuardDuty, Security Hub and
Access Analyzer, and ``config:GetCustomRulePolicy``) and every canned response is validated against the
real service model, so a filter key, an operator or a member name AWS does not define fails the test.
No AWS call is made: a stubbed client never reaches the network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import botocore.session
import pytest
from botocore.stub import ANY, Stubber
from tap_plugin.aws_core.collectors.boto3_collector.findings import (
    ACCESS_ANALYZER_FINDING,
    CONFIG_RULE,
    GUARDDUTY_FINDING,
    HOLDS_ACCESS_ANALYZER_FINDING,
    SECURITYHUB_FINDING,
    SECURITYHUB_SEVERITY_LABELS,
    FindingsLimits,
)
from tap_plugin.aws_core.collectors.boto3_collector.landing_zone import (
    ACCESS_ANALYZER,
    GUARDDUTY_DETECTOR,
    SECURITYHUB_HUB,
    _Reader,
    regional_key,
)
from tap_plugin.aws_core.collectors.boto3_collector.regions import STATUS_ENABLED, RegionFacts

ACCOUNT = "111122223333"
REGION = "us-east-1"
DETECTOR_ID = "12abc34d567e8fa901bc2d34e56789f0"
FINDING_ID = "8cc0c1b0b8fbf4e0a1b2c3d4e5f60718"
FINDING_ARN = f"arn:aws:guardduty:{REGION}:{ACCOUNT}:detector/{DETECTOR_ID}/finding/{FINDING_ID}"
HUB_ARN = f"arn:aws:securityhub:{REGION}:{ACCOUNT}:hub/default"
PRODUCT_ARN = f"arn:aws:securityhub:{REGION}::product/aws/securityhub"
ANALYZER_ARN = f"arn:aws:access-analyzer:{REGION}:{ACCOUNT}:analyzer/account"
BUCKET_ARN = "arn:aws:s3:::example-bucket"
RULE_ARN = f"arn:aws:config:{REGION}:{ACCOUNT}:config-rule/config-rule-abc123"
FUNCTION_ARN = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:orders-handler"
GUARD = "rule tagged when resourceType == 'AWS::S3::Bucket' { configuration.tags !empty }"


class _Stubbed:
    """One stubbed client per service, handed to the reader as its client factory."""

    def __init__(self, *services: str) -> None:
        session = botocore.session.get_session()
        self.clients: dict[str, Any] = {}
        self.stubs: dict[str, Stubber] = {}
        for service in services:
            client = session.create_client(
                service, region_name=REGION, aws_access_key_id="testing", aws_secret_access_key="testing"
            )
            self.clients[service] = client
            self.stubs[service] = Stubber(client)

    def client_for(self, service: str, _region: str) -> Any:
        return self.clients[service]

    def __enter__(self) -> _Stubbed:
        for stub in self.stubs.values():
            stub.activate()
        return self

    def __exit__(self, *exc: object) -> None:
        for stub in self.stubs.values():
            stub.deactivate()

    def done(self) -> None:
        for stub in self.stubs.values():
            stub.assert_no_pending_responses()


def _reader(aws: _Stubbed, *, limits: FindingsLimits | None = None) -> _Reader:
    return _Reader(
        aws.client_for,
        account_id=ACCOUNT,
        partition="aws",
        regions=[REGION],
        facts={REGION: RegionFacts(REGION, "aws", "opt-in-not-required", STATUS_ENABLED, "test")},
        member_accounts=None,
        limits=limits,
    )


def _nodes(reader: _Reader, entity_type: str) -> list[dict[str, Any]]:
    return [n["node"] for n in reader.result.nodes if n["entity"]["entity_type"] == entity_type]


def _gd_finding(*, archived: bool) -> dict[str, Any]:
    return {
        "AccountId": ACCOUNT,
        "Arn": FINDING_ARN,
        "CreatedAt": "2026-11-01T00:00:00.000Z",
        "Description": "Lambda function orders-handler is querying a domain associated with cryptocurrency mining.",
        "Id": FINDING_ID,
        "Region": REGION,
        "SchemaVersion": "2.0",
        "Severity": 8.0,
        "Title": "Lambda function orders-handler called 203.0.113.9.",
        "Type": "CryptoCurrency:Lambda/BitcoinTool.B",
        "UpdatedAt": "2026-11-18T00:00:00.000Z",
        "Resource": {
            "ResourceType": "Lambda",
            "LambdaDetails": {"FunctionArn": FUNCTION_ARN, "FunctionName": "orders-handler"},
        },
        "Service": {
            "Archived": archived,
            "Count": 3,
            "Action": {
                "ActionType": "NETWORK_CONNECTION",
                "NetworkConnectionAction": {
                    "ConnectionDirection": "OUTBOUND",
                    "RemoteIpDetails": {"IpAddressV4": "203.0.113.9"},
                    "RemotePortDetails": {"Port": 443},
                },
            },
            "Evidence": {"ThreatIntelligenceDetails": [{"ThreatListName": "ProofPoint", "ThreatNames": ["miner"]}]},
        },
    }


@pytest.mark.spec("req-aws-landing-zone-findings-9")
def test_guardduty_reads_archived_findings_of_the_window_through_the_real_model() -> None:
    with _Stubbed("guardduty") as aws:
        stub = aws.stubs["guardduty"]
        active = {"service.archived": {"Equals": ["false"]}, "accountId": {"Equals": [ACCOUNT]}}
        stub.add_response(
            "list_findings",
            {"FindingIds": []},
            {
                "DetectorId": DETECTOR_ID,
                "FindingCriteria": {"Criterion": active},
                "SortCriteria": {"AttributeName": "severity", "OrderBy": "DESC"},
                "MaxResults": 50,
            },
        )
        stub.add_response(
            "list_findings",
            {"FindingIds": [FINDING_ID]},
            {
                "DetectorId": DETECTOR_ID,
                "FindingCriteria": {
                    "Criterion": {
                        "service.archived": {"Equals": ["true"]},
                        "accountId": {"Equals": [ACCOUNT]},
                        "updatedAt": {"GreaterThanOrEqual": ANY},
                    }
                },
                "SortCriteria": {"AttributeName": "updatedAt", "OrderBy": "DESC"},
                "MaxResults": 50,
            },
        )
        stub.add_response(
            "get_findings",
            {"Findings": [_gd_finding(archived=True)]},
            {"DetectorId": DETECTOR_ID, "FindingIds": [FINDING_ID]},
        )
        stub.add_response(
            "get_findings_statistics",
            {"FindingStatistics": {"GroupedBySeverity": []}},
            {"DetectorId": DETECTOR_ID, "GroupBy": "SEVERITY", "FindingCriteria": {"Criterion": active}, "MaxResults": 100},
        )
        reader = _reader(aws)
        key = regional_key(ACCOUNT, REGION, DETECTOR_ID)
        prepared = reader.findings.guardduty(REGION, DETECTOR_ID, key, GUARDDUTY_DETECTOR)
        prepared.emit()
        aws.done()
    assert prepared.parent_fields["active_finding_counts"] == {}, "an archived finding is not an active one"
    [node] = _nodes(reader, GUARDDUTY_FINDING)
    assert node["archived"] is True and node["title"] == "Lambda function orders-handler called 203.0.113.9."
    assert node["action"]["NetworkConnectionAction"]["RemoteIpDetails"] == {"IpAddressV4": "203.0.113.9"}
    assert node["evidence"] == {"ThreatIntelligenceDetails": [{"ThreatListName": "ProofPoint", "ThreatNames": ["miner"]}]}
    assert node["description"].startswith("Lambda function orders-handler") and node["resource_id"] == "orders-handler"


def test_guardduty_window_is_thirty_days_in_epoch_milliseconds() -> None:
    with _Stubbed("guardduty") as aws:
        stub = aws.stubs["guardduty"]
        seen: list[int] = []

        def capture(params: dict[str, Any], **_kw: Any) -> None:
            since = params.get("FindingCriteria", {}).get("Criterion", {}).get("updatedAt", {}).get("GreaterThanOrEqual")
            if since is not None:
                seen.append(since)

        aws.clients["guardduty"].meta.events.register("provide-client-params.guardduty.ListFindings", capture)
        for _ in range(2):
            stub.add_response("list_findings", {"FindingIds": []})
        stub.add_response("get_findings_statistics", {"FindingStatistics": {"GroupedBySeverity": []}})
        reader = _reader(aws)
        reader.findings.guardduty(REGION, DETECTOR_ID, regional_key(ACCOUNT, REGION, DETECTOR_ID), GUARDDUTY_DETECTOR)
        aws.done()
    [since] = seen
    expected = (datetime.now(UTC) - timedelta(days=30)).timestamp() * 1000
    assert abs(since - expected) < 60_000


def _sh_finding(record_state: str) -> dict[str, Any]:
    return {
        "SchemaVersion": "2018-10-08",
        "Id": f"arn:aws:securityhub:{REGION}:{ACCOUNT}:security-control/S3.8/finding/abc",
        "ProductArn": PRODUCT_ARN,
        "GeneratorId": "security-control/S3.8",
        "AwsAccountId": ACCOUNT,
        "Region": REGION,
        "Types": ["Software and Configuration Checks/Industry and Regulatory Standards"],
        "CreatedAt": "2026-11-01T00:00:00.000Z",
        "UpdatedAt": "2026-11-18T00:00:00.000Z",
        "Severity": {"Label": "HIGH", "Normalized": 70},
        "Title": "S3 general purpose buckets should block public access",
        "Description": "This control checks whether an S3 general purpose bucket blocks public access.",
        "Remediation": {"Recommendation": {"Text": "Turn on block public access", "Url": "https://docs.aws.amazon.com/"}},
        "Resources": [{"Type": "AwsS3Bucket", "Id": BUCKET_ARN}],
        "Compliance": {
            "Status": "PASSED",
            "StatusReasons": [{"ReasonCode": "CONFIG_EVALUATIONS_EMPTY", "Description": "No evaluations."}],
        },
        "Workflow": {"Status": "RESOLVED"},
        "RecordState": record_state,
        "FindingProviderFields": {"Severity": {"Label": "HIGH"}},
    }


@pytest.mark.spec("req-aws-landing-zone-findings-9")
def test_securityhub_reads_archived_findings_of_the_window_through_the_real_model() -> None:
    def filters(**extra: Any) -> dict[str, Any]:
        return {
            "AwsAccountId": [{"Value": ACCOUNT, "Comparison": "EQUALS"}],
            "Region": [{"Value": REGION, "Comparison": "EQUALS"}],
            **extra,
        }

    with _Stubbed("securityhub") as aws:
        stub = aws.stubs["securityhub"]
        for label in SECURITYHUB_SEVERITY_LABELS:
            stub.add_response(
                "get_findings",
                {"Findings": []},
                {
                    "Filters": filters(
                        RecordState=[{"Value": "ACTIVE", "Comparison": "EQUALS"}],
                        SeverityLabel=[{"Value": label, "Comparison": "EQUALS"}],
                    ),
                    "MaxResults": 100,
                },
            )
        stub.add_response(
            "get_findings",
            {"Findings": [_sh_finding("ARCHIVED")]},
            {
                "Filters": filters(
                    RecordState=[{"Value": "ARCHIVED", "Comparison": "EQUALS"}],
                    UpdatedAt=[{"DateRange": {"Value": 30, "Unit": "DAYS"}}],
                ),
                "SortCriteria": [{"Field": "UpdatedAt", "SortOrder": "desc"}],
                "MaxResults": 100,
            },
        )
        reader = _reader(aws)
        prepared, write = reader.findings.securityhub(REGION)
        write(HUB_ARN, SECURITYHUB_HUB, {})
        aws.done()
    assert prepared.parent_fields["active_finding_counts"] == dict.fromkeys(SECURITYHUB_SEVERITY_LABELS, 0)
    [node] = _nodes(reader, SECURITYHUB_FINDING)
    assert (node["record_state"], node["workflow_status"], node["severity_normalized"]) == ("ARCHIVED", "RESOLVED", 70)
    assert node["remediation"]["Recommendation"]["Text"] == "Turn on block public access"
    assert node["compliance_status_reasons"] == [{"ReasonCode": "CONFIG_EVALUATIONS_EMPTY", "Description": "No evaluations."}]
    assert node["types"] == ["Software and Configuration Checks/Industry and Regulatory Standards"]


@pytest.mark.spec("req-aws-landing-zone-findings-9")
def test_access_analyzer_reads_archived_and_resolved_findings_through_the_real_model() -> None:
    now = datetime.now(UTC)

    def summary(finding_id: str, status: str, updated: datetime) -> dict[str, Any]:
        return {
            "id": finding_id,
            "principal": {"AWS": "123456789012"},
            "action": ["s3:GetObject"],
            "resource": BUCKET_ARN,
            "isPublic": False,
            "resourceType": "AWS::S3::Bucket",
            "condition": {},
            "createdAt": now - timedelta(days=60),
            "analyzedAt": updated,
            "updatedAt": updated,
            "status": status,
            "resourceOwnerAccount": ACCOUNT,
        }

    with _Stubbed("accessanalyzer") as aws:
        stub = aws.stubs["accessanalyzer"]
        owner = {"resourceOwnerAccount": {"eq": [ACCOUNT]}}
        stub.add_response(
            "list_findings",
            {"findings": []},
            {"analyzerArn": ANALYZER_ARN, "filter": {"status": {"eq": ["ACTIVE"]}, **owner}, "maxResults": 100},
        )
        stub.add_response(
            "list_findings",
            {
                "findings": [
                    summary("resolved-recently", "RESOLVED", now - timedelta(days=2)),
                    summary("archived-long-ago", "ARCHIVED", now - timedelta(days=40)),
                ]
            },
            {"analyzerArn": ANALYZER_ARN, "filter": {"status": {"eq": ["ARCHIVED", "RESOLVED"]}, **owner}, "maxResults": 100},
        )
        reader = _reader(aws)
        prepared = reader.findings.access_analyzer(REGION, ANALYZER_ARN, "ACCOUNT", ACCESS_ANALYZER)
        prepared.emit()
        aws.done()
    assert prepared.parent_fields["active_finding_counts"] == {}
    assert [(n["finding_id"], n["status"]) for n in _nodes(reader, ACCESS_ANALYZER_FINDING)] == [
        ("resolved-recently", "RESOLVED")
    ]


@pytest.mark.spec("req-aws-landing-zone-findings-7")
@pytest.mark.parametrize("inline", [False, True], ids=["get_custom_rule_policy", "inline_policy_text"])
def test_config_rule_scope_parameters_and_guard_body_through_the_real_model(inline: bool) -> None:
    # botocore's model makes PolicyText required in the listing; an empty one sends the reader to
    # GetCustomRulePolicy, whose answer is the body.
    details: dict[str, Any] = {
        "PolicyRuntime": "guard-2.x.x",
        "PolicyText": GUARD if inline else "",
        "EnableDebugLogDelivery": False,
    }
    rule = {
        "ConfigRuleName": "tagged-buckets",
        "ConfigRuleArn": RULE_ARN,
        "ConfigRuleId": "config-rule-abc123",
        "Source": {
            "Owner": "CUSTOM_POLICY",
            "SourceDetails": [{"EventSource": "aws.config", "MessageType": "ConfigurationItemChangeNotification"}],
            "CustomPolicyDetails": details,
        },
        "Scope": {"ComplianceResourceTypes": ["AWS::S3::Bucket"], "TagKey": "env", "TagValue": "prod"},
        "InputParameters": '{"requiredTag": "owner"}',
        "ConfigRuleState": "ACTIVE",
    }
    with _Stubbed("config") as aws:
        stub = aws.stubs["config"]
        stub.add_response("describe_config_rules", {"ConfigRules": [rule]}, {})
        stub.add_response("describe_compliance_by_config_rule", {"ComplianceByConfigRules": []}, {})
        if not inline:
            stub.add_response("get_custom_rule_policy", {"PolicyText": GUARD}, {"ConfigRuleName": "tagged-buckets"})
        stub.add_response("list_tags_for_resource", {"Tags": [{"Key": "env", "Value": "prod"}]}, {"ResourceArn": RULE_ARN})
        reader = _reader(aws)
        reader.findings.config_rules(REGION)
        aws.done()
    [node] = _nodes(reader, CONFIG_RULE)
    assert node["scope"] == {"ComplianceResourceTypes": ["AWS::S3::Bucket"], "TagKey": "env", "TagValue": "prod"}
    assert node["input_parameters"] == {"requiredTag": "owner"}
    assert (node["policy_runtime"], node["policy_text"]) == ("guard-2.x.x", GUARD)
    assert node["tags"] == {"env": "prod"}


def _closed_summary(finding_id: str, status: str, updated: datetime) -> dict[str, Any]:
    return {
        "id": finding_id,
        "resource": BUCKET_ARN,
        "resourceType": "AWS::S3::Bucket",
        "condition": {},
        "createdAt": updated - timedelta(days=1),
        "analyzedAt": updated,
        "updatedAt": updated,
        "status": status,
        "resourceOwnerAccount": ACCOUNT,
    }


def _closed_filter() -> dict[str, Any]:
    return {"status": {"eq": ["ARCHIVED", "RESOLVED"]}, "resourceOwnerAccount": {"eq": [ACCOUNT]}}


@pytest.mark.spec("req-aws-landing-zone-findings-9")
def test_access_analyzer_old_closed_findings_first_do_not_use_up_the_limit() -> None:
    """Old ARCHIVED rows come first (the API documents no updatedAt sort); the window is applied per page,
    so only in-window findings count against an operator's limit and the recent one on page three is kept."""
    now = datetime.now(UTC)
    old = now - timedelta(days=90)
    with _Stubbed("accessanalyzer") as aws:
        stub = aws.stubs["accessanalyzer"]
        stub.add_response(
            "list_findings",
            {"findings": []},
            {"analyzerArn": ANALYZER_ARN, "filter": {"status": {"eq": ["ACTIVE"]}, "resourceOwnerAccount": {"eq": [ACCOUNT]}}, "maxResults": 100},
        )
        base = {"analyzerArn": ANALYZER_ARN, "filter": _closed_filter(), "maxResults": 100}
        stub.add_response(
            "list_findings",
            {"findings": [_closed_summary("old-1", "ARCHIVED", old), _closed_summary("old-2", "ARCHIVED", old)], "nextToken": "p2"},
            base,
        )
        stub.add_response(
            "list_findings",
            {"findings": [_closed_summary("old-3", "RESOLVED", old), _closed_summary("old-4", "ARCHIVED", old)], "nextToken": "p3"},
            {**base, "nextToken": "p2"},
        )
        stub.add_response(
            "list_findings",
            {"findings": [_closed_summary("new-1", "RESOLVED", now - timedelta(days=1)), _closed_summary("old-5", "ARCHIVED", old)]},
            {**base, "nextToken": "p3"},
        )
        reader = _reader(aws, limits=FindingsLimits(max_per_region=2))
        reader.findings.access_analyzer(REGION, ANALYZER_ARN, "ACCOUNT", ACCESS_ANALYZER).emit()
        aws.done()
    assert [n["finding_id"] for n in _nodes(reader, ACCESS_ANALYZER_FINDING)] == ["new-1"]
    [surface] = [s for s in reader.result.listings if s.edge_type == HOLDS_ACCESS_ANALYZER_FINDING]
    assert "truncated" not in surface.reasons, "every page was read and the limit was not reached"


@pytest.mark.spec("req-aws-landing-zone-findings-3", "req-aws-landing-zone-findings-9")
def test_access_analyzer_closed_read_reads_every_page_by_default() -> None:
    old = datetime.now(UTC) - timedelta(days=90)
    with _Stubbed("accessanalyzer") as aws:
        stub = aws.stubs["accessanalyzer"]
        stub.add_response("list_findings", {"findings": []})
        for page in range(1, 61):
            response: dict[str, Any] = {"findings": [_closed_summary(f"old-{page}", "ARCHIVED", old)]}
            if page < 60:
                response["nextToken"] = f"p{page + 1}"
            stub.add_response("list_findings", response)
        reader = _reader(aws)
        reader.findings.access_analyzer(REGION, ANALYZER_ARN, "ACCOUNT", ACCESS_ANALYZER).emit()
        aws.done()
    [surface] = [s for s in reader.result.listings if s.edge_type == HOLDS_ACCESS_ANALYZER_FINDING]
    assert "truncated" not in surface.reasons, "60 pages, past the old 50-page bound: read to the end"


@pytest.mark.spec("req-aws-landing-zone-findings-3", "req-aws-landing-zone-findings-9")
def test_access_analyzer_closed_read_stops_at_the_read_budget_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_plugin.aws_core.collectors.boto3_collector import landing_zone as lz

    clock = iter(range(0, 10_000, 10))
    monkeypatch.setattr(lz, "monotonic", lambda: next(clock))
    old = datetime.now(UTC) - timedelta(days=90)
    with _Stubbed("accessanalyzer") as aws:
        stub = aws.stubs["accessanalyzer"]
        stub.add_response("list_findings", {"findings": []})
        stub.add_response("list_findings", {"findings": [_closed_summary("old-1", "ARCHIVED", old)], "nextToken": "p2"})
        reader = _reader(aws, limits=FindingsLimits(read_budget_seconds=5))
        reader.findings.access_analyzer(REGION, ANALYZER_ARN, "ACCOUNT", ACCESS_ANALYZER).emit()
        aws.done()
    assert _nodes(reader, ACCESS_ANALYZER_FINDING) == []
    [surface] = [s for s in reader.result.listings if s.edge_type == HOLDS_ACCESS_ANALYZER_FINDING]
    assert surface.complete is False
    assert "budget of 5 seconds (findings_read_budget_seconds)" in surface.reasons["truncated"]


@pytest.mark.spec("req-aws-landing-zone-findings-3", "req-aws-core-secret-findings-settings-1")
def test_a_findings_read_runs_to_its_end_by_default_and_a_limit_is_shared_per_region() -> None:
    """No fixed cap (rulings Q125a and b): 1,500 findings, past the old 1,000, are all read. Under
    findings_max_per_region the service's reads in one region share the limit, and each says why it stopped."""
    from .test_landing_zone import FakeAws, paged

    pages = [[{"Id": f"f-{p}-{i}"} for i in range(100)] for p in range(15)]
    aws = FakeAws()
    aws.on("securityhub", "get_findings", paged("Findings", *pages))
    reader = _Reader(
        aws.client_for, account_id=ACCOUNT, partition="aws", regions=[REGION],
        facts={REGION: RegionFacts(REGION, "aws", "opt-in-not-required", STATUS_ENABLED, "test")}, member_accounts=None,
    )
    walk, truncated = reader.findings_walk("securityhub", REGION, "get_findings", "Findings")
    assert (len(walk.items), truncated, walk.truncation) == (1500, False, None)

    limited = _Reader(
        aws.client_for, account_id=ACCOUNT, partition="aws", regions=[REGION],
        facts={REGION: RegionFacts(REGION, "aws", "opt-in-not-required", STATUS_ENABLED, "test")}, member_accounts=None,
        limits=FindingsLimits(max_per_region=250),
    )
    first, cut = limited.findings_walk("securityhub", REGION, "get_findings", "Findings")
    assert (len(first.items), cut) == (250, True)
    assert first.truncation == "the read stopped at the per-region limit of 250 securityhub findings (findings_max_per_region)"
    second, cut = limited.findings_walk("securityhub", REGION, "get_findings", "Findings")
    assert (second.items, cut) == ([], True) and "was reached before this read" in str(second.truncation)
    other, cut = limited.findings_walk("securityhub", "us-west-2", "get_findings", "Findings")
    assert len(other.items) == 250, "another region has its own limit"


def test_the_limits_read_from_a_credential() -> None:
    assert FindingsLimits.of({}) == FindingsLimits(None, None)
    assert FindingsLimits.of({"findings_max_per_region": 5, "findings_read_budget_seconds": 30}) == FindingsLimits(5, 30)
    assert FindingsLimits.of({"findings_max_per_region": True}) == FindingsLimits(None, None)


@pytest.mark.spec("req-aws-core-secret-findings-settings-2")
def test_the_limits_are_one_fragment_on_both_kinds() -> None:
    import jsonschema

    from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred

    for key in ("findings_max_per_region", "findings_read_budget_seconds"):
        for schema in (cred.AWS_STATIC_SCHEMA, cred.AWS_ASSUMED_ROLE_SCHEMA):
            assert schema["properties"][key] is cred._FINDINGS_PROPS[key]
        static = {"access_key_id": "AKIA", "secret_access_key": "x"}
        jsonschema.validate({**static, key: 1}, cred.AWS_STATIC_SCHEMA)
        for bad in (0, "10", 1.5):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate({**static, key: bad}, cred.AWS_STATIC_SCHEMA)
