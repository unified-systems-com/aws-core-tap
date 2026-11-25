"""Network Access Analyzer findings and Reachability Analyzer paths as compound edges (aws-core-tap#212, #248;
req-aws-collector-network-analyzer, req-grid-edge-compound).

The readers against botocore's own ec2 model (``Stubber``), so every request and canned answer is shape-checked; the
items through the manifest's own projection and edge rules; the declarations against core's one parser and boot
check; and the retire rule against the real delete walk on grid rows. No AWS call is made. The ARNs use AWS's
documentation account.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import botocore.session
import pytest
from botocore.stub import Stubber
from tap_plugin.aws_core.collectors.boto3_collector import network_insights as ni
from tap_plugin.aws_core.collectors.boto3_collector.authority import COMPLETE, EDGE_READS, PARTIAL, anchor_reads
from tap_plugin.aws_core.collectors.boto3_collector.customfns import build_custom_fn_registry
from tap_plugin.aws_core.collectors.boto3_collector.edges import emit_edges
from tap_plugin.aws_core.collectors.boto3_collector.identity import node_ref
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
from tap_plugin.aws_core.collectors.boto3_collector.source import CustomFnRegistry, UndescribedError, iter_source
from tap_plugin.aws_core.collectors.boto3_collector.transforms import build_transform_registry

REGION = "us-east-1"
ACCOUNT = "111122223333"
SCOPE_ANALYSIS_ARN = f"arn:aws:ec2:{REGION}:{ACCOUNT}:network-insights-access-scope-analysis/nisa-0a1b2c3d4e5f60718"
ANALYSIS_ARN = f"arn:aws:ec2:{REGION}:{ACCOUNT}:network-insights-analysis/nia-0a1b2c3d4e5f60718"
ALB_ARN = f"arn:aws:elasticloadbalancing:{REGION}:{ACCOUNT}:loadbalancer/app/web/50dc6c495c0c9188"
STARTED = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
ENDED = datetime(2026, 11, 20, 10, 4, tzinfo=UTC)
IGW, RTB, ACL, SG, ENI, SUBNET, INSTANCE = (
    "igw-0a1b2c3d",
    "rtb-0a1b2c3d",
    "acl-0a1b2c3d",
    "sg-0a1b2c3d",
    "eni-0a1b2c3d",
    "subnet-0a1b2c3d",
    "i-0a1b2c3d4e5f60718",
)
EDGES_DIR = Path(__file__).resolve().parent.parent / "edges"


def components(*ids: str, numbered: bool = True) -> list[dict[str, Any]]:
    """Path components in the given order, each naming its resource by id (an ARN for an ``arn:`` value)."""
    out = []
    for n, ident in enumerate(ids, start=1):
        component = {"Arn": ident} if ident.startswith("arn:") else {"Id": ident}
        out.append({**({"SequenceNumber": n} if numbered else {}), "Component": component})
    return out


def scope_analysis(**over: Any) -> dict[str, Any]:
    return {
        "NetworkInsightsAccessScopeAnalysisId": "nisa-0a1b2c3d4e5f60718",
        "NetworkInsightsAccessScopeAnalysisArn": SCOPE_ANALYSIS_ARN,
        "NetworkInsightsAccessScopeId": "nis-0a1b2c3d4e5f60718",
        "Status": "succeeded",
        "StartDate": STARTED,
        "EndDate": ENDED,
        "FindingsFound": "true",
        "AnalyzedEniCount": 4,
        **over,
    }


def finding(finding_id: str, path: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "NetworkInsightsAccessScopeAnalysisId": "nisa-0a1b2c3d4e5f60718",
        "NetworkInsightsAccessScopeId": "nis-0a1b2c3d4e5f60718",
        "FindingId": finding_id,
        "FindingComponents": path,
    }


def reachability(**over: Any) -> dict[str, Any]:
    return {
        "NetworkInsightsAnalysisId": "nia-0a1b2c3d4e5f60718",
        "NetworkInsightsAnalysisArn": ANALYSIS_ARN,
        "NetworkInsightsPathId": "nip-0a1b2c3d4e5f60718",
        "StartDate": STARTED,
        "Status": "succeeded",
        "NetworkPathFound": True,
        "ForwardPathComponents": components(INSTANCE, ENI, SG, ACL, RTB, IGW),
        **over,
    }


class _Ec2:
    """One stubbed ec2 client, handed to a reader as its client factory."""

    def __init__(self) -> None:
        self.client = botocore.session.get_session().create_client(
            "ec2", region_name=REGION, aws_access_key_id="testing", aws_secret_access_key="testing"
        )
        self.stub = Stubber(self.client)

    def client_for(self, service: str) -> Any:
        assert service == "ec2", service
        return self.client

    def __enter__(self) -> _Ec2:
        self.stub.activate()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stub.assert_no_pending_responses()
        self.stub.deactivate()


def _entry(entity_type: str) -> dict[str, Any]:
    return next(e for e in manifest_entries() if e["entity_type"] == entity_type)


def _derived(item: dict[str, Any]) -> dict[str, Any]:
    """``item`` with the finding entry's ``derive`` keys added, as the engine adds them after the custom_fn."""
    entry = {**_entry(ni.ACCESS_SCOPE_FINDING), "source": {"custom_fn": "canned"}}
    registry = CustomFnRegistry()
    registry.register("canned", lambda _ctx, client_for: iter([item]))
    scope = {"partition": "aws", "region": REGION, "account": ACCOUNT}
    [out] = iter_source(entry, client_for=lambda _s: None, custom_fns=registry, account_id=ACCOUNT, scope=scope)
    return out


