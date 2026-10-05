"""GRIFT batch-assembly unit tests for the boto3 collector (no DB).

Covers req-aws-collector-grift-batch: one batch per run, provenance
recorded, no deletion content, GRIFT document root shape.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tap_plugin.aws_core.collectors.boto3_collector.batch import (
    COLLECTION_FORMAT,
    address_batch,
    assemble_batch,
    node_envelope,
    resolve_subject,
)
from tap_plugin.aws_core.collectors.boto3_collector.edges import edge_envelope
from tap_plugin.aws_core.collectors.boto3_collector.identity import (
    IdentityError,
    node_ref,
    undeclared_edge_id,
)
from tap_plugin.aws_core.collectors.boto3_collector.projection import ProjectedNode

FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
FIXED_BATCH_ID = "00000000-0000-7000-8000-000000000000"


def _projected(entity_type, key):
    return ProjectedNode(
        entity_type=entity_type,
        natural_key=key,
        name=key,
        fields={"name": key, "arn": key},
        configuration={key: 1, "_source": {"op": "Op", "why": "w"}},
        raw_item={key: 1},
    )


class TestNodeEnvelope:
    def test_shape_and_payload(self):
        env = node_envelope(
            _projected("aws_core__aws_lambda", "arn:fn"),
            {"region": "us-east-1"},
            persist_configuration=True,
        )
        assert env["entity"] == {
            "ref": "aws_core__aws_lambda:arn:fn",
            "entity_type": "aws_core__aws_lambda",
            "name": "arn:fn",
            "dimensions": {"region": "us-east-1"},
        }
        # node payload is typed fields + tags + the configuration envelope
        assert env["node"]["name"] == "arn:fn"
        assert env["node"]["arn"] == "arn:fn"
        assert env["node"]["tags"] == {}
        assert env["node"]["configuration"]["_source"] == {"op": "Op", "why": "w"}

    def test_flag_off_emits_empty_configuration_and_same_typed_fields(self):
        node = _projected("aws_core__aws_lambda", "arn:fn")
        on = node_envelope(node, {}, persist_configuration=True)
        off = node_envelope(node, {}, persist_configuration=False)
        assert off["node"]["configuration"] == {}
        assert {k: v for k, v in off["node"].items() if k != "configuration"} == {
            k: v for k, v in on["node"].items() if k != "configuration"
        }
        # Only the emit is cut: in-run consumers (hydrate-gap warnings, edge
        # derivation) still see the full envelope on the ProjectedNode.
        assert node.configuration["_source"] == {"op": "Op", "why": "w"}

    def test_flag_has_no_default(self):
        with pytest.raises(TypeError):
            node_envelope(_projected("aws_core__aws_lambda", "arn:fn"), {})  # type: ignore[call-arg]


class TestAssembleBatch:
    def _doc(self, nodes, edges):
        return assemble_batch(
            source="tap_plugin.aws_core.collectors.boto3_collector",
            manifest_version="0",
            account_id="123456789012",
            regions=["us-east-1", "us-west-2"],
            node_envelopes=nodes,
            edge_envelopes=edges,
            now=FIXED_NOW,
            batch_entity_id=FIXED_BATCH_ID,
        )

    def test_document_root_shape(self):
        doc = self._doc([], [])
        assert doc["metadata"] == {"grift_version": "0"}
        assert doc["_reserved"] == {}
        assert len(doc["batches"]) == 1  # one batch per run

    def test_batch_entity_and_provenance(self):
        n1 = node_envelope(_projected("aws_core__aws_lambda", "a"), {}, persist_configuration=True)
        n2 = node_envelope(_projected("aws_core__aws_lambda", "b"), {}, persist_configuration=True)
        n3 = node_envelope(_projected("aws_core__aws_iam_role", "r"), {}, persist_configuration=True)
        edge = {"entity": {"entity_type": "edge"}, "edge": {}}
        batch = self._doc([n1, n2, n3], [edge])["batches"][0]

        assert batch["batch_entity"] == {
            "entity_id": FIXED_BATCH_ID,
            "entity_type": "batch",
            "name": "AWS collection 2026-01-02T03:04:05Z",
            "dimensions": {},
        }
        bn = batch["batch_node"]
        assert bn["source"] == "tap_plugin.aws_core.collectors.boto3_collector"
        assert bn["description_json"]["format"] == COLLECTION_FORMAT
        data = bn["description_json"]["data"]
        assert data["manifest_version"] == "0"
        assert data["account_id"] == "123456789012"
        assert data["regions"] == ["us-east-1", "us-west-2"]
        assert data["counts"] == {
            "nodes": 3,
            "edges": 1,
            "by_entity_type": {"aws_core__aws_iam_role": 1, "aws_core__aws_lambda": 2},
        }

    def test_nodes_and_edges_pass_through(self):
        n = node_envelope(_projected("aws_core__aws_s3_bucket", "bkt"), {}, persist_configuration=True)
        edge = {"entity": {"entity_type": "edge"}, "edge": {"edge_type": "X"}}
        batch = self._doc([n], [edge])["batches"][0]
        assert batch["nodes"] == [n]
        assert batch["edges"] == [edge]

    def test_no_deletion_or_tombstone_content(self):
        env = node_envelope(_projected("aws_core__aws_lambda", "a"), {}, persist_configuration=True)
        batch = self._doc([env], [])["batches"][0]
        # Assembler injects no deleted_at / tombstone / implied-absence keys.
        assert "deleted_at" not in batch["batch_entity"]
        assert all("deleted_at" not in n["entity"] for n in batch["nodes"])

    def test_account_id_may_be_none(self):
        doc = assemble_batch(
            source="s",
            manifest_version="0",
            account_id=None,
            regions=[],
            node_envelopes=[],
            edge_envelopes=[],
            now=FIXED_NOW,
            batch_entity_id=FIXED_BATCH_ID,
        )
        assert doc["batches"][0]["batch_node"]["description_json"]["data"]["account_id"] is None

    def test_batch_id_minted_when_not_overridden(self):
        doc = assemble_batch(
            source="s",
            manifest_version="0",
            account_id=None,
            regions=[],
            node_envelopes=[],
            edge_envelopes=[],
            now=FIXED_NOW,
        )
        minted = doc["batches"][0]["batch_entity"]["entity_id"]
        assert minted and minted != FIXED_BATCH_ID  # fresh uuid7 per run


LAMBDA = "aws_core__aws_lambda"
ROLE = "aws_core__aws_iam_role"
FOOTPRINT = "aws_core__aws_account_region"
ZONE = "aws_core__aws_route53_zone"
DIST = "aws_core__aws_cloudfront_distribution"


def _node(entity_type, ref_key, **fields):
    return {
        "entity": {"ref": node_ref(entity_type, ref_key), "entity_type": entity_type, "name": ref_key, "dimensions": {}},
        "node": fields,
    }


def _edge(edge_type, from_type, from_key, to_type, to_key):
    return edge_envelope(
        edge_type, from_ref=node_ref(from_type, from_key), to_ref=node_ref(to_type, to_key), dimensions={}
    )


@pytest.mark.spec("req-aws-collector-identity-3", "req-aws-collector-identity-5")
class TestAddressBatch:
    """req-aws-collector-identity: what the batch sends is named by identity, and only completely."""

    def test_a_node_with_a_hole_in_its_key_fails_rather_than_mints(self):
        """req-aws-collector-identity-5: core finds nothing on a null key part, so it would create the
        node again on every run; the collector refuses to send it."""
        with pytest.raises(IdentityError, match="function_arn"):
            address_batch([_node(LAMBDA, "arn:fn", function_arn=None)], [])
        with pytest.raises(IdentityError, match="function_arn"):
            address_batch([_node(LAMBDA, "arn:fn", function_arn="")], [])
        with pytest.raises(IdentityError, match="region_code"):
            address_batch([_node(FOOTPRINT, "1:r", account_id="1")], [])

    def test_endpoints_in_the_batch_are_refs_and_the_rest_are_natural_keys(self):
        """req-aws-collector-identity-3: a node the batch carries is named by ref; any other by its
        type and declared natural key, which core resolves against the live grid and never mints."""
        out = address_batch(
            [_node(LAMBDA, "arn:fn", function_arn="arn:fn")],
            [_edge("ASSUMES_ROLE__aws_core", LAMBDA, "arn:fn", ROLE, "arn:role")],
        )
        (edge,) = out.edges
        assert edge["entity"]["ref"] == f"edge:ASSUMES_ROLE__aws_core:{LAMBDA}:arn:fn->{ROLE}:arn:role"
        assert "entity_id" not in edge["entity"]
        assert edge["edge"]["from_ref"] == node_ref(LAMBDA, "arn:fn")
        assert edge["edge"]["to_key"] == {"entity_type": ROLE, "key": {"role_arn": "arn:role"}}
        assert "to_ref" not in edge["edge"] and "from_key" not in edge["edge"]
        assert out.key_endpoints == 1

    def test_a_composite_key_node_outside_the_batch_cannot_be_named(self):
        """A composite key is joined into its ref string and cannot be split back honestly."""
        with pytest.raises(IdentityError, match="keyed on"):
            address_batch(
                [_node(LAMBDA, "arn:fn", function_arn="arn:fn")],
                [_edge("HOSTS_LAMBDA__aws_core", FOOTPRINT, "1:us-east-1", LAMBDA, "arn:fn")],
            )

    def test_one_node_per_identity_and_edges_follow_the_kept_one(self):
        """Two refs describing one source object fail a batch in core (duplicate_entity_id): the
        repeat is left out, its ref aliased, and an edge naming either is one edge."""
        out = address_batch(
            [
                _node(LAMBDA, "arn:fn", function_arn="arn:fn"),
                _node(LAMBDA, "arn:fn-alias", function_arn="arn:fn"),
                _node(ROLE, "arn:role", role_arn="arn:role"),
            ],
            [
                _edge("ASSUMES_ROLE__aws_core", LAMBDA, "arn:fn", ROLE, "arn:role"),
                _edge("ASSUMES_ROLE__aws_core", LAMBDA, "arn:fn-alias", ROLE, "arn:role"),
            ],
        )
        assert [n["entity"]["ref"] for n in out.nodes] == [node_ref(LAMBDA, "arn:fn"), node_ref(ROLE, "arn:role")]
        assert out.aliases == {node_ref(LAMBDA, "arn:fn-alias"): node_ref(LAMBDA, "arn:fn")}
        assert [code for code, _ in out.notices] == ["DUPLICATE_IDENTITY"]
        assert len(out.edges) == 1
        assert out.edges[0]["edge"]["from_ref"] == node_ref(LAMBDA, "arn:fn")

    def test_an_edge_type_with_no_identity_keeps_its_explicit_id(self):
        """ROUTES_TRAFFIC declares no identity (aws-core-tap#64); core would create a ref-addressed
        edge of it afresh every run, so it keeps the uuid5 id its existing rows carry."""
        out = address_batch(
            [_node(ZONE, "Z1", hosted_zone_id="Z1")],
            [_edge("ROUTES_TRAFFIC__aws_core", ZONE, "Z1", DIST, "arn:dist")],
        )
        (edge,) = out.edges
        assert "ref" not in edge["entity"]
        assert edge["entity"]["entity_id"] == str(undeclared_edge_id("ROUTES_TRAFFIC__aws_core", "Z1", "arn:dist"))
        assert edge["edge"]["from_ref"] == node_ref(ZONE, "Z1")
        assert edge["edge"]["to_key"] == {"entity_type": DIST, "key": {"distribution_arn": "arn:dist"}}
        assert out.undeclared_edges == 1

    def test_the_input_is_not_mutated(self):
        edge = _edge("ASSUMES_ROLE__aws_core", LAMBDA, "arn:fn", ROLE, "arn:role")
        before = {"entity": dict(edge["entity"]), "edge": dict(edge["edge"])}
        address_batch([_node(LAMBDA, "arn:fn", function_arn="arn:fn")], [edge])
        assert edge == before


@pytest.mark.spec("req-aws-collector-identity-7")
class TestResolveSubject:
    """req-aws-collector-identity-7: a completeness subject is the grid id its parent resolved to."""

    def test_a_carried_parent_becomes_its_resolved_id_and_an_alias_follows_the_kept_ref(self):
        out = address_batch(
            [_node(LAMBDA, "arn:fn", function_arn="arn:fn"), _node(LAMBDA, "arn:fn2", function_arn="arn:fn")], []
        )
        resolved = {node_ref(LAMBDA, "arn:fn"): "0190-id"}
        assert resolve_subject(node_ref(LAMBDA, "arn:fn"), out, resolved) == "0190-id"
        assert resolve_subject(node_ref(LAMBDA, "arn:fn2"), out, resolved) == "0190-id"

    def test_a_parent_the_batch_did_not_carry_keeps_its_ref_as_the_locator(self):
        out = address_batch([], [])
        assert resolve_subject(node_ref(ROLE, "arn:r"), out, {}) == node_ref(ROLE, "arn:r")
