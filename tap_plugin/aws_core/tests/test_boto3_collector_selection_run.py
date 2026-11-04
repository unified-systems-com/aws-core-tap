"""End-to-end proof of collection selection (req-aws-collector-selection): a real ``Boto3Collector.run()`` against
canned EC2 responses and a recording client, asserting what a selected run reads, what it writes and what it states.

Scenarios, from the spec's acceptance criteria:

* no selection: the run reads and states as before (``-5``, the other half);
* ``include_types: ["ec2:vpc"]``: only that entry is read, no call reaches any other EC2 listing or the Organizations
  or landing-zone collaborators (``-2``), the footprint and account anchors still land (``-3``), the echo names the
  selection (``-9``), and the run states no completeness at all: no surface, no ``declare_no_surfaces`` (``-5``);
* a restricted run over a grid already holding the unselected type's rows leaves those rows untouched (``-5``);
* a pattern matching no entry stops the run before any call (``-4``); a resolved account outside ``accounts_allowed``
  stops it before collection (``-6``).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from tap_cares.collectors.config import CollectorConfig
from tap_cares.secrets.models import Secret, SecretRef

from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred
from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector, Boto3CollectorError
from tap_plugin.aws_core.tests.grid_keys import find_node_id, node_id

_ACCOUNT = "111122223333"
_REGION = "us-gov-west-1"
_VPC_ID = "vpc-0aaa1111"
_SUBNET_ID = "subnet-0bbb2222"
_FOOTPRINT = "aws_core__aws_account_region"

_CANNED = {
    "describe_regions": {"Regions": [{"RegionName": _REGION, "OptInStatus": "opt-in-not-required"}]},
    "get_caller_identity": {"Account": _ACCOUNT},
    "describe_vpcs": {"Vpcs": [{"VpcId": _VPC_ID, "OwnerId": _ACCOUNT, "CidrBlock": "10.0.0.0/16", "State": "available"}]},
    "describe_subnets": {
        "Subnets": [
            {
                "SubnetId": _SUBNET_ID,
                "VpcId": _VPC_ID,
                "OwnerId": _ACCOUNT,
                "CidrBlock": "10.0.1.0/24",
                "AvailabilityZone": f"{_REGION}a",
                "State": "available",
            }
        ]
    },
}
_PAGINATED = frozenset({"describe_vpcs", "describe_subnets", "describe_instances", "describe_security_groups"})


class _EmptyPaginator:
    def paginate(self, **_kw):
        return []


class _OnePage:
    def __init__(self, page: dict) -> None:
        self._page = page

    def paginate(self, **_kw):
        yield self._page


class _RecordingClient:
    """Answers the canned calls and records every ``(service, operation)`` this run makes."""

    calls: list[tuple[str, str]] = []

    def __init__(self, service: str) -> None:
        self._service = service

    def can_paginate(self, method: str) -> bool:
        return method in _PAGINATED

    def get_paginator(self, name: str):
        self.calls.append((self._service, name))
        return _OnePage(_CANNED.get(name, {})) if name in _PAGINATED else _EmptyPaginator()

    def __getattr__(self, name: str):
        def call(**_kw):
            self.calls.append((self._service, name))
            return _CANNED.get(name, {})

        return call


class _FakeEvents:
    def register(self, _name: str, _handler: object) -> None:
        return None


class _FakeSession:
    events = _FakeEvents()

    def client(self, service: str, region_name: str = "", **_kwargs: object) -> _RecordingClient:
        return _RecordingClient(service)


def _install(monkeypatch, **selection) -> None:
    _RecordingClient.calls = []
    secret = Secret(
        ref=SecretRef(scope="aws_core", key="boto_collector"),
        kind="aws_static_access_key",
        description="test",
        data={"access_key_id": "AKIA", "secret_access_key": "shh", "regions_allowed": [_REGION], **selection},
        metadata={},
        source_path=Path("/dev/null"),
    )
    monkeypatch.setattr(cred, "resolve_secret", lambda _ref: secret)
    monkeypatch.setattr(collector_mod, "build_session", lambda _data: _FakeSession())
    monkeypatch.setattr(collector_mod, "client_factory", lambda _s, region: (lambda svc: _RecordingClient(svc)))

    def identity(*_a, **_k):
        _RecordingClient.calls.append(("sts", "get_caller_identity"))
        return _ACCOUNT

    monkeypatch.setattr(collector_mod, "caller_account_id", identity)


def _run(*, expect_error: bool = False) -> Boto3Collector:
    collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
    if expect_error:
        with pytest.raises(Boto3CollectorError):
            collector.run()
    else:
        collector.run()
        assert collector.results["error"] == []
    return collector


def _applied(collector: Boto3Collector) -> dict:
    (record,) = [r for r in collector.results["info"] if r["message_code"] == "SELECTION_APPLIED"]
    return record["message_data"]


def _operations() -> set[str]:
    return {op for _service, op in _RecordingClient.calls}


@pytest.mark.django_db
class TestNoSelection:
    @pytest.mark.spec("req-aws-collector-selection-5")
    def test_a_run_selecting_everything_states_its_completeness_as_before(self, monkeypatch):
        _install(monkeypatch)
        collector = _run()
        assert collector._surfaces_declared is True
        assert collector._surfaces, "the full run records its listing surfaces"
        echoed = _applied(collector)
        assert echoed["entries_skipped"] == 0 and echoed["include_types"] == [] and echoed["exclude_types"] == []

    @pytest.mark.spec("req-aws-collector-selection-5")
    def test_a_pattern_that_selects_everything_changes_nothing(self, monkeypatch):
        _install(monkeypatch, include_types=["*:*"])
        collector = _run()
        assert collector._surfaces_declared is True and collector._surfaces


@pytest.mark.django_db
class TestIncludeOneType:
    @pytest.mark.spec("req-aws-collector-selection-2")
    def test_an_unselected_entry_makes_no_call_of_its_own(self, monkeypatch):
        _install(monkeypatch, include_types=["ec2:vpc"])
        _run()
        ops = _operations()
        assert "describe_vpcs" in ops
        assert not ops & {"describe_subnets", "describe_instances", "describe_security_groups"}
        services = {service for service, _op in _RecordingClient.calls}
        assert "organizations" not in services, "the Organizations tree is not a manifest entry; a run that chose its types skips it"

    @pytest.mark.spec("req-aws-collector-selection-3")
    def test_anchors_are_never_filtered(self, monkeypatch):
        from tap_grid.services import get_node

        _install(monkeypatch, include_types=["ec2:vpc"])
        _run()
        footprint = get_node(node_id(_FOOTPRINT, {"account_id": _ACCOUNT, "region_code": _REGION}))
        assert footprint.region_code == _REGION
        assert find_node_id("aws_core__aws_account", _ACCOUNT) is not None
        assert find_node_id("aws_core__aws_vpc", _VPC_ID) is not None
        assert find_node_id("aws_core__aws_subnet", _SUBNET_ID) is None

    @pytest.mark.spec("req-aws-collector-selection-5")
    def test_a_selected_run_states_no_completeness_at_all(self, monkeypatch):
        _install(monkeypatch, include_types=["ec2:vpc"])
        collector = _run()
        assert collector._surfaces == []
        assert collector._surfaces_declared is False, "not even `declare_no_surfaces`: that would say the run covered nothing"

    @pytest.mark.spec("req-aws-collector-selection-9")
    def test_the_effective_selection_is_echoed_once(self, monkeypatch):
        _install(monkeypatch, include_types=["ec2:vpc"], accounts_allowed=[_ACCOUNT])
        collector = _run()
        echoed = _applied(collector)
        assert echoed["include_types"] == ["ec2:vpc"] and echoed["accounts_allowed"] == [_ACCOUNT]
        assert echoed["entries_selected"] == 2  # the entry and the account anchor
        assert echoed["entries_skipped"] == echoed["entries_total"] - 2
        assert len([r for r in collector.results["info"] if r["message_code"] == "SELECTION_APPLIED"]) == 1

    @pytest.mark.spec("req-aws-collector-selection-5")
    def test_a_restricted_run_leaves_the_rows_of_an_unselected_type_untouched(self, monkeypatch):
        from tap_grid.services import get_node

        _install(monkeypatch)
        _run()
        before = get_node(node_id("aws_core__aws_subnet", _SUBNET_ID))
        _install(monkeypatch, include_types=["ec2:vpc"])
        collector = _run()
        after = get_node(node_id("aws_core__aws_subnet", _SUBNET_ID))
        assert after.entity_id == before.entity_id and after.cidr_block == before.cidr_block
        assert after.entity.deleted_at is None
        assert collector._surfaces == [] and collector._surfaces_declared is False


@pytest.mark.django_db
class TestFailClosed:
    @pytest.mark.spec("req-aws-collector-selection-4")
    @pytest.mark.parametrize("key", ["include_types", "exclude_types"])
    def test_a_pattern_matching_no_entry_stops_the_run_before_any_call(self, monkeypatch, key):
        _install(monkeypatch, **{key: ["ec2:no_such_entity"]})
        collector = _run(expect_error=True)
        assert [e["message_code"] for e in collector.results["error"]] == ["SELECTION_PATTERN_UNMATCHED"]
        assert "ec2:no_such_entity" in collector.results["error"][0]["message"]
        assert _RecordingClient.calls == [], "no call, not even the identity probe"

    @pytest.mark.spec("req-aws-collector-selection-6")
    def test_a_resolved_account_outside_accounts_allowed_stops_the_run_before_collection(self, monkeypatch):
        _install(monkeypatch, accounts_allowed=["999988887777"])
        collector = _run(expect_error=True)
        assert [e["message_code"] for e in collector.results["error"]] == ["ACCOUNT_NOT_SELECTED"]
        assert _operations() <= {"get_caller_identity"}, "only the identity probe ran"
        assert find_node_id("aws_core__aws_vpc", _VPC_ID) is None

    @pytest.mark.spec("req-aws-collector-selection-6")
    def test_a_resolved_account_inside_accounts_allowed_proceeds(self, monkeypatch):
        _install(monkeypatch, accounts_allowed=[_ACCOUNT])
        collector = _run()
        assert collector._surfaces, "every type is selected and the one account is inside the list: the run states as before"

    @pytest.mark.spec("req-aws-collector-selection-6")
    def test_an_arn_in_the_wrong_partition_stops_the_run(self, monkeypatch):
        _install(monkeypatch, accounts_allowed=["arn:aws:iam::111122223333:role/x"])
        collector = _run(expect_error=True)
        assert collector.results["error"][0]["message_code"] == "SELECTION_INVALID"
        assert _RecordingClient.calls == []
