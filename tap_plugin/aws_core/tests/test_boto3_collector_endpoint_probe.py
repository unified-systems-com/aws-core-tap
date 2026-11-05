"""The endpoint probe (req-aws-collector-partition-13): a detector for the manifest's "not offered" claims."""

from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest
from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
from tap_plugin.aws_core.collectors.boto3_collector import endpoint_probe
from tap_plugin.aws_core.collectors.boto3_collector.endpoint_probe import EndpointProbe, host_of
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

    def test_host_of_reads_the_endpoint_and_tolerates_a_client_without_one(self):
        assert host_of(SimpleNamespace(meta=SimpleNamespace(endpoint_url="https://x.us-gov-west-1.api.aws/path"))) == "x.us-gov-west-1.api.aws"
        assert host_of(object()) is None


class _Client(base._RecordingClient):
    @property
    def meta(self):
        return SimpleNamespace(endpoint_url=f"https://{self._service}.us-gov-west-1.amazonaws.com")


def _wire(monkeypatch, *, missing=(), **selection):
    base._install(monkeypatch, **selection)
    monkeypatch.setattr(collector_mod, "client_factory", lambda _s, region: (lambda svc: _Client(svc)))
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
    def test_a_marked_service_whose_host_resolves_is_reported_stale_once_per_service(self, monkeypatch):
        _wire(monkeypatch, include_types=["qbusiness:*"])
        collector = base._run()
        (stale,) = _codes(collector, "PARTITION_LIST_STALE")
        assert stale["message_data"]["service"] == "qbusiness"
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
