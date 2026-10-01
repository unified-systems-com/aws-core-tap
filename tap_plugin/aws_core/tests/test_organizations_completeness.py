"""Organizations completeness, collect-only (aws-core-tap#65, req-aws-core-organizations-completeness).

Two layers, as in ``test_organizations.py``: the reader against a canned, PAGINATING
``organizations`` client (no grid), and the four new falsifiers against real grid rows and a fake
client. The fixture is shaped on a real GovCloud organization (partition ``aws-us-gov``, a tag
policy and FullAWSAccess attached at the root, OUs nested three deep); every response is canned.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector.organizations import (
    ACCOUNT,
    ATTACHED_TO_TARGET,
    CONTAINMENT_SURFACES,
    DECLARES_STATEMENT,
    DECLARES_TAG_RULE,
    DELEGATED_ADMINISTRATION,
    DELEGATES_TO_ACCOUNT,
    HOLDS_DELEGATION,
    HOLDS_ORGANIZATIONS_POLICY,
    HOLDS_SERVICE_CONTROL_POLICY,
    ORGANIZATION,
    ORGANIZATIONAL_UNIT,
    ORGANIZATIONS_POLICY,
    PAGINATED_OPERATIONS,
    POLICY_STATEMENT,
    SERVICE_CONTROL_POLICY,
    TAG_POLICY_RULE,
    collect_organization,
    is_aws_managed_policy_arn,
    organization_id_of_policy_arn,
    policy_id_of_arn,
)
from tap_plugin.aws_core.collectors.boto3_collector.policy_documents import (
    content_sha256,
    normalize_statement,
    parse_statements,
    parse_tag_rules,
)
from tap_plugin.aws_core.falsifiers import (
    DelegatedAdministrationFalsifier,
    OrganizationsPolicyFalsifier,
    PolicyStatementFalsifier,
    TagPolicyRuleFalsifier,
)

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
    UNDETERMINED,
    Candidate,
    FalsifyContext,
    unsupported,
)
from tap_grid.services import create_edge, create_node, delete_node, get_node

PARTITION = "aws-us-gov"
ORG_ID = "o-02tvy5y4l7"
ROOT_ID = "r-0vv8"
MGMT = "111111111111"
SECURITY = "222222222222"
AUDIT = "333333333333"
DIMENSIONS = {"cloud": "aws", "aws_account": MGMT, "aws_region": "global"}
REGION = "us-gov-west-1"

OU_1 = "ou-0vv8-level1aa"
OU_2 = "ou-0vv8-level2aa"
OU_3 = "ou-0vv8-level3aa"


def _policy_arn(kind: str, pid: str) -> str:
    return f"arn:{PARTITION}:organizations::{MGMT}:policy/{ORG_ID}/{kind}/{pid}"


FULL_AWS_ACCESS_ARN = f"arn:{PARTITION}:organizations::aws:policy/service_control_policy/p-FullAWSAccess"
SCP_DENY_ARN = _policy_arn("service_control_policy", "p-denyregion1")
SCP_GUARD_ARN = _policy_arn("service_control_policy", "p-guardrails1")
TAG_POLICY_ARN = _policy_arn("tag_policy", "p-tagpolicy01")
RCP_ARN = _policy_arn("resource_control_policy", "p-rcppolicy01")
DECL_ARN = _policy_arn("declarative_policy_ec2", "p-declaratv01")

FULL_AWS_ACCESS_DOC = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]})
DENY_DOC = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "A", "Effect": "Deny", "Action": "s3:*", "Resource": "*"},
            {"Effect": "Allow", "Action": "*", "Resource": "*"},
        ],
    }
)
GUARD_DOC = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyOutsideGov",
                "Effect": "Deny",
                "NotAction": ["iam:*", "sts:*"],
                "Resource": "*",
                "Condition": {"StringNotEquals": {"aws:RequestedRegion": ["us-gov-west-1", "us-gov-east-1"]}},
            }
        ],
    }
)
TAG_DOC = json.dumps(
    {
        "tags": {
            "environment": {
                "tag_key": {"@@assign": "Environment"},
                "tag_value": {"@@assign": ["dev", "prod"]},
                "enforced_for": {"@@assign": ["ec2:instance"]},
            },
            "costcenter": {"tag_key": {"@@assign": "CostCenter"}},
        }
    }
)
RCP_DOC = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "EnforceTls",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:*",
                "Resource": "*",
                "Condition": {"Bool": {"aws:SecureTransport": False}},
            }
        ],
    }
)


def _err(code: str, op: str = "Op") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, op)


class PagedOrganizations:
    """A canned ``organizations`` client that PAGINATES: each (operation, key) holds a list of pages,
    and a page may be an exception, so a test can fail page two of any listing."""

    def __init__(self) -> None:
        self.organization: dict[str, Any] | Exception = {
            "Id": ORG_ID,
            "Arn": f"arn:{PARTITION}:organizations::{MGMT}:organization/{ORG_ID}",
            "MasterAccountId": MGMT,
            "FeatureSet": "ALL",
        }
        self.pages: dict[tuple[str, str], list[Any]] = {}
        #: Failing pages, kept apart from the item pages so the raised value is always an exception.
        self.failures: dict[tuple[str, str, int], Exception] = {}
        self.documents: dict[str, tuple[dict[str, Any], str] | Exception] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def set(self, op: str, key: str, *pages: Any) -> None:
        self.pages[(op, key)] = [[] if isinstance(page, Exception) else page for page in pages]
        for index, page in enumerate(pages):
            if isinstance(page, Exception):
                self.failures[(op, key, index)] = page
            else:
                self.failures.pop((op, key, index), None)

    def _page(self, op: str, key: str, result_key: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((op, dict(kwargs)))
        pages = self.pages.get((op, key), [[]])
        index = int(kwargs.get("NextToken") or 0)
        failure = self.failures.get((op, key, index))
        if failure is not None:
            raise failure
        response: dict[str, Any] = {result_key: pages[index]}
        if index + 1 < len(pages):
            response["NextToken"] = str(index + 1)
        return response

    def describe_organization(self) -> dict[str, Any]:
        self.calls.append(("describe_organization", {}))
        if isinstance(self.organization, Exception):
            raise self.organization
        return {"Organization": self.organization}

    def list_roots(self, **kw: Any) -> dict[str, Any]:
        return self._page("list_roots", "", "Roots", kw)

    def list_organizational_units_for_parent(self, ParentId: str, **kw: Any) -> dict[str, Any]:
        return self._page("list_organizational_units_for_parent", ParentId, "OrganizationalUnits", {"ParentId": ParentId, **kw})

    def list_accounts(self, **kw: Any) -> dict[str, Any]:
        return self._page("list_accounts", "", "Accounts", kw)

    def list_accounts_for_parent(self, ParentId: str, **kw: Any) -> dict[str, Any]:
        return self._page("list_accounts_for_parent", ParentId, "Accounts", {"ParentId": ParentId, **kw})

    def list_policies(self, Filter: str, **kw: Any) -> dict[str, Any]:
        return self._page("list_policies", Filter, "Policies", {"Filter": Filter, **kw})

    def list_targets_for_policy(self, PolicyId: str, **kw: Any) -> dict[str, Any]:
        return self._page("list_targets_for_policy", PolicyId, "Targets", {"PolicyId": PolicyId, **kw})

    def list_tags_for_resource(self, ResourceId: str, **kw: Any) -> dict[str, Any]:
        return self._page("list_tags_for_resource", ResourceId, "Tags", {"ResourceId": ResourceId, **kw})

    def list_aws_service_access_for_organization(self, **kw: Any) -> dict[str, Any]:
        return self._page("list_aws_service_access_for_organization", "", "EnabledServicePrincipals", kw)

    def list_delegated_administrators(self, **kw: Any) -> dict[str, Any]:
        return self._page("list_delegated_administrators", "", "DelegatedAdministrators", kw)

    def list_delegated_services_for_account(self, AccountId: str, **kw: Any) -> dict[str, Any]:
        return self._page("list_delegated_services_for_account", AccountId, "DelegatedServices", {"AccountId": AccountId, **kw})

    def describe_policy(self, PolicyId: str) -> dict[str, Any]:
        self.calls.append(("describe_policy", {"PolicyId": PolicyId}))
        entry = self.documents[PolicyId]
        if isinstance(entry, Exception):
            raise entry  # pylint: disable=raising-bad-type
        summary, content = entry
        return {"Policy": {"PolicySummary": summary, "Content": content}}

    def called(self, op: str, **match: Any) -> list[dict[str, Any]]:
        return [kw for o, kw in self.calls if o == op and all(kw.get(k) == v for k, v in match.items())]


def _summary(arn: str, name: str, kind: str, *, aws_managed: bool = False) -> dict[str, Any]:
    return {"Id": policy_id_of_arn(arn), "Arn": arn, "Name": name, "Type": kind, "AwsManaged": aws_managed}


def _govcloud_org(*, enabled: list[tuple[str, str]] | None = None) -> PagedOrganizations:
    """The real GovCloud org's shape: three nested OUs, a member in the deepest, FullAWSAccess and a
    tag policy at the root, two customer SCPs, root and OU tags, two delegations."""
    c = PagedOrganizations()
    policy_types = enabled if enabled is not None else [("SERVICE_CONTROL_POLICY", "ENABLED"), ("TAG_POLICY", "ENABLED")]
    c.set("list_roots", "", [{"Id": ROOT_ID, "Name": "Root", "PolicyTypes": [{"Type": t, "Status": s} for t, s in policy_types]}])
    c.set("list_tags_for_resource", ROOT_ID, [{"Key": "a", "Value": "b"}])
    c.set("list_tags_for_resource", OU_1, [{"Key": "tier", "Value": "1"}])
    c.set("list_organizational_units_for_parent", ROOT_ID, [{"Id": OU_1, "Name": "L1"}])
    c.set("list_organizational_units_for_parent", OU_1, [{"Id": OU_2, "Name": "L2"}])
    c.set("list_organizational_units_for_parent", OU_2, [{"Id": OU_3, "Name": "L3"}])
    accounts = [{"Id": a, "Name": f"acct-{a[:3]}", "State": "ACTIVE"} for a in (MGMT, SECURITY, AUDIT)]
    c.set("list_accounts", "", accounts)
    c.set("list_accounts_for_parent", ROOT_ID, [{"Id": MGMT}])
    c.set("list_accounts_for_parent", OU_3, [{"Id": SECURITY}, {"Id": AUDIT}])
    c.set(
        "list_aws_service_access_for_organization",
        "",
        [{"ServicePrincipal": "config.amazonaws.com", "DateEnabled": datetime(2026, 9, 1, tzinfo=UTC)}],
        [{"ServicePrincipal": "guardduty.amazonaws.com", "DateEnabled": datetime(2026, 9, 2, tzinfo=UTC)}],
    )
    c.set("list_delegated_administrators", "", [{"Id": SECURITY}], [{"Id": AUDIT}])
    c.set(
        "list_delegated_services_for_account",
        SECURITY,
        [{"ServicePrincipal": "guardduty.amazonaws.com", "DelegationEnabledDate": datetime(2026, 9, 3, tzinfo=UTC)}],
        [{"ServicePrincipal": "securityhub.amazonaws.com", "DelegationEnabledDate": datetime(2026, 9, 4, tzinfo=UTC)}],
    )
    c.set("list_delegated_services_for_account", AUDIT, [{"ServicePrincipal": "config.amazonaws.com"}])
    full = _summary(FULL_AWS_ACCESS_ARN, "FullAWSAccess", "SERVICE_CONTROL_POLICY", aws_managed=True)
    deny = _summary(SCP_DENY_ARN, "DenyS3", "SERVICE_CONTROL_POLICY")
    guard = _summary(SCP_GUARD_ARN, "Guardrails", "SERVICE_CONTROL_POLICY")
    c.set("list_policies", "SERVICE_CONTROL_POLICY", [full, deny], [guard])
    c.set("list_policies", "TAG_POLICY", [_summary(TAG_POLICY_ARN, "tt-environment-tag", "TAG_POLICY")])
    c.set("list_targets_for_policy", full["Id"], [{"TargetId": ROOT_ID, "Type": "ROOT"}])
    c.set("list_targets_for_policy", deny["Id"], [{"TargetId": OU_3, "Type": "ORGANIZATIONAL_UNIT"}])
    c.set("list_targets_for_policy", guard["Id"], [{"TargetId": SECURITY, "Type": "ACCOUNT"}])
    c.set("list_targets_for_policy", policy_id_of_arn(TAG_POLICY_ARN), [{"TargetId": ROOT_ID, "Type": "ROOT"}])
    c.set("list_tags_for_resource", policy_id_of_arn(TAG_POLICY_ARN), [{"Key": "owner", "Value": "platform"}])
    c.documents[full["Id"]] = (full, FULL_AWS_ACCESS_DOC)
    c.documents[deny["Id"]] = (deny, DENY_DOC)
    c.documents[guard["Id"]] = (guard, GUARD_DOC)
    c.documents[policy_id_of_arn(TAG_POLICY_ARN)] = (_summary(TAG_POLICY_ARN, "tt-environment-tag", "TAG_POLICY"), TAG_DOC)
    return c


def _nodes(tree: Any, entity_type: str) -> list[dict[str, Any]]:
    return [n for n in tree.nodes if n["entity"]["entity_type"] == entity_type]


def _one(tree: Any, entity_type: str, **match: Any) -> dict[str, Any]:
    found = [n for n in _nodes(tree, entity_type) if all(n["node"].get(k) == v for k, v in match.items())]
    assert len(found) == 1, (entity_type, match, found)
    return found[0]


def _edges(tree: Any, edge_type: str) -> list[dict[str, Any]]:
    return [e for e in tree.edges if e["edge"]["edge_type"] == edge_type]


def _surfaces(tree: Any, edge_type: str, subject: str | None = None) -> list[Any]:
    return [s for s in tree.listings if s.edge_type == edge_type and (subject is None or s.subject == subject)]


def _id(node: dict[str, Any]) -> str:
    return str(node["entity"]["entity_id"])


# ---------------------------------------------------------------------------
# The reader
# ---------------------------------------------------------------------------


class TestRootAndOrganizationFields:
    @pytest.mark.spec("req-aws-core-organizations-completeness-1")
    def test_root_tags_land_on_the_organization(self) -> None:
        tree = collect_organization(_govcloud_org(), DIMENSIONS)
        org = _one(tree, ORGANIZATION, organization_id=ORG_ID)
        assert org["node"]["tags"] == {"a": "b"}
        assert org["node"]["partition"] == "aws-us-gov"
        assert not [n for n in tree.notices if n.code == "ORG_NODE_SKIPPED"]

    @pytest.mark.spec("req-aws-core-organizations-completeness-1")
    def test_denied_root_tag_read_withholds_the_organization_but_records_its_surfaces(self) -> None:
        client = _govcloud_org()
        client.set("list_tags_for_resource", ROOT_ID, _err("AccessDeniedException"))
        tree = collect_organization(client, DIMENSIONS)
        assert _nodes(tree, ORGANIZATION) == []
        assert any(n.code == "ORG_TAGS_DENIED" for n in tree.notices)
        org_subject = {s.subject for s in tree.listings if s.edge_type == HOLDS_DELEGATION}
        assert len(org_subject) == 1, "the surfaces are still recorded; core skips them (parent not observed)"

    @pytest.mark.spec("req-aws-core-organizations-completeness-1", "req-aws-core-organizations-collect-4")
    def test_list_roots_denied_keeps_the_node_with_root_tags_unknown_not_empty(self) -> None:
        """The Copilot finding carried from aws-core-tap#71: no root id means no root tags to read.
        The node is kept (-collect-4) with tags null ("not read"), never {}."""
        client = _govcloud_org()
        client.set("list_roots", "", _err("AccessDeniedException"))
        tree = collect_organization(client, DIMENSIONS)
        org = _one(tree, ORGANIZATION, organization_id=ORG_ID)
        assert org["node"]["tags"] is None
        assert org["node"]["enabled_policy_types"] is None
        assert not client.called("list_tags_for_resource")
        edges = {s.edge_type for s in tree.listings}
        assert edges == set(CONTAINMENT_SURFACES[ORGANIZATION])
        assert all(s.complete is False and s.authorized is False for s in tree.listings)

    @pytest.mark.spec("req-aws-core-organizations-completeness-1", "req-aws-collector-pagination-2")
    def test_list_roots_second_page_failure_is_the_same_unread_case(self) -> None:
        client = _govcloud_org()
        client.set("list_roots", "", [{"Id": ROOT_ID, "PolicyTypes": []}], _err("TooManyRequestsException"))
        tree = collect_organization(client, DIMENSIONS)
        org = _one(tree, ORGANIZATION, organization_id=ORG_ID)
        assert org["node"]["tags"] is None
        assert org["node"]["enabled_policy_types"] is None
        assert all(s.complete is False for s in tree.listings)

    @pytest.mark.spec("req-aws-core-organizations-completeness-2")
    def test_only_enabled_policy_types_and_pending_ones_are_never_listed(self) -> None:
        client = _govcloud_org(enabled=[("SERVICE_CONTROL_POLICY", "ENABLED"), ("TAG_POLICY", "PENDING_ENABLE")])
        tree = collect_organization(client, DIMENSIONS)
        org = _one(tree, ORGANIZATION, organization_id=ORG_ID)
        assert org["node"]["enabled_policy_types"] == ["SERVICE_CONTROL_POLICY"]
        assert client.called("list_policies", Filter="TAG_POLICY") == []
        [surface] = _surfaces(tree, HOLDS_ORGANIZATIONS_POLICY)
        assert surface.complete is True and surface.count == 0

    @pytest.mark.spec("req-aws-core-organizations-completeness-2")
    def test_observed_none_is_an_empty_list(self) -> None:
        tree = collect_organization(_govcloud_org(enabled=[]), DIMENSIONS)
        assert _one(tree, ORGANIZATION, organization_id=ORG_ID)["node"]["enabled_policy_types"] == []

    @pytest.mark.spec("req-aws-core-organizations-completeness-3", "req-aws-collector-pagination-1")
    def test_service_access_reads_both_pages(self) -> None:
        tree = collect_organization(_govcloud_org(), DIMENSIONS)
        org = _one(tree, ORGANIZATION, organization_id=ORG_ID)
        assert org["node"]["enabled_service_principals"] == [
            {"service_principal": "config.amazonaws.com", "enabled_at": "2026-09-01T00:00:00Z"},
            {"service_principal": "guardduty.amazonaws.com", "enabled_at": "2026-09-02T00:00:00Z"},
        ]

    @pytest.mark.spec("req-aws-core-organizations-completeness-3", "req-aws-collector-pagination-2")
    @pytest.mark.parametrize("pages", [(_err("AccessDeniedException"),), ([{"ServicePrincipal": "config.amazonaws.com"}], _err("ServiceException"))])
    def test_failed_service_access_read_is_null_never_partial(self, pages: tuple[Any, ...]) -> None:
        client = _govcloud_org()
        client.set("list_aws_service_access_for_organization", "", *pages)
        tree = collect_organization(client, DIMENSIONS)
        assert _one(tree, ORGANIZATION, organization_id=ORG_ID)["node"]["enabled_service_principals"] is None


class TestDelegations:
    @pytest.mark.spec("req-aws-core-organizations-completeness-4", "req-aws-core-organizations-completeness-13")
    def test_two_delegations_of_one_account_across_pages(self) -> None:
        tree = collect_organization(_govcloud_org(), DIMENSIONS)
        security = {n["node"]["service_principal"] for n in _nodes(tree, DELEGATED_ADMINISTRATION) if n["node"]["account_id"] == SECURITY}
        assert security == {"guardduty.amazonaws.com", "securityhub.amazonaws.com"}
        assert len(_nodes(tree, DELEGATED_ADMINISTRATION)) == 3, "the outer listing's second page (AUDIT) was read too"
        node = _one(tree, DELEGATED_ADMINISTRATION, account_id=SECURITY, service_principal="guardduty.amazonaws.com")
        assert node["node"]["organization_id"] == ORG_ID
        assert node["node"]["delegation_enabled_at"] == "2026-09-03T00:00:00Z"
        assert node["node"]["tags"] == {}
        assert len(_edges(tree, HOLDS_DELEGATION)) == 3
        assert len(_edges(tree, DELEGATES_TO_ACCOUNT)) == 3
        [surface] = _surfaces(tree, HOLDS_DELEGATION)
        assert surface.complete is True and surface.count == 3

    @pytest.mark.spec("req-aws-core-organizations-completeness-13", "req-aws-collector-pagination-2")
    def test_one_failed_inner_listing_makes_the_one_surface_incomplete(self) -> None:
        client = _govcloud_org()
        client.set(
            "list_delegated_services_for_account",
            SECURITY,
            [{"ServicePrincipal": "guardduty.amazonaws.com"}],
            _err("TooManyRequestsException"),
        )
        tree = collect_organization(client, DIMENSIONS)
        surfaces = _surfaces(tree, HOLDS_DELEGATION)
        assert len(surfaces) == 1, "exactly one HOLDS_DELEGATION surface; never one per delegated account"
        assert surfaces[0].complete is False
        assert surfaces[0].admitted is False
        assert "TooManyRequestsException" in surfaces[0].reasons["enumeration_complete"]

    @pytest.mark.spec("req-aws-core-organizations-completeness-13")
    def test_account_not_registered_means_the_reads_disagree(self) -> None:
        client = _govcloud_org()
        client.set("list_delegated_services_for_account", AUDIT, _err("AccountNotRegisteredException"))
        tree = collect_organization(client, DIMENSIONS)
        [surface] = _surfaces(tree, HOLDS_DELEGATION)
        assert surface.complete is False
        assert "AccountNotRegisteredException" in surface.reasons["enumeration_complete"]
        assert any(n.code == "ORG_DELEGATION_READS_DISAGREE" for n in tree.notices)

    @pytest.mark.spec("req-aws-core-organizations-completeness-13", "req-aws-collector-pagination-2")
    def test_failed_outer_second_page_is_incomplete(self) -> None:
        client = _govcloud_org()
        client.set("list_delegated_administrators", "", [{"Id": SECURITY}], _err("ServiceException"))
        tree = collect_organization(client, DIMENSIONS)
        [surface] = _surfaces(tree, HOLDS_DELEGATION)
        assert surface.complete is False


class TestPolicies:
    @pytest.mark.spec("req-aws-core-organizations-completeness-6")
    def test_customer_managed_scps_are_contained_and_full_aws_access_is_not(self) -> None:
        tree = collect_organization(_govcloud_org(), DIMENSIONS)
        org = _one(tree, ORGANIZATION, organization_id=ORG_ID)
        full = _one(tree, SERVICE_CONTROL_POLICY, policy_arn=FULL_AWS_ACCESS_ARN)
        deny = _one(tree, SERVICE_CONTROL_POLICY, policy_arn=SCP_DENY_ARN)
        guard = _one(tree, SERVICE_CONTROL_POLICY, policy_arn=SCP_GUARD_ARN)
        held = {e["edge"]["to_entity_id"] for e in _edges(tree, HOLDS_SERVICE_CONTROL_POLICY)}
        assert held == {_id(deny), _id(guard)}, "the second ListPolicies page (Guardrails) was read; FullAWSAccess is no child"
        assert _id(full) not in held
        [surface] = _surfaces(tree, HOLDS_SERVICE_CONTROL_POLICY, _id(org))
        assert surface.complete is True and surface.count == 2
        attached = {(e["edge"]["from_entity_id"], e["edge"]["to_entity_id"]) for e in _edges(tree, ATTACHED_TO_TARGET)}
        assert (_id(full), _id(org)) in attached

    @pytest.mark.spec("req-aws-core-organizations-completeness-6", "req-aws-collector-pagination-2")
    def test_failed_scp_second_page_is_incomplete_but_keeps_page_one(self) -> None:
        """Page one's policies are real observations and are written; the surface is incomplete,
        so nothing is inferred from what page two would have named (PR #72 review)."""
        client = _govcloud_org()
        deny = _summary(SCP_DENY_ARN, "DenyS3", "SERVICE_CONTROL_POLICY")
        client.set("list_policies", "SERVICE_CONTROL_POLICY", [deny], _err("ServiceException"))
        tree = collect_organization(client, DIMENSIONS)
        [surface] = _surfaces(tree, HOLDS_SERVICE_CONTROL_POLICY)
        assert surface.complete is False
        assert [n["node"]["policy_arn"] for n in _nodes(tree, SERVICE_CONTROL_POLICY)] == [SCP_DENY_ARN]

    @pytest.mark.spec("req-aws-core-organizations-completeness-14", "req-aws-collector-pagination-2")
    def test_failed_per_type_second_page_keeps_page_one(self) -> None:
        client = _govcloud_org()
        client.set("list_policies", "TAG_POLICY", [_summary(TAG_POLICY_ARN, "tt-environment-tag", "TAG_POLICY")], _err("ServiceException"))
        tree = collect_organization(client, DIMENSIONS)
        [surface] = _surfaces(tree, HOLDS_ORGANIZATIONS_POLICY)
        assert surface.complete is False
        _one(tree, ORGANIZATIONS_POLICY, policy_arn=TAG_POLICY_ARN)

    @pytest.mark.spec("req-aws-core-organizations-completeness-5", "req-aws-core-organizations-completeness-14")
    def test_tag_policy_is_an_organizations_policy_with_its_attachment_and_tags(self) -> None:
        tree = collect_organization(_govcloud_org(), DIMENSIONS)
        org = _one(tree, ORGANIZATION, organization_id=ORG_ID)
        tag_policy = _one(tree, ORGANIZATIONS_POLICY, policy_arn=TAG_POLICY_ARN)
        assert tag_policy["node"]["policy_type"] == "TAG_POLICY"
        assert tag_policy["node"]["tags"] == {"owner": "platform"}
        assert (_id(org), _id(tag_policy)) in {(e["edge"]["from_entity_id"], e["edge"]["to_entity_id"]) for e in _edges(tree, HOLDS_ORGANIZATIONS_POLICY)}
        assert (_id(tag_policy), _id(org)) in {(e["edge"]["from_entity_id"], e["edge"]["to_entity_id"]) for e in _edges(tree, ATTACHED_TO_TARGET)}
        [surface] = _surfaces(tree, HOLDS_ORGANIZATIONS_POLICY)
        assert surface.complete is True and surface.count == 1

    @pytest.mark.spec("req-aws-core-organizations-completeness-5", "req-aws-core-organizations-completeness-12")
    def test_govcloud_lists_only_enabled_types_and_never_backup(self) -> None:
        enabled = [(t, "ENABLED") for t in ("SERVICE_CONTROL_POLICY", "RESOURCE_CONTROL_POLICY", "TAG_POLICY", "DECLARATIVE_POLICY_EC2", "S3_POLICY")]
        client = _govcloud_org(enabled=enabled)
        client.set("list_policies", "RESOURCE_CONTROL_POLICY", [_summary(RCP_ARN, "EnforceTls", "RESOURCE_CONTROL_POLICY")])
        client.set("list_policies", "DECLARATIVE_POLICY_EC2", [_summary(DECL_ARN, "ImageBlock", "DECLARATIVE_POLICY_EC2")])
        client.documents[policy_id_of_arn(RCP_ARN)] = (_summary(RCP_ARN, "EnforceTls", "RESOURCE_CONTROL_POLICY"), RCP_DOC)
        tree = collect_organization(client, DIMENSIONS)
        filters = sorted(kw["Filter"] for kw in client.called("list_policies") if "NextToken" not in kw)
        assert filters == sorted(t for t, _ in enabled)
        assert client.called("list_policies", Filter="BACKUP_POLICY") == []
        declarative = _one(tree, ORGANIZATIONS_POLICY, policy_arn=DECL_ARN)
        assert client.called("describe_policy", PolicyId=policy_id_of_arn(DECL_ARN)) == [], "declarative bodies are not read"
        for edge in (DECLARES_STATEMENT, DECLARES_TAG_RULE):
            [surface] = _surfaces(tree, edge, _id(declarative))
            assert surface.complete is True and surface.count == 0
        rcp_statement = _one(tree, POLICY_STATEMENT, policy_arn=RCP_ARN)
        assert rcp_statement["node"]["principals"] == [{"type": "*", "value": "*"}]
        assert rcp_statement["node"]["conditions"] == [{"operator": "bool", "condition_key": "aws:securetransport", "values": ["false"]}]

    @pytest.mark.spec("req-aws-core-organizations-completeness-14")
    def test_one_failed_per_type_listing_makes_the_one_policy_surface_incomplete(self) -> None:
        client = _govcloud_org(enabled=[("TAG_POLICY", "ENABLED"), ("RESOURCE_CONTROL_POLICY", "ENABLED")])
        client.set("list_policies", "RESOURCE_CONTROL_POLICY", _err("AccessDeniedException"))
        tree = collect_organization(client, DIMENSIONS)
        surfaces = _surfaces(tree, HOLDS_ORGANIZATIONS_POLICY)
        assert len(surfaces) == 1
        assert surfaces[0].complete is False

    @pytest.mark.spec("req-aws-core-organizations-completeness-14")
    def test_a_type_newer_than_the_pinned_enum_is_not_listed_and_refuses_completeness(self) -> None:
        client = _govcloud_org(enabled=[("SERVICE_CONTROL_POLICY", "ENABLED"), ("FUTURE_POLICY", "ENABLED")])
        tree = collect_organization(client, DIMENSIONS)
        org = _one(tree, ORGANIZATION, organization_id=ORG_ID)
        assert org["node"]["enabled_policy_types"] == ["SERVICE_CONTROL_POLICY"]
        assert client.called("list_policies", Filter="FUTURE_POLICY") == []
        [surface] = _surfaces(tree, HOLDS_ORGANIZATIONS_POLICY)
        assert surface.complete is False


class TestStatements:
    @pytest.mark.spec("req-aws-core-organizations-completeness-7", "req-aws-core-organizations-completeness-8")
    def test_sid_and_sidless_statements_are_two_keyed_nodes(self) -> None:
        tree = collect_organization(_govcloud_org(), DIMENSIONS)
        deny = _one(tree, SERVICE_CONTROL_POLICY, policy_arn=SCP_DENY_ARN)
        statements = [n for n in _nodes(tree, POLICY_STATEMENT) if n["node"]["policy_arn"] == SCP_DENY_ARN]
        keys = {n["node"]["statement_key"] for n in statements}
        allow = normalize_statement({"Effect": "Allow", "Action": "*", "Resource": "*"})[1]
        assert keys == {"sid:A", f"content:{content_sha256(allow)}"}
        a = _one(tree, POLICY_STATEMENT, policy_arn=SCP_DENY_ARN, statement_key="sid:A")
        assert a["node"]["effect"] == "Deny" and a["node"]["actions"] == ["s3:*"]
        assert a["node"]["positions"] == [0] and a["node"]["occurrences"] == 1
        assert a["node"]["tags"] == {}
        declared = {e["edge"]["to_entity_id"] for e in _edges(tree, DECLARES_STATEMENT) if e["edge"]["from_entity_id"] == _id(deny)}
        assert declared == {_id(n) for n in statements}
        [surface] = _surfaces(tree, DECLARES_STATEMENT, _id(deny))
        assert surface.complete is True and surface.count == 2

    @pytest.mark.spec("req-aws-core-organizations-completeness-7")
    def test_aws_managed_policy_statements_are_contained_by_it(self) -> None:
        tree = collect_organization(_govcloud_org(), DIMENSIONS)
        full = _one(tree, SERVICE_CONTROL_POLICY, policy_arn=FULL_AWS_ACCESS_ARN)
        [statement] = [n for n in _nodes(tree, POLICY_STATEMENT) if n["node"]["policy_arn"] == FULL_AWS_ACCESS_ARN]
        assert (_id(full), _id(statement)) in {(e["edge"]["from_entity_id"], e["edge"]["to_entity_id"]) for e in _edges(tree, DECLARES_STATEMENT)}

    @pytest.mark.spec("req-aws-core-organizations-completeness-7")
    def test_condition_and_not_action_are_typed(self) -> None:
        tree = collect_organization(_govcloud_org(), DIMENSIONS)
        guard = _one(tree, POLICY_STATEMENT, policy_arn=SCP_GUARD_ARN, statement_key="sid:DenyOutsideGov")
        assert guard["node"]["not_actions"] == ["iam:*", "sts:*"]
        assert guard["node"]["actions"] == []
        assert guard["node"]["conditions"] == [
            {"operator": "stringnotequals", "condition_key": "aws:requestedregion", "values": ["us-gov-east-1", "us-gov-west-1"]}
        ]

    @pytest.mark.spec("req-aws-core-organizations-completeness-8")
    def test_content_sha256_recomputes_from_stored_fields(self) -> None:
        tree = collect_organization(_govcloud_org(), DIMENSIONS)
        for node in _nodes(tree, POLICY_STATEMENT):
            assert content_sha256(node["node"]) == node["node"]["content_sha256"]

    @pytest.mark.spec("req-aws-core-organizations-completeness-10")
    @pytest.mark.parametrize("failure", [_err("AccessDeniedException"), "not json", json.dumps({"Statement": [{"Effect": "Maybe", "Action": "*"}]})])
    def test_unreadable_document_is_an_incomplete_surface_and_no_statements(self, failure: Any) -> None:
        client = _govcloud_org()
        summary = _summary(SCP_DENY_ARN, "DenyS3", "SERVICE_CONTROL_POLICY")
        client.documents[summary["Id"]] = failure if isinstance(failure, Exception) else (summary, failure)
        tree = collect_organization(client, DIMENSIONS)
        deny = _one(tree, SERVICE_CONTROL_POLICY, policy_arn=SCP_DENY_ARN)
        assert [n for n in _nodes(tree, POLICY_STATEMENT) if n["node"]["policy_arn"] == SCP_DENY_ARN] == []
        [surface] = _surfaces(tree, DECLARES_STATEMENT, _id(deny))
        assert surface.complete is False


def _keys(doc: dict[str, Any]) -> dict[str, Any]:
    return parse_statements(json.dumps(doc)).units


class TestStatementIdentityAndUpdates:
    """Each row of the spec's update table, at the identity level (req-aws-core-organizations-completeness-9)."""

    A = {"Sid": "A", "Effect": "Deny", "Action": "s3:*", "Resource": "*"}
    ANON = {"Effect": "Allow", "Action": "*", "Resource": "*"}

    @pytest.mark.spec("req-aws-core-organizations-completeness-9")
    def test_reordering_changes_only_positions(self) -> None:
        before = _keys({"Statement": [self.A, self.ANON]})
        after = _keys({"Statement": [self.ANON, self.A]})
        assert set(before) == set(after)
        assert before["sid:A"].positions == [0] and after["sid:A"].positions == [1]
        assert before["sid:A"].fields == after["sid:A"].fields

    @pytest.mark.spec("req-aws-core-organizations-completeness-9")
    def test_editing_a_sid_statement_keeps_its_key(self) -> None:
        before = _keys({"Statement": [self.A]})
        after = _keys({"Statement": [{**self.A, "Action": ["s3:*", "kms:*"]}]})
        assert set(before) == set(after) == {"sid:A"}
        assert before["sid:A"].content_sha256 != after["sid:A"].content_sha256

    @pytest.mark.spec("req-aws-core-organizations-completeness-9")
    def test_editing_a_sidless_statement_changes_its_key(self) -> None:
        before = _keys({"Statement": [self.ANON]})
        after = _keys({"Statement": [{**self.ANON, "Resource": "arn:aws-us-gov:s3:::b"}]})
        assert set(before).isdisjoint(after)

    @pytest.mark.spec("req-aws-core-organizations-completeness-9")
    @pytest.mark.parametrize("edited", [{"Effect": "Deny", "Action": "s3:*", "Resource": "*"}, {**A, "Sid": "B"}])
    def test_removing_or_renaming_a_sid_changes_the_key(self, edited: dict[str, Any]) -> None:
        assert set(_keys({"Statement": [self.A]})).isdisjoint(_keys({"Statement": [edited]}))

    @pytest.mark.spec("req-aws-core-organizations-completeness-8")
    def test_duplicate_sid_and_sidless_with_the_same_content_differ(self) -> None:
        body = {"Effect": "Deny", "Action": "s3:*", "Resource": "*"}
        units = _keys({"Statement": [{**body, "Sid": "X"}, {**body, "Sid": "X", "Resource": "arn:x"}, body]})
        kinds = sorted(k.split(":", 1)[0] for k in units)
        assert kinds == ["content", "dupsid", "dupsid"]

    @pytest.mark.spec("req-aws-core-organizations-completeness-8")
    def test_two_different_duplicated_sids_get_different_nodes(self) -> None:
        body = {"Effect": "Deny", "Action": "s3:*", "Resource": "*"}
        units = _keys({"Statement": [{**body, "Sid": "X"}, {**body, "Sid": "X"}, {**body, "Sid": "Y"}, {**body, "Sid": "Y"}]})
        assert len(units) == 2
        assert all(u.occurrences == 2 for u in units.values())

    @pytest.mark.spec("req-aws-core-organizations-completeness-8")
    def test_duplicate_sid_warns(self) -> None:
        client = _govcloud_org()
        summary = _summary(SCP_DENY_ARN, "DenyS3", "SERVICE_CONTROL_POLICY")
        client.documents[summary["Id"]] = (summary, json.dumps({"Statement": [self.A, {**self.A, "Action": "kms:*"}]}))
        tree = collect_organization(client, DIMENSIONS)
        assert any(n.code == "DUPLICATE_SID" for n in tree.notices)
        keys = {n["node"]["statement_key"].split(":")[0] for n in _nodes(tree, POLICY_STATEMENT) if n["node"]["policy_arn"] == SCP_DENY_ARN}
        assert keys == {"dupsid"}

    @pytest.mark.spec("req-aws-core-organizations-completeness-8")
    def test_identical_sidless_statements_are_one_node_with_occurrences(self) -> None:
        units = _keys({"Statement": [self.ANON, self.A, self.ANON]})
        [anon] = [u for k, u in units.items() if k.startswith("content:")]
        assert anon.occurrences == 2 and anon.positions == [0, 2]

    @pytest.mark.spec("req-aws-core-organizations-completeness-8")
    @pytest.mark.parametrize(
        ("one", "other"),
        [
            ({"Action": "s3:GetObject"}, {"Action": ["s3:getobject"]}),
            ({"Resource": "arn:x"}, {"Resource": ["arn:x", "arn:x"]}),
            ({"Condition": {"StringEquals": {"aws:PrincipalOrgID": "o-1"}}}, {"Condition": {"stringequals": {"aws:principalorgid": ["o-1"]}}}),
            ({"Principal": {"AWS": "arn:p"}}, {"Principal": {"AWS": ["arn:p"]}}),
        ],
    )
    def test_equivalent_spellings_hash_the_same(self, one: dict[str, Any], other: dict[str, Any]) -> None:
        base = {"Effect": "Deny", "Action": "s3:*", "Resource": "*"}
        assert content_sha256(normalize_statement({**base, **one})[1]) == content_sha256(normalize_statement({**base, **other})[1])


class TestTagPolicyRules:
    @pytest.mark.spec("req-aws-core-organizations-completeness-11")
    def test_one_rule_per_tag_key(self) -> None:
        tree = collect_organization(_govcloud_org(), DIMENSIONS)
        policy = _one(tree, ORGANIZATIONS_POLICY, policy_arn=TAG_POLICY_ARN)
        env = _one(tree, TAG_POLICY_RULE, policy_arn=TAG_POLICY_ARN, tag_key_lower="environment")
        assert env["node"]["tag_key"] == "Environment"
        assert env["node"]["allowed_values"] == ["dev", "prod"]
        assert env["node"]["enforced_for"] == ["ec2:instance"]
        assert env["node"]["inheritance_operators"] == ["@@assign"]
        cost = _one(tree, TAG_POLICY_RULE, policy_arn=TAG_POLICY_ARN, tag_key_lower="costcenter")
        assert cost["node"]["allowed_values"] is None and cost["node"]["enforced_for"] is None
        [rules] = _surfaces(tree, DECLARES_TAG_RULE, _id(policy))
        assert rules.complete is True and rules.count == 2
        [statements] = _surfaces(tree, DECLARES_STATEMENT, _id(policy))
        assert statements.complete is True and statements.count == 0, "a tag policy carries no statements"

    @pytest.mark.spec("req-aws-core-organizations-completeness-11")
    def test_tag_policy_with_no_keys_is_complete_empty(self) -> None:
        assert parse_tag_rules(json.dumps({})) == {}
        client = _govcloud_org()
        summary = _summary(TAG_POLICY_ARN, "tt-environment-tag", "TAG_POLICY")
        client.documents[summary["Id"]] = (summary, json.dumps({"tags": {}}))
        tree = collect_organization(client, DIMENSIONS)
        policy = _one(tree, ORGANIZATIONS_POLICY, policy_arn=TAG_POLICY_ARN)
        [surface] = _surfaces(tree, DECLARES_TAG_RULE, _id(policy))
        assert surface.complete is True and surface.count == 0

    @pytest.mark.spec("req-aws-core-organizations-completeness-11")
    def test_unreadable_tag_policy_is_incomplete(self) -> None:
        client = _govcloud_org()
        client.documents[policy_id_of_arn(TAG_POLICY_ARN)] = _err("ServiceException")
        tree = collect_organization(client, DIMENSIONS)
        policy = _one(tree, ORGANIZATIONS_POLICY, policy_arn=TAG_POLICY_ARN)
        [surface] = _surfaces(tree, DECLARES_TAG_RULE, _id(policy))
        assert surface.complete is False
        assert _nodes(tree, TAG_POLICY_RULE) == []


class TestTripleAndDeclarations:
    @pytest.mark.spec("req-aws-core-contained-type-triple-1")
    def test_reader_surfaces_mirror_model_containment(self) -> None:
        from tap_grid.registry import get_model_class

        for entity_type, edges in CONTAINMENT_SURFACES.items():
            assert tuple(get_model_class(entity_type).CONTAINMENT_EDGES) == edges, entity_type

    @pytest.mark.spec("req-aws-core-contained-type-triple-1")
    def test_every_observed_parent_has_a_surface_for_every_containment_edge(self) -> None:
        enabled = [(t, "ENABLED") for t in ("SERVICE_CONTROL_POLICY", "RESOURCE_CONTROL_POLICY", "TAG_POLICY", "DECLARATIVE_POLICY_EC2")]
        client = _govcloud_org(enabled=enabled)
        client.set("list_policies", "RESOURCE_CONTROL_POLICY", [_summary(RCP_ARN, "EnforceTls", "RESOURCE_CONTROL_POLICY")])
        client.set("list_policies", "DECLARATIVE_POLICY_EC2", [_summary(DECL_ARN, "ImageBlock", "DECLARATIVE_POLICY_EC2")])
        client.documents[policy_id_of_arn(RCP_ARN)] = (_summary(RCP_ARN, "EnforceTls", "RESOURCE_CONTROL_POLICY"), RCP_DOC)
        tree = collect_organization(client, DIMENSIONS)
        recorded = {(s.subject, s.edge_type) for s in tree.listings}
        checked = 0
        for node in tree.nodes:
            for edge in CONTAINMENT_SURFACES.get(node["entity"]["entity_type"], ()):
                assert (_id(node), edge) in recorded, (node["entity"]["entity_type"], node["entity"]["name"], edge)
                checked += 1
        assert checked >= 15

    @pytest.mark.spec("req-aws-collector-tags-13", "req-aws-collector-tags-14")
    def test_every_type_the_reader_emits_declares_one_lane(self) -> None:
        import jsonschema
        from django.apps import apps

        here = Path(__file__).resolve().parents[1] / "collectors" / "boto3_collector"
        schema = json.loads((here / "aws_resource_manifest.schema.json").read_text())
        block = {**schema["$defs"]["tags_block"], "$defs": schema["$defs"]}
        rows = json.loads((here / "tag_lanes.json").read_text())["lanes"]
        models = {m.ENTITY_TYPE for m in apps.get_app_config("aws_core").get_models() if hasattr(m, "ENTITY_TYPE")}
        for row in rows:
            assert row["entity_type"] in models, row
            if row["tags"] != {"source": "organizations"}:
                jsonschema.validate(row["tags"], block)
        lanes: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if row["reader"] == "organizations":
                lanes.setdefault(row["entity_type"], []).append(row)
        enabled = [(t, "ENABLED") for t in ("SERVICE_CONTROL_POLICY", "TAG_POLICY")]
        tree = collect_organization(_govcloud_org(enabled=enabled), DIMENSIONS)
        emitted = {n["entity"]["entity_type"] for n in tree.nodes}
        assert emitted >= {ORGANIZATION, ORGANIZATIONAL_UNIT, ACCOUNT, SERVICE_CONTROL_POLICY, ORGANIZATIONS_POLICY, DELEGATED_ADMINISTRATION, POLICY_STATEMENT, TAG_POLICY_RULE}
        for entity_type in emitted:
            assert len(lanes.get(entity_type, [])) == 1, entity_type
        for node in tree.nodes:
            if lanes[node["entity"]["entity_type"]][0]["tags"]["source"] == "none":
                assert node["node"]["tags"] == {}

    @pytest.mark.spec("req-aws-collector-pagination-3")
    def test_every_call_is_walked_against_botocore(self) -> None:
        import boto3

        # Dummy credentials: a metadata-only client must never walk the ambient provider chain (IMDS).
        client = boto3.session.Session(aws_access_key_id="x", aws_secret_access_key="x").client(
            "organizations", region_name=REGION
        )
        operations = set(client.meta.service_model.operation_names)
        for op in PAGINATED_OPERATIONS:
            assert client.can_paginate(op), op
        fake = _govcloud_org()
        collect_organization(fake, DIMENSIONS)
        used = {op for op, _ in fake.calls}
        assert used - set(PAGINATED_OPERATIONS) == {"describe_organization", "describe_policy"}
        for op in used:
            pascal = "".join(part.capitalize() for part in op.split("_")).replace("Aws", "AWS")
            assert pascal in operations, op
        assert not client.can_paginate("describe_policy")

    @pytest.mark.django_db
    def test_organization_tags_default_to_not_read(self) -> None:
        result = create_node(ORGANIZATION, {"name": "designed"})
        assert result.success, result.errors
        assert get_node(result.entity_id).tags is None

    def test_policy_arn_helpers(self) -> None:
        assert organization_id_of_policy_arn(SCP_DENY_ARN) == ORG_ID
        assert organization_id_of_policy_arn(FULL_AWS_ACCESS_ARN) == ""
        assert policy_id_of_arn(FULL_AWS_ACCESS_ARN) == "p-FullAWSAccess"
        assert is_aws_managed_policy_arn(FULL_AWS_ACCESS_ARN)
        assert not is_aws_managed_policy_arn(SCP_DENY_ARN)
        assert not is_aws_managed_policy_arn("invalid/p-example123")


# ---------------------------------------------------------------------------
# The falsifiers — real grid rows, fake client
# ---------------------------------------------------------------------------


class FakeProbeClient:
    def __init__(self, *, organization_id: str = ORG_ID) -> None:
        self.organization_id = organization_id
        self.services: dict[str, list[Any]] = {}
        self.documents: dict[str, dict[str, Any] | Exception] = {}
        self.calls: list[str] = []

    def describe_organization(self) -> dict[str, Any]:
        return {"Organization": {"Id": self.organization_id}}

    def list_roots(self) -> dict[str, Any]:
        return {"Roots": [{"Id": ROOT_ID}]}

    def list_delegated_services_for_account(self, AccountId: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(f"services:{AccountId}")
        pages = self.services[AccountId]
        index = int(kw.get("NextToken") or 0)
        page = pages[index]
        if isinstance(page, Exception):
            raise page  # pylint: disable=raising-bad-type
        response: dict[str, Any] = {"DelegatedServices": page}
        if index + 1 < len(pages):
            response["NextToken"] = str(index + 1)
        return response

    def describe_policy(self, PolicyId: str) -> dict[str, Any]:
        self.calls.append(f"describe_policy:{PolicyId}")
        entry = self.documents[PolicyId]
        if isinstance(entry, Exception):
            raise entry  # pylint: disable=raising-bad-type
        return {"Policy": entry}


class FakeSession:
    def __init__(self, client: FakeProbeClient) -> None:
        self._client = client

    def client(self, service: str, region_name: str | None = None) -> Any:
        assert service == "organizations"
        return self._client


def _row(entity_type: str, payload: dict[str, Any]) -> uuid.UUID:
    result = create_node(entity_type, payload)
    assert result.success, result.errors
    entity_id = uuid.UUID(str(result.entity_id))
    row = get_node(entity_id)
    row.entity.dimensions = {"cloud": "aws", "aws_account": MGMT, "aws_region": "global"}
    row.entity.save(update_fields=["dimensions"])
    return entity_id


def _cand(entity_id: uuid.UUID, entity_type: str) -> Candidate:
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


def _ctx() -> FalsifyContext:
    return FalsifyContext(batch_id=str(uuid.uuid4()), statement=None)


def _supported(verdicts: dict[str, Any]) -> None:
    for case, verdict in verdicts.items():
        assert unsupported(verdict) is None, (case, unsupported(verdict))


def _delegation(account: str, principal: str, enabled_at: str = "2026-09-03T00:00:00Z", org: str = ORG_ID) -> uuid.UUID:
    return _row(
        DELEGATED_ADMINISTRATION,
        {"name": f"{principal}->{account}", "organization_id": org, "account_id": account, "service_principal": principal, "delegation_enabled_at": enabled_at},
    )


@pytest.mark.django_db
class TestDelegatedAdministrationFalsifier:
    @pytest.mark.spec("req-aws-core-organizations-completeness-4", "req-grid-reconcile-falsifier-6")
    def test_four_cases(self) -> None:
        client = FakeProbeClient()
        when = datetime(2026, 9, 3, tzinfo=UTC)
        cases = {
            CASE_PRESENT: _cand(_delegation("444444444441", "guardduty.amazonaws.com"), DELEGATED_ADMINISTRATION),
            CASE_DROPPED: _cand(_delegation("444444444442", "guardduty.amazonaws.com"), DELEGATED_ADMINISTRATION),
            CASE_FORBIDDEN: _cand(_delegation("444444444443", "guardduty.amazonaws.com"), DELEGATED_ADMINISTRATION),
            CASE_REIDENTIFIED: _cand(_delegation("444444444444", "guardduty.amazonaws.com"), DELEGATED_ADMINISTRATION),
        }
        # present on the SECOND page: the probe reads to the end (req-aws-collector-pagination-1)
        client.services["444444444441"] = [[{"ServicePrincipal": "config.amazonaws.com"}], [{"ServicePrincipal": "guardduty.amazonaws.com", "DelegationEnabledDate": when}]]
        client.services["444444444442"] = [[{"ServicePrincipal": "config.amazonaws.com"}]]
        client.services["444444444443"] = [_err("AccessDeniedException")]
        client.services["444444444444"] = [[{"ServicePrincipal": "guardduty.amazonaws.com", "DelegationEnabledDate": datetime(2026, 9, 30, tzinfo=UTC)}]]
        falsifier = DelegatedAdministrationFalsifier(session=FakeSession(client), account_id=MGMT, region=REGION)
        _supported(run_four_cases(falsifier, cases, _ctx()))

    @pytest.mark.spec("req-aws-core-organizations-completeness-4")
    def test_account_not_registered_is_dropped(self) -> None:
        client = FakeProbeClient()
        client.services[SECURITY] = [_err("AccountNotRegisteredException")]
        f = DelegatedAdministrationFalsifier(session=FakeSession(client), account_id=MGMT, region=REGION)
        [v] = f.batch_falsify([_cand(_delegation(SECURITY, "securityhub.amazonaws.com"), DELEGATED_ADMINISTRATION)], _ctx())
        assert v.verdict == DROPPED_FROM_OBSERVATION

    @pytest.mark.spec("req-aws-core-organizations-completeness-4", "req-aws-collector-pagination-2")
    @pytest.mark.parametrize("pages", [[[{"ServicePrincipal": "x.amazonaws.com"}], _err("ServiceException")], [_err("AccountNotFoundException")]])
    def test_other_failures_are_undetermined(self, pages: list[Any]) -> None:
        client = FakeProbeClient()
        client.services[SECURITY] = pages
        f = DelegatedAdministrationFalsifier(session=FakeSession(client), account_id=MGMT, region=REGION)
        [v] = f.batch_falsify([_cand(_delegation(SECURITY, "guardduty.amazonaws.com"), DELEGATED_ADMINISTRATION)], _ctx())
        assert v.verdict == UNDETERMINED

    def test_other_organization_is_scope_unknown_without_a_probe(self) -> None:
        client = FakeProbeClient()
        f = DelegatedAdministrationFalsifier(session=FakeSession(client), account_id=MGMT, region=REGION)
        [v] = f.batch_falsify([_cand(_delegation(SECURITY, "guardduty.amazonaws.com", org="o-otherorg001"), DELEGATED_ADMINISTRATION)], _ctx())
        assert v.verdict == UNDETERMINED and v.reason == "scope_unknown"
        assert client.calls == []


def _policy_row(entity_type: str, arn: str, *, aws_managed: bool = False, name: str = "p") -> uuid.UUID:
    payload: dict[str, Any] = {"name": name, "policy_arn": arn, "policy_id": policy_id_of_arn(arn), "aws_managed": aws_managed}
    if entity_type == ORGANIZATIONS_POLICY:
        payload["policy_type"] = "TAG_POLICY"
    return _row(entity_type, payload)


@pytest.mark.django_db
class TestOrganizationsPolicyFalsifier:
    @pytest.mark.spec("req-aws-core-organizations-completeness-6", "req-grid-reconcile-falsifier-6")
    @pytest.mark.parametrize(("entity_type", "kind"), [(SERVICE_CONTROL_POLICY, "service_control_policy"), (ORGANIZATIONS_POLICY, "tag_policy")])
    def test_four_cases(self, entity_type: str, kind: str) -> None:
        client = FakeProbeClient()
        arns = {case: _policy_arn(kind, f"p-{case[:6]}aaaa") for case in (CASE_PRESENT, CASE_DROPPED, CASE_FORBIDDEN, CASE_REIDENTIFIED)}
        cases = {case: _cand(_policy_row(entity_type, arn, name="p"), entity_type) for case, arn in arns.items()}
        client.documents[policy_id_of_arn(arns[CASE_PRESENT])] = {"PolicySummary": {"Arn": arns[CASE_PRESENT], "Name": "p"}}
        client.documents[policy_id_of_arn(arns[CASE_DROPPED])] = _err("PolicyNotFoundException")
        client.documents[policy_id_of_arn(arns[CASE_FORBIDDEN])] = _err("AccessDeniedException")
        client.documents[policy_id_of_arn(arns[CASE_REIDENTIFIED])] = {"PolicySummary": {"Arn": _policy_arn(kind, "p-recreated01"), "Name": "p"}}
        falsifier = OrganizationsPolicyFalsifier(session=FakeSession(client), account_id=MGMT, region=REGION)
        _supported(run_four_cases(falsifier, cases, _ctx()))

    def test_aws_managed_is_never_probed(self) -> None:
        client = FakeProbeClient()
        f = OrganizationsPolicyFalsifier(session=FakeSession(client), account_id=MGMT, region=REGION)
        [v] = f.batch_falsify([_cand(_policy_row(SERVICE_CONTROL_POLICY, FULL_AWS_ACCESS_ARN, aws_managed=True), SERVICE_CONTROL_POLICY)], _ctx())
        assert v.verdict == UNDETERMINED and v.reason == "scope_unknown"
        assert client.calls == []


def _statement_row(arn: str, key: str) -> uuid.UUID:
    return _row(POLICY_STATEMENT, {"name": key, "policy_arn": arn, "statement_key": key})


@pytest.mark.django_db
class TestPolicyStatementFalsifier:
    @pytest.mark.spec("req-aws-core-organizations-completeness-10", "req-grid-reconcile-falsifier-6")
    def test_four_cases(self) -> None:
        client = FakeProbeClient()
        a = {"Sid": "A", "Effect": "Deny", "Action": "s3:*", "Resource": "*"}
        present_arn, dropped_arn, forbidden_arn, reborn_arn = (_policy_arn("service_control_policy", f"p-stmt{i}aaaaa") for i in range(4))
        client.documents[policy_id_of_arn(present_arn)] = {"PolicySummary": {"Arn": present_arn}, "Content": json.dumps({"Statement": [a]})}
        client.documents[policy_id_of_arn(dropped_arn)] = {"PolicySummary": {"Arn": dropped_arn}, "Content": json.dumps({"Statement": [{**a, "Sid": "B"}]})}
        client.documents[policy_id_of_arn(forbidden_arn)] = _err("AccessDeniedException")
        # Sid A is now repeated: the same named statement under a dupsid: key (the "becomes duplicated" row).
        client.documents[policy_id_of_arn(reborn_arn)] = {"PolicySummary": {"Arn": reborn_arn}, "Content": json.dumps({"Statement": [a, {**a, "Action": "kms:*"}]})}
        cases = {
            CASE_PRESENT: _cand(_statement_row(present_arn, "sid:A"), POLICY_STATEMENT),
            CASE_DROPPED: _cand(_statement_row(dropped_arn, "sid:A"), POLICY_STATEMENT),
            CASE_FORBIDDEN: _cand(_statement_row(forbidden_arn, "sid:A"), POLICY_STATEMENT),
            CASE_REIDENTIFIED: _cand(_statement_row(reborn_arn, "sid:A"), POLICY_STATEMENT),
        }
        falsifier = PolicyStatementFalsifier(session=FakeSession(client), account_id=MGMT, region=REGION)
        _supported(run_four_cases(falsifier, cases, _ctx()))

    @pytest.mark.spec("req-aws-core-organizations-completeness-10")
    def test_policy_gone_drops_and_unparseable_is_undetermined_one_call_per_policy(self) -> None:
        client = FakeProbeClient()
        gone = _policy_arn("service_control_policy", "p-goneaaaaaa")
        broken = _policy_arn("service_control_policy", "p-brokenaaaa")
        client.documents[policy_id_of_arn(gone)] = _err("PolicyNotFoundException")
        client.documents[policy_id_of_arn(broken)] = {"PolicySummary": {"Arn": broken}, "Content": "{"}
        f = PolicyStatementFalsifier(session=FakeSession(client), account_id=MGMT, region=REGION)
        verdicts = f.batch_falsify(
            [
                _cand(_statement_row(gone, "sid:A"), POLICY_STATEMENT),
                _cand(_statement_row(gone, "sid:B"), POLICY_STATEMENT),
                _cand(_statement_row(broken, "sid:A"), POLICY_STATEMENT),
            ],
            _ctx(),
        )
        assert [v.verdict for v in verdicts] == [DROPPED_FROM_OBSERVATION, DROPPED_FROM_OBSERVATION, UNDETERMINED]
        assert client.calls.count(f"describe_policy:{policy_id_of_arn(gone)}") == 1

    @pytest.mark.parametrize("arn", ["invalid/p-example123", "arn:aws-us-gov:organizations::111111111111:policy/p-example123"])
    def test_malformed_policy_arn_is_refused_without_a_probe(self, arn: str) -> None:
        """Only the exact AWS-managed ARN form skips the organization check (PR #72 review)."""
        client = FakeProbeClient()
        f = PolicyStatementFalsifier(session=FakeSession(client), account_id=MGMT, region=REGION)
        [v] = f.batch_falsify([_cand(_statement_row(arn, "sid:A"), POLICY_STATEMENT)], _ctx())
        assert v.verdict == UNDETERMINED and v.reason == "scope_unknown"
        assert client.calls == []

    def test_aws_managed_policy_statement_is_probed_under_reach_alone(self) -> None:
        client = FakeProbeClient()
        client.documents["p-FullAWSAccess"] = {"PolicySummary": {"Arn": FULL_AWS_ACCESS_ARN}, "Content": FULL_AWS_ACCESS_DOC}
        key = next(iter(parse_statements(FULL_AWS_ACCESS_DOC).units))
        f = PolicyStatementFalsifier(session=FakeSession(client), account_id=MGMT, region=REGION)
        [v] = f.batch_falsify([_cand(_statement_row(FULL_AWS_ACCESS_ARN, key), POLICY_STATEMENT)], _ctx())
        assert v.verdict == PRESENT_AT_PROBE


@pytest.mark.django_db
class TestTagPolicyRuleFalsifier:
    """REIDENTIFIED is structurally impossible for a rule keyed by its tag key alone, so the three
    reachable cases are proven individually (as the S3 and IAM-policy falsifiers do)."""

    @pytest.mark.spec("req-aws-core-organizations-completeness-11")
    @pytest.mark.parametrize(
        ("document", "expected"),
        [
            ({"PolicySummary": {"Arn": TAG_POLICY_ARN}, "Content": TAG_DOC}, PRESENT_AT_PROBE),
            ({"PolicySummary": {"Arn": TAG_POLICY_ARN}, "Content": json.dumps({"tags": {}})}, DROPPED_FROM_OBSERVATION),
            (_err("PolicyNotFoundException"), DROPPED_FROM_OBSERVATION),
            (_err("AccessDeniedException"), UNDETERMINED),
        ],
    )
    def test_cases(self, document: Any, expected: str) -> None:
        client = FakeProbeClient()
        client.documents[policy_id_of_arn(TAG_POLICY_ARN)] = document
        row = _row(TAG_POLICY_RULE, {"name": "env", "policy_arn": TAG_POLICY_ARN, "tag_key_lower": "environment"})
        f = TagPolicyRuleFalsifier(session=FakeSession(client), account_id=MGMT, region=REGION)
        [v] = f.batch_falsify([_cand(row, TAG_POLICY_RULE)], _ctx())
        assert v.verdict == expected
        assert unsupported(v) is None


@pytest.mark.django_db
class TestPolicyCascade:
    @pytest.mark.spec("req-aws-core-organizations-completeness-9")
    def test_deleting_a_policy_cascades_to_its_statements_and_rules(self) -> None:
        from tap_grid.models import Entity

        policy = _policy_row(ORGANIZATIONS_POLICY, TAG_POLICY_ARN)
        statement = _statement_row(TAG_POLICY_ARN, "sid:A")
        rule = _row(TAG_POLICY_RULE, {"name": "env", "policy_arn": TAG_POLICY_ARN, "tag_key_lower": "environment"})
        create_edge(get_node(policy).entity, get_node(statement).entity, DECLARES_STATEMENT)
        create_edge(get_node(policy).entity, get_node(rule).entity, DECLARES_TAG_RULE)
        assert delete_node(policy, cascade="contained").success
        for entity_id in (policy, statement, rule):
            assert Entity.objects.get(pk=entity_id).deleted_at is not None


class TestFalsifierWiring:
    def test_class_paths_resolve_and_construct_with_no_arguments(self) -> None:
        import tomllib

        from django.utils.module_loading import import_string

        from tap_grid.falsifiers import Falsifier

        manifest = tomllib.loads((Path(__file__).resolve().parents[1] / "tap-plugin.toml").read_text())
        for entity_type in (DELEGATED_ADMINISTRATION, SERVICE_CONTROL_POLICY, ORGANIZATIONS_POLICY, POLICY_STATEMENT, TAG_POLICY_RULE):
            cls = import_string(manifest["falsifiers"][entity_type])
            assert issubclass(cls, Falsifier)
            assert cls()
