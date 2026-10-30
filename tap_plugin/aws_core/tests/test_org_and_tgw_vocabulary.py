"""AWS Organizations, IAM Identity Center and Transit Gateway design vocabulary.

Covers req-aws-core-organizations, req-aws-core-identity-center and req-aws-core-transit-gateway
(specs/spec-aws-core-v0.md): each type creates through the service layer with only a name, keys on
its AWS id, refuses a malformed id, and each edge accepts exactly the endpoints it declares.
"""

from __future__ import annotations

from typing import Any

import pytest
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.models import (
    AwsIdentityCenterInstance,
    AwsOrganization,
    AwsOrganizationalUnit,
    AwsServiceControlPolicy,
    TransitGateway,
    TransitGatewayAttachment,
)

from tap_grid.caller_context import CallerContext
from tap_grid.constraints import WILDCARD, get_edge_type_constraints
from tap_grid.models import Edge, Entity
from tap_grid.services import WriteOperation, write_batch

ORG = "aws_core__aws_organization"
OU = "aws_core__aws_organizational_unit"
SCP = "aws_core__aws_service_control_policy"
IDC = "aws_core__aws_identity_center_instance"
TGW = "aws_core__aws_transit_gateway"
ATT = "aws_core__aws_transit_gateway_attachment"
ACCOUNT = "aws_core__aws_account"
VPC = "aws_core__aws_vpc"

# (model, natural-key field, a well-formed AWS id, a malformed one)
TYPES = [
    (AwsOrganization, "organization_id", "o-a1b2c3d4e5", "org-123"),
    (AwsOrganizationalUnit, "ou_id", "ou-ab12-cd34ef56", "ou-AB12"),
    (
        AwsServiceControlPolicy,
        "policy_arn",
        "arn:aws:organizations::123456789012:policy/o-a1b2c3d4e5/service_control_policy/p-examplepolicyid111",
        "arn:aws:organizations::123456789012:policy/p-1",
    ),
    (
        AwsIdentityCenterInstance,
        "instance_arn",
        "arn:aws-us-gov:sso:::instance/ssoins-1234567890abcdef",
        "arn:aws:sso:us-east-1::instance/ssoins-1",
    ),
    (TransitGateway, "transit_gateway_id", "tgw-0123456789abcdef0", "tgw-XYZ"),
    (TransitGatewayAttachment, "attachment_id", "tgw-attach-0123456789abcdef0", "tgw-0123456789abcdef0"),
]


def _node(type_slug: str, payload: dict[str, Any]):
    return write_batch(
        [WriteOperation(verb="create_node", type_slug=type_slug, payload=payload)], caller_context=CallerContext()
    ).results[0]


def _entity(type_slug: str, name: str) -> Entity:
    result = _node(type_slug, {"name": name})
    assert result.success, result.errors
    return Entity.objects.get(id=result.entity_id)


def _permits(allowed, entity_type: str) -> bool:
    return allowed is WILDCARD or entity_type in allowed


def _edge(source: Entity, target: Entity, edge_type: str):
    return write_batch(
        [
            WriteOperation(
                verb="create_edge",
                from_target=str(source.id),
                to_target=str(target.id),
                edge_type=edge_type,
                payload={},
            )
        ],
        caller_context=CallerContext(),
    ).results[0]


class TestDeclarations:
    @pytest.mark.parametrize(("model", "key", "_good", "_bad"), TYPES)
    def test_keyed_on_the_aws_id(self, model, key, _good, _bad) -> None:
        assert model.NATURAL_KEY == (key,)

    @pytest.mark.parametrize(("model", "_key", "_good", "_bad"), TYPES)
    def test_design_vocabulary_has_no_configuration_blob(self, model, _key, _good, _bad) -> None:
        # No blob while no source fills one. A type the boto3 collector collects through a manifest entry always
        # receives its configuration envelope (batch.node_envelope), so its model must declare the field;
        # the Organizations tree is read by its own reader and stays blob-free.
        collected = model.ENTITY_TYPE in {e["entity_type"] for e in manifest_entries()}
        assert ("configuration" in model.FIELD_CRUD_SCHEMA) is collected
        assert any(f.name == "configuration" for f in model._meta.get_fields()) is collected

    @pytest.mark.parametrize(("model", "_key", "_good", "_bad"), TYPES)
    def test_schemas_agree(self, model, _key, _good, _bad) -> None:
        assert set(model.FIELD_CRUD_SCHEMA) == set(model.FIELD_VALIDATION_SCHEMA)
        assert model.DEFAULT_DIMENSIONS == {"tap.cloud": "aws"}


