"""Edge-authority reads for the Organizations tree's reference edges (aws-core-tap#88).

Spec: specs/spec-aws-core-collector-v0.md (req-aws-collector-edge-authority-7, -8). An account moved
between OUs keeps its old ``NESTED_UNDER_PARENT`` edge until something says the run's edges are the
whole set; a policy detached from a target keeps its ``ATTACHED_TO_TARGET`` edge the same way. The
reader states, per node, whether it read that scope whole, and a failed page anywhere the scope
depends on must never read as "complete, found nothing".

Driven with the house fake ``organizations`` client from test_organizations.py, extended here with
paging: a parent's listing can return one page that says "more" and then fail.
"""

from __future__ import annotations

import ast
import inspect
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
from tap_plugin.aws_core.collectors.boto3_collector import organizations as organizations_mod
from tap_plugin.aws_core.collectors.boto3_collector.authority import COMPLETE, FAILED, PARTIAL
from tap_plugin.aws_core.collectors.boto3_collector.batch import node_anchor
from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector
from tap_plugin.aws_core.collectors.boto3_collector.identity import node_ref
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.organizations import (
    ACCOUNT,
    ATTACHED_TO_TARGET,
    NESTED_UNDER_PARENT,
    ORGANIZATION,
    ORGANIZATIONAL_UNIT,
    ORGANIZATIONS_POLICY,
    OUTBOUND,
    SERVICE_CONTROL_POLICY,
    collect_organization,
)

from tap_cares.collectors.config import CollectorConfig

from .test_boto3_collector_slice import _stub_aws  # noqa: F401 (fixture)
from .test_organizations import DIMENSIONS, ORG_ID, ROOT_ID, FakeOrganizations, _basic_org

TOP = "ou-ab12-top00001"
PROD = "ou-ab12-prod0001"
SHARED = "004940046501"
AT_ROOT = "222222222222"
SCP_ID = "p-examplepolicy1"
SCP_ARN = f"arn:aws:organizations::111111111111:policy/{ORG_ID}/service_control_policy/{SCP_ID}"
MANAGED_ID = "p-FullAWSAccess"
MANAGED_ARN = f"arn:aws:organizations::aws:policy/service_control_policy/{MANAGED_ID}"

_NUP = (NESTED_UNDER_PARENT, OUTBOUND)
_ATT = (ATTACHED_TO_TARGET, OUTBOUND)


def _throttled(op: str) -> ClientError:
    return ClientError({"Error": {"Code": "TooManyRequestsException", "Message": "slow down"}}, op)


class PagedOrganizations(FakeOrganizations):
    """The fake, plus a listing that answers one page saying "more" and then fails on the next.

    ``broken_*`` maps a parent (or policy) id to the items of its first page; the page after it
    raises a throttling error, the way a mid-walk failure looks to the reader.
    """

    def __init__(self) -> None:
        super().__init__()
        self.broken_ous_of: dict[str, list[dict[str, Any]]] = {}
        self.broken_accounts_of: dict[str, list[dict[str, Any]]] = {}
        self.broken_targets_of: dict[str, list[dict[str, Any]]] = {}

    @staticmethod
    def _paged(op: str, key: str, first: list[dict[str, Any]], token: str | None) -> dict[str, Any]:
        if token:
            raise _throttled(op)
        return {key: first, "NextToken": "page-2"}

    def list_organizational_units_for_parent(self, ParentId: str, **kwargs: Any) -> dict[str, Any]:
        if ParentId in self.broken_ous_of:
            self.calls.append(("list_organizational_units_for_parent", {"ParentId": ParentId, **kwargs}))
            return self._paged(
                "ListOrganizationalUnitsForParent", "OrganizationalUnits", self.broken_ous_of[ParentId], kwargs.get("NextToken")
            )
        return super().list_organizational_units_for_parent(ParentId, **kwargs)

    def list_accounts_for_parent(self, ParentId: str, **kwargs: Any) -> dict[str, Any]:
        if ParentId in self.broken_accounts_of:
            self.calls.append(("list_accounts_for_parent", {"ParentId": ParentId, **kwargs}))
            return self._paged("ListAccountsForParent", "Accounts", self.broken_accounts_of[ParentId], kwargs.get("NextToken"))
        return super().list_accounts_for_parent(ParentId, **kwargs)

    def list_targets_for_policy(self, PolicyId: str, **kwargs: Any) -> dict[str, Any]:
        if PolicyId in self.broken_targets_of:
            self.calls.append(("list_targets_for_policy", {"PolicyId": PolicyId, **kwargs}))
            return self._paged("ListTargetsForPolicy", "Targets", self.broken_targets_of[PolicyId], kwargs.get("NextToken"))
        return super().list_targets_for_policy(PolicyId, **kwargs)


