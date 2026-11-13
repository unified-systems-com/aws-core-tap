"""Tests for the CloudFormation verifier: synthetic specifications, ledger, manifest and run record, so nothing
needs a download, AWS or Django. The shell fetcher is checked by reading it only (it would need the network)."""

import json
import shutil
from pathlib import Path

import pytest

import cfn_reader
import cfn_verifier
import weighting

ROOT = Path(__file__).resolve().parents[3]


def _j(path: Path, doc) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    return path


def spec_doc(types: dict, version="270.0.0") -> dict:
    return {"ResourceSpecificationVersion": version, "PropertyTypes": {}, "ResourceTypes": types}


RDS = {
    "Properties": {
        "Engine": {"PrimitiveType": "String", "Required": True, "UpdateType": "Mutable"},
        "KmsKeyId": {"PrimitiveType": "String", "Required": False, "UpdateType": "Immutable"},
        "MasterUserPassword": {"PrimitiveType": "String", "Required": False, "UpdateType": "Mutable"},
        "Tags": {"Type": "List", "ItemType": "Tag", "Required": False, "UpdateType": "Mutable"},
    },
    "Attributes": {"DBInstanceArn": {"PrimitiveType": "String"}, "Endpoint.Address": {"PrimitiveType": "String"}},
}
SUBNET = {"Properties": {"VpcId": {"PrimitiveType": "String", "Required": True, "UpdateType": "Immutable"}}, "Attributes": {"SubnetId": {"PrimitiveType": "String"}}}
EXTRA = {"Properties": {"Name": {"PrimitiveType": "String", "Required": False, "UpdateType": "Mutable"}}}


def make_plugin(root: Path) -> Path:
    pkg = root / "tap_plugin/aws_core"
    (pkg / "ledger").mkdir(parents=True)
    shutil.copy(ROOT / "tap_plugin/aws_core/ledger/sources.py", pkg / "ledger/sources.py")
    (pkg / "models").mkdir()
    (pkg / "models/m.py").write_text(
        'class R:\n    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_rds_instance"\n    NATURAL_KEY: ClassVar[tuple] = ("arn",)\n'
        '    FIELD_CRUD_SCHEMA: ClassVar[dict] = {"engine": {}}\n'
        'class S:\n    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_subnet"\n    NATURAL_KEY: ClassVar[tuple] = ("subnet_id",)\n'
        '    FIELD_CRUD_SCHEMA: ClassVar[dict] = {"subnet_id": {}}\n'
    )
    entries = [
        {"entity_type": "aws_core__aws_rds_instance", "service": "rds", "natural_key": "DBInstanceArn", "persist_configuration": True,
         "source": {"aws_op": "DescribeDBInstances"}, "fields": {"engine": "Engine", "arn": "DBInstanceArn", "made_up": "NotInSpec"},
         "tags": {"source": "field"}},
        {"entity_type": "aws_core__aws_subnet", "service": "ec2", "natural_key": "SubnetId", "persist_configuration": False,
         "source": {"aws_op": "DescribeSubnets"}, "fields": {"subnet_id": "SubnetId"}, "tags": {"source": "none"}},
    ]
    _j(pkg / "collectors/boto3_collector/aws_resource_manifest.json", {"manifest_version": 1, "entries": entries})
    (pkg / "collectors/boto3_collector/c.py").write_text("def f(c):\n    c.list_things()\n")
    (pkg / "edges").mkdir()
    rows = [
        {"type_name": "AWS::RDS::DBInstance", "tier": "both", "entity_types": ["aws_core__aws_rds_instance"], "state": "collected-unverified"},
        {"type_name": "AWS::EC2::Subnet", "tier": "both", "entity_types": ["aws_core__aws_subnet"], "state": "collected-unverified"},
        {"type_name": "AWS::Extra::Thing", "tier": "commercial-only", "entity_types": ["aws_core__aws_extra"], "state": "collected-unverified"},
        {"type_name": "AWS::Hand::Written", "tier": "both", "entity_types": ["aws_core__aws_hand"], "state": "collected-unverified"},
        {"type_name": "AWS::Skipped::Thing", "tier": "both", "entity_types": [], "state": "excluded"},
    ]
    _j(pkg / "ledger/aws_coverage_ledger.json", {"cfn_bundle_sha256": "x", "rows": rows})
    _j(pkg / "ledger/decisions.json", {"tag_findings": {}})
    return root


