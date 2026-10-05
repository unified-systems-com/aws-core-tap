"""The collector names nodes and edges by natural key and mints no id (req-aws-collector-identity).

Runs the real collector pipeline against the canned AWS of the vertical-slice test, on a real grid:
a re-run keeps every id and adds no edge, rows written under the old ``uuid5`` ids are found
rather than duplicated, a tombstoned resource returns with a new id without wedging the batch
(aws-core-tap#14), an endpoint the batch does not carry resolves to the row on the grid, and a
node whose key has a hole fails the run instead of being minted afresh.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

import pytest
from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector, Boto3CollectorError
from tap_plugin.aws_core.collectors.boto3_collector.identity import NAMESPACE_AWS_COLLECTOR
from tap_plugin.aws_core.tests.grid_keys import edge_between, find_node_id, live_edges, node_id

from tap_cares.collectors.config import CollectorConfig

from .test_boto3_collector_slice import (
    _ACCOUNT,
    _CANNED,
    _DIST_ARN,
    _FN_ARN,
    _ROLE_ARN,
    _ZONE_ID,
    _stub_aws,  # noqa: F401 — the canned-AWS fixture every test here runs under
)

pytestmark = pytest.mark.usefixtures("_stub_aws")

LAMBDA = "aws_core__aws_lambda"
ROLE = "aws_core__aws_iam_role"
ZONE = "aws_core__aws_route53_zone"
DIST = "aws_core__aws_cloudfront_distribution"
FOOTPRINT = "aws_core__aws_account_region"
ASSUMES_ROLE = "ASSUMES_ROLE__aws_core"
ROUTES_TRAFFIC = "ROUTES_TRAFFIC__aws_core"
REGION = "us-east-1"


def _run() -> Boto3Collector:
    collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
    collector.run()
    return collector


def _nodes() -> dict[uuid.UUID, str]:
    """Every live aws_core node: id -> type."""
    from tap_grid.models import Entity

    return dict(
        Entity.objects.filter(entity_type__startswith="aws_core__", deleted_at__isnull=True).values_list(
            "id", "entity_type"
        )
    )


def _edges() -> dict[uuid.UUID, tuple[str, uuid.UUID, uuid.UUID]]:
    """Every live aws_core edge: id -> (type, from, to)."""
    from tap_grid.models import Edge

    return {
        e.entity_id: (e.edge_type, e.from_entity_id, e.to_entity_id)
        for e in Edge.objects.filter(edge_type__endswith="__aws_core", entity__deleted_at__isnull=True)
    }


def _legacy_id(name: str) -> uuid.UUID:
    """An id as the collector derived it before natural-key refs (the rows already on real grids)."""
    return uuid.uuid5(NAMESPACE_AWS_COLLECTOR, name)


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-identity-1", "req-aws-collector-identity-4")
def test_a_rerun_keeps_every_id_and_adds_no_edge() -> None:
    """req-aws-collector-identity-4: the second run finds every row the first wrote."""
    first = _run()
    assert first.results["error"] == []
    nodes, edges = _nodes(), _edges()
    assert nodes and edges

    second = _run()
    assert second.results["error"] == []
    assert _nodes() == nodes
    assert _edges() == edges
    groups = Counter(edges.values())
    assert [g for g, n in groups.items() if n > 1] == []


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-identity-1")
def test_rows_written_under_uuid5_ids_are_found_not_duplicated() -> None:
    """The cut-over: a grid collected before this change holds uuid5 ids. Found by natural key and by
    edge identity, they keep their ids; nothing is added beside them."""
    from tap_grid.grift import grift_import

    fn_id = _legacy_id(f"{LAMBDA}:{_FN_ARN}")
    role_id = _legacy_id(f"{ROLE}:{_ROLE_ARN}")
    edge_id = _legacy_id(f"edge:{ASSUMES_ROLE}:{_FN_ARN}->{_ROLE_ARN}")
    legacy = {
        "metadata": {"grift_version": "0"},
        "_reserved": {},
        "batches": [
            {
                "batch_entity": {
                    "entity_id": str(uuid.uuid7()),
                    "entity_type": "batch",
                    "name": "pre-switch",
                    "dimensions": {},
                },
                "batch_node": {"source": "test", "name": "pre-switch", "description": "uuid5-era rows"},
                "nodes": [
                    {
                        "entity": {
                            "entity_id": str(fn_id),
                            "entity_type": LAMBDA,
                            "name": "sam-handler",
                            "dimensions": {},
                        },
                        "node": {"name": "sam-handler", "function_arn": _FN_ARN},
                    },
                    {
                        "entity": {
                            "entity_id": str(role_id),
                            "entity_type": ROLE,
                            "name": "sam-exec",
                            "dimensions": {},
                        },
                        "node": {"name": "sam-exec", "role_arn": _ROLE_ARN},
                    },
                ],
                "edges": [
                    {
                        "entity": {"entity_id": str(edge_id), "entity_type": "edge", "name": "e", "dimensions": {}},
                        "edge": {
                            "from_entity_id": str(fn_id),
                            "to_entity_id": str(role_id),
                            "edge_type": ASSUMES_ROLE,
                            "properties": {},
                        },
                    }
                ],
            }
        ],
    }
    imported = grift_import(legacy)
    assert imported.success, [(i.code, i.message) for i in imported.errors]

    collector = _run()
    assert collector.results["error"] == []
    assert node_id(LAMBDA, _FN_ARN) == fn_id
    assert node_id(ROLE, _ROLE_ARN) == role_id
    assert [e.entity_id for e in live_edges(ASSUMES_ROLE, fn_id, role_id)] == [edge_id]


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-identity-6")
def test_a_tombstoned_resource_returns_with_a_new_id_and_the_batch_does_not_wedge() -> None:
    """req-aws-collector-identity-6, the aws-core-tap#14 done-test: a resource deleted on the grid and
    seen again is created afresh under the same natural key; the tombstone is left alone, and the
    edges that named it follow the new row."""
    from tap_grid.models import Entity
    from tap_grid.services import delete_node

    assert _run().results["error"] == []
    old_role = node_id(ROLE, _ROLE_ARN)
    fn = node_id(LAMBDA, _FN_ARN)
    assert delete_node(old_role).success
    assert find_node_id(ROLE, _ROLE_ARN) is None

    again = _run()
    assert again.results["error"] == []
    new_role = node_id(ROLE, _ROLE_ARN)
    assert new_role != old_role
    assert Entity.objects.get(pk=old_role).deleted_at is not None
    assert node_id(LAMBDA, _FN_ARN) == fn
    edge = edge_between(ASSUMES_ROLE, LAMBDA, _FN_ARN, ROLE, _ROLE_ARN)
    assert edge.to_entity_id == new_role
    assert live_edges(ASSUMES_ROLE, fn, old_role) == []


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-identity-7")
def test_a_tombstoned_parent_is_the_new_id_in_its_completeness_surface() -> None:
    """req-aws-collector-identity-7: a surface's subject is the grid id its parent resolved to this
    run, so after the footprint returns under a new id, the surface names the new one and candidate
    derivation can resolve it."""
    from tap_grid.candidates import _resolve_parent
    from tap_grid.services import delete_node

    footprint_key = {"account_id": _ACCOUNT, "region_code": REGION}
    first = _run()
    old = node_id(FOOTPRINT, footprint_key)
    vpcs = [s for s in first._surfaces if s["relation"] == "account_region.vpcs"]
    assert [s["subject"] for s in vpcs] == [str(old)]

    assert delete_node(old).success
    again = _run()
    assert again.results["error"] == []
    new = node_id(FOOTPRINT, footprint_key)
    assert new != old
    (surface,) = [s for s in again._surfaces if s["relation"] == "account_region.vpcs"]
    assert surface["subject"] == str(new)
    assert _resolve_parent(surface) == (new, "HOSTS_VPC__aws_core")
    # The canned AWS here has no account to collect, so the account-scoped listings' parent is not in
    # the batch: their subject stays the account's ref, its source locator, and derives nothing.
    account_subjects = {s["subject"] for s in again._surfaces if s["relation"].startswith("account.")}
    assert account_subjects == {f"aws_core__aws_account:{_ACCOUNT}"}
    assert find_node_id("aws_core__aws_account", _ACCOUNT) is None


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-identity-3")
def test_an_endpoint_the_batch_does_not_carry_resolves_to_the_row_on_the_grid(monkeypatch) -> None:
    """req-aws-collector-identity-3: a later run that cannot list the role still names it by key, and
    core finds the row the earlier run wrote — the edge is the same edge, not a skip."""
    assert _run().results["error"] == []
    role, fn = node_id(ROLE, _ROLE_ARN), node_id(LAMBDA, _FN_ARN)
    (edge,) = live_edges(ASSUMES_ROLE, fn, role)

    monkeypatch.setitem(_CANNED, "list_roles", {"Roles": []})
    again = _run()
    assert again.results["error"] == []
    assert [e.entity_id for e in live_edges(ASSUMES_ROLE, fn, role)] == [edge.entity_id]
    skipped = [w for w in again.results["warn"] if w["message_code"] == "GRIFT_EDGES_SKIPPED"]
    assert not any(s["edge_type"] == ASSUMES_ROLE for w in skipped for s in w["message_data"]["skips"])


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-edges-3")
def test_an_endpoint_that_names_nothing_is_skipped_and_recorded_never_minted(monkeypatch) -> None:
    """A key naming no live node is never created: core skips the edge and the run record names it."""
    monkeypatch.setitem(_CANNED, "list_roles", {"Roles": []})
    collector = _run()
    assert collector.results["error"] == []
    assert find_node_id(ROLE, _ROLE_ARN) is None
    (warning,) = [w for w in collector.results["warn"] if w["message_code"] == "GRIFT_EDGES_SKIPPED"]
    assert ASSUMES_ROLE in {s["edge_type"] for s in warning["message_data"]["skips"]}


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-identity-5")
def test_a_node_with_a_hole_in_its_key_fails_the_run_and_writes_nothing(monkeypatch) -> None:
    """req-aws-collector-identity-5: core would find nothing on a null key part and create the node
    again on every run, so the run fails loudly before anything is submitted."""
    real = collector_mod.footprint_envelopes

    def _thin(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        envelopes = real(*args, **kwargs)
        envelopes[0]["node"]["region_code"] = None
        return envelopes

    monkeypatch.setattr(collector_mod, "footprint_envelopes", _thin)
    submitted: list[Any] = []
    monkeypatch.setattr(Boto3Collector, "submit_grift", lambda self, doc, **kw: submitted.append(doc))
    collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
    with pytest.raises(Boto3CollectorError, match="region_code"):
        collector.run()
    assert [e["message_code"] for e in collector.results["error"]] == ["IDENTITY_INCOMPLETE"]
    assert submitted == []
    assert _nodes() == {}


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-identity-3")
def test_an_edge_type_with_no_identity_keeps_its_uuid5_id_across_runs() -> None:
    """ROUTES_TRAFFIC declares no identity (aws-core-tap#64): it keeps the explicit uuid5 id it had, so
    a re-run replaces it in place instead of adding a ref-addressed copy each time."""
    assert _run().results["error"] == []
    expected = _legacy_id(f"edge:{ROUTES_TRAFFIC}:{_ZONE_ID}->{_DIST_ARN}")
    assert edge_between(ROUTES_TRAFFIC, ZONE, _ZONE_ID, DIST, _DIST_ARN).entity_id == expected
    assert _run().results["error"] == []
    assert edge_between(ROUTES_TRAFFIC, ZONE, _ZONE_ID, DIST, _DIST_ARN).entity_id == expected


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-identity-3")
def test_an_undeclared_edge_ended_on_the_grid_is_left_out_not_a_wedge() -> None:
    """Deleting the zone ends its ROUTES_TRAFFIC edge. Re-sending that edge's fixed uuid5 id would fail
    the whole batch (entity_tombstoned), so the run leaves it out and says so; the zone itself returns
    under a new id. The edge comes back once the type declares an identity (aws-core-tap#64)."""
    from tap_grid.models import Entity
    from tap_grid.services import delete_node

    assert _run().results["error"] == []
    old_zone = node_id(ZONE, _ZONE_ID)
    edge_id = _legacy_id(f"edge:{ROUTES_TRAFFIC}:{_ZONE_ID}->{_DIST_ARN}")
    assert delete_node(old_zone).success
    assert Entity.objects.get(pk=edge_id).deleted_at is not None

    again = _run()
    assert again.results["error"] == []
    assert node_id(ZONE, _ZONE_ID) != old_zone
    (notice,) = [w for w in again.results["warn"] if w["message_code"] == "UNDECLARED_EDGE_RETIRED"]
    assert str(edge_id) in notice["message"]
    assert live_edges(ROUTES_TRAFFIC, node_id(ZONE, _ZONE_ID), node_id(DIST, _DIST_ARN)) == []
