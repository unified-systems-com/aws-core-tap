"""The falsifier foundation (tap-plugin-aws-core#42): the four proof cases every falsifier ships
(``req-grid-reconcile-falsifier-6``, core's ``tap_grid.falsifier_testing``) against a fake
``ec2`` client, plus the single-account scope check and the manifest wiring.

Mirrors ``tap_plugin.github_core.tests.test_falsifiers``'s shape: real grid rows through the
service layer, a fake AWS client arranged so each candidate meets its situation, one
``batch_falsify`` call judging all four at once.

``SubnetFalsifier`` is the concrete falsifier under test here, not a VPC one — see
``tap_plugin/aws_core/falsifiers.py``'s module docstring ("Why Subnet is the one concrete
falsifier here — not VPC") for why: ``Vpc.CONTAINMENT_EDGES`` makes ``aws_core__aws_subnet``
the one type ``validate_plugin``'s falsifier-coverage check already marks reconcilable.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import tomllib
from botocore.exceptions import BotoCoreError, ClientError
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string
from tap_plugin.aws_core.falsifiers import (
    NOT_FOUND_DETAIL,
    SubnetFalsifier,
    error_code_of,
    probe_status_of,
)
from tap_plugin.aws_core.models.aws_account import AwsAccount
from tap_plugin.aws_core.models.aws_organization import AwsOrganization

from tap.plugin_testing import find_plugin_source_root
from tap_grid.falsifier_testing import (
    CASE_DROPPED,
    CASE_FORBIDDEN,
    CASE_PRESENT,
    CASE_REIDENTIFIED,
    run_four_cases,
)
from tap_grid.falsifiers import (
    UNDETERMINED,
    Candidate,
    Falsifier,
    FalsifyContext,
    Verdict,
    get_falsifier,
    register_falsifier,
    unregister_falsifier,
    unsupported,
)
from tap_grid.services import create_node, get_node

SUBNET = "aws_core__aws_subnet"
ACCOUNT_ID = "111122223333"
OTHER_ACCOUNT_ID = "999988887777"
REGION = "us-east-1"

PLUGIN_ROOT = find_plugin_source_root(__file__)


class FakeEc2:
    """A fake ``ec2`` boto3 client: ``describe_subnets(SubnetIds=[...])`` answered from a table
    keyed by the requested subnet id, arranged per test the way ``fake_github.FakeGithub`` is."""

    def __init__(self) -> None:
        self._responses: dict[str, dict[str, Any] | Exception] = {}
        self.calls: list[str] = []

    def answer(self, subnet_id: str, subnet: dict[str, Any]) -> None:
        self._responses[subnet_id] = {"Subnets": [subnet]}

    def empty(self, subnet_id: str) -> None:
        """A 200 with no matching subnet — the non-exception shape some services use instead of
        a NotFound error."""
        self._responses[subnet_id] = {"Subnets": []}

    def refuse(self, subnet_id: str, code: str, message: str = "boom") -> None:
        self._responses[subnet_id] = ClientError({"Error": {"Code": code, "Message": message}}, "DescribeSubnets")

    def describe_subnets(self, SubnetIds: list[str]) -> dict[str, Any]:  # noqa: N803 — boto3's own casing
        subnet_id = SubnetIds[0]
        self.calls.append(subnet_id)
        response = self._responses.get(subnet_id)
        if response is None:
            raise AssertionError(f"FakeEc2: no response configured for {subnet_id!r}")
        if isinstance(response, Exception):
            raise response
        return response


class FakeSession:
    """A boto3-session-shaped double: ``.client('ec2', region_name=...)`` returns the one fake
    ec2 client, whatever region is asked (region routing itself is the collector's job, not the
    falsifier's; the falsifier only needs to reach the right client). ``breaks_with`` makes
    ``.client()`` itself raise, the way a bad region name or broken botocore config can, before
    any network call is made."""

    def __init__(self, ec2: FakeEc2, *, breaks_with: Exception | None = None) -> None:
        self._ec2 = ec2
        self._breaks_with = breaks_with

    def client(self, service: str, region_name: str | None = None) -> Any:
        assert service == "ec2", f"SubnetFalsifier must ask for ec2, asked for {service!r}"
        assert region_name, "SubnetFalsifier must pass a region"
        if self._breaks_with is not None:
            raise self._breaks_with
        return self._ec2


def _create_subnet(
    subnet_id: str, *, name: str = "", account_id: str = ACCOUNT_ID, region: str = REGION
) -> uuid.UUID:
    result = create_node(SUBNET, {"subnet_id": subnet_id, "name": name})
    assert result.success, f"create_node failed: {result.errors}"
    assert result.entity_id is not None
    entity_id = uuid.UUID(str(result.entity_id))
    row = get_node(entity_id)
    row.entity.dimensions = {"cloud": "aws", "aws_account": account_id, "aws_region": region}
    row.entity.save(update_fields=["dimensions"])
    return entity_id


def _candidate(entity_id: uuid.UUID, *, surface: int = 0) -> Candidate:
    return Candidate(
        entity_id=entity_id,
        entity_type=SUBNET,
        reason="dropped_from_observation",
        surface=surface,
        relation="fixture",
        subject=None,
        edge_type=None,
        parent=None,
        interval_first=None,
    )


def _context() -> FalsifyContext:
    return FalsifyContext(batch_id=str(uuid.uuid4()), statement=None)


def _falsifier(ec2: FakeEc2, *, account_id: str = ACCOUNT_ID) -> SubnetFalsifier:
    return SubnetFalsifier(session=FakeSession(ec2), account_id=account_id)


def _probe(verdict: Verdict) -> dict[str, Any]:
    assert verdict.probe is not None, "a judged verdict records its probe"
    return verdict.probe


def _assert_evidence_supports(verdicts: dict[str, Any]) -> None:
    """Core re-derives the classification from the recorded sides; every verdict must survive."""
    for case, verdict in verdicts.items():
        assert unsupported(verdict) is None, f"{case}: {unsupported(verdict)}"


@pytest.mark.django_db
class TestSubnetFalsifierFourCases:
    """Shape: ``ec2:DescribeSubnets(SubnetIds=[subnet_id])``; source id + owning account
    compared."""

    @pytest.mark.spec("req-grid-reconcile-falsifier-6")
    def test_four_cases(self) -> None:
        ec2 = FakeEc2()
        cases: dict[str, Candidate] = {}

        present_id = _create_subnet("subnet-present", name="present-subnet")
        cases[CASE_PRESENT] = _candidate(present_id)
        ec2.answer(
            "subnet-present",
            {"SubnetId": "subnet-present", "OwnerId": ACCOUNT_ID, "Tags": [{"Key": "Name", "Value": "present-subnet"}]},
        )

        dropped_id = _create_subnet("subnet-dropped")
        cases[CASE_DROPPED] = _candidate(dropped_id)
        ec2.refuse("subnet-dropped", "InvalidSubnetID.NotFound")

        forbidden_id = _create_subnet("subnet-forbidden")
        cases[CASE_FORBIDDEN] = _candidate(forbidden_id)
        ec2.refuse("subnet-forbidden", "UnauthorizedOperation")

        reborn_id = _create_subnet("subnet-reborn")
        cases[CASE_REIDENTIFIED] = _candidate(reborn_id)
        # Not a shape DescribeSubnets(SubnetIds=[...]) produces for real (see falsifiers.py's
        # module docstring) — exercises core's generic classify() wiring against a
        # found-but-different source id, the way the test contract requires every falsifier to
        # demonstrate.
        ec2.answer("subnet-reborn", {"SubnetId": "subnet-new-id", "OwnerId": ACCOUNT_ID})

        verdicts = run_four_cases(_falsifier(ec2), cases, _context())
        _assert_evidence_supports(verdicts)
        assert verdicts[CASE_PRESENT].expected == {
            "source_id": "subnet-present",
            "owner": ACCOUNT_ID,
            "name": "present-subnet",
        }
        assert _probe(verdicts[CASE_PRESENT])["owner"] == ACCOUNT_ID
        assert _probe(verdicts[CASE_DROPPED])["detail"] == NOT_FOUND_DETAIL
        assert sorted(ec2.calls) == ["subnet-dropped", "subnet-forbidden", "subnet-present", "subnet-reborn"]

    def test_empty_response_is_also_dropped(self) -> None:
        """Some AWS calls answer a missing id with an empty list instead of raising — same
        meaning as the exception path."""
        ec2 = FakeEc2()
        entity_id = _create_subnet("subnet-empty")
        ec2.empty("subnet-empty")
        [verdict] = _falsifier(ec2).batch_falsify([_candidate(entity_id)], _context())
        assert verdict.verdict == "DROPPED_FROM_OBSERVATION"
        assert unsupported(verdict) is None

    def test_account_mismatch_is_scope_unknown(self) -> None:
        """The single-account analogue of github_core's reach check: a credential resolved to a
        DIFFERENT account than the candidate's own recorded account cannot speak to its absence
        (no probe is even made)."""
        ec2 = FakeEc2()
        entity_id = _create_subnet("subnet-elsewhere", account_id=OTHER_ACCOUNT_ID)
        falsifier = _falsifier(ec2, account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([_candidate(entity_id)], _context())
        assert verdict.verdict == UNDETERMINED
        assert verdict.reason == "scope_unknown"
        assert ec2.calls == []

    def test_no_account_dimension_is_scope_unknown(self) -> None:
        ec2 = FakeEc2()
        result = create_node(SUBNET, {"subnet_id": "subnet-no-dims"})
        assert result.success
        entity_id = uuid.UUID(str(result.entity_id))
        [verdict] = _falsifier(ec2).batch_falsify([_candidate(entity_id)], _context())
        assert verdict.verdict == UNDETERMINED
        assert verdict.reason == "scope_unknown"
        assert ec2.calls == []

    def test_no_subnet_id_is_scope_unknown(self) -> None:
        """A designed-but-not-yet-collected subnet (subnet_id blank, CREATE_REQUIRED = []) has
        nothing to probe AWS for."""
        ec2 = FakeEc2()
        result = create_node(SUBNET, {"name": "not-yet-real"})
        assert result.success
        entity_id = uuid.UUID(str(result.entity_id))
        row = get_node(entity_id)
        row.entity.dimensions = {"cloud": "aws", "aws_account": ACCOUNT_ID, "aws_region": REGION}
        row.entity.save(update_fields=["dimensions"])
        [verdict] = _falsifier(ec2).batch_falsify([_candidate(entity_id)], _context())
        assert verdict.verdict == UNDETERMINED
        assert verdict.reason == "scope_unknown"

    def test_unresolvable_credential_is_undetermined_errored(self) -> None:
        entity_id = _create_subnet("subnet-no-cred")

        def _broken_session_factory() -> tuple[Any, str]:
            raise RuntimeError("no secret configured")

        falsifier = SubnetFalsifier(session_factory=_broken_session_factory)
        [verdict] = falsifier.batch_falsify([_candidate(entity_id)], _context())
        assert verdict.verdict == UNDETERMINED
        assert verdict.reason == "errored"

    def test_empty_account_id_is_scope_unknown_not_fail_open(self) -> None:
        """_scope_check must fail CLOSED on an empty credential account, not skip the
        comparison — a falsifier resolved to "" must never be read as "any account matches"."""
        ec2 = FakeEc2()
        entity_id = _create_subnet("subnet-empty-cred-account")
        falsifier = SubnetFalsifier(session=FakeSession(ec2), account_id="")
        [verdict] = falsifier.batch_falsify([_candidate(entity_id)], _context())
        assert verdict.verdict == UNDETERMINED
        assert verdict.reason == "scope_unknown"
        assert ec2.calls == []

    def test_client_construction_failure_is_undetermined_not_a_crash(self) -> None:
        """botocore can raise while BUILDING a client (bad region, broken config) before any
        network call — that must fail this one candidate closed, never escape judge() and
        blank out the rest of the batch (judge_all is a plain list comprehension)."""
        ec2 = FakeEc2()
        broken = FakeSession(ec2, breaks_with=BotoCoreError())
        ok_entity_id = _create_subnet("subnet-ok")
        broken_entity_id = _create_subnet("subnet-client-breaks")
        falsifier = SubnetFalsifier(session=broken, account_id=ACCOUNT_ID)
        verdicts = {
            v.entity_id: v
            for v in falsifier.batch_falsify([_candidate(ok_entity_id), _candidate(broken_entity_id)], _context())
        }
        for verdict in verdicts.values():
            assert verdict.verdict == UNDETERMINED
            assert verdict.reason == "errored"

    def test_rate_limited_and_generic_error_codes(self) -> None:
        ec2 = FakeEc2()
        throttled_id = _create_subnet("subnet-throttled")
        ec2.refuse("subnet-throttled", "RequestLimitExceeded")
        errored_id = _create_subnet("subnet-weird")
        ec2.refuse("subnet-weird", "InternalError")

        falsifier = _falsifier(ec2)
        verdicts = {
            v.entity_id: v
            for v in falsifier.batch_falsify([_candidate(throttled_id), _candidate(errored_id)], _context())
        }
        assert verdicts[throttled_id].verdict == UNDETERMINED
        assert verdicts[throttled_id].reason == "rate_limited"
        assert verdicts[errored_id].verdict == UNDETERMINED
        assert verdicts[errored_id].reason == "errored"


class TestProbeStatusOf:
    """The AWS error-code -> probe-status mapping, independent of any grid row."""

    def test_not_found_suffix_forms(self) -> None:
        for code in ("InvalidSubnetID.NotFound", "NoSuchBucket", "ResourceNotFoundException"):
            exc = ClientError({"Error": {"Code": code, "Message": "x"}}, "Op")
            assert probe_status_of(exc) == "not_found", code

    def test_forbidden_codes(self) -> None:
        for code in ("UnauthorizedOperation", "AccessDenied", "AccessDeniedException"):
            exc = ClientError({"Error": {"Code": code, "Message": "x"}}, "Op")
            assert probe_status_of(exc) == "forbidden", code

    def test_rate_limit_codes(self) -> None:
        for code in ("Throttling", "ThrottlingException", "RequestLimitExceeded", "TooManyRequestsException"):
            exc = ClientError({"Error": {"Code": code, "Message": "x"}}, "Op")
            assert probe_status_of(exc) == "rate_limited", code

    def test_unknown_client_error_is_errored(self) -> None:
        exc = ClientError({"Error": {"Code": "InternalError", "Message": "x"}}, "Op")
        assert probe_status_of(exc) == "errored"

    def test_error_code_of_missing_error_block(self) -> None:
        exc = ClientError({}, "Op")
        assert error_code_of(exc) == ""


class TestFalsifierManifestWiring:
    """The [falsifiers] table resolves to a real tap_grid.falsifiers.Falsifier, exactly the way
    tap_plugins.base's boot-time registration reads it (import_string + issubclass check)."""

    def test_manifest_declares_subnet_falsifier(self) -> None:
        assert PLUGIN_ROOT is not None, "plugin source tree not found"
        manifest_path = next((PLUGIN_ROOT / "tap_plugin").glob("*/tap-plugin.toml"))
        manifest = tomllib.loads(manifest_path.read_text())
        falsifiers = manifest.get("falsifiers", {})
        assert falsifiers == {
            SUBNET: "tap_plugin.aws_core.falsifiers.SubnetFalsifier",
            "aws_core__aws_organizational_unit": "tap_plugin.aws_core.falsifiers.OrganizationalUnitFalsifier",
            "aws_core__aws_account": "tap_plugin.aws_core.falsifiers.AccountFalsifier",
        }
        # Every falsifier entry must name a type this same plugin declares in [models]
        # (tap_plugins/manifest.py::_parse_falsifiers) — the check the manifest parser itself
        # enforces at load, reasserted here directly against the TOML.
        for entity_type in falsifiers:
            assert entity_type in manifest.get("models", {})

    def test_subnet_is_the_type_containment_coverage_marks_reconcilable(self) -> None:
        """The evidence behind picking Subnet over VPC: Vpc.CONTAINMENT_EDGES names
        PARTITIONED_INTO_SUBNET__aws_core, and that edge's declared target is
        aws_core__aws_subnet — exactly the shape
        tap_plugins/validate/service.py::_check_falsifier_coverage reads to decide which types
        are reconcilable."""
        from tap_plugin.aws_core.models.vpc import Vpc

        assert Vpc.CONTAINMENT_EDGES == ("PARTITIONED_INTO_SUBNET__aws_core",)
        assert PLUGIN_ROOT is not None, "plugin source tree not found"
        edge_path = next((PLUGIN_ROOT / "tap_plugin").glob("*/edges/PARTITIONED_INTO_SUBNET.edge.json"))
        import json

        edge = json.loads(edge_path.read_text())
        assert edge["targets"] == [SUBNET]

    def test_class_path_resolves_to_a_falsifier_subclass(self) -> None:
        cls = import_string("tap_plugin.aws_core.falsifiers.SubnetFalsifier")
        assert isinstance(cls, type) and issubclass(cls, Falsifier)

    def test_registers_and_instantiates_with_no_arguments(self) -> None:
        """Boot calls ``cls()`` with zero arguments (tap_plugins/base.py::
        _register_falsifiers_from_manifest) — every constructor argument must default.

        The app's own ``ready()`` (``AwsCoreConfig`` -> ``TapPluginConfig.ready`` ->
        ``_register_falsifiers_from_manifest``) has typically already registered
        ``aws_core__aws_subnet`` once for this whole test process by the time this test runs,
        so this asserts against whatever is ALREADY there rather than re-registering (which
        would collide with core's own "already registered" guard) — falling back to a genuine
        register/unregister round-trip only when nothing beat it to it.
        """
        cls = import_string("tap_plugin.aws_core.falsifiers.SubnetFalsifier")
        existing = get_falsifier(SUBNET)
        if existing is not None:
            assert isinstance(existing, cls)
            return
        register_falsifier(SUBNET, cls())
        try:
            assert isinstance(get_falsifier(SUBNET), cls)
        finally:
            unregister_falsifier(SUBNET)

    def test_wrong_type_would_be_refused(self) -> None:
        # A type never registered under any real entity type, so this exercises the isinstance
        # gate (which core checks BEFORE the already-registered gate) without depending on
        # whether the app has already registered Subnet's own falsifier in this process.
        with pytest.raises(ImproperlyConfigured):
            register_falsifier("aws_core__not_a_real_type_for_this_test", object())  # type: ignore[arg-type]


class TestAccountAndOrganizationDeclareNoContainment:
    """tap-plugin-aws-core#42: AwsAccount is the root of every other AWS resource this plugin
    models and deliberately declares zero CONTAINMENT_EDGES of its own — see the reasoning on the
    model and in tap_plugin/aws_core/falsifiers.py's module docstring. This is a regression guard
    against silently reversing that decision, not a live behavior test.

    AwsOrganization is different as of tap-plugin-aws-core#50: it now declares the two
    Organizations-tree containment edges (see TestOrganizationContainment below), so what it
    guards here is only that AwsAccount still declares none — an account is a containment TARGET
    (ENROLLS_ACCOUNT), never a source."""

    def test_aws_account_declares_no_containment(self) -> None:
        assert AwsAccount.CONTAINMENT_EDGES == ()

    def test_aws_account_has_a_registered_falsifier(self) -> None:
        from tap_plugin.aws_core.falsifiers import AccountFalsifier

        assert isinstance(get_falsifier(AwsAccount.ENTITY_TYPE), AccountFalsifier)


class TestOrganizationContainment:
    """tap-plugin-aws-core#50: AwsOrganization contains its OUs and its member accounts through
    two NEW parent -> child edges, not the existing child -> parent NESTED_UNDER_PARENT
    reference — see the CONTAINMENT_EDGES comment on models/aws_organization.py."""

    def test_aws_organization_declares_the_two_new_containment_edges(self) -> None:
        assert AwsOrganization.CONTAINMENT_EDGES == (
            "PARTITIONED_INTO_OU__aws_core",
            "ENROLLS_ACCOUNT__aws_core",
        )

    def test_aws_organization_has_no_falsifier(self) -> None:
        """Nothing contains the organization itself."""
        assert get_falsifier(AwsOrganization.ENTITY_TYPE) is None