def make_bundle(d: Path) -> Path:
    def doc(name, ro, pid, taggable, wo=()):
        return {"typeName": name, "primaryIdentifier": pid, "readOnlyProperties": ro, "writeOnlyProperties": list(wo),
                "createOnlyProperties": [], "tagging": {"taggable": taggable}, "handlers": {"list": {}}}
    _j(d / "a.json", doc("AWS::RDS::DBInstance", ["/properties/DBInstanceArn", "/properties/Endpoint/Address"], ["/properties/DBInstanceIdentifier"], True, ["/properties/MasterUserPassword"]))
    _j(d / "b.json", doc("AWS::EC2::Subnet", ["/properties/SubnetId"], ["/properties/SubnetId"], False))
    _j(d / "c.json", doc("AWS::Extra::Thing", [], ["/properties/Name"], True))
    return d


def record(outcomes: dict, regions=("us-gov-west-1",)) -> dict:
    return {"run": {"partition": "aws-us-gov", "regions": list(regions)},
            "results": [{"entity_type": k, "outcome": v} for k, v in outcomes.items()]}


@pytest.fixture
def world(tmp_path):
    plugin = make_plugin(tmp_path / "plugin")
    west = _j(tmp_path / "spec-us-gov-west-1.json", spec_doc({"AWS::RDS::DBInstance": RDS, "AWS::EC2::Subnet": SUBNET}))
    east = _j(tmp_path / "spec-us-gov-east-1.json", spec_doc({"AWS::EC2::Subnet": SUBNET}, version="271.0.0"))
    com = _j(tmp_path / "spec-us-east-1.json", spec_doc({"AWS::RDS::DBInstance": RDS, "AWS::EC2::Subnet": SUBNET, "AWS::Extra::Thing": EXTRA}))
    bundle = make_bundle(tmp_path / "bundle")
    # Inside the plugin, where real records live (tools/validate/runs): the verifier refuses a record outside the
    # plugin checkout or the working directory, and tmp_path is neither.
    rec = _j(plugin / "tools" / "validate" / "runs" / "rec.json", record({"aws_core__aws_rds_instance": "ok", "aws_core__aws_subnet": "unsupported", "aws_core__aws_extra": "empty", "aws_core__aws_hand": "unsupported"}))
    return {"plugin": plugin, "specs": [west, east, com], "bundle": bundle, "rec": rec, "tmp": tmp_path}


W = Path(__file__).resolve().parents[1] / "weights" / "cartography-set-v1.json"


def go(world, **kw):
    args = dict(plugin=world["plugin"], spec_paths=world["specs"], weights_path=W, bundle_path=world["bundle"], record_path=world["rec"], manifest_path=None, primary=None)
    args.update(kw)
    return cfn_verifier.run(**args)


