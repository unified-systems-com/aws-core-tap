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
from typing import Any, cast

import jsonschema
import pytest

from tap_plugin.aws_core.ledger import __main__ as cli
from tap_plugin.aws_core.ledger import sources
from tap_plugin.aws_core.ledger.build import STATES, Inputs, LedgerError, _available, build_ledger, render
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
    "aws-elbv2-loadbalancer.json": _schema("AWS::ElasticLoadBalancingV2::LoadBalancer", tagging={"taggable": True}),
}

BOTO = {
    "ec2": BotoService("ec2", "ec2", True),
    "sqs": BotoService("sqs", "sqs", True),
    "pinpoint": BotoService("pinpoint", "pinpoint", True),
    "govless": BotoService("govless", "govless", False),
    # The name, the endpoint prefix and the CloudFormation service all differ; only the service id says it.
    # A botocore service no CloudFormation service resolves to: it still gets a row (the spec's denominator).
    "orphan": BotoService("orphan", "orphan", True),
    "elbv2": BotoService("elbv2", "elasticloadbalancing", True, aliases=frozenset({"elasticloadbalancingv2"})),
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
            "aws": frozenset({"ec2", "sqs", "pinpoint", "govless", "elasticloadbalancing", "orphan"}),
            "aws-us-gov": frozenset({"ec2", "sqs", "elasticloadbalancing", "orphan"}),
        },
        "named_prefixes": frozenset({"ec2", "sqs", "pinpoint", "govless", "elasticloadbalancing", "orphan"}),
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
            "service_classification": {},
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
        (lambda d: d["service_map"].__setitem__("Typo", ["ec2"]), "no CloudFormation service 'Typo'"),
        (
            lambda d: d["service_classification"].__setitem__("sqs", {"state": "excluded", "reason": "Has CloudFormation types."}),
            "has CloudFormation types",
        ),
        (
            lambda d: d["service_classification"].__setitem__("nope", {"state": "excluded", "reason": "Not a botocore service."}),
            "botocore has no service 'nope'",
        ),
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
    with pytest.raises(SourceError, match="over the size limit"):
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


@pytest.mark.spec("req-aws-core-ledger-denominator")
def test_a_service_is_found_by_any_of_its_botocore_names(tmp_path: Path) -> None:
    # ElasticLoadBalancingV2 is botocore's elbv2 with endpoint prefix elasticloadbalancing: neither normalises to it.
    row = _rows(_inputs(tmp_path))["AWS::ElasticLoadBalancingV2::LoadBalancer"]
    assert row["botocore_services"] == ["elbv2"]
    assert row["tier"] == "both"


@pytest.mark.spec("req-aws-core-ledger-scope")
def test_a_modeled_type_outside_the_in_scope_tier_is_named_in_the_summary(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    decisions = copy.deepcopy(inputs.decisions)
    decisions["type_map"]["aws_core__aws_pinpoint_app"] = {"cfn": ["AWS::Pinpoint::App"]}
    swapped = dataclasses.replace(
        inputs, decisions=decisions, models=inputs.models | {"aws_core__aws_pinpoint_app"}
    )
    assert build_ledger(swapped)["summary"]["modeled_not_in_scope_tier"] == ["AWS::Pinpoint::App"]
    assert build_ledger(inputs)["summary"]["modeled_not_in_scope_tier"] == []


def test_a_bundle_over_the_total_size_is_refused_whatever_its_members_weigh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Many individually valid members can add up to far more than the archive's own size.
    monkeypatch.setattr(sources, "MAX_TOTAL_BYTES", 300)
    archive = tmp_path / "many.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for index in range(6):
            z.writestr(f"t{index}.json", json.dumps(_schema(f"AWS::EC2::Thing{index}")))
    with pytest.raises(SourceError, match="over the size limit"):
        load_cfn_bundle(archive)
    directory = tmp_path / "many"
    directory.mkdir()
    for index in range(6):
        (directory / f"t{index}.json").write_text(json.dumps(_schema(f"AWS::EC2::Thing{index}")))
    with pytest.raises(SourceError, match="over the size limit"):
        load_cfn_bundle(directory)


def test_a_directory_with_too_many_members_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources, "MAX_MEMBERS", 2)
    for index in range(3):
        (tmp_path / f"t{index}.json").write_text(json.dumps(_schema(f"AWS::EC2::Thing{index}")))
    with pytest.raises(SourceError, match="more than 2 members"):
        load_cfn_bundle(tmp_path)


