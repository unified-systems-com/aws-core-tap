"""The aws_core dimension seed: every dimension key aws_core writes has a declared Dimension node.

Core's dimension-map reshape (tap#708, #711) refers to dimensions by their node's id, and George
ruled on 2026-11-12 that nodes are never minted on the fly. So every key in use must be seeded:
``tap.cloud`` (the model and edge default) and ``aws_account`` and ``aws_region`` (stamped by the
collector on every node it writes). ``cloud`` was retired on 2026-11-12 (George, aws-build Q55a): it
duplicated ``tap.cloud``. It stays declared, so grids whose rows still carry it resolve it, but nothing
writes it.
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
# Declared but never written any more.
RETIRED = {"cloud"}


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
    """Every string key the collector writes into a dimensions map, by AST. A *dimensions target is
    a name or attribute ending in ``dimensions``. Seen: a dict literal assigned to one (plain or
    annotated); a constant subscript assigned on one (``dims["k"] = v``); ``.update`` on one, with a
    dict literal or keywords; and any dict literal returned by a function named ``dimensions``, sync
    or async. A key built some other way (computed, or passed through a helper) is not seen; the
    canary in the test below catches the stamp itself being rewritten."""
    import ast

    def is_dims(node: ast.AST) -> bool:
        name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""
        return name.endswith("dimensions")

    def literal_keys(node: ast.AST | None) -> set[str]:
        if isinstance(node, ast.Dict):
            return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        return set()

    keys: set[str] = set()
    for path in (PLUGIN / "collectors").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if is_dims(target):
                        keys |= literal_keys(node.value)
                    if isinstance(target, ast.Subscript) and is_dims(target.value):
                        if isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str):
                            keys.add(target.slice.value)
            elif isinstance(node, ast.AnnAssign) and is_dims(node.target):
                keys |= literal_keys(node.value)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "update":
                if is_dims(node.func.value):
                    for arg in node.args:
                        keys |= literal_keys(arg)
                    keys |= {kw.arg for kw in node.keywords if kw.arg}
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "dimensions":
                for inner in ast.walk(node):
                    keys |= literal_keys(inner)
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
    assert {"aws_account", "aws_region"} <= collector, "the scan stopped seeing the collector's stamp"
    written = (collector | _default_keys() | _seed_keys()) - CORE_KEYS
    assert written == KEYS - RETIRED


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


@pytest.mark.spec("req-aws-core-account-dimension-8")
def test_cloud_is_retired_declared_but_never_written() -> None:
    """Q55a: the collector no longer stamps ``cloud``; the node stays declared and says so."""
    assert "cloud" not in _collector_keys() | _default_keys()
    cloud = next(n for n in _nodes(_seed()) if n["node"]["name"] == "cloud")
    assert cloud["node"]["description"].startswith("Retired 2026-11-12; never stamped.")


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-account-dimension-8")
def test_re_seeding_over_v020_updates_the_retired_node() -> None:
    """A grid that imported v0.2.0 takes v0.3.0: the new batch id is not skipped, and the cloud node's
    description updates by id."""
    from tap_grid.grift import grift_import
    from tap_grid.models import Dimension

    old = copy.deepcopy(_seed())
    batch = old["batches"][0]
    batch["batch_entity"]["entity_id"] = "01a1d109-3ae5-77e3-857e-41a8da8c041c"
    batch["batch_entity"]["name"] = batch["batch_node"]["name"] = "AWS dimensions v0.2.0"
    cloud = next(n for n in batch["nodes"] if n["node"]["name"] == "cloud")
    cloud["node"]["description"] = "The cloud provider (v0.2.0 text)."
    assert grift_import(old).success
    assert grift_import(_seed()).success
    assert Dimension.objects.get(name="cloud").description.startswith("Retired 2026-11-12")


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-account-dimension-8")
def test_the_migration_drops_cloud_from_aws_core_rows_only_and_is_idempotent() -> None:
    """0054 removes only the cloud key, only from aws_core's own node and edge rows, and a second run changes
    nothing."""
    import importlib
    from types import SimpleNamespace

    from django.db import connection

    from tap_grid.models import Entity
    from tap_grid.write_guard import unguarded_write

    migration = importlib.import_module("tap_plugin.aws_core.migrations.0054_retire_cloud_dimension")
    with unguarded_write():
        ours = Entity.objects.create(
            entity_type="aws_core__aws_vpc",
            name="v",
            dimensions={"cloud": "aws", "tap.cloud": "aws", "aws_region": "us-east-1"},
        )
        theirs = Entity.objects.create(entity_type="anchore__image", name="i", dimensions={"cloud": "aws"})
        # An edge's spine row is entity_type "edge"; whose edge it is lives on tap_edge.edge_type.
        our_edge = Entity.objects.create(entity_type="edge", name="e1", dimensions={"cloud": "aws", "aws_region": "x"})
        their_edge = Entity.objects.create(entity_type="edge", name="e2", dimensions={"cloud": "aws"})
    with connection.cursor() as cursor:
        for edge, edge_type in ((our_edge, "HOSTS_VPC__aws_core"), (their_edge, "SCANS__anchore")):
            cursor.execute(
                "INSERT INTO tap_edge (batch_id, flip_map, edge_type, properties, entity_id, from_entity_id, to_entity_id)"
                " VALUES (%s, '{}', %s, '{}', %s, %s, %s)",
                ["test", edge_type, edge.pk, ours.pk, theirs.pk],
            )
    for _ in range(2):
        migration.drop_cloud(None, SimpleNamespace(connection=connection))
    for row in (ours, theirs, our_edge, their_edge):
        row.refresh_from_db()
    assert ours.dimensions == {"tap.cloud": "aws", "aws_region": "us-east-1"}
    assert our_edge.dimensions == {"aws_region": "x"}, "aws_core's edges carried the stamp too"
    assert theirs.dimensions == {"cloud": "aws"}, "another plugin's rows are not aws_core's to change"
    assert their_edge.dimensions == {"cloud": "aws"}
