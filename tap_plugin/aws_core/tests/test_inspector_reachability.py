"""The Inspector network-reachability finding is the first compound edge (aws-core-tap#261,
req-aws-landing-zone-inspector-reachability, req-grid-edge-compound).

The reader against botocore's own model (``Stubber``); the declaration against core's one parser and boot check; and
the retire rule against the real delete walk on grid rows. No AWS call is made.
"""

from __future__ import annotations

from typing import Any

import pytest
from tap_plugin.aws_core.collectors.boto3_collector import inspector as inspector_mod
from tap_plugin.aws_core.collectors.boto3_collector.identity import node_ref
from tap_plugin.aws_core.collectors.boto3_collector.inspector import (
    DOCUMENTED_COMPONENT_TYPES,
    HOSTS_INSPECTOR2_REACHABILITY_FINDING,
    INTERNET_GATEWAY,
    NETWORK_ACL,
    NETWORK_INTERFACE,
    REACHABILITY_DESTINATION,
    REACHABILITY_FINDING,
    REACHABILITY_SOURCE,
    ROUTE_TABLE,
    SECURITY_GROUP,
    TRAVERSES_COMPONENT,
    classify_step,
    read_path,
)

from .test_inspector_findings import (
    ACCOUNT,
    OBSERVED,
    PARTITION,
    REGION,
    _edges,
    _listing,
    _nodes,
    _reader,
    _Stubbed,
    expect_list,
    expect_status,
    expect_totals,
    finding_arn,
)

IGW, RTB, ACL, SG, ENI = "igw-0a1b2c3d", "rtb-0a1b2c3d", "acl-0a1b2c3d", "sg-0a1b2c3d", "eni-0a1b2c3d"


def steps(*ids: str, component_type: str = "UNDOCUMENTED") -> list[dict[str, Any]]:
    return [{"componentId": i, "componentType": component_type} for i in ids]


def reachability(n: int, path: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "findingArn": finding_arn(n),
        "awsAccountId": ACCOUNT,
        "type": "NETWORK_REACHABILITY",
        "title": "Port 22 is reachable from an Internet Gateway",
        "description": "On the instance, port range 22 - 22 is reachable from an Internet Gateway.",
        "remediation": {"recommendation": {"text": "Restrict the security group."}},
        "severity": "MEDIUM",
        "firstObservedAt": OBSERVED,
        "lastObservedAt": OBSERVED,
        "status": "ACTIVE",
        "resources": [{"type": "AWS_EC2_INSTANCE", "id": "i-0abc1234def567890", "region": REGION}],
        "networkReachabilityDetails": {
            "openPortRange": {"begin": 22, "end": 22},
            "protocol": "TCP",
            "networkPath": {"steps": path},
        },
    }


@pytest.mark.spec("req-aws-landing-zone-inspector-reachability-2", "req-aws-landing-zone-inspector-reachability-3")
def test_a_reachability_finding_is_written_as_its_compound_edge() -> None:
    path = steps(IGW, RTB, ACL, SG, ENI)
    with _Stubbed() as aws:
        expect_status(aws.stub)
        expect_totals(aws.stub, "NETWORK_REACHABILITY", {"all": 1, "medium": 1})
        expect_list(aws.stub, "NETWORK_REACHABILITY", "ACTIVE", [reachability(1, path)])
        expect_list(aws.stub, "NETWORK_REACHABILITY", "CLOSED", [])
        reader = _reader(aws, types=("NETWORK_REACHABILITY",))
        reader.inspector.read(REGION)
        aws.stub.assert_no_pending_responses()
    [row] = _nodes(reader, REACHABILITY_FINDING)
    assert (row["protocol"], row["open_port_begin"], row["open_port_end"]) == ("TCP", 22, 22)
    assert row["network_path"] == path and row["unmatched_steps"] == []
    assert row["component_types_unmatched"] == ["UNDOCUMENTED"], "an undocumented componentType is said, not guessed"
    me = node_ref(REACHABILITY_FINDING, finding_arn(1))
    assert _edges(reader, REACHABILITY_SOURCE) == {(node_ref(INTERNET_GATEWAY, IGW), me)}
    assert _edges(reader, REACHABILITY_DESTINATION) == {(me, node_ref(NETWORK_INTERFACE, ENI))}
    assert _edges(reader, TRAVERSES_COMPONENT) == {
        (me, node_ref(ROUTE_TABLE, RTB)),
        (me, node_ref(NETWORK_ACL, ACL)),
        (me, node_ref(SECURITY_GROUP, SG)),
    }
    traverses = {e["edge"]["to_ref"]: e["edge"]["properties"] for e in reader.result.edges if e["edge"]["edge_type"] == TRAVERSES_COMPONENT}
    assert traverses[node_ref(SECURITY_GROUP, SG)] == {"step": 3}
    assert len(_edges(reader, HOSTS_INSPECTOR2_REACHABILITY_FINDING)) == 1
    surface = _listing(reader, "account_region.inspector2_reachability_findings").surface(["b"])
    assert surface["enumeration_complete"] is False and "NETWORK_REACHABILITY" in surface["filter"]