def test_the_download_will_not_write_through_a_symbolic_link_left_at_its_target(tmp_path: Path) -> None:
    # Confining the directory is not enough if the file name in it is a link elsewhere.
    outside = tmp_path / ".." / ".." / ".." / ".." / ".." / ".." / "etc" / "hosts"
    (tmp_path / "CloudformationSchema.zip").symlink_to(outside.resolve())
    with pytest.raises(SourceError, match="outside the working directory"):
        sources.download_bundle(tmp_path)


def test_a_directory_member_that_is_a_symbolic_link_is_refused_not_followed(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "aws-ec2-vpc.json").write_text(json.dumps(BUNDLE["aws-ec2-vpc.json"]))
    (bundle / "evil.json").symlink_to("/etc/hosts")
    with pytest.raises(SourceError, match="is a symbolic link"):
        load_cfn_bundle(bundle)


def test_a_zip_member_is_read_with_a_bound_not_trusted_for_its_declared_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "big.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("aws-ec2-vpc.json", json.dumps(BUNDLE["aws-ec2-vpc.json"]) + " " * 400)
    monkeypatch.setattr(sources, "MAX_MEMBER_BYTES", 300)
    with pytest.raises(SourceError, match="over the size limit"):
        load_cfn_bundle(archive)


@pytest.mark.spec("req-aws-core-ledger-denominator")
def test_a_botocore_service_with_no_cloudformation_type_still_gets_a_row(tmp_path: Path) -> None:
    # The denominator is botocore's service list; a service CloudFormation never mentions is recorded, not omitted.
    inputs = _inputs(tmp_path)
    ledger = build_ledger(inputs)
    assert [r["service"] for r in ledger["service_rows"]] == ["orphan"]
    orphan = ledger["service_rows"][0]
    assert (orphan["state"], orphan["tier"], orphan["reason"]) == ("unclassified", "both", None)
    summary = ledger["summary"]
    assert summary["botocore_services"] == len(BOTO)
    assert summary["botocore_only_services"] == 1 and summary["botocore_only_in_scope_unclassified"] == 1
    assert summary["in_scope_unclassified_all"] == summary["in_scope_unclassified"] + 1
    decided = copy.deepcopy(inputs.decisions)
    decided["service_classification"]["orphan"] = {"state": "excluded", "reason": "A data-plane API with no resources."}
    row = build_ledger(dataclasses.replace(inputs, decisions=decided))["service_rows"][0]
    assert (row["state"], row["reason"]) == ("excluded", "A data-plane API with no resources.")


@pytest.mark.spec("req-aws-core-ledger-tags")
@pytest.mark.parametrize("bad", [0, 1, "false", "true", None, []])
def test_a_taggable_that_is_not_a_boolean_is_refused_not_coerced(tmp_path: Path, bad: Any) -> None:
    # bool("false") is True and bool(0) is False: coercing would turn a malformed bundle into tag evidence.
    for index, document in enumerate(
        (_schema("AWS::EC2::VPC", tagging={"taggable": bad}), _schema("AWS::EC2::VPC", taggable=bad))
    ):
        folder = tmp_path / f"b{index}"
        folder.mkdir()
        (folder / "a.json").write_text(json.dumps(document))
        with pytest.raises(SourceError, match="not a boolean"):
            load_cfn_bundle(folder)


class _FakeResponse:
    """What an opener returns: a context manager with the final address and a body to read."""

    def __init__(self, url: str, body: bytes) -> None:
        self._url, self._body = url, body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        chunk, self._body = self._body[:size], self._body[size:]
        return chunk


class _Opener:
    def __init__(self, on_open: Any, response: _FakeResponse) -> None:
        self._on_open, self._response = on_open, response

    def open(self, request: Any, timeout: float = 0) -> _FakeResponse:
        self._on_open()
        return self._response


def test_a_link_planted_at_the_target_during_the_download_is_replaced_not_written_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The target was checked before the request; something may create a link there while the body arrives.
    outside = tmp_path / "victim.txt"
    outside.write_text("untouched")
    dest = tmp_path / "dl"
    target = dest / "CloudformationSchema.zip"
    origin = f"https://{sources.BUNDLE_URL.split('/')[2]}/CloudformationSchema.zip"

    def plant() -> None:
        target.symlink_to(outside)

    monkeypatch.setattr(
        urllib.request, "build_opener", lambda *_: _Opener(plant, _FakeResponse(origin, b"zip-bytes"))
    )
    path, size, _ = sources.download_bundle(dest)
    assert outside.read_text() == "untouched"
    assert path == target and not path.is_symlink() and path.read_bytes() == b"zip-bytes" and size == 9
    assert [p.name for p in dest.iterdir()] == ["CloudformationSchema.zip"]


