"""``req-aws-collector-enrich-1``: one detail call per listed resource, stored under ``_hydrate.detail``."""

from __future__ import annotations

import botocore.session
import pytest
from botocore.exceptions import ClientError

from tap_plugin.aws_core.collectors.boto3_collector.batch import entry_redact_paths
from tap_plugin.aws_core.collectors.boto3_collector.envelope import redact_configuration
from tap_plugin.aws_core.collectors.boto3_collector.collector import enrich_item
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries

ENRICHED = [e for e in manifest_entries() if e.get("enrich")]
_SESSION = botocore.session.get_session()


def _model(service: str):
    key = service.replace("-", "")
    return _SESSION.get_service_model(key if key in _SESSION.get_available_services() else service)


def test_the_sweep_enriched_the_summary_only_types() -> None:
    assert len(ENRICHED) >= 100


@pytest.mark.parametrize("entry", ENRICHED, ids=lambda e: e["entity_type"])
def test_the_detail_call_is_a_real_read_with_all_its_required_inputs(entry) -> None:
    block = entry["enrich"]
    model = _model(entry["service"])
    assert block["op"] in model.operation_names
    assert block["op"].startswith(("Get", "Describe"))
    assert not any(word in block["op"] for word in ("Secret", "Password", "Token", "Credential", "Key"))
    shape = model.operation_model(block["op"]).input_shape
    required = set(shape.required_members) if shape else set()
    assert required <= set(block["params"]), f"{entry['entity_type']}: {block['op']} also needs {required - set(block['params'])}"
    assert set(block["params"]) <= set(shape.members)


class _Client:
    def __init__(self, response=None, error=None) -> None:
        self.response, self.error, self.calls = response, error, []

    def __getattr__(self, name):
        def call(**kwargs):
            self.calls.append((name, kwargs))
            if self.error:
                raise ClientError({"Error": {"Code": self.error, "Message": "x"}}, name)
            return self.response

        return call


_BLOCK = {"op": "DescribeBroker", "params": {"BrokerId": {"from": "BrokerId"}}, "why": "detail"}


def test_the_detail_response_is_stored_with_its_status_and_the_parameters_come_from_the_item() -> None:
    client = _Client({"BrokerId": "b-1", "EngineType": "ActiveMQ", "ResponseMetadata": {"RequestId": "r"}})
    slot = enrich_item(_BLOCK, {"BrokerId": "b-1"}, service="mq", client_for=lambda _s: client)
    assert client.calls == [("describe_broker", {"BrokerId": "b-1"})]
    assert slot["status"] == "ok" and slot["data"] == {"BrokerId": "b-1", "EngineType": "ActiveMQ"}


def test_a_timestamp_in_the_detail_response_is_stored_as_json() -> None:
    """aws-core-tap#213: boto3 returns datetimes; one left raw in the slot rejected the whole live batch."""
    import json
    from datetime import UTC, datetime

    client = _Client({"BrokerId": "b-1", "Created": datetime(2026, 11, 9, 12, 30, tzinfo=UTC), "Users": [{"At": datetime(2026, 1, 2)}]})
    slot = enrich_item(_BLOCK, {"BrokerId": "b-1"}, service="mq", client_for=lambda _s: client)
    json.dumps(slot, allow_nan=False)  # raises TypeError on any value JSON cannot carry
    assert slot["data"]["Created"] == "2026-11-09T12:30:00Z"
    assert slot["data"]["Users"] == [{"At": "2026-01-02T00:00:00Z"}]


def test_a_refused_detail_call_is_a_denied_slot_not_a_crash() -> None:
    slot = enrich_item(_BLOCK, {"BrokerId": "b-1"}, service="mq", client_for=lambda _s: _Client(error="AccessDeniedException"))
    assert slot["status"] == "denied"


def test_a_secret_in_the_detail_response_is_removed_before_storage() -> None:
    entry = next(e for e in ENRICHED if entry_redact_paths(e) and any(p.startswith("_hydrate.detail.data.") for p in entry_redact_paths(e)))
    path = next(p for p in entry_redact_paths(entry) if p.startswith("_hydrate.detail.data."))
    keys = path.removeprefix("_hydrate.detail.data.").replace("[]", "").split(".")
    data: dict = {}
    cursor = data
    for key in keys[:-1]:
        cursor[key] = {}
        cursor = cursor[key]
    cursor[keys[-1]] = "PLANTED-SECRET-91c2"
    config = {"_hydrate": {"detail": {"status": "ok", "op": "x", "data": data}}}
    stored = redact_configuration(config, [path])
    assert "PLANTED-SECRET-91c2" not in str(stored)


def test_the_stored_envelope_has_no_secret_from_the_detail_response() -> None:
    """End to end through ``node_envelope`` (where redaction runs, after the detail slot is attached)."""
    from tap_plugin.aws_core.collectors.boto3_collector.batch import node_envelope
    from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item

    entry = next(e for e in ENRICHED if any(p.startswith("_hydrate.detail.data.") and "[]" not in p and "." not in p.removeprefix("_hydrate.detail.data.") for p in entry_redact_paths(e)))
    path = next(p for p in entry_redact_paths(entry) if p.startswith("_hydrate.detail.data.") and "[]" not in p and "." not in p.removeprefix("_hydrate.detail.data."))
    member = path.removeprefix("_hydrate.detail.data.")
    item = {entry["natural_key"]: "arn:aws:x:us-east-1:123456789012:thing/y"}
    node = project_item(entry, item)
    node.configuration.setdefault("_hydrate", {})["detail"] = {"status": "ok", "op": entry["enrich"]["op"], "data": {member: "PLANTED-SECRET-77aa"}}
    payload = node_envelope(node, {}, {}, persist_configuration=True, redact_paths=entry_redact_paths(entry))["node"]
    assert "PLANTED-SECRET-77aa" not in str(payload["configuration"])
