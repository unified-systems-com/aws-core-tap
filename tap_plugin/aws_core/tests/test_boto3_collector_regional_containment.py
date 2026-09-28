"""End-to-end proof of region-scoped containment (tap-plugin-aws-core#49): a real
``Boto3Collector.run()`` against canned VPC / subnet / EC2 instance / security group responses,
asserting the footprint node, the ``HOSTS_*`` edges, and the completeness surfaces this run
authored — all the way through the real pipeline, the same discipline
``test_boto3_collector_slice.py`` holds the aws_op path to.

Three scenarios, matching the module docstrings' own decision table
(``containment.py::surface_of``):

* an ENABLED region with full canned data — the footprint node, all four ``HOSTS_*`` edges, and
  four ``reconcilable``-shaped surfaces (``scope_authorized`` / ``enumeration_complete`` /
  ``admitted`` all true);
* a DISABLED region (``ec2:DescribeRegions`` reports ``not-opted-in``) — the footprint node still
  lands (its own status says disabled), but NO ``HOSTS_*`` edge and NO listing call is made, and
  every surface is authored ``scope_authorized: false`` / ``enumeration_complete: false`` with a
  reason — never an "observed empty" read that reconcile could act on;
* a resource shared into the account via AWS RAM (a VPC whose ``OwnerId`` names a different
  account) — ``BELONGS_TO_ACCOUNT`` reaches the real owner, but no ``HOSTS_VPC`` edge is emitted:
  observed, not hosted, so a later revoked share can never read as this account's VPC having been
  deleted.
"""

from __future__ import annotations

import uuid

import pytest
from tap_cares.collectors.config import CollectorConfig
from tap_cares.secrets.models import Secret, SecretRef

from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred
from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector
from tap_plugin.aws_core.collectors.boto3_collector.containment import footprint_id
from tap_plugin.aws_core.collectors.boto3_collector.identity import (
    edge_entity_id,
    node_entity_id,
)
from tap_plugin.aws_core.collectors.boto3_collector.manifest import (
    manifest_entries as _entries,
)

_ACCOUNT = "111122223333"
_OTHER_ACCOUNT = "999988887777"
_REGION_ENABLED = "us-gov-west-1"
_REGION_DISABLED = "us-gov-east-1"

_VPC_ID = "vpc-0aaa1111"
_SUBNET_ID = "subnet-0bbb2222"
_INSTANCE_ID = "i-0ccc3333"
_SG_ID = "sg-0ddd4444"
_SHARED_VPC_ID = "vpc-0eee5555"

_DESCRIBE_REGIONS = {
    "Regions": [
        {"RegionName": _REGION_ENABLED, "OptInStatus": "opt-in-not-required"},
        {"RegionName": _REGION_DISABLED, "OptInStatus": "not-opted-in"},
    ]
}


