"""Amazon Inspector v2 findings, collect-only (aws-core-tap#261, spec-aws-core-landing-zone.md).

No Inspector-enabled account was available, so every read is driven through ``botocore.stub.Stubber``: each
request the reader makes and each canned response is validated against botocore's own ``inspector2`` model, so a
filter key, a sort field or a member name AWS does not define fails the test. No AWS call is made.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import botocore.session
import pytest
from botocore.stub import ANY, Stubber
from tap_plugin.aws_core.collectors.boto3_collector import inspector as inspector_mod
from tap_plugin.aws_core.collectors.boto3_collector.containment import footprint_key
from tap_plugin.aws_core.collectors.boto3_collector.findings import CONCERNS_RESOURCE
from tap_plugin.aws_core.collectors.boto3_collector.identity import composite_natural_key, node_ref
from tap_plugin.aws_core.collectors.boto3_collector.inspector import (
    CONCERNS_TARGETS,
    ECR_REPOSITORY,
    EC2_INSTANCE,
    HOSTS_INSPECTOR2_FINDING,
    IMAGE_HOST,
    INSPECTOR_FINDING,
    LAMBDA_FUNCTION,
    concerned_resource,
    image_digest_of,
)
from tap_plugin.aws_core.collectors.boto3_collector.landing_zone import FOOTPRINT, _Reader
from tap_plugin.aws_core.collectors.boto3_collector.regions import STATUS_ENABLED, RegionFacts

ACCOUNT = "111122223333"
REGION = "us-gov-west-1"
PARTITION = "aws-us-gov"
DIGEST = "sha256:" + "ab" * 32
REPO_ARN = f"arn:{PARTITION}:ecr:{REGION}:{ACCOUNT}:repository/team/app"
IMAGE_ID = f"{REPO_ARN}/{DIGEST}"
FUNCTION_ARN = f"arn:{PARTITION}:lambda:{REGION}:{ACCOUNT}:function:orders-handler"
INSTANCE_ID = "i-0abc1234def567890"
OBSERVED = datetime(2026, 11, 1, tzinfo=UTC)


def finding_arn(n: int) -> str:
    return f"arn:{PARTITION}:inspector2:{REGION}:{ACCOUNT}:finding/{n:032x}"


def package_finding(n: int, resource: dict[str, Any], *, status: str = "ACTIVE", **extra: Any) -> dict[str, Any]:
    """A PACKAGE_VULNERABILITY finding as botocore's Finding shape allows it."""
    finding: dict[str, Any] = {
        "findingArn": finding_arn(n),
        "awsAccountId": ACCOUNT,
        "type": "PACKAGE_VULNERABILITY",
        "title": "CVE-2026-0001 - openssl",
        "description": "A flaw in openssl allows a remote attacker to read memory.",
        "remediation": {"recommendation": {"text": "Upgrade openssl.", "Url": "https://example.com/advice"}},
        "severity": "HIGH",
        "firstObservedAt": OBSERVED,
        "lastObservedAt": OBSERVED,
        "updatedAt": OBSERVED,
        "status": status,
        "resources": [resource],
        "inspectorScore": 7.5,
        "inspectorScoreDetails": {
            "adjustedCvss": {
                "scoreSource": "NVD",
                "cvssSource": "NVD",
                "version": "3.1",
                "score": 7.5,
                "scoringVector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
                "adjustments": [],
            }
        },
        "packageVulnerabilityDetails": {
            "vulnerabilityId": "CVE-2026-0001",
            "source": "NVD",
            "sourceUrl": "https://nvd.nist.gov/vuln/detail/CVE-2026-0001",
            "vendorSeverity": "HIGH",
            "relatedVulnerabilities": ["GHSA-aaaa-bbbb-cccc"],
            "referenceUrls": ["https://example.com/ref"],
            "cvss": [
                {"baseScore": 7.5, "scoringVector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N", "version": "3.1", "source": "NVD"},
                {"baseScore": 5.0, "scoringVector": "AV:N/AC:L/Au:N/C:P/I:N/A:N", "version": "2.0", "source": "NVD"},
            ],
            "vulnerablePackages": [
                {
                    "name": "openssl",
                    "version": "3.0.2",
                    "release": "1.amzn2023",
                    "epoch": 1,
                    "arch": "X86_64",
                    "packageManager": "OS",
                    "filePath": "/usr/lib64/libssl.so.3",
                    "fixedInVersion": "1:3.0.8-1.amzn2023",
                    "remediation": "dnf update openssl",
                }
            ],
        },
        "fixAvailable": "YES",
        "exploitAvailable": "NO",
        "epss": {"score": 0.0123},
    }
    finding.update(extra)
    return finding


