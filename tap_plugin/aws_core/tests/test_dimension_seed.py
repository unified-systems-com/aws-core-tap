"""The aws_core dimension seed: every dimension key aws_core writes has a declared Dimension node.

Core's dimension-map reshape (tap#708, #711) refers to dimensions by their node's id, and George
ruled on 2026-11-12 that nodes are never minted on the fly. So every key in use must be seeded:
``tap.cloud`` (the model and edge default) and ``cloud``, ``aws_account`` and ``aws_region`` (stamped
by the collector on every node it writes).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

SEED = Path(__file__).resolve().parent.parent / "grift" / "dimension.grift.json"
TAP_CLOUD_ID = "019dd143-3e8f-73e4-b0fa-e62ac923065d"
KEYS = {"tap.cloud", "cloud", "aws_account", "aws_region"}


def _seed() -> dict[str, Any]:
    return json.loads(SEED.read_text(encoding="utf-8"))


def _nodes(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for batch in document["batches"] for node in batch["nodes"]]


@pytest.mark.spec("req-aws-core-account-dimension-7")
def test_the_seed_declares_every_key_aws_core_writes() -> None:
    nodes = _nodes(_seed())
    assert {n["entity"]["entity_type"] for n in nodes} == {"dimension"}
    names = [n["node"]["name"] for n in nodes]
    assert sorted(names) == sorted(KEYS), "one node per key, named exactly as the key is written"
    assert all(n["entity"]["name"] == n["node"]["name"] for n in nodes)
    assert all(n["node"]["description"].strip() for n in nodes)


def test_tap_cloud_keeps_its_id_and_is_named_by_its_key() -> None:
    by_id = {n["entity"]["entity_id"]: n for n in _nodes(_seed())}
    assert by_id[TAP_CLOUD_ID]["node"]["name"] == "tap.cloud"


# Keys core declares itself (its own seeds): aws_core's GRIFT seeds carry them, but they are not
# aws_core's vocabulary to declare.
CORE_KEYS = {"tap.meta", "tap.graph"}
PLUGIN = Path(__file__).resolve().parent.parent


def _collector_keys() -> set[str]:
    """Every string key of a dict literal the collector builds as dimensions: assigned to a name
    ending in ``dimensions``, or returned by a function named ``dimensions``."""
    import ast

    keys: set[str] = set()

    def literal_keys(node: ast.AST | None) -> set[str]:
        if isinstance(node, ast.Dict):
            return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        return set()

    for path in (PLUGIN / "collectors").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id.endswith("dimensions") for t in node.targets
            ):
                keys |= literal_keys(node.value)
            if isinstance(node, ast.FunctionDef) and node.name == "dimensions":
                for ret in ast.walk(node):
                    if isinstance(ret, ast.Return):
                        keys |= literal_keys(ret.value)
    return keys


def _default_keys() -> set[str]:
    """Keys of every model's DEFAULT_DIMENSIONS and every edge file's default_dimensions."""
    import re

    keys: set[str] = set()
    for path in (PLUGIN / "models").glob("*.py"):
        for block in re.findall(r"DEFAULT_DIMENSIONS[^=]*=\s*(\{[^}]*\})", path.read_text(encoding="utf-8")):
            keys |= set(json.loads(block))
    for path in (PLUGIN / "edges").glob("*.edge.json"):
        keys |= set(json.loads(path.read_text(encoding="utf-8")).get("default_dimensions", {}))
    return keys


def _seed_keys() -> set[str]:
    keys: set[str] = set()
    for path in (PLUGIN / "grift").glob("*.grift.json"):
        for batch in json.loads(path.read_text(encoding="utf-8"))["batches"]:
            keys |= set(batch["batch_entity"].get("dimensions", {}))
            for item in batch.get("nodes", []) + batch.get("edges", []):
                keys |= set(item["entity"].get("dimensions", {}))
    return keys


@pytest.mark.spec("req-aws-core-account-dimension-7")
def test_every_key_aws_core_writes_is_declared_and_nothing_else() -> None:
    """Derived from the sources, both ways: a key written but not declared, or declared but no longer
    written, fails here."""
    collector = _collector_keys()
    assert {"cloud", "aws_account", "aws_region"} <= collector, "the scan stopped seeing the collector's stamp"
    written = (collector | _default_keys() | _seed_keys()) - CORE_KEYS
    assert written == KEYS


def test_no_description_carries_an_account_number() -> None:
    import re

    text = SEED.read_text(encoding="utf-8")
    assert not re.search(r"\b\d{12}\b", text), "the repo is public: no 12-digit account number in the seed"


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-account-dimension-7")
def test_re_seeding_over_v010_renames_the_node_and_adds_the_rest() -> None:
    """An existing grid holds the v0.1.0 batch (node named 'tap.cloud: aws'). Re-seeding must land:
    the new batch id is not the old one, so it is not skipped, and its node upserts by id."""
    from tap_grid.grift import grift_import
    from tap_grid.models import Dimension

    old = copy.deepcopy(_seed())
    batch = old["batches"][0]
    batch["batch_entity"]["entity_id"] = "019dd143-3e8f-73e4-b0fa-e629e288cd8f"
    batch["batch_entity"]["name"] = batch["batch_node"]["name"] = "AWS Cloud dimension v0.1.0"
    tap_cloud = next(n for n in batch["nodes"] if n["entity"]["entity_id"] == TAP_CLOUD_ID)
    tap_cloud["entity"]["name"] = tap_cloud["node"]["name"] = "tap.cloud: aws"
    batch["nodes"] = [tap_cloud]
    first = grift_import(old)
    assert first.success, [(i.code, i.message) for i in first.errors]
    assert Dimension.objects.get(entity_id=TAP_CLOUD_ID).name == "tap.cloud: aws"

    second = grift_import(_seed())
    assert second.success, [(i.code, i.message) for i in second.errors]
    assert Dimension.objects.get(entity_id=TAP_CLOUD_ID).name == "tap.cloud"
    assert set(Dimension.objects.filter(name__in=KEYS).values_list("name", flat=True)) == KEYS
    assert Dimension.objects.filter(name="tap.cloud: aws").count() == 0
