"""aws-counts — the count tiles on the /aws dashboard (req-aws-core-page-dashboard).

Spec: specs/spec-aws-core-v0.md (req-aws-core-panel-counts).

Each tile is a number the grid can answer about the AWS estate: accounts, OUs, VPCs, the internet
gateways that are its public front doors, internet-facing load balancers, buckets whose public access
is not blocked, firewalls, transit gateway attachments, KMS keys, service control policies, and the
accounts inside each compliance boundary. A panel instance lists the tiles it shows in
``config.tiles``; with none listed it shows the dashboard set (``DEFAULT_KEYS``, the first eleven, in
catalogue order). The later tiles serve the /aws/scps, /aws/security-groups and /aws/network pages and
the IAM column on /aws, and appear only where an instance names them.

Two security-group tiles read the rules inside each group's raw ``configuration`` (IpPermissions,
IpPermissionsEgress). Gryphon cannot walk into a JSON array (``req-grid-traversal-lang-filters-jsonpath``
is Proposed), but its ``=~`` regex reaches the array as Postgres renders it as text, so a group can be
flagged when ANY of its rules carries ``0.0.0.0/0`` / ``::/0`` or ``IpProtocol: -1``. That is a
per-group flag, not a per-rule one: it cannot say that the open range and the all-protocol rule are the
same rule. Per-rule nodes are aws-core-tap#64.

Reads go through Gryphon (``execute_gryphon_raw``, gated on ``grid.read``); folding the envelopes into
tiles is pure, so the tests need no grid. A tile whose read fails says so in the tile rather than
showing 0: an error is never rendered as an empty estate. A tile whose nodes are all design nodes
(dcom=design) is marked design, so a planned estate is never read as a built one.

Boundary membership follows the organisation tree: an account is inside a boundary when it, or an OU
it sits under at any depth (NESTED_UNDER_PARENT), is SCOPED_TO_COMPLIANCE_BOUNDARY that boundary.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest

    from tap_web.models import Panel

logger = logging.getLogger(__name__)

NESTED = "NESTED_UNDER_PARENT__aws_core"
SCOPED = "SCOPED_TO_COMPLIANCE_BOUNDARY__compliance_core"
ACCOUNT = "aws_core__aws_account"
SG ="aws_core__aws_security_group"
SCP = "aws_core__aws_service_control_policy"
STATEMENT = "aws_core__aws_policy_statement"
ROLE = "aws_core__aws_iam_role"

#: A rule open to the whole internet, as Postgres prints a rule list as text: the quoted CIDR value.
OPEN_TO_INTERNET_RE = r'"(0\.0\.0\.0/0|::/0)"'
#: A rule that allows every protocol (and so every port).
ALL_PROTOCOLS_RE = '"IpProtocol": "-1"'
#: The statement belongs to a service control policy (its policy ARN names the policy type).
SCP_ARN_MARK = "/service_control_policy/"


def _nodes(etype: str) -> str:
    return f"MATCH (n:{etype}) RETURN n"


def gryphon_literal(value: str) -> str:
    """A Gryphon string literal for ``value`` (ESCAPED_STRING: JSON's quoting)."""
    return json.dumps(value)


def _where(etype: str, predicate: str) -> str:
    return f"MATCH (n:{etype}) WHERE {predicate} RETURN n"


@dataclass(frozen=True)
class TileDef:
    key: str
    label: str
    note: str
    query: str
    #: Keeps the nodes the tile counts; None counts every node the query returns.
    keep: Callable[[dict[str, Any]], bool] | None = None
    #: A count above zero that deserves a second look (a public front door, public exposure).
    attention: bool = False


def _scheme_public(n: dict[str, Any]) -> bool:
    return str((n.get("data") or {}).get("scheme") or "") == "internet-facing"


def _bucket_public(n: dict[str, Any]) -> bool:
    return (n.get("data") or {}).get("public_access_blocked") is False


CATALOGUE: tuple[TileDef, ...] = (
    TileDef("accounts", "AWS accounts", "Every aws_core account node on the grid.", _nodes(ACCOUNT)),
    TileDef("organizational_units", "Organizational units", "Every OU in the AWS Organizations tree.",
            _nodes("aws_core__aws_organizational_unit")),
    TileDef("service_control_policies", "Service control policies", "Every SCP, attached or not.",
            _nodes("aws_core__aws_service_control_policy")),
    TileDef("vpcs", "VPCs", "Every VPC.", _nodes("aws_core__aws_vpc")),
    TileDef("internet_gateways", "Internet gateways", "Each internet gateway is a path to and from the internet: a public "
            "front door or an egress exit. Every one should be a known, documented exception.",
            _nodes("aws_core__aws_internet_gateway"), attention=True),
    TileDef("internet_facing_load_balancers", "Internet-facing load balancers",
            "Classic, network and application load balancers whose scheme is internet-facing.",
            'MATCH (n) WHERE n.entity_type IN ["aws_core__aws_elb", "aws_core__aws_alb"] RETURN n',
            keep=_scheme_public, attention=True),
    TileDef("public_buckets", "Buckets not blocking public access",
            "S3 buckets whose public access block is off.", _nodes("aws_core__aws_s3_bucket"),
            keep=_bucket_public, attention=True),
    TileDef("network_firewalls", "Network firewalls", "AWS Network Firewall firewalls.",
            _nodes("aws_core__aws_network_firewall")),
    TileDef("transit_gateways", "Transit gateways", "Transit gateways (one per environment is the usual design).",
            _nodes("aws_core__aws_transit_gateway")),
    TileDef("transit_gateway_attachments", "Transit gateway attachments",
            "VPC, VPN, Direct Connect, Connect and peering attachments to a transit gateway.",
            _nodes("aws_core__aws_transit_gateway_attachment")),
    TileDef("kms_keys", "KMS keys", "Every KMS key.", _nodes("aws_core__aws_kms_key")),
    # /aws/scps
    TileDef("customer_scps", "Customer SCPs", "Service control policies the organization wrote (not AWS-managed).",
            _where(SCP, "n.data.aws_managed = false")),
    TileDef("scp_statements", "SCP statements", "Every statement a service control policy declares.",
            _where(STATEMENT, f"n.data.policy_arn CONTAINS {gryphon_literal(SCP_ARN_MARK)}")),
    TileDef("scp_deny_statements", "Deny statements", "SCP statements whose effect is Deny: the organization's guardrails.",
            _where(STATEMENT, f'n.data.effect = "Deny" AND n.data.policy_arn CONTAINS {gryphon_literal(SCP_ARN_MARK)}')),
    # /aws/security-groups
    TileDef("security_groups", "Security groups", "Every security group.", _nodes(SG)),
    TileDef("sg_ingress_open", "Open to the internet (ingress)",
            "Security groups with at least one inbound rule from 0.0.0.0/0 or ::/0.",
            _where(SG, f"n.data.configuration.IpPermissions =~ {gryphon_literal(OPEN_TO_INTERNET_RE)}"), attention=True),
    TileDef("sg_ingress_all_protocols", "All-protocol ingress",
            "Security groups with at least one inbound rule for every protocol (IpProtocol -1), from any source.",
            _where(SG, f"n.data.configuration.IpPermissions =~ {gryphon_literal(ALL_PROTOCOLS_RE)}"), attention=True),
    TileDef("sg_egress_open", "Open to the internet (egress)",
            "Security groups with at least one outbound rule to 0.0.0.0/0 or ::/0. AWS gives every new group one.",
            _where(SG, f"n.data.configuration.IpPermissionsEgress =~ {gryphon_literal(OPEN_TO_INTERNET_RE)}")),
    # /aws/network
    TileDef("default_vpcs", "Default VPCs", "VPCs AWS created by default (is_default). Public subnets and an internet "
            "gateway come with them.", _where("aws_core__aws_vpc", "n.data.is_default = true"), attention=True),
    TileDef("public_subnets", "Public subnets", "Subnets that route to an internet gateway.",
            _where("aws_core__aws_subnet", "n.data.public = true"), attention=True),
    # /aws IAM column
    TileDef("roles_trust_services", "Roles AWS services assume", "IAM roles whose trust policy names an AWS service.",
            _where(ROLE, 'n.data.trusted_services =~ "[a-z]"')),
    TileDef("roles_trust_accounts", "Roles other accounts assume", "IAM roles whose trust policy names an AWS account.",
            _where(ROLE, 'n.data.trusted_account_ids =~ "[0-9]"')),
    TileDef("roles_trust_anyone", "Roles anyone can assume", "IAM roles whose trust policy names the wildcard principal (*).",
            _where(ROLE, "n.data.trusts_wildcard_principal = true"), attention=True),
    TileDef("users_without_mfa", "IAM users without MFA", "IAM users observed with no MFA device. A user whose MFA "
            "was not read is not counted.", _where("aws_core__aws_iam_user", "n.data.mfa_enabled = false"), attention=True),
)
BY_KEY = {t.key: t for t in CATALOGUE}
#: What an instance with no ``config.tiles`` shows: the /aws dashboard set.
DEFAULT_KEYS: tuple[str, ...] = (
    "accounts", "organizational_units", "service_control_policies", "vpcs", "internet_gateways",
    "internet_facing_load_balancers", "public_buckets", "network_firewalls", "transit_gateways",
    "transit_gateway_attachments", "kms_keys",
)

TREE_QUERY = f"MATCH (c)-[:{NESTED}]->(p) RETURN c.entity_id AS child, p.entity_id AS parent"
BOUNDARY_QUERY = "MATCH (b:compliance_core__compliance_boundary) RETURN b"
SCOPE_QUERY = f"MATCH (x)-[:{SCOPED}]->(b) RETURN x.entity_id AS member, b.entity_id AS boundary, b.name AS name"


def fold_tile(tile: TileDef, envelope: dict[str, Any]) -> dict[str, Any]:
    """One tile from its read: the count, whether every counted node is a design node, and its tone."""
    nodes = list(envelope.get("nodes") or [])
    if tile.keep is not None:
        nodes = [n for n in nodes if tile.keep(n)]
    design = bool(nodes) and all((n.get("dimensions") or {}).get("dcom") == "design" for n in nodes)
    tone = "attention" if tile.attention and nodes else ""
    return {"key": tile.key, "label": tile.label, "note": tile.note, "value": len(nodes), "design": design,
            "tone": tone, "error": ""}


def boundary_tiles(accounts: list[dict[str, Any]], tree_rows: list[dict[str, Any]],
                   scope_rows: list[dict[str, Any]], boundaries: list[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """Accounts inside each boundary: the account, or any OU above it, is scoped to the boundary.

    Every boundary node in ``boundaries`` gets a tile, so a boundary nothing is scoped to shows 0
    rather than disappearing."""
    parent = {r["child"]: r["parent"] for r in tree_rows if r.get("child") and r.get("parent")}
    scoped: dict[str, set[str]] = {}
    names: dict[str, str] = {b["entity_id"]: b.get("name") or b["entity_id"] for b in boundaries}
    for r in scope_rows:
        if r.get("member") and r.get("boundary"):
            scoped.setdefault(r["member"], set()).add(r["boundary"])
            names[r["boundary"]] = r.get("name") or r["boundary"]
    inside: dict[str, set[str]] = {b: set() for b in names}
    for a in accounts:
        seen: set[str] = set()
        node: str | None = a["entity_id"]
        while node and node not in seen:
            seen.add(node)
            for b in scoped.get(node, ()):
                inside[b].add(a["entity_id"])
            node = parent.get(node)
    by_id = {a["entity_id"]: a for a in accounts}
    tiles = []
    for b, members in sorted(inside.items(), key=lambda kv: names[kv[0]]):
        counted = [by_id[m] for m in members]
        design = bool(counted) and all((n.get("dimensions") or {}).get("dcom") == "design" for n in counted)
        tiles.append({"key": f"boundary:{b}", "label": f"Accounts in {names[b]}",
                      "note": "Accounts scoped to the boundary directly or through an OU above them.",
                      "value": len(members), "design": design, "tone": "", "error": ""})
    return tiles


def _error_tile(key: str, label: str) -> dict[str, Any]:
    return {"key": key, "label": label, "note": "", "value": None, "design": False, "tone": "error",
            "error": "The read failed; see the server log ([a3c7])."}


class AwsCountsPanelType:
    """Count tiles over the AWS estate on the grid."""

    slug: ClassVar[str] = "aws-counts"
    label: ClassVar[str] = "AWS counts"
    view: ClassVar[str] = "aws_core/panels/counts.html"
    css: ClassVar[list[str]] = ["aws_core/css/counts.css"]
    js: ClassVar[list[str]] = []
    editor_view: ClassVar[str] = ""
    config_defaults: ClassVar[dict[str, Any]] = {"boundaries": True}

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        from tap_grid.gryphon.executor import execute_gryphon_raw

        config = {**cls.config_defaults, **(panel.config or {})}
        keys = [k for k in (config.get("tiles") or DEFAULT_KEYS) if k in BY_KEY]
        tiles: list[dict[str, Any]] = []
        accounts: list[dict[str, Any]] = []
        for key in keys:
            tile = BY_KEY[key]
            try:
                envelope = execute_gryphon_raw(tile.query, {}, layer="full")
            except Exception:  # noqa: BLE001 — a failed read renders as a failed tile, never as 0
                logger.exception("[a3c7] aws counts: %s read failed for panel %s", key, panel.entity_id)
                tiles.append(_error_tile(key, tile.label))
                continue
            if key == "accounts":
                accounts = list(envelope.get("nodes") or [])
            tiles.append(fold_tile(tile, envelope))
        if config.get("boundaries"):
            try:
                if not accounts:
                    accounts = list(execute_gryphon_raw(BY_KEY["accounts"].query, {}, layer="full").get("nodes") or [])
                tree = execute_gryphon_raw(TREE_QUERY, {}, layer="full").get("rows") or []
                scope = execute_gryphon_raw(SCOPE_QUERY, {}, layer="full").get("rows") or []
                try:
                    boundaries = execute_gryphon_raw(BOUNDARY_QUERY, {}, layer="full").get("nodes") or []
                except Exception:  # noqa: BLE001 — a grid without compliance_core has no boundary type
                    logger.info("aws counts: no compliance boundary type on this grid; tiles follow scope edges only")
                    boundaries = []
                tiles += boundary_tiles(accounts, tree, scope, boundaries)
            except Exception:  # noqa: BLE001
                logger.exception("[a3c7] aws counts: boundary read failed for panel %s", panel.entity_id)
                tiles.append(_error_tile("boundaries", "Accounts in each boundary"))
        return {"tiles": tiles, "title": config.get("title") or "", "intro": config.get("intro") or ""}