def ecr_image() -> dict[str, Any]:
    return {
        "type": "AWS_ECR_CONTAINER_IMAGE",
        "id": IMAGE_ID,
        "partition": PARTITION,
        "region": REGION,
        "details": {
            "awsEcrContainerImage": {
                "repositoryName": "team/app",
                "imageHash": DIGEST,
                "registry": ACCOUNT,
                "imageTags": ["canary-tag-must-not-be-stored"],
                "platform": "AMAZON_LINUX_2023",
            }
        },
    }


def ec2_instance() -> dict[str, Any]:
    return {
        "type": "AWS_EC2_INSTANCE",
        "id": INSTANCE_ID,
        "region": REGION,
        "details": {"awsEc2Instance": {"ipV4Addresses": ["198.51.100.77"], "keyName": "canary-key-must-not-be-stored"}},
    }


def lambda_function() -> dict[str, Any]:
    return {"type": "AWS_LAMBDA_FUNCTION", "id": f"{FUNCTION_ARN}:$LATEST", "region": REGION}


class _Stubbed:
    """One stubbed inspector2 client, handed to the reader as its client factory."""

    def __init__(self) -> None:
        self.client = botocore.session.get_session().create_client(
            "inspector2", region_name=REGION, aws_access_key_id="testing", aws_secret_access_key="testing"
        )
        self.stub = Stubber(self.client)

    def client_for(self, service: str, _region: str) -> Any:
        assert service == "inspector2", service
        return self.client

    def __enter__(self) -> _Stubbed:
        self.stub.activate()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stub.deactivate()


def _reader(
    aws: _Stubbed, *, held: bool = False, types: tuple[str, ...] | None = ("PACKAGE_VULNERABILITY",), **kw: Any
) -> _Reader:
    return _Reader(
        aws.client_for,
        account_id=ACCOUNT,
        partition=PARTITION,
        regions=[REGION],
        facts={REGION: RegionFacts(REGION, PARTITION, "opt-in-not-required", STATUS_ENABLED, "test")},
        member_accounts=None,
        host_held=lambda _digest: held,
        inspector_finding_types=types,
        **kw,
    )


def _eq(value: str) -> list[dict[str, str]]:
    return [{"comparison": "EQUALS", "value": value}]


def expect_status(stub: Stubber, status: str = "ENABLED") -> None:
    state = {"status": status, "errorCode": "ALREADY_ENABLED", "errorMessage": "ok"}
    stub.add_response(
        "batch_get_account_status",
        {"accounts": [{"accountId": ACCOUNT, "state": state, "resourceState": {"ec2": state, "ecr": state}}]},
        {"accountIds": [ACCOUNT]},
    )


def expect_totals(stub: Stubber, finding_type: str, counts: dict[str, int]) -> None:
    stub.add_response(
        "list_finding_aggregations",
        {
            "aggregationType": "FINDING_TYPE",
            "responses": [{"findingTypeAggregation": {"accountId": ACCOUNT, "severityCounts": counts}}],
        },
        {
            "aggregationType": "FINDING_TYPE",
            "accountIds": _eq(ACCOUNT),
            "aggregationRequest": {"findingTypeAggregation": {"findingType": finding_type}},
        },
    )


