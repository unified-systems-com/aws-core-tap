"""The comparison logic of compare.py with synthetic data (no Django, no AWS)."""

import json
import os
import sys
from pathlib import Path

SEED = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SEED))
os.environ.pop("SEED_EXPECTED", None)  # importing must not run the container path

import compare  # noqa: E402

KEY = "arn:aws-us-gov:sqs:us-gov-west-1:123456789012:q"
EDGE = ("ENCRYPTED_WITH_KEY__aws_core", "outbound", "aws_core__aws_kms_key", "k1")


def exp(key=KEY, attrs=None, tags=None, edges=()):
    return {"natural_key": key, "attrs": attrs if attrs is not None else {"visibility_timeout": 30, "name": "q"},
            "tags": tags if tags is not None else {"tap-seed": "wave1"},
            "edges": [dict(zip(("edge_type", "direction", "target_type", "target_key"), e, strict=True)) for e in edges]}


_DEFAULT = object()


def row(key=KEY, fields=None, tags=_DEFAULT, edges=()):
    return {"natural_key": key, "fields": fields if fields is not None else {"visibility_timeout": "30", "name": "q"},
            "tags": {"tap-seed": "wave1"} if tags is _DEFAULT else tags, "edges": list(edges)}


def run(expected, rows, again=None, **kw):
    fields = kw.pop("compared", ["visibility_timeout", "name"])
    return compare.compare_type("aws_core__aws_sqs_queue", "AWS::SQS::Queue", expected, fields, rows, rows if again is None else again, **kw)


def test_pass_with_loose_scalars_and_extra_rows():
    rec = run([exp()], [row(), row(key="other")])
    assert rec["verdict"] == "pass" and rec["first_mismatch"] is None and "rows_in_account" not in rec


def test_zero_expected_is_call_path_only():
    assert run([], [row()])["verdict"] == "call-path-only"


def test_missing_and_duplicate_rows():
    assert run([exp()], [])["first_mismatch"].startswith("missing-row @")
    assert run([exp()], [row(), row()])["first_mismatch"].startswith("duplicate-rows @")


def test_field_mismatch_names_the_field_not_the_value():
    rec = run([exp()], [row(fields={"visibility_timeout": "31", "name": "q"})])
    assert rec["verdict"] == "fail" and rec["first_mismatch"].startswith("field-differs:visibility_timeout @")
    assert "31" not in rec["first_mismatch"]


def test_none_is_not_equal_to_a_value_and_empty_list_equals_empty_list():
    assert run([exp(attrs={"name": None})], [row(fields={"name": "q"})], compared=["name"])["verdict"] == "fail"
    assert run([exp(attrs={"name": []})], [row(fields={"name": []})], compared=["name"])["verdict"] == "pass"


def test_tags_empty_unread_null_and_differ():
    assert run([exp(tags={})], [row(tags={})])["verdict"] == "pass"
    assert run([exp()], [row(tags=compare.UNREAD_MARK)])["first_mismatch"].startswith("tags-unread")
    assert run([exp()], [row(tags=None)])["first_mismatch"].startswith("tags-null")
    assert run([exp()], [row(tags={})])["first_mismatch"].startswith("tags-differ")
    assert run([exp(tags={})], [row(tags={"x": "y"})])["first_mismatch"].startswith("tags-differ")


def test_edges_expected_must_be_emitted():
    assert run([exp(edges=[EDGE])], [row(edges=[EDGE])])["verdict"] == "pass"
    rec = run([exp(edges=[EDGE])], [row()])
    assert rec["first_mismatch"].startswith("edge-missing:ENCRYPTED_WITH_KEY__aws_core")
    assert rec["edges_expected"] == 1


def test_second_pass_must_match():
    assert run([exp()], [row()], again=[])["first_mismatch"].endswith("(second-pass)")
    assert run([exp()], [row()], again=[row(), row()])["first_mismatch"].startswith("second-pass-duplicate")
    assert run([exp()], [row()], again=[row(tags={"tap-seed": "other"})])["first_mismatch"].startswith("second-pass-differs")


def test_read_error_fails_and_account_numbers_are_scrubbed():
    rec = run([exp()], None, read_error="ClientError")
    assert rec["verdict"] == "fail" and rec["first_mismatch"] == "read-error:ClientError"
    out = run([exp()], [])
    assert "123456789012" not in out["first_mismatch"] and "<account>" in out["first_mismatch"]