def _canned_for(region: str) -> dict:
    if region == _REGION_ENABLED:
        return {
            "describe_regions": _DESCRIBE_REGIONS,
            "get_caller_identity": {"Account": _ACCOUNT},
            "describe_vpcs": {
                "Vpcs": [
                    {"VpcId": _VPC_ID, "CidrBlock": "10.0.0.0/16", "State": "available", "OwnerId": _ACCOUNT},
                    # A VPC shared into this account via AWS RAM: observed, not this account's own.
                    {
                        "VpcId": _SHARED_VPC_ID,
                        "CidrBlock": "10.9.0.0/16",
                        "State": "available",
                        "OwnerId": _OTHER_ACCOUNT,
                    },
                ]
            },
            "describe_subnets": {
                "Subnets": [
                    {
                        "SubnetId": _SUBNET_ID,
                        "VpcId": _VPC_ID,
                        "CidrBlock": "10.0.1.0/24",
                        "AvailabilityZone": f"{region}a",
                        "OwnerId": _ACCOUNT,
                    }
                ]
            },
            "describe_instances": {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": _INSTANCE_ID,
                                "InstanceType": "t3.micro",
                                "State": {"Name": "running"},
                                "VpcId": _VPC_ID,
                                "SubnetId": _SUBNET_ID,
                            }
                        ]
                    }
                ]
            },
            "describe_security_groups": {
                "SecurityGroups": [
                    {
                        "GroupId": _SG_ID,
                        "GroupName": "default",
                        "Description": "default group",
                        "VpcId": _VPC_ID,
                        "OwnerId": _ACCOUNT,
                    }
                ]
            },
        }
    # The disabled region (also what a region-less service client — the account custom_fn's own
    # `session.client("sts", region_name="us-east-1")` — gets, since it names a region string of
    # its own rather than going through client_factory): nothing region-scoped here would ever be
    # called (the collector's own region gate skips the listing before any of these are reached)
    # — describe_vpcs is present only so a bug that DID call it would show up as real (wrong)
    # data rather than an accidental pass via an empty dict.
    return {
        "describe_regions": _DESCRIBE_REGIONS,
        "get_caller_identity": {"Account": _ACCOUNT},
        "describe_vpcs": {"Vpcs": [{"VpcId": "vpc-shouldnotbelisted", "OwnerId": _ACCOUNT}]},
    }


class _EmptyRgtaPaginator:
    """No tagged resources in this canned scenario — RGTA is exercised elsewhere
    (test_boto3_collector_rgta.py); here it must simply not blow up the run."""

    def paginate(self, **_kw):
        return []


class _OnePagePaginator:
    """A real boto3 EC2 client CAN paginate every one of the four DescribeX calls this PR
    wires (confirmed: describe_vpcs/subnets/instances/security_groups each return True from
    can_paginate) — so ``iter_aws_op`` takes the paginator branch in production, never the
    single-call branch. Yielding the canned response as exactly one page proves that branch
    (not the single-call fallback) produces the right nodes/edges/completeness."""

    def __init__(self, page: dict) -> None:
        self._page = page

    def paginate(self, **_kw):
        yield self._page


#: The methods a real EC2 client CAN paginate, among the ones this canned client answers.
_PAGINATED_METHODS = frozenset(
    {"describe_vpcs", "describe_subnets", "describe_instances", "describe_security_groups"}
)


class _CannedClient:
    def __init__(self, region: str) -> None:
        self._region = region
        self._canned = _canned_for(region)

    def can_paginate(self, method: str) -> bool:
        return method in _PAGINATED_METHODS

    def get_paginator(self, name: str):
        if name in _PAGINATED_METHODS:
            return _OnePagePaginator(self._canned.get(name, {}))
        return _EmptyRgtaPaginator()

    def __getattr__(self, name: str):
        return lambda **_kw: self._canned.get(name, {})


class _FakeEvents:
    def register(self, _name: str, _handler: object) -> None:
        return None


class _FakeSession:
    events = _FakeEvents()

    def client(self, _service: str, region_name: str = "", **_kwargs: object) -> _CannedClient:
        return _CannedClient(region_name)


@pytest.fixture
def _stub_aws(monkeypatch):
    secret = Secret(
        ref=SecretRef(scope="aws_core", key="boto_collector"),
        kind="aws_static_access_key",
        description="test",
        data={
            "access_key_id": "AKIA",
            "secret_access_key": "shh",
            "regions_allowed": [_REGION_ENABLED, _REGION_DISABLED],
        },
        metadata={},
        source_path=__import__("pathlib").Path("/dev/null"),
    )
    monkeypatch.setattr(cred, "resolve_secret", lambda _ref: secret)
    monkeypatch.setattr(collector_mod, "build_session", lambda _data: _FakeSession())
    monkeypatch.setattr(
        collector_mod, "client_factory", lambda _s, region: (lambda _svc: _CannedClient(region))
    )
    monkeypatch.setattr(collector_mod, "caller_account_id", lambda *a, **k: _ACCOUNT)


