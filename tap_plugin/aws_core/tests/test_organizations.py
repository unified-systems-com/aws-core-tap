"""The AWS Organizations tree collector and its two falsifiers (tap-plugin-aws-core#50).

Two layers, tested separately: :mod:`tap_plugin.aws_core.collectors.boto3_collector.organizations`
(a fake ``organizations`` client -> nodes/edges/completeness listings, no grid), and
``OrganizationalUnitFalsifier`` / ``AccountFalsifier`` (real grid rows through the service layer, a
fake client, the same four-case contract every falsifier in this plugin ships —
``req-grid-reconcile-falsifier-6``).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector.organizations import (
    ACCOUNT,
    ATTACHED_TO_TARGET,
    ENROLLS_ACCOUNT,
    NESTED_UNDER_PARENT,
    ORGANIZATION,
    ORGANIZATIONAL_UNIT,
    PARTITIONED_INTO_OU,
    SERVICE_CONTROL_POLICY,
    account_state,
    collect_organization,
    organization_id_of_account_arn,
    partition_of_arn,
)
from tap_plugin.aws_core.falsifiers import AccountFalsifier, OrganizationalUnitFalsifier

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
    FalsifyContext,
    Verdict,
    unsupported,
)
from tap_grid.services import create_edge, create_node, get_node

ORG_ID = "o-abc1234567"
ROOT_ID = "r-ab12"
MGMT_ACCOUNT = "111111111111"
DIMENSIONS = {"cloud": "aws", "aws_account": MGMT_ACCOUNT, "aws_region": "global"}
#: Injected explicitly into every falsifier below (the module docstring's own contract: "region
#: is injected by tests"). Without it, `_region()` falls back to `resolve_aws_secret()` — a real
#: credential read that happens to succeed in a dev stack carrying a secret and fails in CI's
#: credential-free `ci` boot record, masking every assertion behind
#: `UNDETERMINED(organizations client unavailable)` (caught on aws-core-tap#55's own CI run).
REGION = "us-east-1"


# ---------------------------------------------------------------------------
# collect_organization — a fake ``organizations`` client, no grid
# ---------------------------------------------------------------------------


class FakeOrganizations:
    """A fake ``organizations`` client: canned, paginated responses per operation, keyed by the
    single positional-ish kwarg each call is distinguished by (``ParentId`` / ``PolicyId``), and
    unconditional responses for the parameter-free calls."""

    def __init__(self) -> None:
        self.describe_organization_response: dict[str, Any] | Exception = {"Organization": {}}
        self.roots: list[dict[str, Any]] | Exception = []
        self.ous_of: dict[str, list[dict[str, Any]] | Exception] = {}
        self.accounts: list[dict[str, Any]] | Exception = []
        self.accounts_of: dict[str, list[dict[str, Any]]] = {}
        self.policies: list[dict[str, Any]] = []
        self.targets_of: dict[str, list[dict[str, Any]]] = {}
        self.tags_of: dict[str, list[dict[str, Any]]] = {}
        self.tag_errors: dict[str, Exception] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def describe_organization(self) -> dict[str, Any]:
        self.calls.append(("describe_organization", {}))
        if isinstance(self.describe_organization_response, Exception):
            raise self.describe_organization_response
        return self.describe_organization_response

    def list_roots(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_roots", kwargs))
        if isinstance(self.roots, Exception):
            raise self.roots
        return {"Roots": self.roots}

    def list_organizational_units_for_parent(self, ParentId: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_organizational_units_for_parent", {"ParentId": ParentId, **kwargs}))
        configured = self.ous_of.get(ParentId, [])
        if isinstance(configured, Exception):
            error = configured
            raise error
        return {"OrganizationalUnits": configured}

    def list_accounts(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_accounts", kwargs))
        configured = self.accounts
        if isinstance(configured, Exception):
            error = configured
            raise error
        return {"Accounts": configured}

    def list_accounts_for_parent(self, ParentId: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_accounts_for_parent", {"ParentId": ParentId, **kwargs}))
        return {"Accounts": self.accounts_of.get(ParentId, [])}

    def list_policies(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_policies", kwargs))
        return {"Policies": self.policies}

    def list_targets_for_policy(self, PolicyId: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_targets_for_policy", {"PolicyId": PolicyId, **kwargs}))
        return {"Targets": self.targets_of.get(PolicyId, [])}

    def list_tags_for_resource(self, ResourceId: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_tags_for_resource", {"ResourceId": ResourceId, **kwargs}))
        if ResourceId in self.tag_errors:
            raise self.tag_errors[ResourceId]
        return {"Tags": self.tags_of.get(ResourceId, [])}


def _basic_org(client: FakeOrganizations, *, partition_arn: str = "arn:aws:organizations::111111111111:organization/o-abc1234567") -> None:
    client.describe_organization_response = {
        "Organization": {
            "Id": ORG_ID,
            "Arn": partition_arn,
            "MasterAccountId": MGMT_ACCOUNT,
            "FeatureSet": "ALL",
        }
    }
    client.roots = [{"Id": ROOT_ID, "Name": "Root"}]


def _node(tree: Any, entity_type: str, natural_key_field: str, value: str) -> dict[str, Any]:
    matches = [
        n for n in tree.nodes if n["entity"]["entity_type"] == entity_type and n["node"].get(natural_key_field) == value
    ]
    assert len(matches) == 1, f"expected exactly one {entity_type} with {natural_key_field}={value!r}: {matches}"
    return matches[0]


def _edges(tree: Any, edge_type: str) -> list[dict[str, Any]]:
    return [e for e in tree.edges if e["edge"]["edge_type"] == edge_type]


class TestCollectOrganizationTree:
    def test_full_tree_nodes_edges_and_surfaces(self) -> None:
        """org -> root(top OU) -> nested OU, two accounts (one at root, one in the nested OU), one
        SCP attached at the root. Every parent's child listing yields a completeness surface."""
        client = FakeOrganizations()
        _basic_org(client)
        client.ous_of[ROOT_ID] = [{"Id": "ou-ab12-top00001", "Name": "Top"}]
        client.ous_of["ou-ab12-top00001"] = [{"Id": "ou-ab12-nest0001", "Name": "Nested"}]
        client.ous_of["ou-ab12-nest0001"] = []
        client.accounts = [
            {"Id": "222222222222", "Name": "root-account", "Email": "a@x.com", "Status": "ACTIVE"},
            {"Id": "333333333333", "Name": "nested-account", "Email": "b@x.com", "Status": "ACTIVE"},
        ]
        client.accounts_of[ROOT_ID] = [{"Id": "222222222222"}]
        client.accounts_of["ou-ab12-top00001"] = []
        client.accounts_of["ou-ab12-nest0001"] = [{"Id": "333333333333"}]
        client.policies = [
            {"Id": "p-examplepolicy1", "Arn": "arn:aws:organizations::111111111111:policy/o-abc1234567/service_control_policy/p-examplepolicy1", "Name": "Deny", "AwsManaged": False}
        ]
        client.targets_of["p-examplepolicy1"] = [{"TargetId": ROOT_ID, "Type": "ROOT"}]

        tree = collect_organization(client, DIMENSIONS)

        assert tree.state == "collected"
        org_node = _node(tree, ORGANIZATION, "organization_id", ORG_ID)
        assert org_node["node"]["root_id"] == ROOT_ID
        assert org_node["node"]["partition"] == "aws"
        assert org_node["node"]["management_account_id"] == MGMT_ACCOUNT

        _node(tree, ORGANIZATIONAL_UNIT, "ou_id", "ou-ab12-top00001")
        _node(tree, ORGANIZATIONAL_UNIT, "ou_id", "ou-ab12-nest0001")
        root_account = _node(tree, ACCOUNT, "account_id", "222222222222")
        nested_account = _node(tree, ACCOUNT, "account_id", "333333333333")
        assert root_account["node"]["configuration"]["ParentId"] == ROOT_ID
        assert nested_account["node"]["configuration"]["ParentId"] == "ou-ab12-nest0001"
        policy_node = _node(tree, SERVICE_CONTROL_POLICY, "policy_id", "p-examplepolicy1")
        assert policy_node["node"]["aws_managed"] is False

        # Containment: org -> top OU, top OU -> nested OU, org -> both accounts.
        partition_edges = {(e["edge"]["from_entity_id"], e["edge"]["to_entity_id"]) for e in _edges(tree, PARTITIONED_INTO_OU)}
        assert (org_node["entity"]["entity_id"], _node(tree, ORGANIZATIONAL_UNIT, "ou_id", "ou-ab12-top00001")["entity"]["entity_id"]) in partition_edges
        enrolls = {e["edge"]["to_entity_id"] for e in _edges(tree, ENROLLS_ACCOUNT)}
        assert {root_account["entity"]["entity_id"], nested_account["entity"]["entity_id"]} == enrolls
        assert len(_edges(tree, ATTACHED_TO_TARGET)) == 1
        # NESTED_UNDER_PARENT is still emitted (the reference), for both OUs and both accounts.
        assert len(_edges(tree, NESTED_UNDER_PARENT)) == 4

        # Completeness: one surface per parent's OU listing (org, top OU, nested OU) plus one for
        # organization-wide account membership. Placement (ListAccountsForParent) and policy calls
        # are NOT containment surfaces and record none.
        by_relation = {(s.relation, s.subject): s for s in tree.listings}
        assert len(tree.listings) == 4
        org_ou_surface = by_relation[("organization.organizational_units", org_node["entity"]["entity_id"])]
        assert org_ou_surface.complete is True
        assert org_ou_surface.count == 1
        assert org_ou_surface.edge_type == PARTITIONED_INTO_OU
        membership_surface = by_relation[("organization.accounts", org_node["entity"]["entity_id"])]
        assert membership_surface.count == 2
        assert membership_surface.edge_type == ENROLLS_ACCOUNT

    def test_govcloud_partition_read_from_arn(self) -> None:
        client = FakeOrganizations()
        _basic_org(
            client,
            partition_arn="arn:aws-us-gov:organizations::111111111111:organization/o-abc1234567",
        )
        client.ous_of[ROOT_ID] = []
        tree = collect_organization(client, DIMENSIONS)
        org_node = _node(tree, ORGANIZATION, "organization_id", ORG_ID)
        assert org_node["node"]["partition"] == "aws-us-gov"

    def test_not_in_organization_yields_no_nodes_and_an_info_notice(self) -> None:
        client = FakeOrganizations()
        client.describe_organization_response = ClientError(
            {"Error": {"Code": "AWSOrganizationsNotInUseException", "Message": "x"}}, "DescribeOrganization"
        )
        tree = collect_organization(client, DIMENSIONS)
        assert tree.state == "not_in_organization"
        assert tree.nodes == []
        assert tree.listings == []
        assert any(n.code == "ORG_NOT_IN_USE" and n.level == "info" for n in tree.notices)

    def test_describe_organization_denied_is_not_authorized(self) -> None:
        client = FakeOrganizations()
        client.describe_organization_response = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "DescribeOrganization"
        )
        tree = collect_organization(client, DIMENSIONS)
        assert tree.state == "not_authorized"
        assert tree.nodes == []
        assert any(n.code == "ORG_NOT_AUTHORIZED" for n in tree.notices)

    def test_list_roots_denied_refuses_both_child_surfaces_but_keeps_the_org_node(self) -> None:
        """A delegated administrator (or a scoped-down management credential) that can
        DescribeOrganization but not ListRoots: the org node is still written (it IS observed),
        and both surfaces it would have read say why they could not be."""
        client = FakeOrganizations()
        _basic_org(client)
        client.roots = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "ListRoots")
        tree = collect_organization(client, DIMENSIONS)
        assert tree.state == "collected"
        org_node = _node(tree, ORGANIZATION, "organization_id", ORG_ID)
        assert org_node["node"]["root_id"] == ""
        assert len(tree.listings) == 2
        for listing in tree.listings:
            assert listing.complete is False
            assert listing.authorized is False
            assert listing.admitted is False
        assert {s.relation for s in tree.listings} == {"organization.organizational_units", "organization.accounts"}

    def test_ou_listing_failure_is_incomplete_not_empty(self) -> None:
        """A failed child listing must never read as 'this parent has no children' — the
        surface's enumeration_complete is False and cites why, with no fabricated node."""
        client = FakeOrganizations()
        _basic_org(client)
        client.ous_of[ROOT_ID] = ClientError({"Error": {"Code": "TooManyRequestsException", "Message": "x"}}, "ListOUs")
        client.accounts = []
        tree = collect_organization(client, DIMENSIONS)
        assert [n for n in tree.nodes if n["entity"]["entity_type"] == ORGANIZATIONAL_UNIT] == []
        [ou_surface] = [s for s in tree.listings if s.relation == "organization.organizational_units"]
        assert ou_surface.complete is False
        assert ou_surface.authorized is None  # a rate limit says nothing about permission
        assert "enumeration_complete" in ou_surface.reasons

    def test_closed_account_is_reported_present_not_dropped(self) -> None:
        """A closed/suspended account is still named by ListAccounts — present, with its status."""
        client = FakeOrganizations()
        _basic_org(client)
        client.ous_of[ROOT_ID] = []
        client.accounts = [{"Id": "444444444444", "Name": "closed-one", "State": "SUSPENDED"}]
        client.accounts_of[ROOT_ID] = [{"Id": "444444444444"}]
        tree = collect_organization(client, DIMENSIONS)
        node = _node(tree, ACCOUNT, "account_id", "444444444444")
        assert node["node"]["status"] == "SUSPENDED"

    def test_account_moved_mid_walk_still_placed_and_enrolled(self) -> None:
        """An account ListAccounts names but no parent listing places is still enrolled — its
        NESTED_UNDER_PARENT edge is simply not refreshed this run, never dropped as a node."""
        client = FakeOrganizations()
        _basic_org(client)
        client.ous_of[ROOT_ID] = []
        client.accounts = [{"Id": "555555555555", "Name": "unplaced"}]
        client.accounts_of[ROOT_ID] = []
        tree = collect_organization(client, DIMENSIONS)
        node = _node(tree, ACCOUNT, "account_id", "555555555555")
        assert node is not None
        assert {e["edge"]["to_entity_id"] for e in _edges(tree, ENROLLS_ACCOUNT)} == {node["entity"]["entity_id"]}
        assert _edges(tree, NESTED_UNDER_PARENT) == []
        assert any(n.code == "ORG_ACCOUNTS_UNPLACED" for n in tree.notices)

    def test_denied_tags_skip_the_node_rather_than_overwrite_it_with_an_empty_map(self) -> None:
        """GRIFT upsert applies every node through replace_node, whose _apply_replace resets an
        OPTIONAL field the envelope omits to the model default (tap_grid/services/_impl.py) - the
        same {} an unset tags JSONField defaults to. So an unreadable tag read must never be sent
        as tags: {} (that reads back as "no tags", silently erasing real ones a previous run
        observed) and must never be simply omitted either (replace_node resets it exactly the
        same way): the only honest response is to not write the node at all this run."""
        client = FakeOrganizations()
        _basic_org(client)
        client.ous_of[ROOT_ID] = [{"Id": "ou-ab12-tagdenied1", "Name": "Denied"}]
        client.ous_of["ou-ab12-tagdenied1"] = []
        client.tag_errors["ou-ab12-tagdenied1"] = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "ListTagsForResource"
        )
        tree = collect_organization(client, DIMENSIONS)

        assert [n for n in tree.nodes if n["entity"]["entity_type"] == ORGANIZATIONAL_UNIT] == []
        assert any(n.code == "ORG_NODE_SKIPPED" for n in tree.notices)
        assert any(n.code == "ORG_TAGS_DENIED" for n in tree.notices)
        [root_surface] = [s for s in tree.listings if s.relation == "organization.organizational_units"]
        assert root_surface.admitted is False, "a listing that skipped a child it saw did not land whole"

    def test_aws_managed_policy_tags_are_not_read_and_not_a_failure(self) -> None:
        """An AWS-managed policy truly cannot be tagged - {} here is an observed fact, not a
        stand-in for an unreadable read, so it is never asked for and never skips the node."""
        client = FakeOrganizations()
        _basic_org(client)
        client.ous_of[ROOT_ID] = []
        client.policies = [
            {
                "Id": "p-fullawsaccess1",
                "Arn": "arn:aws:organizations::aws:policy/service_control_policy/p-FullAWSAccess",
                "Name": "FullAWSAccess",
                "AwsManaged": True,
            }
        ]
        tree = collect_organization(client, DIMENSIONS)
        node = _node(tree, SERVICE_CONTROL_POLICY, "policy_id", "p-fullawsaccess1")
        assert node["node"]["tags"] == {}
        assert ("list_tags_for_resource", {"ResourceId": "p-fullawsaccess1"}) not in client.calls


