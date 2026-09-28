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
from unittest.mock import MagicMock

import pytest
import tomllib
from botocore.exceptions import BotoCoreError, ClientError
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string
from tap_plugin.aws_core.falsifiers import (
    NOT_FOUND_DETAIL,
    AccountFalsifier,
    Ec2InstanceFalsifier,
    IamPolicyFalsifier,
    IamRoleFalsifier,
    IamUserFalsifier,
    S3BucketFalsifier,
    SecurityGroupFalsifier,
    SubnetFalsifier,
    VpcFalsifier,
    _enabled_regions,
    _iam_probe_status_of,
    _s3_probe_status_of,
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
    DROPPED_FROM_OBSERVATION,
    PRESENT_AT_PROBE,
    REIDENTIFIED,
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
from tap_grid.services import create_edge, create_node, delete_node, get_node

SUBNET = "aws_core__aws_subnet"
VPC = "aws_core__aws_vpc"
SECURITY_GROUP = "aws_core__aws_security_group"
EC2_INSTANCE = "aws_core__aws_ec2_instance"
S3_BUCKET = "aws_core__aws_s3_bucket"
IAM_ROLE = "aws_core__aws_iam_role"
IAM_USER = "aws_core__aws_iam_user"
IAM_POLICY = "aws_core__aws_iam_policy"
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

    def test_manifest_declares_the_compute_network_falsifiers(self) -> None:
        assert PLUGIN_ROOT is not None, "plugin source tree not found"
        manifest_path = next((PLUGIN_ROOT / "tap_plugin").glob("*/tap-plugin.toml"))
        manifest = tomllib.loads(manifest_path.read_text())
        falsifiers = manifest.get("falsifiers", {})
        assert falsifiers == {
            SUBNET: "tap_plugin.aws_core.falsifiers.SubnetFalsifier",
            VPC: "tap_plugin.aws_core.falsifiers.VpcFalsifier",
            SECURITY_GROUP: "tap_plugin.aws_core.falsifiers.SecurityGroupFalsifier",
            EC2_INSTANCE: "tap_plugin.aws_core.falsifiers.Ec2InstanceFalsifier",
            "aws_core__aws_organizational_unit": "tap_plugin.aws_core.falsifiers.OrganizationalUnitFalsifier",
            "aws_core__aws_account": "tap_plugin.aws_core.falsifiers.AccountFalsifier",
            S3_BUCKET: "tap_plugin.aws_core.falsifiers.S3BucketFalsifier",
            IAM_ROLE: "tap_plugin.aws_core.falsifiers.IamRoleFalsifier",
            IAM_USER: "tap_plugin.aws_core.falsifiers.IamUserFalsifier",
            IAM_POLICY: "tap_plugin.aws_core.falsifiers.IamPolicyFalsifier",
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
        for name in (
            "SubnetFalsifier",
            "VpcFalsifier",
            "SecurityGroupFalsifier",
            "Ec2InstanceFalsifier",
            "S3BucketFalsifier",
            "IamRoleFalsifier",
            "IamUserFalsifier",
            "IamPolicyFalsifier",
        ):
            cls = import_string(f"tap_plugin.aws_core.falsifiers.{name}")
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

    @staticmethod
    def _org_and_enrolled_account(org_id: str, account_id: str) -> tuple[Any, Any]:
        org_result = create_node(AwsOrganization.ENTITY_TYPE, {"name": "org", "organization_id": org_id})
        assert org_result.success, org_result.errors
        account_result = create_node(AwsAccount.ENTITY_TYPE, {"name": "acct", "account_id": account_id})
        assert account_result.success, account_result.errors
        org_row = get_node(org_result.entity_id)
        account_row = get_node(account_result.entity_id)
        create_edge(org_row.entity, account_row.entity, "ENROLLS_ACCOUNT__aws_core")
        return org_row.entity.id, account_row.entity.id

    @pytest.mark.django_db
    def test_plain_delete_does_not_cascade_to_accounts(self) -> None:
        """cascade defaults to "none": deleting the org record alone leaves a live account
        untouched — the ordinary, non-destructive shape of retiring an org record."""
        org_id, account_id = self._org_and_enrolled_account("o-plaindel0001", "555500001111")

        result = delete_node(org_id)
        assert result.success, result.errors

        assert get_node(account_id).entity.deleted_at is None, "a plain delete must never cascade"

    @pytest.mark.django_db
    def test_cascade_contained_delete_does_tombstone_enrolled_accounts(self) -> None:
        """The examined, accepted consequence documented on the model: an EXPLICIT
        cascade="contained" delete of the organization does retire every account it enrolls.
        This is a deliberate opt-in on the caller's part, never a side effect of retiring the org
        record alone (see the previous test) or of anything reconcile does on its own — nothing
        ever falsifies AwsOrganization itself."""
        org_id, account_id = self._org_and_enrolled_account("o-cascadel0001", "555500002222")

        result = delete_node(org_id, cascade="contained")
        assert result.success, result.errors

        # get_node's manager is live-only (a tombstoned node 404s through it, by design), so the
        # tombstone itself is read straight off the spine.
        from tap_grid.models import Entity

        assert Entity.objects.get(pk=account_id).deleted_at is not None


# ---------------------------------------------------------------------------
# tap-plugin-aws-core#43 — VPC / security group / EC2 instance, the region fallback, and the
# merged SubnetFalsifier's Local/Wavelength-Zone hint. The fake below is table-driven and keyed
# by (region, method, id) so a test can arrange a different answer per region.
# ---------------------------------------------------------------------------


class TableEc2:
    """A region-keyed ec2 stand-in: ``answers[(region, method, id)]`` is a response dict or an
    exception. ``calls`` records ``(region, method, id)`` in order."""

    def __init__(self) -> None:
        self.answers: dict[tuple[str, str, str], dict[str, Any] | Exception] = {}
        self.calls: list[tuple[str, str, str]] = []

    def answer(self, region: str, method: str, source_id: str, payload: dict[str, Any]) -> None:
        self.answers[(region, method, source_id)] = payload

    def refuse(self, region: str, method: str, source_id: str, code: str) -> None:
        self.answers[(region, method, source_id)] = ClientError({"Error": {"Code": code, "Message": "x"}}, method)

    def call(self, region: str, method: str, source_id: str) -> dict[str, Any]:
        self.calls.append((region, method, source_id))
        response = self.answers.get((region, method, source_id))
        if response is None:
            raise AssertionError(f"TableEc2: nothing configured for {(region, method, source_id)!r}")
        if isinstance(response, Exception):
            raise response
        return response


class _RegionClient:
    def __init__(self, table: TableEc2, region: str) -> None:
        self._table, self._region = table, region

    def describe_vpcs(self, VpcIds: list[str]) -> dict[str, Any]:  # noqa: N803
        return self._table.call(self._region, "describe_vpcs", VpcIds[0])

    def describe_subnets(self, SubnetIds: list[str]) -> dict[str, Any]:  # noqa: N803
        return self._table.call(self._region, "describe_subnets", SubnetIds[0])

    def describe_security_groups(self, GroupIds: list[str]) -> dict[str, Any]:  # noqa: N803
        return self._table.call(self._region, "describe_security_groups", GroupIds[0])

    def describe_instances(self, InstanceIds: list[str]) -> dict[str, Any]:  # noqa: N803
        return self._table.call(self._region, "describe_instances", InstanceIds[0])


class RegionalSession:
    """``.client('ec2', region_name=...)`` returns a client bound to that region; a region in
    ``unbuildable`` raises ``BotoCoreError`` at construction, like a bad region name."""

    def __init__(self, table: TableEc2, *, unbuildable: frozenset[str] = frozenset()) -> None:
        self._table, self._unbuildable = table, unbuildable
        self.regions_asked: list[str] = []

    def client(self, service: str, region_name: str | None = None) -> Any:
        assert service == "ec2" and region_name
        self.regions_asked.append(region_name)
        if region_name in self._unbuildable:
            raise BotoCoreError()
        return _RegionClient(self._table, region_name)


def _create(
    entity_type: str,
    payload: dict[str, Any],
    *,
    region: str | None = REGION,
    account_id: str | None = ACCOUNT_ID,
) -> uuid.UUID:
    """A real grid row stamped the way the collector stamps it. ``region=None`` omits the
    ``aws_region`` dimension (a row the fallback has to place)."""
    result = create_node(entity_type, payload)
    assert result.success, f"create_node failed: {result.errors}"
    assert result.entity_id is not None
    entity_id = uuid.UUID(str(result.entity_id))
    dimensions: dict[str, str] = {"cloud": "aws"}
    if account_id is not None:
        dimensions["aws_account"] = account_id
    if region is not None:
        dimensions["aws_region"] = region
    row = get_node(entity_id)
    row.entity.dimensions = dimensions
    row.entity.save(update_fields=["dimensions"])
    return entity_id


def _candidate_of(entity_id: uuid.UUID, entity_type: str) -> Candidate:
    return Candidate(
        entity_id=entity_id,
        entity_type=entity_type,
        reason="dropped_from_observation",
        surface=0,
        relation="fixture",
        subject=None,
        edge_type=None,
        parent=None,
        interval_first=None,
    )


def _instance_response(instance_id: str, state: str, owner: str = ACCOUNT_ID) -> dict[str, Any]:
    return {
        "Reservations": [{"OwnerId": owner, "Instances": [{"InstanceId": instance_id, "State": {"Name": state}}]}]
    }


@pytest.mark.django_db
class TestComputeNetworkFourCases:
    """``run_four_cases`` for each of the types #43 adds beside Subnet."""

    @pytest.mark.spec("req-grid-reconcile-falsifier-6")
    def test_vpc(self) -> None:
        table = TableEc2()
        cases: dict[str, Candidate] = {}
        for case, vpc_id in (
            (CASE_PRESENT, "vpc-present"),
            (CASE_DROPPED, "vpc-dropped"),
            (CASE_FORBIDDEN, "vpc-forbidden"),
            (CASE_REIDENTIFIED, "vpc-reborn"),
        ):
            cases[case] = _candidate_of(_create(VPC, {"vpc_id": vpc_id}), VPC)
        table.answer(REGION, "describe_vpcs", "vpc-present", {"Vpcs": [{"VpcId": "vpc-present", "OwnerId": ACCOUNT_ID}]})
        table.refuse(REGION, "describe_vpcs", "vpc-dropped", "InvalidVpcID.NotFound")
        table.refuse(REGION, "describe_vpcs", "vpc-forbidden", "UnauthorizedOperation")
        table.answer(REGION, "describe_vpcs", "vpc-reborn", {"Vpcs": [{"VpcId": "vpc-new", "OwnerId": ACCOUNT_ID}]})
        falsifier = VpcFalsifier(session=RegionalSession(table), account_id=ACCOUNT_ID)
        _assert_evidence_supports(run_four_cases(falsifier, cases, _context()))

    @pytest.mark.spec("req-grid-reconcile-falsifier-6")
    def test_security_group(self) -> None:
        table = TableEc2()
        cases: dict[str, Candidate] = {}
        for case, group_id in (
            (CASE_PRESENT, "sg-present"),
            (CASE_DROPPED, "sg-dropped"),
            (CASE_FORBIDDEN, "sg-forbidden"),
            (CASE_REIDENTIFIED, "sg-reborn"),
        ):
            cases[case] = _candidate_of(_create(SECURITY_GROUP, {"group_id": group_id}), SECURITY_GROUP)
        table.answer(
            REGION, "describe_security_groups", "sg-present", {"SecurityGroups": [{"GroupId": "sg-present", "OwnerId": ACCOUNT_ID}]}
        )
        table.refuse(REGION, "describe_security_groups", "sg-dropped", "InvalidGroup.NotFound")
        table.refuse(REGION, "describe_security_groups", "sg-forbidden", "UnauthorizedOperation")
        table.answer(
            REGION, "describe_security_groups", "sg-reborn", {"SecurityGroups": [{"GroupId": "sg-new", "OwnerId": ACCOUNT_ID}]}
        )
        falsifier = SecurityGroupFalsifier(session=RegionalSession(table), account_id=ACCOUNT_ID)
        _assert_evidence_supports(run_four_cases(falsifier, cases, _context()))

    @pytest.mark.spec("req-grid-reconcile-falsifier-6")
    def test_ec2_instance(self) -> None:
        table = TableEc2()
        cases: dict[str, Candidate] = {}
        for case, instance_id in (
            (CASE_PRESENT, "i-present"),
            (CASE_DROPPED, "i-purged"),
            (CASE_FORBIDDEN, "i-forbidden"),
            (CASE_REIDENTIFIED, "i-reborn"),
        ):
            cases[case] = _candidate_of(_create(EC2_INSTANCE, {"instance_id": instance_id}), EC2_INSTANCE)
        table.answer(REGION, "describe_instances", "i-present", _instance_response("i-present", "running"))
        table.refuse(REGION, "describe_instances", "i-purged", "InvalidInstanceID.NotFound")
        table.refuse(REGION, "describe_instances", "i-forbidden", "UnauthorizedOperation")
        table.answer(REGION, "describe_instances", "i-reborn", _instance_response("i-new", "running"))
        falsifier = Ec2InstanceFalsifier(session=RegionalSession(table), account_id=ACCOUNT_ID)
        _assert_evidence_supports(run_four_cases(falsifier, cases, _context()))


@pytest.mark.django_db
class TestEc2InstanceStates:
    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_terminated_is_dropped(self) -> None:
        table = TableEc2()
        entity_id = _create(EC2_INSTANCE, {"instance_id": "i-terminated"})
        table.answer(REGION, "describe_instances", "i-terminated", _instance_response("i-terminated", "terminated"))
        falsifier = Ec2InstanceFalsifier(session=RegionalSession(table), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([_candidate_of(entity_id, EC2_INSTANCE)], _context())
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        assert "terminated" in _probe(verdict)["detail"]
        assert unsupported(verdict) is None

    @pytest.mark.parametrize("state", ["pending", "running", "shutting-down", "stopping", "stopped"])
    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_every_non_terminated_state_is_present_not_gone(self, state: str) -> None:
        """Stopped is not gone — only not running."""
        table = TableEc2()
        entity_id = _create(EC2_INSTANCE, {"instance_id": f"i-{state}"})
        table.answer(REGION, "describe_instances", f"i-{state}", _instance_response(f"i-{state}", state))
        falsifier = Ec2InstanceFalsifier(session=RegionalSession(table), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([_candidate_of(entity_id, EC2_INSTANCE)], _context())
        assert verdict.verdict == PRESENT_AT_PROBE

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_a_terminated_response_naming_a_different_instance_is_not_trusted(self) -> None:
        """The terminated shortcut synthesizes ``not_found``, which bypasses classify()'s own
        identity comparison, so it must check the InstanceId itself: a mismatch falls through to
        the ordinary found path and comes out REIDENTIFIED, never a silent retirement."""
        table = TableEc2()
        entity_id = _create(EC2_INSTANCE, {"instance_id": "i-expected"})
        table.answer(REGION, "describe_instances", "i-expected", _instance_response("i-other", "terminated"))
        falsifier = Ec2InstanceFalsifier(session=RegionalSession(table), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([_candidate_of(entity_id, EC2_INSTANCE)], _context())
        assert verdict.verdict == REIDENTIFIED
        assert unsupported(verdict) is None

    def test_no_owner_on_a_found_resource_is_errored_not_a_crash(self) -> None:
        """The grid holds an owner, so a found probe with none cannot be classified
        (``incomplete``); answered UNDETERMINED(errored), never raised out of verdict_from_probe."""
        table = TableEc2()
        entity_id = _create(VPC, {"vpc_id": "vpc-no-owner"})
        table.answer(REGION, "describe_vpcs", "vpc-no-owner", {"Vpcs": [{"VpcId": "vpc-no-owner"}]})
        falsifier = VpcFalsifier(session=RegionalSession(table), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([_candidate_of(entity_id, VPC)], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "errored")


@pytest.mark.django_db
class TestRegionResolution:
    """Dimension first, then the type's own hint, then a fallback sweep that can only find."""

    def test_the_dimension_is_used_and_the_sweep_is_never_consulted(self) -> None:
        table = TableEc2()
        entity_id = _create(VPC, {"vpc_id": "vpc-dim"}, region="eu-west-1")
        table.refuse("eu-west-1", "describe_vpcs", "vpc-dim", "InvalidVpcID.NotFound")

        def _never(_session: Any) -> list[str]:
            raise AssertionError("the sweep must not run when the row records its region")

        session = RegionalSession(table)
        falsifier = VpcFalsifier(session=session, account_id=ACCOUNT_ID, region_sweep=_never)
        [verdict] = falsifier.batch_falsify([_candidate_of(entity_id, VPC)], _context())
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        assert session.regions_asked == ["eu-west-1"]

    @pytest.mark.parametrize(
        ("zone", "region"),
        [
            ("us-east-1a", "us-east-1"),
            ("us-west-2-lax-1a", "us-west-2"),  # Local Zone: az[:-1] would be us-west-2-lax-1
            ("us-east-1-wl1-bos-wlz-1", "us-east-1"),  # Wavelength Zone
            ("us-gov-west-1a", "us-gov-west-1"),
        ],
    )
    def test_a_subnet_with_no_region_dimension_uses_its_availability_zone(self, zone: str, region: str) -> None:
        table = TableEc2()
        entity_id = _create(SUBNET, {"subnet_id": "subnet-az", "availability_zone": zone}, region=None)
        table.refuse(region, "describe_subnets", "subnet-az", "InvalidSubnetID.NotFound")
        session = RegionalSession(table)
        falsifier = SubnetFalsifier(session=session, account_id=ACCOUNT_ID, region_sweep=lambda _s: [])
        [verdict] = falsifier.batch_falsify([_candidate_of(entity_id, SUBNET)], _context())
        assert session.regions_asked == [region]
        assert verdict.verdict == DROPPED_FROM_OBSERVATION, "an AZ-derived region is the row's own, so it is trusted"

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_a_fallback_sweep_can_find_the_resource(self) -> None:
        table = TableEc2()
        entity_id = _create(VPC, {"vpc_id": "vpc-elsewhere"}, region=None)
        table.refuse("us-east-1", "describe_vpcs", "vpc-elsewhere", "InvalidVpcID.NotFound")
        table.answer("eu-west-1", "describe_vpcs", "vpc-elsewhere", {"Vpcs": [{"VpcId": "vpc-elsewhere", "OwnerId": ACCOUNT_ID}]})
        session = RegionalSession(table)
        falsifier = VpcFalsifier(
            session=session, account_id=ACCOUNT_ID, region_sweep=lambda _s: ["us-east-1", "eu-west-1", "ap-south-1"]
        )
        [verdict] = falsifier.batch_falsify([_candidate_of(entity_id, VPC)], _context())
        assert verdict.verdict == PRESENT_AT_PROBE
        assert session.regions_asked == ["us-east-1", "eu-west-1"], "the sweep stops at the first authoritative answer"

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_a_clean_fallback_sweep_is_undetermined_never_dropped(self) -> None:
        """regions_trustworthy=False: every swept region says not-found and it still is not
        evidence of absence, because the sweep cannot show where the row was collected."""
        table = TableEc2()
        entity_id = _create(VPC, {"vpc_id": "vpc-maybe-elsewhere"}, region=None)
        for region in ("us-east-1", "eu-west-1"):
            table.refuse(region, "describe_vpcs", "vpc-maybe-elsewhere", "InvalidVpcID.NotFound")
        falsifier = VpcFalsifier(
            session=RegionalSession(table), account_id=ACCOUNT_ID, region_sweep=lambda _s: ["us-east-1", "eu-west-1"]
        )
        [verdict] = falsifier.batch_falsify([_candidate_of(entity_id, VPC)], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "may only find, never drop" in verdict.note

    @pytest.mark.spec("req-grid-reconcile-absence-states")
    def test_a_terminated_answer_found_by_a_fallback_sweep_is_also_not_dropped(self) -> None:
        table = TableEc2()
        entity_id = _create(EC2_INSTANCE, {"instance_id": "i-swept"}, region=None)
        table.answer("us-east-1", "describe_instances", "i-swept", _instance_response("i-swept", "terminated"))
        falsifier = Ec2InstanceFalsifier(
            session=RegionalSession(table), account_id=ACCOUNT_ID, region_sweep=lambda _s: ["us-east-1"]
        )
        [verdict] = falsifier.batch_falsify([_candidate_of(entity_id, EC2_INSTANCE)], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")

    def test_a_forbidden_region_in_the_sweep_is_forbidden(self) -> None:
        table = TableEc2()
        entity_id = _create(VPC, {"vpc_id": "vpc-hidden"}, region=None)
        table.refuse("us-east-1", "describe_vpcs", "vpc-hidden", "InvalidVpcID.NotFound")
        table.refuse("eu-west-1", "describe_vpcs", "vpc-hidden", "UnauthorizedOperation")
        falsifier = VpcFalsifier(
            session=RegionalSession(table), account_id=ACCOUNT_ID, region_sweep=lambda _s: ["us-east-1", "eu-west-1"]
        )
        [verdict] = falsifier.batch_falsify([_candidate_of(entity_id, VPC)], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "forbidden")

    def test_no_region_and_no_sweep_is_scope_unknown_without_a_call(self) -> None:
        table = TableEc2()
        entity_id = _create(VPC, {"vpc_id": "vpc-nowhere"}, region=None)
        session = RegionalSession(table)
        falsifier = VpcFalsifier(session=session, account_id=ACCOUNT_ID, region_sweep=lambda _s: [])
        [verdict] = falsifier.batch_falsify([_candidate_of(entity_id, VPC)], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert session.regions_asked == []

    def test_a_sweep_that_cannot_be_resolved_is_scope_unknown_not_a_crash(self) -> None:
        def _boom(_session: Any) -> list[str]:
            raise RuntimeError("no secret configured")

        entity_id = _create(VPC, {"vpc_id": "vpc-no-sweep"}, region=None)
        falsifier = VpcFalsifier(session=RegionalSession(TableEc2()), account_id=ACCOUNT_ID, region_sweep=_boom)
        [verdict] = falsifier.batch_falsify([_candidate_of(entity_id, VPC)], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")

    def test_the_sweep_is_resolved_once_per_run(self) -> None:
        calls: list[int] = []

        def _sweep(_session: Any) -> list[str]:
            calls.append(1)
            return ["us-east-1"]

        table = TableEc2()
        candidates = []
        for n in range(3):
            entity_id = _create(VPC, {"vpc_id": f"vpc-{n}"}, region=None)
            table.refuse("us-east-1", "describe_vpcs", f"vpc-{n}", "InvalidVpcID.NotFound")
            candidates.append(_candidate_of(entity_id, VPC))
        falsifier = VpcFalsifier(session=RegionalSession(table), account_id=ACCOUNT_ID, region_sweep=_sweep)
        falsifier.batch_falsify(candidates, _context())
        assert len(calls) == 1
        falsifier.batch_falsify(candidates, _context())
        assert len(calls) == 2, "a new run re-resolves the sweep"

    def test_a_region_that_cannot_build_a_client_degrades_only_that_candidate(self) -> None:
        table = TableEc2()
        good = _create(SUBNET, {"subnet_id": "subnet-good"}, region="us-east-1")
        bad = _create(SUBNET, {"subnet_id": "subnet-bad"}, region="not-a-region")
        table.refuse("us-east-1", "describe_subnets", "subnet-good", "InvalidSubnetID.NotFound")
        falsifier = SubnetFalsifier(
            session=RegionalSession(table, unbuildable=frozenset({"not-a-region"})), account_id=ACCOUNT_ID
        )
        verdicts = {v.entity_id: v for v in falsifier.batch_falsify([_candidate(bad), _candidate(good)], _context())}
        assert verdicts[good].verdict == DROPPED_FROM_OBSERVATION
        assert (verdicts[bad].verdict, verdicts[bad].reason) == (UNDETERMINED, "errored")

    def test_account_mismatch_refuses_before_any_region_work(self) -> None:
        entity_id = _create(VPC, {"vpc_id": "vpc-other-acct"}, region=None, account_id=OTHER_ACCOUNT_ID)

        def _never(_session: Any) -> list[str]:
            raise AssertionError("a scope-refused candidate must not trigger the sweep")

        falsifier = VpcFalsifier(session=RegionalSession(TableEc2()), account_id=ACCOUNT_ID, region_sweep=_never)
        [verdict] = falsifier.batch_falsify([_candidate_of(entity_id, VPC)], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")


class _DescribeRegionsSession:
    def __init__(self, *, regions: list[dict[str, str]] | None = None, raises: Exception | None = None) -> None:
        self._regions, self._raises = regions, raises
        self.anchors: list[str] = []

    def client(self, service: str, region_name: str) -> Any:
        assert service == "ec2"
        self.anchors.append(region_name)
        return self

    def describe_regions(self, AllRegions: bool) -> dict[str, Any]:  # noqa: N803
        assert AllRegions is False
        if self._raises is not None:
            raise self._raises
        return {"Regions": self._regions or []}


class TestEnabledRegions:
    def test_returns_the_enabled_regions_sorted_and_deduplicated(self) -> None:
        session = _DescribeRegionsSession(
            regions=[{"RegionName": "us-west-2"}, {"RegionName": "us-east-1"}, {"RegionName": "us-east-1"}]
        )
        assert _enabled_regions(session, ["us-east-1"]) == ["us-east-1", "us-west-2"]
        assert session.anchors == ["us-east-1"]

    def test_a_wider_enabled_set_than_the_configured_scope_is_used(self) -> None:
        session = _DescribeRegionsSession(regions=[{"RegionName": "us-west-2"}, {"RegionName": "eu-west-1"}])
        assert _enabled_regions(session, ["us-west-2"]) == ["eu-west-1", "us-west-2"]

    def test_falls_back_to_the_configured_scope_on_failure_or_empty(self) -> None:
        assert _enabled_regions(_DescribeRegionsSession(raises=BotoCoreError()), ["a", "b"]) == ["a", "b"]
        assert _enabled_regions(_DescribeRegionsSession(regions=[]), ["a"]) == ["a"]


# ---------------------------------------------------------------------------
# Storage + IAM (aws-core-tap#41): present/dropped/forbidden proof cases against a mocked
# boto3 session, the S3 403/404 tie-break (AWS's own HeadBucket documentation makes 404 exactly
# as ambiguous as 403), the list_buckets partial-page/failure-caching guards, the IAM name/ARN
# binding check, and the customer-managed-only scope of the IAM policy falsifier. Account
# correctness for all four types is `_scope_check` (the shared foundation), exercised here the
# same way TestSubnetFalsifierFourCases exercises it for Subnet.
#
# S3 and customer-managed IAM policies can never answer REIDENTIFIED (see falsifiers.py's
# S3BucketFalsifier / IamPolicyFalsifier docstrings for exactly why each is structurally
# incapable of it), so `run_four_cases` (which hard-requires a reidentified case) is not used for
# them; present/dropped/forbidden are proven individually instead. IAM role/user CAN answer it —
# for a delete+recreate under a different path, same name — and that case is tested directly.
# ---------------------------------------------------------------------------


def _dimensioned(type_slug: str, payload: dict[str, Any], *, account_id: str = ACCOUNT_ID, region: str = "global") -> uuid.UUID:
    """A grid row created through the service layer, then stamped with the collector's own
    dimensions shape (``_create_subnet``'s pattern, generalised) — the signal `_scope_check`
    reads. ``region="global"`` for IAM/S3: neither is regional for the calls this module makes."""
    result = create_node(type_slug, payload)
    assert result.success, f"create_node failed: {result.errors}"
    assert result.entity_id is not None
    entity_id = uuid.UUID(str(result.entity_id))
    row = get_node(entity_id)
    row.entity.dimensions = {"cloud": "aws", "aws_account": account_id, "aws_region": region}
    row.entity.save(update_fields=["dimensions"])
    return entity_id


def _iam_candidate(entity_id: uuid.UUID, entity_type: str, *, surface: int = 0) -> Candidate:
    return Candidate(
        entity_id=entity_id,
        entity_type=entity_type,
        reason="dropped_from_observation",
        surface=surface,
        relation="fixture",
        subject=None,
        edge_type=None,
        parent=None,
        interval_first=None,
    )


def _client_error(code: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, op)


def _mock_session(service: str, client: Any) -> Any:
    """A boto3-session-shaped double for a single service, matching `FakeSession`'s own
    region-required assertion."""
    session = MagicMock()

    def client_for(svc: str, region_name: str | None = None) -> Any:
        assert svc == service, f"expected {service!r}, asked for {svc!r}"
        assert region_name, "falsifier must pass a region"
        return client

    session.client.side_effect = client_for
    return session


@pytest.mark.django_db
class TestIamRoleFalsifier:
    @staticmethod
    def _role(name: str, arn: str, *, account_id: str = ACCOUNT_ID) -> Candidate:
        rid = _dimensioned(IAM_ROLE, {"name": name, "role_arn": arn}, account_id=account_id)
        return _iam_candidate(rid, IAM_ROLE)

    def test_present(self) -> None:
        candidate = self._role("present", f"arn:aws:iam::{ACCOUNT_ID}:role/present")
        client = MagicMock()
        client.get_role.return_value = {
            "Role": {"Arn": f"arn:aws:iam::{ACCOUNT_ID}:role/present", "RoleName": "present"}
        }
        falsifier = IamRoleFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == PRESENT_AT_PROBE
        assert unsupported(verdict) is None

    def test_a_path_change_on_the_same_name_is_reidentified(self) -> None:
        # get_role looks up by RoleName ALONE (no path in the request), and IAM role names are
        # unique per account across every path — so a delete+recreate under a DIFFERENT path,
        # same name, is genuinely detectable: the response's Arn disagrees with the grid's.
        candidate = self._role("app-role", f"arn:aws:iam::{ACCOUNT_ID}:role/old-path/app-role")
        client = MagicMock()
        client.get_role.return_value = {
            "Role": {"Arn": f"arn:aws:iam::{ACCOUNT_ID}:role/new-path/app-role", "RoleName": "app-role"}
        }
        falsifier = IamRoleFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == REIDENTIFIED
        assert unsupported(verdict) is None

    def test_dropped(self) -> None:
        candidate = self._role("dropped", f"arn:aws:iam::{ACCOUNT_ID}:role/dropped")
        client = MagicMock()
        client.get_role.side_effect = _client_error("NoSuchEntity", "GetRole")
        falsifier = IamRoleFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        assert unsupported(verdict) is None

    def test_no_dimension_refuses_before_any_probe(self) -> None:
        rid = _dimensioned(IAM_ROLE, {"name": "dropped", "role_arn": f"arn:aws:iam::{ACCOUNT_ID}:role/dropped"})
        row = get_node(rid)
        row.entity.dimensions = {}
        row.entity.save(update_fields=["dimensions"])
        candidate = _iam_candidate(rid, IAM_ROLE)
        client = MagicMock()
        falsifier = IamRoleFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        client.get_role.assert_not_called()

    def test_wrong_account_refuses_before_any_probe_even_when_the_call_would_hit(self) -> None:
        # Without `_scope_check` running first, a credential for the WRONG account could still
        # successfully call get_role and find ITS OWN unrelated same-named role. The gate must
        # refuse before the call is ever made, so `get_role.return_value` here is never reached.
        candidate = self._role("dropped", f"arn:aws:iam::{ACCOUNT_ID}:role/dropped", account_id=ACCOUNT_ID)
        client = MagicMock()
        client.get_role.return_value = {
            "Role": {"Arn": f"arn:aws:iam::{OTHER_ACCOUNT_ID}:role/dropped", "RoleName": "dropped"}
        }
        falsifier = IamRoleFalsifier(session=_mock_session("iam", client), account_id=OTHER_ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        client.get_role.assert_not_called()

    def test_a_name_not_matching_its_own_arns_resource_name_refuses_before_any_probe(self) -> None:
        # get_role takes RoleName, never the ARN: if the grid's two independently-stored fields
        # have drifted apart, querying by `name` would ask about a DIFFERENT role than the one
        # this ARN claims to be.
        candidate = self._role("wrong-name", f"arn:aws:iam::{ACCOUNT_ID}:role/actual-name")
        client = MagicMock()
        falsifier = IamRoleFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "does not match the resource name" in verdict.note
        client.get_role.assert_not_called()

    def test_a_path_qualified_arn_still_binds_to_its_trailing_name(self) -> None:
        candidate = self._role("app-role", f"arn:aws:iam::{ACCOUNT_ID}:role/service-role/app-role")
        client = MagicMock()
        client.get_role.return_value = {
            "Role": {"Arn": f"arn:aws:iam::{ACCOUNT_ID}:role/service-role/app-role", "RoleName": "app-role"}
        }
        falsifier = IamRoleFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == PRESENT_AT_PROBE
        client.get_role.assert_called_once_with(RoleName="app-role")

    def test_forbidden(self) -> None:
        candidate = self._role("forbidden", f"arn:aws:iam::{ACCOUNT_ID}:role/forbidden")
        client = MagicMock()
        client.get_role.side_effect = _client_error("AccessDenied", "GetRole")
        falsifier = IamRoleFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "forbidden")
        assert unsupported(verdict) is None

    def test_a_row_without_an_arn_is_not_answered(self) -> None:
        rid = _dimensioned(IAM_ROLE, {"name": "legacy"})
        client = MagicMock()
        falsifier = IamRoleFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([_iam_candidate(rid, IAM_ROLE)], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        client.get_role.assert_not_called()

    def test_a_missing_credential_answers_undetermined(self) -> None:
        def boom() -> Any:
            raise RuntimeError("no secret mounted")

        candidates = [self._role(f"r{i}", f"arn:aws:iam::{ACCOUNT_ID}:role/r{i}") for i in range(2)]
        verdicts = IamRoleFalsifier(session_factory=boom).batch_falsify(candidates, _context())
        assert [(v.verdict, v.reason) for v in verdicts] == [(UNDETERMINED, "errored")] * 2
        assert all("credential unavailable" in v.note for v in verdicts)


@pytest.mark.django_db
class TestIamUserFalsifier:
    @staticmethod
    def _user(name: str, arn: str, *, account_id: str = ACCOUNT_ID) -> Candidate:
        uid = _dimensioned(IAM_USER, {"name": name, "user_arn": arn}, account_id=account_id)
        return _iam_candidate(uid, IAM_USER)

    def test_present(self) -> None:
        candidate = self._user("present", f"arn:aws:iam::{ACCOUNT_ID}:user/present")
        client = MagicMock()
        client.get_user.return_value = {
            "User": {"Arn": f"arn:aws:iam::{ACCOUNT_ID}:user/present", "UserName": "present"}
        }
        falsifier = IamUserFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == PRESENT_AT_PROBE
        assert unsupported(verdict) is None

    def test_a_path_change_on_the_same_name_is_reidentified(self) -> None:
        candidate = self._user("app-user", f"arn:aws:iam::{ACCOUNT_ID}:user/old-path/app-user")
        client = MagicMock()
        client.get_user.return_value = {
            "User": {"Arn": f"arn:aws:iam::{ACCOUNT_ID}:user/new-path/app-user", "UserName": "app-user"}
        }
        falsifier = IamUserFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == REIDENTIFIED
        assert unsupported(verdict) is None

    def test_dropped(self) -> None:
        candidate = self._user("dropped", f"arn:aws:iam::{ACCOUNT_ID}:user/dropped")
        client = MagicMock()
        client.get_user.side_effect = _client_error("NoSuchEntity", "GetUser")
        falsifier = IamUserFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        assert unsupported(verdict) is None

    def test_wrong_account_refuses_before_any_probe(self) -> None:
        candidate = self._user("dropped", f"arn:aws:iam::{ACCOUNT_ID}:user/dropped")
        client = MagicMock()
        falsifier = IamUserFalsifier(session=_mock_session("iam", client), account_id=OTHER_ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        client.get_user.assert_not_called()

    def test_forbidden(self) -> None:
        candidate = self._user("forbidden", f"arn:aws:iam::{ACCOUNT_ID}:user/forbidden")
        client = MagicMock()
        client.get_user.side_effect = _client_error("AccessDenied", "GetUser")
        falsifier = IamUserFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "forbidden")
        assert unsupported(verdict) is None


@pytest.mark.django_db
class TestIamPolicyFalsifier:
    @staticmethod
    def _policy(name: str, arn: str, *, is_aws_managed: bool = False, account_id: str = ACCOUNT_ID) -> Candidate:
        pid = _dimensioned(
            IAM_POLICY, {"name": name, "policy_arn": arn, "is_aws_managed": is_aws_managed}, account_id=account_id
        )
        return _iam_candidate(pid, IAM_POLICY)

    def test_present(self) -> None:
        candidate = self._policy("app-policy", f"arn:aws:iam::{ACCOUNT_ID}:policy/app-policy")
        client = MagicMock()
        client.get_policy.return_value = {
            "Policy": {"Arn": f"arn:aws:iam::{ACCOUNT_ID}:policy/app-policy", "PolicyName": "app-policy"}
        }
        falsifier = IamPolicyFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == PRESENT_AT_PROBE
        client.get_policy.assert_called_once_with(PolicyArn=f"arn:aws:iam::{ACCOUNT_ID}:policy/app-policy")
        assert unsupported(verdict) is None

    def test_dropped(self) -> None:
        candidate = self._policy("dropped", f"arn:aws:iam::{ACCOUNT_ID}:policy/dropped")
        client = MagicMock()
        client.get_policy.side_effect = _client_error("NoSuchEntity", "GetPolicy")
        falsifier = IamPolicyFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        assert unsupported(verdict) is None

    def test_wrong_account_refuses_before_any_probe(self) -> None:
        candidate = self._policy("dropped", f"arn:aws:iam::{ACCOUNT_ID}:policy/dropped")
        client = MagicMock()
        falsifier = IamPolicyFalsifier(session=_mock_session("iam", client), account_id=OTHER_ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        client.get_policy.assert_not_called()

    def test_forbidden(self) -> None:
        candidate = self._policy("forbidden", f"arn:aws:iam::{ACCOUNT_ID}:policy/forbidden")
        client = MagicMock()
        client.get_policy.side_effect = _client_error("AccessDenied", "GetPolicy")
        falsifier = IamPolicyFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "forbidden")
        assert unsupported(verdict) is None

    def test_an_aws_managed_policy_is_never_probed(self) -> None:
        # Refused before even the scope check: it is pointless work regardless of account.
        candidate = self._policy(
            "AdministratorAccess", "arn:aws:iam::aws:policy/AdministratorAccess", is_aws_managed=True
        )
        client = MagicMock()
        falsifier = IamPolicyFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "AWS-managed" in verdict.note
        client.get_policy.assert_not_called()

    def test_a_customer_managed_policy_is_probed_normally(self) -> None:
        candidate = self._policy("app-policy", f"arn:aws:iam::{ACCOUNT_ID}:policy/app-policy", is_aws_managed=False)
        client = MagicMock()
        client.get_policy.return_value = {
            "Policy": {"Arn": f"arn:aws:iam::{ACCOUNT_ID}:policy/app-policy", "PolicyName": "app-policy"}
        }
        falsifier = IamPolicyFalsifier(session=_mock_session("iam", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == PRESENT_AT_PROBE
        client.get_policy.assert_called_once()


@pytest.mark.django_db
class TestS3BucketFalsifier:
    @staticmethod
    def _bucket(name: str, *, account_id: str = ACCOUNT_ID) -> Candidate:
        bid = _dimensioned(S3_BUCKET, {"name": name, "bucket_arn": f"arn:aws:s3:::{name}"}, account_id=account_id)
        return _iam_candidate(bid, S3_BUCKET)

    def test_present(self) -> None:
        candidate = self._bucket("present")
        client = MagicMock()
        client.head_bucket.return_value = {}
        falsifier = S3BucketFalsifier(session=_mock_session("s3", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == PRESENT_AT_PROBE
        assert unsupported(verdict) is None

    def test_wrong_account_refuses_before_any_probe(self) -> None:
        candidate = self._bucket("gone")
        client = MagicMock()
        falsifier = S3BucketFalsifier(session=_mock_session("s3", client), account_id=OTHER_ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        client.head_bucket.assert_not_called()

    def test_a_name_not_matching_its_own_bucket_arn_refuses_before_any_probe(self) -> None:
        # head_bucket takes Bucket=name, never the ARN: if the grid's two independently-stored
        # fields have drifted apart, probing by `name` would ask about a DIFFERENT bucket than
        # the one this ARN claims to be.
        bid = _dimensioned(S3_BUCKET, {"name": "other", "bucket_arn": "arn:aws:s3:::original"})
        candidate = _iam_candidate(bid, S3_BUCKET)
        client = MagicMock()
        falsifier = S3BucketFalsifier(session=_mock_session("s3", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "does not match its own bucket_arn" in verdict.note
        client.head_bucket.assert_not_called()

    @pytest.mark.parametrize("code", ["404", "403"])
    def test_absent_from_list_buckets_is_dropped(self, code: str) -> None:
        # `_scope_check` already confirmed the account before this ever ran, so the tie-break's
        # own absence conclusion is trustworthy without a further owner re-check.
        candidate = self._bucket("gone")
        client = MagicMock()
        client.head_bucket.side_effect = _client_error(code, "HeadBucket")
        client.list_buckets.return_value = {"Buckets": [{"Name": "present"}, {"Name": "other"}]}
        falsifier = S3BucketFalsifier(session=_mock_session("s3", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        assert "absent from this account's own ListBuckets" in _probe_of(verdict)["detail"]
        assert unsupported(verdict) is None

    @pytest.mark.parametrize("code", ["404", "403"])
    def test_present_in_list_buckets_is_forbidden_not_dropped(self, code: str) -> None:
        candidate = self._bucket("locked")
        client = MagicMock()
        client.head_bucket.side_effect = _client_error(code, "HeadBucket")
        client.list_buckets.return_value = {"Buckets": [{"Name": "locked"}]}
        falsifier = S3BucketFalsifier(session=_mock_session("s3", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "forbidden")
        assert "present in this account's own ListBuckets" in verdict.note

    @pytest.mark.parametrize("code", ["404", "403"])
    def test_when_list_buckets_itself_fails_is_undetermined_not_dropped(self, code: str) -> None:
        candidate = self._bucket("mystery")
        client = MagicMock()
        client.head_bucket.side_effect = _client_error(code, "HeadBucket")
        client.list_buckets.side_effect = _client_error("AccessDenied", "ListBuckets")
        falsifier = S3BucketFalsifier(session=_mock_session("s3", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "could not be read either" in verdict.note

    def test_a_400_is_not_routed_through_the_tie_break(self) -> None:
        candidate = self._bucket("weird")
        client = MagicMock()
        client.head_bucket.side_effect = _client_error("400", "HeadBucket")
        falsifier = S3BucketFalsifier(session=_mock_session("s3", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "errored")
        client.list_buckets.assert_not_called()

    def test_a_continuation_token_is_never_treated_as_a_complete_inventory(self) -> None:
        candidate = self._bucket("gone")
        client = MagicMock()
        client.head_bucket.side_effect = _client_error("403", "HeadBucket")
        client.list_buckets.return_value = {"Buckets": [{"Name": "other"}], "ContinuationToken": "eyJ..."}
        falsifier = S3BucketFalsifier(session=_mock_session("s3", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "could not be read either" in verdict.note

    def test_a_missing_buckets_key_is_never_treated_as_an_empty_inventory(self) -> None:
        candidate = self._bucket("gone")
        client = MagicMock()
        client.head_bucket.side_effect = _client_error("403", "HeadBucket")
        client.list_buckets.return_value = {}
        falsifier = S3BucketFalsifier(session=_mock_session("s3", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "could not be read either" in verdict.note

    def test_a_present_but_empty_buckets_list_is_a_trusted_observation(self) -> None:
        candidate = self._bucket("gone")
        client = MagicMock()
        client.head_bucket.side_effect = _client_error("403", "HeadBucket")
        client.list_buckets.return_value = {"Buckets": []}
        falsifier = S3BucketFalsifier(session=_mock_session("s3", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == DROPPED_FROM_OBSERVATION

    def test_list_buckets_is_called_once_per_batch_for_several_ambiguous_statuses(self) -> None:
        candidates = [self._bucket(f"b{i}") for i in range(3)]
        client = MagicMock()
        client.head_bucket.side_effect = _client_error("403", "HeadBucket")
        client.list_buckets.return_value = {"Buckets": []}
        falsifier = S3BucketFalsifier(session=_mock_session("s3", client), account_id=ACCOUNT_ID)
        falsifier.batch_falsify(candidates, _context())
        assert client.list_buckets.call_count == 1

    def test_a_list_buckets_failure_is_cached_for_the_whole_batch(self) -> None:
        candidates = [self._bucket(f"b{i}") for i in range(3)]
        client = MagicMock()
        client.head_bucket.side_effect = _client_error("403", "HeadBucket")
        client.list_buckets.side_effect = _client_error("AccessDenied", "ListBuckets")
        falsifier = S3BucketFalsifier(session=_mock_session("s3", client), account_id=ACCOUNT_ID)
        verdicts = falsifier.batch_falsify(candidates, _context())
        assert [(v.verdict, v.reason) for v in verdicts] == [(UNDETERMINED, "scope_unknown")] * 3
        assert client.list_buckets.call_count == 1

    def test_a_new_run_re_reads_list_buckets(self) -> None:
        candidate = self._bucket("flaky")
        client = MagicMock()
        client.head_bucket.side_effect = _client_error("403", "HeadBucket")
        client.list_buckets.return_value = {"Buckets": []}
        falsifier = S3BucketFalsifier(session=_mock_session("s3", client), account_id=ACCOUNT_ID)
        falsifier.batch_falsify([candidate], FalsifyContext(batch_id="run-1", statement=None))
        falsifier.batch_falsify([candidate], FalsifyContext(batch_id="run-2", statement=None))
        assert client.list_buckets.call_count == 2

    def test_a_row_without_an_arn_is_not_answered(self) -> None:
        bid = _dimensioned(S3_BUCKET, {"name": "legacy"})
        client = MagicMock()
        falsifier = S3BucketFalsifier(session=_mock_session("s3", client), account_id=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([_iam_candidate(bid, S3_BUCKET)], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        client.head_bucket.assert_not_called()

    def test_a_missing_credential_answers_undetermined(self) -> None:
        def boom() -> Any:
            raise RuntimeError("no secret mounted")

        candidates = [self._bucket(f"b{i}") for i in range(2)]
        verdicts = S3BucketFalsifier(session_factory=boom).batch_falsify(candidates, _context())
        assert [(v.verdict, v.reason) for v in verdicts] == [(UNDETERMINED, "errored")] * 2


class TestIamAndS3ProbeStatusOf:
    """The two local extensions to the shared `probe_status_of`, additive over it (module
    docstring): IAM's bare `NoSuch*` convention and S3 HeadBucket's bare numeric codes."""

    @pytest.mark.parametrize(
        ("code", "op", "want"),
        [
            ("NoSuchEntity", "GetRole", "not_found"),
            ("AccessDenied", "GetRole", "forbidden"),
            ("Throttling", "GetRole", "rate_limited"),
            ("InternalError", "GetRole", "errored"),
        ],
    )
    def test_iam_mapping(self, code: str, op: str, want: str) -> None:
        assert _iam_probe_status_of(_client_error(code, op)) == want

    @pytest.mark.parametrize(
        ("code", "op", "want"),
        [
            ("404", "HeadBucket", "not_found"),
            ("403", "HeadBucket", "forbidden"),
            ("400", "HeadBucket", "errored"),
            ("SlowDown", "HeadBucket", "rate_limited"),
        ],
    )
    def test_s3_mapping(self, code: str, op: str, want: str) -> None:
        assert _s3_probe_status_of(_client_error(code, op)) == want


def _probe_of(verdict: Verdict) -> dict[str, Any]:
    assert verdict.probe is not None, "a judged verdict records its probe"
    return verdict.probe