def test_a_failed_download_leaves_no_partial_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "dl"
    elsewhere = _FakeResponse("https://elsewhere.example.test/x.zip", b"data")
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: _Opener(lambda: None, elsewhere))
    with pytest.raises(SourceError, match="not "):
        sources.download_bundle(dest)
    assert list(dest.iterdir()) == []


@pytest.mark.spec("req-aws-core-ledger-tags")
def test_a_manifest_that_says_no_tags_for_a_taggable_type_is_a_contradiction(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    manifest = {"aws_core__aws_sqs_queue": {"entity_type": "aws_core__aws_sqs_queue", "tags": {"source": "none"}}}
    with pytest.raises(LedgerError, match="says it has no tags, but the CloudFormation schema says it is taggable"):
        build_ledger(dataclasses.replace(inputs, manifest=manifest))


@pytest.mark.spec("req-aws-core-ledger-tags")
def test_a_manifest_that_collects_tags_for_an_untaggable_type_is_a_recorded_conflict(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    manifest = {"aws_core__aws_vpc": {"tags": {"source": "service"}}}
    cfn = dict(inputs.cfn)
    cfn["AWS::EC2::VPC"] = dataclasses.replace(cfn["AWS::EC2::VPC"], taggable=False)
    tags = _rows(dataclasses.replace(inputs, cfn=cfn, manifest=manifest))["AWS::EC2::VPC"]["tags"]
    assert (tags["treatment"], tags["evidence"], tags["taggable"]) == ("side-call", "conflict", False)
    assert "manifest collects tags" in tags["citation"]


@pytest.mark.spec("req-aws-core-ledger-scope")
def test_a_known_absence_beside_an_unnamed_service_is_unknown_not_unavailable(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    boto = dict(inputs.boto)
    boto["ec2b"] = dataclasses.replace(boto["ec2"], endpoint_prefix="ec2b")
    gov = {**inputs.partitions, "aws-us-gov": frozenset()}
    probe = dataclasses.replace(inputs, boto=boto, partitions=gov)
    assert _available(["ec2"], "aws-us-gov", probe) is False
    assert _available(["ec2", "ec2b"], "aws-us-gov", probe) is None
    assert _available(["ec2b"], "aws-us-gov", probe) is None


@pytest.mark.spec("req-aws-core-ledger-tags")
def test_entities_of_one_type_that_disagree_on_tag_treatment_are_refused(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    decisions = json.loads(json.dumps(inputs.decisions))
    decisions["type_map"]["aws_core__aws_sqs_queue_alt"] = {"cfn": ["AWS::SQS::Queue"]}
    manifest = {
        "aws_core__aws_sqs_queue": {"tags": {"source": "service"}},
        "aws_core__aws_sqs_queue_alt": {"tags": {"source": "rgta"}},
    }
    models = inputs.models | {"aws_core__aws_sqs_queue_alt"}
    with pytest.raises(LedgerError, match="disagree on tag treatment"):
        build_ledger(dataclasses.replace(inputs, decisions=decisions, manifest=manifest, models=models))


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"primaryIdentifier": "/properties/Id"}, "primaryIdentifier is not a list of strings"),
        ({"primaryIdentifier": [1, 2]}, "primaryIdentifier is not a list of strings"),
        ({"handlers": "list"}, "handlers is not an object"),
        ({"handlers": ["list"]}, "handlers is not an object"),
    ],
)
def test_a_malformed_identifier_or_handlers_is_refused_not_coerced(
    tmp_path: Path, fields: dict[str, Any], message: str
) -> None:
    (tmp_path / "a.json").write_text(json.dumps({**_schema("AWS::EC2::VPC"), **fields}))
    with pytest.raises(SourceError, match=message):
        load_cfn_bundle(tmp_path)


def test_a_zip_over_the_archive_size_is_refused_before_it_is_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "big.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("a.json", json.dumps(_schema("AWS::EC2::VPC")))
    monkeypatch.setattr(sources, "MAX_BUNDLE_BYTES", 50)
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("read the whole archive before checking its size"))
    with pytest.raises(SourceError, match="is over 50 bytes"):
        load_cfn_bundle(archive)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"tagging": "taggable"}, "tagging is not an object"),
        ({"tagging": None}, "tagging is not an object"),
        ({"tagging": ["taggable"]}, "tagging is not an object"),
        ({"tagging": {"taggable": True, "tagProperty": 7}}, "tagProperty is not a string"),
        ({"tagging": {"taggable": True, "tagProperty": ["/properties/Tags"]}}, "tagProperty is not a string"),
    ],
)
def test_malformed_tagging_metadata_is_refused_not_read_as_no_evidence(
    tmp_path: Path, fields: dict[str, Any], message: str
) -> None:
    (tmp_path / "a.json").write_text(json.dumps({**_schema("AWS::EC2::VPC"), **fields}))
    with pytest.raises(SourceError, match=message):
        load_cfn_bundle(tmp_path)


