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


def _listed(partition: str, entity_type: str) -> bool:
    entry = {"service": _SERVICE[entity_type], "entity_type": entity_type}
    return bool(partition_mod.entry_unavailable_reason(partition, entry))


def test_every_entry_the_newest_record_could_not_reach_is_listed():
    record = _newest("aws-us-gov")
    assert record is not None
    missing = [
        r["entity_type"]
        for r in record["results"]
        if r.get("error_class") == "EndpointConnectionError"
        and not _listed("aws-us-gov", r["entity_type"])
        and r["entity_type"] not in ACCEPTED
    ]
    assert not missing, f"unreachable in {record['run']['date']}'s record and not on the list: {missing}"


def test_no_listed_entry_is_shown_reachable_by_the_newest_record():
    record = _newest("aws-us-gov")
    assert record is not None
    reachable = [
        r["entity_type"]
        for r in record["results"]
        if r["outcome"] in ("ok", "empty") and _listed("aws-us-gov", r["entity_type"]) and r["entity_type"] not in ACCEPTED
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