class TestReader:
    def test_normal_form(self, world):
        s = cfn_reader.read_spec(world["specs"][0])
        t = s["types"]["AWS::RDS::DBInstance"]
        assert s["version"] == "270.0.0" and len(s["sha256"]) == 64
        assert t["properties"]["Engine"] == {"required": True, "kind": "String", "update": "Mutable"}
        assert t["properties"]["Tags"]["kind"] == "List<Tag>"
        assert "Endpoint.Address" in t["attributes"]

    def test_refuses_empty(self, tmp_path):
        for doc in ({"ResourceTypes": {}}, {}, [], {"ResourceTypes": []}):
            with pytest.raises(cfn_reader.CfnReadError):
                cfn_reader.read_spec(_j(tmp_path / "e.json", doc))

    def test_refuses_bad_type_name(self, tmp_path):
        with pytest.raises(cfn_reader.CfnReadError):
            cfn_reader.read_spec(_j(tmp_path / "e.json", spec_doc({"not a type": {}})))

    def test_control_characters_replaced(self, tmp_path):
        p = _j(tmp_path / "e.json", spec_doc({"AWS::X::Y": {"Properties": {"Ev\x1b[31mil\nName": {"PrimitiveType": "String"}}}}, version="1\x07.0"))
        s = cfn_reader.read_spec(p)
        assert "\x1b" not in json.dumps(s, ensure_ascii=False) and "\n" not in list(s["types"]["AWS::X::Y"]["properties"])[0]
        assert "\x07" not in s["version"]
        assert cfn_reader.clean("a\x00b\u2028c") == "a b c"

    def test_refuses_symlink(self, tmp_path):
        real = _j(tmp_path / "real.json", spec_doc({"AWS::X::Y": {}}))
        link = tmp_path / "link.json"
        link.symlink_to(real)
        with pytest.raises(cfn_reader.CfnReadError):
            cfn_reader.read_spec(link)

    def test_bundle_through_ledger_reader(self, world):
        b = cfn_reader.read_bundle(world["plugin"], world["bundle"])
        t = b["types"]["AWS::RDS::DBInstance"]
        assert t["read_only"] == ["DBInstanceArn", "Endpoint"] and t["write_only"] == ["MasterUserPassword"]
        assert t["primary_identifier"] == ["/properties/DBInstanceIdentifier"] and t["taggable"] is True
        assert b["types"]["AWS::EC2::Subnet"]["taggable"] is False

    def test_manifest(self, tmp_path):
        p = tmp_path / "manifest.tsv"
        p.write_text("spec-b.json\tu\t200\tabc\t10\t270.0.0\nspec-a.json\tu\t200\tdef\t11\t270.0.0\n")
        assert [r["file"] for r in cfn_reader.read_manifest(p)] == ["spec-a.json", "spec-b.json"]
        p.write_text("only\ttwo\n")
        with pytest.raises(cfn_reader.CfnReadError):
            cfn_reader.read_manifest(p)


class TestAvailability:
    def test_leads_per_region(self, world):
        a = go(world)["availability"]
        pr = a["per_region"]
        assert pr["us-gov-west-1"]["absent"] == 2 and pr["us-gov-east-1"]["absent"] == 3 and pr["us-east-1"]["absent"] == 1
        rows = {r["type"]: r for r in a["rows"]}
        assert rows["AWS::Extra::Thing"]["lead_absent_in"] == ["us-gov-east-1", "us-gov-west-1"]
        assert "AWS::Skipped::Thing" not in rows  # not claimed collected

    def test_contradictions(self, world):
        a = go(world)["availability"]
        flags = {(c["type"], c["flag"]) for c in a["contradictions"]}
        assert ("AWS::EC2::Subnet", "specification-offers-but-call-unsupported") in flags
        assert ("AWS::EC2::Subnet", "tier-both-but-call-unsupported") in flags
        assert ("AWS::Hand::Written", "tier-both-and-specification-lacks-and-call-unsupported") in flags
        assert ("AWS::Extra::Thing", "specification-lacks-but-call-works") in flags
        assert ("AWS::Extra::Thing", "tier-commercial-only-but-call-works") in flags

    def test_backtest_on_tiny_record(self, world):
        b = go(world)["availability"]["backtest"]
        assert b["applicable"] and b["region"] == "us-gov-west-1"
        assert (b["present_in_specification"], b["present_and_worked"], b["present_but_unsupported"]) == (2, 1, ["AWS::EC2::Subnet"])
        assert (b["absent_from_specification"], b["absent_but_worked"]) == (2, 1)
        assert (b["unsupported"], b["unsupported_and_absent"], b["unsupported_with_tier_both"]) == (2, 1, 2)

    def test_unclassifiable_outcomes_left_out(self, world):
        _j(world["rec"], record({"aws_core__aws_rds_instance": "access-denied", "aws_core__aws_subnet": "throttled"}))
        b = go(world)["availability"]["backtest"]
        assert b["with_a_classifiable_outcome"] == 0

    def test_without_record(self, world):
        r = go(world, record_path=None)
        assert r["availability"]["backtest"]["applicable"] is False
        flags = {c["flag"] for c in r["availability"]["contradictions"]}
        assert "tier-both-but-specification-lacks-in-gov" in flags  # AWS::Hand::Written


