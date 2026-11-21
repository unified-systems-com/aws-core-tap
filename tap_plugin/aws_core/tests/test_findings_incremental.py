"""Incremental findings reads (rulings Q126a and c, spec-aws-core-landing-zone.md req-aws-landing-zone-findings-10).

A run asks GuardDuty and Security Hub only for findings updated since that source's last clean read, kept as the
watermark ``findings_read_through`` in the metadata of the collector's own batch node. The reader against the
paginating fake of ``test_landing_zone.py``; then two real collector runs, the second reading the first's watermark
from the grid's batch row. No AWS call is made.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tap_plugin.aws_core.collectors.boto3_collector.findings import (
    READ_THROUGH,
    WATERMARK_OVERLAP,
    read_through_of,
    watermark_key,
)
from tap_plugin.aws_core.collectors.boto3_collector.landing_zone import GUARDDUTY_DETECTOR, SECURITYHUB_HUB

from .test_landing_zone import EAST, MGMT, REGIONS, WEST, _err, _one, collect
from .test_security_findings import with_findings

STARTED = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
WATERMARK = "2026-11-19T11:45:00Z"


def _calls(aws: Any, service: str, operation: str, region: str) -> list[dict[str, Any]]:
    return [kw for s, r, op, kw in aws.calls if (s, op, r) == (service, operation, region)]


@pytest.mark.spec("req-aws-landing-zone-findings-10")
def test_a_first_run_reads_in_full_and_writes_a_watermark_per_clean_source() -> None:
    aws = with_findings()
    read = collect(aws, run_started=STARTED)
    for kw in _calls(aws, "guardduty", "list_findings", WEST):
        assert kw["FindingCriteria"]["Criterion"]["service.archived"]["Equals"] == ["true"] or (
            "updatedAt" not in kw["FindingCriteria"]["Criterion"]
        ), "no watermark: the active read is full"
    expected = (STARTED - WATERMARK_OVERLAP).isoformat().replace("+00:00", "Z")
    assert read.read_through[watermark_key("guardduty", MGMT, WEST)] == expected
    assert read.read_through[watermark_key("securityhub", MGMT, WEST)] == expected
    assert not [k for k in read.read_through if k.startswith("accessanalyzer|")], "Access Analyzer stays a full read"


@pytest.mark.spec("req-aws-landing-zone-findings-10")
def test_a_watermark_filters_each_source_and_counts_say_they_are_not_totals() -> None:
    aws = with_findings()
    marks = {watermark_key("guardduty", MGMT, WEST): WATERMARK, watermark_key("securityhub", MGMT, WEST): WATERMARK}
    read = collect(aws, run_started=STARTED, read_through=marks)
    since_ms = int(datetime(2026, 11, 19, 11, 45, tzinfo=UTC).timestamp() * 1000)
    active = [
        kw
        for kw in _calls(aws, "guardduty", "list_findings", WEST)
        if kw["FindingCriteria"]["Criterion"]["service.archived"]["Equals"] == ["false"]
    ]
    assert active and all(kw["FindingCriteria"]["Criterion"]["updatedAt"] == {"GreaterThanOrEqual": since_ms} for kw in active)
    [stats] = _calls(aws, "guardduty", "get_findings_statistics", WEST)
    assert "updatedAt" not in stats["FindingCriteria"]["Criterion"], "the totals are still the whole set"
    sh = _calls(aws, "securityhub", "get_findings", WEST)
    assert sh and all(kw["Filters"]["UpdatedAt"][0]["Start"] == WATERMARK for kw in sh)
    hub = _one(read, SECURITYHUB_HUB)
    assert hub["active_finding_counts"] is None and hub["active_finding_counts_complete"] is None
    detector = _one(read, GUARDDUTY_DETECTOR)
    assert detector["active_finding_counts_complete"] is True, "GuardDuty's totals come from the statistics call"
    # East had no watermark: a full read there.
    assert all("UpdatedAt" not in kw["Filters"] or "DateRange" in kw["Filters"]["UpdatedAt"][0] for kw in _calls(aws, "securityhub", "get_findings", EAST))


@pytest.mark.spec("req-aws-landing-zone-findings-10")
def test_an_unclean_read_writes_no_new_watermark() -> None:
    aws = with_findings()
    aws.on("securityhub", "get_findings", _err("ThrottlingException"), region=WEST)
    read = collect(aws, run_started=STARTED)
    assert not [k for k in read.read_through if k.startswith("securityhub|")]
    assert watermark_key("guardduty", MGMT, WEST) in read.read_through


@pytest.mark.django_db
@pytest.mark.spec("req-aws-landing-zone-findings-10")
def test_two_runs_carry_the_watermark_on_the_batch_node(monkeypatch: pytest.MonkeyPatch) -> None:
    """The importer stores the document's ``batch_node.metadata`` on ``Batch.metadata``; the next run reads it from
    the most recent closed batch of this collector, filters on it, and carries forward a key it did not refresh."""
    from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
    from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred
    from tap_plugin.aws_core.collectors.boto3_collector.collector import _SOURCE, Boto3Collector

    from tap_cares.collectors.config import CollectorConfig
    from tap_cares.secrets.models import Secret, SecretRef
    from tap_grid.models import Batch

    from .test_landing_zone import _Session

    def run(aws: Any) -> Boto3Collector:
        aws.on(
            "ec2",
            "describe_regions",
            {"Regions": [{"RegionName": r, "OptInStatus": "opt-in-not-required"} for r in REGIONS]},
        )
        aws.on("organizations", "describe_organization", _err("AWSOrganizationsNotInUseException"))
        monkeypatch.setattr(collector_mod, "build_session", lambda _data: _Session(aws))
        monkeypatch.setattr(collector_mod, "client_factory", lambda _s, region: lambda service: aws.client_for(service, region))
        collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
        collector.run()
        assert collector.results["error"] == []
        return collector

    secret = Secret(
        ref=SecretRef(scope="aws_core", key="boto_collector"),
        kind="aws_static_access_key",
        description="test",
        data={"access_key_id": "AKIA", "secret_access_key": "shh", "regions_allowed": REGIONS},
        metadata={},
        source_path=Path("/dev/null"),
    )
    monkeypatch.setattr(cred, "resolve_secret", lambda _ref: secret)
    monkeypatch.setattr(collector_mod, "caller_account_id", lambda *a, **k: MGMT)

    assert read_through_of(_SOURCE) == {}
    run(with_findings())
    first = read_through_of(_SOURCE)
    gd_west = watermark_key("guardduty", MGMT, WEST)
    assert gd_west in first, "the first run's clean sources are on its batch node"
    stored = Batch.objects.filter(source=_SOURCE).order_by("-closed_at").first()
    assert stored is not None and stored.metadata[READ_THROUGH] == first

    second = with_findings()
    second.on("securityhub", "get_findings", _err("ThrottlingException"), region=WEST)
    run(second)
    sh_west = watermark_key("securityhub", MGMT, WEST)
    marks = read_through_of(_SOURCE)
    assert marks[sh_west] == first[sh_west], "a failed source keeps its previous value"
    assert datetime.fromisoformat(marks[gd_west].replace("Z", "+00:00")) >= datetime.fromisoformat(
        first[gd_west].replace("Z", "+00:00")
    )
    active = [
        kw
        for kw in _calls(second, "guardduty", "list_findings", WEST)
        if kw["FindingCriteria"]["Criterion"]["service.archived"]["Equals"] == ["false"]
    ]
    assert active and all("updatedAt" in kw["FindingCriteria"]["Criterion"] for kw in active), "the second run filters"
    assert timedelta(0) < WATERMARK_OVERLAP