@pytest.mark.django_db
class TestCreate:
    @pytest.mark.parametrize(("model", "key", "_good", "_bad"), TYPES)
    def test_designed_node_needs_only_a_name(self, model, key, _good, _bad) -> None:
        result = _node(model.ENTITY_TYPE, {"name": "highbar"})
        assert result.success, result.errors
        row = model.all_objects.get(entity_id=result.entity_id)
        assert getattr(row, key) == ""
        assert row.entity.name == "highbar"
        assert row.entity.dimensions == {"tap.cloud": "aws"}

    @pytest.mark.parametrize(("model", "key", "good", "_bad"), TYPES)
    def test_well_formed_id_is_accepted_and_names_the_node(self, model, key, good, _bad) -> None:
        result = _node(model.ENTITY_TYPE, {"name": "x", key: good})
        assert result.success, result.errors
        # A plain lookup, not BaseModel.find_existing: the plugin's CI core pin predates that helper.
        assert model.objects.get(**{key: good}).entity_id == result.entity_id

    @pytest.mark.parametrize(("model", "key", "_good", "bad"), TYPES)
    def test_malformed_id_is_refused(self, model, key, _good, bad) -> None:
        assert not _node(model.ENTITY_TYPE, {"name": "x", key: bad}).success

    @pytest.mark.parametrize(("model", "_key", "_good", "_bad"), TYPES)
    def test_name_is_required(self, model, _key, _good, _bad) -> None:
        assert not _node(model.ENTITY_TYPE, {}).success

    @pytest.mark.parametrize(("model", "_key", "_good", "_bad"), TYPES)
    def test_two_id_less_designs_stay_distinct(self, model, _key, _good, _bad) -> None:
        results = write_batch(
            [
                WriteOperation(verb="create_node", type_slug=model.ENTITY_TYPE, payload={"name": "a"}),
                WriteOperation(verb="create_node", type_slug=model.ENTITY_TYPE, payload={"name": "b"}),
            ],
            caller_context=CallerContext(),
        ).results
        assert all(r.success for r in results)
        assert results[0].entity_id != results[1].entity_id

    def test_organization_partition_and_feature_set_are_closed(self) -> None:
        assert _node(ORG, {"name": "o", "partition": "aws-us-gov", "feature_set": "ALL"}).success
        assert _node(ORG, {"name": "o", "partition": "aws-cn"}).success
        assert not _node(ORG, {"name": "o", "partition": "gov"}).success
        assert not _node(ORG, {"name": "o", "feature_set": "all"}).success

    def test_transit_gateway_options_and_asn(self) -> None:
        ok = _node(
            TGW,
            {
                "name": "hub",
                "owner_account_id": "123456789012",
                "region": "us-gov-west-1",
                "amazon_side_asn": 4200000000,
                "auto_accept_shared_attachments": False,
                "default_route_table_association": False,
                "default_route_table_propagation": False,
            },
        )
        assert ok.success, ok.errors
        row = TransitGateway.all_objects.get(entity_id=ok.entity_id)
        assert row.amazon_side_asn == 4200000000
        assert row.default_route_table_association is False
        unobserved = TransitGateway.all_objects.get(entity_id=_node(TGW, {"name": "u"}).entity_id)
        assert unobserved.auto_accept_shared_attachments is None
        assert not _node(TGW, {"name": "x", "amazon_side_asn": 0}).success

    @pytest.mark.parametrize("asn", [64512, 65534, 4200000000, 4294967294])
    def test_asn_in_aws_private_ranges_is_accepted(self, asn: int) -> None:
        assert _node(TGW, {"name": "hub", "amazon_side_asn": asn}).success

    @pytest.mark.parametrize("asn", [64511, 65535, 4199999999, 4294967295, 1])
    def test_asn_outside_aws_private_ranges_is_refused(self, asn: int) -> None:
        assert not _node(TGW, {"name": "hub", "amazon_side_asn": asn}).success

    def test_asn_explicit_null_is_accepted(self) -> None:
        result = _node(TGW, {"name": "hub", "amazon_side_asn": None})
        assert result.success, result.errors
        assert TransitGateway.all_objects.get(entity_id=result.entity_id).amazon_side_asn is None

    def test_aws_managed_scp_arn_is_accepted(self) -> None:
        arn = "arn:aws:organizations::aws:policy/service_control_policy/p-FullAWSAccess"
        assert _node(SCP, {"name": "FullAWSAccess", "policy_arn": arn, "policy_id": "p-FullAWSAccess"}).success

    def test_designed_scp_is_not_asserted_customer_managed(self) -> None:
        unobserved = _node(SCP, {"name": "deny-leave-org"})
        assert AwsServiceControlPolicy.all_objects.get(entity_id=unobserved.entity_id).aws_managed is None
        managed = _node(SCP, {"name": "FullAWSAccess", "policy_id": "p-FullAWSAccess", "aws_managed": True})
        assert AwsServiceControlPolicy.all_objects.get(entity_id=managed.entity_id).aws_managed is True

    def test_attachment_resource_type_is_aws_enum(self) -> None:
        assert _node(ATT, {"name": "a", "resource_type": "tgw-peering"}).success
        assert not _node(ATT, {"name": "a", "resource_type": "transit"}).success

    def test_tags_are_flat_strings(self) -> None:
        assert _node(OU, {"name": "prod", "tags": {"Owner": "platform"}}).success
        assert not _node(OU, {"name": "prod", "tags": {"Owner": {"nested": "x"}}}).success


