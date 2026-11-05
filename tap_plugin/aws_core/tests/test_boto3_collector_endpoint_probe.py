"""The endpoint probe (req-aws-collector-partition-13): a detector for the manifest's "not offered" claims."""

from __future__ import annotations

import socket

import pytest
from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
from tap_plugin.aws_core.collectors.boto3_collector import endpoint_probe
from tap_plugin.aws_core.collectors.boto3_collector.endpoint_probe import EndpointProbe
from tap_plugin.aws_core.tests import test_boto3_collector_selection_run as base


class _Resolver:
    """A resolver that knows which hosts have no record, and counts its lookups."""

    def __init__(self, missing=()):
        self.missing = set(missing)
        self.lookups: list[str] = []

    def __call__(self, host, port):
        self.lookups.append(host)
        if host in self.missing:
            raise socket.gaierror(-2, "Name or service not known")
        return [("family", "type", 0, "", (host, port))]


class TestEndpointProbe:
    @pytest.mark.spec("req-aws-collector-partition-13")
    def test_a_host_with_no_record_does_not_resolve_and_one_with_a_record_does(self, monkeypatch):
        monkeypatch.setattr(endpoint_probe, "RESOLVE", _Resolver(missing={"gone.example"}))
        probe = EndpointProbe("sts.example")
        assert probe.resolves("gone.example") is False
        assert probe.resolves("here.example") is True

    @pytest.mark.spec("req-aws-collector-partition-13")
    def test_each_host_is_looked_up_once(self, monkeypatch):
        resolver = _Resolver()
        monkeypatch.setattr(endpoint_probe, "RESOLVE", resolver)
        probe = EndpointProbe("sts.example")
        for _ in range(3):
            probe.resolves("a.example")
        assert resolver.lookups.count("a.example") == 1

    @pytest.mark.spec("req-aws-collector-partition-13")
    def test_a_resolver_that_cannot_find_the_control_host_is_not_believed(self, monkeypatch):
        monkeypatch.setattr(endpoint_probe, "RESOLVE", _Resolver(missing={"sts.example", "a.example"}))
        probe = EndpointProbe("sts.example")
        assert probe.usable is False
        assert probe.resolves("a.example") is None, "neither a yes nor a no: DNS here cannot be trusted"

    @pytest.mark.spec("req-aws-collector-partition-13")
    def test_no_host_and_no_control_host_say_nothing(self, monkeypatch):
        monkeypatch.setattr(endpoint_probe, "RESOLVE", _Resolver())
        assert EndpointProbe(None).resolves("a.example") is None
        assert EndpointProbe("sts.example").resolves(None) is None

    @pytest.mark.spec("req-aws-collector-partition-13")
    def test_the_host_is_the_one_the_operation_calls_not_the_clients_default(self):
        # Offline: the request is built and stopped before it is sent. The hosts below were seen in the error text of
        # real calls on 2026-11-04 (a different host per operation; a FIPS client calling a non-FIPS host).
        assert endpoint_probe.request_host("wellarchitected", "us-gov-west-1", "ListLenses") == "wellarchitected.us-gov-west-1.amazonaws.com"
        assert (
            endpoint_probe.request_host("wellarchitected", "us-gov-west-1", "ListAgentProfiles")
            == "wellarchitected-agent.us-gov-west-1.amazonaws.com"
        )
        # The collector's client reports kinesisvideo-fips as its endpoint but sends to the host below, FIPS being off.
        assert endpoint_probe.request_host("kinesisvideo", "us-gov-west-1", "ListStreams", use_fips=False) == "kinesisvideo.us-gov-west-1.amazonaws.com"
        assert endpoint_probe.request_host("kinesisvideo", "us-gov-west-1", "ListStreams", use_fips=True) == "kinesisvideo-fips.us-gov-west-1.amazonaws.com"

    @pytest.mark.spec("req-aws-collector-partition-13")
    def test_an_operation_that_needs_parameters_it_lacks_gives_no_host(self):
        assert endpoint_probe.request_host("sts", "us-gov-west-1", "AssumeRole") is None
        assert endpoint_probe.request_host("no-such-service", "us-gov-west-1", "ListThings") is None


def _wire(monkeypatch, *, missing=(), **selection):
    """Every request host is ``<service>.us-gov-west-1.amazonaws.com``; ``missing`` names hosts with no record."""
    base._install(monkeypatch, **selection)
    monkeypatch.setattr(
        collector_mod, "request_host", lambda service, region, operation, params=None, **_kw: f"{service}.{region}.amazonaws.com"
    )
    resolver = _Resolver(missing=missing)
    monkeypatch.setattr(endpoint_probe, "RESOLVE", resolver)
    return resolver


def _codes(collector, code):
    return [w for w in collector.results["warn"] if w["message_code"] == code]


@pytest.mark.django_db
class TestInARun:
    @pytest.mark.spec("req-aws-collector-partition-13")
    def test_an_unmarked_service_with_no_host_is_reported_once_and_still_called(self, monkeypatch):
        _wire(monkeypatch, missing={"ec2.us-gov-west-1.amazonaws.com"}, include_types=["ec2:vpc", "ec2:subnet"])
        collector = base._run()
        (gap,) = _codes(collector, "PARTITION_GAP_LEARNED")
        assert gap["message_data"]["service"] == "ec2" and gap["message_data"]["host"] == "ec2.us-gov-west-1.amazonaws.com"
        assert ("ec2", "describe_vpcs") in base._RecordingClient.calls, "a detector, not a skip: the entry is still called"

    @pytest.mark.spec("req-aws-collector-partition-13")
    def test_a_marked_entry_whose_host_resolves_is_reported_stale(self, monkeypatch):
        _wire(monkeypatch, include_types=["qbusiness:*"])
        collector = base._run()
        stale = _codes(collector, "PARTITION_LIST_STALE")
        assert stale and {w["message_data"]["service"] for w in stale} == {"qbusiness"}
        assert len({w["message_data"]["entity_type"] for w in stale}) == len(stale), "one per marked entry"
        assert not [s for s, _op in base._RecordingClient.calls if s == "qbusiness"], "still not called"

    @pytest.mark.spec("req-aws-collector-partition-13")
    def test_a_marked_service_whose_host_has_no_record_raises_nothing(self, monkeypatch):
        _wire(monkeypatch, missing={"qbusiness.us-gov-west-1.amazonaws.com"}, include_types=["qbusiness:*"])
        collector = base._run()
        assert not _codes(collector, "PARTITION_LIST_STALE") and not _codes(collector, "PARTITION_GAP_LEARNED")

    @pytest.mark.spec("req-aws-collector-partition-13")
    def test_when_dns_here_cannot_be_trusted_the_probe_says_nothing(self, monkeypatch):
        _wire(
            monkeypatch,
            missing={"sts.us-gov-west-1.amazonaws.com", "ec2.us-gov-west-1.amazonaws.com"},
            include_types=["ec2:vpc", "qbusiness:*"],
        )
        collector = base._run()
        assert not _codes(collector, "PARTITION_LIST_STALE") and not _codes(collector, "PARTITION_GAP_LEARNED")
        assert ("ec2", "describe_vpcs") in base._RecordingClient.calls
