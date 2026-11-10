"""Unit tests for registered custom_fns (boto3-free, no DB).

Covers req-aws-collector-source: the route53_zones_with_alias_targets
cross-join — list CloudFront once, build domain->ARN, enrich each zone
with resolved alias_cloudfront_arns so ROUTES_TRAFFIC resolves by ARN
identity with no transform. Filters non-CloudFront aliases; keeps raw
domains lossless; resolves nothing it can't map (no bogus ARN).

Also covers aws_account_singleton (synthesizes the one aws_account node
from STS GetCallerIdentity + optional IAM account alias) and
cloudfront_distributions_with_oac (resolves and embeds each origin's
Origin Access Control config in the distribution's configuration).
"""

from __future__ import annotations

import json

import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    _bucket_size_metrics,
    aws_account_singleton,
    cloudfront_distributions_with_oac,
    route53_record_sets_described,
    route53_zones_with_alias_targets,
)
from tap_plugin.aws_core.collectors.boto3_collector.route53_records import walk_of

_CF_ARN = "arn:aws:cloudfront::111122223333:distribution/E1ABCDEF"
_CF_DOMAIN = "d111abcdef.cloudfront.net"


class _FakeCloudFront:
    def can_paginate(self, _m: str) -> bool:
        return False

    def list_distributions(self, **_kw):
        return {
            "DistributionList": {"Items": [{"ARN": _CF_ARN, "DomainName": _CF_DOMAIN}]},
            "ResponseMetadata": {"RequestId": "strip-me"},
        }


class _FakeRoute53:
    def __init__(self, record_sets):
        self._rrs = record_sets

    def can_paginate(self, _m: str) -> bool:
        return False

    def list_hosted_zones(self, **_kw):
        return {
            "HostedZones": [
                {
                    "Id": "/hostedzone/Z1SAMSITE",
                    "Name": "samsite.unified-systems.com.",
                    "Config": {"PrivateZone": False},
                    "ResourceRecordSetCount": 4,
                }
            ]
        }

    def list_resource_record_sets(self, **_kw):
        return {"ResourceRecordSets": self._rrs}


_ALB_ARN = "arn:aws:elasticloadbalancing:us-east-1:111122223333:loadbalancer/app/web/50dc6c495c0c9188"
_ALB_DNS = "web-123.us-east-1.elb.amazonaws.com"
_NLB_DNS = "net-456.elb.us-east-1.amazonaws.com"


class _FakeElbv2:
    def can_paginate(self, _m: str) -> bool:
        return False

    def describe_load_balancers(self, **_kw):
        return {
            "LoadBalancers": [
                {"LoadBalancerArn": _ALB_ARN, "DNSName": _ALB_DNS, "Type": "application"},
                {"LoadBalancerArn": "arn:aws:elasticloadbalancing:us-east-1:111122223333:loadbalancer/net/n/1", "DNSName": _NLB_DNS, "Type": "network"},
            ]
        }


_CLASSIC_DNS = "legacy-789.us-east-1.elb.amazonaws.com"


class _FakeClassicElb:
    def can_paginate(self, _m: str) -> bool:
        return False

    def describe_load_balancers(self, **_kw):
        return {"LoadBalancerDescriptions": [{"LoadBalancerName": "legacy", "DNSName": _CLASSIC_DNS}]}


class _FakeSession:
    def __init__(self, record_sets):
        self._rrs = record_sets

    def client(self, service: str, **_kw):
        if service == "cloudfront":
            return _FakeCloudFront()
        if service == "route53":
            return _FakeRoute53(self._rrs)
        if service == "elbv2":
            return _FakeElbv2()
        if service == "elb":
            return _FakeClassicElb()
        raise AssertionError(f"unexpected client {service!r}")


def _records(rrs, session=None):
    """The record set items for one zone holding ``rrs``, by name and type."""
    items = list(route53_record_sets_described(session or _FakeSession(rrs)))
    return {(i["Name"], i["Type"], i.get("SetIdentifier")): i for i in items}


