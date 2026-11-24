"""VPC Network Access Analyzer findings and Reachability Analyzer paths as compound edges (aws-core-tap#212, #248).

Spec: specs/spec-aws-core-collector-v0.md (``req-aws-collector-network-analyzer``), on core's compound edges as
shipped (``req-grid-edge-compound``) and following the first one, the Amazon Inspector reachability finding
(``inspector.py``, ``req-aws-landing-zone-inspector-reachability``).

Two kinds, each with its own middle node:

- **A Network Access Analyzer finding** (``aws_ec2_network_access_scope_finding``, ruled 2026-11-09 on #212): one node
  per finding ``GetNetworkInsightsAccessScopeAnalysisFindings`` returns for a succeeded analysis.
  ``REPORTS_ACCESS_SCOPE_FINDING`` runs to it from its analysis. ``ACCESS_SCOPE_FINDING_SOURCE`` runs from the
  path's first component, ``ACCESS_SCOPE_FINDING_DESTINATION`` to its last, and ``TRAVERSES_COMPONENT`` to each
  component between them.
- **A Reachability Analyzer analysis** (``aws_ec2_network_insights_analysis``): the analysis is itself the middle
  node, as the Inspector finding is. It has an identity of its own (its ARN), a time (``StartDate``), and, when AWS
  found a path (``NetworkPathFound``), a sender, a receiver and the hops between them in
  ``ForwardPathComponents``. A separate path node would carry no fact the analysis does not, under an identity
  borrowed from it. ``REACHABILITY_ANALYSIS_SOURCE`` runs from the forward path's first component,
  ``REACHABILITY_ANALYSIS_DESTINATION`` to its last, and ``TRAVERSES_COMPONENT`` to each one between. An analysis
  that found no path, or has not finished, has no role edges.

**Which component is which.** The components are put in ``SequenceNumber`` order. AWS documents neither that order
nor that the first and last components are the path's ends (read: botocore ``PathComponent``; the Network Access
Analyzer and Reachability Analyzer guides, 2026-11-24), so both are inferences to check against a live finding.
A component's type is read from its ``Component.Id``'s resource-id prefix, or from its ``Component.Arn`` through
``arn_resolver``, never from its position. Each role accepts only the types the service's guide lists for it
(``ACCESS_SCOPE_ENDS``, ``ACCESS_SCOPE_PATH``, ``REACHABILITY_ENDS``, ``REACHABILITY_PATH``). A component that
matches no tabled type, or a type its role does not accept, gets no edge and is listed in
``unmatched_components`` with the reason.

**Manifest edge rules.** Each item carries one slot per (role, target type): ``_source_<token>`` and
``_destination_<token>``, a list of at most one key, and ``_hops_<token>``, a list of ``{key, properties: {step}}``,
the step being the component's 0-based position in ``SequenceNumber`` order. ``<token>`` is the target type without
``aws_core__aws_``. The manifest declares one edge rule per slot; ``tests/test_network_insights.py`` holds the
manifest to the tables here.

Nothing here was observed against a live account: shapes are read from botocore's ``ec2`` model, and the tests drive
the readers through ``botocore.stub.Stubber``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from .authority import COMPLETE, PARTIAL, with_edge_reads

ACCESS_SCOPE_FINDING = "aws_core__aws_ec2_network_access_scope_finding"
ACCESS_SCOPE_ANALYSIS = "aws_core__aws_ec2_network_insights_access_scope_analysis"
REACHABILITY_ANALYSIS = "aws_core__aws_ec2_network_insights_analysis"

REPORTS_ACCESS_SCOPE_FINDING = "REPORTS_ACCESS_SCOPE_FINDING__aws_core"
ACCESS_SCOPE_FINDING_SOURCE = "ACCESS_SCOPE_FINDING_SOURCE__aws_core"
ACCESS_SCOPE_FINDING_DESTINATION = "ACCESS_SCOPE_FINDING_DESTINATION__aws_core"
REACHABILITY_ANALYSIS_SOURCE = "REACHABILITY_ANALYSIS_SOURCE__aws_core"
REACHABILITY_ANALYSIS_DESTINATION = "REACHABILITY_ANALYSIS_DESTINATION__aws_core"
TRAVERSES_COMPONENT = "TRAVERSES_COMPONENT__aws_core"

EC2_INSTANCE = "aws_core__aws_ec2_instance"
NETWORK_INTERFACE = "aws_core__aws_ec2_network_interface"
INTERNET_GATEWAY = "aws_core__aws_internet_gateway"
NAT_GATEWAY = "aws_core__aws_nat_gateway"
NETWORK_ACL = "aws_core__aws_network_acl"
ROUTE_TABLE = "aws_core__aws_route_table"
SECURITY_GROUP = "aws_core__aws_security_group"
SUBNET = "aws_core__aws_subnet"
VPC = "aws_core__aws_vpc"
VPC_ENDPOINT = "aws_core__aws_vpc_endpoint"
VPC_ENDPOINT_SERVICE = "aws_core__aws_vpc_endpoint_service"
PEERING_CONNECTION = "aws_core__aws_ec2_vpc_peering_connection"
TRANSIT_GATEWAY = "aws_core__aws_transit_gateway"
TRANSIT_GATEWAY_ATTACHMENT = "aws_core__aws_transit_gateway_attachment"
TRANSIT_GATEWAY_ROUTE_TABLE = "aws_core__aws_ec2_transit_gateway_route_table"
VPN_GATEWAY = "aws_core__aws_ec2_vpn_gateway"
VPN_CONNECTION = "aws_core__aws_ec2_vpn_connection"
PREFIX_LIST = "aws_core__aws_ec2_prefix_list"
ALB = "aws_core__aws_alb"
TARGET_GROUP = "aws_core__aws_target_group"
NETWORK_FIREWALL = "aws_core__aws_network_firewall"

#: AWS resource-id prefixes and the aws_core type keyed by that id (each type's manifest ``natural_key`` is the id).
#: Matched longest first, so ``vpce-svc-`` wins over ``vpce-`` and ``tgw-attach-`` over ``tgw-``. A load balancer,
#: target group, network firewall or prefix list is named by its ARN instead (:func:`classify_component`).
ID_PREFIXES: dict[str, str] = {
    "i-": EC2_INSTANCE,
    "eni-": NETWORK_INTERFACE,
    "igw-": INTERNET_GATEWAY,
    "nat-": NAT_GATEWAY,
    "acl-": NETWORK_ACL,
    "rtb-": ROUTE_TABLE,
    "sg-": SECURITY_GROUP,
    "subnet-": SUBNET,
    "vpc-": VPC,
    "vpce-": VPC_ENDPOINT,
    "vpce-svc-": VPC_ENDPOINT_SERVICE,
    "pcx-": PEERING_CONNECTION,
    "tgw-": TRANSIT_GATEWAY,
    "tgw-attach-": TRANSIT_GATEWAY_ATTACHMENT,
    "tgw-rtb-": TRANSIT_GATEWAY_ROUTE_TABLE,
    "vgw-": VPN_GATEWAY,
    "vpn-": VPN_CONNECTION,
}
_PREFIXES_LONGEST_FIRST: tuple[tuple[str, str], ...] = tuple(sorted(ID_PREFIXES.items(), key=lambda p: -len(p[0])))

#: Network Access Analyzer: "findings for network paths that start or end at" these (how-network-access-analyzer-works,
#: read 2026-11-24). Interface, gateway and Gateway Load Balancer endpoints are all ``vpce-`` VPC endpoints.
ACCESS_SCOPE_ENDS: tuple[str, ...] = (
    INTERNET_GATEWAY,
    NETWORK_INTERFACE,
    TRANSIT_GATEWAY_ATTACHMENT,
    VPC_ENDPOINT,
    VPC_ENDPOINT_SERVICE,
    PEERING_CONNECTION,
    VPN_GATEWAY,
)
#: Network Access Analyzer: "the following resource types are supported as resources on network paths" (same page).
#: Of its load balancers only an Application Load Balancer is keyed by the ARN a component carries.
ACCESS_SCOPE_PATH: tuple[str, ...] = (
    INTERNET_GATEWAY,
    ALB,
    NAT_GATEWAY,
    NETWORK_ACL,
    NETWORK_FIREWALL,
    NETWORK_INTERFACE,
    ROUTE_TABLE,
    SECURITY_GROUP,
    TARGET_GROUP,
    TRANSIT_GATEWAY_ROUTE_TABLE,
    TRANSIT_GATEWAY_ATTACHMENT,
    VPC_ENDPOINT,
    VPC_ENDPOINT_SERVICE,
    PEERING_CONNECTION,
    VPN_GATEWAY,
)
#: Reachability Analyzer: "the following resource types as sources and destinations" (how-reachability-analyzer-works,
#: read 2026-11-24). An IP address destination names no node.
REACHABILITY_ENDS: tuple[str, ...] = (
    EC2_INSTANCE,
    INTERNET_GATEWAY,
    NETWORK_INTERFACE,
    TRANSIT_GATEWAY,
    TRANSIT_GATEWAY_ATTACHMENT,
    VPN_GATEWAY,
    VPC_ENDPOINT_SERVICE,
    VPC_ENDPOINT,
    PEERING_CONNECTION,
)
#: Reachability Analyzer: "the following resource types can appear in reachable paths" (same page).
REACHABILITY_PATH: tuple[str, ...] = (
    EC2_INSTANCE,
    INTERNET_GATEWAY,
    ALB,
    NAT_GATEWAY,
    NETWORK_ACL,
    NETWORK_FIREWALL,
    NETWORK_INTERFACE,
    PREFIX_LIST,
    ROUTE_TABLE,
    SECURITY_GROUP,
    SUBNET,
    TARGET_GROUP,
    TRANSIT_GATEWAY,
    TRANSIT_GATEWAY_ATTACHMENT,
    TRANSIT_GATEWAY_ROUTE_TABLE,
    VPN_GATEWAY,
    VPC_ENDPOINT_SERVICE,
    VPC_ENDPOINT,
    PEERING_CONNECTION,
    VPC,
    VPN_CONNECTION,
)
#: Every type a component can be classified as.
COMPONENT_TYPES: frozenset[str] = frozenset((*ACCESS_SCOPE_PATH, *ACCESS_SCOPE_ENDS, *REACHABILITY_PATH, *REACHABILITY_ENDS))


@dataclass(frozen=True)
class Kind:
    """One compound edge kind: its role edges and the types each role accepts."""

    source_edge: str
    destination_edge: str
    ends: tuple[str, ...]
    path: tuple[str, ...]


ACCESS_SCOPE = Kind(ACCESS_SCOPE_FINDING_SOURCE, ACCESS_SCOPE_FINDING_DESTINATION, ACCESS_SCOPE_ENDS, ACCESS_SCOPE_PATH)
REACHABILITY = Kind(REACHABILITY_ANALYSIS_SOURCE, REACHABILITY_ANALYSIS_DESTINATION, REACHABILITY_ENDS, REACHABILITY_PATH)
#: The middle-node type of each kind.
KINDS: dict[str, Kind] = {ACCESS_SCOPE_FINDING: ACCESS_SCOPE, REACHABILITY_ANALYSIS: REACHABILITY}


def token(entity_type: str) -> str:
    """The slot suffix of a target type: ``aws_core__aws_ec2_network_interface`` -> ``ec2_network_interface``."""
    return entity_type.removeprefix("aws_core__aws_")


def slot_names(kind: Kind) -> list[str]:
    """Every slot an item of ``kind`` carries, each always present (an empty list when nothing is in it)."""
    return (
        [f"_source_{token(t)}" for t in kind.ends]
        + [f"_destination_{token(t)}" for t in kind.ends]
        + [f"_hops_{token(t)}" for t in kind.path]
    )


def classify_component(component: Any) -> tuple[str, str] | None:
    """``(aws_core type, natural key)`` of one ``AnalysisComponent``: from its ``Id``'s resource-id prefix, else from its
    ``Arn`` (or an ARN-shaped ``Id``) read by ``arn_resolver``; None when neither names a tabled type."""
    from .arn_resolver import resolve_arn

    if not isinstance(component, dict):
        return None
    component_id = component.get("Id")
    if isinstance(component_id, str):
        for prefix, entity_type in _PREFIXES_LONGEST_FIRST:
            if component_id.startswith(prefix):
                return entity_type, component_id
    for value in (component.get("Arn"), component_id):
        if isinstance(value, str) and value.startswith("arn:"):
            target = resolve_arn(value)
            if target is not None and target[0] in COMPONENT_TYPES:
                return target
    return None


def ordered_components(components: Any) -> list[dict[str, Any]]:
    """The ``PathComponent`` list in ``SequenceNumber`` order; a component without one keeps its place after those with
    one (a stable sort)."""
    listed = [c for c in components or [] if isinstance(c, dict)]
    numbered = [c for c in listed if isinstance(c.get("SequenceNumber"), int) and not isinstance(c.get("SequenceNumber"), bool)]
    unnumbered = [c for c in listed if c not in numbered]
    return sorted(numbered, key=lambda c: c["SequenceNumber"]) + unnumbered


@dataclass
class Path:
    """What one path's components say: its ends, its hops, and what matched nothing."""

    source: tuple[str, str] | None = None
    destination: tuple[str, str] | None = None
    hops: list[tuple[int, str, str]] = field(default_factory=list)
    unmatched: list[dict[str, Any]] = field(default_factory=list)
    first: dict[str, Any] = field(default_factory=dict)
    last: dict[str, Any] = field(default_factory=dict)
    count: int = 0


