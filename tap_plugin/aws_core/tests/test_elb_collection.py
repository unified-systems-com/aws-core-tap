"""The load balancer readers (``elbv2_albs_described``, ``elb_family_described``,
``elbv2_target_groups_described``): which load balancers each takes, how tags are read, and what a failed
tag read does. Fake ELB clients, no network."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector.authority import COMPLETE, EDGE_READS
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    elb_family_described,
    elbv2_albs_described,
    elbv2_target_groups_described,
)

REGION_ARN = "arn:aws:elasticloadbalancing:us-east-1:123456789012"


def _arn(kind: str, name: str) -> str:
    return f"{REGION_ARN}:loadbalancer/{kind}/{name}/abc"


def _denied(op: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, op)


class _Client:
    """A fake ELB client: ``describe_*`` return canned answers; ``describe_tags`` serves a tag table, records
    the batches it was asked for, and fails for any batch holding an id in ``deny``."""

    def __init__(self, answers: dict[str, Any], tags: dict[str, dict[str, str]] | None = None, deny: set[str] | None = None):
        self._answers = answers
        self._tags = tags or {}
        self._deny = deny or set()
        self.tag_batches: list[list[str]] = []

    def can_paginate(self, method: str) -> bool:
        return False

    def describe_load_balancers(self, **_: Any) -> Any:
        return self._answers["lbs"]

    def describe_target_groups(self, **_: Any) -> Any:
        return self._answers.get("groups", {"TargetGroups": []})

    def describe_target_health(self, **kwargs: Any) -> Any:
        answer = self._answers.get("health", {}).get(kwargs["TargetGroupArn"], {"TargetHealthDescriptions": []})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def describe_listeners(self, **kwargs: Any) -> Any:
        answer = self._answers.get("listeners", {}).get(kwargs["LoadBalancerArn"], {"Listeners": []})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def describe_rules(self, **kwargs: Any) -> Any:
        answer = self._answers.get("rules", {}).get(kwargs["ListenerArn"], {"Rules": []})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def describe_instance_health(self, **kwargs: Any) -> Any:
        answer = self._answers.get("instance_health", {}).get(kwargs["LoadBalancerName"], {"InstanceStates": []})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def describe_tags(self, **kwargs: Any) -> Any:
        (ids,) = kwargs.values()
        self.tag_batches.append(list(ids))
        if self._deny & set(ids):
            raise _denied("DescribeTags")
        key = "ResourceArn" if "ResourceArns" in kwargs else "LoadBalancerName"
        return {
            "TagDescriptions": [
                {key: i, "Tags": [{"Key": k, "Value": v} for k, v in self._tags.get(i, {}).items()]} for i in ids
            ]
        }


def _run(fn: Any, **clients: _Client) -> list[dict[str, Any]]:
    return list(fn(None, client_for=lambda service: clients[service]))


def _v2(*lbs: dict[str, Any], **kw: Any) -> _Client:
    return _Client({"lbs": {"LoadBalancers": list(lbs)}}, **kw)


def _lb(kind: str, name: str, **extra: Any) -> dict[str, Any]:
    return {
        "LoadBalancerArn": _arn(kind, name),
        "LoadBalancerName": name,
        "DNSName": f"{name}.elb.amazonaws.com",
        "Type": {"app": "application", "net": "network", "gwy": "gateway"}[kind],
        "State": {"Code": "active"},
        "AvailabilityZones": [{"SubnetId": "subnet-b"}, {"SubnetId": "subnet-a"}],
        **extra,
    }


class TestApplicationLoadBalancers:
    def test_only_application_load_balancers_are_taken_with_state_subnets_and_tags(self) -> None:
        v2 = _v2(_lb("app", "web"), _lb("net", "tcp"), tags={_arn("app", "web"): {"owner": "net"}})
        [alb] = _run(elbv2_albs_described, elbv2=v2)
        assert alb["LoadBalancerName"] == "web"
        assert (alb["_state"], alb["_subnet_ids"]) == ("active", ["subnet-a", "subnet-b"])
        assert (alb["_tags"], alb["_tags_unread"]) == ({"owner": "net"}, False)
        assert alb[EDGE_READS] == {"_subnet_ids": COMPLETE, "_forwards": COMPLETE, "_target_instance_ids": COMPLETE, "_target_lambda_arns": COMPLETE}
        assert (alb["_forwards"], alb["_target_instance_ids"], alb["_target_lambda_arns"]) == ([], [], [])
        assert v2.tag_batches == [[_arn("app", "web")]]

    def test_tags_are_read_twenty_arns_to_a_call(self) -> None:
        v2 = _v2(*[_lb("app", f"lb{i}") for i in range(45)])
        assert len(_run(elbv2_albs_described, elbv2=v2)) == 45
        assert [len(b) for b in v2.tag_batches] == [20, 20, 5]

    def test_a_denied_batch_leaves_its_tags_unread_and_the_rest_read(self) -> None:
        lbs = [_lb("app", f"lb{i}") for i in range(25)]
        v2 = _v2(*lbs, tags={_arn("app", "lb21"): {"k": "v"}}, deny={_arn("app", "lb3")})
        items = {i["LoadBalancerName"]: i for i in _run(elbv2_albs_described, elbv2=v2)}
        assert all(items[f"lb{n}"]["_tags_unread"] for n in range(20))
        assert items["lb21"]["_tags"] == {"k": "v"} and items["lb21"]["_tags_unread"] is False
        assert items["lb24"]["_tags"] == {} and items["lb24"]["_tags_unread"] is False

    def test_a_successful_answer_that_leaves_an_id_out_reads_it_as_unread(self) -> None:
        class _Partial(_Client):
            def describe_tags(self, **kwargs: Any) -> Any:
                answer = super().describe_tags(**kwargs)
                answer["TagDescriptions"] = answer["TagDescriptions"][:1]
                return answer

        lbs = [_lb("app", "a"), _lb("app", "b")]
        v2 = _Partial({"lbs": {"LoadBalancers": lbs}}, tags={_arn("app", "a"): {"k": "v"}})
        items = {i["LoadBalancerName"]: i for i in _run(elbv2_albs_described, elbv2=v2)}
        assert (items["a"]["_tags"], items["a"]["_tags_unread"]) == ({"k": "v"}, False)
        assert (items["b"]["_tags"], items["b"]["_tags_unread"]) == ({}, True)

    def test_no_load_balancers_makes_no_tag_call(self) -> None:
        v2 = _v2()
        assert _run(elbv2_albs_described, elbv2=v2) == []
        assert v2.tag_batches == []


class TestOtherLoadBalancers:
    def _classic(self, **kw: Any) -> _Client:
        return _Client(
            {
                "lbs": {
                    "LoadBalancerDescriptions": [
                        {
                            "LoadBalancerName": "legacy",
                            "DNSName": "legacy.elb.amazonaws.com",
                            "Scheme": "internal",
                            "Subnets": ["subnet-z", "subnet-y"],
                        }
                    ]
                }
            },
            **kw,
        )

    def test_network_gateway_and_classic_are_told_apart(self) -> None:
        v2 = _v2(_lb("app", "web"), _lb("net", "tcp"), _lb("gwy", "inspect"))
        items = _run(elb_family_described, elbv2=v2, elb=self._classic(tags={"legacy": {"team": "ops"}}))
        assert {i["LoadBalancerName"]: i["_lb_type"] for i in items} == {
            "tcp": "network",
            "inspect": "gateway",
            "legacy": "classic",
        }
        classic = next(i for i in items if i["_lb_type"] == "classic")
        assert (classic["_tags"], classic["_subnet_ids"]) == ({"team": "ops"}, ["subnet-y", "subnet-z"])

    def test_a_classic_load_balancer_is_keyed_by_dns_name_and_read_by_name(self) -> None:
        classic = self._classic()
        _run(elb_family_described, elbv2=_v2(), elb=classic)
        assert classic.tag_batches == [["legacy"]]

    def test_each_api_fails_its_own_tags_alone(self) -> None:
        v2 = _v2(_lb("net", "tcp"), deny={_arn("net", "tcp")})
        items = {i["LoadBalancerName"]: i for i in _run(elb_family_described, elbv2=v2, elb=self._classic())}
        assert items["tcp"]["_tags_unread"] is True
        assert items["legacy"]["_tags_unread"] is False


class TestTargetGroups:
    def test_target_groups_carry_their_tags(self) -> None:
        arn = f"{REGION_ARN}:targetgroup/web/1"
        client = _Client({"groups": {"TargetGroups": [{"TargetGroupArn": arn, "TargetGroupName": "web"}]}}, tags={arn: {"a": "b"}})
        [tg] = _run(elbv2_target_groups_described, elbv2=client)
        assert (tg["_tags"], tg["_tags_unread"]) == ({"a": "b"}, False)

    def test_a_denied_tag_read_is_unread_not_empty(self) -> None:
        arn = f"{REGION_ARN}:targetgroup/web/1"
        client = _Client({"groups": {"TargetGroups": [{"TargetGroupArn": arn}]}}, deny={arn})
        [tg] = _run(elbv2_target_groups_described, elbv2=client)
        assert (tg["_tags"], tg["_tags_unread"]) == ({}, True)


class TestClassicRoutes:
    """A Classic load balancer routes to its registered instances with their health (req-aws-collector-lb-topology-8)."""

    def _classic(self, health: Any = None) -> _Client:
        lb = {
            "LoadBalancerName": "legacy",
            "DNSName": "legacy.elb.amazonaws.com",
            "Subnets": [],
            "Instances": [{"InstanceId": "i-2"}, {"InstanceId": "i-1"}],
            "ListenerDescriptions": [
                {"Listener": {"Protocol": "HTTP", "LoadBalancerPort": 80, "InstanceProtocol": "HTTP", "InstancePort": 8080}},
                {"Listener": {"Protocol": "HTTPS", "LoadBalancerPort": 443, "InstanceProtocol": "HTTP", "InstancePort": 8080}},
                {"Listener": {"Protocol": "TCP", "LoadBalancerPort": 9000, "InstanceProtocol": "TCP", "InstancePort": 9000}},
            ],
        }
        states = health if health is not None else {"InstanceStates": [
            {"InstanceId": "i-1", "State": "InService", "ReasonCode": "N/A", "Description": "N/A"},
            {"InstanceId": "i-2", "State": "OutOfService", "ReasonCode": "Instance", "Description": "Instance has failed at least the UnhealthyThreshold number of health checks consecutively."},
        ]}
        return _Client({"lbs": {"LoadBalancerDescriptions": [lb]}, "instance_health": {"legacy": states}})

    @pytest.mark.spec("req-aws-collector-lb-topology-8")
    def test_each_instance_is_routed_once_per_instance_port_with_its_health(self) -> None:
        [item] = _run(elb_family_described, elbv2=_v2(), elb=self._classic())
        routes = {(t["id"], t["properties"]["port"]): t["properties"] for t in item["_instance_targets"]}
        assert set(routes) == {("i-1", 8080), ("i-1", 9000), ("i-2", 8080), ("i-2", 9000)}
        assert (routes[("i-1", 8080)]["health_state"], routes[("i-2", 9000)]["health_state"]) == ("InService", "OutOfService")
        assert routes[("i-2", 9000)]["health_reason"] == "Instance"
        assert routes[("i-1", 8080)]["availability_zone"] is None
        assert item[EDGE_READS]["_instance_targets"] == COMPLETE

    @pytest.mark.spec("req-aws-collector-lb-topology-8")
    def test_a_health_read_that_failed_leaves_the_health_unobserved_and_the_routes_read(self) -> None:
        [item] = _run(elb_family_described, elbv2=_v2(), elb=self._classic(health=_denied("DescribeInstanceHealth")))
        assert {t["id"] for t in item["_instance_targets"]} == {"i-1", "i-2"}
        assert all(t["properties"]["health_state"] is None for t in item["_instance_targets"])
        assert item[EDGE_READS]["_instance_targets"] == COMPLETE

    @pytest.mark.spec("req-aws-collector-lb-topology-3")
    def test_the_replaced_direct_routes_are_empty_and_read_complete(self) -> None:
        [item] = _run(elb_family_described, elbv2=_v2(), elb=self._classic())
        assert (item["_target_instance_ids"], item["_forwards"]) == ([], [])
        assert (item[EDGE_READS]["_target_instance_ids"], item[EDGE_READS]["_forwards"]) == (COMPLETE, COMPLETE)

    def test_a_load_balancer_with_no_instances_makes_no_health_call(self) -> None:
        class _NoHealth(_Client):
            def describe_instance_health(self, **kwargs: Any) -> Any:
                raise AssertionError("no instances, no health call")

        client = _NoHealth({"lbs": {"LoadBalancerDescriptions": [{"LoadBalancerName": "empty", "DNSName": "empty.elb.amazonaws.com", "Subnets": []}]}})
        [item] = _run(elb_family_described, elbv2=_v2(), elb=client)
        assert item["_instance_targets"] == []