def _keys(item, slot):
    return [t["key"] for t in item[slot]]


class TestRoute53RecordSets:
    """Every record set is a node, resolving through its alias or CNAME (req-aws-collector-lb-topology-5, -6)."""

    @pytest.mark.spec("req-aws-collector-lb-topology-5")
    def test_every_record_set_is_an_item_keyed_by_zone_name_type_and_set_identifier(self):
        rrs = [
            {"Name": "txt.samsite.unified-systems.com.", "Type": "TXT", "ResourceRecords": [{"Value": '"v=spf1"'}]},
            {"Name": "w.samsite.unified-systems.com.", "Type": "A", "SetIdentifier": "blue", "Weight": 90, "ResourceRecords": [{"Value": "10.0.0.1"}]},
        ]
        items = _records(rrs)
        txt = items[("txt.samsite.unified-systems.com.", "TXT", None)]
        assert txt["_record_set_key"] == "Z1SAMSITE/txt.samsite.unified-systems.com./TXT/"
        assert txt["_zone_id"] == "/hostedzone/Z1SAMSITE"
        assert all(txt[slot] == [] for slot in ("_resolves_alb", "_resolves_elb", "_resolves_cloudfront", "_resolves_record"))
        assert set(txt["_edge_reads"].values()) == {"complete"}
        weighted = items[("w.samsite.unified-systems.com.", "A", "blue")]
        assert weighted["_record_set_key"] == "Z1SAMSITE/w.samsite.unified-systems.com./A/blue"

    @pytest.mark.spec("req-aws-collector-lb-topology-6")
    def test_a_cloudfront_alias_resolves_to_its_arn_and_an_unmatched_alias_is_partial(self):
        rrs = [
            {"Name": "samsite.unified-systems.com.", "Type": "A", "AliasTarget": {"DNSName": f"{_CF_DOMAIN.upper()}.", "HostedZoneId": "Z2FDTNDATAQYW2", "EvaluateTargetHealth": False}},
            {"Name": "api.samsite.unified-systems.com.", "Type": "A", "AliasTarget": {"DNSName": "x.us-east-1.elb.amazonaws.com."}},
        ]
        items = _records(rrs)
        cf = items[("samsite.unified-systems.com.", "A", None)]
        assert cf["_resolves_cloudfront"] == [{"key": _CF_ARN, "properties": {"via": "alias", "evaluate_target_health": False}}]
        unmatched = items[("api.samsite.unified-systems.com.", "A", None)]
        assert unmatched["_resolves_alb"] == [] and unmatched["_resolves_elb"] == []
        assert unmatched["_edge_reads"]["_resolves_alb"] == "partial"

    @pytest.mark.spec("req-aws-collector-lb-topology-6")
    def test_an_alias_naming_a_region_the_partition_does_not_have_is_never_asked(self):
        class _Counting(_FakeSession):
            asked: list[str] = []

            def client(self, service: str, **kw):
                if service in ("elbv2", "elb"):
                    self.asked.append(kw.get("region_name", ""))
                return super().client(service, **kw)

        rrs = [{"Name": "x.", "Type": "A", "AliasTarget": {"DNSName": "web-1.xx-evil-9.elb.amazonaws.com."}}]
        session = _Counting(rrs)
        (item,) = _records(rrs, session).values()
        assert "xx-evil-9" not in session.asked
        assert item["_resolves_alb"] == [] and item["_edge_reads"]["_resolves_alb"] == "partial"

    @pytest.mark.spec("req-aws-collector-lb-topology-6")
    def test_load_balancer_aliases_resolve_to_the_alb_arn_and_the_nlb_and_classic_dns_names(self):
        rrs = [
            {"Name": "a.", "Type": "A", "AliasTarget": {"DNSName": f"dualstack.{_ALB_DNS.upper()}."}},
            {"Name": "b.", "Type": "A", "AliasTarget": {"DNSName": f"{_NLB_DNS}."}},
            {"Name": "c.", "Type": "A", "AliasTarget": {"DNSName": f"dualstack.{_CLASSIC_DNS}."}},
        ]
        items = _records(rrs)
        assert _keys(items[("a.", "A", None)], "_resolves_alb") == [_ALB_ARN]
        assert _keys(items[("b.", "A", None)], "_resolves_elb") == [_NLB_DNS]
        assert _keys(items[("c.", "A", None)], "_resolves_elb") == [_CLASSIC_DNS]
        assert items[("a.", "A", None)]["_edge_reads"]["_resolves_alb"] == "complete"

    @pytest.mark.spec("req-aws-collector-lb-topology-6")
    def test_a_cname_naming_a_load_balancer_resolves_via_cname(self):
        rrs = [{"Name": "app.", "Type": "CNAME", "TTL": 60, "ResourceRecords": [{"Value": _ALB_DNS}]}]
        (item,) = _records(rrs).values()
        assert item["_resolves_alb"] == [{"key": _ALB_ARN, "properties": {"via": "cname", "evaluate_target_health": None}}]

    @pytest.mark.spec("req-aws-collector-lb-topology-6")
    def test_an_alias_to_a_record_in_the_same_zone_resolves_to_that_record_set(self):
        rrs = [
            {"Name": "www.samsite.unified-systems.com.", "Type": "A", "AliasTarget": {"DNSName": "samsite.unified-systems.com.", "HostedZoneId": "Z1SAMSITE"}},
            {"Name": "samsite.unified-systems.com.", "Type": "A", "ResourceRecords": [{"Value": "10.0.0.1"}]},
        ]
        items = _records(rrs)
        www = items[("www.samsite.unified-systems.com.", "A", None)]
        assert _keys(www, "_resolves_record") == ["Z1SAMSITE/samsite.unified-systems.com./A/"]

    @pytest.mark.spec("req-aws-collector-lb-topology-6")
    def test_a_cname_to_a_name_in_the_same_zone_resolves_to_every_record_set_there(self):
        rrs = [
            {"Name": "www.samsite.unified-systems.com.", "Type": "CNAME", "ResourceRecords": [{"Value": "origin.samsite.unified-systems.com"}]},
            {"Name": "origin.samsite.unified-systems.com.", "Type": "A", "ResourceRecords": [{"Value": "10.0.0.1"}]},
            {"Name": "origin.samsite.unified-systems.com.", "Type": "AAAA", "ResourceRecords": [{"Value": "fd00::1"}]},
            {"Name": "gone.samsite.unified-systems.com.", "Type": "CNAME", "ResourceRecords": [{"Value": "nothing.samsite.unified-systems.com."}]},
        ]
        items = _records(rrs)
        www = items[("www.samsite.unified-systems.com.", "CNAME", None)]
        assert sorted(_keys(www, "_resolves_record")) == [
            "Z1SAMSITE/origin.samsite.unified-systems.com./A/",
            "Z1SAMSITE/origin.samsite.unified-systems.com./AAAA/",
        ]
        assert www["_resolves_record"][0]["properties"] == {"via": "cname", "evaluate_target_health": None}
        assert www["_edge_reads"]["_resolves_record"] == "complete"
        # A same-zone name with no record set is not "resolves to nothing": the read is partial.
        assert items[("gone.samsite.unified-systems.com.", "CNAME", None)]["_edge_reads"]["_resolves_record"] == "partial"

    @pytest.mark.spec("req-aws-collector-lb-topology-6")
    def test_a_denied_cloudfront_listing_leaves_its_aliases_partial_and_every_record_described(self):
        class _DeniedCloudFront(_FakeCloudFront):
            def list_distributions(self, **_kw):
                raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "ListDistributions")

        class _Session(_FakeSession):
            def client(self, service: str, **kw):
                return _DeniedCloudFront() if service == "cloudfront" else super().client(service, **kw)

        rrs = [
            {"Name": "samsite.unified-systems.com.", "Type": "A", "AliasTarget": {"DNSName": f"{_CF_DOMAIN}.", "HostedZoneId": "Z2FDTNDATAQYW2"}},
            {"Name": "txt.samsite.unified-systems.com.", "Type": "TXT", "ResourceRecords": [{"Value": '"x"'}]},
        ]
        items = _records(rrs, _Session(rrs))
        assert items[("samsite.unified-systems.com.", "A", None)]["_edge_reads"]["_resolves_cloudfront"] == "partial"
        assert set(items[("txt.samsite.unified-systems.com.", "TXT", None)]["_edge_reads"].values()) == {"complete"}

    @pytest.mark.spec("req-aws-collector-lb-topology-5")
    def test_the_walk_is_projected_only_once_every_record_set_was_yielded(self):
        rrs = [{"Name": "a.", "Type": "A"}, {"Name": "b.", "Type": "A"}]
        session = _FakeSession(rrs)
        reader = route53_record_sets_described(session)
        next(reader)
        walk = walk_of(session)
        assert walk is not None and walk.projected is False
        list(reader)
        assert walk.projected is True

    @pytest.mark.spec("req-aws-collector-lb-topology-6")
    def test_an_unmappable_cloudfront_domain_yields_no_arn(self):
        rrs = [{"Name": "s.", "Type": "A", "AliasTarget": {"DNSName": "dXXXXXXXXXXXXX.cloudfront.net."}}]
        (item,) = _records(rrs).values()
        assert item["_resolves_cloudfront"] == [] and item["_edge_reads"]["_resolves_cloudfront"] == "partial"

    @pytest.mark.spec("req-aws-collector-lb-topology-6")
    def test_the_zone_s_replaced_direct_routes_read_complete_and_empty(self):
        rrs = [{"Name": "s.", "Type": "A", "AliasTarget": {"DNSName": f"{_CF_DOMAIN}."}}]
        (zone,) = route53_zones_with_alias_targets(_FakeSession(rrs))
        assert zone["Id"] == "/hostedzone/Z1SAMSITE" and zone["_zone_resource_id"] == "Z1SAMSITE"
        assert (zone["alias_cloudfront_arns"], zone["alias_alb_arns"], zone["alias_elb_dns_names"]) == ([], [], [])
        assert set(zone["_edge_reads"].values()) == {"complete"}


