"""Inspector findings projected into compliance_core (aws-core-tap#261, req-aws-landing-zone-inspector-compliance).

The rules are pure functions over plain data and are tested here without a grid. compliance_core is an OPTIONAL
dependency of aws_core: the readiness tests run without it (its absence is one of the cases), and the tests that
write into it run only on a stack that loads it (``requires_compliance_core``); aws_core's own CI does not.
"""

from __future__ import annotations

import ast
import tomllib
import uuid
from pathlib import Path
from typing import Any

import pytest
from tap_plugin.aws_core.collectors.boto3_collector import compliance
from tap_plugin.aws_core.collectors.boto3_collector.compliance import (
    CARRIES,
    CONCERNS,
    FINDING,
    VULNERABILITY,
    HeldVulnerability,
    choose_cvss,
    concerns_properties,
    finding_ref,
    project,
    vuln_id_of,
)
from tap_plugin.aws_core.collectors.boto3_collector.identity import node_ref

PLUGIN = Path(__file__).resolve().parents[1]
ACCOUNT = "111122223333"
REGION = "us-gov-west-1"
PARTITION = "aws-us-gov"
INSTANCE_ID = "i-0abc1234def567890"
REPO_ARN = f"arn:{PARTITION}:ecr:{REGION}:{ACCOUNT}:repository/team/app"
NVD31 = {"baseScore": 7.5, "scoringVector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N", "version": "3.1", "source": "NVD"}
VENDOR31 = {"baseScore": 6.1, "scoringVector": "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N", "version": "3.1", "source": "UBUNTU_CVE"}
NVD2 = {"baseScore": 5.0, "scoringVector": "AV:N/AC:L/Au:N/C:P/I:N/A:N", "version": "2.0", "source": "NVD"}


def _loaded() -> bool:
    try:
        from django.apps import apps

        return any(getattr(getattr(c, "manifest", None), "slug", None) == "compliance_core" for c in apps.get_app_configs())
    except Exception:  # noqa: BLE001 — no app registry, no compliance_core
        return False


requires_compliance_core = pytest.mark.skipif(not _loaded(), reason="compliance_core is not loaded on this stack")


def row(n: int, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "finding_arn": f"arn:{PARTITION}:inspector2:{REGION}:{ACCOUNT}:finding/{n:032x}",
        "status": "ACTIVE",
        "severity": "HIGH",
        "title": "CVE-2026-0001 - openssl",
        "description": "A flaw in openssl.",
        "first_observed_at": "2026-11-01T00:00:00Z",
        "vulnerability_id": "CVE-2026-0001",
        "related_vulnerabilities": [],
        "cvss": [NVD2, VENDOR31, NVD31],
        "fix_available": "YES",
        "vulnerable_packages": [{"name": "openssl", "version": "3.0.2", "fixedInVersion": "3.0.8"}],
        "package_identities": None,
        "resource_type": "AWS_EC2_INSTANCE",
        "resource_id": INSTANCE_ID,
    }
    base.update(extra)
    return base


# --- the rules ------------------------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-landing-zone-inspector-compliance-5")
@pytest.mark.parametrize(
    ("given", "related", "expected"),
    [
        ("CVE-2026-0001", ["CVE-2026-0002"], "CVE-2026-0001"),
        ("ALAS2-2026-1234", ["CVE-2026-0002", "CVE-2026-0003"], "CVE-2026-0002"),
        ("GHSA-aaaa-bbbb-cccc", [], "GHSA-aaaa-bbbb-cccc"),
        ("GHSA-aaaa-bbbb-cccc", None, "GHSA-aaaa-bbbb-cccc"),
        (None, ["CVE-2026-0009"], "CVE-2026-0009"),
        (None, None, None),
    ],
)
def test_the_vulnerability_id_rule(given: Any, related: Any, expected: Any) -> None:
    assert vuln_id_of(given, related) == expected


