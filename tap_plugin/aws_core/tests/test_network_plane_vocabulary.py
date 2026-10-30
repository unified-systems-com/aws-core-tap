"""Network-plane design vocabulary: placement edges, Direct Connect, PrivateLink, DNS Firewall, Private CA.

Covers req-aws-core-placement (including -5, the subnet's zone edge), req-aws-core-direct-connect, req-aws-core-privatelink,
req-aws-core-dns-firewall and req-aws-core-private-ca (specs/spec-aws-core-v0.md): each type creates
through the service layer with only a name, keys on its AWS id, refuses a malformed id, and each edge
declares exactly the endpoints it names.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.models import (
    AcmPrivateCa,
    AvailabilityZone,
    DxConnection,
    DxGateway,
    DxVirtualInterface,
    Route53ResolverFirewallRuleGroup,
    Subnet,
    Vpc,
    VpcEndpoint,
    VpcEndpointService,
)

from tap_grid.caller_context import CallerContext
from tap_grid.constraints import WILDCARD, get_edge_type_constraints
from tap_grid.models import Edge, Entity
from tap_grid.services import WriteOperation, delete_node, write_batch


def t(slug: str) -> str:
    return f"aws_core__aws_{slug}"


# (model, natural-key field, a well-formed AWS id, a malformed one)
# Network-plane types the collector collects and whose models hold the collector's configuration envelope.
CONFIGURATION_REVIEWED = {
    "aws_core__aws_vpc_endpoint",
    "aws_core__aws_dx_connection",
    "aws_core__aws_dx_gateway",
    "aws_core__aws_dx_virtual_interface",
    "aws_core__aws_vpc_endpoint_service",
    "aws_core__aws_route53_resolver_firewall_rule_group",
    "aws_core__aws_transit_gateway",
    "aws_core__aws_transit_gateway_attachment",
    "aws_core__aws_acm_private_ca",
}

TYPES = [
    (DxConnection, "connection_id", "dxcon-fg5678gh", "dxlag-fg5678gh"),
    (DxGateway, "direct_connect_gateway_id", "5f294f92-bafb-4011-916d-9b0bb4a1b2c3", "dxgw-123"),
    (DxVirtualInterface, "virtual_interface_id", "dxvif-ffhhk74f", "dxcon-ffhhk74f"),
    (VpcEndpointService, "service_id", "vpce-svc-0123456789abcdef0", "vpce-0123456789abcdef0"),
    (VpcEndpoint, "vpc_endpoint_id", "vpce-0123456789abcdef0", "vpce-svc-0123456789abcdef0"),
    (Route53ResolverFirewallRuleGroup, "rule_group_id", "rslvr-frg-0123456789abcdef", "rslvr-frgassoc-1"),
    (
        AcmPrivateCa,
        "ca_arn",
        "arn:aws-us-gov:acm-pca:us-gov-west-1:123456789012:certificate-authority/12345678-1234-1234-1234-123456789012",
        "arn:aws:acm:us-east-1:123456789012:certificate/12345678-1234-1234-1234-123456789012",
    ),
]


def _node(type_slug: str, payload: dict[str, Any]):
    return write_batch(
        [WriteOperation(verb="create_node", type_slug=type_slug, payload=payload)], caller_context=CallerContext()
    ).results[0]


# Fields the fixtures set on existing aws_core models: required ones, and an ELB's lb_type so the
# endpoint-service case targets a Network Load Balancer (aws_elb covers classic, network and
# gateway load balancers; PrivateLink fronts only the last two).
_REQUIRED = {
    "aws_core__aws_security_group": {"group_id": "sg-0123456789abcdef0"},
    "aws_core__aws_internet_gateway": {"igw_id": "igw-0123456789abcdef0"},
    "aws_core__aws_elb": {"lb_type": "network"},
}


def _entity(type_slug: str, name: str) -> Entity:
    result = _node(type_slug, {"name": name, **_REQUIRED.get(type_slug, {})})
    assert result.success, result.errors
    return Entity.objects.get(id=result.entity_id)


def _edge(source: Entity, target: Entity, edge_type: str, properties: dict[str, Any] | None = None):
    payload = {"properties": properties} if properties else {}
    return write_batch(
        [
            WriteOperation(
                verb="create_edge",
                from_target=str(source.id),
                to_target=str(target.id),
                edge_type=edge_type,
                payload=payload,
            )
        ],
        caller_context=CallerContext(),
    ).results[0]


def _permits(allowed, entity_type: str) -> bool:
    return allowed is WILDCARD or entity_type in allowed


class TestDeclarations:
    @pytest.mark.parametrize(("model", "key", "_good", "_bad"), TYPES)
    def test_keyed_on_the_aws_id(self, model, key, _good, _bad) -> None:
        assert model.NATURAL_KEY == (key,)

    @pytest.mark.parametrize(("model", "_key", "_good", "_bad"), TYPES)
    def test_no_blob_and_no_duplicated_owner(self, model, _key, _good, _bad) -> None:
        # The owning account is the BELONGS_TO_ACCOUNT edge, never a second copy in a field.
        fields = {f.name for f in model._meta.get_fields()}
        # "No blob" holds while no source fills one. A type the boto3 collector collects always receives its
        # configuration envelope (batch.node_envelope), so its model must declare the field or the batch is
        # rejected at import. Which collected types may hold one is a decision, listed in
        # CONFIGURATION_REVIEWED: adding a manifest entry for another network-plane type fails here until
        # that type is added to it on purpose.
        if model.ENTITY_TYPE in CONFIGURATION_REVIEWED:
            assert "configuration" in fields
        else:
            assert "configuration" not in fields
            assert model.ENTITY_TYPE not in {e["entity_type"] for e in manifest_entries()}, (
                f"{model.ENTITY_TYPE} is collected, so its model must declare configuration: "
                "decide it and add the type to CONFIGURATION_REVIEWED"
            )
        assert "owner_account_id" not in fields
        assert set(model.FIELD_CRUD_SCHEMA) == set(model.FIELD_VALIDATION_SCHEMA)

    def test_vpc_contains_its_subnets_and_nothing_else(self) -> None:
        assert Vpc.CONTAINMENT_EDGES == ("PARTITIONED_INTO_SUBNET__aws_core",)
        # getattr: the CI floor core predates BaseModel.CONTAINMENT_EDGES, so Subnet inherits nothing there.
        assert getattr(Subnet, "CONTAINMENT_EDGES", ()) == ()

    def test_account_edge_covers_every_new_type(self) -> None:
        sources = get_edge_type_constraints("BELONGS_TO_ACCOUNT__aws_core").sources
        assert {m.ENTITY_TYPE for m, *_ in TYPES} <= sources
        # Region, AZ, the account itself, the Organizations tree and AWS-owned foundation models do not.
        for excluded in ("region", "az", "account", "organization", "organizational_unit", "bedrock_model"):
            assert t(excluded) not in sources

    def test_customer_device_target_is_open(self) -> None:
        constraints = get_edge_type_constraints("TERMINATES_AT_CUSTOMER_DEVICE__aws_core")
        assert constraints.sources == {t("dx_connection")}
        assert constraints.targets is WILDCARD

    def test_endpoint_service_routes_traffic(self) -> None:
        assert t("vpc_endpoint_service") in get_edge_type_constraints("ROUTES_TRAFFIC__aws_core").sources


@pytest.mark.django_db
class TestCreate:
    @pytest.mark.parametrize(("model", "key", "_good", "_bad"), TYPES)
    def test_designed_node_needs_only_a_name(self, model, key, _good, _bad) -> None:
        result = _node(model.ENTITY_TYPE, {"name": "highbar"})
        assert result.success, result.errors
        row = model.all_objects.get(entity_id=result.entity_id)
        assert getattr(row, key) == ""
        assert row.entity.dimensions == {"tap.cloud": "aws"}

    @pytest.mark.parametrize(("model", "key", "good", "_bad"), TYPES)
    def test_well_formed_id_is_accepted(self, model, key, good, _bad) -> None:
        result = _node(model.ENTITY_TYPE, {"name": "x", key: good})
        assert result.success, result.errors
        assert model.objects.get(**{key: good}).entity_id == result.entity_id

    @pytest.mark.parametrize(("model", "key", "_good", "bad"), TYPES)
    def test_malformed_id_is_refused(self, model, key, _good, bad) -> None:
        assert not _node(model.ENTITY_TYPE, {"name": "x", key: bad}).success

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

    def test_virtual_interface_fields(self) -> None:
        ok = _node(
            t("dx_virtual_interface"),
            {"name": "transit-vif", "virtual_interface_type": "transit", "vlan": 101, "customer_asn": 65001},
        )
        assert ok.success, ok.errors
        assert not _node(t("dx_virtual_interface"), {"name": "x", "virtual_interface_type": "hosted"}).success
        assert not _node(t("dx_virtual_interface"), {"name": "x", "vlan": 4095}).success

    def test_connection_bandwidth_and_hosted(self) -> None:
        ok = _node(t("dx_connection"), {"name": "c", "bandwidth": "10Gbps", "location": "EqDC2", "is_hosted": False})
        assert ok.success, ok.errors
        assert _node(t("dx_connection"), {"name": "c", "bandwidth": "500Mbps", "is_hosted": True}).success
        assert not _node(t("dx_connection"), {"name": "c", "bandwidth": "10 gigs"}).success

    @pytest.mark.parametrize("asn", [64511, 65535, 4294967295])
    def test_dx_gateway_asn_outside_aws_ranges_is_refused(self, asn: int) -> None:
        assert not _node(t("dx_gateway"), {"name": "g", "amazon_side_asn": asn}).success

    def test_dx_gateway_asn_in_range(self) -> None:
        assert _node(t("dx_gateway"), {"name": "g", "amazon_side_asn": 64512}).success

    def test_endpoint_type_is_aws_enum(self) -> None:
        assert _node(t("vpc_endpoint"), {"name": "e", "endpoint_type": "Interface"}).success
        assert not _node(t("vpc_endpoint"), {"name": "e", "endpoint_type": "interface"}).success

    def test_rule_group_domain_lists_are_name_lists(self) -> None:
        ok = _node(
            t("route53_resolver_firewall_rule_group"),
            {
                "name": "egress-dns",
                "rule_count": 2,
                "block_domain_lists": ["AWSManagedDomainsMalwareDomainList"],
                "allow_domain_lists": ["highbar-allowed"],
            },
        )
        assert ok.success, ok.errors
        assert not _node(
            t("route53_resolver_firewall_rule_group"), {"name": "x", "block_domain_lists": [{"id": "rslvr-fdl-1"}]}
        ).success

    def test_private_ca_enums(self) -> None:
        ok = _node(
            t("acm_private_ca"),
            {"name": "pki-root", "ca_type": "ROOT", "key_algorithm": "EC_secp384r1", "status": "ACTIVE"},
        )
        assert ok.success, ok.errors
        assert not _node(t("acm_private_ca"), {"name": "x", "ca_type": "INTERMEDIATE"}).success


@pytest.mark.django_db
class TestEdges:
    @pytest.mark.parametrize(
        ("edge_type", "source", "target"),
        [
            ("BELONGS_TO_ACCOUNT__aws_core", t("vpc"), t("account")),
            ("BELONGS_TO_ACCOUNT__aws_core", t("dx_connection"), t("account")),
            ("RESIDES_IN_VPC__aws_core", t("security_group"), t("vpc")),
            ("RESIDES_IN_VPC__aws_core", t("vpc_endpoint"), t("vpc")),
            ("PARTITIONED_INTO_SUBNET__aws_core", t("vpc"), t("subnet")),
            ("RESIDES_IN_SUBNET__aws_core", t("ecs_service"), t("subnet")),
            ("RESIDES_IN_SUBNET__aws_core", t("vpc_endpoint"), t("subnet")),
            ("ATTACHED_TO_VPC__aws_core", t("internet_gateway"), t("vpc")),
            ("RESIDES_IN_AZ__aws_core", t("subnet"), t("az")),
            ("CARRIED_ON_CONNECTION__aws_core", t("dx_virtual_interface"), t("dx_connection")),
            ("ATTACHED_TO_DX_GATEWAY__aws_core", t("dx_virtual_interface"), t("dx_gateway")),
            ("ATTACHES_DX_GATEWAY__aws_core", t("transit_gateway_attachment"), t("dx_gateway")),
            ("TERMINATES_AT_CUSTOMER_DEVICE__aws_core", t("dx_connection"), t("account")),  # open target
            ("CONSUMES_ENDPOINT_SERVICE__aws_core", t("vpc_endpoint"), t("vpc_endpoint_service")),
            ("ROUTES_TRAFFIC__aws_core", t("vpc_endpoint_service"), t("elb")),
            ("FILTERS_VPC_DNS__aws_core", t("route53_resolver_firewall_rule_group"), t("vpc")),
            ("ISSUED_BY_CA__aws_core", t("acm_private_ca"), t("acm_private_ca")),
            ("ISSUED_BY_CA__aws_core", t("acm_certificate"), t("acm_private_ca")),
        ],
    )
    def test_declared_endpoints_are_accepted(self, edge_type: str, source: str, target: str) -> None:
        result = _edge(_entity(source, "s"), _entity(target, "t"), edge_type)
        assert result.success, result.errors
        edge = Edge.objects.select_related("entity").get(entity_id=result.entity_id)
        assert edge.entity.dimensions == {"tap.cloud": "aws"}

    @pytest.mark.parametrize(
        ("edge_type", "source", "target"),
        [
            ("BELONGS_TO_ACCOUNT__aws_core", t("region"), t("account")),
            ("RESIDES_IN_VPC__aws_core", t("subnet"), t("vpc")),  # a subnet is PARTITIONED_INTO_SUBNET's
            ("RESIDES_IN_VPC__aws_core", t("ec2_instance"), t("vpc")),  # placed in a subnet instead
            ("PARTITIONED_INTO_SUBNET__aws_core", t("subnet"), t("vpc")),
            ("ATTACHED_TO_VPC__aws_core", t("nat_gateway"), t("vpc")),
            ("RESIDES_IN_AZ__aws_core", t("ec2_instance"), t("az")),  # reaches its zone through its subnet
            ("RESIDES_IN_AZ__aws_core", t("az"), t("subnet")),
            ("RESIDES_IN_AZ__aws_core", t("subnet"), t("region")),
            ("CARRIED_ON_CONNECTION__aws_core", t("dx_gateway"), t("dx_connection")),
            ("ATTACHES_DX_GATEWAY__aws_core", t("dx_virtual_interface"), t("dx_gateway")),
            ("CONSUMES_ENDPOINT_SERVICE__aws_core", t("vpc"), t("vpc_endpoint_service")),
            ("FILTERS_VPC_DNS__aws_core", t("route53_resolver_firewall_rule_group"), t("subnet")),
            ("ISSUED_BY_CA__aws_core", t("acm_private_ca"), t("acm_certificate")),
        ],
    )
    def test_other_pairs_fall_outside_the_declaration(self, edge_type: str, source: str, target: str) -> None:
        # The declaration, not the write path: tap_grid checks edges by permission union and aws_core
        # nodes mostly declare no node-side constraints, so such a write can succeed
        # (unified-systems-com/tap#794).
        constraints = get_edge_type_constraints(edge_type)
        assert constraints is not None
        assert not (_permits(constraints.sources, source) and _permits(constraints.targets, target))

    def test_dns_firewall_association_properties(self) -> None:
        group, vpc = _entity(t("route53_resolver_firewall_rule_group"), "g"), _entity(t("vpc"), "v")
        ok = _edge(group, vpc, "FILTERS_VPC_DNS__aws_core", {"priority": 101, "mutation_protection": True})
        assert ok.success, ok.errors
        assert not _edge(group, vpc, "FILTERS_VPC_DNS__aws_core", {"priority": 50}).success
        assert not _edge(group, vpc, "FILTERS_VPC_DNS__aws_core", {"action": "BLOCK"}).success

    @pytest.mark.skipif(
        "cascade" not in inspect.signature(delete_node).parameters,
        reason="this core predates contained cascade (req-grid-service-delete-cascade)",
    )
    def test_retiring_a_vpc_retires_its_subnets_only(self) -> None:
        vpc, subnet, sg = _entity(t("vpc"), "v"), _entity(t("subnet"), "s"), _entity(t("security_group"), "sg")
        assert _edge(vpc, subnet, "PARTITIONED_INTO_SUBNET__aws_core").success
        assert _edge(sg, vpc, "RESIDES_IN_VPC__aws_core").success
        result = delete_node(str(vpc.id), caller_context=CallerContext(), cascade="contained")
        assert result.success, result.errors
        assert not Subnet.objects.filter(entity_id=subnet.id).exists()
        assert Entity.objects.filter(id=sg.id, deleted_at__isnull=True).exists()

    @pytest.mark.skipif(
        "cascade" not in inspect.signature(delete_node).parameters,
        reason="this core predates contained cascade (req-grid-service-delete-cascade)",
    )
    def test_a_subnets_zone_outlives_the_subnet(self) -> None:
        # req-aws-core-placement-5: RESIDES_IN_AZ is a reference, so the zone stays live.
        vpc, subnet, zone = _entity(t("vpc"), "v"), _entity(t("subnet"), "s"), _entity(t("az"), "us-gov-east-1a")
        assert _edge(vpc, subnet, "PARTITIONED_INTO_SUBNET__aws_core").success
        assert _edge(subnet, zone, "RESIDES_IN_AZ__aws_core").success
        result = delete_node(str(vpc.id), caller_context=CallerContext(), cascade="contained")
        assert result.success, result.errors
        assert not Subnet.objects.filter(entity_id=subnet.id).exists()
        assert Entity.objects.filter(id=zone.id, deleted_at__isnull=True).exists()

    def test_zone_edge_is_not_containment(self) -> None:
        for model in (Subnet, AvailabilityZone, Vpc):
            assert "RESIDES_IN_AZ__aws_core" not in getattr(model, "CONTAINMENT_EDGES", ())
