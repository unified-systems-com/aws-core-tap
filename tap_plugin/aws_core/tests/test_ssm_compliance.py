"""SSM patch state projected into compliance_core (req-aws-core-ssm-compliance, aws-core-tap#281, Q141a to c).

The rules are pure functions over plain data and are tested here without a grid. The stored read is tested against a
real collector run driven by the SSM walk's fakes (test_ssm_patch_state.py). compliance_core is an OPTIONAL dependency:
the readiness and gate tests run without it, and the test that writes into it runs only on a stack that loads it.
No AWS call is made.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from tap_plugin.aws_core.collectors.boto3_collector import compliance, ssm_compliance
from tap_plugin.aws_core.collectors.boto3_collector.compliance import CARRIES, CONCERNS, FINDING, VULNERABILITY, HeldVulnerability
from tap_plugin.aws_core.collectors.boto3_collector.identity import composite_natural_key, endpoint_key, node_ref
from tap_plugin.aws_core.collectors.boto3_collector.ssm_compliance import (
    EXPOSED_STATES,
    RESOLVES,
    Report,
    finding_ref,
    project,
    resolvable_keys,
    source_key,
)
from tap_plugin.aws_core.tests.test_inspector_compliance import requires_compliance_core
from tap_plugin.aws_core.tests.test_ssm_patch_state import (  # noqa: F401 — _stub_ssm is a fixture
    ACCOUNT,
    EC2_ID,
    EC2_ID_2,
    HYBRID_ID,
    PARTITION,
    REGION,
    _stub_ssm,
)

PATCH = "aws_core__aws_ssm_patch"
MI = "aws_core__aws_ssm_managed_instance"
EC2 = "aws_core__aws_ec2_instance"
#: Not an account number: the pure rules only need a scope string for the finding key.
SCOPE = "0000"
OPENSSL = "openssl-libs.x86_64:1:3.0.8-1.amzn2023"


def report(instance_id: str, state: str, *, kb_id: str = OPENSSL, cves: tuple[str, ...] = ("CVE-2026-0001",),
           resource_type: str = "EC2Instance", severity: str = "Critical") -> Report:
    return Report(
        instance_id=instance_id,
        resource_type=resource_type,
        partition=PARTITION,
        operating_system="AMAZON_LINUX_2023",
        kb_id=kb_id,
        title=f"{kb_id} title",
        cve_ids=cves,
        state=state,
        severity=severity,
    )


def _patch_ref(kb_id: str = OPENSSL, operating_system: str = "AMAZON_LINUX_2023") -> str:
    return node_ref(PATCH, composite_natural_key({"partition": PARTITION, "operating_system": operating_system, "kb_id": kb_id}))


def _edges(out: Any, edge_type: str) -> set[tuple[str, str]]:
    return {(e["edge"]["from_ref"], e["edge"]["to_ref"]) for e in out.edges if e["edge"]["edge_type"] == edge_type}


def _findings(out: Any) -> dict[str, dict[str, Any]]:
    return {n["node"]["source_key"]: n["node"] for n in out.nodes if n["entity"]["entity_type"] == FINDING}


# --- the switch -------------------------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-ssm-compliance-1")
def test_the_switch_is_its_own_one_boolean_and_off_unless_true() -> None:
    import jsonschema
    from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred

    assert ssm_compliance.OPTION == "ssm_compliance_findings" != compliance.OPTION
    assert not ssm_compliance.enabled({}) and not ssm_compliance.enabled({"ssm_compliance_findings": "true"})
    assert not ssm_compliance.enabled({"inspector_compliance_findings": True}), "Inspector's switch does not turn it on"
    assert ssm_compliance.enabled({"ssm_compliance_findings": True})
    assert not compliance.enabled({"ssm_compliance_findings": True}), "nor does it turn Inspector's on"
    for schema in (cred.AWS_STATIC_SCHEMA, cred.AWS_ASSUMED_ROLE_SCHEMA):
        assert schema["properties"]["ssm_compliance_findings"] is cred._FINDINGS_PROPS["ssm_compliance_findings"]
    static = {"access_key_id": "AKIA", "secret_access_key": "x"}
    jsonschema.validate({**static, "ssm_compliance_findings": True}, cred.AWS_STATIC_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**static, "ssm_compliance_findings": "yes"}, cred.AWS_STATIC_SCHEMA)


# --- the rules ------------------------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-ssm-compliance-5")
def test_exposure_is_the_four_states_where_the_fix_is_not_in_effect() -> None:
    assert EXPOSED_STATES == {"MISSING", "FAILED", "INSTALLED_PENDING_REBOOT", "AVAILABLE_SECURITY_UPDATE"}
    for state in ("MISSING", "FAILED", "INSTALLED_PENDING_REBOOT", "AVAILABLE_SECURITY_UPDATE"):
        out = project([report(EC2_ID, state)], [], account_id=SCOPE)
        assert [f["status"] for f in _findings(out).values()] == ["open"], state
    for state in ("INSTALLED", "INSTALLED_OTHER", "INSTALLED_REJECTED", "NOT_APPLICABLE", None):
        out = project([report(EC2_ID, state)], [], account_id=SCOPE)
        assert _findings(out) == {}, state
        assert _edges(out, RESOLVES) == {(_patch_ref(), node_ref(VULNERABILITY, "CVE-2026-0001"))}, "linked whatever the state"


@pytest.mark.spec("req-aws-core-ssm-compliance-4", "req-aws-core-ssm-compliance-5", "req-aws-core-ssm-compliance-7")
def test_a_projection_is_the_patch_links_and_one_finding_per_exposed_instance_and_cve() -> None:
    kernel = "kernel.x86_64:0:6.1.100-1.amzn2023"
    reports = [
        report(EC2_ID, "MISSING", cves=("CVE-2026-0001", "CVE-2026-0002")),
        report(EC2_ID, "INSTALLED", kb_id=kernel, cves=("CVE-2026-0001",)),  # the same CVE, a second patch
        report(EC2_ID_2, "INSTALLED", cves=("CVE-2026-0001", "CVE-2026-0002")),
        report(HYBRID_ID, "FAILED", kb_id="KB5034441", cves=("CVE-2026-0003",), resource_type="ManagedInstance", severity="Important"),
    ]
    reports[3] = Report(**{**reports[3].__dict__, "operating_system": "WINDOWS"})
    out = project(reports, [], account_id=SCOPE)
    vulns = {n["node"]["vuln_id"]: n["node"] for n in out.nodes if n["entity"]["entity_type"] == VULNERABILITY}
    assert set(vulns) == {"CVE-2026-0001", "CVE-2026-0002", "CVE-2026-0003"}
    assert all(v == {"vuln_id": k, "aliases": []} for k, v in vulns.items()), "SSM states no CVSS, so none is written"
    assert _edges(out, RESOLVES) == {
        (_patch_ref(), node_ref(VULNERABILITY, "CVE-2026-0001")),
        (_patch_ref(), node_ref(VULNERABILITY, "CVE-2026-0002")),
        (_patch_ref(kernel), node_ref(VULNERABILITY, "CVE-2026-0001")),
        (_patch_ref("KB5034441", "WINDOWS"), node_ref(VULNERABILITY, "CVE-2026-0003")),
    }
    findings = _findings(out)
    one, two, hybrid = (source_key(SCOPE, EC2_ID, "CVE-2026-0001"), source_key(SCOPE, EC2_ID, "CVE-2026-0002"),
                        source_key(SCOPE, HYBRID_ID, "CVE-2026-0003"))
    assert set(findings) == {one, two, hybrid}, "one per exposed (instance, CVE); the patched instance has none"
    assert out.projected == 3 and out.skipped == 0
    assert findings[one]["source"] == "aws_ssm_patch" and findings[one]["status"] == "open"
    assert findings[one]["name"] == f"CVE-2026-0001 on {EC2_ID}"
    assert findings[one]["summary"] == f"Critical CVE-2026-0001 {OPENSSL}", "the exposed patch, not the installed one"
    assert f"{kernel} INSTALLED" in findings[one]["description"] and f"{OPENSSL} MISSING" in findings[one]["description"]
    assert "first_detected_at" not in findings[one]
    concerns = [e["edge"] for e in out.edges if e["edge"]["edge_type"] == CONCERNS]
    assert {(c["from_ref"], c["to_ref"]) for c in concerns} == {
        (finding_ref(one), node_ref(VULNERABILITY, "CVE-2026-0001")),
        (finding_ref(two), node_ref(VULNERABILITY, "CVE-2026-0002")),
        (finding_ref(hybrid), node_ref(VULNERABILITY, "CVE-2026-0003")),
    }
    assert all(c["properties"] == {"fix_state": "fixed"} for c in concerns)
    assert _edges(out, CARRIES) == {
        (node_ref(EC2, EC2_ID), finding_ref(one)),
        (node_ref(EC2, EC2_ID), finding_ref(two)),
        (node_ref(MI, HYBRID_ID), finding_ref(hybrid)),
    }, "an EC2-backed node's finding is carried by the EC2 instance, a hybrid one's by the managed instance"


@pytest.mark.spec("req-aws-core-ssm-compliance-4")
def test_a_held_vulnerability_is_found_by_id_or_alias_and_left_as_it_is() -> None:
    held = [HeldVulnerability("CVE-2026-0042", ("CVE-2026-0001",), True)]
    out = project([report(EC2_ID, "MISSING")], held, account_id=SCOPE)
    assert not [n for n in out.nodes if n["entity"]["entity_type"] == VULNERABILITY], "a held one is never re-sent"
    assert _edges(out, RESOLVES) == {(_patch_ref(), node_ref(VULNERABILITY, "CVE-2026-0042"))}
    [concern] = [e["edge"] for e in out.edges if e["edge"]["edge_type"] == CONCERNS]
    assert concern["to_ref"] == node_ref(VULNERABILITY, "CVE-2026-0042")
    assert ssm_compliance.names_of([report(EC2_ID, "MISSING", cves=("CVE-2026-0001", "CVE-2026-0002"))]) == {
        "CVE-2026-0001",
        "CVE-2026-0002",
    }


@pytest.mark.spec("req-aws-core-ssm-compliance-4")
def test_an_ambiguous_cve_and_a_token_that_is_not_a_cve_are_skipped_and_said() -> None:
    held = [HeldVulnerability("CVE-2026-0001", (), True), HeldVulnerability("GHSA-x", ("CVE-2026-0001",), True)]
    out = project([report(EC2_ID, "MISSING", cves=("CVE-2026-0001", "ALAS-2026-1", "CVE-2026-0009"))], held, account_id=SCOPE)
    codes = [code for code, _message in out.notices]
    assert codes == ["SSM_COMPLIANCE_VULNERABILITY_AMBIGUOUS", "SSM_COMPLIANCE_CVE_SKIPPED"]
    assert _edges(out, RESOLVES) == {(_patch_ref(), node_ref(VULNERABILITY, "CVE-2026-0009"))}
    assert set(_findings(out)) == {source_key(SCOPE, EC2_ID, "CVE-2026-0009")}


@pytest.mark.spec("req-aws-core-ssm-compliance-6")
def test_a_finding_is_resolved_only_on_a_positive_record() -> None:
    patched = source_key(SCOPE, EC2_ID, "CVE-2026-0001")
    gone = source_key(SCOPE, EC2_ID, "CVE-2026-0099")
    out = project([report(EC2_ID, "INSTALLED")], [], account_id=SCOPE, held_open=[patched, gone])
    findings = _findings(out)
    assert set(findings) == {patched}, "a pair no longer reported is left as it was"
    assert findings[patched]["status"] == "resolved"
    assert _edges(out, CARRIES) == {(node_ref(EC2, EC2_ID), finding_ref(patched))}
    assert _findings(project([report(EC2_ID, "INSTALLED")], [], account_id=SCOPE)) == {}, "nothing held: nothing written"
    # Only the pairs with no exposed patch are looked up.
    mixed = [report(EC2_ID, "MISSING"), report(EC2_ID, "INSTALLED", kb_id="other"), report(EC2_ID_2, "INSTALLED")]
    assert resolvable_keys(SCOPE, mixed) == {source_key(SCOPE, EC2_ID_2, "CVE-2026-0001")}


def test_the_patch_endpoint_names_the_stored_patch_by_its_declared_key() -> None:
    """The patch is not in the projection batch, so its endpoint is a key core resolves against the live grid."""
    import tap_plugin.aws_core.models  # noqa: F401 — registers the models

    key = endpoint_key(*_patch_ref().split(":", 1))
    assert key == {"entity_type": PATCH, "key": {"partition": PARTITION, "operating_system": "AMAZON_LINUX_2023", "kb_id": OPENSSL}}


# --- readiness --------------------------------------------------------------------------------------------------------


def _secret(data: dict[str, Any]) -> Any:
    from tap_cares.secrets.models import Secret, SecretRef

    return Secret(
        ref=SecretRef(scope="aws_core", key="boto_collector"),
        kind="aws_static_access_key",
        description="test",
        data={"access_key_id": "AKIA", "secret_access_key": "shh", "regions_allowed": [REGION], **data},
        metadata={},
        source_path=Path("/dev/null"),
    )


@pytest.mark.spec("req-aws-core-ssm-compliance-1", "req-aws-core-ssm-compliance-2")
def test_self_test_checks_compliance_core_only_when_the_ssm_switch_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
    from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred

    monkeypatch.setattr(collector_mod, "caller_account_id", lambda *a, **k: ACCOUNT)
    monkeypatch.setattr(collector_mod, "build_session", lambda _data: object())
    monkeypatch.setattr(compliance, "readiness", lambda: "compliance_core is not installed: absent")
    for data, ssm_check, inspector_check in (
        ({"ssm_compliance_findings": True}, True, False),
        ({"ssm_compliance_findings": False, "inspector_compliance_findings": True}, False, True),
        ({}, False, False),
    ):
        monkeypatch.setattr(cred, "resolve_secret", lambda _ref, d=data: _secret(d))
        codes = {c.code: c for c in collector_mod.Boto3Collector.self_test().checks}
        assert ("SSM_COMPLIANCE_READY" in codes) is ssm_check, data
        assert ("INSPECTOR_COMPLIANCE_READY" in codes) is inspector_check, data
        if ssm_check:
            assert codes["SSM_COMPLIANCE_READY"].is_failure


def _collector() -> Any:
    from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector

    from tap_cares.collectors.config import CollectorConfig

    return Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-ssm-compliance-2")
def test_a_failed_readiness_at_run_time_is_an_error_not_a_failed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compliance, "readiness", lambda: "compliance_core 0.8.7 is older than 0.8.13")
    collector = _collector()
    reason = collector._project_ssm_compliance({"ssm_compliance_findings": True}, ACCOUNT)
    assert reason == "compliance_core 0.8.7 is older than 0.8.13"
    [error] = collector.results["error"]
    assert error["message_code"] == "SSM_COMPLIANCE_PROJECTION_FAILED"


# --- the stored read, from a real collector run -------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-ssm-compliance-1", "req-aws-core-ssm-compliance-2", "req-aws-core-ssm-compliance-3")
def test_a_run_with_the_switch_on_collects_everything_and_projects_from_what_it_stored(
    _stub_ssm, monkeypatch: pytest.MonkeyPatch  # noqa: F811 — the fixture imported above
) -> None:
    from tap_grid.services import get_node
    from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred
    from tap_plugin.aws_core.tests.grid_keys import node_id

    from tap_cares.secrets.models import Secret

    base = cred.resolve_secret(None)
    monkeypatch.setattr(cred, "resolve_secret", lambda _ref: Secret(**{**base.__dict__, "data": {**base.data, "ssm_compliance_findings": True}}))
    seen: list[str] = []
    monkeypatch.setattr(compliance, "readiness", lambda: seen.append("checked") or "compliance_core is not installed: absent")
    collector = _collector()
    collector.run()
    assert seen == ["checked"]
    [error] = collector.results["error"]
    assert error["message_code"] == "SSM_COMPLIANCE_PROJECTION_FAILED"
    assert "SSM patch state NOT projected into compliance_core" in collector.summary
    assert get_node(node_id(MI, EC2_ID)).patch_missing_count == 2, "the AWS data is collected either way"

    # What the projection reads: the account's stored instances, their REPORTS_PATCH edges and the patches.
    reports = ssm_compliance.stored_reports(ACCOUNT)
    seen_reports = {(r.instance_id, r.kb_id, r.state, r.cve_ids) for r in reports}
    assert seen_reports == {  # the gap rows only: the INSTALLED kernel row is no edge (Q147 option 3)
        (EC2_ID, OPENSSL, "MISSING", ("CVE-2026-0001", "CVE-2026-0002")),
        (EC2_ID_2, OPENSSL, "INSTALLED_PENDING_REBOOT", ("CVE-2026-0001", "CVE-2026-0002")),
        (HYBRID_ID, "KB5034441", "FAILED", ()),
    }
    assert ssm_compliance.stored_reports("0000") == [], "another account's instances are not read"
    out = project(reports, [], account_id=ACCOUNT)
    assert set(_findings(out)) == {
        source_key(ACCOUNT, iid, cve) for iid in (EC2_ID, EC2_ID_2) for cve in ("CVE-2026-0001", "CVE-2026-0002")
    }
    assert _edges(out, RESOLVES) == {
        (_patch_ref(), node_ref(VULNERABILITY, "CVE-2026-0001")),
        (_patch_ref(), node_ref(VULNERABILITY, "CVE-2026-0002")),
    }


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-ssm-compliance-1")
def test_a_run_with_the_switch_off_never_looks_for_compliance_core(_stub_ssm, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(compliance, "readiness", lambda: pytest.fail("readiness was checked with the switch off"))
    collector = _collector()
    collector.run()
    assert collector.results["error"] == []


# --- writing into compliance_core (only where it is loaded) -----------------------------------------------------------


@pytest.mark.django_db
@requires_compliance_core
@pytest.mark.xfail(
    strict=True,
    reason="Open, not ruled: under Q147 option 3 an installed patch is no longer an edge, so its pair is no longer "
    "reported and the finding is never resolved (req-aws-core-ssm-compliance-6); the stale edge stays live until "
    "reconcile applies its removal proposal.",
)
@pytest.mark.spec("req-aws-core-ssm-compliance-3", "req-aws-core-ssm-compliance-4", "req-aws-core-ssm-compliance-6")
def test_stored_patch_state_is_projected_and_a_patched_pair_resolves(_stub_ssm) -> None:  # noqa: F811
    from tap_grid.models import Edge
    from tap_grid.registry import get_model_class

    _collector().run()
    collector = _collector()
    assert collector._project_ssm_compliance({"ssm_compliance_findings": True}, ACCOUNT) is None
    assert collector.results["error"] == []
    findings = {f.source_key: f for f in get_model_class(FINDING).objects.filter(source="aws_ssm_patch")}
    assert set(findings) == {
        source_key(ACCOUNT, iid, cve) for iid in (EC2_ID, EC2_ID_2) for cve in ("CVE-2026-0001", "CVE-2026-0002")
    }
    assert {f.status for f in findings.values()} == {"open"}
    assert Edge.objects.filter(edge_type=RESOLVES, entity__deleted_at__isnull=True).count() == 2
    # The instance installs the patch: its finding resolves on the next projection; a second one writes nothing new.
    _stub_ssm.patches[EC2_ID][0] = {**_stub_ssm.patches[EC2_ID][0], "State": "INSTALLED"}
    _stub_ssm.patches[EC2_ID_2][0] = {**_stub_ssm.patches[EC2_ID_2][0], "State": "INSTALLED"}
    _collector().run()
    assert collector._project_ssm_compliance({"ssm_compliance_findings": True}, ACCOUNT) is None
    statuses = set(get_model_class(FINDING).objects.filter(source="aws_ssm_patch").values_list("status", flat=True))
    assert statuses == {"resolved"}
    assert get_model_class(FINDING).objects.filter(source="aws_ssm_patch").count() == 4