# ---------------------------------------------------------------------------
# aws_account_singleton — synthesize the one aws_account node
# ---------------------------------------------------------------------------


class _FakeSts:
    def get_caller_identity(self, **_kw):
        return {
            "Account": "180731181784",
            "Arn": "arn:aws:iam::180731181784:computing_core__user/collector",
            "UserId": "AIDAEXAMPLE",
            "ResponseMetadata": {"RequestId": "strip-me"},
        }


class _FakeIam:
    def __init__(self, aliases=None, raise_error=False):
        self._aliases = aliases or []
        self._raise = raise_error

    def list_account_aliases(self, **_kw):
        if self._raise:
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "denied"}},
                "ListAccountAliases",
            )
        return {"AccountAliases": self._aliases, "ResponseMetadata": {"RequestId": "x"}}


class _FakeOrganizations:
    def __init__(self, account):
        self._account = account

    def describe_account(self, **_kw):
        if self._account is None:
            raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "DescribeAccount")
        return {"Account": self._account, "ResponseMetadata": {"RequestId": "x"}}


class _FakeAccountSession:
    def __init__(self, aliases=None, iam_raises=False, organization=None):
        self._aliases = aliases
        self._iam_raises = iam_raises
        self._organization = organization

    def client(self, service: str, **_kw):
        if service == "sts":
            return _FakeSts()
        if service == "iam":
            return _FakeIam(self._aliases, self._iam_raises)
        if service == "organizations":
            return _FakeOrganizations(self._organization)
        raise AssertionError(f"unexpected client {service!r}")