def _org() -> PagedOrganizations:
    """org root -> Top -> Prod; account `shared` in Prod (moved there from the root), one at the
    root; one customer-managed SCP attached at Prod and one AWS-managed SCP attached at the root."""
    client = PagedOrganizations()
    _basic_org(client)
    client.ous_of[ROOT_ID] = [{"Id": TOP, "Name": "Top"}]
    client.ous_of[TOP] = [{"Id": PROD, "Name": "Prod"}]
    client.ous_of[PROD] = []
    client.accounts = [
        {"Id": SHARED, "Name": "shared", "Email": "s@x.com", "State": "ACTIVE"},
        {"Id": AT_ROOT, "Name": "at-root", "Email": "r@x.com", "State": "ACTIVE"},
    ]
    client.accounts_of[ROOT_ID] = [{"Id": AT_ROOT}]
    client.accounts_of[TOP] = []
    client.accounts_of[PROD] = [{"Id": SHARED}]
    client.policies = [
        {"Id": SCP_ID, "Arn": SCP_ARN, "Name": "DenyLeave", "AwsManaged": False},
        {"Id": MANAGED_ID, "Arn": MANAGED_ARN, "Name": "FullAWSAccess", "AwsManaged": True},
    ]
    client.targets_of[SCP_ID] = [{"TargetId": PROD, "Type": "ORGANIZATIONAL_UNIT"}]
    client.targets_of[MANAGED_ID] = [{"TargetId": ROOT_ID, "Type": "ROOT"}]
    return client


def _reads(tree: Any, entity_type: str, key: str) -> dict[tuple[str, str], str]:
    return tree.edge_reads.get(node_ref(entity_type, key), {})


def _outbound(tree: Any, edge_type: str, entity_type: str, key: str) -> list[str]:
    """The batch's ``edge_type`` edges leaving one node, by target ref: the set a claim calls whole."""
    ref = node_ref(entity_type, key)
    return sorted(e["edge"]["to_ref"] for e in tree.edges if e["edge"]["edge_type"] == edge_type and e["edge"]["from_ref"] == ref)