def _run() -> Boto3Collector:
    collector = Boto3Collector(
        CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7())
    )
    collector.run()
    assert collector.results["error"] == []
    return collector


def _surface(collector: Boto3Collector, relation: str, region: str) -> dict:
    subject = str(footprint_id(_ACCOUNT, region))
    matches = [s for s in collector._surfaces if s["relation"] == relation and s["subject"] == subject]
    assert len(matches) == 1, (relation, region, [(s["relation"], s["subject"]) for s in collector._surfaces])
    return matches[0]


@pytest.mark.django_db
class TestEnabledRegion:
    def test_footprint_node_lands_with_partition_and_status(self, _stub_aws):
        from tap_grid.services import get_node

        _run()
        fp = get_node(footprint_id(_ACCOUNT, _REGION_ENABLED))
        assert fp.account_id == _ACCOUNT
        assert fp.region_code == _REGION_ENABLED
        assert fp.partition == "aws-us-gov"
        assert fp.status == "enabled"
        assert fp.opt_in_status == "opt-in-not-required"

    @pytest.mark.parametrize(
        ("edge_type", "child_type", "child_key"),
        [
            ("HOSTS_VPC__aws_core", "aws_core__aws_vpc", _VPC_ID),
            ("HOSTS_SUBNET__aws_core", "aws_core__aws_subnet", _SUBNET_ID),
            ("HOSTS_EC2_INSTANCE__aws_core", "aws_core__aws_ec2_instance", _INSTANCE_ID),
            ("HOSTS_SECURITY_GROUP__aws_core", "aws_core__aws_security_group", _SG_ID),
        ],
    )
    def test_hosts_edge_from_footprint_to_each_owned_resource(self, _stub_aws, edge_type, child_type, child_key):
        from tap_grid.services import get_edge

        _run()
        fp_key = f"{_ACCOUNT}:{_REGION_ENABLED}"
        edge = get_edge(edge_entity_id(edge_type, fp_key, child_key))
        assert edge.edge_type == edge_type
        assert str(edge.from_entity_id) == str(footprint_id(_ACCOUNT, _REGION_ENABLED))
        assert str(edge.to_entity_id) == str(node_entity_id(child_type, child_key))

    def test_every_owned_listing_is_reconcilable(self, _stub_aws):
        collector = _run()
        for relation in (
            "account_region.vpcs",
            "account_region.subnets",
            "account_region.instances",
            "account_region.security_groups",
        ):
            surface = _surface(collector, relation, _REGION_ENABLED)
            assert surface["scope_authorized"] is True, surface
            assert surface["enumeration_complete"] is True, surface
            assert surface["admitted"] is True, surface
            assert surface["edge_type"] is not None

    def test_shared_vpc_is_not_hosted_by_this_account_footprint(self, _stub_aws):
        """RAM share: observed, but never hosted — so a later revoked share can never read as
        this account's VPC having been deleted. (Its BELONGS_TO_ACCOUNT edge — the one this run
        DOES emit, ``containment.py::containment_envelopes`` — is not asserted queryable here:
        a single-account collector never collects the foreign owner's own aws_account node, so
        that edge stays a permissively-skipped dangling edge, same as every one of
        BELONGS_TO_ACCOUNT's other 52 source types already behaves for a resource this
        credential cannot claim ownership of; that is GRIFT's existing dangling-edge contract,
        not something this PR changes.)"""
        from tap_grid.exceptions import ServiceNotFoundError
        from tap_grid.services import get_edge, get_node

        _run()
        shared = get_node(node_entity_id("aws_core__aws_vpc", _SHARED_VPC_ID))
        assert shared.vpc_id == _SHARED_VPC_ID
        with pytest.raises(ServiceNotFoundError):
            get_edge(edge_entity_id("HOSTS_VPC__aws_core", f"{_ACCOUNT}:{_REGION_ENABLED}", _SHARED_VPC_ID))

    def test_shared_vpc_belongs_to_account_envelope_names_its_real_owner(self, _stub_aws):
        """Unit-level proof of the same fact ``test_shared_vpc_is_not_hosted...`` demonstrates
        through a full run: the envelope ``containment_envelopes`` builds for a shared resource
        names the REAL owner, never the observing account, regardless of whether that owner's
        own node was ever collected (a full run can't show this directly — the edge stays
        dangling and unqueryable, per GRIFT's own contract)."""
        from tap_plugin.aws_core.collectors.boto3_collector.containment import (
            containment_envelopes,
        )
        from tap_plugin.aws_core.collectors.boto3_collector.identity import (
            node_entity_id,
        )
        from tap_plugin.aws_core.collectors.boto3_collector.projection import (
            project_item,
        )

        entry = next(e for e in _entries() if e["entity_type"] == "aws_core__aws_vpc")
        item = {"VpcId": _SHARED_VPC_ID, "CidrBlock": "10.9.0.0/16", "State": "available", "OwnerId": _OTHER_ACCOUNT}
        node = project_item(entry, item)
        envelopes = containment_envelopes(
            node,
            entry,
            account_id=_ACCOUNT,
            region=_REGION_ENABLED,
            dimensions={"cloud": "aws", "aws_account": _ACCOUNT, "aws_region": _REGION_ENABLED},
        )
        # ONLY the reference edge — no HOSTS edge, since the owner isn't this account.
        assert len(envelopes) == 1
        edge = envelopes[0]["edge"]
        assert edge["edge_type"] == "BELONGS_TO_ACCOUNT__aws_core"
        assert edge["from_entity_id"] == str(node.entity_id)
        assert edge["to_entity_id"] == str(node_entity_id("aws_core__aws_account", _OTHER_ACCOUNT))

    def test_own_vpc_belongs_to_this_account(self, _stub_aws):
        from tap_grid.services import get_edge

        _run()
        owner_edge = get_edge(edge_entity_id("BELONGS_TO_ACCOUNT__aws_core", _VPC_ID, _ACCOUNT))
        assert str(owner_edge.to_entity_id) == str(node_entity_id("aws_core__aws_account", _ACCOUNT))


