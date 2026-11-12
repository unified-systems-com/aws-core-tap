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


def test_the_collector_keys_match_what_the_collector_stamps() -> None:
    """The seed names the collector's keys exactly, so a rename on either side fails here."""
    collector = (Path(__file__).resolve().parent.parent / "collectors" / "boto3_collector" / "collector.py").read_text(
        encoding="utf-8"
    )
    for key in ("cloud", "aws_account", "aws_region"):
        assert f'"{key}":' in collector, f"collector no longer stamps {key!r}; update the seed"


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