@pytest.mark.spec("req-aws-landing-zone-inspector-compliance-6")
def test_cvss_prefers_nvd_3_then_vendor_3_then_2_with_the_vector() -> None:
    assert choose_cvss([NVD2, VENDOR31, NVD31]) == {
        "cvss_score": 7.5,
        "cvss_vector": NVD31["scoringVector"],
        "cvss_version": "3.1",
        "cvss_source": "NVD",
    }
    assert choose_cvss([NVD2, VENDOR31])["cvss_source"] == "UBUNTU_CVE"
    assert choose_cvss([NVD2])["cvss_version"] == "2.0"
    nvd30 = {**NVD31, "version": "3.0", "baseScore": 7.0}
    assert choose_cvss([nvd30, NVD31])["cvss_version"] == "3.1", "the highest version first within a rank"
    assert choose_cvss([{**NVD31, "version": "4.0"}]) is None
    assert choose_cvss([]) is None and choose_cvss(None) is None


@pytest.mark.spec("req-aws-landing-zone-inspector-compliance-5")
@pytest.mark.parametrize(
    ("fix", "packages", "expected"),
    [
        ("YES", [{"fixedInVersion": "3.0.8"}, {"fixedInVersion": "3.0.8"}], {"fixed_versions": ["3.0.8"], "fix_state": "fixed"}),
        ("NO", [{"fixedInVersion": "NotAvailable"}], {"fixed_versions": [], "fix_state": "not-fixed"}),
        ("PARTIAL", [{"fixedInVersion": "2.1"}, {"name": "b"}], {"fixed_versions": ["2.1"], "fix_state": "fixed"}),
        (None, [{"fixedInVersion": "1"}], {"fixed_versions": ["1"]}),
        ("YES", None, {"fix_state": "fixed"}),
    ],
)
def test_the_fix_rides_the_pair(fix: Any, packages: Any, expected: dict[str, Any]) -> None:
    assert concerns_properties(fix, packages) == expected


@pytest.mark.spec("req-aws-landing-zone-inspector-compliance-5", "req-aws-landing-zone-inspector-compliance-7")
def test_a_projection_is_the_neutral_shape() -> None:
    closed = row(2, status="CLOSED", resource_type="AWS_ECR_REPOSITORY", resource_id=REPO_ARN)
    out = project([row(1), closed], [])
    assert out.projected == 2 and out.skipped == 0
    findings = {n["node"]["source_key"]: n["node"] for n in out.nodes if n["entity"]["entity_type"] == FINDING}
    first = findings[row(1)["finding_arn"]]
    assert first["source"] == "aws_inspector" and first["status"] == "open"
    assert first["first_detected_at"] == "2026-11-01T00:00:00Z" and first["summary"] == "High CVE-2026-0001 openssl"
    assert findings[closed["finding_arn"]]["status"] == "resolved", "resolved only on a closed row"
    [vulnerability] = [n["node"] for n in out.nodes if n["entity"]["entity_type"] == VULNERABILITY]
    assert vulnerability["vuln_id"] == "CVE-2026-0001" and vulnerability["cvss_source"] == "NVD"
    assert "epss_score" not in vulnerability and "kev" not in vulnerability
    concerns = [e["edge"] for e in out.edges if e["edge"]["edge_type"] == CONCERNS]
    assert {e["to_ref"] for e in concerns} == {node_ref(VULNERABILITY, "CVE-2026-0001")}
    assert concerns[0]["properties"] == {"fixed_versions": ["3.0.8"], "fix_state": "fixed"}
    carriers = {(e["edge"]["from_ref"], e["edge"]["to_ref"]) for e in out.edges if e["edge"]["edge_type"] == CARRIES}
    assert carriers == {
        (node_ref("aws_core__aws_ec2_instance", INSTANCE_ID), finding_ref(row(1)["finding_arn"])),
        (node_ref("aws_core__aws_ecr_repository", REPO_ARN), finding_ref(closed["finding_arn"])),
    }


@pytest.mark.spec("req-aws-landing-zone-inspector-compliance-6")
def test_a_held_vulnerability_keeps_its_cvss_and_its_id() -> None:
    held = [HeldVulnerability("CVE-2026-0001", (), True)]
    out = project([row(1)], held)
    assert [n for n in out.nodes if n["entity"]["entity_type"] == VULNERABILITY] == [], "a filled slot is not sent"
    empty = project([row(1)], [HeldVulnerability("CVE-2026-0001", (), False)])
    [patch] = [n["node"] for n in empty.nodes if n["entity"]["entity_type"] == VULNERABILITY]
    assert set(patch) == {"vuln_id", "cvss_score", "cvss_vector", "cvss_version", "cvss_source"}


