"""The readers for EKS, Elasticsearch and Network Firewall: what each lists, what a description that fails
costs, and what an edge read declares. Fake clients, no network."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector.authority import COMPLETE, EDGE_READS
from tap_plugin.aws_core.collectors.boto3_collector.source import SourceError
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    eks_clusters_described,
    elasticsearch_domains_described,
    network_firewalls_described,
)


def _denied(op: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, op)


class _Client:
    def __init__(self, **canned: Any) -> None:
        self._canned = canned

    def can_paginate(self, method: str) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        def call(**kwargs: Any) -> Any:
            value = self._canned[name]
            if callable(value):
                value = value(**kwargs)
            if isinstance(value, Exception):
                raise value
            return value

        return call


def _run(fn: Any, service: str, client: _Client) -> list[dict[str, Any]]:
    return list(fn(None, client_for=lambda requested: client if requested == service else None))


def _run_to_the_gap(fn: Any, service: str, client: _Client) -> tuple[list[dict[str, Any]], str]:
    """What the reader yielded, and the gap it raised after yielding it (the engine keeps the former and
    reports the latter as ENTRY_SKIPPED)."""
    yielded: list[dict[str, Any]] = []
    with pytest.raises(SourceError) as gap:
        for item in fn(None, client_for=lambda requested: client if requested == service else None):
            yielded.append(item)
    return yielded, str(gap.value)


class TestEks:
    def test_each_cluster_is_described_and_declares_its_subnet_read(self) -> None:
        client = _Client(
            list_clusters={"clusters": ["a", "b"]},
            describe_cluster=lambda name: {"cluster": {"name": name, "arn": f"arn:aws:eks:us-east-1:1:cluster/{name}"}},
        )
        items = _run(eks_clusters_described, "eks", client)
        assert [i["name"] for i in items] == ["a", "b"]
        assert items[0][EDGE_READS] == {"resourcesVpcConfig": COMPLETE}

    def test_a_cluster_that_cannot_be_described_is_a_loud_gap_and_the_rest_are_kept(self) -> None:
        def describe(name: str) -> Any:
            return _denied("DescribeCluster") if name == "a" else {"cluster": {"name": name, "arn": "arn:aws:eks::1:c/b"}}

        client = _Client(list_clusters={"clusters": ["a", "b"]}, describe_cluster=describe)
        yielded, gap = _run_to_the_gap(eks_clusters_described, "eks", client)
        assert [i["name"] for i in yielded] == ["b"]
        assert gap.startswith("1 EKS clusters could not be described") and "a" in gap


class TestElasticsearch:
    def test_each_domain_status_is_the_item(self) -> None:
        client = _Client(
            list_domain_names={"DomainNames": [{"DomainName": "logs"}]},
            describe_elasticsearch_domain=lambda DomainName: {
                "DomainStatus": {"DomainName": DomainName, "ARN": "arn:aws:es:us-east-1:1:domain/logs"}
            },
        )
        [item] = _run(elasticsearch_domains_described, "es", client)
        assert item["DomainName"] == "logs" and item[EDGE_READS] == {"VPCOptions": COMPLETE}

    def test_a_domain_that_cannot_be_described_is_a_loud_gap(self) -> None:
        client = _Client(
            list_domain_names={"DomainNames": [{"DomainName": "logs"}]},
            describe_elasticsearch_domain=_denied("DescribeElasticsearchDomain"),
        )
        yielded, gap = _run_to_the_gap(elasticsearch_domains_described, "es", client)
        assert yielded == [] and "logs" in gap


class TestNetworkFirewall:
    def test_the_status_and_inline_tags_ride_with_the_firewall(self) -> None:
        arn = "arn:aws:network-firewall:us-east-1:1:firewall/edge"
        client = _Client(
            list_firewalls={"Firewalls": [{"FirewallName": "edge", "FirewallArn": arn}]},
            describe_firewall={
                "Firewall": {"FirewallName": "edge", "FirewallArn": arn, "Tags": [{"Key": "k", "Value": "v"}]},
                "FirewallStatus": {"Status": "READY"},
            },
        )
        [item] = _run(network_firewalls_described, "network-firewall", client)
        assert (item["_status"], item["Tags"]) == ("READY", [{"Key": "k", "Value": "v"}])
        assert item[EDGE_READS] == {"SubnetMappings": COMPLETE}

    def test_a_firewall_that_cannot_be_described_is_a_loud_gap(self) -> None:
        arn = "arn:aws:network-firewall:us-east-1:1:firewall/edge"
        client = _Client(
            list_firewalls={"Firewalls": [{"FirewallArn": arn}]}, describe_firewall=_denied("DescribeFirewall")
        )
        yielded, gap = _run_to_the_gap(network_firewalls_described, "network-firewall", client)
        assert yielded == [] and arn in gap