class TestAwsAccountSingleton:
    def test_yields_exactly_one_item_keyed_by_account(self):
        items = list(aws_account_singleton(_FakeAccountSession(aliases=["sbtf-tech"])))
        assert len(items) == 1
        # Account id is at "Account" — the manifest natural_key.
        assert items[0]["Account"] == "180731181784"
        # ResponseMetadata stripped.
        assert "ResponseMetadata" not in items[0]

    def test_alias_becomes_the_name(self):
        item = next(iter(aws_account_singleton(_FakeAccountSession(aliases=["sbtf-tech"]))))
        assert item["_account_name"] == "sbtf-tech"
        assert item["_account_aliases"] == ["sbtf-tech"]

    def test_name_falls_back_to_id_form_when_no_alias(self):
        item = next(iter(aws_account_singleton(_FakeAccountSession(aliases=[]))))
        assert item["_account_name"] == "AWS Account 180731181784"

    def test_email_and_status_are_unread_when_organizations_will_not_say(self):
        item = next(iter(aws_account_singleton(_FakeAccountSession(aliases=[]))))
        assert item["_email"] is None and item["_status"] is None

    def test_email_and_status_come_from_describe_account(self):
        org = {"Email": "owner@example.com", "State": "ACTIVE"}
        item = next(iter(aws_account_singleton(_FakeAccountSession(aliases=[], organization=org))))
        assert item["_email"] == "owner@example.com" and item["_status"] == "ACTIVE"

    def test_iam_failure_is_non_fatal_name_falls_back(self):
        # A denied/failed ListAccountAliases must not fail the account node —
        # the name just falls back to the id form.
        item = next(iter(aws_account_singleton(_FakeAccountSession(iam_raises=True))))
        assert item["_account_name"] == "AWS Account 180731181784"
        assert item["_account_aliases"] == []