def _modeled() -> set[str]:
    return {e["entity_type"] for e in manifest_entries()}


def _edges(entity_type: str, item: dict[str, Any]) -> set[tuple[str, str, str, tuple[tuple[str, Any], ...]]]:
    """``(edge type, from ref, to ref, properties)`` for every edge the manifest's rules emit for ``item``."""
    entry = _entry(entity_type)
    node = project_item(entry, item, {"region": REGION})
    emission = emit_edges(node, entry, modeled_types=_modeled(), transforms=build_transform_registry(), dimensions={})
    assert emission.warnings == []
    return {
        (e["edge"]["edge_type"], e["edge"]["from_ref"], e["edge"]["to_ref"], tuple(sorted(e["edge"]["properties"].items())))
        for e in emission.envelopes
    }


class TestReadPath:
    """The first component is the source, the last the destination, the ones between are hops (-4)."""

    @pytest.mark.spec("req-aws-collector-network-analyzer-4")
    def test_ends_and_hops_come_from_the_components_in_sequence_order(self) -> None:
        path = components(IGW, RTB, ACL, SG, ENI)
        path.reverse()  # AWS's list order is not relied on: SequenceNumber is
        read = ni.read_path(path, ni.ACCESS_SCOPE)
        assert (read.source, read.destination) == ((ni.INTERNET_GATEWAY, IGW), (ni.NETWORK_INTERFACE, ENI))
        assert read.hops == [(1, ni.ROUTE_TABLE, RTB), (2, ni.NETWORK_ACL, ACL), (3, ni.SECURITY_GROUP, SG)]
        assert read.unmatched == [] and read.count == 5

    @pytest.mark.spec("req-aws-collector-network-analyzer-4")
    def test_a_component_no_role_accepts_is_listed_with_its_reason_and_gets_no_edge(self) -> None:
        # A subnet is not a Network Access Analyzer path resource, an unknown id matches no type, and a route table
        # is not a type a finding's path can start at.
        read = ni.read_path(components(RTB, SUBNET, "x-0a1b2c3d", ENI), ni.ACCESS_SCOPE)
        assert (read.source, read.destination, read.hops) == (None, (ni.NETWORK_INTERFACE, ENI), [])
        assert [(u["step"], u["id"]) for u in read.unmatched] == [(0, RTB), (1, SUBNET), (2, "x-0a1b2c3d")]
        assert read.unmatched[0]["reason"] == f"the source: {ni.ROUTE_TABLE} is not an end the service lists"
        assert read.unmatched[1]["reason"] == f"{ni.SUBNET} is not a path type the service lists"
        assert read.unmatched[2]["reason"] == "no tabled aws_core type matches its id or ARN"

    @pytest.mark.spec("req-aws-collector-network-analyzer-4")
    def test_the_longest_id_prefix_wins_and_an_arn_names_a_load_balancer(self) -> None:
        assert ni.classify_component({"Id": "vpce-svc-0a1b2c3d"}) == (ni.VPC_ENDPOINT_SERVICE, "vpce-svc-0a1b2c3d")
        assert ni.classify_component({"Id": "vpce-0a1b2c3d"}) == (ni.VPC_ENDPOINT, "vpce-0a1b2c3d")
        assert ni.classify_component({"Id": "tgw-attach-0a1b2c3d"}) == (ni.TRANSIT_GATEWAY_ATTACHMENT, "tgw-attach-0a1b2c3d")
        assert ni.classify_component({"Id": "tgw-rtb-0a1b2c3d"}) == (ni.TRANSIT_GATEWAY_ROUTE_TABLE, "tgw-rtb-0a1b2c3d")
        assert ni.classify_component({"Id": "tgw-0a1b2c3d"}) == (ni.TRANSIT_GATEWAY, "tgw-0a1b2c3d")
        assert ni.classify_component({"Id": "app/web/50dc6c495c0c9188", "Arn": ALB_ARN}) == (ni.ALB, ALB_ARN)
        assert ni.classify_component({"Id": "web"}) is None

    def test_a_component_without_a_sequence_number_keeps_its_place_after_the_numbered_ones(self) -> None:
        listed = [{"Component": {"Id": SG}}, {"SequenceNumber": 2, "Component": {"Id": ENI}}, {"SequenceNumber": 1, "Component": {"Id": IGW}}]
        assert [c["Component"]["Id"] for c in ni.ordered_components(listed)] == [IGW, ENI, SG]

    def test_a_component_met_twice_has_one_path_edge_at_its_first_step(self) -> None:
        slots = ni.slots(ni.read_path(components(IGW, SG, RTB, SG, ENI), ni.ACCESS_SCOPE), ni.ACCESS_SCOPE)
        assert slots["_hops_security_group"] == [{"key": SG, "properties": {"step": 1}}]