def expect_list(
    stub: Stubber,
    finding_type: str,
    status: str,
    findings: list[dict[str, Any]],
    token: str | None = None,
    *,
    page_token: str | None = None,
    since: Any = None,
) -> None:
    criteria: dict[str, Any] = {
        "awsAccountId": _eq(ACCOUNT),
        "findingType": _eq(finding_type),
        "findingStatus": _eq(status),
    }
    if status == "CLOSED" or since is not None:
        criteria["updatedAt"] = [{"startInclusive": ANY if since is None or status == "CLOSED" else since}]
    request: dict[str, Any] = {
        "filterCriteria": criteria,
        "sortCriteria": {"field": "SEVERITY" if status == "ACTIVE" else "LAST_OBSERVED_AT", "sortOrder": "DESC"},
        "maxResults": 100,
    }
    if page_token:
        request["nextToken"] = page_token
    response: dict[str, Any] = {"findings": findings}
    if token:
        response["nextToken"] = token
    stub.add_response("list_findings", response, request)


def _nodes(reader: _Reader, entity_type: str) -> list[dict[str, Any]]:
    return [n["node"] for n in reader.result.nodes if n["entity"]["entity_type"] == entity_type]


def _edges(reader: _Reader, edge_type: str) -> set[tuple[str, str]]:
    return {(e["edge"]["from_ref"], e["edge"]["to_ref"]) for e in reader.result.edges if e["edge"]["edge_type"] == edge_type}


def _listing(reader: _Reader, relation: str) -> Any:
    [listing] = [lst for lst in reader.result.listings if lst.relation == relation]
    return listing


@pytest.fixture
def package_only() -> None:
    """The tests below read the package type alone (``inspector_finding_types``), so each stubs exactly its calls."""


