"""Engine-core unit tests for the boto3 collector (boto3-free, no DB).

Covers req-aws-collector-manifest / -field-projection / -identity:
the restricted path evaluator, identity by ref, manifest
load+validate, and the configuration envelope.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime

import jsonschema
import pytest

from tap_plugin.aws_core.collectors.boto3_collector import manifest as manifest_mod
from tap_plugin.aws_core.collectors.boto3_collector.envelope import (
    build_configuration,
    jsonable,
    without_response_metadata,
)
from tap_plugin.aws_core.collectors.boto3_collector.identity import (
    NAMESPACE_AWS_COLLECTOR,
    IdentityError,
    edge_ref,
    node_ref,
    split_node_ref,
    undeclared_edge_id,
)
from tap_plugin.aws_core.collectors.boto3_collector.manifest import (
    ManifestError,
    load_manifest,
    manifest_entries,
)
from tap_plugin.aws_core.collectors.boto3_collector.paths import eval_path


class TestEvalPath:
    def test_scalar_and_dotted(self):
        item = {"FunctionArn": "arn:lambda", "LoggingConfig": {"LogGroup": "/aws/lambda/x"}}
        assert eval_path(item, "FunctionArn") == "arn:lambda"
        assert eval_path(item, "LoggingConfig.LogGroup") == "/aws/lambda/x"

    def test_missing_is_graceful(self):
        assert eval_path({}, "FunctionArn") is None
        assert eval_path({"LoggingConfig": {}}, "LoggingConfig.LogGroup") is None
        assert eval_path({"a": 1}, "a.b.c") is None  # scalar where dict expected

    def test_top_level_list_flatten(self):
        resp = {"Functions": [{"FunctionArn": "a"}, {"FunctionArn": "b"}]}
        assert eval_path(resp, "Functions[]") == [{"FunctionArn": "a"}, {"FunctionArn": "b"}]

    def test_bare_list_expr(self):
        items = [{"Id": "z1"}, {"Id": "z2"}]
        assert eval_path(items, "[]") == items

    def test_nested_flatten(self):
        resp = {"DistributionList": {"Items": [{"ARN": "a"}, {"ARN": "b"}]}}
        assert eval_path(resp, "DistributionList.Items[]") == [{"ARN": "a"}, {"ARN": "b"}]

    def test_flatten_then_project_fanout(self):
        item = {"Origins": {"Items": [{"DomainName": "a.s3"}, {"DomainName": "b.s3"}]}}
        assert eval_path(item, "Origins.Items[].DomainName") == ["a.s3", "b.s3"]

    def test_flatten_missing_or_wrongtype_is_empty(self):
        assert eval_path({}, "Functions[]") == []
        assert eval_path({"Functions": "nope"}, "Functions[]") == []
        assert eval_path({"Origins": {}}, "Origins.Items[].DomainName") == []


class TestIdentity:
    """req-aws-collector-identity: a ref names a source object in one batch; it is never a grid id."""

    def test_namespace_is_frozen(self):
        assert NAMESPACE_AWS_COLLECTOR == uuid.uuid5(uuid.NAMESPACE_DNS, "tap.aws_core.boto3_collector")

    def test_node_ref_is_type_and_natural_key(self):
        assert node_ref("aws_core__aws_lambda", "arn:x") == "aws_core__aws_lambda:arn:x"
        assert node_ref("aws_core__aws_lambda", "arn:y") != node_ref("aws_core__aws_lambda", "arn:x")
        assert node_ref("aws_core__aws_s3_bucket", "arn:x") != node_ref("aws_core__aws_lambda", "arn:x")

    def test_split_node_ref_keeps_a_key_that_carries_colons(self):
        assert split_node_ref("aws_core__aws_lambda:arn:aws:lambda:r:1:function:f") == (
            "aws_core__aws_lambda",
            "arn:aws:lambda:r:1:function:f",
        )
        with pytest.raises(IdentityError):
            split_node_ref("no-colon")

    def test_edge_ref_is_directional(self):
        fn, role = node_ref("aws_core__aws_lambda", "arn:fn"), node_ref("aws_core__aws_iam_role", "arn:role")
        assert edge_ref("ASSUMES_ROLE__aws_core", fn, role) != edge_ref("ASSUMES_ROLE__aws_core", role, fn)
        assert edge_ref("WRITES_LOGS__aws_core", fn, role) != edge_ref("ASSUMES_ROLE__aws_core", fn, role)

    def test_undeclared_edge_id_is_the_derivation_existing_rows_carry(self):
        """An edge type that declares no identity keeps the uuid5 id its rows were written under."""
        assert undeclared_edge_id("ROUTES_TRAFFIC__aws_core", "Z1", "arn:d") == uuid.uuid5(
            NAMESPACE_AWS_COLLECTOR, "edge:ROUTES_TRAFFIC__aws_core:Z1->arn:d"
        )


class TestManifest:
    def test_loads_and_validates(self):
        m = load_manifest()
        assert m["manifest_version"] == "0"
        entries = manifest_entries()
        assert len(entries) == 23
        for e in entries:
            assert {
                "entity_type",
                "service",
                "scope",
                "source",
                "why",
                "items_path",
                "natural_key",
                "fields",
            } <= e.keys()
            assert e["scope"] in ("regional", "global")
            assert ("aws_op" in e["source"]) ^ ("custom_fn" in e["source"])

    def test_schema_rejects_bad_manifest(self):
        schema = json.loads(manifest_mod.SCHEMA_PATH.read_text())
        bad = {"manifest_version": "0", "entries": [{"entity_type": "x"}]}  # missing required
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)

    def test_manifest_error_on_missing_file(self, tmp_path, monkeypatch):
        load_manifest.cache_clear()
        monkeypatch.setattr(manifest_mod, "MANIFEST_PATH", tmp_path / "nope.json")
        with pytest.raises(ManifestError):
            load_manifest()
        load_manifest.cache_clear()


class TestEnvelope:
    def test_strip_response_metadata(self):
        assert without_response_metadata({"a": 1, "ResponseMetadata": {"RequestId": "r"}}) == {"a": 1}
        assert without_response_metadata([1, 2]) == [1, 2]

    def test_jsonable_datetime_to_iso_z(self):
        dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        assert jsonable(dt) == "2026-01-02T03:04:05Z"
        assert jsonable(datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02T03:04:05Z"  # naive -> UTC
        assert jsonable(date(2026, 1, 2)) == "2026-01-02"
        assert jsonable({"t": [dt]}) == {"t": ["2026-01-02T03:04:05Z"]}

    def test_build_configuration_deterministic_with_source(self):
        item = {"FunctionArn": "arn:x", "LastModified": datetime(2026, 1, 1, tzinfo=UTC)}
        c1 = build_configuration(item, source_op="ListFunctions", why="why-x")
        c2 = build_configuration(item, source_op="ListFunctions", why="why-x")
        assert c1 == c2
        assert c1["_source"] == {"op": "ListFunctions", "why": "why-x"}
        assert c1["LastModified"] == "2026-01-01T00:00:00Z"
        assert json.dumps(c1, sort_keys=True) == json.dumps(c2, sort_keys=True)