class TestAccessScopeReader:
    """One node per finding of a succeeded analysis, read to its end; a cut read is a gap (-1, -2)."""

    @pytest.mark.spec("req-aws-collector-network-analyzer-1")
    def test_every_finding_of_a_succeeded_analysis_is_read_to_its_end(self) -> None:
        analyses = [
            scope_analysis(),
            scope_analysis(NetworkInsightsAccessScopeAnalysisId="nisa-running", Status="running"),
            scope_analysis(NetworkInsightsAccessScopeAnalysisId="nisa-none", FindingsFound="false"),
            scope_analysis(NetworkInsightsAccessScopeAnalysisId="nisa-failed", Status="failed"),
        ]
        with _Ec2() as aws:
            aws.stub.add_response("describe_network_insights_access_scope_analyses", {"NetworkInsightsAccessScopeAnalyses": analyses}, {})
            ask = {"NetworkInsightsAccessScopeAnalysisId": "nisa-0a1b2c3d4e5f60718"}
            aws.stub.add_response(
                "get_network_insights_access_scope_analysis_findings",
                {"AnalysisFindings": [finding("f-1", components(IGW, SG, ENI))], "NextToken": "page-2"},
                ask,
            )
            aws.stub.add_response(
                "get_network_insights_access_scope_analysis_findings",
                {"AnalysisFindings": [finding("f-2", components(ENI, RTB, IGW))]},
                {**ask, "NextToken": "page-2"},
            )
            items = list(ni.ec2_network_access_scope_findings_described(None, client_for=aws.client_for))
        assert [(i["_analysis_arn"], i["FindingId"]) for i in items] == [(SCOPE_ANALYSIS_ARN, "f-1"), (SCOPE_ANALYSIS_ARN, "f-2")]
        first = items[0]
        assert (first["_analysis_arn"], first["_analysis_start_date"], first["_analysis_end_date"]) == (
            SCOPE_ANALYSIS_ARN,
            "2026-11-20T10:00:00Z",
            "2026-11-20T10:04:00Z",
        )
        assert first[EDGE_READS]["_analysis_arn"] == COMPLETE
        assert set(first[EDGE_READS]) == {"_analysis_arn", *ni.slot_names(ni.ACCESS_SCOPE)}

    @pytest.mark.spec("req-aws-collector-network-analyzer-2")
    def test_an_analysis_whose_findings_could_not_all_be_read_contributes_none_and_is_a_gap(self) -> None:
        second = scope_analysis(
            NetworkInsightsAccessScopeAnalysisId="nisa-second",
            NetworkInsightsAccessScopeAnalysisArn=SCOPE_ANALYSIS_ARN.replace("0a1b2c3d4e5f60718", "second"),
        )
        with _Ec2() as aws:
            aws.stub.add_response(
                "describe_network_insights_access_scope_analyses", {"NetworkInsightsAccessScopeAnalyses": [scope_analysis(), second]}, {}
            )
            ask = {"NetworkInsightsAccessScopeAnalysisId": "nisa-0a1b2c3d4e5f60718"}
            aws.stub.add_response(
                "get_network_insights_access_scope_analysis_findings",
                {"AnalysisFindings": [finding("f-1", components(IGW, ENI))], "NextToken": "page-2"},
                ask,
            )
            aws.stub.add_client_error(
                "get_network_insights_access_scope_analysis_findings", "RequestLimitExceeded", expected_params={**ask, "NextToken": "page-2"}
            )
            aws.stub.add_response(
                "get_network_insights_access_scope_analysis_findings",
                {"AnalysisFindings": [finding("f-9", components(IGW, ENI))]},
                {"NetworkInsightsAccessScopeAnalysisId": "nisa-second"},
            )
            yielded: list[dict[str, Any]] = []
            with pytest.raises(UndescribedError, match="nisa-0a1b2c3d4e5f60718"):
                for item in ni.ec2_network_access_scope_findings_described(None, client_for=aws.client_for):
                    yielded.append(item)
        assert [i["FindingId"] for i in yielded] == ["f-9"]

    def test_an_account_with_no_analyses_yields_nothing_and_raises_nothing(self) -> None:
        with _Ec2() as aws:
            aws.stub.add_response("describe_network_insights_access_scope_analyses", {"NetworkInsightsAccessScopeAnalyses": []}, {})
            assert list(ni.ec2_network_access_scope_findings_described(None, client_for=aws.client_for)) == []

    def test_both_readers_are_registered(self) -> None:
        registry = build_custom_fn_registry()
        for name, fn in ni.NETWORK_INSIGHTS_FNS.items():
            assert registry.get(name) is fn