# ---------------------------------------------------------------------------
# cloudfront_distributions_with_oac — embed each origin's OAC config
# ---------------------------------------------------------------------------

_OAC = {
    "Id": "EG8DXNRAHC015",
    "OriginAccessControlConfig": {
        "Name": "samsite-oac",
        "SigningProtocol": "sigv4",
        "SigningBehavior": "always",
        "OriginAccessControlOriginType": "s3",
    },
}


class _FakeCloudFrontOac:
    def __init__(self, distributions):
        self._distributions = distributions
        self.oac_calls: list[str] = []

    def can_paginate(self, _m: str) -> bool:
        return False

    def list_distributions(self, **_kw):
        return {
            "DistributionList": {"Items": self._distributions},
            "ResponseMetadata": {"RequestId": "strip-me"},
        }

    def get_origin_access_control(self, *, Id, **_kw):  # noqa: N803 — boto3 kwarg name
        self.oac_calls.append(Id)
        return {"OriginAccessControl": _OAC, "ResponseMetadata": {"RequestId": "x"}}


class _FakeOacSession:
    def __init__(self, distributions):
        self.cf = _FakeCloudFrontOac(distributions)

    def client(self, service: str, **_kw):
        if service == "cloudfront":
            return self.cf
        raise AssertionError(f"unexpected client {service!r}")