@pytest.mark.spec("req-aws-landing-zone-inspector-1", "req-aws-landing-zone-inspector-2", "req-aws-landing-zone-inspector-3")
def test_package_findings_are_read_through_the_real_model(package_only: None) -> None:
    findings = [package_finding(1, ecr_image()), package_finding(2, ec2_instance()), package_finding(3, lambda_function())]
    closed = package_finding(4, ec2_instance(), status="CLOSED")
    with _Stubbed() as aws:
        expect_status(aws.stub)
        expect_totals(aws.stub, "PACKAGE_VULNERABILITY", {"all": 3, "high": 3, "critical": 0})
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "ACTIVE", findings)
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "CLOSED", [closed])
        reader = _reader(aws)
        reader.inspector.read(REGION)
        aws.stub.assert_no_pending_responses()

    rows = {n["finding_arn"]: n for n in _nodes(reader, INSPECTOR_FINDING)}
    assert set(rows) == {finding_arn(n) for n in (1, 2, 3, 4)}
    image = rows[finding_arn(1)]
    assert image["status"] == "ACTIVE" and rows[finding_arn(4)]["status"] == "CLOSED"
    assert image["vulnerability_id"] == "CVE-2026-0001"
    assert image["related_vulnerabilities"] == ["GHSA-aaaa-bbbb-cccc"]
    assert [c["version"] for c in image["cvss"]] == ["3.1", "2.0"], "every CVSS entry is kept"
    assert image["adjusted_cvss"]["score"] == 7.5 and image["inspector_score"] == 7.5
    assert image["epss_score"] == 0.0123 and image["fix_available"] == "YES" and image["exploit_available"] == "NO"
    [package] = image["vulnerable_packages"]
    assert package["filePath"] == "/usr/lib64/libssl.so.3" and package["fixedInVersion"] == "1:3.0.8-1.amzn2023"
    assert image["image_digest"] == DIGEST and image["remediation"] == "Upgrade openssl."
    assert image["first_observed_at"] == "2026-11-01T00:00:00Z"
    stored = repr(rows)
    for canary in ("canary-tag-must-not-be-stored", "canary-key-must-not-be-stored", "198.51.100.77", "AMAZON_LINUX"):
        assert canary not in stored, f"{canary}: resources[].details must not be stored"

    concerns = _edges(reader, CONCERNS_RESOURCE)
    assert (node_ref(INSPECTOR_FINDING, finding_arn(1)), node_ref(ECR_REPOSITORY, REPO_ARN)) in concerns
    host = node_ref(IMAGE_HOST, composite_natural_key({"realm": "oci-digest", "stable_id": DIGEST}))
    assert (node_ref(INSPECTOR_FINDING, finding_arn(1)), host) in concerns
    assert (node_ref(INSPECTOR_FINDING, finding_arn(2)), node_ref(EC2_INSTANCE, INSTANCE_ID)) in concerns
    assert (node_ref(INSPECTOR_FINDING, finding_arn(3)), node_ref(LAMBDA_FUNCTION, FUNCTION_ARN)) in concerns
    [host_node] = _nodes(reader, IMAGE_HOST)
    assert host_node == {"realm": "oci-digest", "stable_id": DIGEST, "kind": "container"}

    footprint = node_ref(FOOTPRINT, footprint_key(ACCOUNT, REGION))
    assert len(_edges(reader, HOSTS_INSPECTOR2_FINDING)) == 4
    assert all(f == footprint for f, _ in _edges(reader, HOSTS_INSPECTOR2_FINDING))
    fields = reader.result.footprint_fields[REGION]
    assert fields["inspector2_status"] == "ENABLED"
    assert fields["inspector2_resource_status"] == {"ec2": "ENABLED", "ecr": "ENABLED"}
    assert fields["inspector2_active_finding_counts"] == {"PACKAGE_VULNERABILITY": {"ALL": 3, "HIGH": 3, "CRITICAL": 0}}
    assert fields["inspector2_active_finding_counts_complete"] is True
    assert fields["inspector2_active_findings_truncated"] is False

    listing = _listing(reader, "account_region.inspector2_findings")
    surface = listing.surface(["batch"])
    assert surface["enumeration_complete"] is False and surface["filter_control"] is None
    assert "findingType in PACKAGE_VULNERABILITY" in surface["filter"]
    assert "truncated" not in listing.reasons


@pytest.mark.spec("req-aws-landing-zone-inspector-3")
def test_a_held_image_host_is_sent_with_its_key_and_kind_only(package_only: None) -> None:
    with _Stubbed() as aws:
        expect_status(aws.stub)
        expect_totals(aws.stub, "PACKAGE_VULNERABILITY", {"all": 1})
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "ACTIVE", [package_finding(1, ecr_image())])
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "CLOSED", [])
        reader = _reader(aws, held=True)
        reader.inspector.read(REGION)
    [envelope] = [n for n in reader.result.nodes if n["entity"]["entity_type"] == IMAGE_HOST]
    assert envelope["node"] == {"realm": "oci-digest", "stable_id": DIGEST, "kind": "container"}
    assert "name" not in envelope["entity"]