class TestOrganizationHelpers:
    def test_partition_of_arn(self) -> None:
        assert partition_of_arn("arn:aws-us-gov:organizations::1:organization/o-x") == "aws-us-gov"
        assert partition_of_arn("not-an-arn") == ""
        assert partition_of_arn("") == ""

    def test_organization_id_of_account_arn(self) -> None:
        assert (
            organization_id_of_account_arn("arn:aws:organizations::111111111111:account/o-abc1234567/222222222222")
            == "o-abc1234567"
        )
        assert organization_id_of_account_arn("arn:aws:iam::123:role/x") == ""
        assert organization_id_of_account_arn("") == ""

    def test_account_state_falls_back_to_status(self) -> None:
        assert account_state({"State": "ACTIVE", "Status": "ACTIVE"}) == "ACTIVE"
        assert account_state({"Status": "ACTIVE"}) == "ACTIVE"
        assert account_state({}) == ""


# ---------------------------------------------------------------------------
# OrganizationalUnitFalsifier / AccountFalsifier — real grid rows, fake client
# ---------------------------------------------------------------------------


class FakeOrgClient:
    """A fake ``organizations`` client for the falsifier side: reach (``describe_organization`` +
    ``list_roots``) plus per-candidate ``describe_organizational_unit`` / ``describe_account`` /
    ``list_parents``, arranged per test."""

    def __init__(self, *, organization_id: str = ORG_ID, root_ids: list[str] | None = None) -> None:
        self.organization_id = organization_id
        self.root_ids = root_ids if root_ids is not None else [ROOT_ID]
        self.reach_error: Exception | None = None
        self._ou_responses: dict[str, dict[str, Any] | Exception] = {}
        self._parents: dict[str, list[dict[str, Any]]] = {}
        self._account_responses: dict[str, dict[str, Any] | Exception] = {}
        self.calls: list[str] = []

    def describe_organization(self) -> dict[str, Any]:
        self.calls.append("describe_organization")
        if self.reach_error is not None:
            raise self.reach_error
        return {"Organization": {"Id": self.organization_id}}

    def list_roots(self) -> dict[str, Any]:
        self.calls.append("list_roots")
        if self.reach_error is not None:
            raise self.reach_error
        return {"Roots": [{"Id": rid} for rid in self.root_ids]}

    def answer_ou(self, ou_id: str, unit: dict[str, Any], *, parents: list[dict[str, Any]] | None = None) -> None:
        self._ou_responses[ou_id] = {"OrganizationalUnit": unit}
        self._parents[ou_id] = parents if parents is not None else []

    def refuse_ou(self, ou_id: str, code: str) -> None:
        self._ou_responses[ou_id] = ClientError({"Error": {"Code": code, "Message": "x"}}, "DescribeOU")

    def describe_organizational_unit(self, OrganizationalUnitId: str) -> dict[str, Any]:
        self.calls.append(f"describe_organizational_unit:{OrganizationalUnitId}")
        response = self._ou_responses[OrganizationalUnitId]
        if isinstance(response, Exception):
            raise response
        return response

    def list_parents(self, ChildId: str) -> dict[str, Any]:
        self.calls.append(f"list_parents:{ChildId}")
        return {"Parents": self._parents.get(ChildId, [])}

    def answer_account(self, account_id: str, account: dict[str, Any]) -> None:
        self._account_responses[account_id] = {"Account": account}

    def refuse_account(self, account_id: str, code: str) -> None:
        self._account_responses[account_id] = ClientError({"Error": {"Code": code, "Message": "x"}}, "DescribeAccount")

    def describe_account(self, AccountId: str) -> dict[str, Any]:
        self.calls.append(f"describe_account:{AccountId}")
        response = self._account_responses[AccountId]
        if isinstance(response, Exception):
            raise response
        return response