class TestRecordPath:
    """--run-record is confined to the plugin checkout or the working directory: the path comes from the command line,
    and the verifier reads and hashes whatever it names (SonarCloud S8707 on _sha)."""

    ONE = {"aws_core__aws_rds_instance": "ok"}

    @staticmethod
    def _cwd(tmp_path, monkeypatch) -> Path:
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        return cwd

    def test_absolute_path_outside_both_refused(self, world, tmp_path, monkeypatch):
        self._cwd(tmp_path, monkeypatch)
        outside = _j(tmp_path / "elsewhere" / "rec.json", record(self.ONE))
        with pytest.raises(ValueError, match="plugin checkout or the working directory"):
            go(world, record_path=outside)

    def test_dotdot_escape_refused(self, world, tmp_path, monkeypatch):
        self._cwd(tmp_path, monkeypatch)
        _j(tmp_path / "escape.json", record(self.ONE))
        sneaky = world["plugin"] / "tools" / "validate" / "runs" / ".." / ".." / ".." / ".." / "escape.json"
        assert sneaky.is_file()  # the file exists; only where the path leads is wrong
        with pytest.raises(ValueError, match="plugin checkout or the working directory"):
            go(world, record_path=sneaky)

    def test_symlink_inside_plugin_refused(self, world, tmp_path, monkeypatch):
        self._cwd(tmp_path, monkeypatch)
        real = _j(tmp_path / "outside.json", record(self.ONE))
        link = world["plugin"] / "tools" / "validate" / "runs" / "link.json"
        link.symlink_to(real)
        with pytest.raises(ValueError, match="symbolic link"):
            go(world, record_path=link)

    def test_working_directory_accepted(self, world, tmp_path, monkeypatch):
        cwd = self._cwd(tmp_path, monkeypatch)
        _j(cwd / "rec.json", record(self.ONE))
        for p in (cwd / "rec.json", Path("rec.json")):  # absolute and relative to the working directory
            r = go(world, record_path=p)
            assert r["availability"]["backtest"]["applicable"] and r["inputs"]["run_record"]["entries"] == 1


class TestProperties:
    def test_read_only_and_writable_split(self, world):
        p = go(world)["properties"]
        rds = next(x for x in p["types"] if x["type"] == "AWS::RDS::DBInstance")
        assert rds["held_writable"] == ["Engine", "Tags"]
        assert rds["held_read_only"] == ["DBInstanceArn"]
        assert rds["missing_read_only"] == ["Endpoint"]
        assert rds["missing_writable"] == ["KmsKeyId"]
        assert rds["write_only_unreadable"] == ["MasterUserPassword"]  # cannot be read back, so not counted against us
        assert rds["named_but_not_in_specification"] == ["NotInSpec"]
        assert rds["stores_whole_configuration"] is True and rds["denominator"] == 5

    def test_headline_and_weighting(self, world):
        w = weighting.load(W)
        assert w.cfn("AWS::RDS::DBInstance") > 0
        p = go(world)["properties"]
        assert p["types_scored"] == 2 and p["pooled_held_pct"] == round(100 * (3 + 1) / 7, 1)
        assert p["weighted_held_pct"] is not None
        assert p["top_disagreements"][0]["type"] == "AWS::RDS::DBInstance"

    def test_types_without_manifest_listed_not_scored(self, world):
        p = go(world)["properties"]
        assert {x["type"] for x in p["types_without_manifest_entry"]} == {"AWS::Extra::Thing", "AWS::Hand::Written"}
        assert all(x["type"] not in ("AWS::Hand::Written",) for x in p["types"])

    def test_primary_region_preference(self, world):
        east_only = go(world, primary="us-east-1")["properties"]
        assert east_only["types_scored"] == 2
        with pytest.raises(cfn_reader.CfnReadError):
            go(world, primary="eu-west-9")