@pytest.mark.parametrize("content", [b"x", b"PK\x03\x04 truncated"])
def test_a_corrupt_zip_is_a_refusal_not_a_traceback(tmp_path: Path, content: bytes) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(content)
    with pytest.raises(SourceError, match="not a readable zip"):
        load_cfn_bundle(bad)


def test_a_member_that_is_not_utf8_is_a_refusal(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(SourceError, match="is not JSON"):
        load_cfn_bundle(tmp_path)


def _committed() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(cli.LEDGER_PATH.read_text()))


@pytest.mark.spec("req-aws-core-ledger-states")
def test_the_committed_ledger_matches_its_schema_and_its_own_summary() -> None:
    ledger = _committed()
    schema = json.loads((cli.PACKAGE / "aws_coverage_ledger.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(ledger)
    rows = ledger["rows"]
    assert ledger["summary"]["types"] == len(rows)
    for state, count in ledger["summary"]["by_state"].items():
        assert count == sum(1 for r in rows if r["state"] == state), state
    assert len({r["type_name"] for r in rows}) == len(rows)


@pytest.mark.spec("req-aws-core-ledger-states")
def test_the_committed_ledger_agrees_with_the_manifest() -> None:
    entries = json.loads(cli.MANIFEST_PATH.read_text())["entries"]
    collected = {e["entity_type"] for e in entries}
    in_ledger = {
        entity for r in _committed()["rows"] if r["state"].startswith("collected") for entity in r["entity_types"]
    }
    # Every manifest entry that maps to a CloudFormation type is a collected row, and no collected row lacks one.
    assert in_ledger <= collected
    unmapped = {u["entity_type"] for u in _committed()["unmapped_models"]}
    assert collected - in_ledger <= unmapped | {
        entity for r in _committed()["rows"] for entity in r["entity_types"] if not r["state"].startswith("collected")
    }


@pytest.mark.spec("req-aws-core-ledger-tags")
def test_a_tag_finding_settles_a_conflict_and_a_not_found_with_its_citation(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    cfn = dict(inputs.cfn)
    cfn["AWS::EC2::VPC"] = dataclasses.replace(cfn["AWS::EC2::VPC"], taggable=False)
    cite = "botocore iam defines TagPolicy and ListPolicyTags, so the type has tags"
    decisions = json.loads(json.dumps(inputs.decisions))
    decisions["tag_findings"] = {"AWS::EC2::VPC": {"taggable": True, "citation": cite}}
    manifest = {"aws_core__aws_vpc": {"tags": {"source": "service"}}}
    tags = _rows(dataclasses.replace(inputs, cfn=cfn, decisions=decisions, manifest=manifest))["AWS::EC2::VPC"]["tags"]
    assert (tags["treatment"], tags["evidence"], tags["taggable"]) == ("side-call", "confirmed", True)
    assert tags["citation"].startswith(cite) and "overrides the CloudFormation schema" in tags["citation"]


@pytest.mark.spec("req-aws-core-ledger-tags")
def test_a_tag_finding_that_contradicts_the_manifest_or_names_no_type_is_refused(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    cite = "botocore has no Tag or ListTags operation for this type at all"
    for finding, manifest, message in (
        ({"taggable": False, "citation": cite}, {"aws_core__aws_sqs_queue": {"tags": {"source": "service"}}}, "manifest collects them"),
        ({"taggable": True, "citation": cite}, {"aws_core__aws_sqs_queue": {"tags": {"source": "none"}}}, "manifest says it has none"),
    ):
        decisions = json.loads(json.dumps(inputs.decisions))
        decisions["tag_findings"] = {"AWS::SQS::Queue": finding}
        with pytest.raises(LedgerError, match=message):
            build_ledger(dataclasses.replace(inputs, decisions=decisions, manifest=manifest))
    decisions = json.loads(json.dumps(inputs.decisions))
    decisions["tag_findings"] = {"AWS::No::Such": {"taggable": True, "citation": cite}}
    with pytest.raises(LedgerError, match="the bundle has no type AWS::No::Such"):
        build_ledger(dataclasses.replace(inputs, decisions=decisions))
