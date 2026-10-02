"""Internal consistency of the region-scoped containment substrate (tap-plugin-aws-core#49).

Every source of truth that must agree with ``tap_plugin.aws_core.regional.REGIONAL_CHILDREN`` is
checked against it here, rather than trusted to have been kept in sync by hand: the ``.edge.json``
files, the manifest entries' ``containment`` blocks, ``AwsAccountRegion``'s edge declarations, and
the ``[falsifiers]`` manifest table (the trap named in ``regional.py``'s own docstring).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.models.aws_account_region import AwsAccountRegion
from tap_plugin.aws_core.regional import (
    CHILD_BY_TYPE,
    LANDING_ZONE_CHILDREN,
    NOT_YET_WIRED,
    PARENT_ENTITY_TYPE,
    REGIONAL_CHILDREN,
)

_PLUGIN_DIR = Path(__file__).resolve().parents[1]
_TOML = tomllib.loads((_PLUGIN_DIR / "tap-plugin.toml").read_text())


@pytest.mark.parametrize("child", REGIONAL_CHILDREN, ids=lambda c: c.entity_type)
class TestEveryRegionalChild:
    def test_edge_file_matches(self, child):
        edge = _TOML["edges"][child.edge_type]
        data = (_PLUGIN_DIR / edge).read_text()
        import json

        d = json.loads(data)
        assert d["slug"] == child.edge_type
        assert d["sources"] == [PARENT_ENTITY_TYPE]
        assert d["targets"] == [child.entity_type]

    def test_declared_on_the_parent_as_both_outbound_and_containment(self, child):
        assert child.edge_type in AwsAccountRegion.CONTAINMENT_EDGES
        outbound_edge_types = {e["type"] for rule in AwsAccountRegion.OUTBOUND_EDGES for e in rule["edges"]}
        assert child.edge_type in outbound_edge_types

    def test_falsifier_registered(self, child):
        """The whole reason REGIONAL_CHILDREN is trimmed to what it is (regional.py's docstring):
        a CONTAINMENT_EDGES target with no [falsifiers] row reds validate_plugin --strict."""
        assert child.entity_type in _TOML["falsifiers"], (
            f"{child.entity_type} is a containment target with no [falsifiers] row; "
            "validate_plugin --strict will fail on this"
        )

    def test_manifest_entry_declares_matching_containment(self, child):
        entries = {e["entity_type"]: e for e in manifest_entries()}
        entry = entries.get(child.entity_type)
        assert entry is not None, f"{child.entity_type} is in REGIONAL_CHILDREN but has no manifest entry"
        block = entry.get("containment")
        assert block is not None, f"{child.entity_type}'s manifest entry declares no containment block"
        assert block["edge_type"] == child.edge_type
        assert block["relation"] == child.relation
        assert entry["scope"] == "regional"
        assert "aws_op" in entry["source"], "containment requires an aws_op source (custom_fn is opaque to the engine)"


@pytest.mark.parametrize("child", LANDING_ZONE_CHILDREN, ids=lambda c: c.entity_type)
class TestEveryLandingZoneChild:
    """The landing-zone reader's footprint children (aws-core-tap#66) agree with the same sources of
    truth, except a manifest entry: a custom reader lists them, not the manifest engine."""

    def test_edge_file_matches(self, child):
        import json

        d = json.loads((_PLUGIN_DIR / _TOML["edges"][child.edge_type]).read_text())
        assert (d["slug"], d["sources"], d["targets"]) == (child.edge_type, [PARENT_ENTITY_TYPE], [child.entity_type])

    def test_declared_on_the_parent_as_both_outbound_and_containment(self, child):
        assert child.edge_type in AwsAccountRegion.CONTAINMENT_EDGES
        assert child.edge_type in {e["type"] for rule in AwsAccountRegion.OUTBOUND_EDGES for e in rule["edges"]}

    def test_falsifier_registered(self, child):
        assert child.entity_type in _TOML["falsifiers"]

    def test_not_a_manifest_entry(self, child):
        assert child.entity_type not in {e["entity_type"] for e in manifest_entries()}


def test_every_footprint_containment_edge_is_in_one_table():
    tables = [c.edge_type for c in REGIONAL_CHILDREN + LANDING_ZONE_CHILDREN]
    assert sorted(tables) == sorted(AwsAccountRegion.CONTAINMENT_EDGES)


def test_containment_edges_is_a_subset_of_outbound_edges():
    """The import-time invariant BaseModel.__init_subclass__ enforces; asserted directly so a
    future edit that breaks it fails here with a clear message, not a cryptic import error."""
    outbound = {e["type"] for rule in AwsAccountRegion.OUTBOUND_EDGES for e in rule["edges"]}
    assert set(AwsAccountRegion.CONTAINMENT_EDGES) <= outbound


def test_no_duplicate_edge_types():
    types = [c.edge_type for c in REGIONAL_CHILDREN]
    assert len(types) == len(set(types))


def test_child_by_type_is_complete():
    assert set(CHILD_BY_TYPE) == {c.entity_type for c in REGIONAL_CHILDREN}


def test_not_yet_wired_types_are_not_wired():
    """The worklist and the live table are disjoint — a type does not appear in both, which would
    say it is simultaneously done and not done."""
    wired = {c.entity_type for c in REGIONAL_CHILDREN}
    worklist = {t for t, _ in NOT_YET_WIRED}
    assert wired.isdisjoint(worklist)


def test_not_yet_wired_types_really_have_no_falsifier_yet():
    """A worklist entry that quietly gained a falsifier should move INTO REGIONAL_CHILDREN, not
    linger as 'not yet wired' — this would catch the table falling out of date the other way."""
    for entity_type, _ in NOT_YET_WIRED:
        assert entity_type not in _TOML.get("falsifiers", {}), (
            f"{entity_type} now has a falsifier; move it from NOT_YET_WIRED into REGIONAL_CHILDREN"
        )