def _unmatched(step: int, component: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"step": step, "id": component.get("Id"), "arn": component.get("Arn"), "reason": reason}


def read_path(components: Any, kind: Kind) -> Path:
    """The compound edge's pieces from a path's components: the first is the source, the last the destination, and
    every one between is a hop. A role gets an edge only for a type the kind accepts in it."""
    ordered = ordered_components(components)
    path = Path(count=len(ordered))
    if not ordered:
        return path
    path.first = dict(ordered[0].get("Component") or {})
    path.last = dict(ordered[-1].get("Component") or {})
    last = len(ordered) - 1
    for step, item in enumerate(ordered):
        component = item.get("Component") or {}
        target = classify_component(component)
        roles = (["source"] if step == 0 else []) + (["destination"] if step == last else [])
        if not roles:
            if target is None:
                path.unmatched.append(_unmatched(step, component, "no tabled aws_core type matches its id or ARN"))
            elif target[0] not in kind.path:
                path.unmatched.append(_unmatched(step, component, f"{target[0]} is not a path type the service lists"))
            else:
                path.hops.append((step, *target))
            continue
        for role in roles:
            if target is None:
                path.unmatched.append(_unmatched(step, component, f"the {role}: no tabled aws_core type matches its id or ARN"))
            elif target[0] not in kind.ends:
                path.unmatched.append(_unmatched(step, component, f"the {role}: {target[0]} is not an end the service lists"))
            elif role == "source":
                path.source = target
            else:
                path.destination = target
    return path