@pytest.mark.spec("req-aws-landing-zone-inspector-4")
def test_a_limited_read_stops_and_says_truncated(package_only: None) -> None:
    from tap_plugin.aws_core.collectors.boto3_collector.findings import FindingsLimits

    with _Stubbed() as aws:
        expect_status(aws.stub)
        expect_totals(aws.stub, "PACKAGE_VULNERABILITY", {"all": 40, "critical": 40})
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "ACTIVE", [package_finding(1, ec2_instance())], token="t1")
        expect_list(
            aws.stub,
            "PACKAGE_VULNERABILITY",
            "ACTIVE",
            [package_finding(2, ec2_instance()), package_finding(3, ec2_instance())],
            token="t2",
            page_token="t1",
        )
        reader = _reader(aws, limits=FindingsLimits(max_per_region=2))
        reader.inspector.read(REGION)
        aws.stub.assert_no_pending_responses()
    assert len(_nodes(reader, INSPECTOR_FINDING)) == 2, "the closed read finds the limit spent and makes no call"
    fields = reader.result.footprint_fields[REGION]
    assert fields["inspector2_active_finding_counts"] == {"PACKAGE_VULNERABILITY": {"ALL": 40, "CRITICAL": 40}}
    assert fields["inspector2_active_findings_truncated"] is True
    listing = _listing(reader, "account_region.inspector2_findings")
    assert listing.reasons["truncated"].startswith(
        "truncated: the read stopped at the per-region limit of 2 inspector2 findings (findings_max_per_region)"
    )
    assert reader.result.read_through == {}, "a truncated read writes no watermark"
    assert listing.surface(["b"])["enumeration_complete"] is False


@pytest.mark.spec("req-aws-landing-zone-inspector-5")
def test_a_disabled_account_reads_no_finding_and_says_why() -> None:
    with _Stubbed() as aws:
        expect_status(aws.stub, "DISABLED")
        reader = _reader(aws, types=None)
        reader.inspector.read(REGION)
        aws.stub.assert_no_pending_responses()
    assert _nodes(reader, INSPECTOR_FINDING) == []
    fields = reader.result.footprint_fields[REGION]
    assert fields["inspector2_status"] == "DISABLED"
    assert all(counts == {} for counts in fields["inspector2_active_finding_counts"].values())
    for _edge, relation in reader.inspector.containment():
        listing = _listing(reader, relation)
        assert listing.reasons["not_scanning"].startswith("inspector_disabled")
        assert listing.surface(["b"])["enumeration_complete"] is False
    assert "INSPECTOR2_NOT_SCANNING" in {n.code for n in reader.result.notices}


@pytest.mark.spec("req-aws-landing-zone-inspector-5")
def test_a_failed_status_read_is_null_and_still_reads(package_only: None) -> None:
    with _Stubbed() as aws:
        aws.stub.add_client_error("batch_get_account_status", "AccessDeniedException", http_status_code=403)
        expect_totals(aws.stub, "PACKAGE_VULNERABILITY", {"all": 0})
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "ACTIVE", [])
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "CLOSED", [])
        reader = _reader(aws)
        reader.inspector.read(REGION)
        aws.stub.assert_no_pending_responses()
    fields = reader.result.footprint_fields[REGION]
    assert fields["inspector2_status"] is None and fields["inspector2_resource_status"] is None


@pytest.mark.spec("req-aws-landing-zone-inspector-4")
def test_a_failed_aggregation_leaves_totals_incomplete(package_only: None) -> None:
    with _Stubbed() as aws:
        expect_status(aws.stub)
        aws.stub.add_client_error("list_finding_aggregations", "ThrottlingException", http_status_code=429)
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "ACTIVE", [])
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "CLOSED", [])
        reader = _reader(aws)
        reader.inspector.read(REGION)
    fields = reader.result.footprint_fields[REGION]
    assert fields["inspector2_active_finding_counts"] is None
    assert fields["inspector2_active_finding_counts_complete"] is False


