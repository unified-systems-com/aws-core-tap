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


class TestKmsAliases:
    def test_the_target_key_arn_is_built_from_the_alias_arn(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import kms_aliases_described

        client = _Client(
            list_aliases={
                "Aliases": [
                    {"AliasName": "alias/app", "AliasArn": "arn:aws-us-gov:kms:us-gov-west-1:1:alias/app", "TargetKeyId": "k-1"},
                    {"AliasName": "alias/orphan", "AliasArn": "arn:aws:kms:us-east-1:1:alias/orphan"},
                ]
            }
        )
        app, orphan = _run(kms_aliases_described, "kms", client)
        assert app["_target_key_arn"] == "arn:aws-us-gov:kms:us-gov-west-1:1:key/k-1"
        assert orphan["_target_key_arn"] is None
        assert app[EDGE_READS] == {"_target_key_arn": COMPLETE}


class TestCloudTrailLake:
    ARN = "arn:aws:cloudtrail:us-east-1:1:eventdatastore/abc"

    def test_tags_come_from_list_tags_by_arn_in_batches(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import cloudtrail_event_data_stores_described

        seen: list[list[str]] = []

        def list_tags(ResourceIdList: list[str]) -> Any:
            seen.append(ResourceIdList)
            return {"ResourceTagList": [{"ResourceId": self.ARN, "TagsList": [{"Key": "team", "Value": "sec"}]}]}

        client = _Client(
            list_event_data_stores={"EventDataStores": [{"EventDataStoreArn": self.ARN, "Name": "audit"}]},
            list_tags=list_tags,
        )
        [item] = _run(cloudtrail_event_data_stores_described, "cloudtrail", client)
        assert (item["_name"], item["_tags"], item["_tags_unread"]) == ("audit", {"team": "sec"}, False)
        assert seen == [[self.ARN]]

    def test_a_denied_tag_read_is_unread_and_the_name_falls_back_to_the_arn_tail(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import cloudtrail_dashboards_described

        arn = "arn:aws:cloudtrail:us-east-1:1:dashboard/dash-1"
        client = _Client(list_dashboards={"Dashboards": [{"DashboardArn": arn, "Type": "CUSTOM"}]}, list_tags=_denied("ListTags"))
        [item] = _run(cloudtrail_dashboards_described, "cloudtrail", client)
        assert (item["_name"], item["_tags"], item["_tags_unread"]) == ("dash-1", {}, True)


class TestConfigOrganizationReaders:
    def _denied_org(self) -> ClientError:
        return ClientError({"Error": {"Code": "OrganizationAccessDeniedException", "Message": "not the admin"}}, "DescribeOrganizationConfigRules")

    def test_outside_the_organization_admin_account_there_is_nothing_to_list_and_no_error(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
            config_organization_conformance_packs_described,
            config_organization_rules_described,
        )

        assert _run(config_organization_rules_described, "config", _Client(describe_organization_config_rules=self._denied_org())) == []
        assert _run(config_organization_conformance_packs_described, "config", _Client(describe_organization_conformance_packs=self._denied_org())) == []

    def test_any_other_failure_is_not_swallowed(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import config_organization_rules_described

        with pytest.raises(ClientError):
            _run(config_organization_rules_described, "config", _Client(describe_organization_config_rules=_denied("DescribeOrganizationConfigRules")))

    def test_a_not_the_admin_error_after_a_page_was_yielded_is_a_failure_not_an_empty_end(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import config_organization_rules_described

        class _TwoPages(_Client):
            def can_paginate(self, method: str) -> bool:
                return True

            def get_paginator(self, method: str) -> Any:
                outer = self

                class _Paginator:
                    def paginate(self, **_: Any) -> Any:
                        yield {"OrganizationConfigRules": [{"OrganizationConfigRuleName": "r", "OrganizationConfigRuleArn": "arn"}]}
                        raise outer._canned["error"]

                return _Paginator()

        with pytest.raises(ClientError):
            _run(config_organization_rules_described, "config", _TwoPages(error=self._denied_org()))

    def test_rules_carry_a_json_safe_update_time(self) -> None:
        from datetime import UTC, datetime

        from tap_plugin.aws_core.collectors.boto3_collector.customfns import config_organization_rules_described

        client = _Client(
            describe_organization_config_rules={
                "OrganizationConfigRules": [
                    {"OrganizationConfigRuleName": "r", "OrganizationConfigRuleArn": "arn:aws:config:r:1:organization-config-rule/r", "LastUpdateTime": datetime(2026, 10, 1, tzinfo=UTC)}
                ]
            }
        )
        [item] = _run(config_organization_rules_described, "config", client)
        assert item["_last_update_time"] == "2026-10-01T00:00:00Z"


class TestIdentityCenter:
    INSTANCE = {"InstanceArn": "arn:aws:sso:::instance/ssoins-1", "IdentityStoreId": "d-1"}

    def _clients(self, **canned: Any) -> Any:
        sso = _Client(list_instances={"Instances": [self.INSTANCE]}, **{k: v for k, v in canned.items() if k.startswith("list_app")})
        store = _Client(**{k: v for k, v in canned.items() if k == "list_users"})
        return lambda service: {"sso-admin": sso, "identitystore": store}[service]

    def test_only_the_identifying_names_leave_the_user_reader(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import identity_center_users_described

        profile = {
            "UserId": "u-1",
            "UserName": "alice@example.com",
            "DisplayName": "Alice",
            "Emails": [{"Value": "alice@example.com"}],
            "PhoneNumbers": [{"Value": "+1 555 0100"}],
            "Addresses": [{"Locality": "Springfield"}],
            "Title": "SRE",
        }
        [user] = list(identity_center_users_described(None, client_for=self._clients(list_users={"Users": [profile]})))
        assert set(user) == {"IdentityStoreId", "UserId", "UserName", "DisplayName", "_key"}
        assert user["_key"] == "d-1:u-1"
        assert "555" not in str(user) and "Springfield" not in str(user)

    def test_an_identity_store_that_cannot_be_listed_is_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import identity_center_users_described

        client_for = self._clients(list_users=_denied("ListUsers"))
        with pytest.raises(SourceError) as gap:
            list(identity_center_users_described(None, client_for=client_for))
        assert "d-1" in str(gap.value)

    def test_applications_and_their_assignments(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
            identity_center_application_assignments_described,
            identity_center_applications_described,
        )

        app = "arn:aws:sso::1:application/ssoins-1/apl-1"
        client_for = self._clients(
            list_applications={"Applications": [{"ApplicationArn": app, "InstanceArn": self.INSTANCE["InstanceArn"], "Name": "wiki"}]},
            list_application_assignments={"ApplicationAssignments": [{"ApplicationArn": app, "PrincipalType": "USER", "PrincipalId": "u-1"}, {"ApplicationArn": app}]},
        )
        assert [a["Name"] for a in identity_center_applications_described(None, client_for=client_for)] == ["wiki"]
        [assignment] = list(identity_center_application_assignments_described(None, client_for=client_for))
        assert assignment["_key"] == f"{app}|USER|u-1"

    def test_an_application_whose_assignments_cannot_be_listed_is_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import identity_center_application_assignments_described

        app = "arn:aws:sso::1:application/ssoins-1/apl-1"
        client_for = self._clients(list_applications={"Applications": [{"ApplicationArn": app}]}, list_application_assignments=_denied("ListApplicationAssignments"))
        with pytest.raises(SourceError) as gap:
            list(identity_center_application_assignments_described(None, client_for=client_for))
        assert app in str(gap.value)


class TestAccessAnalyzerArchiveRules:
    ANALYZER = "arn:aws:access-analyzer:us-east-1:1:analyzer/acct"

    def test_a_rule_is_keyed_by_its_analyzer_and_name(self) -> None:
        from datetime import UTC, datetime

        from tap_plugin.aws_core.collectors.boto3_collector.customfns import access_analyzer_archive_rules_described

        client = _Client(
            list_analyzers={"analyzers": [{"name": "acct", "arn": self.ANALYZER}]},
            list_archive_rules={"archiveRules": [{"ruleName": "r1", "filter": {"a": {"eq": ["b"]}}, "updatedAt": datetime(2026, 10, 1, tzinfo=UTC)}]},
        )
        [rule] = _run(access_analyzer_archive_rules_described, "accessanalyzer", client)
        assert rule["_arn"] == f"{self.ANALYZER}/archive-rule/r1"
        assert (rule["_analyzer_arn"], rule["_updated_at"]) == (self.ANALYZER, "2026-10-01T00:00:00Z")

    def test_an_analyzer_whose_rules_cannot_be_listed_is_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import access_analyzer_archive_rules_described

        client = _Client(list_analyzers={"analyzers": [{"name": "acct", "arn": self.ANALYZER}]}, list_archive_rules=_denied("ListArchiveRules"))
        yielded, gap = _run_to_the_gap(access_analyzer_archive_rules_described, "accessanalyzer", client)
        assert yielded == [] and self.ANALYZER in gap


class TestSns:
    ARN = "arn:aws:sns:us-east-1:1:alerts"

    def test_a_topic_carries_its_typed_attributes_and_tags(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import sns_topics_described

        client = _Client(
            list_topics={"Topics": [{"TopicArn": self.ARN}]},
            get_topic_attributes={"Attributes": {"KmsMasterKeyId": "alias/aws/sns", "FifoTopic": "true", "SubscriptionsConfirmed": "3", "SubscriptionsPending": "x"}},
            list_tags_for_resource={"Tags": [{"Key": "team", "Value": "sec"}]},
        )
        [topic] = _run(sns_topics_described, "sns", client)
        assert topic["_name"] == "alerts" and topic["_kms_master_key_id"] == "alias/aws/sns" and topic["_fifo_topic"] is True
        assert (topic["_subscriptions_confirmed"], topic["_subscriptions_pending"]) == (3, None)
        assert (topic["_tags"], topic["_tags_unread"]) == ({"team": "sec"}, False)

    def test_a_denied_tag_read_is_unread_and_unreadable_attributes_are_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import sns_topics_described

        client = _Client(list_topics={"Topics": [{"TopicArn": self.ARN}]}, get_topic_attributes={"Attributes": {}}, list_tags_for_resource=_denied("ListTagsForResource"))
        [topic] = _run(sns_topics_described, "sns", client)
        assert (topic["_tags"], topic["_tags_unread"], topic["_fifo_topic"]) == ({}, True, None)
        blocked = _Client(list_topics={"Topics": [{"TopicArn": self.ARN}]}, get_topic_attributes=_denied("GetTopicAttributes"))
        yielded, gap = _run_to_the_gap(sns_topics_described, "sns", blocked)
        assert yielded == [] and self.ARN in gap

    def test_the_endpoint_never_leaves_and_unconfirmed_subscriptions_are_not_collected(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import sns_subscriptions_listed

        client = _Client(
            list_subscriptions={
                "Subscriptions": [
                    {"SubscriptionArn": self.ARN + ":1111", "TopicArn": self.ARN, "Protocol": "email", "Owner": "1", "Endpoint": "alice@example.com"},
                    {"SubscriptionArn": "PendingConfirmation", "TopicArn": self.ARN, "Protocol": "https", "Endpoint": "https://u:p@host"},
                ]
            }
        )
        [sub] = _run(sns_subscriptions_listed, "sns", client)
        assert "Endpoint" not in sub and "alice@example.com" not in str(sub) and sub["Protocol"] == "email"


class TestEventBridge:
    def test_a_listing_with_a_token_and_no_paginator_is_followed_to_its_end(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import eventbridge_event_buses_described

        seen: list[dict[str, Any]] = []

        def list_event_buses(**kwargs: Any) -> Any:
            seen.append(kwargs)
            if "NextToken" not in kwargs:
                return {"EventBuses": [{"Name": "a", "Arn": "arn:a"}], "NextToken": "t1"}
            return {"EventBuses": [{"Name": "b", "Arn": "arn:b"}]}

        buses = _run(eventbridge_event_buses_described, "events", _Client(list_event_buses=list_event_buses))
        assert [b["Name"] for b in buses] == ["a", "b"] and seen[1] == {"NextToken": "t1"}

    def test_an_archive_arn_is_built_from_its_bus_arn(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import eventbridge_archives_described

        client = _Client(list_archives={"Archives": [{"ArchiveName": "all", "EventSourceArn": "arn:aws-us-gov:events:us-gov-west-1:1:event-bus/default"}, {"ArchiveName": "odd", "EventSourceArn": "nope"}]})
        [archive] = _run(eventbridge_archives_described, "events", client)
        assert archive["_arn"] == "arn:aws-us-gov:events:us-gov-west-1:1:archive/all"


class TestApiDestinationUrls:
    def test_a_token_in_the_url_never_leaves_the_reader(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import eventbridge_api_destinations_described

        client = _Client(
            list_api_destinations={
                "ApiDestinations": [
                    {"Name": "a", "InvocationEndpoint": "https://user:pw@api.example.com:8443/hook/v1?token=SECRET&x=1#frag"},
                    {"Name": "b", "InvocationEndpoint": "https://api.example.com/plain"},
                ]
            }
        )
        a, b = _run(eventbridge_api_destinations_described, "events", client)
        assert a["InvocationEndpoint"] == "https://api.example.com:8443/hook/v1"
        assert "SECRET" not in str(a) and "pw" not in a["InvocationEndpoint"]
        assert b["InvocationEndpoint"] == "https://api.example.com/plain"


class TestLambdaSecurityTypes:
    def test_function_urls_are_listed_per_function_and_a_failed_function_is_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import lambda_function_urls_described

        def urls(FunctionName: str) -> Any:
            if FunctionName == "bad":
                return _denied("ListFunctionUrlConfigs")
            return {"FunctionUrlConfigs": [{"FunctionUrl": f"https://{FunctionName}.lambda-url.r.on.aws/", "FunctionArn": f"arn:{FunctionName}", "AuthType": "NONE", "Cors": {"AllowOrigins": ["*"]}}]}

        client = _Client(list_functions={"Functions": [{"FunctionName": "ok"}, {"FunctionName": "bad"}]}, list_function_url_configs=urls)
        yielded, gap = _run_to_the_gap(lambda_function_urls_described, "lambda", client)
        assert [u["_allow_origins"] for u in yielded] == [["*"]] and "bad" in gap

    def test_every_layer_version_is_taken_not_only_the_latest(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import lambda_layer_versions_described

        client = _Client(
            list_layers={"Layers": [{"LayerName": "deps", "LayerArn": "arn:aws:lambda:r:1:layer:deps"}]},
            list_layer_versions={"LayerVersions": [{"LayerVersionArn": "arn:aws:lambda:r:1:layer:deps:1", "Version": 1}, {"LayerVersionArn": "arn:aws:lambda:r:1:layer:deps:2", "Version": 2}]},
        )
        versions = _run(lambda_layer_versions_described, "lambda", client)
        assert [v["Version"] for v in versions] == [1, 2] and versions[0]["_layer_name"] == "deps"

    def test_a_mapping_without_an_arn_gets_one_built_from_its_function(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import lambda_event_source_mappings_described

        client = _Client(
            list_event_source_mappings={
                "EventSourceMappings": [
                    {"UUID": "u-1", "FunctionArn": "arn:aws:lambda:us-east-1:1:function:fn:live"},
                    {"UUID": "u-2", "FunctionArn": "arn:aws:lambda:us-east-1:1:function:fn", "EventSourceMappingArn": "arn:aws:lambda:us-east-1:1:event-source-mapping:u-2"},
                ]
            }
        )
        built, given = _run(lambda_event_source_mappings_described, "lambda", client)
        assert built["_arn"] == "arn:aws:lambda:us-east-1:1:event-source-mapping:u-1"
        assert given["_arn"] == "arn:aws:lambda:us-east-1:1:event-source-mapping:u-2"


class TestGuardDutyChildren:
    DET = "12abc34d567e8fa901bc2d34e56789f0"

    def _client(self, **canned: Any) -> Any:
        class _Gd(_Client):
            meta = type("Meta", (), {"region_name": "us-east-1"})()

        gd = _Gd(list_detectors={"DetectorIds": [self.DET]}, **canned)
        sts = _Client(get_caller_identity={"Account": "123456789012"})
        return lambda service: {"guardduty": gd, "sts": sts}[service]

    def test_a_filter_is_keyed_under_its_detector_and_points_at_the_detector_node(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import guardduty_filters_described

        client_for = self._client(list_filters={"FilterNames": ["known"]}, get_filter=lambda DetectorId, FilterName: {"Name": FilterName, "Action": "ARCHIVE", "Rank": 1})
        [item] = list(guardduty_filters_described(None, client_for=client_for))
        assert item["_key"] == f"{self.DET}/filter/known"
        assert item["_detector_key"] == f"123456789012:us-east-1:{self.DET}"
        assert item[EDGE_READS] == {"_detector_key": COMPLETE}

    def test_a_filter_that_cannot_be_described_is_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import guardduty_filters_described

        client_for = self._client(list_filters={"FilterNames": ["known"]}, get_filter=_denied("GetFilter"))
        with pytest.raises(SourceError) as gap:
            list(guardduty_filters_described(None, client_for=client_for))
        assert "known" in str(gap.value)

    def test_the_member_email_never_leaves_the_reader(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import guardduty_members_described

        client_for = self._client(list_members={"Members": [{"AccountId": "999988887777", "Email": "owner@example.com", "RelationshipStatus": "Enabled"}]})
        [member] = list(guardduty_members_described(None, client_for=client_for))
        assert "Email" not in member and "owner@example.com" not in str(member)
        assert member["_key"] == f"{self.DET}/member/999988887777"


class TestWafv2:
    def _client(self, region: str = "us-east-1", **canned: Any) -> Any:
        class _Waf(_Client):
            meta = type("Meta", (), {"region_name": region})()

        return _Waf(**canned)

    def test_the_cloudfront_scope_is_read_only_through_the_home_region_of_the_commercial_partition(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import wafv2_ip_sets_described

        def listing_into(seen: list[str]) -> Any:
            def listing(Scope: str) -> Any:
                seen.append(Scope)
                return {"IPSets": []}

            return listing

        scopes: dict[str, list[str]] = {}
        for region in ("us-east-1", "eu-west-1", "us-gov-west-1"):
            scopes[region] = []
            _run(wafv2_ip_sets_described, "wafv2", self._client(region, list_ip_sets=listing_into(scopes[region])))
        assert scopes == {"us-east-1": ["REGIONAL", "CLOUDFRONT"], "eu-west-1": ["REGIONAL"], "us-gov-west-1": ["REGIONAL"]}

    def test_a_web_acl_carries_default_action_rule_count_and_tags(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import wafv2_web_acls_described

        arn = "arn:aws:wafv2:eu-west-1:1:regional/webacl/a/i"
        client = self._client(
            "eu-west-1",
            list_web_acls={"WebACLs": [{"Name": "a", "Id": "i", "ARN": arn}]},
            get_web_acl={"WebACL": {"Name": "a", "Id": "i", "ARN": arn, "DefaultAction": {"Allow": {}}, "Rules": [{}, {}]}},
            list_tags_for_resource={"TagInfoForResource": {"TagList": [{"Key": "k", "Value": "v"}]}},
        )
        [acl] = _run(wafv2_web_acls_described, "wafv2", client)
        assert (acl["_default_action"], acl["_rule_count"], acl["Scope"]) == ("ALLOW", 2, "REGIONAL")
        assert (acl["_tags"], acl["_tags_unread"]) == ({"k": "v"}, False)

    def test_a_denied_tag_read_is_unread_and_an_undescribable_object_is_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import wafv2_ip_sets_described

        arn = "arn:aws:wafv2:eu-west-1:1:regional/ipset/a/i"
        listing = {"IPSets": [{"Name": "a", "Id": "i", "ARN": arn}]}
        ok = self._client("eu-west-1", list_ip_sets=listing, get_ip_set={"IPSet": {"Addresses": ["1.2.3.4/32"]}}, list_tags_for_resource=_denied("ListTagsForResource"))
        [ip_set] = _run(wafv2_ip_sets_described, "wafv2", ok)
        assert (ip_set["_tags"], ip_set["_tags_unread"], ip_set["_address_count"]) == ({}, True, 1)
        bad = self._client("eu-west-1", list_ip_sets=listing, get_ip_set=_denied("GetIPSet"))
        yielded, gap = _run_to_the_gap(wafv2_ip_sets_described, "wafv2", bad)
        assert yielded == [] and arn in gap


class TestS3AccessPoints:
    def test_status_account_and_bucket_arn_ride_with_the_item(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import s3_access_points_described

        class _S3c(_Client):
            meta = type("Meta", (), {"region_name": "us-gov-west-1"})()

        s3c = _S3c(
            list_access_points={"AccessPointList": [{"Name": "a", "Bucket": "data", "NetworkOrigin": "Internet"}, {"Name": "b", "Bucket": "data", "NetworkOrigin": "VPC", "VpcConfiguration": {"VpcId": "vpc-1"}}]},
            get_access_point_policy_status=lambda AccountId, Name: {"PolicyStatus": {"IsPublic": True}} if Name == "a" else _denied("GetAccessPointPolicyStatus"),
        )
        sts = _Client(get_caller_identity={"Account": "123456789012"})
        a, b = list(s3_access_points_described(None, client_for=lambda service: {"s3control": s3c, "sts": sts}[service]))
        assert (a["_is_public"], a["_account_id"], a["_bucket_arn"]) == (True, "123456789012", "arn:aws-us-gov:s3:::data")
        assert (b["_is_public"], b["_vpc_id"]) == (None, "vpc-1")


class TestEfs:
    def test_access_points_and_mount_targets_name_their_file_system_arn(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import efs_access_points_described, efs_mount_targets_described

        fs_arn = "arn:aws-us-gov:elasticfilesystem:us-gov-west-1:1:file-system/fs-1"
        efs = _Client(
            describe_access_points={"AccessPoints": [{"AccessPointId": "fsap-1", "AccessPointArn": "arn:aws-us-gov:elasticfilesystem:us-gov-west-1:1:access-point/fsap-1", "FileSystemId": "fs-1"}]},
            describe_file_systems={"FileSystems": [{"FileSystemId": "fs-1", "FileSystemArn": fs_arn}]},
            describe_mount_targets={"MountTargets": [{"MountTargetId": "fsmt-1", "FileSystemId": "fs-1", "SubnetId": "subnet-1"}]},
        )
        [ap] = _run(efs_access_points_described, "efs", efs)
        assert ap["_file_system_arn"] == fs_arn
        [mt] = _run(efs_mount_targets_described, "efs", efs)
        assert mt["_file_system_arn"] == fs_arn and mt[EDGE_READS]["SubnetId"] == COMPLETE

    def test_a_file_system_whose_mount_targets_cannot_be_listed_is_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import efs_mount_targets_described

        efs = _Client(describe_file_systems={"FileSystems": [{"FileSystemId": "fs-1"}]}, describe_mount_targets=_denied("DescribeMountTargets"))
        yielded, gap = _run_to_the_gap(efs_mount_targets_described, "efs", efs)
        assert yielded == [] and "fs-1" in gap


class TestListeners:
    LB = "arn:aws:elasticloadbalancing:us-east-1:1:loadbalancer/app/web/abc"

    def test_a_listener_carries_certificates_actions_and_an_alb_arn_only_for_an_alb(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import elbv2_listeners_described

        nlb = "arn:aws:elasticloadbalancing:us-east-1:1:loadbalancer/net/tcp/def"
        listeners = {self.LB: {"ListenerArn": "arn:l1", "LoadBalancerArn": self.LB, "Protocol": "HTTPS", "Certificates": [{"CertificateArn": "arn:aws:acm:r:1:certificate/a"}], "DefaultActions": [{"Type": "forward"}]}, nlb: {"ListenerArn": "arn:l2", "LoadBalancerArn": nlb}}
        client = _Client(
            describe_load_balancers={"LoadBalancers": [{"LoadBalancerArn": self.LB, "Type": "application"}, {"LoadBalancerArn": nlb, "Type": "network"}]},
            describe_listeners=lambda LoadBalancerArn: {"Listeners": [listeners[LoadBalancerArn]]},
            describe_listener_certificates={"Certificates": [{"CertificateArn": "arn:aws:acm:r:1:certificate/a", "IsDefault": True}, {"CertificateArn": "arn:aws:acm:r:1:certificate/sni", "IsDefault": False}]},
            describe_tags={"TagDescriptions": [{"ResourceArn": "arn:l1", "Tags": [{"Key": "k", "Value": "v"}]}, {"ResourceArn": "arn:l2", "Tags": []}]},
        )
        alb_listener, nlb_listener = _run(elbv2_listeners_described, "elbv2", client)
        assert alb_listener["_alb_arn"] == self.LB and nlb_listener["_alb_arn"] is None
        assert alb_listener["_certificate_arns"] == ["arn:aws:acm:r:1:certificate/a", "arn:aws:acm:r:1:certificate/sni"]
        assert alb_listener["_action_types"] == ["forward"]
        assert alb_listener["_tags"] == {"k": "v"}

    def test_unreadable_extra_certificates_make_the_certificate_read_partial_not_complete(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.authority import PARTIAL
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import elbv2_listeners_described

        client = _Client(
            describe_load_balancers={"LoadBalancers": [{"LoadBalancerArn": self.LB, "Type": "application"}]},
            describe_listeners={"Listeners": [{"ListenerArn": "arn:l1", "LoadBalancerArn": self.LB, "Protocol": "HTTPS", "Certificates": [{"CertificateArn": "arn:aws:acm:r:1:certificate/a"}]}]},
            describe_listener_certificates=_denied("DescribeListenerCertificates"),
            describe_tags={"TagDescriptions": []},
        )
        [listener] = _run(elbv2_listeners_described, "elbv2", client)
        assert listener["_certificate_arns"] == ["arn:aws:acm:r:1:certificate/a"]
        assert listener[EDGE_READS]["_certificate_arns"] == PARTIAL

    def test_a_load_balancer_whose_listeners_cannot_be_listed_is_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import elbv2_listeners_described

        client = _Client(describe_load_balancers={"LoadBalancers": [{"LoadBalancerArn": self.LB, "Type": "application"}]}, describe_listeners=_denied("DescribeListeners"), describe_tags={"TagDescriptions": []})
        yielded, gap = _run_to_the_gap(elbv2_listeners_described, "elbv2", client)
        assert yielded == [] and self.LB in gap


class TestBackup:
    def test_a_plan_names_its_target_vaults_and_a_vault_carries_tags(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import backup_plans_described, backup_vaults_described

        client = _Client(
            list_backup_plans={"BackupPlansList": [{"BackupPlanArn": "arn:aws:backup:us-east-1:1:backup-plan:p-1", "BackupPlanId": "p-1", "BackupPlanName": "daily"}]},
            get_backup_plan={"BackupPlan": {"Rules": [{"TargetBackupVaultName": "prod"}, {"TargetBackupVaultName": "prod"}, {"TargetBackupVaultName": "dr"}]}},
            list_tags={"Tags": {"owner": "x"}},
            list_backup_vaults={"BackupVaultList": [{"BackupVaultArn": "arn:aws:backup:us-east-1:1:backup-vault:prod", "BackupVaultName": "prod"}]},
        )
        [plan] = _run(backup_plans_described, "backup", client)
        assert plan["_rule_count"] == 3 and len(plan["BackupPlan"]["Rules"]) == 3
        assert plan["_target_vault_arns"] == ["arn:aws:backup:us-east-1:1:backup-vault:dr", "arn:aws:backup:us-east-1:1:backup-vault:prod"]
        [vault] = _run(backup_vaults_described, "backup", client)
        assert (vault["_tags"], vault["_tags_unread"]) == ({"owner": "x"}, False)

    def test_a_denied_tag_read_is_unread_and_an_unreadable_plan_is_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import backup_legal_holds_described, backup_plans_described

        holds = _Client(list_legal_holds={"LegalHolds": [{"LegalHoldArn": "arn:h", "Title": "t"}]}, list_tags=_denied("ListTags"))
        [hold] = _run(backup_legal_holds_described, "backup", holds)
        assert (hold["_tags"], hold["_tags_unread"]) == ({}, True)
        plans = _Client(list_backup_plans={"BackupPlansList": [{"BackupPlanArn": "arn:p", "BackupPlanId": "p-1"}]}, get_backup_plan=_denied("GetBackupPlan"))
        yielded, gap = _run_to_the_gap(backup_plans_described, "backup", plans)
        assert yielded == [] and "arn:p" in gap


class TestCognitoPoolChildren:
    POOL = "us-east-1_Abc123"

    def _client(self, **canned: Any) -> Any:
        return _Client(list_user_pools={"UserPools": [{"Id": self.POOL}]}, **canned)

    def test_the_client_secret_flag_is_derived_and_the_key_names_the_pool(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import cognito_user_pool_clients_described

        client = self._client(
            list_user_pool_clients={"UserPoolClients": [{"ClientId": "c1"}, {"ClientId": "c2"}]},
            describe_user_pool_client=lambda UserPoolId, ClientId: {"UserPoolClient": {"ClientId": ClientId, **({"ClientSecret": "s"} if ClientId == "c1" else {})}},
        )
        c1, c2 = _run(cognito_user_pool_clients_described, "cognito-idp", client)
        assert (c1["_key"], c1["_has_secret"], c2["_has_secret"]) == (f"{self.POOL}:c1", True, False)

    def test_a_pool_whose_clients_cannot_be_read_is_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import cognito_user_pool_clients_described

        client = self._client(list_user_pool_clients=_denied("ListUserPoolClients"))
        yielded, gap = _run_to_the_gap(cognito_user_pool_clients_described, "cognito-idp", client)
        assert yielded == [] and self.POOL in gap

    def test_groups_providers_servers_and_domains_are_keyed_by_pool(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
            cognito_identity_providers_described,
            cognito_user_pool_domains_described,
            cognito_user_pool_groups_described,
            cognito_user_pool_resource_servers_described,
        )

        client = self._client(
            list_groups={"Groups": [{"GroupName": "admins", "RoleArn": "arn:aws:iam::1:role/r"}]},
            list_identity_providers={"Providers": [{"ProviderName": "corp"}]},
            describe_identity_provider={"IdentityProvider": {"ProviderName": "corp", "ProviderType": "SAML"}},
            list_resource_servers={"ResourceServers": [{"Identifier": "https://api", "Name": "api"}]},
            describe_user_pool={"UserPool": {"Domain": "prefix", "CustomDomain": "auth.example.com"}},
            describe_user_pool_domain=lambda Domain: {"DomainDescription": {"Domain": Domain, "Status": "ACTIVE"}},
        )
        assert [g["_key"] for g in _run(cognito_user_pool_groups_described, "cognito-idp", client)] == [f"{self.POOL}:admins"]
        assert [i["_key"] for i in _run(cognito_identity_providers_described, "cognito-idp", client)] == [f"{self.POOL}:corp"]
        assert [r["_key"] for r in _run(cognito_user_pool_resource_servers_described, "cognito-idp", client)] == [f"{self.POOL}:https://api"]
        domains = _run(cognito_user_pool_domains_described, "cognito-idp", client)
        assert [d["_key"] for d in domains] == [f"{self.POOL}:auth.example.com", f"{self.POOL}:prefix"]
        assert all(d["UserPoolId"] == self.POOL for d in domains)

    def test_an_identity_pool_that_cannot_be_described_is_a_loud_gap(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import cognito_identity_pools_described

        client = _Client(list_identity_pools={"IdentityPools": [{"IdentityPoolId": "us-east-1:abc"}]}, describe_identity_pool=_denied("DescribeIdentityPool"))
        yielded, gap = _run_to_the_gap(cognito_identity_pools_described, "cognito-identity", client)
        assert yielded == [] and "us-east-1:abc" in gap
