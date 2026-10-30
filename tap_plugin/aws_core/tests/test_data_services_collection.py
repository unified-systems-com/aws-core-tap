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


class TestDirectConnectGateways:
    OWNER = "123456789012"

    def _client(self, **kw: Any) -> Any:
        class _Dx(_Client):
            meta = type("Meta", (), {"region_name": "us-east-1"})()

        return _Dx(**kw)

    def test_the_arn_is_built_from_the_owner_and_tags_are_read_by_it(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import dx_gateways_described

        arn = f"arn:aws:directconnect::{self.OWNER}:dx-gateway/gw-1"
        seen: list[Any] = []

        def describe_tags(resourceArns: list[str]) -> Any:
            seen.append(resourceArns)
            return {"resourceTags": [{"resourceArn": arn, "tags": [{"key": "team", "value": "net"}]}]}

        client = self._client(
            describe_direct_connect_gateways={
                "directConnectGateways": [
                    {"directConnectGatewayId": "gw-1", "directConnectGatewayName": "hub", "ownerAccount": self.OWNER}
                ]
            },
            describe_tags=describe_tags,
        )
        [item] = _run(dx_gateways_described, "directconnect", client)
        assert (item["_arn"], item["_tags"], item["_tags_unread"]) == (arn, {"team": "net"}, False)
        assert seen == [[arn]]

    def test_a_denied_tag_batch_leaves_the_tags_unread(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import dx_gateways_described

        client = self._client(
            describe_direct_connect_gateways={
                "directConnectGateways": [
                    {"directConnectGatewayId": "gw-1", "directConnectGatewayName": "hub", "ownerAccount": self.OWNER}
                ]
            },
            describe_tags=_denied("DescribeTags"),
        )
        [item] = _run(dx_gateways_described, "directconnect", client)
        assert (item["_tags"], item["_tags_unread"]) == ({}, True)

    def test_a_gateway_with_no_owner_has_no_arn_and_is_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import dx_gateways_described

        client = self._client(
            describe_direct_connect_gateways={"directConnectGateways": [{"directConnectGatewayId": "gw-1"}]},
            describe_tags={"resourceTags": []},
        )
        yielded, gap = _run_to_the_gap(dx_gateways_described, "directconnect", client)
        assert yielded == [] and "gw-1" in gap


class TestTransitGateways:
    def test_options_become_booleans_and_an_absent_option_stays_unknown(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import transit_gateways_described

        client = _Client(
            describe_transit_gateways={
                "TransitGateways": [
                    {
                        "TransitGatewayId": "tgw-1",
                        "Options": {"AutoAcceptSharedAttachments": "enable", "DefaultRouteTableAssociation": "disable"},
                    }
                ]
            }
        )
        [item] = _run(transit_gateways_described, "ec2", client)
        assert item["_auto_accept_shared_attachments"] is True
        assert item["_default_route_table_association"] is False
        assert item["_default_route_table_propagation"] is None

    def test_attachments_carry_the_resource_id_only_under_the_type_it_is(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import transit_gateway_attachments_described

        def attachment(kind: str, ident: str) -> dict[str, Any]:
            return {"TransitGatewayAttachmentId": f"tgw-attach-{kind}", "TransitGatewayId": "tgw-1", "ResourceType": kind, "ResourceId": ident}

        client = _Client(
            describe_transit_gateway_attachments={
                "TransitGatewayAttachments": [
                    attachment("vpc", "vpc-1"),
                    attachment("direct-connect-gateway", "dxgw-1"),
                    attachment("peering", "tgw-peer"),
                    attachment("vpn", "vpn-1"),
                ]
            }
        )
        by_kind = {i["ResourceType"]: i for i in _run(transit_gateway_attachments_described, "ec2", client)}
        slots = ("_vpc_id", "_dx_gateway_id", "_peer_transit_gateway_id")
        assert [by_kind["vpc"][k] for k in slots] == ["vpc-1", None, None]
        assert [by_kind["direct-connect-gateway"][k] for k in slots] == [None, "dxgw-1", None]
        assert [by_kind["peering"][k] for k in slots] == [None, None, "tgw-peer"]
        assert [by_kind["vpn"][k] for k in slots] == [None, None, None]
        assert by_kind["vpc"][EDGE_READS]["_vpc_id"] == COMPLETE


class TestCodeBuild:
    def test_projects_are_fetched_a_hundred_to_a_call_and_a_missing_one_is_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import codebuild_projects_described

        names = [f"p{i}" for i in range(150)]
        batches: list[int] = []

        def batch_get(names: list[str]) -> Any:
            batches.append(len(names))
            return {"projects": [{"name": n, "arn": f"arn:aws:codebuild:r:1:project/{n}", "vpcConfig": {"vpcId": "vpc-1"} if n == "p0" else {}} for n in names if n != "p120"]}

        client = _Client(list_projects={"projects": names}, batch_get_projects=batch_get)
        yielded, gap = _run_to_the_gap(codebuild_projects_described, "codebuild", client)
        assert batches == [100, 50]
        assert len(yielded) == 149 and "p120" in gap
        assert next(i for i in yielded if i["name"] == "p0")["_vpc_attached"] is True
        assert next(i for i in yielded if i["name"] == "p1")["_vpc_attached"] is False


class TestCodePipeline:
    ARN = "arn:aws:codepipeline:us-east-1:123456789012:release"

    def _pipeline(self) -> dict[str, Any]:
        return {
            "pipeline": {
                "name": "release",
                "roleArn": "arn:aws:iam::123456789012:role/release",
                "stages": [
                    {
                        "name": "Source",
                        "actions": [
                            {"actionTypeId": {"category": "Source", "provider": "S3"}, "configuration": {"S3Bucket": "src"}},
                            {"actionTypeId": {"category": "Source", "provider": "GitHub"}, "configuration": {"Repo": "x"}},
                        ],
                    },
                    {
                        "name": "Build",
                        "actions": [{"actionTypeId": {"category": "Build", "provider": "CodeBuild"}, "configuration": {"ProjectName": "build"}}],
                    },
                ],
            },
            "metadata": {"pipelineArn": self.ARN},
        }

    def test_the_arn_stages_builds_and_source_buckets_are_derived_from_the_one_answer(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import codepipeline_pipelines_described

        client = _Client(
            list_pipelines={"pipelines": [{"name": "release"}]},
            get_pipeline=self._pipeline(),
            list_tags_for_resource={"tags": [{"key": "owner", "value": "ci"}]},
        )
        [item] = _run(codepipeline_pipelines_described, "codepipeline", client)
        assert item["_arn"] == self.ARN and item["_stage_names"] == ["Source", "Build"]
        assert item["_codebuild_project_arns"] == ["arn:aws:codebuild:us-east-1:123456789012:project/build"]
        assert item["_s3_source_bucket_arns"] == ["arn:aws:s3:::src"]
        assert (item["_tags"], item["_tags_unread"]) == ({"owner": "ci"}, False)
        assert item[EDGE_READS]["_codebuild_project_arns"] == COMPLETE

    def test_a_denied_tag_read_is_unread_and_the_pipeline_is_still_collected(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import codepipeline_pipelines_described

        client = _Client(
            list_pipelines={"pipelines": [{"name": "release"}]},
            get_pipeline=self._pipeline(),
            list_tags_for_resource=_denied("ListTagsForResource"),
        )
        [item] = _run(codepipeline_pipelines_described, "codepipeline", client)
        assert (item["_tags"], item["_tags_unread"]) == ({}, True)

    def test_a_pipeline_that_cannot_be_described_is_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import codepipeline_pipelines_described

        client = _Client(list_pipelines={"pipelines": [{"name": "release"}]}, get_pipeline=_denied("GetPipeline"))
        yielded, gap = _run_to_the_gap(codepipeline_pipelines_described, "codepipeline", client)
        assert yielded == [] and "release" in gap