@pytest.mark.spec("req-aws-landing-zone-inspector-3")
@pytest.mark.parametrize(
    ("resource_type", "resource_id", "expected"),
    [
        ("AWS_EC2_INSTANCE", INSTANCE_ID, (EC2_INSTANCE, INSTANCE_ID)),
        ("AWS_EC2_INSTANCE", f"arn:{PARTITION}:ec2:{REGION}:{ACCOUNT}:instance/{INSTANCE_ID}", (EC2_INSTANCE, INSTANCE_ID)),
        ("AWS_LAMBDA_FUNCTION", FUNCTION_ARN, (LAMBDA_FUNCTION, FUNCTION_ARN)),
        ("AWS_LAMBDA_FUNCTION", f"{FUNCTION_ARN}:$LATEST", (LAMBDA_FUNCTION, FUNCTION_ARN)),
        ("AWS_LAMBDA_FUNCTION", f"{FUNCTION_ARN}:3", None),
        ("AWS_ECR_REPOSITORY", REPO_ARN, (ECR_REPOSITORY, REPO_ARN)),
        ("AWS_ECR_CONTAINER_IMAGE", IMAGE_ID, (ECR_REPOSITORY, REPO_ARN)),
        ("CODE_REPOSITORY", "github/acme/app", None),
        ("AWS_EC2_INSTANCE", "", None),
    ],
)
def test_the_resource_a_finding_concerns(resource_type: str, resource_id: str, expected: Any) -> None:
    assert concerned_resource(resource_type, resource_id) == expected


def test_image_digest_only_for_an_image() -> None:
    assert image_digest_of("AWS_ECR_CONTAINER_IMAGE", IMAGE_ID) == DIGEST
    assert image_digest_of("AWS_ECR_REPOSITORY", REPO_ARN) is None
    assert image_digest_of("AWS_ECR_CONTAINER_IMAGE", f"{REPO_ARN}/sha256:short") is None


def test_concerns_targets_equal_the_model_declaration() -> None:
    from tap_plugin.aws_core.models.aws_inspector2_finding import AwsInspector2Finding

    declared = {
        node["type"]
        for rule in AwsInspector2Finding.OUTBOUND_EDGES
        if {"type": CONCERNS_RESOURCE} in rule["edges"]
        for node in rule["nodes"]
    }
    assert declared == set(CONCERNS_TARGETS)


@pytest.mark.spec("req-aws-landing-zone-inspector-7")
def test_every_finding_type_is_read_by_default_and_the_setting_trims() -> None:
    every = _reader(_Stubbed(), types=None)
    assert every.inspector.selected_types() == every.inspector.finding_types()
    assert {"PACKAGE_VULNERABILITY", "CODE_VULNERABILITY"} <= set(every.inspector.selected_types())
    trimmed = _reader(_Stubbed(), types=("CODE_VULNERABILITY",))
    assert trimmed.inspector.selected_types() == ("CODE_VULNERABILITY",)
    assert set(inspector_mod.FINDING_TYPES) == {"PACKAGE_VULNERABILITY", "CODE_VULNERABILITY", "NETWORK_REACHABILITY"}


@pytest.mark.spec("req-aws-landing-zone-inspector-1", "req-aws-landing-zone-inspector-2")
def test_a_code_finding_keeps_its_cwes_detector_rule_and_location() -> None:
    code = {
        "findingArn": finding_arn(9),
        "awsAccountId": ACCOUNT,
        "type": "CODE_VULNERABILITY",
        "title": "CWE-798 - Hardcoded credentials",
        "description": "Hardcoded credentials can be intercepted.",
        "remediation": {"recommendation": {"text": "Use a secrets manager."}},
        "severity": "CRITICAL",
        "firstObservedAt": OBSERVED,
        "lastObservedAt": OBSERVED,
        "status": "ACTIVE",
        "resources": [lambda_function()],
        "codeVulnerabilityDetails": {
            "filePath": {"fileName": "handler.py", "filePath": "src/handler.py", "startLine": 12, "endLine": 14},
            "detectorTags": ["security", "secrets"],
            "referenceUrls": ["https://cwe.mitre.org/data/definitions/798.html"],
            "ruleId": "python-hardcoded-credentials",
            "detectorId": "python/hardcoded-credentials@v1.0",
            "detectorName": "Hardcoded credentials",
            "cwes": ["CWE-798"],
        },
    }
    with _Stubbed() as aws:
        expect_status(aws.stub)
        expect_totals(aws.stub, "CODE_VULNERABILITY", {"all": 1, "critical": 1})
        expect_list(aws.stub, "CODE_VULNERABILITY", "ACTIVE", [code])
        expect_list(aws.stub, "CODE_VULNERABILITY", "CLOSED", [])
        reader = _reader(aws, types=("CODE_VULNERABILITY",))
        reader.inspector.read(REGION)
        aws.stub.assert_no_pending_responses()
    [row] = _nodes(reader, INSPECTOR_FINDING)
    assert row["finding_type"] == "CODE_VULNERABILITY" and row["cwes"] == ["CWE-798"]
    assert (row["detector_id"], row["detector_name"], row["rule_id"]) == (
        "python/hardcoded-credentials@v1.0",
        "Hardcoded credentials",
        "python-hardcoded-credentials",
    )
    assert (row["code_file_name"], row["code_file_path"], row["code_start_line"], row["code_end_line"]) == (
        "handler.py",
        "src/handler.py",
        12,
        14,
    )
    assert row["vulnerability_id"] is None and row["cvss"] is None
    assert (node_ref(INSPECTOR_FINDING, finding_arn(9)), node_ref(LAMBDA_FUNCTION, FUNCTION_ARN)) in _edges(
        reader, CONCERNS_RESOURCE
    )
    assert reader.result.footprint_fields[REGION]["inspector2_active_finding_counts"] == {
        "CODE_VULNERABILITY": {"ALL": 1, "CRITICAL": 1}
    }


