"""The aws_core dimension seed: every dimension key aws_core writes has a declared Dimension node.

Core's dimension-map reshape (tap#708, #711) refers to dimensions by their node's id, and George
ruled on 2026-11-12 that nodes are never minted on the fly. So every key aws_core writes must be
seeded somewhere: ``aws.account`` and ``aws.region`` (stamped by the collector on every node and edge
it writes) here, and ``tap.computing.cloud`` (every model's and edge type's default) by computing_core,
which owns the cloud dimension and keeps the id of aws_core's former ``tap.cloud`` node (Q56).
``cloud`` was retired (Q55a): it duplicated the cloud dimension. It stays declared, so grids whose rows
still carry it resolve it, but nothing writes it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

SEED = Path(__file__).resolve().parent.parent / "grift" / "dimension.grift.json"
# aws_core's former tap.cloud node: computing_core now seeds it as tap.computing.cloud (Q56).
TAP_CLOUD_ID = "019dd143-3e8f-73e4-b0fa-e62ac923065d"
ACCOUNT_ID = "01a1d109-3ae5-77e3-857e-41aac951274e"
REGION_ID = "01a1d109-3ae5-77e3-857e-41abf1031159"
KEYS = {"cloud", "aws.account", "aws.region"}
# Declared but never written any more.
RETIRED = {"cloud"}
# Written by aws_core (its type defaults) but declared by computing_core, which owns them.
COMPUTING_KEYS = {"tap.computing.cloud"}


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


def test_the_cloud_node_is_computing_cores_now_and_the_renamed_keys_keep_their_ids() -> None:
    by_id = {n["entity"]["entity_id"]: n["node"]["name"] for n in _nodes(_seed())}
    assert TAP_CLOUD_ID not in by_id, "computing_core seeds that id as tap.computing.cloud (Q56)"
    assert by_id[ACCOUNT_ID] == "aws.account" and by_id[REGION_ID] == "aws.region"


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
    assert {"aws.account", "aws.region"} <= collector, "the scan stopped seeing the collector's stamp"
    written = (collector | _default_keys() | _seed_keys()) - CORE_KEYS
    assert written == (KEYS - RETIRED) | COMPUTING_KEYS


def test_no_description_carries_an_account_number() -> None:
    import re

    text = SEED.read_text(encoding="utf-8")
    assert not re.search(r"\b\d{12}\b", text), "the repo is public: no 12-digit account number in the seed"


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-account-dimension-8")
def test_re_seeding_over_v030_renames_the_keys_by_id() -> None:
    """A grid that imported v0.3.0 (aws_account, aws_region) takes v0.4.0: the new batch id is not skipped, and
    each node is renamed in place, keeping its id."""
    from tap_grid.grift import grift_import
    from tap_grid.models import Dimension

    old = copy.deepcopy(_seed())
    batch = old["batches"][0]
    batch["batch_entity"]["entity_id"] = "01a1d190-085f-7451-baf0-e090d1b05508"
    batch["batch_entity"]["name"] = batch["batch_node"]["name"] = "AWS dimensions v0.3.0"
    for node in batch["nodes"]:
        node["entity"]["name"] = node["node"]["name"] = node["node"]["name"].replace("aws.", "aws_")
    assert grift_import(old).success
    assert Dimension.objects.get(entity_id=ACCOUNT_ID).name == "aws_account"
    assert grift_import(_seed()).success
    assert Dimension.objects.get(entity_id=ACCOUNT_ID).name == "aws.account"
    assert Dimension.objects.get(entity_id=REGION_ID).name == "aws.region"


@pytest.mark.spec("req-aws-core-account-dimension-8")
def test_cloud_is_retired_declared_but_never_written() -> None:
    """Q55a: nothing stamps ``cloud``; the node stays declared and says it is retired."""
    assert "cloud" not in _collector_keys() | _default_keys()
    cloud = next(n for n in _nodes(_seed()) if n["node"]["name"] == "cloud")
    assert cloud["node"]["description"].startswith("Retired 2026-11-12; never stamped.")


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-account-dimension-8")
def test_the_migration_renames_aws_core_rows_only_and_is_idempotent() -> None:
    """The migration renames tap.cloud and aws_region and drops cloud and aws_account, only on aws_core's own node and
    edge rows; a row that already carries the new key keeps it; a second run changes nothing."""
    import importlib
    from types import SimpleNamespace

    from django.db import connection

    from tap_grid.models import Entity
    from tap_grid.write_guard import unguarded_write

    migration = importlib.import_module("tap_plugin.aws_core.migrations.0055_rename_aws_dimensions")
    with unguarded_write():
        ours = Entity.objects.create(
            entity_type="aws_core__aws_vpc",
            name="v",
            dimensions={"cloud": "aws", "tap.cloud": "aws", "aws_account": "acct-a", "aws_region": "us-east-1"},
        )
        theirs = Entity.objects.create(entity_type="anchore__image", name="i", dimensions={"cloud": "aws"})
        # An edge's spine row is entity_type "edge"; whose edge it is lives on tap_edge.edge_type.
        our_edge = Entity.objects.create(
            entity_type="edge", name="e1", dimensions={"cloud": "aws", "aws_region": "x", "aws.region": "kept"}
        )
        their_edge = Entity.objects.create(entity_type="edge", name="e2", dimensions={"cloud": "aws"})
    with connection.cursor() as cursor:
        for edge, edge_type in ((our_edge, "HOSTS_VPC__aws_core"), (their_edge, "SCANS__anchore")):
            cursor.execute(
                "INSERT INTO tap_edge (batch_id, flip_map, edge_type, properties, entity_id, from_entity_id, to_entity_id)"
                " VALUES (%s, '{}', %s, '{}', %s, %s, %s)",
                ["test", edge_type, edge.pk, ours.pk, theirs.pk],
            )
    for _ in range(2):
        migration.rename_dimensions(None, SimpleNamespace(connection=connection))
    for row in (ours, theirs, our_edge, their_edge):
        row.refresh_from_db()
    # aws_account is dropped, not carried into aws.account (Q60a): it named the observer, not the owner.
    assert ours.dimensions == {"tap.computing.cloud": "aws", "aws.region": "us-east-1"}
    assert our_edge.dimensions == {"aws.region": "kept"}, "an edge's existing new key is kept; the old one goes"
    assert theirs.dimensions == {"cloud": "aws"}, "another plugin's rows are not aws_core's to change"
    assert their_edge.dimensions == {"cloud": "aws"}


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-account-dimension-9")
def test_a_migrated_row_has_no_owner_until_re_collected_so_its_falsifier_fails_closed() -> None:
    """Q60a: an old aws_account value named the OBSERVER. A RAM-shared subnet seen by the receiving account carried
    that account; renamed into aws.account it would pass the receiver's scope check and reopen the false-deletion
    path. Dropped, the row has no aws.account, and the scope check refuses it until the owner is stamped."""
    import importlib
    from types import SimpleNamespace

    from django.db import connection
    from tap_plugin.aws_core.falsifiers import SubnetFalsifier, _dimensions_of

    from tap_grid.falsifiers import Candidate
    from tap_grid.models import Entity
    from tap_grid.write_guard import unguarded_write

    receiver = "111122223333"
    migration = importlib.import_module("tap_plugin.aws_core.migrations.0055_rename_aws_dimensions")
    with unguarded_write():
        shared = Entity.objects.create(
            entity_type="aws_core__aws_subnet",
            name="shared",
            dimensions={"tap.cloud": "aws", "aws_account": receiver, "aws_region": "us-east-1"},
        )
    migration.rename_dimensions(None, SimpleNamespace(connection=connection))
    shared.refresh_from_db()
    assert "aws.account" not in shared.dimensions and "aws_account" not in shared.dimensions

    row = SimpleNamespace(entity=shared)
    candidate = Candidate(
        entity_id=shared.id,
        entity_type="aws_core__aws_subnet",
        reason="dropped_from_observation",
        surface=0,
        relation="fixture",
        subject=None,
        edge_type=None,
        parent=None,
        interval_first=None,
    )
    verdict = SubnetFalsifier(session=None, account_id=receiver)._scope_check(
        candidate, receiver, _dimensions_of(row).get("aws.account") or None
    )
    assert verdict is not None and verdict.reason == "scope_unknown"
