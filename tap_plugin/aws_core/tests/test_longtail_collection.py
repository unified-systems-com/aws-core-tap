"""The readers for types whose list call does not carry the object's ARN (``customfns_longtail``): what each
lists, how each ARN is obtained, and what a failure costs. Fake clients, no network."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector.customfns import build_custom_fn_registry
from tap_plugin.aws_core.collectors.boto3_collector.customfns_longtail import (
    LONGTAIL_FNS,
    appconfig_extension_associations_described,
    codecommit_repositories_described,
    mailmanager_relays_described,
    opensearch_domains_described,
    rbin_rules_described,
    redshift_clusters_described,
    rekognition_collections_described,
    rekognition_stream_processors_described,
    securityhub_hub_v2_described,
    synthetics_canaries_described,
    xray_sampling_rules_described,
)
from tap_plugin.aws_core.collectors.boto3_collector.source import SourceError


def _denied(op: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, op)


class _Client:
    """A client whose methods are canned: a value, a callable taking the request, or an exception to raise."""

    def __init__(self, *, region: str = "us-east-1", **canned: Any) -> None:
        self._canned = canned
        self.meta = SimpleNamespace(region_name=region)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def can_paginate(self, method: str) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        def call(**kwargs: Any) -> Any:
            self.calls.append((name, kwargs))
            value = self._canned[name]
            if callable(value):
                value = value(**kwargs)
            if isinstance(value, Exception):
                raise value
            return value

        return call


def _factory(**clients: _Client) -> Any:
    sts = clients.setdefault("sts", _Client(get_caller_identity={"Account": "123456789012"}))
    assert sts is not None
    return lambda service: clients[service]


def _run(fn: Any, **clients: _Client) -> list[dict[str, Any]]:
    return list(fn(None, client_for=_factory(**clients)))


def _run_to_the_gap(fn: Any, **clients: _Client) -> tuple[list[dict[str, Any]], str]:
    yielded: list[dict[str, Any]] = []
    with pytest.raises(SourceError) as gap:
        for item in fn(None, client_for=_factory(**clients)):
            yielded.append(item)
    return yielded, str(gap.value)


def test_every_longtail_reader_is_registered() -> None:
    registry = build_custom_fn_registry()
    for name in LONGTAIL_FNS:
        assert callable(registry.get(name)), name


class TestListThenGet:
    def test_each_collection_is_described_and_keeps_its_id(self) -> None:
        client = _Client(
            list_collections={"CollectionIds": ["faces", "vault"], "FaceModelVersions": ["7.0", "7.0"]},
            describe_collection=lambda CollectionId: {
                "CollectionARN": f"arn:aws:rekognition:us-east-1:123456789012:collection/{CollectionId}",
                "FaceCount": 3,
                "ResponseMetadata": {"HTTPStatusCode": 200},
            },
        )
        items = _run(rekognition_collections_described, rekognition=client)
        assert [i["CollectionId"] for i in items] == ["faces", "vault"]
        assert items[0]["CollectionARN"].endswith("collection/faces")
        assert all("ResponseMetadata" not in i for i in items)

    def test_a_description_that_fails_is_a_gap_after_the_rest_are_yielded(self) -> None:
        def describe(Name: str) -> Any:
            if Name == "bad":
                return _denied("DescribeStreamProcessor")
            return {"Name": Name, "StreamProcessorArn": f"arn:aws:rekognition:us-east-1:123456789012:streamprocessor/{Name}"}

        client = _Client(
            list_stream_processors={"StreamProcessors": [{"Name": "good"}, {"Name": "bad"}]},
            describe_stream_processor=describe,
        )
        yielded, gap = _run_to_the_gap(rekognition_stream_processors_described, rekognition=client)
        assert [i["Name"] for i in yielded] == ["good"]
        assert "bad" in gap and "Rekognition stream processors" in gap

    def test_an_answer_without_the_arn_is_a_gap_not_a_node(self) -> None:
        client = _Client(
            list_extension_associations={"Items": [{"Id": "x1"}]},
            get_extension_association={"Id": "x1"},
        )
        yielded, gap = _run_to_the_gap(appconfig_extension_associations_described, appconfig=client)
        assert yielded == [] and "x1" in gap

    def test_a_relay_is_described_by_its_id(self) -> None:
        client = _Client(
            list_relays={"Relays": [{"RelayId": "r-1", "RelayName": "out"}]},
            get_relay=lambda RelayId: {"RelayId": RelayId, "RelayArn": f"arn:aws:ses:us-east-1:123456789012:mail-manager-relay/{RelayId}"},
        )
        [relay] = _run(mailmanager_relays_described, mailmanager=client)
        assert relay["RelayArn"].endswith("/r-1")
        assert client.calls[-1] == ("get_relay", {"RelayId": "r-1"})


class TestOpenSearch:
    def test_only_opensearch_engine_domains_are_listed_and_described(self) -> None:
        client = _Client(
            list_domain_names={"DomainNames": [{"DomainName": "logs", "EngineType": "OpenSearch"}]},
            describe_domain=lambda DomainName: {"DomainStatus": {"DomainName": DomainName, "ARN": f"arn:aws:es:us-east-1:123456789012:domain/{DomainName}"}},
        )
        [domain] = _run(opensearch_domains_described, opensearch=client)
        assert domain["ARN"].endswith("domain/logs")
        assert client.calls[0] == ("list_domain_names", {"EngineType": "OpenSearch"})

    def test_a_domain_that_cannot_be_described_is_a_gap(self) -> None:
        client = _Client(
            list_domain_names={"DomainNames": [{"DomainName": "a"}, {"DomainName": "b"}]},
            describe_domain=lambda DomainName: _denied("DescribeDomain") if DomainName == "b" else {"DomainStatus": {"DomainName": "a", "ARN": "arn:aws:es:us-east-1:123456789012:domain/a"}},
        )
        yielded, gap = _run_to_the_gap(opensearch_domains_described, opensearch=client)
        assert [d["DomainName"] for d in yielded] == ["a"] and "b" in gap


class TestBuiltArns:
    def test_a_redshift_cluster_gets_the_documented_arn(self) -> None:
        client = _Client(describe_clusters={"Clusters": [{"ClusterIdentifier": "t1", "Tags": [{"Key": "k", "Value": "v"}]}, {"NodeType": "no-id"}]})
        [cluster] = _run(redshift_clusters_described, redshift=client)
        assert cluster["_arn"] == "arn:aws:redshift:us-east-1:123456789012:cluster:t1"
        assert cluster["Tags"] == [{"Key": "k", "Value": "v"}]

    def test_a_govcloud_region_builds_a_govcloud_arn(self) -> None:
        client = _Client(region="us-gov-west-1", describe_canaries={"Canaries": [{"Name": "ping"}]})
        [canary] = _run(synthetics_canaries_described, synthetics=client)
        assert canary["_arn"] == "arn:aws-us-gov:synthetics:us-gov-west-1:123456789012:canary:ping"

    def test_no_account_id_fails_the_listing_instead_of_keying_by_a_hole(self) -> None:
        client = _Client(describe_clusters={"Clusters": [{"ClusterIdentifier": "t1"}]})
        sts = _Client(get_caller_identity={})
        with pytest.raises(SourceError, match="account id"):
            list(redshift_clusters_described(None, client_for=_factory(redshift=client, sts=sts)))


class TestCodeCommit:
    def test_names_are_described_in_batches_of_at_most_25(self) -> None:
        names = [f"repo-{n}" for n in range(26)]
        client = _Client(
            list_repositories={"repositories": [{"repositoryName": n, "repositoryId": f"id-{n}"} for n in names]},
            batch_get_repositories=lambda repositoryNames: {
                "repositories": [{"repositoryName": n, "Arn": f"arn:aws:codecommit:us-east-1:123456789012:{n}"} for n in repositoryNames]
            },
        )
        items = _run(codecommit_repositories_described, codecommit=client)
        assert len(items) == 26
        sizes = [len(kwargs["repositoryNames"]) for name, kwargs in client.calls if name == "batch_get_repositories"]
        assert sizes == [25, 1]

    def test_a_repository_that_is_not_returned_is_a_gap(self) -> None:
        client = _Client(
            list_repositories={"repositories": [{"repositoryName": "a"}, {"repositoryName": "b"}]},
            batch_get_repositories={"repositories": [{"repositoryName": "a", "Arn": "arn:aws:codecommit:us-east-1:123456789012:a"}], "repositoriesNotFound": ["b"]},
        )
        yielded, gap = _run_to_the_gap(codecommit_repositories_described, codecommit=client)
        assert [r["repositoryName"] for r in yielded] == ["a"] and "b" in gap


class TestUnwrapped:
    def test_rbin_is_asked_once_per_resource_type(self) -> None:
        client = _Client(
            list_rules=lambda ResourceType: {"Rules": [{"Identifier": ResourceType.lower(), "RuleArn": f"arn:aws:rbin:us-east-1:123456789012:rule/{ResourceType.lower()}"}]}
        )
        rules = _run(rbin_rules_described, rbin=client)
        assert {r["ResourceType"] for r in rules} == {"EBS_SNAPSHOT", "EC2_IMAGE", "EBS_VOLUME"}

    def test_the_rbin_resource_types_are_the_ones_botocore_defines(self) -> None:
        from botocore.session import get_session

        from tap_plugin.aws_core.collectors.boto3_collector import customfns_longtail

        enum = get_session().get_service_model("rbin").shape_for("ResourceType").enum
        assert set(customfns_longtail._RBIN_RESOURCE_TYPES) == set(enum)

    def test_a_sampling_rule_is_unwrapped_beside_its_timestamps(self) -> None:
        client = _Client(
            get_sampling_rules={
                "SamplingRuleRecords": [
                    {"SamplingRule": {"RuleName": "Default", "RuleARN": "arn:aws:xray:us-east-1:123456789012:sampling-rule/Default"}, "CreatedAt": "t1", "ModifiedAt": "t2"},
                    {"SamplingRule": {"RuleName": "no-arn"}},
                ]
            }
        )
        [rule] = _run(xray_sampling_rules_described, xray=client)
        assert rule["RuleName"] == "Default" and rule["CreatedAt"] == "t1"

    def test_the_security_hub_v2_resource_is_one_item(self) -> None:
        client = _Client(describe_security_hub_v2={"HubV2Arn": "arn:aws:securityhub:us-east-1:123456789012:hubv2/default", "SubscribedAt": "t"})
        [hub] = _run(securityhub_hub_v2_described, securityhub=client)
        assert hub["HubV2Arn"].endswith("hubv2/default")


class TestArnListings:
    def test_an_application_gets_the_documented_arn(self) -> None:
        client = _Client(list_applications={"Items": [{"Id": "abc1234", "Name": "web"}]})
        [app] = _run(LONGTAIL_FNS["appconfig_applications_described"], appconfig=client)
        assert app["_arn"] == "arn:aws:appconfig:us-east-1:123456789012:application/abc1234"

    def test_environments_are_asked_once_per_application(self) -> None:
        client = _Client(
            list_applications={"Items": [{"Id": "a1"}, {"Id": "a2"}]},
            list_environments=lambda ApplicationId: {"Items": [{"ApplicationId": ApplicationId, "Id": f"e-{ApplicationId}", "Name": "prod"}]},
        )
        envs = _run(LONGTAIL_FNS["appconfig_environments_described"], appconfig=client)
        assert [e["_arn"].rsplit(":", 1)[1] for e in envs] == ["application/a1/environment/e-a1", "application/a2/environment/e-a2"]

    def test_an_application_whose_environments_cannot_be_read_is_a_gap(self) -> None:
        def environments(ApplicationId: str) -> Any:
            return _denied("ListEnvironments") if ApplicationId == "a2" else {"Items": [{"ApplicationId": ApplicationId, "Id": "e"}]}

        client = _Client(list_applications={"Items": [{"Id": "a1"}, {"Id": "a2"}]}, list_environments=environments)
        yielded, gap = _run_to_the_gap(LONGTAIL_FNS["appconfig_environments_described"], appconfig=client)
        assert len(yielded) == 1 and "a2" in gap

    def test_bare_names_are_wrapped_and_the_ses_arn_service_is_ses(self) -> None:
        client = _Client(list_configuration_sets={"ConfigurationSets": ["default"]})
        [cs] = _run(LONGTAIL_FNS["ses_configuration_sets_described"], sesv2=client)
        assert cs["ConfigurationSetName"] == "default"
        assert cs["_arn"] == "arn:aws:ses:us-east-1:123456789012:configuration-set/default"

    def test_a_bot_alias_carries_its_bot_id_into_the_arn(self) -> None:
        client = _Client(
            list_bots={"botSummaries": [{"botId": "B1"}]},
            list_bot_aliases=lambda botId: {"botAliasSummaries": [{"botAliasId": "A1", "botAliasName": "live"}]},
        )
        [alias] = _run(LONGTAIL_FNS["lex_bot_aliases_described"], **{"lexv2-models": client})
        assert alias["_arn"] == "arn:aws:lex:us-east-1:123456789012:bot-alias/B1/A1" and alias["botId"] == "B1"

    def test_the_lag_account_comes_from_the_item_not_from_sts(self) -> None:
        client = _Client(describe_lags={"lags": [{"lagId": "dxlag-1", "ownerAccount": "999999999999"}]})
        sts = _Client(get_caller_identity=_denied("GetCallerIdentity"))
        [lag] = list(LONGTAIL_FNS["directconnect_lags_described"](None, client_for=_factory(directconnect=client, sts=sts)))
        assert lag["_arn"] == "arn:aws:directconnect:us-east-1:999999999999:dxlag/dxlag-1"

    def test_a_profile_association_gets_the_documented_arn(self) -> None:
        client = _Client(list_profile_associations={"ProfileAssociations": [{"Id": "rpassoc-1", "Name": "a"}]})
        [assoc] = _run(LONGTAIL_FNS["route53profiles_profile_associations_described"], route53profiles=client)
        assert assoc["_arn"] == "arn:aws:route53profiles:us-east-1:123456789012:profile-association/rpassoc-1"

    def test_s3_control_tags_are_read_with_the_account_and_ride_in_the_item(self) -> None:
        client = _Client(
            list_storage_lens_groups={"StorageLensGroupList": [{"Name": "g", "StorageLensGroupArn": "arn:aws:s3:us-east-1:123456789012:storage-lens-group/g"}]},
            list_tags_for_resource={"Tags": [{"Key": "owner", "Value": "net-team"}]},
        )
        [group] = _run(LONGTAIL_FNS["s3_storage_lens_groups_described"], s3control=client)
        assert group["_tags"] == {"owner": "net-team"} and group["_tags_unread"] is False
        assert client.calls[0] == ("list_storage_lens_groups", {"AccountId": "123456789012"})
        assert client.calls[1][1]["AccountId"] == "123456789012"

    def test_an_s3_control_tag_read_that_fails_is_marked_unread_not_empty(self) -> None:
        client = _Client(
            list_access_grants={"AccessGrantsList": [{"AccessGrantArn": "arn:aws:s3:us-east-1:123456789012:access-grants/default/grant/x"}]},
            list_tags_for_resource=_denied("ListTagsForResource"),
        )
        [grant] = _run(LONGTAIL_FNS["s3_access_grants_described"], s3control=client)
        assert grant["_tags"] == {} and grant["_tags_unread"] is True

    def test_an_item_missing_the_key_the_arn_needs_is_a_loud_gap(self) -> None:
        client = _Client(describe_cluster_subnet_groups={"ClusterSubnetGroups": [{"ClusterSubnetGroupName": "g"}, {"Description": "no name"}]})
        fn = LONGTAIL_FNS["redshift_subnet_groups_described"]
        seen: list[dict[str, Any]] = []
        with pytest.raises(SourceError, match="could not be described"):
            for item in fn(None, client_for=_factory(redshift=client)):
                seen.append(item)
        # what could be built is yielded first, so the engine keeps it and reports the gap
        assert [g["_arn"].rsplit(":", 1)[1] for g in seen] == ["g"]


def test_an_item_the_arn_cannot_be_built_for_is_a_loud_gap_not_an_absence() -> None:
    from tap_plugin.aws_core.collectors.boto3_collector.customfns_longtail import _arn_listing

    client = _Client(
        list_environments=lambda **kw: {
            "Items": [{"ApplicationId": "app1", "Id": "env1"}, {"Id": "env2"}]  # the second carries no ApplicationId
        },
        list_applications={"Items": [{"Id": "app1"}]},
    )
    seen: list[dict[str, Any]] = []
    with pytest.raises(SourceError, match="could not be described"):
        for item in _arn_listing(
            _factory(appconfig=client),
            "appconfig",
            "list_environments",
            "Items",
            "application/{ApplicationId}/environment/{Id}",
            label="AppConfig environments",
        ):
            seen.append(item)
    # the item that could be built was yielded before the gap was raised
    assert [i["_arn"] for i in seen] == ["arn:aws:appconfig:us-east-1:123456789012:application/app1/environment/env1"]