@pytest.mark.spec("req-aws-landing-zone-inspector-compliance-5")
def test_a_vulnerability_is_looked_up_by_alias_before_one_is_minted() -> None:
    ghsa = row(1, vulnerability_id="GHSA-aaaa-bbbb-cccc", related_vulnerabilities=[])
    held = [HeldVulnerability("CVE-2026-0042", ("GHSA-aaaa-bbbb-cccc",), True)]
    out = project([ghsa], held)
    [edge] = [e["edge"] for e in out.edges if e["edge"]["edge_type"] == CONCERNS]
    assert edge["to_ref"] == node_ref(VULNERABILITY, "CVE-2026-0042")
    assert not [n for n in out.nodes if n["entity"]["entity_type"] == VULNERABILITY]
    advisory = project([row(2, vulnerability_id="ALAS2-2026-1", related_vulnerabilities=["CVE-2026-0007"])], [])
    [minted] = [n["node"] for n in advisory.nodes if n["entity"]["entity_type"] == VULNERABILITY]
    assert minted["vuln_id"] == "CVE-2026-0007" and minted["aliases"] == ["ALAS2-2026-1"]


@pytest.mark.spec("req-aws-landing-zone-inspector-compliance-5")
def test_a_code_finding_is_a_finding_and_a_carrier_with_no_vulnerability() -> None:
    code = row(
        3,
        finding_type="CODE_VULNERABILITY",
        title="CWE-798 - Hardcoded credentials",
        vulnerability_id=None,
        related_vulnerabilities=None,
        cvss=None,
        fix_available=None,
        vulnerable_packages=None,
        cwes=["CWE-798"],
        rule_id="python-hardcoded-credentials",
        resource_type="AWS_LAMBDA_FUNCTION",
        resource_id=f"arn:{PARTITION}:lambda:{REGION}:{ACCOUNT}:function:orders-handler",
    )
    out = project([code], [])
    assert out.projected == 1 and out.skipped == 0
    [finding] = [n["node"] for n in out.nodes]
    assert finding["source_key"] == code["finding_arn"] and finding["summary"] == "High CWE-798 python-hardcoded-credentials"
    assert [e["edge"]["edge_type"] for e in out.edges] == [CARRIES], "no vulnerability node and no CONCERNS edge (Q124b)"
    assert compliance.names_of([code]) == set()


def test_two_held_vulnerabilities_for_one_finding_is_refused() -> None:
    held = [HeldVulnerability("CVE-2026-0001", (), True), HeldVulnerability("GHSA-x", ("CVE-2026-0001",), True)]
    out = project([row(1)], held)
    assert out.projected == 0 and out.skipped == 1
    assert out.notices[0][0] == "INSPECTOR_COMPLIANCE_VULNERABILITY_AMBIGUOUS"


def test_a_row_with_no_vulnerability_id_is_skipped_and_said() -> None:
    out = project([row(1, vulnerability_id=None, related_vulnerabilities=None)], [])
    assert out.projected == 0 and out.skipped == 1 and out.nodes == []


def test_the_option_is_off_unless_true() -> None:
    assert not compliance.enabled({}) and not compliance.enabled({"inspector_compliance_findings": "true"})
    assert compliance.enabled({"inspector_compliance_findings": True})


@pytest.mark.spec("req-aws-core-secret-inspector-compliance-2")
def test_the_option_is_one_boolean_on_both_kinds() -> None:
    import jsonschema
    from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred

    for schema in (cred.AWS_STATIC_SCHEMA, cred.AWS_ASSUMED_ROLE_SCHEMA):
        assert schema["properties"]["inspector_compliance_findings"] is cred._FINDINGS_PROPS["inspector_compliance_findings"]
    static = {"access_key_id": "AKIA", "secret_access_key": "x"}
    jsonschema.validate({**static, "inspector_compliance_findings": True}, cred.AWS_STATIC_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**static, "inspector_compliance_findings": "yes"}, cred.AWS_STATIC_SCHEMA)


