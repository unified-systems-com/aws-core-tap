"""The manifest's ``not_offered`` blocks against the newest wave 0 record (req-aws-collector-partition-10).

The blocks keep the collector from calling an endpoint that is not there. It can rot two ways: an entry that
cannot be reached is missing from it, or a listed entry has become reachable. The newest wave 0 record for the
partition says which; this test fails with the entry named. A re-run of wave 0 that ignores the list
(``WAVE0_IGNORE_AVAILABILITY=1``) is the record that can show a listed entry reachable.
"""

from __future__ import annotations

import json
from pathlib import Path

from tap_plugin.aws_core.collectors.boto3_collector import partition as partition_mod
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries

RUNS = Path(__file__).resolve().parents[1] / "runs"
#: Entries that are knowingly out of step with the record, each with the reason. Empty is the goal.
ACCEPTED: dict[str, str] = {}

_SERVICE = {e["entity_type"]: e["service"] for e in manifest_entries()}


def _newest(partition: str) -> dict | None:
    records = [json.loads(p.read_text()) for p in sorted(RUNS.glob("wave0-*.json"))]
    records = [r for r in records if r.get("run", {}).get("partition") == partition]
    return records[-1] if records else None


_ENTRY = {e["entity_type"]: e for e in manifest_entries()}


def _listed(partition: str, entity_type: str, region: str | None = None, fips: bool = False) -> bool:
    """Whether the entry is skipped in the partition, in the region, by a run with FIPS endpoints on or off. Wave 0 ran
    in us-gov-west-1 with FIPS endpoints off."""
    return bool(partition_mod.entry_unavailable_reason(partition, _ENTRY[entity_type], region, fips))


def test_every_entry_the_newest_record_could_not_reach_is_listed():
    record = _newest("aws-us-gov")
    assert record is not None
    missing = [
        r["entity_type"]
        for r in record["results"]
        if r.get("error_class") == "EndpointConnectionError"
        and not _listed("aws-us-gov", r["entity_type"], r["region"])
        and r["entity_type"] not in ACCEPTED
    ]
    assert not missing, f"unreachable in {record['run']['date']}'s record and not on the list: {missing}"


def test_no_listed_entry_is_shown_reachable_by_the_newest_record():
    record = _newest("aws-us-gov")
    assert record is not None
    reachable = [
        r["entity_type"]
        for r in record["results"]
        if r["outcome"] in ("ok", "empty") and _listed("aws-us-gov", r["entity_type"], r["region"]) and r["entity_type"] not in ACCEPTED
    ]
    assert not reachable, f"on the list but reachable in {record['run']['date']}'s record: {reachable}"


def test_the_accepted_list_names_only_entries_that_are_actually_out_of_step():
    record = _newest("aws-us-gov")
    assert record is not None
    by_type = {r["entity_type"]: r for r in record["results"]}
    for entity_type, reason in ACCEPTED.items():
        assert reason.strip(), f"{entity_type}: an exemption states why"
        assert entity_type in by_type, f"accepted but not in the record: {entity_type}"
        result = by_type[entity_type]
        unreachable_and_unlisted = result.get("error_class") == "EndpointConnectionError" and not _listed("aws-us-gov", entity_type)
        reachable_and_listed = result["outcome"] in ("ok", "empty") and _listed("aws-us-gov", entity_type)
        assert unreachable_and_unlisted or reachable_and_listed, f"{entity_type} is accepted but the record and the list agree: remove it"


#: Variants of the live call record where the manifest and the record knowingly differ, each with the reason.
ACCEPTED_CALLS: dict[tuple[str, str, bool], str] = {
    ("managedblockchain", "us-gov-west-1", True): "a block holds one condition; this service has a host in gov-west only without FIPS, and the FIPS case is learned at run time",
}


def test_every_variant_of_the_live_call_record_agrees_with_the_manifest():
    """One real call per service, region and FIPS setting (runs/availability-calls-*.json): a service the record could not
    connect to is skipped there, and one that answered is not."""
    records = sorted(RUNS.glob("availability-calls-*.json"))
    assert records
    record = json.loads(records[-1].read_text())
    disagree = []
    for r in record["results"]:
        skipped = _listed("aws-us-gov", r["entity_type"], r["region"], r["fips"])
        if skipped != (r["outcome"] == "no_endpoint") and (r["service"], r["region"], r["fips"]) not in ACCEPTED_CALLS:
            disagree.append((r["service"], r["region"], r["fips"], r["outcome"], "skipped" if skipped else "called"))
    assert not disagree, disagree


def test_the_accepted_call_variants_are_actually_out_of_step():
    records = sorted(RUNS.glob("availability-calls-*.json"))
    record = json.loads(records[-1].read_text())
    by_variant = {(r["service"], r["region"], r["fips"]): r for r in record["results"]}
    for variant, reason in ACCEPTED_CALLS.items():
        assert reason.strip() and variant in by_variant, variant
        r = by_variant[variant]
        assert _listed("aws-us-gov", r["entity_type"], r["region"], r["fips"]) != (r["outcome"] == "no_endpoint"), f"{variant} agrees now: remove it"