@pytest.mark.django_db
class TestDisabledRegion:
    def test_footprint_node_still_lands_but_says_disabled(self, _stub_aws):
        from tap_grid.services import get_node

        _run()
        fp = get_node(footprint_id(_ACCOUNT, _REGION_DISABLED))
        assert fp.status == "disabled"
        assert fp.opt_in_status == "not-opted-in"

    def test_no_listing_call_is_made_and_no_hosts_edge_exists(self, _stub_aws):
        """The disabled-region gate skips the call entirely — this is the 'never observed-empty a
        region the credential could not read' guarantee, proven by the absence of the edge that a
        (wrongly) executed listing's canned data would have produced."""
        from tap_grid.exceptions import ServiceNotFoundError
        from tap_grid.services import get_edge

        _run()
        fp_key = f"{_ACCOUNT}:{_REGION_DISABLED}"
        with pytest.raises(ServiceNotFoundError):
            get_edge(edge_entity_id("HOSTS_VPC__aws_core", fp_key, "vpc-shouldnotbelisted"))

    def test_every_surface_is_authored_unreadable_not_empty(self, _stub_aws):
        collector = _run()
        for relation in (
            "account_region.vpcs",
            "account_region.subnets",
            "account_region.instances",
            "account_region.security_groups",
        ):
            surface = _surface(collector, relation, _REGION_DISABLED)
            assert surface["scope_authorized"] is False, surface
            assert surface["enumeration_complete"] is False, surface
            assert surface["admitted"] is False, surface
            assert surface["count_observed"] is None, surface
            assert "region_disabled" in surface["reasons"]["scope_authorized"]