def test_steps_no_tabled_type_matches_are_listed_with_a_reason() -> None:
    reach = read_path(steps(IGW, "subnet-0a1b", "vpce-0a1b", "pcx-0a1b", "eni-first", RTB, ENI))
    assert reach.source == (INTERNET_GATEWAY, IGW)
    assert reach.destination == (NETWORK_INTERFACE, ENI)
    reasons = {s["componentId"]: s["reason"] for s in reach.unmatched_steps}
    assert set(reasons) == {"subnet-0a1b", "vpce-0a1b", "pcx-0a1b", "eni-first"}
    assert "second gateway" in reasons["pcx-0a1b"] and "before the last" in reasons["eni-first"]
    assert read_path([]).source is None and read_path(None).destination is None


def test_a_load_balancer_is_read_from_its_arn() -> None:
    arn = f"arn:{PARTITION}:elasticloadbalancing:{REGION}:{ACCOUNT}:loadbalancer/app/web/0123456789abcdef"
    assert classify_step({"componentId": "web", "componentType": "X", "componentArn": arn}) == ("aws_core__aws_alb", arn)
    assert classify_step({"componentId": "web-classic", "componentType": "X"}) is None


def test_the_documented_component_type_table_is_empty_until_live_values_are_captured() -> None:
    assert DOCUMENTED_COMPONENT_TYPES == {}


@pytest.mark.spec("req-aws-landing-zone-inspector-reachability-1")
def test_the_declaration_is_a_valid_compound_edge() -> None:
    from tap_grid.compound_edges import compound_edge_of, compound_types
    from tap_plugin.aws_core.models.aws_inspector2_reachability_finding import AwsInspector2ReachabilityFinding

    declared = compound_edge_of(AwsInspector2ReachabilityFinding)
    assert declared is not None and declared.kind == "REACHABILITY"
    assert declared.retires_with == ("source", "destination")
    assert declared.path == TRAVERSES_COMPONENT and declared.carrier is None
    assert REACHABILITY_FINDING in compound_types()


@pytest.mark.spec("req-aws-landing-zone-inspector-reachability-1")
def test_the_boot_check_passes() -> None:
    from django.core import checks

    errors = [m for m in checks.run_checks() if getattr(m, "id", "") in ("tap_grid.E004", "tap_grid.E006")]
    assert errors == [], errors


def _node(entity_type: str, fields: dict[str, Any]) -> Any:
    from tap_grid.services import create_node, get_node

    result = create_node(entity_type, {"name": "n", **fields})
    assert result.success, result.errors
    return get_node(result.entity_id)


@pytest.mark.django_db
@pytest.mark.spec("req-aws-landing-zone-inspector-reachability-4")
@pytest.mark.parametrize("retire", ["gateway", "interface", "component"])
def test_the_finding_retires_with_either_end_and_not_with_a_component(retire: str) -> None:
    from tap_grid.models import Entity
    from tap_grid.services import create_edge, delete_node

    igw = _node(INTERNET_GATEWAY, {"igw_id": IGW})
    eni = _node(NETWORK_INTERFACE, {"ec2_network_interface_id": ENI})
    sg = _node(SECURITY_GROUP, {"group_id": SG})
    finding = _node(REACHABILITY_FINDING, {"finding_arn": finding_arn(1)})
    create_edge(igw.entity, finding.entity, REACHABILITY_SOURCE)
    create_edge(finding.entity, eni.entity, REACHABILITY_DESTINATION)
    create_edge(finding.entity, sg.entity, TRAVERSES_COMPONENT, {"step": 3})
    target = {"gateway": igw, "interface": eni, "component": sg}[retire]
    result = delete_node(target.entity_id)
    assert result.success, result.errors
    gone = Entity.objects.get(id=finding.entity_id).deleted_at is not None
    assert gone is (retire != "component")


def test_the_module_reads_every_type_by_default() -> None:
    assert inspector_mod.NETWORK_REACHABILITY in _reader(_Stubbed(), types=None).inspector.selected_types()
