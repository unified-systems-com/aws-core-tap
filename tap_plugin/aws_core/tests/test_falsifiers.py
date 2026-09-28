"""Falsifier coverage for aws_core's compute + network types (req-grid-reconcile-falsifier-6):
the four proof cases every falsifier ships, plus the region-sweep behaviour this plugin's
models force (no stored region — see ``tap_plugin.aws_core.falsifiers`` module docstring) and
the EC2-instance terminated-state rule.

The fake EC2 client is table-driven and keyed by ``(region, method, id)``, matching the
``_FakeClient`` convention already used for this collector's own tests
(``test_boto3_collector_source.py``) rather than ``botocore.stub.Stubber`` or moto — neither is
used elsewhere in this plugin's test suite.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from tap_grid.falsifier_testing import (
    CASE_DROPPED,
    CASE_FORBIDDEN,
    CASE_PRESENT,
    CASE_REIDENTIFIED,
    run_four_cases,
)
from tap_grid.falsifiers import (
    DROPPED_FROM_OBSERVATION,
    PRESENT_AT_PROBE,
    REIDENTIFIED,
    UNDETERMINED,
    Candidate,
    FalsifyContext,
    Verdict,
    unsupported,
)
from tap_grid.services import create_node

from tap_plugin.aws_core.falsifiers import (
    Ec2InstanceFalsifier,
    SecurityGroupFalsifier,
    SubnetFalsifier,
    VpcFalsifier,
    _enabled_regions,
)

VPC = "aws_core__aws_vpc"
SUBNET = "aws_core__aws_subnet"
SECURITY_GROUP = "aws_core__aws_security_group"
EC2_INSTANCE = "aws_core__aws_ec2_instance"


class _FakeEc2Client:
    """One region's client: reads its answers from the shared fake, keyed by its own region."""

    def __init__(self, fake: _FakeEc2, region: str) -> None:
        self._fake, self._region = fake, region

    def _call(self, method: str, ids: list[str]) -> Any:
        source_id = ids[0]
        self._fake.calls.append((self._region, method, source_id))
        kind, payload = self._fake.answers.get((self._region, method, source_id), ("error", "InternalError"))
        if kind == "error":
            raise ClientError({"Error": {"Code": payload}}, method)
        return payload

    def describe_vpcs(self, VpcIds: list[str]) -> Any:
        return self._call("describe_vpcs", VpcIds)

    def describe_subnets(self, SubnetIds: list[str]) -> Any:
        return self._call("describe_subnets", SubnetIds)

    def describe_security_groups(self, GroupIds: list[str]) -> Any:
        return self._call("describe_security_groups", GroupIds)

    def describe_instances(self, InstanceIds: list[str]) -> Any:
        return self._call("describe_instances", InstanceIds)


class _FakeEc2:
    """Table-driven fake for every (region, method, id) this test suite probes."""

    def __init__(self) -> None:
        self.answers: dict[tuple[str, str, str], tuple[str, Any]] = {}
        self.calls: list[tuple[str, str, str]] = []

    def answer(self, region: str, method: str, source_id: str, payload: dict[str, Any]) -> None:
        self.answers[(region, method, source_id)] = ("ok", payload)

    def refuse(self, region: str, method: str, source_id: str, code: str) -> None:
        self.answers[(region, method, source_id)] = ("error", code)

    def client_for(self, service: str, region: str) -> _FakeEc2Client:
        assert service == "ec2"
        return _FakeEc2Client(self, region)


def _create(type_slug: str, payload: dict[str, Any]) -> uuid.UUID:
    result = create_node(type_slug, payload)
    assert result.success, f"create_node failed: {result.errors}"
    assert result.entity_id is not None
    return uuid.UUID(str(result.entity_id))


def _candidate(
    entity_id: uuid.UUID, entity_type: str = "", parent: uuid.UUID | None = None, *, surface: int = 0
) -> Candidate:
    return Candidate(
        entity_id=entity_id,
        entity_type=entity_type,
        reason="dropped_from_observation",
        surface=surface,
        relation="fixture",
        subject=str(parent) if parent else None,
        edge_type=None,
        parent=parent,
        interval_first=None,
    )