@pytest.mark.django_db
class TestEdges:
    @pytest.mark.parametrize(
        ("edge_type", "source", "target"),
        [
            ("NESTED_UNDER_PARENT__aws_core", OU, ORG),
            ("NESTED_UNDER_PARENT__aws_core", OU, OU),
            ("NESTED_UNDER_PARENT__aws_core", ACCOUNT, OU),
            ("NESTED_UNDER_PARENT__aws_core", ACCOUNT, ORG),
            ("ATTACHED_TO_TARGET__aws_core", SCP, ORG),
            ("ATTACHED_TO_TARGET__aws_core", SCP, OU),
            ("ATTACHED_TO_TARGET__aws_core", SCP, ACCOUNT),
            ("ATTACHED_TO_TRANSIT_GATEWAY__aws_core", ATT, TGW),
            ("ATTACHES_VPC__aws_core", ATT, VPC),
            ("PEERS_WITH_TRANSIT_GATEWAY__aws_core", ATT, TGW),
        ],
    )
    def test_declared_endpoints_are_accepted(self, edge_type: str, source: str, target: str) -> None:
        result = _edge(_entity(source, "s"), _entity(target, "t"), edge_type)
        assert result.success, result.errors
        edge = Edge.objects.select_related("entity").get(entity_id=result.entity_id)
        assert edge.edge_type == edge_type
        assert edge.entity.dimensions == {"tap.cloud": "aws"}

    @pytest.mark.parametrize(
        ("edge_type", "source", "target"),
        [
            ("NESTED_UNDER_PARENT__aws_core", ORG, OU),  # the root has no parent
            ("NESTED_UNDER_PARENT__aws_core", OU, ACCOUNT),  # an account is a leaf
            ("ATTACHED_TO_TARGET__aws_core", SCP, VPC),  # SCPs attach to the tree only
            ("ATTACHED_TO_TARGET__aws_core", OU, ORG),  # only a policy attaches
            ("ATTACHED_TO_TRANSIT_GATEWAY__aws_core", VPC, TGW),  # VPCs attach through an attachment
            ("ATTACHES_VPC__aws_core", ATT, TGW),
            ("PEERS_WITH_TRANSIT_GATEWAY__aws_core", TGW, TGW),
            ("TRUSTS_IDENTITY_SOURCE__aws_core", ORG, ACCOUNT),  # only an Identity Center instance trusts
        ],
    )
    def test_other_pairs_fall_outside_the_declaration(self, edge_type: str, source: str, target: str) -> None:
        # The declaration, not the write path: tap_grid checks edges by permission union, and an
        # aws_core node declares no OUTBOUND_EDGES / INBOUND_EDGES, so the node side permits any
        # edge and the write succeeds. That is true of every aws_core edge type, not these alone.
        constraints = get_edge_type_constraints(edge_type)
        assert constraints is not None
        assert not (_permits(constraints.sources, source) and _permits(constraints.targets, target))

    def test_identity_source_target_is_open(self) -> None:
        constraints = get_edge_type_constraints("TRUSTS_IDENTITY_SOURCE__aws_core")
        assert constraints.sources == {IDC}
        assert constraints.targets is WILDCARD
        # The external provider is another plugin's node (an Okta application, say), which aws_core
        # cannot name. Any type is accepted; an aws_account stands in because this plugin's CI
        # installs no identity plugin.
        result = _edge(_entity(IDC, "highbar"), _entity(ACCOUNT, "stand-in"), "TRUSTS_IDENTITY_SOURCE__aws_core")
        assert result.success, result.errors