class TestThroughTheEngine:
    """The items through the manifest entries' own projection and edge rules (-4, -5)."""

    @pytest.mark.spec("req-aws-collector-network-analyzer-4", "req-aws-collector-network-analyzer-5")
    def test_a_finding_lands_as_its_compound_edge_with_its_analysis_and_dates(self) -> None:
        item = _derived(ni.access_scope_finding_item(finding("f-1", components(IGW, RTB, SG, ACL, ENI)), scope_analysis()))
        node = project_item(_entry(ni.ACCESS_SCOPE_FINDING), item, {"region": REGION})
        key = f"aws:{ACCOUNT}:{REGION}:nisa-0a1b2c3d4e5f60718/f-1"  # the batch ref; the node is keyed by (analysis_arn, finding_id)
        assert node.natural_key == key
        assert {k: node.fields[k] for k in ("name", "finding_id", "analysis_arn", "access_scope_id", "component_count")} == {
            "name": "f-1",
            "finding_id": "f-1",
            "analysis_arn": SCOPE_ANALYSIS_ARN,
            "access_scope_id": "nis-0a1b2c3d4e5f60718",
            "component_count": 5,
        }
        assert (node.fields["analysis_start_date"], node.fields["analysis_end_date"]) == ("2026-11-20T10:00:00Z", "2026-11-20T10:04:00Z")
        assert (node.fields["source_component_id"], node.fields["destination_component_id"]) == (IGW, ENI)
        me = node_ref(ni.ACCESS_SCOPE_FINDING, key)
        assert _edges(ni.ACCESS_SCOPE_FINDING, item) == {
            (ni.REPORTS_ACCESS_SCOPE_FINDING, node_ref(ni.ACCESS_SCOPE_ANALYSIS, SCOPE_ANALYSIS_ARN), me, ()),
            (ni.ACCESS_SCOPE_FINDING_SOURCE, node_ref(ni.INTERNET_GATEWAY, IGW), me, ()),
            (ni.ACCESS_SCOPE_FINDING_DESTINATION, me, node_ref(ni.NETWORK_INTERFACE, ENI), ()),
            (ni.TRAVERSES_COMPONENT, me, node_ref(ni.ROUTE_TABLE, RTB), (("step", 1),)),
            (ni.TRAVERSES_COMPONENT, me, node_ref(ni.SECURITY_GROUP, SG), (("step", 2),)),
            (ni.TRAVERSES_COMPONENT, me, node_ref(ni.NETWORK_ACL, ACL), (("step", 3),)),
        }

    @pytest.mark.spec("req-aws-collector-network-analyzer-5")
    def test_the_resource_a_path_reaches_is_stated_even_when_no_node_matches_it(self) -> None:
        item = _derived(ni.access_scope_finding_item(finding("f-1", components(IGW, "arn:aws:example:::thing")), scope_analysis()))
        node = project_item(_entry(ni.ACCESS_SCOPE_FINDING), item, {"region": REGION})
        assert (node.fields["destination_component_id"], node.fields["destination_component_arn"]) == (None, "arn:aws:example:::thing")
        assert [u["step"] for u in node.fields["unmatched_components"]] == [1]

    @pytest.mark.spec("req-aws-collector-network-analyzer-4")
    def test_an_analysis_that_found_a_path_lands_as_its_compound_edge(self) -> None:
        item = ni.reachability_analysis_item(reachability())
        me = node_ref(ni.REACHABILITY_ANALYSIS, ANALYSIS_ARN)
        assert _edges(ni.REACHABILITY_ANALYSIS, item) == {
            (ni.REACHABILITY_ANALYSIS_SOURCE, node_ref(ni.EC2_INSTANCE, INSTANCE), me, ()),
            (ni.REACHABILITY_ANALYSIS_DESTINATION, me, node_ref(ni.INTERNET_GATEWAY, IGW), ()),
            (ni.TRAVERSES_COMPONENT, me, node_ref(ni.NETWORK_INTERFACE, ENI), (("step", 1),)),
            (ni.TRAVERSES_COMPONENT, me, node_ref(ni.SECURITY_GROUP, SG), (("step", 2),)),
            (ni.TRAVERSES_COMPONENT, me, node_ref(ni.NETWORK_ACL, ACL), (("step", 3),)),
            (ni.TRAVERSES_COMPONENT, me, node_ref(ni.ROUTE_TABLE, RTB), (("step", 4),)),
        }
        node = project_item(_entry(ni.REACHABILITY_ANALYSIS), item, {"region": REGION})
        reads = anchor_reads(node, _entry(ni.REACHABILITY_ANALYSIS), modeled_types=_modeled(), transforms=build_transform_registry())
        assert set(reads.values()) == {COMPLETE}

    @pytest.mark.spec("req-aws-collector-network-analyzer-4")
    @pytest.mark.parametrize(
        ("over", "read"),
        [({"NetworkPathFound": False}, COMPLETE), ({"Status": "running", "NetworkPathFound": None}, PARTIAL)],
    )
    def test_an_analysis_without_a_found_path_has_no_role_edges(self, over: dict[str, Any], read: str) -> None:
        analysis = {k: v for k, v in {**reachability(), **over}.items() if v is not None}
        item = ni.reachability_analysis_item(analysis)
        assert _edges(ni.REACHABILITY_ANALYSIS, item) == set()
        assert set(item[EDGE_READS].values()) == {read}

    def test_the_analysis_reader_yields_each_analysis_with_its_slots(self) -> None:
        with _Ec2() as aws:
            aws.stub.add_response("describe_network_insights_analyses", {"NetworkInsightsAnalyses": [reachability()]}, {})
            [item] = list(ni.ec2_network_insights_analyses_described(None, client_for=aws.client_for))
        assert item["_source_ec2_instance"] == [INSTANCE] and item["_destination_internet_gateway"] == [IGW]