def test_uncovered_declared_edges_are_reported_not_passed():
    rec = run([exp()], [row()], manifest_edges=[("ENCRYPTED_WITH_KEY__aws_core", "aws_core__aws_kms_key"), ("X__aws_core", "aws_core__aws_vpc")],
              seeded_types={"aws_core__aws_kms_key"})
    assert rec["verdict"] == "pass" and rec["uncovered_edges"] == ["ENCRYPTED_WITH_KEY__aws_core->aws_core__aws_kms_key"]


def test_report_is_deterministic_and_counts_verdicts():
    full = json.loads((SEED / "seeding.json").read_text(encoding="utf-8"))
    catalog = {"types": {"AWS::SQS::Queue": full["types"]["AWS::SQS::Queue"]}}  # the one type this synthetic wave seeds
    doc = {"wave": ["wave1"], "resources": [
        {"entity_type": "aws_core__aws_sqs_queue", "natural_key": KEY, "attrs": {f: None for f in catalog["types"]["AWS::SQS::Queue"]["compares"]}, "tags": {}, "edges": []}]}
    rows = {"aws_core__aws_sqs_queue": [row(fields={f: None for f in catalog["types"]["AWS::SQS::Queue"]["compares"]}, tags={})]}
    a = compare.build_report(doc, catalog, rows, rows, {}, {})
    b = compare.build_report(doc, catalog, rows, rows, {}, {})
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["counts"] == {"pass": 1} and [t["cfn_type"] for t in a["types"]] == ["AWS::SQS::Queue"]
    assert "123456789012" not in json.dumps(a)
    # the real catalog names 24 types: a doc that seeds one of them fails for the other 23, it does not pass
    whole = compare.build_report(doc, full, rows, rows, {}, {})
    assert whole["counts"] == {"fail": 23, "pass": 1}


def test_the_catalog_is_found_beside_the_file_or_at_the_mount(tmp_path):
    assert compare.catalog_path(str(SEED / "compare.py")) == str(SEED / "seeding.json")
    assert compare.catalog_path(str(tmp_path / "manage.py"), mount="/m") == "/m/seeding.json"  # a __file__ that names something else
    assert compare.catalog_path(None, mount="/m") == "/m/seeding.json"


def test_compare_uses_the_wave_zero_read_guard_not_a_verb_prefix():
    text = (SEED / "compare.py").read_text()
    assert "from readguard import install" in text and "install(session)" in text
    assert "read_verb" not in text


def test_a_type_the_wave_should_seed_but_the_state_lacks_fails_the_record():
    doc = {"wave": ["wave1"], "resources": [{"entity_type": "t", "natural_key": "k", "attrs": {}, "tags": {}, "edges": []}]}
    catalog = {"types": {"AWS::X::Y": {"entity_type": "t", "module": "wave1", "compares": []},
                         "AWS::X::Z": {"entity_type": "u", "module": "wave1", "compares": []},
                         "AWS::X::W": {"entity_type": "w", "module": "wave2", "compares": []}}}
    got = {"t": [row(key="k", fields={}, tags={})]}
    report = compare.build_report(doc, catalog, got, got, {}, {})
    assert report["counts"] == {"fail": 1, "pass": 1}
    missing = [r for r in report["types"] if r["verdict"] == "fail"]
    assert missing[0]["entity_type"] == "u" and missing[0]["first_mismatch"] == "seeded-type-absent-from-state"  # wave2's type is not this wave's


def test_unresolved_expected_edge_targets_fail_the_record():
    doc = {"wave": ["wave1"], "resources": [{"entity_type": "t", "natural_key": "k", "attrs": {}, "tags": {}, "edges": []}], "unresolved_edge_targets": 2}
    catalog = {"types": {"AWS::X::Y": {"entity_type": "t", "compares": []}}}
    report = compare.build_report(doc, catalog, {"t": [row(key="k", fields={}, tags={})]}, {"t": [row(key="k", fields={}, tags={})]}, {}, {})
    assert report["counts"].get("fail") == 1 and report["types"][-1]["first_mismatch"] == "unresolved-edge-targets:2"
    clean = compare.build_report({**doc, "unresolved_edge_targets": 0}, catalog, {"t": [row(key="k", fields={}, tags={})]}, {"t": [row(key="k", fields={}, tags={})]}, {}, {})
    assert "fail" not in clean["counts"]


def test_canon():
    assert compare.canon(True) == "true" and compare.canon(30) == compare.canon("30") == "30" and compare.canon(1.0) == "1"
    assert compare.canon(["b", "a"]) == compare.canon(["a", "b"]) and compare.canon({"b": 1, "a": 2}) == {"a": "2", "b": "1"}