@pytest.mark.spec("req-aws-landing-zone-findings-10")
def test_a_watermark_filters_the_reads_and_a_clean_read_moves_it() -> None:
    from tap_plugin.aws_core.collectors.boto3_collector.findings import watermark_key

    since = datetime(2026, 11, 19, 11, 45, tzinfo=UTC)
    started = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    key = watermark_key("inspector2:PACKAGE_VULNERABILITY", ACCOUNT, REGION)
    with _Stubbed() as aws:
        expect_status(aws.stub)
        expect_totals(aws.stub, "PACKAGE_VULNERABILITY", {"all": 0})
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "ACTIVE", [], since=since)
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "CLOSED", [])
        reader = _reader(aws, read_through={key: "2026-11-19T11:45:00Z"}, run_started=started)
        reader.inspector.read(REGION)
        aws.stub.assert_no_pending_responses()
    assert reader.result.read_through == {key: "2026-11-20T11:45:00Z"}
    surface = _listing(reader, "account_region.inspector2_findings").surface(["b"])
    assert "incremental: updatedAt >= 2026-11-19T11:45:00Z" in surface["filter"]
    assert surface["enumeration_complete"] is False


@pytest.mark.spec("req-aws-landing-zone-findings-10")
def test_a_finding_type_added_later_is_read_in_full_not_from_another_types_watermark() -> None:
    """Each finding type keeps its own watermark: a package-only run's watermark never filters a code read."""
    from tap_plugin.aws_core.collectors.boto3_collector.findings import watermark_key

    since = datetime(2026, 11, 19, 11, 45, tzinfo=UTC)
    started = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    package_key = watermark_key("inspector2:PACKAGE_VULNERABILITY", ACCOUNT, REGION)
    code_key = watermark_key("inspector2:CODE_VULNERABILITY", ACCOUNT, REGION)
    with _Stubbed() as aws:
        expect_status(aws.stub)
        expect_totals(aws.stub, "PACKAGE_VULNERABILITY", {"all": 0})
        expect_totals(aws.stub, "CODE_VULNERABILITY", {"all": 0})
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "ACTIVE", [], since=since)
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "CLOSED", [])
        expect_list(aws.stub, "CODE_VULNERABILITY", "ACTIVE", [])  # no updatedAt: a full read
        expect_list(aws.stub, "CODE_VULNERABILITY", "CLOSED", [])
        reader = _reader(
            aws,
            types=("PACKAGE_VULNERABILITY", "CODE_VULNERABILITY"),
            read_through={package_key: "2026-11-19T11:45:00Z"},
            run_started=started,
        )
        reader.inspector.read(REGION)
        aws.stub.assert_no_pending_responses()
    assert reader.result.read_through == {package_key: "2026-11-20T11:45:00Z", code_key: "2026-11-20T11:45:00Z"}


