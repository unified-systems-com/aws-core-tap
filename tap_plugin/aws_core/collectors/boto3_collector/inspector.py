"""Amazon Inspector v2 findings for the landing-zone reader (aws-core-tap#261).

Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-inspector), with the containment pairs of
``req-aws-core-contained-type-triple`` (specs/spec-aws-core-v0.md).

Inspector is regional and has no detector-like parent resource, so its findings are contained by the account's
region footprint. Per region in scope, for the run's own account:

    inspector2  BatchGetAccountStatus (is Inspector on here), ListFindingAggregations(FINDING_TYPE) once per
                finding type (the true totals), ListFindings per finding type twice: ACTIVE, most severe first,
                and CLOSED in the last ``CLOSED_WINDOW_DAYS`` days

Every finding type is read by default (ruling Q124a); the credential's ``inspector_finding_types`` down-selects.
Each read runs to its end unless the operator's shared findings limits stop it (``findings.FindingsLimits``, rulings
Q125a and b), and asks only for findings updated since Inspector's watermark in the region when it has one
(``findings.READ_THROUGH``, rulings Q126a and c). A findings surface is filtered, so it is never complete and
nominates no retirement (the surface rule of ``findings.py``).

What is stored is typed fields and Inspector's own sub-documents (CVSS entries, the adjusted score, vulnerable
packages, a code finding's CWEs, detector, rule and file location) verbatim. ``resources[].details`` is never
stored: the node the finding concerns already holds those facts. In GovCloud the code type returns nothing (no
Lambda code scanning there), which is stored as such.

A ``NETWORK_REACHABILITY`` finding is the middle node of the first compound edge (``req-grid-edge-compound``):
``REACHABILITY_SOURCE`` from the entry gateway, ``REACHABILITY_DESTINATION`` to the network interface and
``TRAVERSES_COMPONENT`` to each route table, security group and network ACL on the path (:func:`read_path`).

Nothing here was observed against a live Inspector account: shapes and filters are read from botocore's
``inspector2`` model, and the tests drive this module through ``botocore.stub.Stubber``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .containment import footprint_key
from .envelope import jsonable
from .findings import CLOSED_WINDOW_DAYS, CONCERNS_RESOURCE
from .identity import node_ref
from .partition import parse_arn

if TYPE_CHECKING:
    from .landing_zone import _Reader, _Walk

FOOTPRINT = "aws_core__aws_account_region"
INSPECTOR_FINDING = "aws_core__aws_inspector2_finding"
EC2_INSTANCE = "aws_core__aws_ec2_instance"
LAMBDA_FUNCTION = "aws_core__aws_lambda"
ECR_REPOSITORY = "aws_core__aws_ecr_repository"
IMAGE_HOST = "computing_core__host"
#: Every type a package finding's ``CONCERNS_RESOURCE`` can reach; the model's OUTBOUND_EDGES declares exactly these.
CONCERNS_TARGETS: tuple[str, ...] = (EC2_INSTANCE, LAMBDA_FUNCTION, ECR_REPOSITORY, IMAGE_HOST)

HOSTS_INSPECTOR2_FINDING = "HOSTS_INSPECTOR2_FINDING__aws_core"
RELATION_INSPECTOR2_FINDINGS = "account_region.inspector2_findings"

# --- the package chain (req-aws-landing-zone-inspector-packages) ----------------------------------------------------
PACKAGE = "computing_core__package"
INSTALLS_PACKAGE = "INSTALLS_PACKAGE__computing_core"
#: Inspector ``packageManager`` (read: botocore ``PackageManager``) -> the package-URL type computing_core's SBOM
#: parser keys a package by (``classify_component``: purl type, name, version), so Inspector, grype and anchore name
#: one node. ``OS`` is the image's distribution family (:data:`OS_FAMILIES`).
LANGUAGE_ECOSYSTEMS: dict[str, str] = {
    "NPM": "npm",
    "YARN": "npm",
    "NODEPKG": "npm",
    "PIP": "pypi",
    "PIPENV": "pypi",
    "POETRY": "pypi",
    "PYTHONPKG": "pypi",
    "BUNDLER": "gem",
    "GEMSPEC": "gem",
    "CARGO": "cargo",
    "NUGET": "nuget",
    "DOTNET_CORE": "nuget",
    "GOBINARY": "golang",
    "GOMOD": "golang",
}
#: Package managers given no key, and why: a node would join nothing another writer makes.
UNMAPPED_MANAGERS: dict[str, str] = {
    "JAR": "Syft names a Maven component by its artifact id and Inspector by group:artifact",
    "POM": "Syft names a Maven component by its artifact id and Inspector by group:artifact",
    "COMPOSER": "composer is not a package type computing_core's SBOM parser keeps",
}
#: An image ``platform`` prefix -> the OS package type (inferred from Inspector's supported operating systems;
#: botocore types ``platform`` as a free string, so these must be checked against live findings).
OS_FAMILIES: tuple[tuple[str, str], ...] = (
    ("AMAZON_LINUX", "rpm"),
    ("RHEL", "rpm"),
    ("CENTOS", "rpm"),
    ("ORACLE", "rpm"),
    ("ALMA", "rpm"),
    ("ROCKY", "rpm"),
    ("FEDORA", "rpm"),
    ("SUSE", "rpm"),
    ("SLES", "rpm"),
    ("OPENSUSE", "rpm"),
    ("DEBIAN", "deb"),
    ("UBUNTU", "deb"),
    ("ALPINE", "apk"),
)
#: computing_core's package column limits.
_MAX_ECOSYSTEM, _MAX_PACKAGE_NAME, _MAX_PACKAGE_VERSION = 32, 255, 128

# --- the reachability compound edge (req-aws-landing-zone-inspector-reachability) ---------------------------------
REACHABILITY_FINDING = "aws_core__aws_inspector2_reachability_finding"
HOSTS_INSPECTOR2_REACHABILITY_FINDING = "HOSTS_INSPECTOR2_REACHABILITY_FINDING__aws_core"
RELATION_INSPECTOR2_REACHABILITY_FINDINGS = "account_region.inspector2_reachability_findings"
REACHABILITY_SOURCE = "REACHABILITY_SOURCE__aws_core"
REACHABILITY_DESTINATION = "REACHABILITY_DESTINATION__aws_core"
TRAVERSES_COMPONENT = "TRAVERSES_COMPONENT__aws_core"
INTERNET_GATEWAY = "aws_core__aws_internet_gateway"
VPN_GATEWAY = "aws_core__aws_ec2_vpn_gateway"
PEERING_CONNECTION = "aws_core__aws_ec2_vpc_peering_connection"
ALB = "aws_core__aws_alb"
NETWORK_INTERFACE = "aws_core__aws_ec2_network_interface"
ROUTE_TABLE = "aws_core__aws_route_table"
SECURITY_GROUP = "aws_core__aws_security_group"
NETWORK_ACL = "aws_core__aws_network_acl"
#: The closed lists the role edges declare (``edges/REACHABILITY_SOURCE.edge.json`` and ``TRAVERSES_COMPONENT``).
SOURCE_TYPES: tuple[str, ...] = (INTERNET_GATEWAY, VPN_GATEWAY, PEERING_CONNECTION, ALB)
PATH_TYPES: tuple[str, ...] = (ROUTE_TABLE, SECURITY_GROUP, NETWORK_ACL)
#: AWS resource-id prefixes, each documented with its resource (``igw-``, ``vgw-``, ``pcx-``, ``rtb-``, ``sg-``,
#: ``acl-``, ``eni-``), and the aws_core type keyed by that id. A step's role is read from this, or from its ARN.
ID_PREFIXES: dict[str, str] = {
    "igw-": INTERNET_GATEWAY,
    "vgw-": VPN_GATEWAY,
    "pcx-": PEERING_CONNECTION,
    "rtb-": ROUTE_TABLE,
    "sg-": SECURITY_GROUP,
    "acl-": NETWORK_ACL,
    "eni-": NETWORK_INTERFACE,
}
#: ``Step.componentType`` values whose meaning AWS documents. botocore types the member as a free string with no
#: enum, and no AWS page found lists its values (searched 2026-11-20), so the table is empty: every value is listed
#: in ``component_types_unmatched`` and the role comes from the id or ARN. Fill it from live findings.
DOCUMENTED_COMPONENT_TYPES: dict[str, str] = {}

PACKAGE_VULNERABILITY = "PACKAGE_VULNERABILITY"
CODE_VULNERABILITY = "CODE_VULNERABILITY"
NETWORK_REACHABILITY = "NETWORK_REACHABILITY"
#: Every finding type botocore's ``FindingType`` enum names, in the order a run reads them (read: botocore 1.44.4).
#: ``inspector_finding_types`` in the credential down-selects them; absent, all are read (ruling Q124a).
FINDING_TYPES: tuple[str, ...] = ("PACKAGE_VULNERABILITY", "CODE_VULNERABILITY", "NETWORK_REACHABILITY")
#: ``ListFindings`` takes at most 100 (read: botocore ``ListFindingsMaxResults``).
INSPECTOR_PAGE = 100
#: Statuses that mean Inspector is positively not scanning this account here (botocore ``Status``).
NOT_SCANNING = frozenset({"DISABLED", "SUSPENDED"})
#: ``severityCounts`` members, in Inspector's ``Severity`` label form (botocore ``SeverityCounts``).
SEVERITY_COUNT_MEMBERS: tuple[str, ...] = ("all", "critical", "high", "medium", "low", "informational", "untriaged")

PAGINATED_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("inspector2", "list_findings"),
    ("inspector2", "list_finding_aggregations"),
)
SINGLE_OPERATIONS: tuple[tuple[str, str], ...] = (("inspector2", "batch_get_account_status"),)


def _eq(value: str) -> list[dict[str, str]]:
    return [{"comparison": "EQUALS", "value": value}]


def _str(value: Any) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        value = value if value.tzinfo else value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return _str(value)


def _doc(value: Any) -> Any:
    return None if value is None else jsonable(value)


def _str_list(values: Any) -> list[str] | None:
    return [str(v) for v in values if v] if isinstance(values, list) else None


def image_digest_of(resource_type: str | None, resource_id: str | None) -> str | None:
    """An ECR image's digest from its resource id (``arn:…:repository/<name>/sha256:<hex>``), else None."""
    from .ecs import well_formed_digest

    if resource_type != "AWS_ECR_CONTAINER_IMAGE" or not resource_id or "/sha256:" not in resource_id:
        return None
    return well_formed_digest("sha256:" + resource_id.rsplit("/sha256:", 1)[1])