class TestCloudfrontDistributionsWithOac:
    def test_oac_resolved_and_embedded(self):
        dist = {
            "ARN": "arn:aws:cloudfront::111:distribution/E1",
            "DomainName": "d1.cloudfront.net",
            "Origins": {"Items": [{"Id": "s3-origin", "OriginAccessControlId": "EG8DXNRAHC015"}]},
        }
        items = list(cloudfront_distributions_with_oac(_FakeOacSession([dist])))
        assert len(items) == 1
        oacs = items[0]["_origin_access_controls"]
        assert set(oacs.keys()) == {"EG8DXNRAHC015"}
        cfg = oacs["EG8DXNRAHC015"]["OriginAccessControlConfig"]
        assert cfg["SigningProtocol"] == "sigv4"
        # Distribution identity/projection fields preserved verbatim.
        assert items[0]["ARN"] == "arn:aws:cloudfront::111:distribution/E1"

    def test_distribution_with_no_oac_yields_empty_map(self):
        dist = {
            "ARN": "arn:aws:cloudfront::111:distribution/E2",
            "DomainName": "d2.cloudfront.net",
            "Origins": {"Items": [{"Id": "custom-origin", "OriginAccessControlId": ""}]},
        }
        item = next(iter(cloudfront_distributions_with_oac(_FakeOacSession([dist]))))
        assert item["_origin_access_controls"] == {}

    def test_origin_access_mode_per_origin(self):
        # Each origin's access mode survives
        # configuration being off, read from the summary with no extra call.
        dist = {
            "ARN": "arn:aws:cloudfront::111:distribution/E3",
            "Origins": {
                "Items": [
                    {"Id": "oac-origin", "OriginAccessControlId": "EG8DXNRAHC015"},
                    {
                        "Id": "oai-origin",
                        "OriginAccessControlId": "",
                        "S3OriginConfig": {"OriginAccessIdentity": "origin-access-identity/cloudfront/E2QWRUHAPOMQZL"},
                    },
                    {
                        "Id": "open-s3-origin",
                        "OriginAccessControlId": "",
                        "S3OriginConfig": {"OriginAccessIdentity": ""},
                    },
                    {
                        # A shared-secret header is not OAC or OAI: still "none",
                        # which means "no OAC or OAI", not "public".
                        "Id": "alb-origin",
                        "CustomOriginConfig": {"OriginProtocolPolicy": "https-only"},
                        "CustomHeaders": {"Quantity": 1, "Items": [{"HeaderName": "X-Origin-Verify", "HeaderValue": "s"}]},
                    },
                ]
            },
        }
        item = next(iter(cloudfront_distributions_with_oac(_FakeOacSession([dist]))))
        assert item["_origin_access"] == {
            "oac-origin": "oac",
            "oai-origin": "oai",
            "open-s3-origin": "none",
            "alb-origin": "none",
        }

    def test_custom_header_presence_per_origin(self):
        # Presence only. An origin with a header is
        # True, one without (absent, empty, or Quantity 0) is False, and the
        # derived map carries neither the header value nor its name.
        dist = {
            "ARN": "arn:aws:cloudfront::111:distribution/E4",
            "Origins": {
                "Items": [
                    {
                        "Id": "verified-alb",
                        "CustomHeaders": {
                            "Quantity": 1,
                            "Items": [{"HeaderName": "X-Origin-Verify", "HeaderValue": "canary-unit-3e8b"}],
                        },
                    },
                    {"Id": "quantity-zero", "CustomHeaders": {"Quantity": 0}},
                    {"Id": "empty-items", "CustomHeaders": {"Quantity": 0, "Items": []}},
                    {"Id": "no-block"},
                ]
            },
        }
        item = next(iter(cloudfront_distributions_with_oac(_FakeOacSession([dist]))))
        presence = item["_origin_custom_headers_present"]
        assert presence == {
            "verified-alb": True,
            "quantity-zero": False,
            "empty-items": False,
            "no-block": False,
        }
        assert "canary-unit-3e8b" not in json.dumps(presence)
        assert "X-Origin-Verify" not in json.dumps(presence)

    def test_shared_oac_resolved_once(self):
        # Two distributions referencing the same OAC -> one GetOriginAccessControl
        # call (the oac_cache dedups across distributions).
        dists = [
            {
                "ARN": "arn:aws:cloudfront::111:distribution/E1",
                "Origins": {"Items": [{"OriginAccessControlId": "EG8DXNRAHC015"}]},
            },
            {
                "ARN": "arn:aws:cloudfront::111:distribution/E2",
                "Origins": {"Items": [{"OriginAccessControlId": "EG8DXNRAHC015"}]},
            },
        ]
        session = _FakeOacSession(dists)
        items = list(cloudfront_distributions_with_oac(session))
        assert len(items) == 2
        assert session.cf.oac_calls == ["EG8DXNRAHC015"]  # called exactly once


# ---------------------------------------------------------------------------
# _bucket_size_metrics — aggregate bucket size + object count from CloudWatch
# ---------------------------------------------------------------------------

