"""AWS Organizations tree reader for the boto3 collector (tap-plugin-aws-core#50).

Spec: specs/spec-aws-core-v0.md (req-aws-core-organizations-collect / -reconcile).

The manifest engine drives one account at a time; the Organizations tree is not a per-account
resource list but one connected structure read through a handful of calls that only the
management account (or a delegated administrator) may make. So it is its own pure collaborator,
called from ``Boto3Collector.run()`` with the run's already-resolved session, and it returns
what the run needs to fold into its single GRIFT batch: node envelopes, edge envelopes, and one
**listing** per parent whose children it read — the raw material of the completeness surfaces
(``req-grid-reconcile-evidence``) that make a removed OU or a removed account a reconcile
candidate at all.

What it reads (all read-only ``organizations:`` actions):

    DescribeOrganization                       the organization node
    ListRoots                                  the root (folded into the organization node)
    ListOrganizationalUnitsForParent           per root / per OU, so nested OUs are walked
    ListAccounts                               every member account (the membership surface)
    ListAccountsForParent                      per root / per OU: where each account sits now
    ListPolicies(Filter=SERVICE_CONTROL_POLICY)  the SCPs
    ListPolicies(Filter=<type>)                one per other policy type ENABLED on the root
    ListTargetsForPolicy                       per policy: where it is attached
    DescribePolicy                             per SCP/RCP: its statements; per tag policy: its rules
    ListAWSServiceAccessForOrganization        the AWS services with trusted access
    ListDelegatedAdministrators                the delegated-administrator accounts
    ListDelegatedServicesForAccount            per delegated account: which services
    ListTagsForResource                        root, OU, account and customer-managed policy tags

Organizations completeness (aws-core-tap#65, ``req-aws-core-organizations-completeness``) is
collect-only: every surface it records and every falsifier it registers is inert until reconcile
authority is armed, which nothing here does. Every list call above is paginated by botocore and is
read to its last page (``req-aws-collector-pagination``, ``PAGINATED_OPERATIONS``); a page after the
first that fails leaves the field ``null`` or the surface incomplete, never the pages read so far.

``ListTargetsForPolicy`` is used for attachments rather than ``ListPoliciesForTarget``: both give
the same edge set, but the former is one call per policy (a handful) where the latter is one per
root, OU *and account* (hundreds in the org this is for) against an API with a low request
quota.

Which edges, and why the direction differs from the existing tree edge
----------------------------------------------------------------------
``NESTED_UNDER_PARENT`` (OU/account -> parent) is the tree as a **reference**: an account moves
between OUs (``MoveAccount``), and nothing in core ends the old edge when the new one appears, so
it cannot be a containment declaration (the cascade would tombstone a live account through a stale
edge). Two NEW parent -> child edges carry the containment, each chosen so that the relation never
moves:

- ``PARTITIONED_INTO_OU`` (organization/OU -> OU). AWS has no operation that re-parents an OU, so
  an OU's parent is fixed for its life, and ``DeleteOrganizationalUnit`` refuses a non-empty OU.
- ``ENROLLS_ACCOUNT`` (organization -> account): the organization-wide ``ListAccounts`` membership.
  Deliberately organization-level, not OU-level: a ``MoveAccount`` does not change it, so a moved
  account is never mistaken for a departed one and never left holding a stale containment edge.

An account's current OU is also recorded on the node (``configuration.ParentId``), because the
``NESTED_UNDER_PARENT`` edge alone cannot say which of two edges is the stale one after a move.

Failure discipline
------------------
Nothing here raises for an AWS failure. A denied or failing call degrades to a **listing that says
so** (``scope_authorized`` false / ``enumeration_complete`` false, with a reason), never to an
empty result that reads as "the parent has no children". That is the whole difference between a
member-account credential, a delegated administrator missing one action, and an organization that
really is empty.

GovCloud
--------
Region and partition are never hardcoded. The client is built in the run's own first region and
botocore resolves the endpoint from it (verified offline against botocore 1.43.103's endpoint
data: every ``us-gov-*`` region resolves ``organizations`` to
``organizations.us-gov-west-1.amazonaws.com``, signing in ``us-gov-west-1``; commercial regions to
``organizations.us-east-1.amazonaws.com``; China to ``cn-northwest-1``). Every ARN stored comes
from an API response, none is constructed here, and the organization's ``partition`` field is read
from the ARN ``DescribeOrganization`` returns. NOT verified against a live GovCloud organization,
and assumed rather than confirmed from documentation: that GovCloud Organizations exposes the same
operations and response shapes listed above (in particular ``Account.State``, for which the reader
falls back to ``Account.Status``), and that service control policies are enabled on the root.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError
from tap_plugin.aws_core.policy_types import (
    OTHER_POLICY_TYPES,
    POLICY_TYPES,
    STATEMENT_POLICY_TYPES,
    TAG_RULE_POLICY_TYPES,
)
from tap_plugin.aws_core.policy_types import (
    SERVICE_CONTROL_POLICY as _SCP_TYPE,
)

from .identity import edge_entity_id, node_entity_id
from .policy_documents import PolicyDocumentError, parse_statements, parse_tag_rules
from .tags import normalize_tags

ORGANIZATION = "aws_core__aws_organization"
ORGANIZATIONAL_UNIT = "aws_core__aws_organizational_unit"
ACCOUNT = "aws_core__aws_account"
SERVICE_CONTROL_POLICY = "aws_core__aws_service_control_policy"
ORGANIZATIONS_POLICY = "aws_core__aws_organizations_policy"
POLICY_STATEMENT = "aws_core__aws_policy_statement"
TAG_POLICY_RULE = "aws_core__aws_tag_policy_rule"
DELEGATED_ADMINISTRATION = "aws_core__aws_delegated_administration"

PARTITIONED_INTO_OU = "PARTITIONED_INTO_OU__aws_core"
ENROLLS_ACCOUNT = "ENROLLS_ACCOUNT__aws_core"
NESTED_UNDER_PARENT = "NESTED_UNDER_PARENT__aws_core"
ATTACHED_TO_TARGET = "ATTACHED_TO_TARGET__aws_core"
HOLDS_DELEGATION = "HOLDS_DELEGATION__aws_core"
DELEGATES_TO_ACCOUNT = "DELEGATES_TO_ACCOUNT__aws_core"
HOLDS_SERVICE_CONTROL_POLICY = "HOLDS_SERVICE_CONTROL_POLICY__aws_core"
HOLDS_ORGANIZATIONS_POLICY = "HOLDS_ORGANIZATIONS_POLICY__aws_core"
DECLARES_STATEMENT = "DECLARES_STATEMENT__aws_core"
DECLARES_TAG_RULE = "DECLARES_TAG_RULE__aws_core"

#: The (parent type -> containment edge types) this reader records surfaces for, mirroring each
#: parent model's CONTAINMENT_EDGES (``req-aws-core-contained-type-triple-1``; a test compares them).
CONTAINMENT_SURFACES: dict[str, tuple[str, ...]] = {
    ORGANIZATION: (
        PARTITIONED_INTO_OU,
        ENROLLS_ACCOUNT,
        HOLDS_DELEGATION,
        HOLDS_SERVICE_CONTROL_POLICY,
        HOLDS_ORGANIZATIONS_POLICY,
    ),
    ORGANIZATIONAL_UNIT: (PARTITIONED_INTO_OU,),
    SERVICE_CONTROL_POLICY: (DECLARES_STATEMENT,),
    ORGANIZATIONS_POLICY: (DECLARES_STATEMENT, DECLARES_TAG_RULE),
}

#: Every operation this reader reads through its page loop. Each is paginated in the pinned
#: botocore's ``paginators-1.json`` (``req-aws-collector-pagination-3``; a test walks the list).
#: ``DescribeOrganization`` and ``DescribePolicy`` are not paginated and are single calls.
PAGINATED_OPERATIONS: tuple[str, ...] = (
    "list_roots",
    "list_organizational_units_for_parent",
    "list_accounts",
    "list_accounts_for_parent",
    "list_policies",
    "list_targets_for_policy",
    "list_tags_for_resource",
    "list_aws_service_access_for_organization",
    "list_delegated_administrators",
    "list_delegated_services_for_account",
)

#: Completeness-surface relation names, in the source's own terms (the spec's
#: ``repository.secrets`` convention): ``<parent kind>.<what was listed>``.
RELATION_ORGANIZATION_OUS = "organization.organizational_units"
RELATION_OU_OUS = "organizational_unit.organizational_units"
RELATION_ORGANIZATION_ACCOUNTS = "organization.accounts"
RELATION_ORGANIZATION_DELEGATIONS = "organization.delegated_administrations"
RELATION_ORGANIZATION_SCPS = "organization.service_control_policies"
RELATION_ORGANIZATION_POLICIES = "organization.organizations_policies"
RELATION_POLICY_STATEMENTS = "policy.statements"
RELATION_POLICY_TAG_RULES = "policy.tag_rules"

#: ``ListPolicies`` requires a Filter. SCPs are always listed (their own model, as before
#: aws-core-tap#65); every other type only when the root has it ENABLED.
_SCP_FILTER = _SCP_TYPE
_ENABLED = "ENABLED"
#: ``ListDelegatedServicesForAccount``: "the specified account is not a delegated administrator"
#: (botocore organizations model). During collection it means the outer listing named an account the
#: inner read disowns: the two reads disagree.
ACCOUNT_NOT_REGISTERED = "AccountNotRegisteredException"
#: Organizations caps every list call at 20 items.
_PAGE_SIZE = 20
#: A token loop that never ends is a defect in the source, not a listing; stop and say so.
_MAX_PAGES = 5000

_NOT_IN_USE_CODES = frozenset({"AWSOrganizationsNotInUseException"})
_DENIED_CODES = frozenset(
    {"AccessDeniedException", "AccessDenied", "AccessDeniedForDependencyException", "UnauthorizedOperation"}
)

#: Account states in which AWS still lists the account but it is no longer usable. Closed and
#: suspended accounts stay visible in Organizations (for a period AWS controls) — visibility, not
#: existence, is what a listing observes, so these are reported in ``status`` and never dropped.
INACTIVE_ACCOUNT_STATES = frozenset({"SUSPENDED", "PENDING_CLOSURE", "CLOSED"})


#: This reader's name in the custom-reader registries (tag_lanes.json, reader_sensitivity.json).
READER = "organizations"
_HERE = Path(__file__).resolve().parent


@functools.cache
def reader_sensitivity(reader: str = READER) -> dict[str, dict[str, Any]]:
    """``{entity type: sensitivity block}`` for every type ``reader`` may emit (this reader by
    default; the landing-zone reader passes its own name), from ``reader_sensitivity.json``, each
    block validated against the manifest schema's ``$defs/sensitivity``
    (``req-aws-collector-manifest-6``). An invalid file raises: it is a defect in the plugin, and
    the collector isolates it like any other defect in this read."""
    import jsonschema

    schema = json.loads((_HERE / "aws_resource_manifest.schema.json").read_text())
    block_schema = {**schema["$defs"]["sensitivity"], "$defs": schema["$defs"]}
    declared: dict[str, dict[str, Any]] = {}
    for row in json.loads((_HERE / "reader_sensitivity.json").read_text())["rows"]:
        if row["reader"] != reader:
            continue
        jsonschema.validate(row["sensitivity"], block_schema)
        if row["entity_type"] in declared:
            raise ValueError(f"reader_sensitivity.json declares {row['entity_type']} twice for {reader}")
        declared[row["entity_type"]] = row["sensitivity"]
    return declared


def sensitivity_refusal(entity_type: str, declared: dict[str, dict[str, Any]]) -> str | None:
    """Why a node of ``entity_type`` may not be written by this reader, or None.

    The type-level equivalent of the manifest's per-entry rules for a reader that stores typed
    fields only: there is no ``persist_configuration`` switch, so a type nobody reviewed
    (``req-aws-collector-manifest-7``) or one with a ``credential`` location
    (``req-aws-collector-field-projection-7``'s default) is not written at all."""
    block = declared.get(entity_type)
    if block is None:
        return "no sensitivity declaration in reader_sensitivity.json"
    if block["status"] == "unreviewed":
        return "its sensitivity is unreviewed, and a custom reader's typed fields cannot be withheld"
    credential = [loc["path"] for loc in block.get("locations", []) if loc["category"] == "credential"]
    if credential:
        return f"its typed field(s) {', '.join(credential)} are declared credential"
    return None


def organizations_client(session: Any, region: str) -> Any:
    """An ``organizations`` client in the run's own region, with retry headroom.

    The region comes from the credential's region scope, so the endpoint and the partition follow
    the credential (see the module docstring); Organizations has a low request quota, so the
    standard retry mode is given more attempts than the default.
    """
    return session.client("organizations", region_name=region, config=Config(retries={"mode": "standard", "max_attempts": 8}))


def error_code(exc: BaseException) -> str:
    """The AWS ``Error.Code`` of a ``ClientError``, or ``""``."""
    if isinstance(exc, ClientError):
        return str((exc.response or {}).get("Error", {}).get("Code", ""))
    return ""


def partition_of_arn(arn: str) -> str:
    """The partition segment of an ARN (``arn:<partition>:...``), or ``""``."""
    parts = str(arn or "").split(":", 2)
    return parts[1] if len(parts) == 3 and parts[0] == "arn" else ""


def organization_id_of_account_arn(arn: str) -> str:
    """The organization id in an Organizations account ARN, or ``""``.

    ``arn:<partition>:organizations::<management account>:account/<o-id>/<account id>``.
    """
    segments = str(arn or "").split(":", 5)
    if len(segments) != 6 or segments[2] != "organizations":
        return ""
    resource = segments[5].split("/")
    return resource[1] if len(resource) >= 3 and resource[0] == "account" else ""


def account_state(account: dict[str, Any]) -> str:
    """``Account.State`` (the current field) falling back to the deprecated ``Status``."""
    return str(account.get("State") or account.get("Status") or "")


@dataclass
class Listing:
    """What one parent's child listing established — the raw material of a completeness surface.

    ``subject`` is the parent's grid entity id. Ids here are deterministic ``uuid5`` values the
    batch carries explicitly, so the id the batch writes IS the id core holds (no batch-local ref
    to resolve after import, unlike an assigned-identity plugin).
    """

    relation: str
    edge_type: str
    subject: str
    first: datetime
    last: datetime
    authorized: bool | None
    complete: bool | None
    count: int | None
    admitted: bool = True
    reasons: dict[str, str] = field(default_factory=dict)

    def surface(self, applied_batches: list[str]) -> dict[str, Any]:
        """The authored surface fields ``CollectorBase.record_surface`` takes."""
        reasons = dict(self.reasons)
        reasons.setdefault("source_consistent", "no_promise: AWS Organizations makes no snapshot promise across pages")
        return {
            "relation": self.relation,
            "edge_type": self.edge_type,
            "subject": self.subject,
            "interval": {"first": self.first.isoformat(), "last": self.last.isoformat()},
            "scope_authorized": self.authorized,
            "enumeration_complete": self.complete,
            "source_consistent": "unknown",
            "admitted": self.admitted,
            "count_observed": self.count,
            "reasons": reasons,
            "applied_batches": list(applied_batches),
        }


@dataclass
class Notice:
    """A structured run-log entry the collector forwards (``level`` is ``info`` or ``warn``)."""

    level: str
    code: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrganizationTree:
    """Everything one Organizations read produced."""

    #: ``collected`` (the tree was read), ``not_in_organization``, ``not_authorized`` or ``failed``
    #: (DescribeOrganization gave no organization to describe).
    state: str = "failed"
    organization_id: str = ""
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    listings: list[Listing] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    #: Every member account id the organization-wide ``ListAccounts`` named, or None when that
    #: listing did not read to its end (or was never reached). The landing-zone reader's Identity
    #: Center assignment surface is complete only over a complete account set
    #: (``req-aws-landing-zone-identity-center-5``).
    member_accounts: list[str] | None = None

    def node_ids(self, entity_type: str) -> set[str]:
        return {n["entity"]["entity_id"] for n in self.nodes if n["entity"]["entity_type"] == entity_type}


def _now() -> datetime:
    return datetime.now(UTC)


def _envelope(entity_type: str, natural_key: str, name: str, fields: dict[str, Any], dimensions: dict[str, str]) -> dict[str, Any]:
    """A GRIFT node envelope. ``fields`` are exactly the model's own columns.

    Unlike the manifest engine's ``node_envelope`` this adds no ``configuration``: the organization,
    OU and SCP models declare none (``req-aws-core-organizations-7``), and the service layer
    refuses an undeclared field, which would reject the whole batch.
    """
    return {
        "entity": {
            "entity_id": str(node_entity_id(entity_type, natural_key)),
            "entity_type": entity_type,
            "name": name,
            "dimensions": dict(dimensions),
        },
        "node": fields,
    }


def _edge(edge_type: str, from_type: str, from_key: str, to_type: str, to_key: str, dimensions: dict[str, str]) -> dict[str, Any]:
    return {
        "entity": {
            "entity_id": str(edge_entity_id(edge_type, from_key, to_key)),
            "entity_type": "edge",
            "name": f"{from_key} {edge_type} {to_key}",
            "dimensions": dict(dimensions),
        },
        "edge": {
            "from_entity_id": str(node_entity_id(from_type, from_key)),
            "to_entity_id": str(node_entity_id(to_type, to_key)),
            "edge_type": edge_type,
            "properties": {},
        },
    }


def _schema_problem(entity_type: str, fields: dict[str, Any]) -> str | None:
    """Why ``fields`` would be refused by the model's own validation schema, or None.

    One malformed value (an id AWS formats differently in some partition, say) must cost one node,
    not the whole batch: the service layer rejects a batch on a single invalid node, and a
    rejected batch aborts the run — so this check must be at least as strict as the service
    layer's own, never a lighter approximation of it. ``SERVICE_CRUD_SCHEMA["create"]``
    (``tap_grid.models._build_service_schemas``) is exactly what ``create_node`` validates
    against: ``FIELD_CRUD_SCHEMA``'s per-field schemas under ``additionalProperties: False`` with
    ``CREATE_REQUIRED`` enforced — read directly rather than re-derived, so the two can never
    silently drift apart.
    """
    import jsonschema

    from tap_grid.registry import get_model_class

    schema = get_model_class(entity_type).SERVICE_CRUD_SCHEMA["create"]
    validator = jsonschema.Draft202012Validator(schema)
    problems = sorted(validator.iter_errors(fields), key=lambda e: list(e.path))
    if not problems:
        return None
    first = problems[0]
    where = ".".join(str(p) for p in first.path) or "<node>"
    return f"{where}: {first.message}"


@dataclass
class _Read:
    """The outcome of reading one paginated call to its end (or to its failure)."""

    items: list[dict[str, Any]]
    first: datetime
    last: datetime
    #: True only when the walk reached the last page with no error.
    complete: bool = True
    #: False when the credential was refused, None when the failure says nothing about permission.
    authorized: bool | None = True
    why: str = ""
    #: The AWS ``Error.Code`` of the failure, when there was one.
    code: str = ""


def _aggregate(reads: list[_Read], *, why: str = "") -> _Read:
    """Several listings behind ONE surface (one parent, one edge type): complete only when every
    one of them is, and ``why`` names every failure (``req-aws-core-contained-type-triple``,
    "nested listings aggregate"). ``why`` adds a failure that is not a read (two reads disagreeing,
    a precondition unread). Authorization is refused when any read was refused."""
    first = min((r.first for r in reads), default=_now())
    last = max((r.last for r in reads), default=first)
    failed = [r for r in reads if not r.complete]
    reasons = [r.why for r in failed if r.why] + ([why] if why else [])
    if not failed and not why:
        return _Read([], first, last)
    authorized: bool | None = False if any(r.authorized is False for r in failed) else None
    return _Read([], first, last, complete=False, authorized=authorized, why="; ".join(reasons) or "incomplete")


class _Reader:
    """One Organizations read. Holds the client, the accumulators and the tag-permission latch."""

    def __init__(self, client: Any, dimensions: dict[str, str], sensitivity: dict[str, dict[str, Any]] | None = None) -> None:
        self.client = client
        self.dimensions = dimensions
        self.sensitivity = reader_sensitivity() if sensitivity is None else sensitivity
        self.tree = OrganizationTree()
        #: Once ListTagsForResource is denied it is denied for every resource; stop asking.
        self._tags_denied = False
        self._tags_missing = 0

    # -- plumbing ---------------------------------------------------------

    def notice(self, level: str, code: str, message: str, **data: Any) -> None:
        self.tree.notices.append(Notice(level, code, message, data))

    def _pages(self, operation: str, result_key: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Every item of a paginated list call. Raises what the call raises."""
        fn: Callable[..., dict[str, Any]] = getattr(self.client, operation)
        token: str | None = None
        for _ in range(_MAX_PAGES):
            kwargs = dict(params, MaxResults=_PAGE_SIZE)
            if token:
                kwargs["NextToken"] = token
            response = fn(**kwargs)
            yield from response.get(result_key) or []
            token = response.get("NextToken")
            if not token:
                return
        raise EndpointConnectionError(endpoint_url=f"{operation}: NextToken chain exceeded {_MAX_PAGES} pages")

    def read(self, operation: str, result_key: str, **params: Any) -> _Read:
        """Read one list call to its end. A failure keeps the items it did get (they are real
        observations) but marks the read incomplete, so nothing is inferred from what it did not name."""
        first = _now()
        result = _Read(items=[], first=first, last=first)
        try:
            for item in self._pages(operation, result_key, params):
                result.items.append(item)
        except ClientError as exc:
            code = error_code(exc) or "ClientError"
            result.complete = False
            result.authorized = False if code in _DENIED_CODES else None
            result.why = f"{code}: {operation} failed"
            result.code = code
            self.notice(
                "info" if result.authorized is False else "warn",
                "ORG_LISTING_FAILED",
                result.why,
                operation=operation,
                error_code=code,
            )
        except BotoCoreError as exc:
            result.complete = False
            result.authorized = None
            result.why = f"{type(exc).__name__}: {operation} failed"
            self.notice("warn", "ORG_LISTING_FAILED", result.why, operation=operation)
        result.last = _now()
        return result

    def surface(
        self, read: _Read, relation: str, edge_type: str, subject_type: str, subject_key: str, *, count: int | None = None
    ) -> Listing:
        """Describe what ``read`` established as a completeness surface, and keep it for the run.

        ``count`` overrides the item count when the listing names more than it contains (a policy
        listing names AWS-managed policies no organization contains)."""
        subject = str(node_entity_id(subject_type, subject_key))
        if read.complete:
            listing = Listing(
                relation, edge_type, subject, read.first, read.last, True, True, len(read.items) if count is None else count
            )
        else:
            denied = read.authorized is False
            listing = Listing(
                relation,
                edge_type,
                subject,
                read.first,
                read.last,
                authorized=read.authorized,
                complete=False,
                count=None,
                admitted=False,
                reasons={
                    "scope_authorized": f"{'denied' if denied else 'not_determinable'}: {read.why}",
                    "enumeration_complete": f"nothing_established: {read.why}",
                    "admitted": f"nothing_to_process: {read.why}",
                },
            )
        self.tree.listings.append(listing)
        return listing

    def tags_of(self, resource_id: str) -> dict[str, str] | None:
        """``ListTagsForResource`` normalized to ``{str: str}``, or ``None`` when unreadable.

        ``None`` is deliberate, never ``{}``: GRIFT upsert applies every node through
        ``replace_node`` (``tap_grid/grift/importer.py``), whose ``_apply_replace`` resets an
        OPTIONAL field the envelope omits to the model default — the same ``{}`` an empty JSONField
        defaults to. So neither sending ``{}`` nor omitting the key can honestly stand for "not
        read this run": both read back as an authoritative "no tags", silently erasing real tags a
        previous run observed the moment a permission narrows or one call times out. The only
        honest response is not to write the node at all this run — ``add_node`` (below) refuses a
        node whose ``tags`` is this ``None`` sentinel, the same way it refuses a schema violation.

        An unreadable tag set is counted and reported once rather than per resource, and a denial
        latches: the permission is per action, not per resource.
        """
        if self._tags_denied:
            return None
        raw: list[dict[str, Any]] = []
        token: str | None = None
        try:
            for _ in range(_MAX_PAGES):
                kwargs: dict[str, Any] = {"ResourceId": resource_id}
                if token:
                    kwargs["NextToken"] = token
                response = self.client.list_tags_for_resource(**kwargs)
                raw.extend(response.get("Tags") or [])
                token = response.get("NextToken")
                if not token:
                    break
        except ClientError as exc:
            if error_code(exc) in _DENIED_CODES:
                self._tags_denied = True
                self.notice(
                    "info",
                    "ORG_TAGS_DENIED",
                    "organizations:ListTagsForResource is denied: the organization (its root's tags), OU, account "
                    "and customer-managed policy nodes are not written this run rather than overwriting their "
                    "tags with a false empty observation.",
                )
            else:
                self._tags_missing += 1
            return None
        except BotoCoreError:
            self._tags_missing += 1
            return None
        return normalize_tags(raw, "list_kv")

    # -- shaping ----------------------------------------------------------

    def add_node(
        self, entity_type: str, natural_key: str, name: str, fields: dict[str, Any], *, tags_not_read: bool = False
    ) -> bool:
        """Append one node envelope unless the model would refuse it, or its tags were unreadable
        this run; True when kept.

        A ``tags`` of ``None`` (the ``tags_of`` sentinel) is caught here rather than left for
        ``_schema_problem`` to reject on type (``{"type": "object", ...}`` would refuse ``None``
        anyway) so the recorded reason names the real cause — an unreadable read, not a malformed
        one — and every caller gets the same refusal for free rather than repeating the check.

        ``tags_not_read`` is the one exception, the organization whose root could not be listed
        (``_add_organization``): it has no root id to read tags for, the node must still be written
        (``req-aws-core-organizations-collect-4``), and its model accepts ``null`` as "not read".
        """
        if "tags" in fields and fields["tags"] is None and not tags_not_read:
            self.notice(
                "warn",
                "ORG_NODE_SKIPPED",
                f"{entity_type} {natural_key}: skipped, tags could not be read this run",
                entity_type=entity_type,
            )
            return False
        refused = sensitivity_refusal(entity_type, self.sensitivity)
        if refused is not None:
            self.notice(
                "warn", "ORG_NODE_SKIPPED", f"{entity_type} {natural_key}: skipped, {refused}", entity_type=entity_type
            )
            return False
        problem = _schema_problem(entity_type, fields)
        if problem is not None:
            self.notice(
                "warn", "ORG_NODE_SKIPPED", f"{entity_type} {natural_key}: skipped, {problem}", entity_type=entity_type
            )
            return False
        self.tree.nodes.append(_envelope(entity_type, natural_key, name, fields, self.dimensions))
        return True

    def add_edge(self, edge_type: str, from_type: str, from_key: str, to_type: str, to_key: str) -> None:
        self.tree.edges.append(_edge(edge_type, from_type, from_key, to_type, to_key, self.dimensions))

    @staticmethod
    def withdraw_if_skipped(listing: Listing, skipped: int) -> None:
        """A listing whose child the model refused did not reach processing whole.

        The skipped child exists in AWS but is not written, so it would look absent from the run's
        observations. The falsifier would rescue it, but a surface that knowingly did not land
        everything must not claim to have.
        """
        if skipped and listing.admitted:
            listing.admitted = False
            listing.reasons["admitted"] = f"child_skipped: {skipped} listed item(s) were refused by the model"

    # -- the read ---------------------------------------------------------

    def collect(self) -> OrganizationTree:
        organization = self._describe_organization()
        if organization is None:
            return self.tree
        org_id = str(organization["Id"])
        self.tree.organization_id = org_id

        roots = self.read("list_roots", "Roots")
        root_ids = sorted(str(r["Id"]) for r in roots.items if r.get("Id"))
        roots_read = roots.complete and bool(root_ids)
        root = next((r for r in roots.items if root_ids and str(r.get("Id") or "") == root_ids[0]), {})
        enabled = _enabled_policy_types(root) if roots_read else None
        self._add_organization(
            organization,
            root_ids[0] if root_ids else "",
            roots_read=roots_read,
            # The field holds only the pinned enum's values (its model refuses any other); the policy
            # reader below gets every ENABLED type and refuses completeness for one it cannot model.
            enabled_policy_types=None if enabled is None else [t for t in enabled if t in POLICY_TYPES],
            enabled_service_principals=self._read_service_access(),
        )
        self.tree.state = "collected"
        if not roots_read:
            # A member account can DescribeOrganization but not ListRoots: it can see that the
            # organization exists and nothing of its tree. Say so on every surface it would have
            # read, rather than record none (which reads as "did not think about it").
            why = roots.why or "ListRoots returned no root"
            failed = _Read([], roots.first, roots.last, complete=False, authorized=roots.authorized, why=why)
            self.surface(failed, RELATION_ORGANIZATION_OUS, PARTITIONED_INTO_OU, ORGANIZATION, org_id)
            self.surface(failed, RELATION_ORGANIZATION_ACCOUNTS, ENROLLS_ACCOUNT, ORGANIZATION, org_id)
            self.surface(failed, RELATION_ORGANIZATION_DELEGATIONS, HOLDS_DELEGATION, ORGANIZATION, org_id)
            self.surface(failed, RELATION_ORGANIZATION_SCPS, HOLDS_SERVICE_CONTROL_POLICY, ORGANIZATION, org_id)
            self.surface(failed, RELATION_ORGANIZATION_POLICIES, HOLDS_ORGANIZATIONS_POLICY, ORGANIZATION, org_id)
            return self.tree

        seen_ous: set[str] = set()
        # (the parent's AWS id, its grid entity type, its grid natural key)
        queue: list[tuple[str, str, str]] = [(rid, ORGANIZATION, org_id) for rid in root_ids]
        root_parents = list(queue)
        while queue:
            parent_aws_id, parent_type, parent_key = queue.pop(0)
            relation = RELATION_ORGANIZATION_OUS if parent_type == ORGANIZATION else RELATION_OU_OUS
            read = self.read("list_organizational_units_for_parent", "OrganizationalUnits", ParentId=parent_aws_id)
            listing = self.surface(read, relation, PARTITIONED_INTO_OU, parent_type, parent_key)
            skipped = 0
            for unit in sorted(read.items, key=lambda u: str(u.get("Id") or "")):
                ou_id = str(unit.get("Id") or "")
                if not ou_id or ou_id in seen_ous:
                    continue
                seen_ous.add(ou_id)
                name = str(unit.get("Name") or ou_id)
                if not self.add_node(
                    ORGANIZATIONAL_UNIT, ou_id, name, {"name": name, "ou_id": ou_id, "tags": self.tags_of(ou_id)}
                ):
                    skipped += 1
                    continue
                self.add_edge(PARTITIONED_INTO_OU, parent_type, parent_key, ORGANIZATIONAL_UNIT, ou_id)
                self.add_edge(NESTED_UNDER_PARENT, ORGANIZATIONAL_UNIT, ou_id, parent_type, parent_key)
                queue.append((ou_id, ORGANIZATIONAL_UNIT, ou_id))
            self.withdraw_if_skipped(listing, skipped)

        placement_parents = root_parents + [(ou, ORGANIZATIONAL_UNIT, ou) for ou in sorted(seen_ous)]
        self._read_accounts(org_id, placement_parents)
        self._read_delegations(org_id)
        self._read_service_control_policies(org_id)
        self._read_other_policies(org_id, enabled)
        if self._tags_missing:
            self.notice(
                "warn",
                "ORG_TAGS_INCOMPLETE",
                f"{self._tags_missing} tag read(s) failed; those nodes carry no tags this run.",
                count=self._tags_missing,
            )
        self._dedupe()
        return self.tree

    def _dedupe(self) -> None:
        """One envelope per entity id: a root-attached policy listed under two roots, say."""
        for attr in ("nodes", "edges"):
            seen: set[str] = set()
            kept = []
            for envelope in getattr(self.tree, attr):
                entity_id = envelope["entity"]["entity_id"]
                if entity_id not in seen:
                    seen.add(entity_id)
                    kept.append(envelope)
            setattr(self.tree, attr, kept)

    def _describe_organization(self) -> dict[str, Any] | None:
        try:
            response = self.client.describe_organization()
        except ClientError as exc:
            code = error_code(exc)
            if code in _NOT_IN_USE_CODES:
                self.tree.state = "not_in_organization"
                self.notice(
                    "info",
                    "ORG_NOT_IN_USE",
                    "This AWS account is not part of an organization; no Organizations tree to collect.",
                )
            elif code in _DENIED_CODES:
                self.tree.state = "not_authorized"
                self.notice(
                    "info",
                    "ORG_NOT_AUTHORIZED",
                    "organizations:DescribeOrganization is denied to this credential; the Organizations tree is not collected.",
                    error_code=code,
                )
            else:
                self.tree.state = "failed"
                self.notice(
                    "warn", "ORG_DESCRIBE_FAILED", f"DescribeOrganization failed: {code or type(exc).__name__}", error_code=code
                )
            return None
        except BotoCoreError as exc:
            self.tree.state = "failed"
            self.notice("warn", "ORG_DESCRIBE_FAILED", f"DescribeOrganization failed: {type(exc).__name__}")
            return None
        organization = response.get("Organization") or {}
        if not organization.get("Id"):
            self.tree.state = "failed"
            self.notice("warn", "ORG_DESCRIBE_FAILED", "DescribeOrganization returned no organization id.")
            return None
        return dict(organization)

    def _add_organization(
        self,
        organization: dict[str, Any],
        root_id: str,
        *,
        roots_read: bool,
        enabled_policy_types: list[str] | None,
        enabled_service_principals: list[dict[str, str]] | None,
    ) -> None:
        """The organization node, which stands for its root (``req-aws-core-organizations-4``).

        Its ``tags`` are the root's (``req-aws-core-organizations-completeness-1``), read through
        the same ``tags_of`` as every other Organizations node, with the same rule: a root tag set
        that could not be read withholds the node rather than write a false empty map. One case is
        different, settled here (aws-core-tap#65, the Copilot finding carried from aws-core-tap#71):
        when ``ListRoots`` itself failed there is no root id to read tags FOR, and the node must
        still be written (``req-aws-core-organizations-collect-4``). It is then written with
        ``tags: null``, which the organization model accepts and which means "not read", never ``{}``.
        """
        org_id = str(organization["Id"])
        partition = partition_of_arn(str(organization.get("Arn") or "")) or str(
            getattr(getattr(self.client, "meta", None), "partition", "") or ""
        )
        name = f"Organization {org_id}"
        self.add_node(
            ORGANIZATION,
            org_id,
            name,
            {
                "name": name,
                "organization_id": org_id,
                "root_id": root_id,
                "management_account_id": str(organization.get("MasterAccountId") or ""),
                "feature_set": str(organization.get("FeatureSet") or ""),
                "partition": partition,
                "tags": self.tags_of(root_id) if roots_read else None,
                "enabled_policy_types": enabled_policy_types,
                "enabled_service_principals": enabled_service_principals,
            },
            tags_not_read=not roots_read,
        )

    def _read_service_access(self) -> list[dict[str, str]] | None:
        """``ListAWSServiceAccessForOrganization`` to its last page; ``None`` when any page failed
        (``req-aws-core-organizations-completeness-3``, ``req-aws-collector-pagination-2``)."""
        read = self.read("list_aws_service_access_for_organization", "EnabledServicePrincipals")
        if not read.complete:
            return None
        by_principal: dict[str, str] = {}
        for item in read.items:
            principal = str(item.get("ServicePrincipal") or "")
            if principal:
                by_principal[principal] = _iso(item.get("DateEnabled"))
        return [{"service_principal": p, "enabled_at": by_principal[p]} for p in sorted(by_principal)]

    def _account_fields(self, account: dict[str, Any], parent_id: str | None) -> tuple[str, dict[str, Any]] | None:
        account_id = str(account.get("Id") or "")
        if not account_id:
            return None
        configuration: dict[str, Any] = {
            # Email and Name are typed columns already; the free-form blob carries only what they do not.
            "Arn": str(account.get("Arn") or ""),
            "State": str(account.get("State") or ""),
            "Status": str(account.get("Status") or ""),
            "JoinedMethod": str(account.get("JoinedMethod") or ""),
            "JoinedTimestamp": _iso(account.get("JoinedTimestamp")),
            "_source": {"op": "ListAccounts", "why": "Member account of the organization."},
        }
        if parent_id:
            configuration["ParentId"] = parent_id
        return account_id, {
            "name": str(account.get("Name") or account_id),
            "account_id": account_id,
            "email": str(account.get("Email") or ""),
            "status": account_state(account),
            "configuration": configuration,
        }

    def _read_accounts(self, org_id: str, parents: list[tuple[str, str, str]]) -> None:
        """Membership from ``ListAccounts``; placement from ``ListAccountsForParent`` per parent."""
        members = self.read("list_accounts", "Accounts")
        membership = self.surface(members, RELATION_ORGANIZATION_ACCOUNTS, ENROLLS_ACCOUNT, ORGANIZATION, org_id)
        if members.complete:
            self.tree.member_accounts = sorted({str(a["Id"]) for a in members.items if a.get("Id")})
        by_id: dict[str, dict[str, Any]] = {str(a["Id"]): a for a in members.items if a.get("Id")}
        placement: dict[str, tuple[str, str, str]] = {}
        placement_complete = True
        for parent_aws_id, parent_type, parent_key in parents:
            # Placement is a reference (NESTED_UNDER_PARENT), not a containment surface: nothing is
            # inferred from a parent NOT naming an account, so no surface is recorded for it.
            read = self.read("list_accounts_for_parent", "Accounts", ParentId=parent_aws_id)
            placement_complete = placement_complete and read.complete
            for account in read.items:
                account_id = str(account.get("Id") or "")
                if account_id:
                    placement[account_id] = (parent_aws_id, parent_type, parent_key)
                    by_id.setdefault(account_id, account)

        skipped = 0
        for account_id in sorted(by_id):
            parent = placement.get(account_id)
            shaped = self._account_fields(by_id[account_id], parent[0] if parent else None)
            if shaped is None:
                continue
            key, fields = shaped
            fields["tags"] = self.tags_of(key)
            if not self.add_node(ACCOUNT, key, fields["name"], fields):
                skipped += 1
                continue
            self.add_edge(ENROLLS_ACCOUNT, ORGANIZATION, org_id, ACCOUNT, key)
            if parent is not None:
                self.add_edge(NESTED_UNDER_PARENT, ACCOUNT, key, parent[1], parent[2])
        self.withdraw_if_skipped(membership, skipped)
        unplaced = sorted(a for a in by_id if a not in placement)
        if unplaced:
            self.notice(
                "warn",
                "ORG_ACCOUNTS_UNPLACED",
                f"{len(unplaced)} member account(s) were named by no parent listing this run "
                f"({'a parent listing failed' if not placement_complete else 'moved mid-walk'}); "
                "their placement edge is not refreshed.",
                count=len(unplaced),
            )

    def _read_delegations(self, org_id: str) -> None:
        """Delegated administration (``req-aws-core-organizations-completeness-4``, ``-13``).

        ``ListDelegatedAdministrators``, then ``ListDelegatedServicesForAccount`` per account it
        names, each read to its last page. ONE ``HOLDS_DELEGATION`` surface for the organization,
        complete only when every one of those reads finished: core fans candidates out from the
        surface's parent and edge type, so a surface per inner call would nominate every other
        account's delegations. ``AccountNotRegisteredException`` for an account the outer listing
        named means the two reads disagree, recorded as an incomplete surface with that reason.
        """
        outer = self.read("list_delegated_administrators", "DelegatedAdministrators")
        reads = [outer]
        disagreements: list[str] = []
        skipped = emitted = 0
        accounts = sorted({str(a.get("Id") or "") for a in outer.items} - {""})
        for account_id in accounts:
            inner = self.read("list_delegated_services_for_account", "DelegatedServices", AccountId=account_id)
            if inner.code == ACCOUNT_NOT_REGISTERED:
                disagreements.append(account_id)
            else:
                reads.append(inner)
            for service in sorted(inner.items, key=lambda d: str(d.get("ServicePrincipal") or "")):
                principal = str(service.get("ServicePrincipal") or "")
                if not principal:
                    continue
                key = delegation_key(org_id, account_id, principal)
                label = f"{principal} -> {account_id}"
                fields: dict[str, Any] = {
                    "name": label,
                    "organization_id": org_id,
                    "account_id": account_id,
                    "service_principal": principal,
                    "delegation_enabled_at": _iso(service.get("DelegationEnabledDate")),
                    # AWS cannot tag a delegation (lane `none`, tag_lanes.json).
                    "tags": {},
                }
                if not self.add_node(DELEGATED_ADMINISTRATION, key, label, fields):
                    skipped += 1
                    continue
                emitted += 1
                self.add_edge(HOLDS_DELEGATION, ORGANIZATION, org_id, DELEGATED_ADMINISTRATION, key)
                self.add_edge(DELEGATES_TO_ACCOUNT, DELEGATED_ADMINISTRATION, key, ACCOUNT, account_id)
        why = ""
        if disagreements:
            why = (
                f"{ACCOUNT_NOT_REGISTERED}: ListDelegatedAdministrators named {len(disagreements)} account(s) that "
                f"ListDelegatedServicesForAccount says are not delegated administrators ({', '.join(disagreements)})"
            )
            self.notice("warn", "ORG_DELEGATION_READS_DISAGREE", why, accounts=disagreements)
        listing = self.surface(
            _aggregate(reads, why=why),
            RELATION_ORGANIZATION_DELEGATIONS,
            HOLDS_DELEGATION,
            ORGANIZATION,
            org_id,
            count=emitted,
        )
        self.withdraw_if_skipped(listing, skipped)

    def _read_service_control_policies(self, org_id: str) -> None:
        """SCPs, always listed (their own model, as before aws-core-tap#65). One
        ``HOLDS_SERVICE_CONTROL_POLICY`` surface for the organization; only customer-managed SCPs
        are its children (``req-aws-core-organizations-completeness-6``)."""
        listed = self.read("list_policies", "Policies", Filter=_SCP_FILTER)
        # Policies a failed listing did return are real observations and are written; the
        # surface is then incomplete, so nothing is inferred from what it did not name.
        emitted, skipped = self._add_policies(org_id, listed.items, SERVICE_CONTROL_POLICY, HOLDS_SERVICE_CONTROL_POLICY)
        listing = self.surface(
            listed, RELATION_ORGANIZATION_SCPS, HOLDS_SERVICE_CONTROL_POLICY, ORGANIZATION, org_id, count=emitted
        )
        self.withdraw_if_skipped(listing, skipped)

    def _read_other_policies(self, org_id: str, enabled: list[str] | None) -> None:
        """Every other policy type the root has ENABLED (``req-aws-core-organizations-completeness-5``,
        ``-14``): one ``ListPolicies(Filter=<type>)`` per type and never one for a type the root has
        not enabled, all behind ONE ``HOLDS_ORGANIZATIONS_POLICY`` surface, complete only when the
        enabled types were read and every per-type listing finished."""
        now = _now()
        if enabled is None:
            unread = _Read([], now, now, complete=False, authorized=None, why="the root's enabled policy types were not read")
            self.surface(unread, RELATION_ORGANIZATION_POLICIES, HOLDS_ORGANIZATIONS_POLICY, ORGANIZATION, org_id)
            return
        reads: list[_Read] = []
        unknown: list[str] = []
        emitted = skipped = 0
        for policy_type in enabled:
            if policy_type == _SCP_FILTER:
                continue
            if policy_type not in OTHER_POLICY_TYPES:
                # A type AWS added after the pinned botocore: the model would refuse its
                # policy_type, so it is not listed, and the surface cannot claim completeness.
                unknown.append(policy_type)
                continue
            listed = self.read("list_policies", "Policies", Filter=policy_type)
            reads.append(listed)
            added, refused = self._add_policies(org_id, listed.items, ORGANIZATIONS_POLICY, HOLDS_ORGANIZATIONS_POLICY)
            emitted += added
            skipped += refused
        why = f"enabled policy type(s) this plugin does not model: {', '.join(unknown)}" if unknown else ""
        if unknown:
            self.notice("warn", "ORG_POLICY_TYPE_UNMODELLED", why, policy_types=unknown)
        listing = self.surface(
            _aggregate(reads, why=why),
            RELATION_ORGANIZATION_POLICIES,
            HOLDS_ORGANIZATIONS_POLICY,
            ORGANIZATION,
            org_id,
            count=emitted,
        )
        self.withdraw_if_skipped(listing, skipped)

    def _add_policies(
        self, org_id: str, policies: list[dict[str, Any]], entity_type: str, holds_edge: str
    ) -> tuple[int, int]:
        """Policy nodes, their containment edge (customer-managed only), their attachments and their
        bodies. Returns (customer-managed policies emitted, customer-managed policies refused)."""
        emitted = skipped = 0
        for policy in sorted(policies, key=lambda p: str(p.get("Arn") or "")):
            policy_id = str(policy.get("Id") or "")
            arn = str(policy.get("Arn") or "")
            if not policy_id or not arn:
                continue
            aws_managed = policy.get("AwsManaged")
            # Containment only for a policy AWS reports as customer-managed: an AWS-managed policy
            # (or one whose flag is missing) is never claimed as this organization's child.
            customer_managed = aws_managed is False
            policy_type = str(policy.get("Type") or "") if entity_type == ORGANIZATIONS_POLICY else _SCP_FILTER
            name = str(policy.get("Name") or policy_id)
            fields: dict[str, Any] = {
                "name": name,
                "policy_arn": arn,
                "policy_id": policy_id,
                "description": str(policy.get("Description") or "")[:512],
                "aws_managed": aws_managed if isinstance(aws_managed, bool) else None,
                # An AWS-managed policy cannot be tagged; asking is a wasted, rate-limited call.
                "tags": {} if aws_managed is True else self.tags_of(policy_id),
            }
            if entity_type == ORGANIZATIONS_POLICY:
                fields["policy_type"] = policy_type
            if not self.add_node(entity_type, arn, name, fields):
                skipped += 1 if customer_managed else 0
                continue
            if customer_managed:
                emitted += 1
                self.add_edge(holds_edge, ORGANIZATION, org_id, entity_type, arn)
            targets = self.read("list_targets_for_policy", "Targets", PolicyId=policy_id)
            for target in targets.items:
                target_id = str(target.get("TargetId") or "")
                kind = str(target.get("Type") or "")
                if kind == "ROOT":
                    self.add_edge(ATTACHED_TO_TARGET, entity_type, arn, ORGANIZATION, org_id)
                elif kind == "ORGANIZATIONAL_UNIT" and target_id:
                    self.add_edge(ATTACHED_TO_TARGET, entity_type, arn, ORGANIZATIONAL_UNIT, target_id)
                elif kind == "ACCOUNT" and target_id:
                    self.add_edge(ATTACHED_TO_TARGET, entity_type, arn, ACCOUNT, target_id)
            self._read_body(entity_type, arn, policy_id, name, policy_type)
        return emitted, skipped

    def _describe_policy(self, policy_id: str) -> tuple[_Read, str | None]:
        """``DescribePolicy`` (not paginated): ``(the read, the document)``; the document is None
        when the call failed."""
        first = _now()
        try:
            response = self.client.describe_policy(PolicyId=policy_id)
        except ClientError as exc:
            code = error_code(exc) or "ClientError"
            why = f"{code}: describe_policy failed"
            denied = code in _DENIED_CODES
            self.notice("info" if denied else "warn", "ORG_LISTING_FAILED", why, operation="describe_policy", error_code=code)
            return _Read([], first, _now(), complete=False, authorized=False if denied else None, why=why, code=code), None
        except BotoCoreError as exc:
            why = f"{type(exc).__name__}: describe_policy failed"
            self.notice("warn", "ORG_LISTING_FAILED", why, operation="describe_policy")
            return _Read([], first, _now(), complete=False, authorized=None, why=why), None
        content = (response.get("Policy") or {}).get("Content")
        return _Read([], first, _now()), content if isinstance(content, str) else None

    def _read_body(self, entity_type: str, arn: str, policy_id: str, policy_name: str, policy_type: str) -> None:
        """A policy's contained units, and one surface per containment edge its model declares.

        SCP/RCP: statements (``DECLARES_STATEMENT``). Tag policy: one rule per key
        (``DECLARES_TAG_RULE``). An edge type the policy's type cannot carry is recorded complete and
        empty, so every observed parent has a surface for every containment edge its model declares
        (``req-aws-core-contained-type-triple-1``). Declarative and other types: no body is read
        (``req-aws-core-organizations-completeness-12``); they carry neither statements nor rules.
        """
        declared = CONTAINMENT_SURFACES[entity_type]
        reads_statements = policy_type in STATEMENT_POLICY_TYPES
        reads_rules = policy_type in TAG_RULE_POLICY_TYPES
        described: _Read | None = None
        document: str | None = None
        if reads_statements or reads_rules:
            described, document = self._describe_policy(policy_id)
        if DECLARES_STATEMENT in declared:
            if reads_statements and described is not None:
                self._add_statements(entity_type, arn, policy_name, described, document)
            else:
                self._empty_surface(RELATION_POLICY_STATEMENTS, DECLARES_STATEMENT, entity_type, arn, policy_type)
        if DECLARES_TAG_RULE in declared:
            if reads_rules and described is not None:
                self._add_tag_rules(entity_type, arn, policy_name, described, document)
            else:
                self._empty_surface(RELATION_POLICY_TAG_RULES, DECLARES_TAG_RULE, entity_type, arn, policy_type)

    def _empty_surface(self, relation: str, edge_type: str, entity_type: str, arn: str, policy_type: str) -> None:
        """A complete, empty surface for a containment edge the policy's type cannot carry (a tag
        policy has no statements, an RCP no tag rules, a declarative policy neither)."""
        now = _now()
        listing = self.surface(_Read([], now, now), relation, edge_type, entity_type, arn)
        listing.reasons["enumeration_basis"] = f"type_cannot_carry: a {policy_type or 'policy'} holds no units of this kind"

    def _unreadable(self, described: _Read, problem: str, arn: str) -> _Read:
        """The read behind a body surface that cannot be called complete: the call failed, or the
        document did not parse (``req-aws-core-organizations-completeness-10``)."""
        if not described.complete:
            return described
        self.notice("warn", "ORG_POLICY_UNPARSEABLE", f"{arn}: {problem}", policy_arn=arn)
        return _Read([], described.first, described.last, complete=False, authorized=True, why=f"unparseable: {problem}")

    def _add_statements(
        self, entity_type: str, arn: str, policy_name: str, described: _Read, document: str | None
    ) -> None:
        """Statement nodes of one SCP or RCP (``req-aws-core-organizations-completeness-7``..``-10``)."""
        try:
            if not described.complete:
                raise PolicyDocumentError(described.why)
            if document is None:
                raise PolicyDocumentError("DescribePolicy returned no Content")
            parsed = parse_statements(document)
        except PolicyDocumentError as exc:
            self.surface(
                self._unreadable(described, str(exc), arn), RELATION_POLICY_STATEMENTS, DECLARES_STATEMENT, entity_type, arn
            )
            return
        if parsed.duplicate_sids:
            self.notice(
                "warn",
                "DUPLICATE_SID",
                f"{arn} repeats Sid(s) {', '.join(parsed.duplicate_sids)}; those statements are keyed dupsid:<hash>.",
                policy_arn=arn,
                sids=parsed.duplicate_sids,
            )
        skipped = 0
        for key in sorted(parsed.units):
            unit = parsed.units[key]
            natural = statement_natural_key(arn, key)
            label = f"{policy_name}: {unit.sid or key[: key.index(':') + 13]}"[:255]
            fields: dict[str, Any] = {
                "name": label,
                "policy_arn": arn,
                "statement_key": key,
                "sid": unit.sid,
                **unit.fields,
                "positions": list(unit.positions),
                "occurrences": unit.occurrences,
                "content_sha256": unit.content_sha256,
                # A statement is not an AWS resource (lane `none`, tag_lanes.json).
                "tags": {},
            }
            if not self.add_node(POLICY_STATEMENT, natural, label, fields):
                skipped += 1
                continue
            self.add_edge(DECLARES_STATEMENT, entity_type, arn, POLICY_STATEMENT, natural)
        listing = self.surface(
            _Read([], described.first, described.last),
            RELATION_POLICY_STATEMENTS,
            DECLARES_STATEMENT,
            entity_type,
            arn,
            count=len(parsed.units),
        )
        self.withdraw_if_skipped(listing, skipped)

    def _add_tag_rules(
        self, entity_type: str, arn: str, policy_name: str, described: _Read, document: str | None
    ) -> None:
        """One rule node per tag key of a tag policy (``req-aws-core-organizations-completeness-11``)."""
        try:
            if not described.complete:
                raise PolicyDocumentError(described.why)
            if document is None:
                raise PolicyDocumentError("DescribePolicy returned no Content")
            rules = parse_tag_rules(document)
        except PolicyDocumentError as exc:
            self.surface(
                self._unreadable(described, str(exc), arn), RELATION_POLICY_TAG_RULES, DECLARES_TAG_RULE, entity_type, arn
            )
            return
        skipped = 0
        for lower in sorted(rules):
            rule = rules[lower]
            natural = tag_rule_natural_key(arn, lower)
            label = f"{policy_name}: {rule.tag_key}"[:255]
            fields: dict[str, Any] = {
                "name": label,
                "policy_arn": arn,
                "tag_key_lower": lower,
                "tag_key": rule.tag_key,
                "allowed_values": rule.allowed_values,
                "enforced_for": rule.enforced_for,
                "inheritance_operators": rule.inheritance_operators,
                # A rule is not an AWS resource (lane `none`, tag_lanes.json).
                "tags": {},
            }
            if not self.add_node(TAG_POLICY_RULE, natural, label, fields):
                skipped += 1
                continue
            self.add_edge(DECLARES_TAG_RULE, entity_type, arn, TAG_POLICY_RULE, natural)
        listing = self.surface(
            _Read([], described.first, described.last),
            RELATION_POLICY_TAG_RULES,
            DECLARES_TAG_RULE,
            entity_type,
            arn,
            count=len(rules),
        )
        self.withdraw_if_skipped(listing, skipped)


def _enabled_policy_types(root: dict[str, Any]) -> list[str]:
    """``Root.PolicyTypes`` entries whose ``Status`` is ``ENABLED``, sorted
    (``req-aws-core-organizations-completeness-2``). ``PENDING_ENABLE`` and ``PENDING_DISABLE``
    are not enabled. Every enabled type is returned, including one outside the pinned enum, so
    the policy reader can refuse to call its surface complete; collect keeps only the enum's
    values in the organization's field."""
    types = {str(t.get("Type") or "") for t in (root.get("PolicyTypes") or []) if str(t.get("Status") or "") == _ENABLED}
    return sorted(types - {""})


def delegation_key(organization_id: str, account_id: str, service_principal: str) -> str:
    """The delegation's natural key, ``(organization_id, account_id, service_principal)``, in one string."""
    return f"{organization_id}:{account_id}:{service_principal}"


def statement_natural_key(policy_arn: str, statement_key: str) -> str:
    """The statement's natural key, ``(policy_arn, statement_key)``, in one string."""
    return f"{policy_arn}#{statement_key}"


def tag_rule_natural_key(policy_arn: str, tag_key_lower: str) -> str:
    """The tag-policy rule's natural key, ``(policy_arn, tag_key_lower)``, in one string."""
    return f"{policy_arn}#{tag_key_lower}"


#: The two Organizations policy ARN forms, exactly (partition, empty region, account or ``aws``):
#: customer-managed ``arn:<p>:organizations::<12 digits>:policy/<o-id>/<type>/<p-id>`` and
#: AWS-managed ``arn:<p>:organizations::aws:policy/<type>/<p-id>``. Anything else is neither, and a
#: falsifier refuses it rather than probe on a guessed scope.
_CUSTOMER_POLICY_ARN = re.compile(
    r"^arn:aws(?:-us-gov|-cn)?:organizations::[0-9]{12}:policy/(o-[a-z0-9]{10,32})/[a-z0-9_]+/p-[0-9a-zA-Z_]{8,128}$"
)
_AWS_MANAGED_POLICY_ARN = re.compile(r"^arn:aws(?:-us-gov|-cn)?:organizations::aws:policy/[a-z0-9_]+/p-[0-9a-zA-Z_]{8,128}$")


def organization_id_of_policy_arn(arn: str) -> str:
    """The organization id in a customer-managed policy ARN of the exact form, or ``""``."""
    match = _CUSTOMER_POLICY_ARN.match(str(arn or ""))
    return match.group(1) if match else ""


def is_aws_managed_policy_arn(arn: str) -> bool:
    """True only for the exact AWS-managed policy ARN form."""
    return _AWS_MANAGED_POLICY_ARN.match(str(arn or "")) is not None


def policy_id_of_arn(arn: str) -> str:
    """The ``p-…`` id that ends a policy ARN, or ``""``."""
    last = str(arn or "").rsplit("/", 1)[-1]
    return last if last.startswith("p-") else ""


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        value = value if value.tzinfo else value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value or "")


def collect_organization(
    client: Any, dimensions: dict[str, str], *, sensitivity: dict[str, dict[str, Any]] | None = None
) -> OrganizationTree:
    """Read the Organizations tree with ``client``; never raises for an AWS failure.

    ``dimensions`` are stamped on every node and edge (the run's own
    ``{"cloud", "aws_account", "aws_region"}``, region ``global``). ``sensitivity`` replaces
    ``reader_sensitivity()`` (tests only).
    """
    return _Reader(client, dimensions, sensitivity).collect()


__all__ = [
    "ACCOUNT",
    "ACCOUNT_NOT_REGISTERED",
    "READER",
    "CONTAINMENT_SURFACES",
    "DECLARES_STATEMENT",
    "DECLARES_TAG_RULE",
    "DELEGATED_ADMINISTRATION",
    "DELEGATES_TO_ACCOUNT",
    "HOLDS_DELEGATION",
    "HOLDS_ORGANIZATIONS_POLICY",
    "HOLDS_SERVICE_CONTROL_POLICY",
    "ORGANIZATIONS_POLICY",
    "PAGINATED_OPERATIONS",
    "POLICY_STATEMENT",
    "TAG_POLICY_RULE",
    "delegation_key",
    "is_aws_managed_policy_arn",
    "organization_id_of_policy_arn",
    "policy_id_of_arn",
    "reader_sensitivity",
    "sensitivity_refusal",
    "statement_natural_key",
    "tag_rule_natural_key",
    "ENROLLS_ACCOUNT",
    "INACTIVE_ACCOUNT_STATES",
    "ORGANIZATION",
    "ORGANIZATIONAL_UNIT",
    "PARTITIONED_INTO_OU",
    "SERVICE_CONTROL_POLICY",
    "Listing",
    "Notice",
    "OrganizationTree",
    "account_state",
    "collect_organization",
    "error_code",
    "organization_id_of_account_arn",
    "organizations_client",
    "partition_of_arn",
]