class FakeOrgSession:
    def __init__(self, client: FakeOrgClient) -> None:
        self._client = client

    def client(self, service: str, region_name: str | None = None) -> Any:
        assert service == "organizations", f"must ask for organizations, asked for {service!r}"
        return self._client


def _context() -> FalsifyContext:
    return FalsifyContext(batch_id=str(uuid.uuid4()), statement=None)


def _org_row(*, organization_id: str = ORG_ID, root_id: str = ROOT_ID) -> uuid.UUID:
    result = create_node(ORGANIZATION, {"name": "org", "organization_id": organization_id, "root_id": root_id})
    assert result.success, result.errors
    return uuid.UUID(str(result.entity_id))


def _ou_row(
    ou_id: str, *, name: str = "", account_id: str = MGMT_ACCOUNT, org_id: uuid.UUID | None = None
) -> uuid.UUID:
    """A live ``AwsOrganizationalUnit`` row. ``org_id`` also records the ``NESTED_UNDER_PARENT``
    edge to it — the chain ``_organization_id_of`` walks — omitted only by the tests that mean to
    exercise no-organization-on-record or a different one."""
    result = create_node(ORGANIZATIONAL_UNIT, {"name": name or ou_id, "ou_id": ou_id})
    assert result.success, result.errors
    entity_id = uuid.UUID(str(result.entity_id))
    row = get_node(entity_id)
    row.entity.dimensions = {"cloud": "aws", "aws_account": account_id, "aws_region": "global"}
    row.entity.save(update_fields=["dimensions"])
    if org_id is not None:
        create_edge(row.entity, get_node(org_id).entity, "NESTED_UNDER_PARENT__aws_core")
    return entity_id