class TestPlacement:
    def test_every_account_and_ou_is_complete_when_the_walk_is(self):
        tree = collect_organization(_org(), DIMENSIONS)
        for entity_type, key in ((ACCOUNT, SHARED), (ACCOUNT, AT_ROOT), (ORGANIZATIONAL_UNIT, TOP), (ORGANIZATIONAL_UNIT, PROD)):
            assert _reads(tree, entity_type, key) == {_NUP: COMPLETE}, (entity_type, key)

    def test_a_complete_claim_covers_exactly_the_one_parent_edge_the_batch_sends(self):
        # The moved account: the batch asserts only shared -> Prod, so a complete claim is what lets
        # tap propose the edge to its old parent (the root) for removal.
        tree = collect_organization(_org(), DIMENSIONS)
        assert _outbound(tree, NESTED_UNDER_PARENT, ACCOUNT, SHARED) == [node_ref(ORGANIZATIONAL_UNIT, PROD)]
        assert _outbound(tree, NESTED_UNDER_PARENT, ACCOUNT, AT_ROOT) == [node_ref(ORGANIZATION, ORG_ID)]

    def test_the_organization_is_never_an_anchor(self):
        # The organization stands for the root, which has no parent; its edges here are all inbound
        # or containment, and neither is claimed.
        tree = collect_organization(_org(), DIMENSIONS)
        assert _reads(tree, ORGANIZATION, ORG_ID) == {}

    def test_a_failed_account_page_fails_every_account_s_placement(self):
        # ListAccountsForParent(root) answers one page that says "more", then fails. `at-root` was
        # named on that page and its edge is sent, yet no account's placement is complete: an account
        # the failed page did not name may sit under the root as well.
        client = _org()
        client.broken_accounts_of[ROOT_ID] = [{"Id": AT_ROOT}]
        tree = collect_organization(client, DIMENSIONS)
        assert _outbound(tree, NESTED_UNDER_PARENT, ACCOUNT, AT_ROOT) == [node_ref(ORGANIZATION, ORG_ID)]
        assert _reads(tree, ACCOUNT, AT_ROOT) == {_NUP: FAILED}
        assert _reads(tree, ACCOUNT, SHARED) == {_NUP: FAILED}
        # An OU's parent comes from the OU walk, which did not fail.
        assert _reads(tree, ORGANIZATIONAL_UNIT, PROD) == {_NUP: COMPLETE}

    def test_a_failed_ou_page_fails_the_ou_it_named_and_every_account(self):
        # ListOrganizationalUnitsForParent(root) names Top on its first page, then fails.
        client = _org()
        client.broken_ous_of[ROOT_ID] = [{"Id": TOP, "Name": "Top"}]
        tree = collect_organization(client, DIMENSIONS)
        assert _outbound(tree, NESTED_UNDER_PARENT, ORGANIZATIONAL_UNIT, TOP) == [node_ref(ORGANIZATION, ORG_ID)]
        assert _reads(tree, ORGANIZATIONAL_UNIT, TOP) == {_NUP: FAILED}
        # Prod was named by Top's own listing, which finished.
        assert _reads(tree, ORGANIZATIONAL_UNIT, PROD) == {_NUP: COMPLETE}
        # The walk that finds every parent failed, so no account's parent set is known whole.
        assert _reads(tree, ACCOUNT, SHARED) == {_NUP: FAILED}
        assert _reads(tree, ACCOUNT, AT_ROOT) == {_NUP: FAILED}

    def test_an_account_named_under_two_parents_is_partial(self):
        # A MoveAccount between two parent listings: the walk finished, but cannot say which parent
        # is the account's.
        client = _org()
        client.accounts_of[TOP] = [{"Id": SHARED}]
        tree = collect_organization(client, DIMENSIONS)
        assert _reads(tree, ACCOUNT, SHARED) == {_NUP: PARTIAL}
        assert _reads(tree, ACCOUNT, AT_ROOT) == {_NUP: COMPLETE}

    def test_an_account_no_parent_named_is_partial_and_sends_no_parent_edge(self):
        client = _org()
        client.accounts_of[PROD] = []
        tree = collect_organization(client, DIMENSIONS)
        assert _outbound(tree, NESTED_UNDER_PARENT, ACCOUNT, SHARED) == []
        # Never a complete claim over an empty set: that would propose removing its real parent edge.
        assert _reads(tree, ACCOUNT, SHARED) == {_NUP: PARTIAL}

    def test_an_ou_the_model_refused_leaves_its_accounts_unlisted_so_placement_is_partial(self):
        # Top's tags cannot be read, so Top is not written and its children are never listed: Prod
        # is not in the batch, `shared` (a member, from ListAccounts) is sent with no parent edge,
        # and `at-root`'s placement cannot be called whole either.
        client = _org()
        client.tag_errors[TOP] = _throttled("ListTagsForResource")
        tree = collect_organization(client, DIMENSIONS)
        assert _reads(tree, ORGANIZATIONAL_UNIT, TOP) == {}
        assert _reads(tree, ORGANIZATIONAL_UNIT, PROD) == {}
        assert _outbound(tree, NESTED_UNDER_PARENT, ACCOUNT, SHARED) == []
        assert _reads(tree, ACCOUNT, SHARED) == {_NUP: PARTIAL}
        assert _reads(tree, ACCOUNT, AT_ROOT) == {_NUP: PARTIAL}

    def test_a_node_the_tree_did_not_write_is_never_judged(self):
        # `shared`'s tags cannot be read: the account is not written, so nothing may be claimed at it.
        client = _org()
        client.tag_errors[SHARED] = _throttled("ListTagsForResource")
        tree = collect_organization(client, DIMENSIONS)
        written = {n["entity"]["ref"] for n in tree.nodes}
        assert node_ref(ACCOUNT, SHARED) not in written
        assert set(tree.edge_reads) <= written


