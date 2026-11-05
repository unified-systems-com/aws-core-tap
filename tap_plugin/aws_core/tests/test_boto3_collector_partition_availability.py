"""Entries a partition does not offer (req-aws-collector-partition-7, -8 and -11): the list and the skip."""

from __future__ import annotations

import json

import pytest
from tap_plugin.aws_core.collectors.boto3_collector import partition as partition_mod
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.partition import (
    PARTITION_AWS,
    PARTITION_US_GOV,
    entry_unavailable_reason,
)
from tap_plugin.aws_core.tests import test_boto3_collector_selection_run as base

_ENTRIES = {e["entity_type"]: e for e in manifest_entries()}
#: The nine services every entry of which failed to connect in the wave 0 run, and the three Well-Architected entries.
_WHOLE = {
    "qbusiness", "timestream-influxdb", "kinesisvideo", "notifications", "cloudwatchomni",
    "ecr-public", "internetmonitor", "datazone", "kendra-ranking",
}  # fmt: skip
_AGENT = {"wellarchitected_agent_context", "wellarchitected_agent_goal", "wellarchitected_agent_profile"}


def _entry(entity: str) -> dict:
    return _ENTRIES[f"aws_core__aws_{entity}"]


class TestTheList:
    @pytest.mark.spec("req-aws-collector-partition-8")
    def test_govcloud_lists_the_twenty_two_entries_of_the_wave_0_record_and_the_two_named_services(self):
        listed = [e for e in _ENTRIES.values() if entry_unavailable_reason(PARTITION_US_GOV, e)]
        assert {e["service"] for e in listed} == _WHOLE | {"cloudfront", "wellarchitected"}
        assert len([e for e in listed if e["service"] in _WHOLE]) == 19
        assert {e["entity_type"].removeprefix("aws_core__aws_") for e in listed if e["service"] == "wellarchitected"} == _AGENT
        assert partition_mod.service_unavailable_reason(PARTITION_US_GOV, "macie2")

    @pytest.mark.spec("req-aws-collector-partition-7")
    def test_the_grain_is_the_entry_where_a_service_is_served_in_part(self):
        assert entry_unavailable_reason(PARTITION_US_GOV, _entry("wellarchitected_agent_profile"))
        assert entry_unavailable_reason(PARTITION_US_GOV, _entry("wellarchitected_lens")) is None
        assert entry_unavailable_reason(PARTITION_US_GOV, _entry("qbusiness_plugin"))
        assert entry_unavailable_reason(PARTITION_US_GOV, _entry("ec2_instance")) is None

    @pytest.mark.spec("req-aws-collector-partition-7")
    def test_the_commercial_partition_lists_nothing(self):
        assert not [e for e in _ENTRIES.values() if entry_unavailable_reason(PARTITION_AWS, e)]

    @pytest.mark.spec("req-aws-collector-partition-7")
    def test_every_listed_entity_type_is_in_the_manifest_and_every_listed_service_is_known(self):
        data = json.loads(partition_mod.AVAILABILITY_FILE.read_text())
        services = {e["service"] for e in _ENTRIES.values()} | {"macie2"}
        for block in data["partitions"].values():
            for item in block["entries"]:
                assert item.get("entity_type") in _ENTRIES or item.get("service") in services, item

    @pytest.mark.spec("req-aws-collector-partition-7")
    @pytest.mark.parametrize(
        "item",
        [
            {"service": "x", "description": "d", "evidence": "e", "date": "2026-11-04"},  # no method
            {"service": "x", "method": "ran", "evidence": "e", "date": "2026-11-04"},  # no description
            {"service": "x", "entity_type": "y", "description": "d", "method": "ran", "evidence": "e", "date": "d"},
        ],
    )
    def test_a_malformed_file_stops_the_load(self, tmp_path, item):
        path = tmp_path / "list.json"
        path.write_text(json.dumps({"partitions": {"aws-us-gov": {"entries": [item]}}}))
        with pytest.raises(ValueError):
            partition_mod._load_unavailable(path)


@pytest.mark.django_db
class TestInARun:
    @pytest.mark.spec("req-aws-collector-partition-7")
    def test_a_listed_service_makes_no_call_and_says_why_once_per_entry(self, monkeypatch):
        base._install(monkeypatch, include_types=["qbusiness:*"])
        collector = base._run()
        assert not [s for s, _op in base._RecordingClient.calls if s == "qbusiness"]
        notes = [r for r in collector.results["info"] if r["message_code"] == "SERVICE_NOT_AVAILABLE_IN_PARTITION"]
        assert len(notes) == len([e for e in _ENTRIES.values() if e["service"] == "qbusiness"])
        assert all("not available in partition aws-us-gov" in r["message"] for r in notes)

    @pytest.mark.spec("req-aws-collector-partition-11")
    def test_listed_entries_do_not_make_a_full_run_a_selected_run(self, monkeypatch):
        base._install(monkeypatch)
        collector = base._run()
        assert collector._surfaces and collector._surfaces_declared is True
        applied = base._applied(collector)
        assert applied["entries_skipped"] == 0
        assert len([r for r in collector.results["info"] if r["message_code"] == "SERVICE_NOT_AVAILABLE_IN_PARTITION"]) >= 22
