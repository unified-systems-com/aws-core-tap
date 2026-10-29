"""The coverage ledger (specs/spec-aws-core-coverage-ledger.md): facts join decisions, deterministically.

No network and no Django: the bundle is a handful of synthetic schemas, botocore is replaced by hand-built
service facts, and the committed ledger and decisions are checked against their schemas and each other.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import tomllib
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from tap_plugin.aws_core.ledger import __main__ as cli
from tap_plugin.aws_core.ledger import sources
from tap_plugin.aws_core.ledger.build import STATES, Inputs, LedgerError, build_ledger, render
from tap_plugin.aws_core.ledger.sources import BotoService, SameHostRedirect, SourceError, confine, load_cfn_bundle

PACKAGE = Path(cli.PACKAGE)


def _schema(type_name: str, **extra: Any) -> dict[str, Any]:
    return {"typeName": type_name, "primaryIdentifier": ["/properties/Id"], "handlers": {"list": {}}, **extra}


BUNDLE = {
    "aws-ec2-vpc.json": _schema(
        "AWS::EC2::VPC", tagging={"taggable": True, "tagProperty": "/properties/Tags"}
    ),
    "aws-ec2-vpccidrblock.json": _schema("AWS::EC2::VPCCidrBlock", tagging={"taggable": False}),
    "aws-sqs-queue.json": _schema("AWS::SQS::Queue", tagging={"taggable": True, "tagProperty": "/properties/Tags"}),
    "aws-sqs-queuepolicy.json": _schema("AWS::SQS::QueuePolicy", tagging={"taggable": False}),
    "aws-pinpoint-app.json": _schema("AWS::Pinpoint::App"),
    "aws-newsvc-thing.json": _schema("AWS::NewSvc::Thing", taggable=True),
    "aws-govless-thing.json": _schema("AWS::GovLess::Thing", tagging={"taggable": True}),
}

BOTO = {
    "ec2": BotoService("ec2", "ec2", True),
    "sqs": BotoService("sqs", "sqs", True),
    "pinpoint": BotoService("pinpoint", "pinpoint", True),
    "govless": BotoService("govless", "govless", False),
}


def _write_bundle(root: Path) -> Path:
    root.mkdir()
    for name, document in BUNDLE.items():
        (root / name).write_text(json.dumps(document))
    return root


def _inputs(tmp_path: Path, **overrides: Any) -> Inputs:
    cfn, sha = load_cfn_bundle(_write_bundle(tmp_path / "bundle"))
    values: dict[str, Any] = {
        "cfn": cfn,
        "cfn_sha256": sha,
        "botocore_version": "1.0.0",
        "boto": BOTO,
        "partitions": {
            "aws": frozenset({"ec2", "sqs", "pinpoint", "govless"}),
            "aws-us-gov": frozenset({"ec2", "sqs"}),
        },
        "named_prefixes": frozenset({"ec2", "sqs", "pinpoint", "govless"}),
        "decisions": {
            "service_map": {},
            "type_map": {
                "aws_core__aws_vpc": {"cfn": ["AWS::EC2::VPC"]},
                "aws_core__aws_sqs_queue": {"cfn": ["AWS::SQS::Queue"]},
                "aws_core__aws_az": {"cfn": [], "reason": "Reference data, not a CloudFormation resource."},
            },
            "classification": {
                "AWS::SQS::QueuePolicy": {"state": "excluded", "reason": "A policy document on the queue, not a node."}
            },
        },
        "models": frozenset({"aws_core__aws_vpc", "aws_core__aws_sqs_queue", "aws_core__aws_az"}),
        "manifest": {"aws_core__aws_sqs_queue": {"entity_type": "aws_core__aws_sqs_queue", "tags": {"source": "service"}}},
    }
    values.update(overrides)
    return Inputs(**values)


def _rows(inputs: Inputs) -> dict[str, dict[str, Any]]:
    return {row["type_name"]: row for row in build_ledger(inputs)["rows"]}


@pytest.mark.spec("req-aws-core-ledger-states")
def test_states_come_from_decisions_and_the_manifest(tmp_path: Path) -> None:
    rows = _rows(_inputs(tmp_path))
    assert rows["AWS::EC2::VPC"]["state"] == "modeled"
    assert rows["AWS::SQS::Queue"]["state"] == "collected-unverified"
    assert rows["AWS::SQS::QueuePolicy"]["state"] == "excluded"
    assert rows["AWS::SQS::QueuePolicy"]["reason"].startswith("A policy document")
    assert rows["AWS::Pinpoint::App"]["state"] == "unclassified"
    assert {row["state"] for row in rows.values()} <= set(STATES)


@pytest.mark.spec("req-aws-core-ledger-states")
def test_a_model_with_no_resource_type_is_listed_with_its_reason(tmp_path: Path) -> None:
    ledger = build_ledger(_inputs(tmp_path))
    assert ledger["unmapped_models"] == [
        {"entity_type": "aws_core__aws_az", "reason": "Reference data, not a CloudFormation resource."}
    ]


@pytest.mark.spec("req-aws-core-ledger-denominator")
def test_the_same_inputs_build_the_same_bytes(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    first = render(build_ledger(inputs))
    second = render(build_ledger(inputs))
    assert first == second


@pytest.mark.spec("req-aws-core-ledger-tags")
def test_untaggable_needs_a_positive_source_and_silence_is_not_evidence(tmp_path: Path) -> None:
    rows = _rows(_inputs(tmp_path))
    untaggable = rows["AWS::EC2::VPCCidrBlock"]["tags"]
    assert (untaggable["treatment"], untaggable["evidence"]) == ("none", "confirmed")
    assert "tagging.taggable is false" in untaggable["citation"]
    silent = rows["AWS::Pinpoint::App"]["tags"]
    assert (silent["treatment"], silent["evidence"], silent["citation"]) == (None, "not-found", None)
    # A type the schema calls taggable keeps its tag property and gets the treatment its manifest entry uses.
    queue = rows["AWS::SQS::Queue"]["tags"]
    assert (queue["treatment"], queue["tag_property"]) == ("side-call", "/properties/Tags")
    assert rows["AWS::EC2::VPC"]["tags"]["treatment"] is None


@pytest.mark.spec("req-aws-core-ledger-tags")
def test_the_deprecated_top_level_taggable_is_read_when_there_is_no_tagging_block(tmp_path: Path) -> None:
    row = _rows(_inputs(tmp_path))["AWS::NewSvc::Thing"]
    assert row["tags"]["taggable"] is True
    assert row["cfn"]["has_tagging_block"] is False


@pytest.mark.spec("req-aws-core-ledger-scope")
def test_tier_is_both_commercial_only_or_unknown_never_a_guess(tmp_path: Path) -> None:
    rows = _rows(_inputs(tmp_path))
    assert rows["AWS::EC2::VPC"]["tier"] == "both"
    assert rows["AWS::Pinpoint::App"]["tier"] == "commercial-only"
    # No botocore service and a service botocore does not name are both "does not say", not "unavailable".
    assert rows["AWS::NewSvc::Thing"]["tier"] == "unknown"
    assert rows["AWS::NewSvc::Thing"]["partitions"] == {"aws": None, "aws-us-gov": None}


@pytest.mark.spec("req-aws-core-ledger-denominator")
def test_a_service_with_no_list_or_describe_is_recorded_not_enumerable_by_botocore(tmp_path: Path) -> None:
    rows = _rows(_inputs(tmp_path))
    assert rows["AWS::GovLess::Thing"]["enumerable_by_botocore"] is False
    assert rows["AWS::GovLess::Thing"]["state"] == "unclassified"
    assert rows["AWS::NewSvc::Thing"]["enumerable_by_botocore"] is None


@pytest.mark.spec("req-aws-core-ledger-denominator")
def test_the_summary_counts_what_the_rows_say(tmp_path: Path) -> None:
    ledger = build_ledger(_inputs(tmp_path))
    summary = ledger["summary"]
    assert summary["types"] == len(ledger["rows"]) == len(BUNDLE)
    assert sum(summary["by_state"].values()) == summary["types"]
    both = [r for r in ledger["rows"] if r["tier"] == "both"]
    assert summary["in_scope_types"] == len(both)
    assert summary["in_scope_unclassified"] == sum(r["state"] == "unclassified" for r in both)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["type_map"].__setitem__("aws_core__aws_vpc", {"cfn": ["AWS::Nope::Thing"]}), "no type AWS::Nope::Thing"),
        (lambda d: d["classification"].__setitem__("AWS::EC2::VPC", {"state": "excluded", "reason": "A reason."}), "also modelled"),
        (lambda d: d["type_map"].pop("aws_core__aws_sqs_queue"), "missing the model aws_core__aws_sqs_queue"),
        (lambda d: d["service_map"].__setitem__("EC2", ["not-a-botocore-service"]), "no service 'not-a-botocore-service'"),
        (lambda d: d["type_map"].__setitem__("aws_core__aws_az", {"cfn": []}), "no CloudFormation type and no reason"),
        (lambda d: d["type_map"].__setitem__("aws_core__ghost", {"cfn": ["AWS::EC2::VPC"]}), "has no model"),
    ],
)
def test_decisions_that_disagree_with_the_facts_are_refused(tmp_path: Path, mutate: Any, message: str) -> None:
    inputs = _inputs(tmp_path)
    decisions = copy.deepcopy(inputs.decisions)
    mutate(decisions)
    with pytest.raises(LedgerError, match=message):
        build_ledger(dataclasses.replace(inputs, decisions=decisions))


@pytest.mark.spec("req-aws-core-ledger-denominator")
def test_a_manifest_entry_with_no_model_is_refused(tmp_path: Path) -> None:
    manifest = {"aws_core__aws_unknown": {"entity_type": "aws_core__aws_unknown"}}
    with pytest.raises(LedgerError, match="manifest: aws_core__aws_unknown has no model"):
        build_ledger(_inputs(tmp_path, manifest=manifest))


def test_a_zip_and_a_directory_give_the_same_types(tmp_path: Path) -> None:
    directory = _write_bundle(tmp_path / "dir")
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for name, document in BUNDLE.items():
            z.writestr(name, json.dumps(document))
    assert load_cfn_bundle(directory)[0] == load_cfn_bundle(archive)[0]


def test_the_bundle_is_data_only_and_hostile_members_are_ignored_or_refused(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("aws-ec2-vpc.json", json.dumps(BUNDLE["aws-ec2-vpc.json"]))
        z.writestr("../escape.json", json.dumps(_schema("AWS::Evil::Escape")))
        z.writestr("/abs.json", json.dumps(_schema("AWS::Evil::Absolute")))
        z.writestr("payload.py", "raise SystemExit('executed')")
        z.writestr("readme.txt", "ignored")
    types, _ = load_cfn_bundle(archive)
    assert set(types) == {"AWS::EC2::VPC"}


def test_a_bundle_that_is_not_one_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SourceError, match="neither a zip nor a directory"):
        load_cfn_bundle(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SourceError, match="holds no CloudFormation resource type"):
        load_cfn_bundle(empty)
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "a.json").write_text(json.dumps(_schema("not a type name")))
    with pytest.raises(SourceError, match="is not a CloudFormation type name"):
        load_cfn_bundle(bad)
    twice = tmp_path / "twice"
    twice.mkdir()
    for name in ("a.json", "b.json"):
        (twice / name).write_text(json.dumps(_schema("AWS::EC2::VPC")))
    with pytest.raises(SourceError, match="appears twice"):
        load_cfn_bundle(twice)
    big = tmp_path / "big"
    big.mkdir()
    (big / "a.json").write_text(json.dumps(_schema("AWS::EC2::VPC")))
    monkeypatch.setattr(sources, "MAX_MEMBER_BYTES", 10)
    with pytest.raises(SourceError, match="is over 10 bytes"):
        load_cfn_bundle(big)


@pytest.mark.spec("req-aws-core-ledger-denominator")
def test_a_built_ledger_validates_against_its_schema(tmp_path: Path) -> None:
    schema = json.loads((PACKAGE / "aws_coverage_ledger.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(json.loads(render(build_ledger(_inputs(tmp_path)))))


# -- the committed decisions --------------------------------------------------------------------------------


def test_the_committed_decisions_validate_and_cover_every_model() -> None:
    decisions = cli.load_decisions()
    models = set(tomllib.loads(cli.PLUGIN_TOML.read_text())["models"])
    assert set(decisions["type_map"]) == models
    entries = json.loads(cli.MANIFEST_PATH.read_text())["entries"]
    assert {e["entity_type"] for e in entries} <= models


# -- paths and the one address -------------------------------------------------------------------------------


def test_a_path_argument_is_confined_to_the_working_or_temporary_directory(tmp_path: Path) -> None:
    assert confine(tmp_path / "bundle") == (tmp_path / "bundle").resolve()
    with pytest.raises(SourceError, match="outside the working directory"):
        confine("/etc/passwd")
    with pytest.raises(SourceError, match="outside the working directory"):
        confine(tmp_path.joinpath(*[".."] * 12, "etc", "passwd"))


def test_a_symbolic_link_out_of_the_allowed_places_is_refused(tmp_path: Path) -> None:
    link = tmp_path / "escape"
    link.symlink_to("/etc")
    with pytest.raises(SourceError, match="outside the working directory"):
        confine(link / "passwd")
    with pytest.raises(SourceError, match="outside the working directory"):
        load_cfn_bundle(link)


def test_the_download_follows_a_redirect_only_to_the_same_https_host() -> None:
    handler = SameHostRedirect()
    request = urllib.request.Request("https://schema.example.test/bundle.zip")
    kept = handler.redirect_request(request, None, 302, "Found", {}, "https://schema.example.test/other.zip")
    assert kept is not None and kept.full_url == "https://schema.example.test/other.zip"
    for refused in ("https://elsewhere.example.test/bundle.zip", "http://schema.example.test/bundle.zip"):
        with pytest.raises(urllib.error.URLError, match="refused a redirect"):
            handler.redirect_request(request, None, 302, "Found", {}, refused)
