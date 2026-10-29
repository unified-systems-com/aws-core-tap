"""A tag read that did not answer is not an empty tag set (aws-core-tap#111, req-aws-collector-tags).

Pure functions, no grid: a failed, refused or skipped read resolves to UNREAD and the node envelope
leaves ``tags`` out, so core's keep-absent upsert (tap#1128) leaves the stored tags alone. ``{}`` is
only ever a successful read of an untagged resource.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector.batch import UNREAD, node_envelope
from tap_plugin.aws_core.collectors.boto3_collector.collector import resolve_node_tags
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    cloudtrail_trails_described,
    kms_keys_described,
    sqs_queues_described,
)
from tap_plugin.aws_core.collectors.boto3_collector.projection import ProjectedNode


def _node() -> ProjectedNode:
    return ProjectedNode(
        entity_type="aws_core__aws_lambda",
        natural_key="arn:fn",
        name="fn",
        fields={"function_arn": "arn:fn"},
        configuration={},
        raw_item={},
    )


class TestEnvelope:
    def test_unread_omits_the_tags_field(self):
        assert "tags" not in node_envelope(_node(), {}, UNREAD, persist_configuration=False)["node"]

    def test_unread_drops_a_tags_value_a_projector_left_in_the_fields(self):
        node = _node()
        node.fields["tags"] = {"stale": "value"}
        assert "tags" not in node_envelope(node, {}, UNREAD, persist_configuration=False)["node"]

    def test_an_empty_read_still_sends_an_explicit_empty_map(self):
        assert node_envelope(_node(), {}, {}, persist_configuration=False)["node"]["tags"] == {}

    def test_a_read_map_is_sent_whole(self):
        assert node_envelope(_node(), {}, {"a": "1"}, persist_configuration=False)["node"]["tags"] == {"a": "1"}


def _denied(op: str, code: str = "AccessDeniedException") -> ClientError:
    return ClientError({"Error": {"Code": code}}, op)


class _TagClient:
    def __init__(self, exc: Exception | None = None, payload: dict[str, Any] | None = None) -> None:
        self._exc, self._payload = exc, payload or {}

    def list_tags_for_resource(self, **_kw: Any) -> dict[str, Any]:
        if self._exc:
            raise self._exc
        return self._payload


SERVICE = {"source": "service", "op": "ListTagsForResource", "params": {"Arn": {"from": "Arn"}}, "path": "Tags", "shape": "list_kv"}


class TestResolver:
    def _resolve(self, block: dict[str, Any], item: Any, **kw: Any):
        entry = {"entity_type": "x", "service": "s", "natural_key": "Arn", "tags": block}
        return resolve_node_tags(entry, item, rgta_map=kw.pop("rgta_map", {}), client_for=kw.pop("client_for", None), **kw)

    @pytest.mark.parametrize("code", ["AccessDeniedException", "ThrottlingException", "InternalError"])
    def test_a_refused_or_failed_service_call_is_unread(self, code: str):
        client = _TagClient(_denied("ListTagsForResource", code))
        tags, slot, _ = self._resolve(SERVICE, {"Arn": "a"}, client_for=lambda _s: client)
        assert tags is UNREAD
        assert slot is not None and slot["status"] in ("denied", "error")

    def test_a_missing_resource_or_empty_answer_is_an_answer(self):
        gone = _TagClient(_denied("ListTagsForResource", "NoSuchEntity"))
        assert self._resolve(SERVICE, {"Arn": "a"}, client_for=lambda _s: gone)[0] == {}
        empty = _TagClient(payload={"Tags": []})
        assert self._resolve(SERVICE, {"Arn": "a"}, client_for=lambda _s: empty)[0] == {}

    def test_a_skipped_rgta_sweep_is_unread_not_untagged(self):
        block = {"source": "rgta", "resource_type_filter": "lambda:function"}
        item = {"Arn": "a"}
        assert self._resolve(block, item, rgta_unread=True)[0] is UNREAD
        assert self._resolve(block, item)[0] == {}
        assert self._resolve(block, item, rgta_map={"a": {"k": "v"}})[0] == {"k": "v"}

    def test_a_field_the_custom_fn_could_not_fill_is_unread(self):
        block = {"source": "field", "from": "_tags", "shape": "map"}
        assert self._resolve(block, {"_tags": {}, "_tags_unread": True})[0] is UNREAD
        assert self._resolve(block, {"_tags": {}, "_tags_unread": False})[0] == {}
        assert self._resolve(block, {"Name": "no-tags-key"})[0] == {}


class _Kms:
    def can_paginate(self, _m: str) -> bool:
        return False

    def list_keys(self, **_kw):
        return {"Keys": [{"KeyId": "k1", "KeyArn": "arn:k1"}]}

    def list_aliases(self, **_kw):
        return {"Aliases": []}

    def describe_key(self, **_kw):
        return {"KeyMetadata": {"KeyId": "k1", "Arn": "arn:k1"}}

    def list_resource_tags(self, **_kw):
        raise _denied("ListResourceTags")


class _Sqs:
    def can_paginate(self, _m: str) -> bool:
        return False

    def list_queues(self, **_kw):
        return {"QueueUrls": ["https://sqs/1/q"]}

    def get_queue_attributes(self, **_kw):
        return {"Attributes": {"QueueArn": "arn:aws:sqs:us-east-1:1:q"}}

    def list_queue_tags(self, **_kw):
        raise _denied("ListQueueTags")


class _Trail:
    meta = SimpleNamespace(region_name="us-east-1")

    def can_paginate(self, _m: str) -> bool:
        return False

    def describe_trails(self, **_kw):
        return {"trailList": [{"Name": "t", "TrailARN": "arn:aws:cloudtrail:us-east-1:1:trail/t", "HomeRegion": "us-east-1"}]}

    def get_trail_status(self, **_kw):
        return {"IsLogging": True}

    def list_tags(self, **_kw):
        raise _denied("ListTags")


class TestCustomFunctionsMarkAFailedTagRead:
    def test_kms(self):
        (key,) = list(kms_keys_described(None, client_for=lambda _s: _Kms()))
        assert key["_tags_unread"] is True

    def test_sqs(self):
        (queue,) = list(sqs_queues_described(None, client_for=lambda _s: _Sqs()))
        assert queue["_tags_unread"] is True

    def test_cloudtrail(self):
        trails = list(cloudtrail_trails_described(None, client_for=lambda _s: _Trail()))
        assert [t["_tags_unread"] for t in trails] == [True]