class TestAttachments:
    def test_a_customer_managed_policy_s_targets_are_complete(self):
        tree = collect_organization(_org(), DIMENSIONS)
        assert _reads(tree, SERVICE_CONTROL_POLICY, SCP_ARN) == {_ATT: COMPLETE}
        assert _outbound(tree, ATTACHED_TO_TARGET, SERVICE_CONTROL_POLICY, SCP_ARN) == [node_ref(ORGANIZATIONAL_UNIT, PROD)]

    def test_complete_and_empty_is_said(self):
        client = _org()
        client.targets_of[SCP_ID] = []
        tree = collect_organization(client, DIMENSIONS)
        assert _outbound(tree, ATTACHED_TO_TARGET, SERVICE_CONTROL_POLICY, SCP_ARN) == []
        assert _reads(tree, SERVICE_CONTROL_POLICY, SCP_ARN) == {_ATT: COMPLETE}

    def test_a_failed_targets_page_is_failed_not_empty(self):
        client = _org()
        client.broken_targets_of[SCP_ID] = [{"TargetId": PROD, "Type": "ORGANIZATIONAL_UNIT"}]
        tree = collect_organization(client, DIMENSIONS)
        assert _outbound(tree, ATTACHED_TO_TARGET, SERVICE_CONTROL_POLICY, SCP_ARN) == [node_ref(ORGANIZATIONAL_UNIT, PROD)]
        assert _reads(tree, SERVICE_CONTROL_POLICY, SCP_ARN) == {_ATT: FAILED}

    def test_a_target_the_reader_cannot_map_is_partial(self):
        client = _org()
        client.targets_of[SCP_ID] = [
            {"TargetId": PROD, "Type": "ORGANIZATIONAL_UNIT"},
            {"TargetId": "x-unknown", "Type": "SOMETHING_NEW"},
        ]
        tree = collect_organization(client, DIMENSIONS)
        assert _reads(tree, SERVICE_CONTROL_POLICY, SCP_ARN) == {_ATT: PARTIAL}

    def test_an_aws_managed_policy_is_never_claimed(self):
        # Its ARN names no organization, so its one node is every organization's in the partition.
        tree = collect_organization(_org(), DIMENSIONS)
        assert _outbound(tree, ATTACHED_TO_TARGET, SERVICE_CONTROL_POLICY, MANAGED_ARN) == [node_ref(ORGANIZATION, ORG_ID)]
        assert _reads(tree, SERVICE_CONTROL_POLICY, MANAGED_ARN) == {}

    def test_a_policy_whose_managed_flag_is_missing_is_never_claimed(self):
        client = _org()
        client.policies = [{"Id": SCP_ID, "Arn": SCP_ARN, "Name": "DenyLeave"}]
        tree = collect_organization(client, DIMENSIONS)
        assert _reads(tree, SERVICE_CONTROL_POLICY, SCP_ARN) == {}

    def test_other_policy_types_are_claimed_the_same_way(self):
        client = _org()
        client.roots = [
            {"Id": ROOT_ID, "Name": "Root", "PolicyTypes": [{"Type": "TAG_POLICY", "Status": "ENABLED"}]}
        ]
        tag_arn = f"arn:aws:organizations::111111111111:policy/{ORG_ID}/tag_policy/p-tagpolicy01"
        scp = client.policies[0]
        tag = {"Id": "p-tagpolicy01", "Arn": tag_arn, "Name": "Tags", "AwsManaged": False, "Type": "TAG_POLICY"}

        def _policies(**kwargs: Any) -> dict[str, Any]:
            return {"Policies": [tag] if kwargs.get("Filter") == "TAG_POLICY" else [scp]}

        client.list_policies = _policies  # type: ignore[method-assign]
        client.targets_of["p-tagpolicy01"] = [{"TargetId": AT_ROOT, "Type": "ACCOUNT"}]
        tree = collect_organization(client, DIMENSIONS)
        assert _reads(tree, ORGANIZATIONS_POLICY, tag_arn) == {_ATT: COMPLETE}


# ---------------------------------------------------------------------------
# Through the collector
# ---------------------------------------------------------------------------


