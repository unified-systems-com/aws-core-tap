"""The manifest's "not offered" claims against botocore's own partition data (req-aws-collector-partition-14).

Botocore lists the services each partition has an endpoint for. Its silence proves nothing, since it synthesises a
hostname for a service it has no entry for, and a service it lists can still fail to resolve (seven of the ten services
wave 0 could not reach in GovCloud are listed by it). So only a claim that rests on documentation or on botocore's own
data is held to it: an entry marked ``web``, ``read`` or ``inferred`` whose service botocore lists for the partition is a
claim the data contradicts. A claim marked ``ran`` rests on a live call that failed, and stands.
"""

from __future__ import annotations

import pytest
from botocore.session import get_session
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries


def _listed_by_botocore(partition: str) -> set[str]:
    data = get_session().get_data("endpoints")
    block = next(p for p in data["partitions"] if p["partition"] == partition)
    return set(block["services"])


def _endpoint_prefix(service: str) -> str | None:
    try:
        return get_session().get_service_model(service).endpoint_prefix
    except Exception:  # noqa: BLE001 - a service botocore has no model for cannot be contradicted by it
        return None


def _claims():
    for entry in manifest_entries():
        for partition, block in (entry.get("not_offered") or {}).items():
            yield entry, partition, block


@pytest.mark.spec("req-aws-collector-partition-14")
def test_no_documented_or_inferred_claim_is_contradicted_by_botocores_partition_data():
    contradicted = []
    for entry, partition, block in _claims():
        if block["method"] == "ran":
            continue
        prefix = _endpoint_prefix(entry["service"])
        if prefix and prefix in _listed_by_botocore(partition):
            contradicted.append((entry["entity_type"], partition, block["method"]))
    assert not contradicted, f"botocore lists an endpoint for these, so their claim needs a live call (ran): {contradicted}"


@pytest.mark.spec("req-aws-collector-partition-14")
def test_the_claims_the_manifest_makes_cite_a_method_botocore_can_be_held_to():
    assert any(block["method"] != "ran" for _e, _p, block in _claims()), "CloudFront rests on documentation, so the check above bites"