def os_ecosystem(platform: Any) -> str | None:
    """The OS package type of an image ``platform`` (``AMAZON_LINUX_2023`` -> ``rpm``), or None when unknown."""
    if not isinstance(platform, str):
        return None
    upper = platform.upper()
    return next((ecosystem for prefix, ecosystem in OS_FAMILIES if upper.startswith(prefix)), None)


def package_identities(packages: Any, platform: Any) -> list[dict[str, Any]]:
    """Per vulnerable package, the ``computing_core__package`` key it is written under, or why it has none.

    ``{name, version, package_manager, key: {ecosystem, name, version} | None, unmatched: reason | None}``. A
    language package keeps Inspector's ``version``; an OS package's version is ``version-release`` with ``epoch:``
    first when the epoch is above zero (inferred to be Syft's form for rpm, dpkg and apk; to be checked against a
    live finding and an SBOM of the same image).
    """
    out: list[dict[str, Any]] = []
    for package in packages if isinstance(packages, list) else []:
        if not isinstance(package, dict):
            continue
        name, version = str(package.get("name") or ""), str(package.get("version") or "")
        manager = str(package.get("packageManager") or "")
        ecosystem: str | None
        unmatched: str | None = None
        if manager == "OS":
            ecosystem = os_ecosystem(platform)
            if ecosystem is None:
                unmatched = f"an OS package on an image whose platform {platform!r} names no known distribution family"
            release = str(package.get("release") or "")
            epoch = package.get("epoch")
            full = version + (f"-{release}" if release else "")
            if isinstance(epoch, int) and not isinstance(epoch, bool) and epoch > 0:
                full = f"{epoch}:{full}"
            version = full
        elif manager in LANGUAGE_ECOSYSTEMS:
            ecosystem = LANGUAGE_ECOSYSTEMS[manager]
        else:
            ecosystem = None
            unmatched = UNMAPPED_MANAGERS.get(manager) or f"package manager {manager or 'none'!r} has no mapped type"
        if ecosystem is not None and (not name or not version):
            ecosystem, unmatched = None, "no name or version"
        if ecosystem is not None and (len(name) > _MAX_PACKAGE_NAME or len(version) > _MAX_PACKAGE_VERSION):
            ecosystem, unmatched = None, "a name or version longer than computing_core's package columns"
        key = {"ecosystem": ecosystem[:_MAX_ECOSYSTEM], "name": name, "version": version} if ecosystem else None
        out.append(
            {
                "name": str(package.get("name") or ""),
                "version": str(package.get("version") or ""),
                "package_manager": manager or None,
                "key": key,
                "unmatched": unmatched,
            }
        )
    return out


