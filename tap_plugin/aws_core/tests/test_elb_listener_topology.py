"""Load balancer -> listener -> rule -> target group (aws-core-tap#220): the listener and rule readers, the walk they
share, the withholding of a load balancer's replaced routes, and the Classic listener reader
(``req-aws-collector-lb-topology-1``, ``-3``, ``-9``). Fake ELB clients, no network."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector.authority import COMPLETE, EDGE_READS, FAILED
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    classic_listener_key,
    elb_classic_listeners_described,
    elbv2_listener_rules_described,
    elbv2_listeners_described,
)
from tap_plugin.aws_core.collectors.boto3_collector.elb_topology import (
    ALB_TYPE,
    ELB_TYPE,
    REPLACED_LB_SCOPES,
    shared_walk,
    walk_listeners,
    walks_of,
    withhold_unreplaced_lb_routes,
)
from tap_plugin.aws_core.collectors.boto3_collector.source import SourceError

REGION_ARN = "arn:aws:elasticloadbalancing:us-east-1:123456789012"


def _denied(op: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, op)


def _lb(kind: str, name: str) -> dict[str, Any]:
    return {
        "LoadBalancerArn": f"{REGION_ARN}:loadbalancer/{kind}/{name}/abc",
        "LoadBalancerName": name,
        "DNSName": f"{name}.elb.amazonaws.com",
        "Type": {"app": "application", "net": "network", "gwy": "gateway"}[kind],
    }


def _listener(lb: dict[str, Any], port: int, protocol: str, *, default_actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "ListenerArn": f"{lb['LoadBalancerArn']}/listener-{port}",
        "LoadBalancerArn": lb["LoadBalancerArn"],
        "Port": port,
        "Protocol": protocol,
        "DefaultActions": default_actions or [],
    }


def _group(name: str) -> str:
    return f"{REGION_ARN}:targetgroup/{name}/1"


class _Meta:
    def __init__(self, region: str) -> None:
        self.region_name = region
        self.partition = "aws"


class _Elbv2:
    """A fake ELBv2 client: canned load balancers, listeners per load balancer and rules per listener (an exception
    in place of an answer raises), counting ``describe_load_balancers`` calls."""

    def __init__(self, lbs: list[dict[str, Any]], listeners: dict[str, Any] | None = None, rules: dict[str, Any] | None = None, region: str = "us-east-1"):
        self.lbs, self.listeners, self.rules = lbs, listeners or {}, rules or {}
        self.meta = _Meta(region)
        self.lb_calls = 0

    def can_paginate(self, method: str) -> bool:
        return False

    def describe_load_balancers(self, **_: Any) -> Any:
        self.lb_calls += 1
        return {"LoadBalancers": self.lbs}

    def describe_listeners(self, **kwargs: Any) -> Any:
        answer = self.listeners.get(kwargs["LoadBalancerArn"], {"Listeners": []})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def describe_rules(self, **kwargs: Any) -> Any:
        answer = self.rules.get(kwargs["ListenerArn"], {"Rules": []})
        if isinstance(answer, Exception):
            raise answer
        return answer

    def describe_listener_certificates(self, **_: Any) -> Any:
        return {"Certificates": []}

    def describe_tags(self, **kwargs: Any) -> Any:
        return {"TagDescriptions": [{"ResourceArn": arn, "Tags": []} for arn in kwargs["ResourceArns"]]}


class _Session:
    pass


def _run(fn: Any, session: Any = None, **clients: Any) -> list[dict[str, Any]]:
    return list(fn(session, client_for=lambda service: clients[service]))


def _alb_with_rules() -> tuple[dict[str, Any], dict[str, Any], _Elbv2]:
    alb = _lb("app", "web")
    listener = _listener(alb, 443, "HTTPS", default_actions=[{"Type": "forward", "TargetGroupArn": _group("web")}])
    host = [{"Field": "host-header", "HostHeaderConfig": {"Values": ["api.example.com"]}}]
    rules = [
        {"RuleArn": "rule-api", "Priority": "10", "IsDefault": False, "Conditions": host, "Actions": [
            {"Type": "forward", "ForwardConfig": {"TargetGroups": [
                {"TargetGroupArn": _group("api-blue"), "Weight": 90}, {"TargetGroupArn": _group("api-green"), "Weight": 10}]}}]},
        {"RuleArn": "rule-old", "Priority": "20", "IsDefault": False, "Conditions": [], "Actions": [
            {"Type": "redirect", "RedirectConfig": {"Host": "new.example.com"}}]},
        {"RuleArn": "rule-default", "Priority": "default", "IsDefault": True, "Conditions": [], "Actions": [
            {"Type": "forward", "TargetGroupArn": _group("web")}]},
    ]
    client = _Elbv2([alb], {alb["LoadBalancerArn"]: {"Listeners": [listener]}}, {listener["ListenerArn"]: {"Rules": rules}})
    return alb, listener, client


class TestRules:
    """Every rule of an Application listener is a node, its default rule among them (req-aws-collector-lb-topology-1)."""

    @pytest.mark.spec("req-aws-collector-lb-topology-1")
    def test_every_rule_is_a_node_with_its_priority_conditions_and_listener(self) -> None:
        alb, listener, client = _alb_with_rules()
        rules = {r["RuleArn"]: r for r in _run(elbv2_listener_rules_described, elbv2=client)}
        assert set(rules) == {"rule-api", "rule-old", "rule-default"}
        api = rules["rule-api"]
        assert (api["_listener_arn"], api["_load_balancer_arn"], api["Priority"], api["IsDefault"]) == (listener["ListenerArn"], alb["LoadBalancerArn"], "10", False)
        assert api["Conditions"] == [{"Field": "host-header", "HostHeaderConfig": {"Values": ["api.example.com"]}}]
        assert (rules["rule-default"]["IsDefault"], rules["rule-old"]["_action_types"]) == (True, ["redirect"])

    @pytest.mark.spec("req-aws-collector-lb-topology-1")
    def test_a_rule_forwards_to_each_group_with_only_the_weight_on_the_edge(self) -> None:
        _, _, client = _alb_with_rules()
        rules = {r["RuleArn"]: r for r in _run(elbv2_listener_rules_described, elbv2=client)}
        assert rules["rule-api"]["_forwards"] == [
            {"target_group_arn": _group("api-blue"), "properties": {"route_id": "rule-api", "weight": 90}},
            {"target_group_arn": _group("api-green"), "properties": {"route_id": "rule-api", "weight": 10}},
        ]
        assert rules["rule-default"]["_forwards"] == [{"target_group_arn": _group("web"), "properties": {"route_id": "rule-default", "weight": None}}]
        assert rules["rule-old"]["_forwards"] == []
        assert all(r[EDGE_READS]["_forwards"] == COMPLETE for r in rules.values())

    @pytest.mark.spec("req-aws-collector-lb-topology-1")
    def test_a_network_load_balancer_has_no_rules(self) -> None:
        nlb = _lb("net", "tcp")
        client = _Elbv2([nlb], {nlb["LoadBalancerArn"]: {"Listeners": [_listener(nlb, 443, "TCP")]}})
        assert _run(elbv2_listener_rules_described, elbv2=client) == []

    @pytest.mark.spec("req-aws-collector-lb-topology-1")
    def test_a_listener_whose_rules_could_not_be_listed_is_a_gap_after_the_rest_are_yielded(self) -> None:
        alb, listener, client = _alb_with_rules()
        second = _listener(alb, 80, "HTTP")
        client.listeners[alb["LoadBalancerArn"]] = {"Listeners": [listener, second]}
        client.rules[second["ListenerArn"]] = _denied("DescribeRules")
        yielded: list[dict[str, Any]] = []
        with pytest.raises(SourceError, match="whose rules"):
            for item in elbv2_listener_rules_described(None, client_for=lambda _s: client):
                yielded.append(item)
        assert {r["RuleArn"] for r in yielded} == {"rule-api", "rule-old", "rule-default"}


class TestListeners:
    """A listener evaluates its rules, or, with none, forwards straight to its groups (req-aws-collector-lb-topology-1)."""

    @pytest.mark.spec("req-aws-collector-lb-topology-1")
    def test_an_application_listener_evaluates_its_rules_and_forwards_nowhere_itself(self) -> None:
        alb, _, client = _alb_with_rules()
        [listener] = _run(elbv2_listeners_described, elbv2=client)
        assert listener["_rule_arns"] == ["rule-api", "rule-default", "rule-old"]
        assert (listener["_forwards"], listener["_alb_arn"], listener["_elb_dns_name"], listener["_lb_type"]) == ([], alb["LoadBalancerArn"], None, "application")
        assert (listener[EDGE_READS]["_rule_arns"], listener[EDGE_READS]["_forwards"]) == (COMPLETE, COMPLETE)

    @pytest.mark.spec("req-aws-collector-lb-topology-1")
    def test_a_network_listener_forwards_by_its_default_action(self) -> None:
        nlb = _lb("net", "tcp")
        listener = _listener(nlb, 443, "TCP", default_actions=[{"Type": "forward", "TargetGroupArn": _group("front-alb")}])
        client = _Elbv2([nlb], {nlb["LoadBalancerArn"]: {"Listeners": [listener]}})
        [item] = _run(elbv2_listeners_described, elbv2=client)
        assert item["_forwards"] == [{"target_group_arn": _group("front-alb"), "properties": {"route_id": listener["ListenerArn"], "weight": None}}]
        assert (item["_rule_arns"], item["_elb_dns_name"], item["_alb_arn"]) == ([], "tcp.elb.amazonaws.com", None)

    @pytest.mark.spec("req-aws-collector-lb-topology-1")
    def test_rules_that_could_not_be_listed_are_not_an_absence(self) -> None:
        alb, listener, client = _alb_with_rules()
        client.rules[listener["ListenerArn"]] = _denied("DescribeRules")
        [item] = _run(elbv2_listeners_described, elbv2=client)
        assert (item["_rule_arns"], item[EDGE_READS]["_rule_arns"]) == ([], FAILED)

    def test_a_load_balancer_whose_listeners_could_not_be_listed_is_a_gap(self) -> None:
        alb, _, client = _alb_with_rules()
        nlb = _lb("net", "tcp")
        client.lbs.append(nlb)
        client.listeners[nlb["LoadBalancerArn"]] = _denied("DescribeListeners")
        with pytest.raises(SourceError, match="whose listeners"):
            list(elbv2_listeners_described(None, client_for=lambda _s: client))


class TestWalk:
    def test_the_listener_and_rule_readers_share_one_walk_per_region(self) -> None:
        session = _Session()
        _, _, east = _alb_with_rules()
        west = _Elbv2([], region="us-west-2")
        _run(elbv2_listeners_described, session, elbv2=east)
        _run(elbv2_listener_rules_described, session, elbv2=east)
        _run(elbv2_listeners_described, session, elbv2=west)
        assert (east.lb_calls, west.lb_calls) == (1, 1)
        assert len(walks_of(session)) == 2

    def test_a_walk_that_raised_is_kept_and_not_retried(self) -> None:
        class _Denied(_Elbv2):
            def describe_load_balancers(self, **_: Any) -> Any:
                self.lb_calls += 1
                raise _denied("DescribeLoadBalancers")

        session, client = _Session(), _Denied([])
        for _ in range(2):
            with pytest.raises(ClientError):
                shared_walk(session, lambda _service: client)
        assert client.lb_calls == 1 and walks_of(session) == []


class TestWithholding:
    """A load balancer's replaced routes are claimed only once its listeners and rules reached the batch
    (req-aws-collector-lb-topology-3)."""

    def _judged(self, alb: dict[str, Any], nlb: dict[str, Any]) -> list[Any]:
        complete = dict.fromkeys(REPLACED_LB_SCOPES, COMPLETE)
        return [
            ({"entity": {"entity_type": ALB_TYPE}, "node": {"lb_arn": alb["LoadBalancerArn"]}}, dict(complete)),
            ({"entity": {"entity_type": ELB_TYPE}, "node": {"dns_name": nlb["DNSName"], "lb_type": "network"}}, dict(complete)),
            ({"entity": {"entity_type": ELB_TYPE}, "node": {"dns_name": "legacy.elb.amazonaws.com", "lb_type": "classic"}}, dict(complete)),
        ]

    @staticmethod
    def _reads(rows: list[Any]) -> list[str]:
        return [reads[REPLACED_LB_SCOPES[0]] for _envelope, reads in rows]

    @pytest.mark.spec("req-aws-collector-lb-topology-3")
    def test_replaced_routes_wait_for_both_readers_and_a_complete_read(self) -> None:
        alb, listener, client = _alb_with_rules()
        nlb = _lb("net", "tcp")
        client.lbs.append(nlb)
        walk = walk_listeners(client)
        # Neither reader has finished: nothing is claimed, except the Classic load balancer, whose routes are its own.
        rows = self._judged(alb, nlb)
        assert withhold_unreplaced_lb_routes(rows, [walk]) == 2
        assert self._reads(rows) == [FAILED, FAILED, COMPLETE]
        # The listener reader finished: the Network Load Balancer, which has no rules, is carried; the ALB waits.
        walk.listeners_projected = True
        rows = self._judged(alb, nlb)
        withhold_unreplaced_lb_routes(rows, [walk])
        assert self._reads(rows) == [FAILED, COMPLETE, COMPLETE]
        # Both finished: both are claimed.
        walk.rules_projected = True
        rows = self._judged(alb, nlb)
        assert withhold_unreplaced_lb_routes(rows, [walk]) == 0
        assert self._reads(rows) == [COMPLETE, COMPLETE, COMPLETE]

    @pytest.mark.spec("req-aws-collector-lb-topology-3")
    def test_a_rule_read_that_failed_keeps_the_load_balancers_old_routes(self) -> None:
        alb, listener, client = _alb_with_rules()
        client.rules[listener["ListenerArn"]] = _denied("DescribeRules")
        nlb = _lb("net", "tcp")
        walk = walk_listeners(client)
        walk.listeners_projected = walk.rules_projected = True
        rows = self._judged(alb, nlb)
        withhold_unreplaced_lb_routes(rows, [walk])
        # The ALB's rules were not read; the Network Load Balancer was never listed by this walk.
        assert self._reads(rows) == [FAILED, FAILED, COMPLETE]
        assert all(reads[scope] == FAILED for _e, reads in rows[:2] for scope in REPLACED_LB_SCOPES)

    def test_no_walk_claims_nothing(self) -> None:
        alb, nlb = _lb("app", "web"), _lb("net", "tcp")
        rows = self._judged(alb, nlb)
        withhold_unreplaced_lb_routes(rows, [])
        assert self._reads(rows) == [FAILED, FAILED, COMPLETE]


class _Classic:
    def __init__(self, lbs: list[dict[str, Any]]) -> None:
        self.lbs = lbs
        self.meta = _Meta("us-east-1")

    def can_paginate(self, method: str) -> bool:
        return False

    def describe_load_balancers(self, **_: Any) -> Any:
        return {"LoadBalancerDescriptions": self.lbs}


class _Sts:
    def __init__(self, account: str = "123456789012") -> None:
        self.account, self.calls = account, 0

    def get_caller_identity(self) -> Any:
        self.calls += 1
        return {"Account": self.account}


class TestClassicListeners:
    """A Classic load balancer's listeners are nodes too (req-aws-collector-lb-topology-9)."""

    def _legacy(self) -> dict[str, Any]:
        acm = "arn:aws:acm:us-east-1:123456789012:certificate/abc"
        return {
            "LoadBalancerName": "legacy",
            "DNSName": "legacy.elb.amazonaws.com",
            "ListenerDescriptions": [
                {"Listener": {"Protocol": "HTTP", "LoadBalancerPort": 80, "InstanceProtocol": "HTTP", "InstancePort": 8080}, "PolicyNames": []},
                {"Listener": {"Protocol": "HTTPS", "LoadBalancerPort": 443, "InstanceProtocol": "HTTP", "InstancePort": 8080, "SSLCertificateId": acm},
                 "PolicyNames": ["ELBSecurityPolicy-TLS-1-2-2017-01"]},
                {"Listener": {"Protocol": "SSL", "LoadBalancerPort": 8443, "InstanceProtocol": "TCP", "InstancePort": 8443,
                              "SSLCertificateId": "arn:aws:iam::123456789012:server-certificate/legacy"}, "PolicyNames": []},
            ],
        }

    @pytest.mark.spec("req-aws-collector-lb-topology-9")
    def test_each_listener_is_keyed_by_partition_account_region_load_balancer_protocol_and_port(self) -> None:
        sts = _Sts()
        items = {i["LoadBalancerPort"]: i for i in _run(elb_classic_listeners_described, elb=_Classic([self._legacy()]), sts=sts)}
        assert items[443]["_key"] == "aws:123456789012:us-east-1:legacy:HTTPS:443"
        assert items[443]["_key"] == classic_listener_key("aws", "123456789012", "us-east-1", "legacy", "https", 443)
        assert (items[443]["InstancePort"], items[443]["PolicyNames"], items[443]["_elb_dns_name"]) == (8080, ["ELBSecurityPolicy-TLS-1-2-2017-01"], "legacy.elb.amazonaws.com")
        assert sts.calls == 1

    @pytest.mark.spec("req-aws-collector-lb-topology-9")
    def test_only_an_acm_certificate_is_an_edge(self) -> None:
        items = {i["LoadBalancerPort"]: i for i in _run(elb_classic_listeners_described, elb=_Classic([self._legacy()]), sts=_Sts())}
        assert items[443]["_acm_certificate_arns"] == ["arn:aws:acm:us-east-1:123456789012:certificate/abc"]
        assert (items[80]["_acm_certificate_arns"], items[8443]["_acm_certificate_arns"]) == ([], [])
        assert items[8443]["SSLCertificateId"].endswith(":server-certificate/legacy")

    def test_no_classic_load_balancers_reads_no_account(self) -> None:
        sts = _Sts()
        assert _run(elb_classic_listeners_described, elb=_Classic([]), sts=sts) == []
        assert sts.calls == 0

    def test_an_unreadable_account_raises_rather_than_key_without_it(self) -> None:
        with pytest.raises(SourceError, match="account"):
            _run(elb_classic_listeners_described, elb=_Classic([self._legacy()]), sts=_Sts(account=""))
