"""ELBv2 listeners and rules: one walk per region, shared by the listener and rule readers (aws-core-tap#220).

A load balancer reaches a target group through a listener and, on an Application Load Balancer, one of the
listener's rules: load balancer -> listener (``LISTENS_ON_LOAD_BALANCER``, read from the listener) -> rule
(``EVALUATES_LISTENER_RULE``) -> target group (``FORWARDS_TO_TARGET_GROUP``). A Network or Gateway Load Balancer has
no rules, so its listener forwards straight to the group. The walk lists each load balancer's listeners, and each
Application listener's rules, once per region per run.

The load balancers' own ``FORWARDS_TO_TARGET_GROUP`` and ``ROUTES_TRAFFIC`` slots are the edges this path replaced.
They are claimed empty only for a load balancer whose listeners and rules were all read and whose readers yielded
every one of them, which is known only once every reader has run (:func:`withhold_unreplaced_lb_routes`).

Spec: ``specs/spec-aws-core-collector-v0.md`` (``req-aws-collector-lb-topology-1``, ``-3``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from weakref import WeakKeyDictionary

from botocore.exceptions import BotoCoreError, ClientError

from .authority import FAILED
from .batch import node_key
from .envelope import without_response_metadata

ALB_TYPE = "aws_core__aws_alb"
ELB_TYPE = "aws_core__aws_elb"
#: The load balancer's edges the listener and rule nodes replaced: one claim scope each.
REPLACED_LB_SCOPES = (("FORWARDS_TO_TARGET_GROUP__aws_core", "outbound"), ("ROUTES_TRAFFIC__aws_core", "outbound"))


def forward_targets(action: dict[str, Any]) -> list[tuple[str, int | None]]:
    """The target groups a ``forward`` action sends to, each with its weight (``None`` when the action names one
    group without a ``ForwardConfig``). Any other action type (redirect, fixed response, authenticate) forwards
    nowhere."""
    if action.get("Type") != "forward":
        return []
    groups = (action.get("ForwardConfig") or {}).get("TargetGroups") or []
    if groups:
        return [(str(g["TargetGroupArn"]), g.get("Weight")) for g in groups if g.get("TargetGroupArn")]
    return [(str(action["TargetGroupArn"]), None)] if action.get("TargetGroupArn") else []


def forwards(route_id: str, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ``FORWARDS_TO_TARGET_GROUP`` values of one rule's (or rule-less listener's) actions: one per target group,
    carrying only the route and the forward's weight. Everything else about the rule is on its node."""
    return [
        {"target_group_arn": arn, "properties": {"route_id": route_id, "weight": weight}}
        for action in actions
        for arn, weight in forward_targets(action)
    ]


@dataclass
class LoadBalancerListeners:
    """One load balancer's listeners and, for an Application Load Balancer, each listener's rules."""

    lb: dict[str, Any]
    listeners: list[dict[str, Any]] = field(default_factory=list)
    listeners_read: bool = False
    #: listener ARN -> its rules, for each Application listener whose ``DescribeRules`` answered.
    rules: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    #: Application listeners whose ``DescribeRules`` did not answer.
    rules_failed: set[str] = field(default_factory=set)

    @property
    def is_application(self) -> bool:
        return self.lb.get("Type") == "application"

    @property
    def read(self) -> bool:
        """Every listener, and every rule of an Application listener, was read."""
        return self.listeners_read and not self.rules_failed


@dataclass
class ListenerWalk:
    """One region's load balancers, their listeners and their rules, for the run's ELBv2 readers."""

    lbs: list[LoadBalancerListeners] = field(default_factory=list)
    #: The listener reader yielded every listener it read; the rule reader every rule. Until both have, no load
    #: balancer's replacement is known to have reached the batch.
    listeners_projected: bool = False
    rules_projected: bool = False

    def carried(self, lb: LoadBalancerListeners) -> bool:
        """The load balancer's listeners and rules were all read and all reached the batch."""
        return lb.read and self.listeners_projected and (self.rules_projected or not lb.is_application)


def _pages(client: Any, method: str, **kwargs: Any) -> list[dict[str, Any]]:
    if client.can_paginate(method):
        return [without_response_metadata(p) for p in client.get_paginator(method).paginate(**kwargs)]
    return [without_response_metadata(getattr(client, method)(**kwargs))]