# --- the dependency, as declared --------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-landing-zone-inspector-compliance-2")
def test_compliance_core_is_optional_never_imported_and_not_in_pyproject() -> None:
    manifest = tomllib.loads((PLUGIN / "tap-plugin.toml").read_text())
    [dep] = [d for d in manifest["depends_on"] if d["slug"] == "compliance_core"]
    assert dep["optional"] is True and dep["min_version"] == compliance.MIN_VERSION
    pyproject = tomllib.loads((PLUGIN.parents[1] / "pyproject.toml").read_text())
    assert not [d for d in pyproject["project"]["dependencies"] if d.startswith("compliance-core-tap")]
    for path in PLUGIN.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            module = node.module if isinstance(node, ast.ImportFrom) else None
            for name in [*names, module or ""]:
                assert not name.startswith("tap_plugin.compliance_core"), f"{path} imports {name}"


# --- readiness --------------------------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-landing-zone-inspector-compliance-3")
def test_readiness_names_a_missing_or_old_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compliance, "_plugin_version", lambda: False)
    assert "not installed" in compliance.readiness()
    monkeypatch.setattr(compliance, "_plugin_version", lambda: "0.8.7")
    assert "older than 0.8.13" in compliance.readiness()
    monkeypatch.setattr(compliance, "_plugin_version", lambda: None)
    assert "names no version" in compliance.readiness()


@requires_compliance_core
@pytest.mark.spec("req-aws-landing-zone-inspector-compliance-3")
def test_readiness_passes_on_compliance_core_and_names_a_missing_edge_property(monkeypatch: pytest.MonkeyPatch) -> None:
    assert compliance.readiness() is None
    import tap_grid.constraints as constraints

    monkeypatch.setattr(constraints, "get_edge_property_schema", lambda _e: {"properties": {"fixed_versions": {}}})
    assert "lacks the property fix_state" in compliance.readiness()


@pytest.mark.spec("req-aws-landing-zone-inspector-compliance-3")
def test_self_test_fails_when_the_option_is_on_and_compliance_core_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
    from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred

    from tap_cares.secrets.models import Secret, SecretRef

    def secret(option: bool) -> Secret:
        return Secret(
            ref=SecretRef(scope="aws_core", key="boto_collector"),
            kind="aws_static_access_key",
            description="test",
            data={"access_key_id": "AKIA", "secret_access_key": "shh", "regions_allowed": [REGION], "inspector_compliance_findings": option},
            metadata={},
            source_path=Path("/dev/null"),
        )

    monkeypatch.setattr(collector_mod, "caller_account_id", lambda *a, **k: ACCOUNT)
    monkeypatch.setattr(collector_mod, "build_session", lambda _data: object())
    monkeypatch.setattr(compliance, "readiness", lambda: "compliance_core is not installed: absent")
    for option, failing in ((True, True), (False, False)):
        monkeypatch.setattr(cred, "resolve_secret", lambda _ref, o=option: secret(o))
        result = collector_mod.Boto3Collector.self_test()
        codes = {c.code: c for c in result.checks}
        assert ("INSPECTOR_COMPLIANCE_READY" in codes) is option
        if failing:
            assert codes["INSPECTOR_COMPLIANCE_READY"].is_failure


# --- writing into compliance_core (only where it is loaded) -----------------------------------------------------------


def _collector() -> Any:
    from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector

    from tap_cares.collectors.config import CollectorConfig

    return Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))


def _inspector_row(n: int, **extra: Any) -> None:
    from tap_grid.services import create_node

    fields = {k: v for k, v in row(n, **extra).items() if k != "package_identities"}
    result = create_node("aws_core__aws_inspector2_finding", {"name": f"f{n}", "account_id": ACCOUNT, "region": REGION, **fields})
    assert result.success, result.errors