class TestDeclarations:
    """Both middle nodes declare their compound edge as core ships it (-3)."""

    @pytest.mark.spec("req-aws-collector-network-analyzer-3")
    @pytest.mark.parametrize(("entity_type", "kind"), [(ni.ACCESS_SCOPE_FINDING, "ACCESS_SCOPE_FINDING"), (ni.REACHABILITY_ANALYSIS, "REACHABILITY_ANALYSIS")])
    def test_the_declaration_is_a_valid_compound_edge(self, entity_type: str, kind: str) -> None:
        from tap_grid.compound_edges import compound_edge_of, compound_types
        from tap_grid.registry import get_model_class

        declared = compound_edge_of(get_model_class(entity_type))
        assert declared is not None and declared.kind == kind
        assert (declared.source, declared.destination) == (ni.KINDS[entity_type].source_edge, ni.KINDS[entity_type].destination_edge)
        assert declared.path == ni.TRAVERSES_COMPONENT and declared.carrier is None
        assert declared.retires_with == ("source", "destination")
        assert entity_type in compound_types()

    @pytest.mark.spec("req-aws-collector-network-analyzer-3")
    def test_the_boot_check_passes(self) -> None:
        from django.core import checks

        errors = [m for m in checks.run_checks() if getattr(m, "id", "") in ("tap_grid.E004", "tap_grid.E006")]
        assert errors == [], errors


