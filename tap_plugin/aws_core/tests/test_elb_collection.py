"""The load balancer readers (``elbv2_albs_described``, ``elb_family_described``,
``elbv2_target_groups_described``): which load balancers each takes, how tags are read, and what a failed
tag read does. Fake ELB clients, no network."""

from __future__ import annotations

from typing import Any

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
        return self._answers["groups"]

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
        assert alb[EDGE_READS] == {"_subnet_ids": COMPLETE}
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