def slots(path: Path | None, kind: Kind) -> dict[str, list[Any]]:
    """The item slots the manifest edge rules read, every one present. ``path`` None means no role edges at all."""
    out: dict[str, list[Any]] = {name: [] for name in slot_names(kind)}
    if path is None:
        return out
    if path.source is not None:
        out[f"_source_{token(path.source[0])}"].append(path.source[1])
    if path.destination is not None:
        out[f"_destination_{token(path.destination[0])}"].append(path.destination[1])
    seen: set[tuple[str, str]] = set()
    for step, entity_type, key in path.hops:
        if (entity_type, key) in seen:  # one edge per component; the first step it is met at
            continue
        seen.add((entity_type, key))
        out[f"_hops_{token(entity_type)}"].append({"key": key, "properties": {"step": step}})
    return out


def _iso(value: Any) -> str | None:
    """A botocore timestamp as ISO 8601 UTC text (``2026-11-24T10:00:00Z``); a string is passed through; else None."""
    if isinstance(value, datetime):
        value = value if value.tzinfo else value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return value if isinstance(value, str) and value else None


def access_scope_finding_item(finding: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    """One finding as the manifest projects it: AWS's finding, plus the analysis it came from and its slots."""
    analysis_arn = str(analysis.get("NetworkInsightsAccessScopeAnalysisArn") or "")
    path = read_path(finding.get("FindingComponents"), ACCESS_SCOPE)
    item_slots = slots(path, ACCESS_SCOPE)
    return with_edge_reads(
        {
            **finding,
            "_analysis_arn": analysis_arn,
            "_analysis_start_date": _iso(analysis.get("StartDate")),
            "_analysis_end_date": _iso(analysis.get("EndDate")),
            "_component_count": path.count,
            "_source_component_id": path.first.get("Id"),
            "_source_component_arn": path.first.get("Arn"),
            "_destination_component_id": path.last.get("Id"),
            "_destination_component_arn": path.last.get("Arn"),
            "_unmatched_components": path.unmatched,
            **item_slots,
        },
        # Every slot is read from the finding this item is: complete.
        {"_analysis_arn": COMPLETE, **dict.fromkeys(item_slots, COMPLETE)},
    )


def reachability_analysis_item(analysis: dict[str, Any]) -> dict[str, Any]:
    """One Reachability Analyzer analysis as the manifest projects it: AWS's analysis plus its slots. Role edges only
    when AWS says it found a path; a slot reads complete only once the analysis has succeeded, since a running or
    failed analysis has not said what its path is."""
    found = analysis.get("Status") == "succeeded" and analysis.get("NetworkPathFound") is True
    path = read_path(analysis.get("ForwardPathComponents"), REACHABILITY) if found else None
    item_slots = slots(path, REACHABILITY)
    read = COMPLETE if analysis.get("Status") == "succeeded" else PARTIAL
    return with_edge_reads(
        {**analysis, "_unmatched_components": path.unmatched if path is not None else [], **item_slots},
        dict.fromkeys(item_slots, read),
    )


def ec2_network_access_scope_findings_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Network Access Analyzer findings (regional): ``DescribeNetworkInsightsAccessScopeAnalyses`` names the
    analyses, and ``GetNetworkInsightsAccessScopeAnalysisFindings`` is read to its end for each one that succeeded and
    does not say it found nothing (``FindingsFound`` ``false``). An analysis whose findings could not all be read
    contributes none of them, so a cut read never looks whole; the reader raises once the rest are yielded."""
    from .customfns import _pages, _undescribed

    client = client_for("ec2")
    failed: list[str] = []
    for page in _pages(client, "describe_network_insights_access_scope_analyses"):
        for analysis in page.get("NetworkInsightsAccessScopeAnalyses") or []:
            if not isinstance(analysis, dict):
                continue
            analysis_id = analysis.get("NetworkInsightsAccessScopeAnalysisId")
            if not analysis_id or not analysis.get("NetworkInsightsAccessScopeAnalysisArn"):
                continue
            if analysis.get("Status") != "succeeded" or analysis.get("FindingsFound") == "false":
                continue
            try:
                findings = [
                    finding
                    for found in _pages(
                        client,
                        "get_network_insights_access_scope_analysis_findings",
                        NetworkInsightsAccessScopeAnalysisId=analysis_id,
                    )
                    for finding in found.get("AnalysisFindings") or []
                    if isinstance(finding, dict) and finding.get("FindingId")
                ]
            except (BotoCoreError, ClientError):
                failed.append(str(analysis_id))
                continue
            for finding in findings:
                yield access_scope_finding_item(finding, analysis)
    if failed:
        raise _undescribed("Network Access Analyzer analyses' findings", failed)


def ec2_network_insights_analyses_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Reachability Analyzer analyses (regional) with ``DescribeNetworkInsightsAnalyses``, each with the
    role and path slots of the compound edge it is the middle node of."""
    from .customfns import _pages

    client = client_for("ec2")
    for page in _pages(client, "describe_network_insights_analyses"):
        for analysis in page.get("NetworkInsightsAnalyses") or []:
            if isinstance(analysis, dict):
                yield reachability_analysis_item(analysis)


#: Manifest custom_fn name -> callable (registered by ``customfns.build_custom_fn_registry``).
NETWORK_INSIGHTS_FNS = {
    "ec2_network_access_scope_findings_described": ec2_network_access_scope_findings_described,
    "ec2_network_insights_analyses_described": ec2_network_insights_analyses_described,
}

__all__ = [
    "ACCESS_SCOPE",
    "ACCESS_SCOPE_ENDS",
    "ACCESS_SCOPE_PATH",
    "COMPONENT_TYPES",
    "ID_PREFIXES",
    "KINDS",
    "NETWORK_INSIGHTS_FNS",
    "REACHABILITY",
    "REACHABILITY_ENDS",
    "REACHABILITY_PATH",
    "Kind",
    "Path",
    "access_scope_finding_item",
    "classify_component",
    "ordered_components",
    "reachability_analysis_item",
    "read_path",
    "slot_names",
    "slots",
    "token",
]