class TestManifestRules:
    """One edge rule per slot, and each role edge lists exactly the role's types (-6)."""

    @pytest.mark.spec("req-aws-collector-network-analyzer-6")
    @pytest.mark.parametrize("entity_type", sorted(ni.KINDS))
    def test_the_manifest_declares_one_rule_per_slot(self, entity_type: str) -> None:
        kind = ni.KINDS[entity_type]
        rules = [r for r in _entry(entity_type).get("edges", []) if r["edge_type"] != ni.REPORTS_ACCESS_SCOPE_FINDING]
        declared = {(r["value_path"].removesuffix("[]"), r["target_type"], r["edge_type"]) for r in rules}
        expected = (
            {(f"_source_{ni.token(t)}", t, kind.source_edge) for t in kind.ends}
            | {(f"_destination_{ni.token(t)}", t, kind.destination_edge) for t in kind.ends}
            | {(f"_hops_{ni.token(t)}", t, ni.TRAVERSES_COMPONENT) for t in kind.path}
        )
        assert declared == expected and len(rules) == len(expected)
        assert {r["value_path"].removesuffix("[]") for r in rules} == set(ni.slot_names(kind))

    @pytest.mark.spec("req-aws-collector-network-analyzer-6")
    @pytest.mark.parametrize("entity_type", sorted(ni.KINDS))
    def test_each_role_edge_lists_exactly_the_role_types(self, entity_type: str) -> None:
        kind = ni.KINDS[entity_type]

        def edge(slug: str) -> dict[str, Any]:
            return json.loads((EDGES_DIR / f"{slug.removesuffix('__aws_core')}.edge.json").read_text())

        assert (set(edge(kind.source_edge)["sources"]), edge(kind.source_edge)["targets"]) == (set(kind.ends), [entity_type])
        assert (edge(kind.destination_edge)["sources"], set(edge(kind.destination_edge)["targets"])) == ([entity_type], set(kind.ends))
        traverses = edge(ni.TRAVERSES_COMPONENT)
        assert entity_type in traverses["sources"] and set(kind.path) <= set(traverses["targets"])