@pytest.mark.django_db
@requires_compliance_core
@pytest.mark.spec("req-aws-landing-zone-inspector-compliance-4")
def test_held_vulnerabilities_are_found_by_id_or_alias_without_reading_other_rows() -> None:
    """The alias lookup asks the database for the wanted names (jsonb ``?|``), not every row that has aliases."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from tap_grid.services import create_node
    from tap_plugin.aws_core.collectors.boto3_collector.compliance import held_vulnerabilities

    create_node(VULNERABILITY, {"vuln_id": "CVE-2026-0042", "aliases": ["GHSA-aaaa-bbbb-cccc"]})
    create_node(VULNERABILITY, {"vuln_id": "CVE-2026-0043", "aliases": ["GHSA-dddd-eeee-ffff"]})
    create_node(VULNERABILITY, {"vuln_id": "CVE-2026-0044"})
    with CaptureQueriesContext(connection) as queries:
        by_alias = held_vulnerabilities(["GHSA-aaaa-bbbb-cccc"])
    assert [v.vuln_id for v in by_alias] == ["CVE-2026-0042"]
    assert "?|" in queries.captured_queries[-1]["sql"]
    assert [v.vuln_id for v in held_vulnerabilities(["CVE-2026-0044"])] == ["CVE-2026-0044"]
    assert held_vulnerabilities(["CVE-2026-9999"]) == []


@pytest.mark.django_db
@requires_compliance_core
@pytest.mark.spec("req-aws-landing-zone-inspector-compliance-4", "req-aws-landing-zone-inspector-compliance-6")
def test_stored_rows_are_projected_and_a_filled_cvss_is_kept() -> None:
    from tap_grid.registry import get_model_class
    from tap_grid.services import create_node

    create_node(VULNERABILITY, {"vuln_id": "CVE-2026-0042", "aliases": ["GHSA-aaaa-bbbb-cccc"], "cvss_score": 9.8, "cvss_source": "CNA"})
    create_node("aws_core__aws_ec2_instance", {"name": "i", "instance_id": INSTANCE_ID})
    _inspector_row(1)
    _inspector_row(2, vulnerability_id="GHSA-aaaa-bbbb-cccc", status="CLOSED")
    collector = _collector()
    assert collector._project_inspector_findings({"inspector_compliance_findings": True}, ACCOUNT) is None
    assert collector.results["error"] == []
    findings = get_model_class(FINDING).objects.filter(source="aws_inspector")
    assert findings.count() == 2
    assert {f.status for f in findings} == {"open", "resolved"}
    vulns = {v.vuln_id: v for v in get_model_class(VULNERABILITY).objects.all()}
    assert vulns["CVE-2026-0042"].cvss_score == 9.8 and vulns["CVE-2026-0042"].cvss_source == "CNA", "filled: kept"
    assert vulns["CVE-2026-0001"].cvss_vector == NVD31["scoringVector"] and vulns["CVE-2026-0001"].cvss_source == "NVD"
    from tap_grid.models import Edge

    assert Edge.objects.filter(edge_type=CARRIES, entity__deleted_at__isnull=True).count() == 2
    assert Edge.objects.filter(edge_type=CONCERNS, entity__deleted_at__isnull=True).count() == 2
    # A second run writes the same nodes and edges again, not new ones.
    assert collector._project_inspector_findings({"inspector_compliance_findings": True}, ACCOUNT) is None
    assert get_model_class(FINDING).objects.filter(source="aws_inspector").count() == 2
    assert Edge.objects.filter(edge_type=CARRIES, entity__deleted_at__isnull=True).count() == 2


@pytest.mark.django_db
@pytest.mark.spec("req-aws-landing-zone-inspector-compliance-3")
def test_a_failed_readiness_at_run_time_is_an_error_not_a_failed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compliance, "readiness", lambda: "compliance_core 0.8.7 is older than 0.8.13")
    collector = _collector()
    reason = collector._project_inspector_findings({"inspector_compliance_findings": True}, ACCOUNT)
    assert reason == "compliance_core 0.8.7 is older than 0.8.13"
    [error] = collector.results["error"]
    assert error["message_code"] == "INSPECTOR_COMPLIANCE_PROJECTION_FAILED"