def walk_listeners(client: Any) -> ListenerWalk:
    """List the region's load balancers, each one's listeners, and each Application listener's rules.

    A load balancer whose listeners cannot be listed, or an Application listener whose rules cannot, is kept with
    its read marked, so its readers report the gap and its replaced edges are never claimed. The load balancer
    listing itself failing raises, as every other source does.
    """
    walk = ListenerWalk()
    for page in _pages(client, "describe_load_balancers"):
        for lb in page.get("LoadBalancers", []):
            if not lb.get("LoadBalancerArn"):
                continue
            entry = LoadBalancerListeners(lb=lb)
            walk.lbs.append(entry)
            try:
                entry.listeners = [
                    listener
                    for listener_page in _pages(client, "describe_listeners", LoadBalancerArn=lb["LoadBalancerArn"])
                    for listener in listener_page.get("Listeners", [])
                    if listener.get("ListenerArn")
                ]
            except BotoCoreError, ClientError:
                continue
            entry.listeners_read = True
            if not entry.is_application:
                continue
            for listener in entry.listeners:
                arn = str(listener["ListenerArn"])
                try:
                    entry.rules[arn] = [r for rp in _pages(client, "describe_rules", ListenerArn=arn) for r in rp.get("Rules", []) if r.get("RuleArn")]
                except BotoCoreError, ClientError:
                    entry.rules_failed.add(arn)
    return walk


#: One walk per session and region: the listener and rule readers share one set of ELBv2 calls. A walk that raised
#: is kept too, so a denied ``DescribeLoadBalancers`` is not retried by the second reader.
_WALKS: WeakKeyDictionary[Any, dict[str, ListenerWalk | BaseException]] = WeakKeyDictionary()


def _region(client: Any) -> str:
    return str(getattr(getattr(client, "meta", None), "region_name", "") or "")


def shared_walk(session: Any, client_for: Any) -> ListenerWalk:
    """The run's :class:`ListenerWalk` for the region ``client_for`` is bound to, made once per session and region."""
    client = client_for("elbv2")
    region = _region(client)
    try:
        regions = _WALKS.setdefault(session, {}) if session is not None else None
    except TypeError:  # a session that cannot be weakly referenced: no sharing, still correct
        regions = None
    cached = regions.get(region) if regions is not None else None
    if isinstance(cached, BaseException):
        raise cached
    if cached is not None:
        return cached
    try:
        walk = walk_listeners(client)
    except (BotoCoreError, ClientError) as exc:
        if regions is not None:
            regions[region] = exc
        raise
    if regions is not None:
        regions[region] = walk
    return walk


def walks_of(session: Any) -> list[ListenerWalk]:
    """The run's completed walks, one per region read (none when no reader ran or every one raised)."""
    try:
        regions = _WALKS.get(session) or {}
    except TypeError:
        return []
    return [walk for walk in regions.values() if isinstance(walk, ListenerWalk)]


def withhold_unreplaced_lb_routes(judged: list[tuple[dict[str, Any], dict[tuple[str, str], str]]], walks: list[ListenerWalk]) -> int:
    """Mark a load balancer's replaced slots failed unless its listeners and rules reached the batch.

    Run once every reader has finished and before claims are made. An Application, Network or Gateway Load Balancer
    whose replacement was not carried keeps its old ``FORWARDS_TO_TARGET_GROUP`` and ``ROUTES_TRAFFIC`` edges rather
    than lose them with nothing in their place (as ``withhold_unreplaced_zone_routes`` does for zones). A Classic load
    balancer is left alone: its replacement is on its own item. Returns how many load balancers were withheld.
    """
    carried: set[str] = set()
    for walk in walks:
        for lb in walk.lbs:
            if walk.carried(lb):
                carried.update(str(v) for v in (lb.lb.get("LoadBalancerArn"), lb.lb.get("DNSName")) if v)
    withheld = 0
    for envelope, reads in judged:
        entity_type = envelope["entity"]["entity_type"]
        if entity_type not in (ALB_TYPE, ELB_TYPE) or not any(scope in reads for scope in REPLACED_LB_SCOPES):
            continue
        if entity_type == ELB_TYPE and envelope["node"].get("lb_type") == "classic":
            continue
        key = str(next(iter(node_key(envelope).values()), "") or "")
        if key in carried:
            continue
        if any(reads.get(scope, FAILED) != FAILED for scope in REPLACED_LB_SCOPES):
            withheld += 1
        for scope in REPLACED_LB_SCOPES:
            if scope in reads:
                reads[scope] = FAILED
    return withheld