def concerned_resource(resource_type: str | None, resource_id: str | None) -> tuple[str, str] | None:
    """``(aws_core type, natural key)`` of the resource a finding's ``resources[0]`` names, or None.

    An EC2 instance by its id (Inspector's id is the instance id, or an instance ARN); a Lambda function by its
    unqualified ARN, ``:$LATEST`` removed (any other qualifier names a version aws_core does not model); an ECR
    repository by its ARN; an ECR image by its repository's ARN, the ``/sha256:`` digest removed.
    """
    if not resource_id:
        return None
    if resource_type == "AWS_EC2_INSTANCE":
        if resource_id.startswith("i-"):
            return EC2_INSTANCE, resource_id
        parsed = parse_arn(resource_id)
        if parsed and parsed.service == "ec2" and parsed.resource.startswith("instance/i-"):
            return EC2_INSTANCE, parsed.resource.split("/", 1)[1]
        return None
    if resource_type == "AWS_LAMBDA_FUNCTION":
        arn = resource_id.removesuffix(":$LATEST")
        parsed = parse_arn(arn)
        if parsed and parsed.service == "lambda" and parsed.resource.startswith("function:"):
            if parsed.resource.count(":") == 1:
                return LAMBDA_FUNCTION, arn
        return None
    if resource_type in ("AWS_ECR_REPOSITORY", "AWS_ECR_CONTAINER_IMAGE"):
        arn = resource_id.rsplit("/sha256:", 1)[0] if resource_type == "AWS_ECR_CONTAINER_IMAGE" else resource_id
        parsed = parse_arn(arn)
        if parsed and parsed.service == "ecr" and parsed.resource.startswith("repository/"):
            return ECR_REPOSITORY, arn
        return None
    return None


