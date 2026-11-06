"""Entries a partition does not offer (req-aws-collector-partition-7, -8 and -11): the list and the skip."""

from __future__ import annotations

import pytest
from tap_plugin.aws_core.collectors.boto3_collector import partition as partition_mod
from tap.jsonfiles import JsonFileError, load_schema, validate_json
from tap_plugin.aws_core.collectors.boto3_collector.manifest import SCHEMA_PATH, manifest_entries
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
    def test_a_service_is_marked_on_all_of_its_entries_or_is_named_as_served_in_part(self):
        """The grain is the entry; a service marked on some of its entries and not others must be a known split."""
        split = set()
        for partition in (PARTITION_US_GOV, PARTITION_AWS):
            by_service: dict[str, list[bool]] = {}
            for e in _ENTRIES.values():
                by_service.setdefault(e["service"], []).append(partition in (e.get("not_offered") or {}))
            split |= {s for s, flags in by_service.items() if any(flags) and not all(flags)}
        assert split == {"wellarchitected"}, "a new split service needs a reason here, or its entries should all be marked"

    @pytest.mark.spec("req-aws-collector-partition-7")
    @pytest.mark.parametrize(
        "block",
        [
            {"aws-us-gov": {"why": "w", "method": "ran", "date": "2026-11-04"}},  # no evidence
            {"aws-us-gov": {"why": "w", "method": "guessed", "evidence": "e", "date": "2026-11-04"}},  # method
            {"aws-us-gov": {"why": "w", "method": "ran", "evidence": "e", "date": "yesterday"}},  # date
            {"aws-cn": {"why": "w", "method": "ran", "evidence": "e", "date": "2026-11-04"}},  # partition
        ],
    )
    def test_a_malformed_not_offered_block_fails_the_manifest_schema(self, block):
        schema = load_schema(SCHEMA_PATH)
        entry = {**_entry("ec2_instance"), "not_offered": block}
        with pytest.raises(JsonFileError):
            validate_json({"manifest_version": "0", "entries": [entry]}, schema, source="test")

    @pytest.mark.spec("req-aws-collector-partition-7")
    def test_the_blocks_the_manifest_carries_are_valid(self):
        schema = load_schema(SCHEMA_PATH)
        validate_json({"manifest_version": "0", "entries": list(_ENTRIES.values())}, schema, source="test")


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


def _entries_of(service: str) -> list[dict]:
    return [e for e in _ENTRIES.values() if e["service"] == service]


class TestRegionsAndFips:
    """A block may hold only in some regions of the partition, or only with FIPS endpoints on or off
    (req-aws-collector-partition-15)."""

    @pytest.mark.spec("req-aws-collector-partition-15")
    def test_a_service_offered_in_gov_west_only_is_skipped_in_gov_east_only(self):
        for entry in _entries_of("polly"):
            assert entry_unavailable_reason(PARTITION_US_GOV, entry, "us-gov-east-1", False)
            assert entry_unavailable_reason(PARTITION_US_GOV, entry, "us-gov-west-1", False) is None
            assert entry_unavailable_reason(PARTITION_US_GOV, entry) is None, "no region in hand: the block is not applied"

    @pytest.mark.spec("req-aws-collector-partition-15")
    def test_a_service_with_no_fips_endpoint_is_skipped_only_when_fips_is_on(self):
        for entry in _entries_of("schemas"):
            assert entry_unavailable_reason(PARTITION_US_GOV, entry, "us-gov-west-1", True)
            assert entry_unavailable_reason(PARTITION_US_GOV, entry, "us-gov-west-1", False) is None
            assert entry_unavailable_reason(PARTITION_US_GOV, entry, "us-gov-west-1", None) is None

    @pytest.mark.spec("req-aws-collector-partition-15")
    def test_kinesisvideo_is_skipped_unless_fips_is_on(self):
        for entry in _entries_of("kinesisvideo"):
            assert entry_unavailable_reason(PARTITION_US_GOV, entry, "us-gov-west-1", False)
            assert entry_unavailable_reason(PARTITION_US_GOV, entry, "us-gov-west-1", None)
            assert entry_unavailable_reason(PARTITION_US_GOV, entry, "us-gov-west-1", True) is None

    @pytest.mark.spec("req-aws-collector-partition-15")
    def test_a_block_with_both_limits_needs_both(self):
        (entry, *_) = _entries_of("bedrock-agent")
        assert entry_unavailable_reason(PARTITION_US_GOV, entry, "us-gov-east-1", True)
        assert entry_unavailable_reason(PARTITION_US_GOV, entry, "us-gov-east-1", False) is None
        assert entry_unavailable_reason(PARTITION_US_GOV, entry, "us-gov-west-1", True) is None

    @pytest.mark.spec("req-aws-collector-partition-15")
    def test_a_conditional_block_is_not_a_whole_service_listing(self):
        assert partition_mod.service_unavailable_reason(PARTITION_US_GOV, "polly") is None
        assert partition_mod.service_unavailable_reason(PARTITION_US_GOV, "kinesisvideo") is None

    @pytest.mark.spec("req-aws-collector-partition-15")
    @pytest.mark.parametrize(
        ("extra", "valid"),
        [
            ({"regions": ["us-gov-east-1"]}, True),
            ({"fips": True}, True),
            ({"regions": ["us-gov-east-1"], "fips": False}, True),
            ({"regions": []}, False),
            ({"regions": ["us-gov-east-1", "us-gov-east-1"]}, False),
            ({"fips": "yes"}, False),
        ],
    )
    def test_the_schema_takes_regions_and_fips_and_refuses_malformed_ones(self, extra, valid):
        schema = load_schema(SCHEMA_PATH)
        block = {"why": "w", "method": "ran", "evidence": "e", "date": "2026-11-05", **extra}
        entry = {**_entry("ec2_instance"), "not_offered": {"aws-us-gov": block}}
        if valid:
            validate_json({"manifest_version": "0", "entries": [entry]}, schema, source="test")
        else:
            with pytest.raises(JsonFileError):
                validate_json({"manifest_version": "0", "entries": [entry]}, schema, source="test")


@pytest.mark.django_db
class TestRegionsInARun:
    @pytest.mark.spec("req-aws-collector-partition-15")
    def test_a_west_only_service_is_called_in_west_and_skipped_in_east(self, monkeypatch):
        base._install(monkeypatch, include_types=["polly:*"], regions_allowed=["us-gov-west-1", "us-gov-east-1"])
        collector = base._run()
        skipped = [r for r in collector.results["info"] if r["message_code"] == "SERVICE_NOT_AVAILABLE_IN_PARTITION"]
        assert skipped and {r["message_data"]["region"] for r in skipped} == {"us-gov-east-1"}
        assert [s for s, _op in base._RecordingClient.calls if s == "polly"], "still called in gov-west"