@pytest.mark.spec("req-aws-landing-zone-findings-10")
def test_a_finding_read_but_not_written_keeps_the_previous_watermark(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refused write is not a clean read: the next run asks for that finding again."""
    from tap_plugin.aws_core.collectors.boto3_collector.findings import watermark_key

    monkeypatch.setattr(inspector_mod.InspectorReads, "_finding", lambda self, region, finding: False)
    key = watermark_key("inspector2:PACKAGE_VULNERABILITY", ACCOUNT, REGION)
    with _Stubbed() as aws:
        expect_status(aws.stub)
        expect_totals(aws.stub, "PACKAGE_VULNERABILITY", {"all": 1, "high": 1})
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "ACTIVE", [package_finding(1, ec2_instance())])
        expect_list(aws.stub, "PACKAGE_VULNERABILITY", "CLOSED", [])
        reader = _reader(aws, run_started=datetime(2026, 11, 20, 12, 0, tzinfo=UTC))
        reader.inspector.read(REGION)
        aws.stub.assert_no_pending_responses()
    assert key not in reader.result.read_through
    assert reader.result.read_through == {}  # no other form of Inspector key moved either


# ---------------------------------------------------------------------------
# The falsifier — a real grid row, a fake client
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.spec("req-aws-landing-zone-inspector-6", "req-grid-reconcile-falsifier-6")
def test_the_finding_falsifier() -> None:
    from tap_grid.falsifiers import DROPPED_FROM_OBSERVATION, PRESENT_AT_PROBE, UNDETERMINED, unsupported
    from tap_plugin.aws_core.falsifiers import InspectorFindingFalsifier

    from .test_landing_zone import MGMT, REGIONS, WEST, FakeAws, ProbeSession, _cand, _ctx, _err, _row

    arn = f"arn:{PARTITION}:inspector2:{WEST}:{MGMT}:finding/{1:032x}"
    payload = {"name": "f", "finding_arn": arn, "region": WEST, "status": "ACTIVE"}
    row = _row(INSPECTOR_FINDING, payload)
    for answer, expected in (
        ({"findings": [{"findingArn": arn, "status": "ACTIVE"}]}, PRESENT_AT_PROBE),
        ({"findings": [{"findingArn": arn, "status": "CLOSED"}]}, PRESENT_AT_PROBE),
        ({"findings": []}, DROPPED_FROM_OBSERVATION),
        (_err("AccessDeniedException"), UNDETERMINED),
        (_err("ThrottlingException"), UNDETERMINED),
    ):
        aws = FakeAws()
        aws.on("inspector2", "list_findings", answer)
        falsifier = InspectorFindingFalsifier(session=ProbeSession(aws), allowed_regions=REGIONS, account_id=MGMT)
        [verdict] = falsifier.batch_falsify([_cand(row, INSPECTOR_FINDING)], _ctx())
        assert verdict.verdict == expected, (answer, verdict.note)
        assert unsupported(verdict) is None
        [(_service, region, _op, kwargs)] = aws.calls
        assert region == WEST and kwargs["filterCriteria"] == {"findingArn": _eq(arn)}


def test_the_falsifier_is_wired() -> None:
    import tomllib
    from pathlib import Path

    from tap_plugin.aws_core.falsifiers import InspectorFindingFalsifier

    toml = tomllib.loads((Path(__file__).resolve().parents[1] / "tap-plugin.toml").read_text())
    cls = InspectorFindingFalsifier
    assert toml["falsifiers"][INSPECTOR_FINDING] == f"{cls.__module__}.{cls.__qualname__}"
    assert cls() is not None