def _context() -> FalsifyContext:
    return FalsifyContext(batch_id=str(uuid.uuid4()), statement=None)


def _probe(verdict: Verdict) -> dict[str, Any]:
    assert verdict.probe is not None, "a judged verdict records its probe"
    return verdict.probe


def _assert_evidence_supports(verdicts: dict[str, Any]) -> None:
    for case, verdict in verdicts.items():
        assert unsupported(verdict) is None, f"{case}: {unsupported(verdict)}"


@pytest.mark.django_db
class TestVpcFalsifier:
    """Shape: GET-equivalent ``describe_vpcs``; ``VpcId`` compared."""

    @pytest.mark.spec("req-grid-reconcile-falsifier-6")
    def test_four_cases(self) -> None:
        fake = _FakeEc2()
        cases: dict[str, Candidate] = {}

        present = _create(VPC, {"vpc_id": "vpc-present"})
        cases[CASE_PRESENT] = _candidate(present)
        fake.answer("us-east-1", "describe_vpcs", "vpc-present", {"Vpcs": [{"VpcId": "vpc-present"}]})

        dropped = _create(VPC, {"vpc_id": "vpc-dropped"})
        cases[CASE_DROPPED] = _candidate(dropped)
        fake.refuse("us-east-1", "describe_vpcs", "vpc-dropped", "InvalidVpcID.NotFound")

        forbidden = _create(VPC, {"vpc_id": "vpc-forbidden"})
        cases[CASE_FORBIDDEN] = _candidate(forbidden)
        fake.refuse("us-east-1", "describe_vpcs", "vpc-forbidden", "UnauthorizedOperation")

        # Not a shape real AWS would produce for an id-filtered describe (see the falsifiers
        # module docstring) — exercised only to prove classify()'s wiring is sound, matching
        # req-grid-reconcile-falsifier-6's required corpus.
        reborn = _create(VPC, {"vpc_id": "vpc-reborn"})
        cases[CASE_REIDENTIFIED] = _candidate(reborn)
        fake.answer("us-east-1", "describe_vpcs", "vpc-reborn", {"Vpcs": [{"VpcId": "vpc-reborn-new"}]})

        falsifier = VpcFalsifier(client_for=fake.client_for, regions=["us-east-1"])
        verdicts = run_four_cases(falsifier, cases, _context())
        _assert_evidence_supports(verdicts)
        assert verdicts[CASE_PRESENT].expected == {"source_id": "vpc-present", "owner": None, "name": None}
        assert "InvalidVpcID.NotFound" in _probe(verdicts[CASE_DROPPED])["detail"]

    def test_a_row_without_a_vpc_id_is_not_answered(self) -> None:
        rid = _create(VPC, {"name": "design-only"})
        fake = _FakeEc2()
        [verdict] = VpcFalsifier(client_for=fake.client_for, regions=["us-east-1"]).batch_falsify(
            [_candidate(rid)], _context()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert fake.calls == []

    def test_an_unknown_grid_row_is_not_answered(self) -> None:
        fake = _FakeEc2()
        [verdict] = VpcFalsifier(client_for=fake.client_for, regions=["us-east-1"]).batch_falsify(
            [_candidate(uuid.uuid4())], _context()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "errored")
        assert "grid row could not be read" in verdict.note


@pytest.mark.django_db
class TestRegionSweep:
    """No model in this set stores a region (the substitution the falsifiers module docstring
    names), so every falsifier but Subnet's sweeps the credential's configured regions."""

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_found_in_a_later_region_stops_the_sweep(self) -> None:
        vid = _create(VPC, {"vpc_id": "vpc-elsewhere"})
        fake = _FakeEc2()
        fake.refuse("us-east-1", "describe_vpcs", "vpc-elsewhere", "InvalidVpcID.NotFound")
        fake.answer("eu-west-1", "describe_vpcs", "vpc-elsewhere", {"Vpcs": [{"VpcId": "vpc-elsewhere"}]})
        falsifier = VpcFalsifier(client_for=fake.client_for, regions=["us-east-1", "eu-west-1", "ap-south-1"])
        [verdict] = falsifier.batch_falsify([_candidate(vid)], _context())
        assert verdict.verdict == PRESENT_AT_PROBE
        assert fake.calls == [
            ("us-east-1", "describe_vpcs", "vpc-elsewhere"),
            ("eu-west-1", "describe_vpcs", "vpc-elsewhere"),
        ], "the sweep stops at the first authoritative answer; ap-south-1 is never asked"

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_not_found_requires_every_configured_region_to_agree(self) -> None:
        vid = _create(VPC, {"vpc_id": "vpc-truly-gone"})
        fake = _FakeEc2()
        fake.refuse("us-east-1", "describe_vpcs", "vpc-truly-gone", "InvalidVpcID.NotFound")
        fake.refuse("eu-west-1", "describe_vpcs", "vpc-truly-gone", "InvalidVpcID.NotFound")
        falsifier = VpcFalsifier(client_for=fake.client_for, regions=["us-east-1", "eu-west-1"])
        [verdict] = falsifier.batch_falsify([_candidate(vid)], _context())
        assert verdict.verdict == DROPPED_FROM_OBSERVATION

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_a_forbidden_region_refuses_the_retirement_even_when_others_say_not_found(self) -> None:
        """Fail closed: a region that refused the probe could be hiding the object, so a
        not_found everywhere else is not let through as a retirement."""
        vid = _create(VPC, {"vpc_id": "vpc-maybe-hidden"})
        fake = _FakeEc2()
        fake.refuse("us-east-1", "describe_vpcs", "vpc-maybe-hidden", "InvalidVpcID.NotFound")
        fake.refuse("eu-west-1", "describe_vpcs", "vpc-maybe-hidden", "UnauthorizedOperation")
        falsifier = VpcFalsifier(client_for=fake.client_for, regions=["us-east-1", "eu-west-1"])
        [verdict] = falsifier.batch_falsify([_candidate(vid)], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "forbidden")

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_an_errored_region_also_refuses_the_retirement(self) -> None:
        vid = _create(VPC, {"vpc_id": "vpc-flaky"})
        fake = _FakeEc2()
        fake.refuse("us-east-1", "describe_vpcs", "vpc-flaky", "InvalidVpcID.NotFound")
        fake.refuse("eu-west-1", "describe_vpcs", "vpc-flaky", "InternalError")
        falsifier = VpcFalsifier(client_for=fake.client_for, regions=["us-east-1", "eu-west-1"])
        [verdict] = falsifier.batch_falsify([_candidate(vid)], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "errored")

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_no_configured_regions_is_undetermined_not_a_crash(self) -> None:
        vid = _create(VPC, {"vpc_id": "vpc-no-scope"})
        fake = _FakeEc2()
        falsifier = VpcFalsifier(client_for=fake.client_for, regions=[])
        [verdict] = falsifier.batch_falsify([_candidate(vid)], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "errored")
        assert "no region scope" in verdict.note

    def test_a_missing_credential_answers_undetermined_for_every_candidate(self) -> None:
        def boom() -> Any:
            raise RuntimeError("no secret mounted")

        candidates = [_candidate(uuid.uuid4(), surface=i) for i in range(2)]
        verdicts = VpcFalsifier(session_factory=boom).batch_falsify(candidates, _context())
        assert [(v.verdict, v.reason) for v in verdicts] == [(UNDETERMINED, "errored")] * 2
        assert all("credential unavailable" in v.note for v in verdicts)

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_a_client_construction_failure_degrades_the_candidate_not_the_whole_batch(self) -> None:
        """PR #44: client construction (``client_for(service, region)``) used to run
        OUTSIDE ``_describe_one``'s guarded try/except. A region boto3 cannot build a client for
        must answer UNDETERMINED(errored) for this candidate, never raise out of batch_falsify —
        raising would cost every OTHER candidate of this type its verdict too
        (tap_grid.falsifiers._judge answers a whole group errored when batch_falsify raises)."""

        def client_for(service: str, region: str) -> Any:
            raise BotoCoreError()

        vid = _create(VPC, {"vpc_id": "vpc-unbuildable-region"})
        falsifier = VpcFalsifier(client_for=client_for, regions=["not-a-real-region"])
        [verdict] = falsifier.batch_falsify([_candidate(vid)], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "errored")


@pytest.mark.django_db
class TestSubnetFalsifier:
    """Shape: ``describe_subnets``; ``SubnetId`` compared; the availability-zone shortcut."""

    @pytest.mark.spec("req-grid-reconcile-falsifier-6")
    def test_four_cases(self) -> None:
        fake = _FakeEc2()
        cases: dict[str, Candidate] = {}

        present = _create(SUBNET, {"subnet_id": "subnet-present", "availability_zone": "us-east-1a"})
        cases[CASE_PRESENT] = _candidate(present)
        fake.answer("us-east-1", "describe_subnets", "subnet-present", {"Subnets": [{"SubnetId": "subnet-present"}]})

        dropped = _create(SUBNET, {"subnet_id": "subnet-dropped", "availability_zone": "us-east-1a"})
        cases[CASE_DROPPED] = _candidate(dropped)
        fake.refuse("us-east-1", "describe_subnets", "subnet-dropped", "InvalidSubnetID.NotFound")

        forbidden = _create(SUBNET, {"subnet_id": "subnet-forbidden", "availability_zone": "us-east-1a"})
        cases[CASE_FORBIDDEN] = _candidate(forbidden)
        fake.refuse("us-east-1", "describe_subnets", "subnet-forbidden", "AccessDenied")

        reborn = _create(SUBNET, {"subnet_id": "subnet-reborn", "availability_zone": "us-east-1a"})
        cases[CASE_REIDENTIFIED] = _candidate(reborn)
        fake.answer("us-east-1", "describe_subnets", "subnet-reborn", {"Subnets": [{"SubnetId": "subnet-reborn-new"}]})

        falsifier = SubnetFalsifier(client_for=fake.client_for, regions=["us-east-1"])
        verdicts = run_four_cases(falsifier, cases, _context())
        _assert_evidence_supports(verdicts)

    @pytest.mark.spec("req-aws-collector-regions")
    def test_the_availability_zone_derived_region_is_tried_before_the_sweep(self) -> None:
        sid = _create(SUBNET, {"subnet_id": "subnet-az-hint", "availability_zone": "us-west-2c"})
        fake = _FakeEc2()
        fake.answer("us-west-2", "describe_subnets", "subnet-az-hint", {"Subnets": [{"SubnetId": "subnet-az-hint"}]})
        # The configured sweep order deliberately does NOT lead with us-west-2.
        falsifier = SubnetFalsifier(client_for=fake.client_for, regions=["us-east-1", "eu-west-1", "us-west-2"])
        [verdict] = falsifier.batch_falsify([_candidate(sid)], _context())
        assert verdict.verdict == PRESENT_AT_PROBE
        assert fake.calls == [("us-west-2", "describe_subnets", "subnet-az-hint")], (
            "the AZ hint is tried first and answers authoritatively; us-east-1/eu-west-1 are never asked"
        )

    def test_a_subnet_with_no_availability_zone_falls_back_to_the_configured_sweep(self) -> None:
        sid = _create(SUBNET, {"subnet_id": "subnet-no-az"})
        fake = _FakeEc2()
        fake.refuse("us-east-1", "describe_subnets", "subnet-no-az", "InvalidSubnetID.NotFound")
        fake.answer("eu-west-1", "describe_subnets", "subnet-no-az", {"Subnets": [{"SubnetId": "subnet-no-az"}]})
        falsifier = SubnetFalsifier(client_for=fake.client_for, regions=["us-east-1", "eu-west-1"])
        [verdict] = falsifier.batch_falsify([_candidate(sid)], _context())
        assert verdict.verdict == PRESENT_AT_PROBE


@pytest.mark.django_db
class TestSecurityGroupFalsifier:
    """Shape: ``describe_security_groups``; ``GroupId`` compared."""

    @pytest.mark.spec("req-grid-reconcile-falsifier-6")
    def test_four_cases(self) -> None:
        fake = _FakeEc2()
        cases: dict[str, Candidate] = {}

        present = _create(SECURITY_GROUP, {"group_id": "sg-present"})
        cases[CASE_PRESENT] = _candidate(present)
        fake.answer("us-east-1", "describe_security_groups", "sg-present", {"SecurityGroups": [{"GroupId": "sg-present"}]})

        dropped = _create(SECURITY_GROUP, {"group_id": "sg-dropped"})
        cases[CASE_DROPPED] = _candidate(dropped)
        fake.refuse("us-east-1", "describe_security_groups", "sg-dropped", "InvalidGroup.NotFound")

        forbidden = _create(SECURITY_GROUP, {"group_id": "sg-forbidden"})
        cases[CASE_FORBIDDEN] = _candidate(forbidden)
        fake.refuse("us-east-1", "describe_security_groups", "sg-forbidden", "UnauthorizedOperation")

        reborn = _create(SECURITY_GROUP, {"group_id": "sg-reborn"})
        cases[CASE_REIDENTIFIED] = _candidate(reborn)
        fake.answer(
            "us-east-1", "describe_security_groups", "sg-reborn", {"SecurityGroups": [{"GroupId": "sg-reborn-new"}]}
        )

        falsifier = SecurityGroupFalsifier(client_for=fake.client_for, regions=["us-east-1"])
        verdicts = run_four_cases(falsifier, cases, _context())
        _assert_evidence_supports(verdicts)


@pytest.mark.django_db
class TestEc2InstanceFalsifier:
    """Shape: ``describe_instances``; ``InstanceId`` compared; the terminated-state rule."""

    @pytest.mark.spec("req-grid-reconcile-falsifier-6")
    def test_four_cases(self) -> None:
        fake = _FakeEc2()
        cases: dict[str, Candidate] = {}

        present = _create(EC2_INSTANCE, {"instance_id": "i-present"})
        cases[CASE_PRESENT] = _candidate(present)
        fake.answer(
            "us-east-1",
            "describe_instances",
            "i-present",
            {"Reservations": [{"Instances": [{"InstanceId": "i-present", "State": {"Name": "running"}}]}]},
        )

        # A genuine 404: an instance id old enough that AWS has purged it entirely.
        dropped = _create(EC2_INSTANCE, {"instance_id": "i-purged"})
        cases[CASE_DROPPED] = _candidate(dropped)
        fake.refuse("us-east-1", "describe_instances", "i-purged", "InvalidInstanceID.NotFound")

        forbidden = _create(EC2_INSTANCE, {"instance_id": "i-forbidden"})
        cases[CASE_FORBIDDEN] = _candidate(forbidden)
        fake.refuse("us-east-1", "describe_instances", "i-forbidden", "UnauthorizedOperation")

        reborn = _create(EC2_INSTANCE, {"instance_id": "i-reborn"})
        cases[CASE_REIDENTIFIED] = _candidate(reborn)
        fake.answer(
            "us-east-1",
            "describe_instances",
            "i-reborn",
            {"Reservations": [{"Instances": [{"InstanceId": "i-reborn-new", "State": {"Name": "running"}}]}]},
        )

        falsifier = Ec2InstanceFalsifier(client_for=fake.client_for, regions=["us-east-1"])
        verdicts = run_four_cases(falsifier, cases, _context())
        _assert_evidence_supports(verdicts)

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_a_terminated_instance_is_dropped_from_observation(self) -> None:
        iid = _create(EC2_INSTANCE, {"instance_id": "i-terminated"})
        fake = _FakeEc2()
        fake.answer(
            "us-east-1",
            "describe_instances",
            "i-terminated",
            {"Reservations": [{"Instances": [{"InstanceId": "i-terminated", "State": {"Name": "terminated"}}]}]},
        )
        falsifier = Ec2InstanceFalsifier(client_for=fake.client_for, regions=["us-east-1", "eu-west-1"])
        [verdict] = falsifier.batch_falsify([_candidate(iid)], _context())
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        assert "terminated" in _probe(verdict)["detail"]
        assert fake.calls == [("us-east-1", "describe_instances", "i-terminated")], (
            "a terminated instance is an authoritative answer from the region that has it; the "
            "sweep must not continue into eu-west-1"
        )

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_a_terminated_response_naming_a_different_instance_is_not_trusted(self) -> None:
        """PR #44: the terminated-state shortcut folds a successful response into
        ``not_found`` WITHOUT going through classify()'s identity comparison — so it must check
        identity itself before taking that shortcut. A response naming some other instance
        (which real DescribeInstances-by-id never does, but nothing here should rest on that
        alone) must fall through to the ordinary found path and come out REIDENTIFIED, not
        silently retire the candidate under a state field that describes a different object."""
        iid = _create(EC2_INSTANCE, {"instance_id": "i-expected"})
        fake = _FakeEc2()
        fake.answer(
            "us-east-1",
            "describe_instances",
            "i-expected",
            {"Reservations": [{"Instances": [{"InstanceId": "i-other", "State": {"Name": "terminated"}}]}]},
        )
        falsifier = Ec2InstanceFalsifier(client_for=fake.client_for, regions=["us-east-1"])
        [verdict] = falsifier.batch_falsify([_candidate(iid)], _context())
        assert verdict.verdict == REIDENTIFIED
        assert unsupported(verdict) is None

    @pytest.mark.parametrize("state", ["pending", "running", "shutting-down", "stopping", "stopped"])
    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_every_non_terminated_state_is_present_not_gone(self, state: str) -> None:
        """Stopped is not gone — only not running."""
        iid = _create(EC2_INSTANCE, {"instance_id": f"i-{state}"})
        fake = _FakeEc2()
        fake.answer(
            "us-east-1",
            "describe_instances",
            f"i-{state}",
            {"Reservations": [{"Instances": [{"InstanceId": f"i-{state}", "State": {"Name": state}}]}]},
        )
        falsifier = Ec2InstanceFalsifier(client_for=fake.client_for, regions=["us-east-1"])
        [verdict] = falsifier.batch_falsify([_candidate(iid)], _context())
        assert verdict.verdict == PRESENT_AT_PROBE


class _FakeEc2ClientForRegions:
    """A minimal session/client stand-in for ``_enabled_regions``: ``.client(service,
    region_name=...)`` returns an object whose ``describe_regions`` answers from a table, or
    raises, keyed only by whether the call should succeed — the anchor region never matters to
    the answer, only to which client construction call was made."""

    def __init__(self, *, regions: list[dict[str, str]] | None = None, raises: Exception | None = None) -> None:
        self._regions = regions
        self._raises = raises
        self.anchor_regions_used: list[str] = []

    def client(self, service: str, region_name: str) -> Any:
        assert service == "ec2"
        self.anchor_regions_used.append(region_name)
        return self

    def describe_regions(self, AllRegions: bool) -> Any:
        assert AllRegions is False
        if self._raises is not None:
            raise self._raises
        return {"Regions": self._regions or []}


class TestEnabledRegions:
    """PR #44: the sweep is the account's full enabled-region set
    (``ec2:DescribeRegions``), not merely the operator's current ``regions_allowed`` collection
    scope — a row already on the grid (Subnet, via the pre-existing VPC containment edge) may
    have been collected under a wider scope that was since narrowed. Round 4: the fallback used
    on a ``DescribeRegions`` failure must come back marked untrustworthy, not silently equal to
    a confirmed sweep — an earlier version of this fix fell back silently, which quietly
    reopened the exact false-retirement bug this mechanism exists to close."""

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_returns_the_accounts_enabled_regions_sorted_and_deduplicated(self) -> None:
        session = _FakeEc2ClientForRegions(
            regions=[
                {"RegionName": "us-west-2"},
                {"RegionName": "us-east-1"},
                {"RegionName": "us-east-1"},
            ]
        )
        assert _enabled_regions(session, ["us-east-1"]) == (["us-east-1", "us-west-2"], True)
        assert session.anchor_regions_used == ["us-east-1"], "anchored on the first configured region"

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_a_wider_enabled_set_than_the_configured_scope_is_used(self) -> None:
        """The whole point: DescribeRegions can name a region regions_allowed does not."""
        session = _FakeEc2ClientForRegions(regions=[{"RegionName": "us-west-2"}, {"RegionName": "eu-west-1"}])
        assert _enabled_regions(session, ["us-west-2"]) == (["eu-west-1", "us-west-2"], True)

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_falls_back_to_the_configured_scope_when_describe_regions_fails(self) -> None:
        session = _FakeEc2ClientForRegions(raises=BotoCoreError())
        assert _enabled_regions(session, ["us-east-1", "eu-west-1"]) == (["us-east-1", "eu-west-1"], False)

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_an_empty_enabled_set_falls_back_to_the_configured_scope(self) -> None:
        """Defensive: DescribeRegions succeeding with nothing named is not trusted as 'sweep
        nothing' — that would be worse than the scope this falsifier used before this fix."""
        session = _FakeEc2ClientForRegions(regions=[])
        assert _enabled_regions(session, ["us-east-1"]) == (["us-east-1"], False)


@pytest.mark.django_db
class TestUntrustworthyRegionScopeNeverAuthorizesRetirement:
    """PR #44: a clean not_found sweep of a region scope this run could not confirm complete
    must never stand in for a clean sweep of everywhere the resource could actually be.
    ``regions_trustworthy=False`` is driven directly (there is no real AWS session in a unit
    test) — it is exactly what ``_default_session`` -> ``_enabled_regions`` hands ``judge()``
    in production after an ``ec2:DescribeRegions`` failure."""

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_a_clean_sweep_of_an_unconfirmed_fallback_scope_is_undetermined_not_dropped(self) -> None:
        """``regions_trustworthy=False`` is exactly what a ``DescribeRegions`` failure produces
        via ``_default_session`` -> ``_enabled_regions`` in production; driven directly here
        since there is no real AWS session in a unit test."""
        vid = _create(VPC, {"vpc_id": "vpc-maybe-elsewhere"})
        fake = _FakeEc2()
        fake.refuse("us-east-1", "describe_vpcs", "vpc-maybe-elsewhere", "InvalidVpcID.NotFound")
        falsifier = VpcFalsifier(client_for=fake.client_for, regions=["us-east-1"], regions_trustworthy=False)
        [verdict] = falsifier.batch_falsify([_candidate(vid)], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "not evidence of absence" in verdict.note

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_a_trustworthy_clean_sweep_still_drops(self) -> None:
        """The gate is specifically about trustworthiness, not about adding friction generally —
        the default (True) still yields DROPPED_FROM_OBSERVATION exactly as every other test in
        this file already assumes."""
        vid = _create(VPC, {"vpc_id": "vpc-really-gone"})
        fake = _FakeEc2()
        fake.refuse("us-east-1", "describe_vpcs", "vpc-really-gone", "InvalidVpcID.NotFound")
        falsifier = VpcFalsifier(client_for=fake.client_for, regions=["us-east-1"], regions_trustworthy=True)
        [verdict] = falsifier.batch_falsify([_candidate(vid)], _context())
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