def _node(entity_type: str, fields: dict[str, Any]) -> Any:
    from tap_grid.services import create_node, get_node

    result = create_node(entity_type, {"name": "n", **fields})
    assert result.success, result.errors
    return get_node(result.entity_id)


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-network-analyzer-3")
@pytest.mark.parametrize("retire", ["source", "destination", "hop"])
def test_a_finding_retires_with_either_end_and_not_with_a_hop(retire: str) -> None:
    from tap_grid.models import Entity
    from tap_grid.services import create_edge, delete_node

    igw = _node(ni.INTERNET_GATEWAY, {"igw_id": IGW})
    eni = _node(ni.NETWORK_INTERFACE, {"ec2_network_interface_id": ENI})
    sg = _node(ni.SECURITY_GROUP, {"group_id": SG})
    found = _node(ni.ACCESS_SCOPE_FINDING, {"analysis_arn": SCOPE_ANALYSIS_ARN, "finding_id": "f-1"})
    create_edge(igw.entity, found.entity, ni.ACCESS_SCOPE_FINDING_SOURCE)
    create_edge(found.entity, eni.entity, ni.ACCESS_SCOPE_FINDING_DESTINATION)
    create_edge(found.entity, sg.entity, ni.TRAVERSES_COMPONENT, {"step": 1})
    result = delete_node({"source": igw, "destination": eni, "hop": sg}[retire].entity_id)
    assert result.success, result.errors
    assert (Entity.objects.get(id=found.entity_id).deleted_at is not None) is (retire != "hop")


def _reachability_graph() -> dict[str, Any]:
    """An analysis that found a path: instance -> analysis -> internet gateway, through a security group."""
    from tap_grid.services import create_edge

    nodes = {
        "source": _node(ni.EC2_INSTANCE, {"instance_id": INSTANCE}),
        "destination": _node(ni.INTERNET_GATEWAY, {"igw_id": IGW}),
        "hop": _node(ni.SECURITY_GROUP, {"group_id": SG}),
        "analysis": _node(ni.REACHABILITY_ANALYSIS, {"ec2_network_insights_analysis_arn": ANALYSIS_ARN}),
    }
    create_edge(nodes["source"].entity, nodes["analysis"].entity, ni.REACHABILITY_ANALYSIS_SOURCE)
    create_edge(nodes["analysis"].entity, nodes["destination"].entity, ni.REACHABILITY_ANALYSIS_DESTINATION)
    create_edge(nodes["analysis"].entity, nodes["hop"].entity, ni.TRAVERSES_COMPONENT, {"step": 2})
    return nodes


def _live(node: Any) -> bool:
    from tap_grid.models import Entity

    return Entity.objects.get(id=node.entity_id).deleted_at is None


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-network-analyzer-3")
@pytest.mark.parametrize("retire", ["source", "destination", "hop"])
def test_a_reachability_analysis_retires_with_either_end_and_not_with_a_hop(retire: str) -> None:
    from tap_grid.services import delete_node

    nodes = _reachability_graph()
    result = delete_node(nodes[retire].entity_id)
    assert result.success, result.errors
    assert _live(nodes["analysis"]) is (retire == "hop")


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-network-analyzer-3")
def test_an_end_a_later_batch_does_not_list_retires_nothing() -> None:
    """A run that re-observes the analysis and simply does not name its ends is not a deletion of either end:
    only a real retirement of an end retires the middle node (req-grid-edge-compound-5)."""
    import uuid

    from tap_grid.grift import grift_import
    from tap_grid.grift.upgrade import build_header

    nodes = _reachability_graph()
    later = {
        "_reserved": {},
        "batches": [
            {
                "batch_entity": {"entity_id": str(uuid.uuid7()), "entity_type": "batch", "name": "later", "dimensions": {}},
                "batch_node": {"source": "test", "name": "later", "description": "the analysis alone, its ends unlisted"},
                "nodes": [
                    {
                        "entity": {
                            "entity_id": str(nodes["analysis"].entity_id),
                            "entity_type": ni.REACHABILITY_ANALYSIS,
                            "name": "n",
                            "dimensions": {},
                        },
                        "node": {"name": "n", "ec2_network_insights_analysis_arn": ANALYSIS_ARN},
                    }
                ],
                "edges": [],
            }
        ],
    }
    later["metadata"] = build_header(later)
    imported = grift_import(later)
    assert imported.success, [(i.code, i.message) for i in imported.errors]
    assert all(_live(node) for node in nodes.values())