def classify_step(step: dict[str, Any]) -> tuple[str, str] | None:
    """``(aws_core type, natural key)`` of one path step: from its ``componentId``'s documented resource-id prefix,
    else from its ``componentArn`` (or an ARN-shaped id) read by ``arn_resolver``; None when neither names a type the
    role edges can reach. ``componentType`` plays no part (``DOCUMENTED_COMPONENT_TYPES`` is empty)."""
    from .arn_resolver import resolve_arn

    component_id = str(step.get("componentId") or "")
    for prefix, entity_type in ID_PREFIXES.items():
        if component_id.startswith(prefix):
            return entity_type, component_id
    for value in (step.get("componentArn"), component_id):
        if isinstance(value, str) and value.startswith("arn:"):
            target = resolve_arn(value)
            if target is not None and target[0] in (*SOURCE_TYPES, *PATH_TYPES, NETWORK_INTERFACE):
                return target
    return None


@dataclass
class Reach:
    """What one reachability finding's path says: its ends, its path components, and what matched nothing."""

    source: tuple[str, str] | None = None
    destination: tuple[str, str] | None = None
    path: list[tuple[int, str, str]] = field(default_factory=list)
    unmatched_steps: list[dict[str, Any]] = field(default_factory=list)
    component_types_unmatched: list[str] = field(default_factory=list)


def read_path(steps: Any) -> Reach:
    """The compound edge's pieces from ``networkPath.steps``. The first gateway step is the source; the last
    network-interface step is the destination; every route table, security group and network ACL is on the path.
    A step no tabled type matches, a second gateway and an earlier interface are listed in ``unmatched_steps``."""
    reach = Reach()
    steps = [s for s in steps or [] if isinstance(s, dict)]
    types: list[str] = []
    interfaces: list[tuple[int, tuple[str, str]]] = []
    for index, step in enumerate(steps):
        component_type = str(step.get("componentType") or "")
        if component_type and component_type not in DOCUMENTED_COMPONENT_TYPES and component_type not in types:
            types.append(component_type)
        target = classify_step(step)
        record = {"step": index, "componentId": step.get("componentId"), "componentType": step.get("componentType")}
        if target is None:
            reach.unmatched_steps.append({**record, "reason": "no tabled aws_core type matches its id or ARN"})
        elif target[0] in SOURCE_TYPES:
            if reach.source is None:
                reach.source = target
            else:
                reach.unmatched_steps.append({**record, "reason": "a second gateway on the path; the first is the source"})
        elif target[0] in PATH_TYPES:
            reach.path.append((index, *target))
        else:
            interfaces.append((index, target))
    if interfaces:
        reach.destination = interfaces[-1][1]
        for index, _target in interfaces[:-1]:
            step = steps[index]
            reach.unmatched_steps.append(
                {
                    "step": index,
                    "componentId": step.get("componentId"),
                    "componentType": step.get("componentType"),
                    "reason": "a network interface before the last; the last is the destination",
                }
            )
    reach.component_types_unmatched = types
    return reach


@dataclass
class _TypeRead:
    """One finding type's two reads in one region."""

    active: _Walk
    active_cut: bool
    closed: _Walk
    closed_cut: bool
    findings: list[dict[str, Any]] = field(default_factory=list)