from datetime import UTC, datetime  # noqa: E402

_TS_OLD = datetime(2026, 5, 19, tzinfo=UTC)
_TS_NEW = datetime(2026, 5, 20, tzinfo=UTC)


class _FakeCloudWatch:
    """Fake CloudWatch — returns the canned MetricDataResults for get_metric_data."""

    def __init__(self, results=None, raise_error=False):
        self._results = results if results is not None else []
        self._raise = raise_error
        self.last_queries = None

    def get_metric_data(self, *, MetricDataQueries, StartTime, EndTime, ScanBy=None):  # noqa: N803
        self.last_queries = MetricDataQueries
        if self._raise:
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "denied"}},
                "GetMetricData",
            )
        return {"MetricDataResults": self._results}


class TestBucketSizeMetrics:
    def test_object_count_and_single_tier_size(self):
        cw = _FakeCloudWatch(
            results=[
                {"Id": "objcount", "Values": [930.0], "Timestamps": [_TS_NEW]},
                {"Id": "size0", "Values": [1.0e8], "Timestamps": [_TS_NEW]},
            ]
        )
        m = _bucket_size_metrics(cw, "samsite-prod-1")
        assert m["object_count"] == 930
        assert m["size_bytes"] == 100_000_000
        assert m["size_observed_at"] == _TS_NEW.isoformat()

    def test_size_summed_across_storage_tiers(self):
        # A lifecycled bucket: Standard + Glacier tiers both report size.
        cw = _FakeCloudWatch(
            results=[
                {"Id": "objcount", "Values": [100.0], "Timestamps": [_TS_NEW]},
                {"Id": "size0", "Values": [1.0e9], "Timestamps": [_TS_NEW]},
                {"Id": "size6", "Values": [5.0e8], "Timestamps": [_TS_NEW]},
            ]
        )
        m = _bucket_size_metrics(cw, "lifecycled-bucket")
        assert m["size_bytes"] == 1_500_000_000  # both tiers summed
        assert m["object_count"] == 100

    def test_latest_timestamp_wins(self):
        # Datapoints from different days -> size_observed_at is the newest.
        cw = _FakeCloudWatch(
            results=[
                {"Id": "objcount", "Values": [5.0], "Timestamps": [_TS_OLD]},
                {"Id": "size0", "Values": [1.0e6], "Timestamps": [_TS_NEW]},
            ]
        )
        m = _bucket_size_metrics(cw, "b")
        assert m["size_observed_at"] == _TS_NEW.isoformat()

    def test_no_datapoints_is_unknown_not_zero(self):
        # A new/empty bucket with no CloudWatch data -> null fields, not 0.
        cw = _FakeCloudWatch(
            results=[
                {"Id": "objcount", "Values": [], "Timestamps": []},
                {"Id": "size0", "Values": [], "Timestamps": []},
            ]
        )
        m = _bucket_size_metrics(cw, "empty-bucket")
        assert m == {"size_bytes": None, "object_count": None, "size_observed_at": ""}

    def test_cloudwatch_failure_is_non_fatal(self):
        # A denied GetMetricData must not fail the bucket — empty/null result.
        cw = _FakeCloudWatch(raise_error=True)
        m = _bucket_size_metrics(cw, "b")
        assert m == {"size_bytes": None, "object_count": None, "size_observed_at": ""}

    def test_queries_cover_objects_and_every_size_tier(self):
        cw = _FakeCloudWatch(results=[])
        _bucket_size_metrics(cw, "b")
        ids = {q["Id"] for q in cw.last_queries}
        # One NumberOfObjects query + one BucketSizeBytes query per storage tier.
        assert "objcount" in ids
        assert sum(1 for i in ids if i.startswith("size")) >= 5


# ---------------------------------------------------------------------------
# eventbridge_rules_with_targets — resolve each rule's target ARNs
# ---------------------------------------------------------------------------

from tap_plugin.aws_core.collectors.boto3_collector.customfns import (  # noqa: E402
    eventbridge_rules_with_targets,
)