def _account_row(account_id_val: str, *, name: str = "", credential_account: str = MGMT_ACCOUNT) -> uuid.UUID:
    result = create_node(ACCOUNT, {"name": name or account_id_val, "account_id": account_id_val})
    assert result.success, result.errors
    entity_id = uuid.UUID(str(result.entity_id))
    row = get_node(entity_id)
    row.entity.dimensions = {"cloud": "aws", "aws_account": credential_account, "aws_region": "global"}
    row.entity.save(update_fields=["dimensions"])
    return entity_id


def _candidate(entity_id: uuid.UUID, entity_type: str, *, parent: uuid.UUID | None) -> Candidate:
    return Candidate(
        entity_id=entity_id,
        entity_type=entity_type,
        reason="dropped_from_observation",
        surface=0,
        relation="fixture",
        subject=None,
        edge_type=None,
        parent=parent,
        interval_first=None,
    )


def _assert_evidence_supports(verdicts: dict[str, Verdict]) -> None:
    for case, verdict in verdicts.items():
        assert unsupported(verdict) is None, f"{case}: {unsupported(verdict)}"


@pytest.mark.django_db
class TestOrganizationalUnitFalsifierFourCases:
    @pytest.mark.spec("req-grid-reconcile-falsifier-6")
    def test_four_cases(self) -> None:
        org_id = _org_row()
        client = FakeOrgClient()
        cases: dict[str, Candidate] = {}

        present_id = _ou_row("ou-ab12-present01", name="present-ou", org_id=org_id)
        cases[CASE_PRESENT] = _candidate(present_id, ORGANIZATIONAL_UNIT, parent=org_id)
        client.answer_ou("ou-ab12-present01", {"Id": "ou-ab12-present01", "Name": "present-ou"}, parents=[{"Id": ROOT_ID}])

        dropped_id = _ou_row("ou-ab12-dropped01", org_id=org_id)
        cases[CASE_DROPPED] = _candidate(dropped_id, ORGANIZATIONAL_UNIT, parent=org_id)
        client.refuse_ou("ou-ab12-dropped01", "OrganizationalUnitNotFoundException")

        forbidden_id = _ou_row("ou-ab12-forbid001", org_id=org_id)
        cases[CASE_FORBIDDEN] = _candidate(forbidden_id, ORGANIZATIONAL_UNIT, parent=org_id)
        client.refuse_ou("ou-ab12-forbid001", "AccessDeniedException")

        reborn_id = _ou_row("ou-ab12-reborn001", org_id=org_id)
        cases[CASE_REIDENTIFIED] = _candidate(reborn_id, ORGANIZATIONAL_UNIT, parent=org_id)
        client.answer_ou("ou-ab12-reborn001", {"Id": "ou-ab12-newid001", "Name": "x"}, parents=[{"Id": ROOT_ID}])

        falsifier = OrganizationalUnitFalsifier(session=FakeOrgSession(client), account_id=MGMT_ACCOUNT, region=REGION)
        verdicts = run_four_cases(falsifier, cases, _context())
        _assert_evidence_supports(verdicts)
        assert verdicts[CASE_PRESENT].expected["owner"] == ROOT_ID
        assert unsupported(verdicts[CASE_PRESENT]) is None

    def test_renamed_ou_is_relocated_renamed(self) -> None:
        org_id = _org_row()
        client = FakeOrgClient()
        ou_id = _ou_row("ou-ab12-renamed01", name="old-name", org_id=org_id)
        client.answer_ou("ou-ab12-renamed01", {"Id": "ou-ab12-renamed01", "Name": "new-name"}, parents=[{"Id": ROOT_ID}])
        falsifier = OrganizationalUnitFalsifier(session=FakeOrgSession(client), account_id=MGMT_ACCOUNT, region=REGION)
        [verdict] = falsifier.batch_falsify([_candidate(ou_id, ORGANIZATIONAL_UNIT, parent=org_id)], _context())
        assert verdict.verdict == "RELOCATED"
        assert verdict.kind == "renamed"

    def test_ou_recorded_under_a_different_organization_is_scope_unknown(self) -> None:
        """The OU's own NESTED_UNDER_PARENT chain reaches a DIFFERENT organization than the
        credential's reach: an absence here says nothing about that other organization's OU.
        This is the organization-id comparison, not a root-id-suffix heuristic — AWS documents no
        global uniqueness for that short alphanumeric string (unified-ai-review#55)."""
        home_org_id = _org_row(organization_id=ORG_ID)
        foreign_org_id = _org_row(organization_id="o-foreignorg1")
        client = FakeOrgClient(organization_id=ORG_ID)
        ou_id = _ou_row("ou-ab12-foreign01", org_id=foreign_org_id)
        falsifier = OrganizationalUnitFalsifier(session=FakeOrgSession(client), account_id=MGMT_ACCOUNT, region=REGION)
        [verdict] = falsifier.batch_falsify([_candidate(ou_id, ORGANIZATIONAL_UNIT, parent=home_org_id)], _context())
        assert verdict.verdict == UNDETERMINED
        assert verdict.reason == "scope_unknown"
        assert "describe_organizational_unit:ou-ab12-foreign01" not in client.calls

    def test_ou_with_no_recorded_organization_is_scope_unknown(self) -> None:
        """A NESTED_UNDER_PARENT chain that reaches no AwsOrganization at all (a malformed or
        design-only row) cannot be compared against — refused before any probe."""
        org_id = _org_row()
        client = FakeOrgClient()
        ou_id = _ou_row("ou-ab12-noorg0001")  # no org_id: no NESTED_UNDER_PARENT edge recorded
        falsifier = OrganizationalUnitFalsifier(session=FakeOrgSession(client), account_id=MGMT_ACCOUNT, region=REGION)
        [verdict] = falsifier.batch_falsify([_candidate(ou_id, ORGANIZATIONAL_UNIT, parent=org_id)], _context())
        assert verdict.verdict == UNDETERMINED
        assert verdict.reason == "scope_unknown"
        assert "describe_organizational_unit:ou-ab12-noorg0001" not in client.calls

    def test_reach_failure_is_undetermined_for_every_candidate(self) -> None:
        org_id = _org_row()
        client = FakeOrgClient()
        client.reach_error = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "DescribeOrganization")
        ou_id = _ou_row("ou-ab12-anycase01")
        falsifier = OrganizationalUnitFalsifier(session=FakeOrgSession(client), account_id=MGMT_ACCOUNT, region=REGION)
        [verdict] = falsifier.batch_falsify([_candidate(ou_id, ORGANIZATIONAL_UNIT, parent=org_id)], _context())
        assert verdict.verdict == UNDETERMINED
        assert verdict.reason == "forbidden"

    def test_not_in_organization_reach_is_scope_unknown(self) -> None:
        org_id = _org_row()
        client = FakeOrgClient()
        client.reach_error = ClientError({"Error": {"Code": "AWSOrganizationsNotInUseException", "Message": "x"}}, "DescribeOrganization")
        ou_id = _ou_row("ou-ab12-anycase02")
        falsifier = OrganizationalUnitFalsifier(session=FakeOrgSession(client), account_id=MGMT_ACCOUNT, region=REGION)
        [verdict] = falsifier.batch_falsify([_candidate(ou_id, ORGANIZATIONAL_UNIT, parent=org_id)], _context())
        assert verdict.verdict == UNDETERMINED
        assert verdict.reason == "scope_unknown"

    def test_account_mismatch_is_scope_unknown_before_any_reach_call(self) -> None:
        org_id = _org_row()
        client = FakeOrgClient()
        ou_id = _ou_row("ou-ab12-elsewhere1", account_id="999988887777")
        falsifier = OrganizationalUnitFalsifier(session=FakeOrgSession(client), account_id=MGMT_ACCOUNT, region=REGION)
        [verdict] = falsifier.batch_falsify([_candidate(ou_id, ORGANIZATIONAL_UNIT, parent=org_id)], _context())
        assert verdict.verdict == UNDETERMINED
        assert verdict.reason == "scope_unknown"
        assert client.calls == []