class InspectorReads:
    """The Inspector half of one landing-zone read. ``reader`` is the landing-zone ``_Reader``; every node, edge,
    surface, notice and AWS call goes through it."""

    def __init__(self, reader: _Reader) -> None:
        self.r = reader

    # -- account status and totals ----------------------------------------

    def _status(self, region: str) -> tuple[str | None, dict[str, str] | None]:
        response, _ = self.r.call("inspector2", region, "batch_get_account_status", accountIds=[self.r.account_id])
        if response is None:
            return None, None
        account = next(
            (a for a in response.get("accounts") or [] if isinstance(a, dict) and a.get("accountId") == self.r.account_id),
            None,
        )
        if account is None:
            return None, None
        status = _str((account.get("state") or {}).get("status"))
        resources = {
            str(name): str(state.get("status"))
            for name, state in (account.get("resourceState") or {}).items()
            if isinstance(state, dict) and state.get("status")
        }
        return status, resources

    def _totals(self, region: str, finding_types: tuple[str, ...]) -> tuple[dict[str, dict[str, int]], bool]:
        """``({finding type: {SEVERITY: count}}, every call answered)`` from ``ListFindingAggregations``: the true
        totals, whatever the reads were limited or filtered to."""
        counts: dict[str, dict[str, int]] = {}
        complete = True
        for finding_type in finding_types:
            read = self.r.walk(
                "inspector2",
                region,
                "list_finding_aggregations",
                "responses",
                aggregationType="FINDING_TYPE",
                accountIds=_eq(self.r.account_id),
                aggregationRequest={"findingTypeAggregation": {"findingType": finding_type}},
            )
            if not read.complete:
                complete = False
                continue
            totals: dict[str, int] = {}
            for response in read.items:
                aggregation = (response or {}).get("findingTypeAggregation") or {}
                if aggregation.get("accountId") not in (None, self.r.account_id):
                    continue
                severity = aggregation.get("severityCounts") or {}
                for member in SEVERITY_COUNT_MEMBERS:
                    value = severity.get(member)
                    if isinstance(value, int) and not isinstance(value, bool):
                        totals[member.upper()] = totals.get(member.upper(), 0) + value
            counts[finding_type] = totals
        return counts, complete

    # -- the finding reads --------------------------------------------------

    def _read(self, region: str, finding_type: str, since: datetime | None) -> _TypeRead:
        """ACTIVE findings of one type, most severe first, then those CLOSED in the window; each to its end unless the
        operator's limits stop it, and only those updated since ``since`` when the source has a watermark."""
        account = self.r.account_id
        window = datetime.now(UTC) - timedelta(days=CLOSED_WINDOW_DAYS)
        active_criteria: dict[str, Any] = {
            "awsAccountId": _eq(account),
            "findingType": _eq(finding_type),
            "findingStatus": _eq("ACTIVE"),
        }
        if since is not None:
            active_criteria["updatedAt"] = [{"startInclusive": since}]
        active, active_cut = self.r.findings_walk(
            "inspector2",
            region,
            "list_findings",
            "findings",
            filterCriteria=active_criteria,
            sortCriteria={"field": "SEVERITY", "sortOrder": "DESC"},
            maxResults=INSPECTOR_PAGE,
        )
        closed, closed_cut = self.r.findings_walk(
            "inspector2",
            region,
            "list_findings",
            "findings",
            filterCriteria={
                "awsAccountId": _eq(account),
                "findingType": _eq(finding_type),
                "findingStatus": _eq("CLOSED"),
                "updatedAt": [{"startInclusive": max(window, since) if since is not None else window}],
            },
            sortCriteria={"field": "LAST_OBSERVED_AT", "sortOrder": "DESC"},
            maxResults=INSPECTOR_PAGE,
        )
        found = [f for f in active.items + closed.items if isinstance(f, dict)]
        return _TypeRead(active, active_cut, closed, closed_cut, found)

    def filter_text(self, finding_types: tuple[str, ...], since: datetime | None) -> str:
        account = self.r.account_id
        return (
            f"inspector2:ListFindings awsAccountId={account}, findingType in {', '.join(finding_types)}, "
            f"findingStatus=ACTIVE; and findingStatus=CLOSED, updatedAt in the last {CLOSED_WINDOW_DAYS} days"
            + (f"; incremental: updatedAt >= {self.r.iso(since)}" if since is not None else "")
        )

    def _record(
        self,
        region: str,
        relation: str,
        edge_type: str,
        types: tuple[str, ...],
        reads: list[_TypeRead],
        *,
        since: datetime | None,
        unwritten: int,
        not_scanning: str | None,
        not_selected: bool,
    ) -> None:
        """The footprint's surface for one containment edge (one or more finding types): filtered, so never
        complete, whether or not a limit stopped a read."""
        from .landing_zone import _now
        from .landing_zone import _Walk as Walk

        walks = [w for r in reads for w in (r.active, r.closed)]
        if walks:
            combined = self.r.aggregate(walks)
        else:
            now = _now()
            combined = Walk([], now, now, operation="list_findings")
        listing = self.r.findings.surface(
            combined,
            relation,
            edge_type,
            FOOTPRINT,
            footprint_key(self.r.account_id, region),
            count=sum(len(w.items) for w in walks),
            skipped=unwritten,
            filter_text=self.filter_text(types, since),
            truncated=any(r.active_cut or r.closed_cut for r in reads),
        )
        if not_scanning:
            listing.reasons["not_scanning"] = (
                f"inspector_{not_scanning.lower()}: BatchGetAccountStatus says Inspector is {not_scanning} for this "
                "account here, so no finding was read"
            )
        elif not_selected:
            listing.reasons["not_selected"] = (
                f"not_selected: inspector_finding_types leaves out {', '.join(types)}, so no finding of it was read"
            )

    # -- one region ---------------------------------------------------------

    def selected_types(self) -> tuple[str, ...]:
        """The finding types this run reads, in reading order: every type unless ``inspector_finding_types`` trims."""
        chosen = self.r.inspector_finding_types
        return tuple(t for t in self.finding_types() if chosen is None or t in chosen)

    def read(self, region: str) -> None:
        """Every Inspector read for one region; the footprint's fields go to ``footprint_fields``."""
        status, resource_status = self._status(region)
        selected = self.selected_types()
        fields: dict[str, Any] = {"inspector2_status": status, "inspector2_resource_status": resource_status}
        not_scanning = status if status in NOT_SCANNING else None
        since = self.r.since("inspector2", region)
        reads: dict[str, _TypeRead] = {}
        if not_scanning:
            self.r.notice(
                "info",
                "INSPECTOR2_NOT_SCANNING",
                f"inspector2 in {region}: BatchGetAccountStatus says {status}; no finding was read.",
                region=region,
                status=status,
            )
            fields.update(
                inspector2_active_finding_counts={t: {} for t in selected},
                inspector2_active_finding_counts_complete=True,
                inspector2_active_findings_truncated=False,
            )
        else:
            counts, complete = self._totals(region, selected)
            for finding_type in selected:
                reads[finding_type] = self._read(region, finding_type, since)
            cut = any(r.active_cut for r in reads.values())
            active_complete = all(r.active.complete for r in reads.values())
            fields.update(
                inspector2_active_finding_counts=counts if counts or complete else None,
                inspector2_active_finding_counts_complete=complete,
                inspector2_active_findings_truncated=cut if active_complete or cut else None,
            )
        self.r.result.footprint_fields.setdefault(region, {}).update(fields)
        unwritten_by_relation: dict[str, int] = {}
        for finding_type, read in reads.items():
            relation, _edge, writer = self.kinds()[finding_type]
            unwritten = sum(1 for f in read.active.items + read.closed.items if not isinstance(f, dict))
            for finding in read.findings:
                if not writer(region, finding):
                    unwritten += 1
            unwritten_by_relation[relation] = unwritten_by_relation.get(relation, 0) + unwritten
        if reads:
            self.r.mark_read(
                "inspector2",
                region,
                [w for r in reads.values() for w in (r.active, r.closed)],
                clean=not any(r.active_cut or r.closed_cut for r in reads.values()),
            )
        for relation, edge_type, types in self.surfaces():
            chosen = tuple(t for t in types if t in selected)
            self._record(
                region,
                relation,
                edge_type,
                chosen or types,
                [reads[t] for t in chosen if t in reads],
                since=since,
                unwritten=unwritten_by_relation.get(relation, 0),
                not_scanning=not_scanning,
                not_selected=not chosen,
            )

    def surfaces(self) -> list[tuple[str, str, tuple[str, ...]]]:
        """``(relation, containment edge, finding types)``: one footprint surface per containment edge."""
        grouped: dict[tuple[str, str], list[str]] = {}
        for finding_type, (relation, edge_type, _writer) in self.kinds().items():
            grouped.setdefault((relation, edge_type), []).append(finding_type)
        return [(relation, edge_type, tuple(types)) for (relation, edge_type), types in grouped.items()]

    def containment(self) -> tuple[tuple[str, str], ...]:
        """``(containment edge, surface relation)`` per surface: what ``readable_regions`` records for a region it
        does not read (a disabled region, or a partition without the service)."""
        return tuple((edge_type, relation) for relation, edge_type, _types in self.surfaces())

    def finding_types(self) -> tuple[str, ...]:
        return tuple(self.kinds())

    def kinds(self) -> dict[str, tuple[str, str, Callable[[str, dict[str, Any]], bool]]]:
        """Finding type → (surface relation, containment edge, writer), in reading order."""
        return {
            PACKAGE_VULNERABILITY: (RELATION_INSPECTOR2_FINDINGS, HOSTS_INSPECTOR2_FINDING, self._finding),
            CODE_VULNERABILITY: (RELATION_INSPECTOR2_FINDINGS, HOSTS_INSPECTOR2_FINDING, self._finding),
            NETWORK_REACHABILITY: (
                RELATION_INSPECTOR2_REACHABILITY_FINDINGS,
                HOSTS_INSPECTOR2_REACHABILITY_FINDING,
                self._reachability_finding,
            ),
        }

    # -- writing ------------------------------------------------------------

    def _common(self, region: str, finding: dict[str, Any]) -> dict[str, Any]:
        """The fields every Inspector finding type stores. ``resources[].details`` is not among them."""
        resources = [r for r in finding.get("resources") or [] if isinstance(r, dict)]
        resource = resources[0] if resources else {}
        recommendation = (finding.get("remediation") or {}).get("recommendation") or {}
        title = str(finding.get("title") or "")
        return {
            "finding_arn": str(finding.get("findingArn") or ""),
            "account_id": _str(finding.get("awsAccountId")) or self.r.account_id,
            "region": _str(resource.get("region")) or region,
            "finding_type": _str(finding.get("type")),
            "status": _str(finding.get("status")),
            "severity": _str(finding.get("severity")),
            "inspector_score": _num(finding.get("inspectorScore")),
            "title": title[:1024] or None,
            "description": _str(finding.get("description")),
            "remediation": _str(recommendation.get("text")),
            "remediation_url": (_str(recommendation.get("Url")) or "")[:2048] or None,
            "first_observed_at": _iso(finding.get("firstObservedAt")),
            "last_observed_at": _iso(finding.get("lastObservedAt")),
            "updated_at": _iso(finding.get("updatedAt")),
            "resource_type": _str(resource.get("type")),
            "resource_id": (_str(resource.get("id")) or "")[:2048] or None,
            # AWS cannot tag a finding (lane `none`, tag_lanes.json).
            "tags": {},
        }

    def _finding(self, region: str, finding: dict[str, Any]) -> bool:
        """A package- or code-vulnerability finding: one ``aws_inspector2_finding`` row."""
        common = self._common(region, finding)
        arn = common["finding_arn"]
        if not arn:
            return False
        details = finding.get("packageVulnerabilityDetails") or {}
        code = finding.get("codeVulnerabilityDetails") or {}
        location = code.get("filePath") or {}
        adjusted = (finding.get("inspectorScoreDetails") or {}).get("adjustedCvss")
        vulnerability_id = _str(details.get("vulnerabilityId"))
        digest = image_digest_of(common["resource_type"], common["resource_id"])
        # The image's platform is read in memory from resources[].details (never stored) for the OS package type.
        resources = [r for r in finding.get("resources") or [] if isinstance(r, dict)]
        image = ((resources[0].get("details") or {}).get("awsEcrContainerImage") or {}) if resources else {}
        identities = package_identities(details.get("vulnerablePackages"), image.get("platform")) if digest else None
        fields: dict[str, Any] = {
            "name": (common["title"] or vulnerability_id or _str(code.get("detectorName")) or arn)[:255],
            **common,
            "vulnerability_id": (vulnerability_id or "")[:128] or None,
            "related_vulnerabilities": _str_list(details.get("relatedVulnerabilities")),
            "vulnerability_source": _str(details.get("source")),
            "source_url": (_str(details.get("sourceUrl")) or "")[:2048] or None,
            "vendor_severity": _str(details.get("vendorSeverity")),
            "vendor_created_at": _iso(details.get("vendorCreatedAt")),
            "vendor_updated_at": _iso(details.get("vendorUpdatedAt")),
            "reference_urls": _str_list(details.get("referenceUrls") if details else code.get("referenceUrls")),
            "cvss": _doc(details.get("cvss")),
            "adjusted_cvss": _doc(adjusted),
            "fix_available": _str(finding.get("fixAvailable")),
            "exploit_available": _str(finding.get("exploitAvailable")),
            "last_known_exploit_at": _iso((finding.get("exploitabilityDetails") or {}).get("lastKnownExploitAt")),
            "epss_score": _num((finding.get("epss") or {}).get("score")),
            "vulnerable_packages": _doc(details.get("vulnerablePackages")),
            "image_digest": digest,
            "package_identities": identities,
            # A code-vulnerability finding's detail (read: botocore CodeVulnerabilityDetails, CodeFilePath).
            "cwes": _str_list(code.get("cwes")),
            "detector_id": _str(code.get("detectorId")),
            "detector_name": (_str(code.get("detectorName")) or "")[:255] or None,
            "detector_tags": _str_list(code.get("detectorTags")),
            "rule_id": _str(code.get("ruleId")),
            "code_file_name": (_str(location.get("fileName")) or "")[:1024] or None,
            "code_file_path": (_str(location.get("filePath")) or "")[:2048] or None,
            "code_start_line": _int(location.get("startLine")),
            "code_end_line": _int(location.get("endLine")),
            "code_source_lambda_layer_arn": (_str(code.get("sourceLambdaLayerArn")) or "")[:2048] or None,
        }
        if not self.r.add_node(INSPECTOR_FINDING, arn, str(fields["name"]), fields, region):
            return False
        self.r.hosts(HOSTS_INSPECTOR2_FINDING, region, INSPECTOR_FINDING, arn)
        target = concerned_resource(common["resource_type"], common["resource_id"])
        if target is not None:
            self.r.add_edge(CONCERNS_RESOURCE, INSPECTOR_FINDING, arn, target[0], target[1], region)
        if digest is not None and self._image_host(digest):
            from .ecs import host_key
            from .identity import composite_natural_key

            self.r.add_edge(
                CONCERNS_RESOURCE, INSPECTOR_FINDING, arn, IMAGE_HOST, composite_natural_key(host_key(digest)), region
            )
            self._installs(digest, identities or [])
        return True

    def _installs(self, digest: str, identities: list[dict[str, Any]]) -> None:
        """The image host ``INSTALLS_PACKAGE`` each keyed package (req-aws-landing-zone-inspector-packages-1). A
        package envelope carries its key and nothing else, so what an SBOM writer stored (purl, licence) is kept."""
        from .ecs import host_ref
        from .edges import edge_envelope
        from .identity import composite_natural_key, edge_ref
        from .organizations import sensitivity_refusal

        keyed = [i["key"] for i in identities if i.get("key")]
        if not keyed:
            return
        refused = sensitivity_refusal(PACKAGE, self.r.sensitivity)
        if refused is not None:
            self.r.notice("warn", "LANDING_ZONE_NODE_SKIPPED", f"{PACKAGE}: skipped, {refused}", entity_type=PACKAGE)
            return
        for key in keyed:
            ref = node_ref(PACKAGE, composite_natural_key(key))
            if ref not in self.r._node_refs:
                self.r._node_refs.add(ref)
                self.r.result.nodes.append({"entity": {"ref": ref, "entity_type": PACKAGE, "dimensions": {}}, "node": dict(key)})
            edge = edge_ref(INSTALLS_PACKAGE, host_ref(digest), ref)
            if edge not in self.r._edge_refs:
                self.r._edge_refs.add(edge)
                # An image is not in an account or a region: the edge takes its type's default dimensions.
                self.r.result.edges.append(edge_envelope(INSTALLS_PACKAGE, from_ref=host_ref(digest), to_ref=ref, dimensions={}))

    def _reachability_finding(self, region: str, finding: dict[str, Any]) -> bool:
        """The middle node of the reachability compound edge, its role edges and its containment."""
        common = self._common(region, finding)
        arn = common["finding_arn"]
        if not arn:
            return False
        details = finding.get("networkReachabilityDetails") or {}
        ports = details.get("openPortRange") or {}
        steps = (details.get("networkPath") or {}).get("steps")
        reach = read_path(steps)
        begin, end = ports.get("begin"), ports.get("end")
        fields: dict[str, Any] = {
            "name": (common["title"] or arn)[:255],
            **common,
            "protocol": _str(details.get("protocol")),
            "open_port_begin": begin if isinstance(begin, int) and not isinstance(begin, bool) else None,
            "open_port_end": end if isinstance(end, int) and not isinstance(end, bool) else None,
            "network_path": _doc(steps),
            "component_types_unmatched": reach.component_types_unmatched if steps is not None else None,
            "unmatched_steps": reach.unmatched_steps if steps is not None else None,
        }
        if not self.r.add_node(REACHABILITY_FINDING, arn, str(fields["name"]), fields, region):
            return False
        self.r.hosts(HOSTS_INSPECTOR2_REACHABILITY_FINDING, region, REACHABILITY_FINDING, arn)
        if reach.source is not None:
            self.r.add_edge(REACHABILITY_SOURCE, reach.source[0], reach.source[1], REACHABILITY_FINDING, arn, region)
        if reach.destination is not None:
            self.r.add_edge(
                REACHABILITY_DESTINATION, REACHABILITY_FINDING, arn, reach.destination[0], reach.destination[1], region
            )
        for index, entity_type, key in reach.path:
            self.r.add_edge(TRAVERSES_COMPONENT, REACHABILITY_FINDING, arn, entity_type, key, region, properties={"step": index})
        return True

    def _image_host(self, digest: str) -> bool:
        """Stage computing_core's image host for ``digest`` once, as the ECS reader does (``ecs._host_envelope``):
        a host the grid holds is sent with its key and kind only. False when the host type is refused."""
        from .ecs import _host_envelope, host_held_on_grid, host_ref
        from .organizations import sensitivity_refusal

        ref = host_ref(digest)
        if ref in self.r._node_refs:
            return True
        refused = sensitivity_refusal(IMAGE_HOST, self.r.sensitivity)
        if refused is not None:
            self.r.notice("warn", "LANDING_ZONE_NODE_SKIPPED", f"{IMAGE_HOST} {digest}: skipped, {refused}", entity_type=IMAGE_HOST)
            return False
        held_on_grid = self.r.host_held or host_held_on_grid
        try:
            held = bool(held_on_grid(digest))
        except Exception as exc:  # noqa: BLE001 — recorded; the write that is safe either way is sent
            held = True
            self.r.notice(
                "warn",
                "INSPECTOR2_IMAGE_HOST_LOOKUP_FAILED",
                f"image host {digest}: the grid lookup failed ({type(exc).__name__}); sent with its key and kind only",
            )
        self.r._node_refs.add(ref)
        # No image reference is passed: Inspector names the repository and tags only in resources[].details, which
        # is not stored, so a host first seen here is named by its digest (ECS names it later if it runs the image).
        self.r.result.nodes.append(_host_envelope(digest, set(), held))
        return True


__all__ = [
    "CONCERNS_TARGETS",
    "DOCUMENTED_COMPONENT_TYPES",
    "REACHABILITY_FINDING",
    "classify_step",
    "package_identities",
    "read_path",
    "HOSTS_INSPECTOR2_FINDING",
    "INSPECTOR_FINDING",
    "FINDING_TYPES",
    "PAGINATED_OPERATIONS",
    "SINGLE_OPERATIONS",
    "InspectorReads",
    "concerned_resource",
    "image_digest_of",
]
