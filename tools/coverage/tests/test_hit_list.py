"""Tests for tools/coverage. The committed hit list is regenerated and compared, so a change to the manifest,
a model's containment, the falsifier table, the ledger or the weighting that is not followed by a
regeneration fails here; the other tests check that the counts mean what they say."""

import json
import shutil
from pathlib import Path

import hit_list

ROOT = Path(__file__).resolve().parents[3]  # the aws-core-tap checkout
PKG = Path("tap_plugin") / "aws_core"


def _service(report: dict, name: str) -> dict:
    return next(s for s in report["services"] if s["service"] == name)


def _row(report: dict, service: str, type_name: str) -> dict:
    return next(r for r in _service(report, service)["rows"] if r["type_name"] == type_name)


def test_committed_hit_list_is_current() -> None:
    expected = json.dumps(hit_list.build(ROOT, hit_list.DEFAULT_WEIGHTS), indent=1, sort_keys=True) + "\n"
    assert (ROOT / "tools/coverage/hit-list.json").read_text() == expected, "run: python3 -I tools/coverage/hit_list.py"


def test_build_is_deterministic() -> None:
    a = hit_list.build(ROOT, hit_list.DEFAULT_WEIGHTS)
    assert a == hit_list.build(ROOT, hit_list.DEFAULT_WEIGHTS)


def test_ranking_follows_the_stated_formula() -> None:
    r = hit_list.build(ROOT, hit_list.DEFAULT_WEIGHTS)
    weights = [s["weight"] for s in r["services"]]
    assert weights == sorted(weights, reverse=True) and all(w > 0 for w in weights)
    for s in r["services"]:
        assert s["weight"] == sum(t["weight"] for t in s["rows"])
        assert s["reconcilable"] <= s["with_falsifier"] <= s["collected"] <= s["types"]


def test_known_facts() -> None:
    r = hit_list.build(ROOT, hit_list.DEFAULT_WEIGHTS)
    role = _row(r, "IAM", "AWS::IAM::Role")
    assert role["reconcilable"] and role["has_falsifier"] and role["has_completeness_surface"] and role["config_supported"]
    vpc = _row(r, "EC2", "AWS::EC2::VPC")
    assert vpc["cascade_parent_of"] == ["aws_core__aws_subnet"]


def test_losing_a_falsifier_shows_as_a_gap(tmp_path: Path) -> None:
    for sub in ("models", "edges", "ledger", "collectors/boto3_collector"):
        shutil.copytree(ROOT / PKG / sub, tmp_path / PKG / sub, ignore=shutil.ignore_patterns("__pycache__", "*.py") if sub.startswith("collectors") else None)
    toml = (ROOT / PKG / "tap-plugin.toml").read_text()
    line = 'aws_core__aws_iam_role = "tap_plugin.aws_core.falsifiers.IamRoleFalsifier"\n'
    assert line in toml
    (tmp_path / PKG / "tap-plugin.toml").write_text(toml.replace(line, ""))
    r = hit_list.build(tmp_path, hit_list.DEFAULT_WEIGHTS)
    role = _row(r, "IAM", "AWS::IAM::Role")
    assert role["has_falsifier"] is False and role["falsifier_gap"] is True and role["reconcilable"] is False
    base = hit_list.build(ROOT, hit_list.DEFAULT_WEIGHTS)
    assert _service(r, "IAM")["reconcilable"] == _service(base, "IAM")["reconcilable"] - 1


def test_config_types_file_names_its_source() -> None:
    d = json.loads((ROOT / "tools/coverage/config-resource-types.json").read_text())
    assert d["botocore_version"] and "AWS::IAM::Role" in d["types"] and d["types"] == sorted(d["types"])