_LAMBDA_ARN = "arn:aws:lambda:us-east-2:180731181784:function:samsite-prod-1-opa-compliance"
_SQS_ARN = "arn:aws:sqs:us-east-2:180731181784:some-queue"


class _FakeEvents:
    def __init__(self, rules, targets_by_rule, targets_raise=False):
        self._rules = rules
        self._targets = targets_by_rule
        self._targets_raise = targets_raise

    def can_paginate(self, _m: str) -> bool:
        return False

    def list_rules(self, **_kw):
        return {"Rules": self._rules}

    def list_targets_by_rule(self, *, Rule, EventBusName, **_kw):  # noqa: N803
        if self._targets_raise:
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "denied"}},
                "ListTargetsByRule",
            )
        return {"Targets": self._targets.get(Rule, [])}


def _events_client_for(fake_events):
    def _cf(service: str):
        assert service == "events"
        return fake_events

    return _cf


class TestEventbridgeRulesWithTargets:
    def test_lambda_target_resolved(self):
        rule = {
            "Name": "samsite-prod-1-opa-compliance",
            "Arn": "arn:aws:events:us-east-2:180731181784:rule/samsite-prod-1-opa-compliance",
            "State": "ENABLED",
            "ScheduleExpression": "rate(1 day)",
            "EventBusName": "default",
        }
        events = _FakeEvents([rule], {"samsite-prod-1-opa-compliance": [{"Id": "t1", "Arn": _LAMBDA_ARN}]})
        items = list(eventbridge_rules_with_targets(None, client_for=_events_client_for(events)))
        assert len(items) == 1
        item = items[0]
        # Rule identity/projection fields preserved verbatim.
        assert item["Name"] == "samsite-prod-1-opa-compliance"
        assert item["ScheduleExpression"] == "rate(1 day)"
        # The Lambda target resolves into the edge-bearing key.
        assert item["_target_arns"] == [_LAMBDA_ARN]
        assert item["_lambda_target_arns"] == [_LAMBDA_ARN]

    def test_non_lambda_target_kept_lossless_but_not_edge_bearing(self):
        # An SQS target stays in _target_arns (lossless -> configuration) but
        # is filtered out of _lambda_target_arns so it produces no dangling
        # INVOKES_LAMBDA edge to a non-existent aws_lambda node.
        rule = {"Name": "r", "Arn": "arn:aws:events:us-east-2:1:rule/r", "EventBusName": "default"}
        events = _FakeEvents([rule], {"r": [{"Id": "t1", "Arn": _SQS_ARN}]})
        item = next(iter(eventbridge_rules_with_targets(None, client_for=_events_client_for(events))))
        assert item["_target_arns"] == [_SQS_ARN]
        assert item["_lambda_target_arns"] == []

    def test_mixed_targets_split(self):
        rule = {"Name": "r", "Arn": "arn:aws:events:us-east-2:1:rule/r", "EventBusName": "default"}
        events = _FakeEvents(
            [rule],
            {"r": [{"Id": "t1", "Arn": _LAMBDA_ARN}, {"Id": "t2", "Arn": _SQS_ARN}]},
        )
        item = next(iter(eventbridge_rules_with_targets(None, client_for=_events_client_for(events))))
        assert set(item["_target_arns"]) == {_LAMBDA_ARN, _SQS_ARN}
        assert item["_lambda_target_arns"] == [_LAMBDA_ARN]

    def test_list_targets_failure_is_non_fatal(self):
        # A denied ListTargetsByRule must not fail the rule — it still
        # collects, just with no resolved targets.
        rule = {"Name": "r", "Arn": "arn:aws:events:us-east-2:1:rule/r", "EventBusName": "default"}
        events = _FakeEvents([rule], {}, targets_raise=True)
        item = next(iter(eventbridge_rules_with_targets(None, client_for=_events_client_for(events))))
        assert item["Name"] == "r"
        assert item["_target_arns"] == []
        assert item["_lambda_target_arns"] == []