@pytest.mark.django_db
class TestAccountFalsifierFourCases:
    @pytest.mark.spec("req-grid-reconcile-falsifier-6")
    def test_four_cases(self) -> None:
        org_id = _org_row()
        client = FakeOrgClient()
        cases: dict[str, Candidate] = {}
        def account_arn(acct: str) -> str:
            return f"arn:aws:organizations::{MGMT_ACCOUNT}:account/{ORG_ID}/{acct}"

        present_id = _account_row("222222222222", name="present")
        cases[CASE_PRESENT] = _candidate(present_id, ACCOUNT, parent=org_id)
        client.answer_account(
            "222222222222", {"Id": "222222222222", "Arn": account_arn("222222222222"), "Name": "present", "State": "ACTIVE"}
        )

        dropped_id = _account_row("333333333333")
        cases[CASE_DROPPED] = _candidate(dropped_id, ACCOUNT, parent=org_id)
        client.refuse_account("333333333333", "AccountNotFoundException")

        forbidden_id = _account_row("444444444444")
        cases[CASE_FORBIDDEN] = _candidate(forbidden_id, ACCOUNT, parent=org_id)
        client.refuse_account("444444444444", "AccessDeniedException")

        reborn_id = _account_row("555555555555")
        cases[CASE_REIDENTIFIED] = _candidate(reborn_id, ACCOUNT, parent=org_id)
        client.answer_account("555555555555", {"Id": "666666666666", "Arn": account_arn("666666666666"), "Name": "x"})

        falsifier = AccountFalsifier(session=FakeOrgSession(client), account_id=MGMT_ACCOUNT, region=REGION)
        verdicts = run_four_cases(falsifier, cases, _context())
        _assert_evidence_supports(verdicts)
        assert verdicts[CASE_PRESENT].expected["owner"] == ORG_ID

    def test_suspended_account_is_present_at_probe_with_a_note(self) -> None:
        """A closed/suspended account is still describable — present, never retired here."""
        org_id = _org_row()
        client = FakeOrgClient()
        account_id = _account_row("777777777777")
        client.answer_account(
            "777777777777",
            {
                "Id": "777777777777",
                "Arn": f"arn:aws:organizations::{MGMT_ACCOUNT}:account/{ORG_ID}/777777777777",
                "Name": "777777777777",
                "State": "SUSPENDED",
            },
        )
        falsifier = AccountFalsifier(session=FakeOrgSession(client), account_id=MGMT_ACCOUNT, region=REGION)
        [verdict] = falsifier.batch_falsify([_candidate(account_id, ACCOUNT, parent=org_id)], _context())
        assert verdict.verdict == "PRESENT_AT_PROBE"
        assert "SUSPENDED" in (verdict.note or "")

    def test_transferred_to_another_organization_is_relocated(self) -> None:
        org_id = _org_row()
        client = FakeOrgClient()
        account_id = _account_row("888888888888")
        client.answer_account(
            "888888888888",
            {
                "Id": "888888888888",
                "Arn": "arn:aws:organizations::222222222222:account/o-other000000/888888888888",
                "Name": "moved",
            },
        )
        falsifier = AccountFalsifier(session=FakeOrgSession(client), account_id=MGMT_ACCOUNT, region=REGION)
        [verdict] = falsifier.batch_falsify([_candidate(account_id, ACCOUNT, parent=org_id)], _context())
        assert verdict.verdict == "RELOCATED"
        assert verdict.kind == "transferred"

    def test_no_organization_id_on_parent_is_scope_unknown(self) -> None:
        """A candidate whose recorded parent carries no organization_id (a foreign or malformed
        row) cannot be compared against — refused before any probe (though the shared reach read
        for the batch has already run)."""
        org_id = _org_row(organization_id="")
        client = FakeOrgClient()
        account_id = _account_row("999999999991")
        falsifier = AccountFalsifier(session=FakeOrgSession(client), account_id=MGMT_ACCOUNT, region=REGION)
        [verdict] = falsifier.batch_falsify([_candidate(account_id, ACCOUNT, parent=org_id)], _context())
        assert verdict.verdict == UNDETERMINED
        assert verdict.reason == "scope_unknown"
        assert "describe_account:999999999991" not in client.calls

    def test_wrong_organization_reach_is_scope_unknown(self) -> None:
        org_id = _org_row(organization_id="o-thisorg0001")
        client = FakeOrgClient(organization_id="o-otherorg001")
        account_id = _account_row("999999999992")
        falsifier = AccountFalsifier(session=FakeOrgSession(client), account_id=MGMT_ACCOUNT, region=REGION)
        [verdict] = falsifier.batch_falsify([_candidate(account_id, ACCOUNT, parent=org_id)], _context())
        assert verdict.verdict == UNDETERMINED
        assert verdict.reason == "scope_unknown"
        assert "describe_account:999999999992" not in client.calls


class TestFalsifierManifestWiringForOrganizations:
    def test_class_paths_resolve_to_falsifier_subclasses(self) -> None:
        from django.utils.module_loading import import_string

        from tap_grid.falsifiers import Falsifier

        for path in (
            "tap_plugin.aws_core.falsifiers.OrganizationalUnitFalsifier",
            "tap_plugin.aws_core.falsifiers.AccountFalsifier",
        ):
            cls = import_string(path)
            assert isinstance(cls, type) and issubclass(cls, Falsifier)

    def test_zero_argument_construction(self) -> None:
        """Boot calls ``cls()`` (tap_plugins/base.py::_register_falsifiers_from_manifest) — every
        constructor argument must default."""
        assert OrganizationalUnitFalsifier()
        assert AccountFalsifier()