def _judged_claims(monkeypatch, client: FakeOrganizations) -> list[dict[str, Any]]:
    """Run the collector over ``client``'s organization and return the claims it sends (judged only,
    not imported)."""
    monkeypatch.setattr(collector_mod, "importer_accepts_edge_cases", lambda: True)
    monkeypatch.setattr(collector_mod, "collect_organization", lambda _client, dims: collect_organization(client, dims))
    documents: list[dict[str, Any]] = []

    def _judge_only(self, document, **_kw):
        documents.append(document)
        return SimpleNamespace(imported_batches=[], counts=SimpleNamespace(batches_imported=0))

    monkeypatch.setattr(Boto3Collector, "submit_grift", _judge_only)
    collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
    collector.run()
    assert collector.results["error"] == []
    return documents[0]["batches"][0]["edge_cases"]["authority"]


def _claim(claims: list[dict[str, Any]], edge_type: str, entity_type: str, key: dict[str, str]) -> list[dict[str, Any]]:
    anchor = {"entity_type": entity_type, "key": key}
    return [c for c in claims if c["edge_type"] == edge_type and c["anchor"] == anchor]


@pytest.mark.django_db
@pytest.mark.usefixtures("_stub_aws")
class TestThroughTheCollector:
    def test_the_moved_account_is_claimed_complete_by_type_and_key(self, monkeypatch):
        claims = _judged_claims(monkeypatch, _org())
        assert _claim(claims, NESTED_UNDER_PARENT, ACCOUNT, {"account_id": SHARED}) == [
            {
                "edge_type": NESTED_UNDER_PARENT,
                "anchor": {"entity_type": ACCOUNT, "key": {"account_id": SHARED}},
                "direction": "outbound",
                "read": COMPLETE,
            }
        ]
        assert [c["read"] for c in _claim(claims, NESTED_UNDER_PARENT, ORGANIZATIONAL_UNIT, {"ou_id": PROD})] == [COMPLETE]
        assert [c["read"] for c in _claim(claims, ATTACHED_TO_TARGET, SERVICE_CONTROL_POLICY, {"policy_arn": SCP_ARN})] == [
            COMPLETE
        ]
        assert _claim(claims, ATTACHED_TO_TARGET, SERVICE_CONTROL_POLICY, {"policy_arn": MANAGED_ARN}) == []
        # One claim per scope across the whole batch, manifest and Organizations together.
        scopes = [(c["edge_type"], repr(sorted(c["anchor"].items())), c["direction"]) for c in claims]
        assert len(scopes) == len(set(scopes))

    def test_a_failed_placement_page_is_sent_as_failed(self, monkeypatch):
        client = _org()
        client.broken_accounts_of[PROD] = [{"Id": SHARED}]
        claims = _judged_claims(monkeypatch, client)
        assert [c["read"] for c in _claim(claims, NESTED_UNDER_PARENT, ACCOUNT, {"account_id": SHARED})] == [FAILED]
        assert [c["read"] for c in _claim(claims, NESTED_UNDER_PARENT, ACCOUNT, {"account_id": AT_ROOT})] == [FAILED]

    def test_every_organizations_anchor_names_a_node_the_batch_sends(self, monkeypatch):
        claims = _judged_claims(monkeypatch, _org())
        tree = collect_organization(_org(), DIMENSIONS)
        sent = [node_anchor(n) for n in tree.nodes]
        org_types = {NESTED_UNDER_PARENT, ATTACHED_TO_TARGET}
        assert all(c["anchor"] in sent for c in claims if c["edge_type"] in org_types)


class TestNoOtherProducer:
    """The scope a claim names is every live edge of the type at the anchor, whoever wrote it. Only
    organizations.py writes the two claimed types in this collector, so nothing else the batch sends
    can fall inside a claimed scope unread."""

    def test_only_the_organizations_reader_writes_the_claimed_types(self):
        claimed = {NESTED_UNDER_PARENT, ATTACHED_TO_TARGET}
        rule_types = {r["edge_type"] for e in manifest_entries() for r in e.get("edges", [])}
        containment_types = {e["containment"]["edge_type"] for e in manifest_entries() if e.get("containment")}
        assert not (claimed & (rule_types | containment_types))
        here = Path(inspect.getfile(organizations_mod)).parent
        for module in ("landing_zone", "findings", "containment", "edges", "customfns"):
            tree = ast.parse((here / f"{module}.py").read_text())
            constants = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            assert not (claimed & constants), module
