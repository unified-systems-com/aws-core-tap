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

PACKAGE_VULNERABILITY = "PACKAGE_VULNERABILITY"
CODE_VULNERABILITY = "CODE_VULNERABILITY"
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
    "HOSTS_INSPECTOR2_FINDING",
    "INSPECTOR_FINDING",
    "FINDING_TYPES",
    "PAGINATED_OPERATIONS",
    "SINGLE_OPERATIONS",
    "InspectorReads",
    "concerned_resource",
    "image_digest_of",
]