class TestIdentityAndTags:
    def test_identity(self, world):
        it = go(world)["identity_tags"]
        by = {x["type"]: x for x in it["identity_disagreements"]}
        assert by["AWS::RDS::DBInstance"]["verdict"] == "ours-arn-schema-identifier-is-not"
        assert "AWS::EC2::Subnet" not in by  # SubnetId agrees

    def test_tags(self, world):
        it = go(world)["identity_tags"]
        assert [x["type"] for x in it["tag_disagreements"]] == []  # rds taggable+collected, subnet not taggable+none
        m = world["plugin"] / "tap_plugin/aws_core/collectors/boto3_collector/aws_resource_manifest.json"
        d = json.loads(m.read_text())
        d["entries"][1]["tags"] = {"source": "service"}
        _j(m, d)
        it = go(world)["identity_tags"]
        assert it["tag_disagreements"][0]["verdict"] == "we-collect-tags-schema-says-not-taggable"
        dec = world["plugin"] / "tap_plugin/aws_core/ledger/decisions.json"
        _j(dec, {"tag_findings": {"AWS::EC2::Subnet": {"taggable": True, "citation": "botocore says so"}}})
        assert go(world)["identity_tags"]["tag_disagreements"] == []

    def test_needs_bundle(self, world):
        assert go(world, bundle_path=None)["identity_tags"]["applicable"] is False


class TestDeterminismAndDrift:
    def test_two_runs_identical(self, world):
        a, b = go(world), go(world)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        assert cfn_verifier.markdown(a, None) == cfn_verifier.markdown(b, None)

    def test_baseline_gate(self, world, tmp_path, capsys):
        out = tmp_path / "out"
        base = ["--plugin", str(world["plugin"]), "--bundle", str(world["bundle"]), "--run-record", str(world["rec"])]
        for s in world["specs"]:
            base += ["--spec", str(s)]
        assert cfn_verifier.main(base + ["--out", str(out)]) == 0
        assert (out / "report.json").exists() and (out / "report.md").exists()
        assert cfn_verifier.main(base + ["--baseline", str(out / "report.json"), "--fail-on-regression"]) == 0
        # AWS's specification loses a type: a changed input, and a new gap
        _j(world["specs"][2], spec_doc({"AWS::EC2::Subnet": SUBNET, "AWS::Extra::Thing": EXTRA}, version="271.0.0"))
        rc = cfn_verifier.main(base + ["--baseline", str(out / "report.json"), "--fail-on-regression", "--out", str(tmp_path / "out2")])
        assert rc == 1
        d = json.loads((tmp_path / "out2/report.json").read_text())["drift"]
        assert d["cause"] == "reference" and d["reference_inputs_changed"] == ["specifications"] and d["our_inputs_changed"] == []
        assert "absent:us-east-1:AWS::RDS::DBInstance" in d["new_gaps"]

    def test_baseline_of_other_schema_fails_closed(self, world, tmp_path):
        out = tmp_path / "out"
        base = ["--plugin", str(world["plugin"])] + [x for s in world["specs"] for x in ("--spec", str(s))]
        cfn_verifier.main(base + ["--out", str(out)])
        rep = json.loads((out / "report.json").read_text())
        rep["schema_version"] = 99
        _j(out / "old.json", rep)
        assert cfn_verifier.main(base + ["--baseline", str(out / "old.json"), "--fail-on-regression"]) == 1

    def test_fail_on_regression_needs_baseline(self, world):
        with pytest.raises(SystemExit) as e:
            cfn_verifier.main(["--spec", str(world["specs"][0]), "--fail-on-regression"])
        assert e.value.code == 2

    def test_empty_spec_is_an_argument_error(self, world, tmp_path):
        with pytest.raises(SystemExit) as e:
            cfn_verifier.main(["--plugin", str(world["plugin"]), "--spec", str(_j(tmp_path / "spec-empty.json", {"ResourceTypes": {}}))])
        assert e.value.code == 2


class TestFetchScript:
    def test_syntax(self):
        script = Path(__file__).resolve().parents[1] / "cfn_fetch.sh"
        text = script.read_text()
        assert text.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in text and "--fail" in text
        assert "python" not in text.lower()
