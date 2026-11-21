"""Security findings and Config rule compliance for the landing-zone reader (aws-core-tap#76).

Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-findings), with the containment pairs
of ``req-aws-core-contained-type-triple`` (specs/spec-aws-core-v0.md).

The landing-zone reader (``landing_zone.py``) already reads the services that produce findings: a
GuardDuty detector, a Security Hub hub with its enabled standards, an Access Analyzer analyzer and
the Config recorder, per region for the run's own account. This module reads what they report and
hands it back to that reader, which owns the node, edge and surface plumbing:

    guardduty      ListFindings (capped), GetFindings (≤50 ids per call), GetFindingsStatistics
    securityhub    GetFindings (capped, one read per severity label, highest first)
    accessanalyzer ListFindings (external-access analyzers), ListFindingsV2 (the others), capped
    config         DescribeConfigRules, DescribeComplianceByConfigRule, GetCustomRulePolicy (a Guard
                   rule's policy body), DescribeConformancePacks, GetConformancePackComplianceSummary,
                   ListTagsForResource

Collect-only, and bounded. A finding is an event the service keeps for a while, not a resource an
operator creates, and an account can hold many. Each parent is read twice, both times limited to the
run's own account: its active findings, and the findings it closed in the last ``CLOSED_WINDOW_DAYS``
days (GuardDuty archived, Security Hub ``RecordState`` ARCHIVED, Access Analyzer ARCHIVED or RESOLVED;
aws-core-tap#264, ruling Q115a), so a finding that is fixed or dismissed shows as closed instead of
staying on the grid as active, and its time to close is visible. Each read runs to its last page: there
is no fixed cap (rulings Q125a and b, "collect everything by default and allow people to trim"). An
operator trims with the credential's ``findings_max_per_region`` (the most findings one service writes
per region, shared by its reads there) and ``findings_read_budget_seconds`` (a read stops at its next
page once it has run that long), both off by default (:class:`FindingsLimits`). The parent's surface
records the filters verbatim with no positive control, and a read a limit stopped as a truncation, so a
findings surface is never complete and never nominates a retirement.

Incremental (rulings Q126a and c). A run asks GuardDuty and Security Hub (and Inspector, ``inspector.py``) only for
findings updated since that source's last clean read: the watermark ``findings_read_through``, one ISO time per
``<service>|<account>|<region>``, kept in the ``metadata`` of the collector's own batch node (:func:`read_through_of`,
:data:`READ_THROUGH`). A source whose reads in a region all finished cleanly (no error, no cut-off, no limit or budget
truncation, every finding fetched) writes the run's start minus ``WATERMARK_OVERLAP``; every other key is carried
forward unchanged. No watermark for a key is a full read. Access Analyzer has no date filter, so it is always read in
full. An incremental read is filtered, so it is never complete and never retires: a finding AWS deletes without an
update stays live until the watermark is cleared, which forces one full read. The parent (detector, hub, analyzer) carries per-severity counts of its ACTIVE findings,
so a page can show totals without every finding.

A finding's state is the service's own field, verbatim: GuardDuty's ``archived``, Security Hub's
``record_state`` (beside its ``workflow_status``), Access Analyzer's ``status``. AWS stamps no
closed-at time; a closed finding's ``updated_at`` is when it last changed, which for a closed finding
is its closing or later.

Only typed fields are stored, each declared in ``reader_sensitivity.json``. What a finding says about
itself is kept (aws-core-tap#264, ruling Q114c): GuardDuty's description, action, instance network
interfaces and evidence; Security Hub's description, remediation, network, malware, vulnerabilities,
product fields, types, normalized severity, compliance status reasons and finding-provider fields; a
Config rule's scope, input parameters and Guard policy body. Addresses in titles and resource ids are
stored as AWS wrote them (ruling Q114b). Each group is one JSON field, in AWS's own shape.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .arn_resolver import resolve_arn
from .envelope import jsonable
from .partition import parse_arn

if TYPE_CHECKING:
    from .landing_zone import _Reader, _Walk

GUARDDUTY_FINDING = "aws_core__aws_guardduty_finding"
SECURITYHUB_FINDING = "aws_core__aws_securityhub_finding"
STANDARDS_SUBSCRIPTION = "aws_core__aws_securityhub_standards_subscription"
ACCESS_ANALYZER_FINDING = "aws_core__aws_access_analyzer_finding"
CONFIG_RULE = "aws_core__aws_config_rule"
CONFORMANCE_PACK = "aws_core__aws_config_conformance_pack"
EC2_INSTANCE = "aws_core__aws_ec2_instance"
IAM_USER = "aws_core__aws_iam_user"
IAM_ROLE = "aws_core__aws_iam_role"
S3_BUCKET = "aws_core__aws_s3_bucket"
#: Every type a GuardDuty finding's CONCERNS_RESOURCE can reach (aws-core-tap#264, Q115b): the
#: instance, bucket and access-key user it names by id, and the types ``_guardduty_resource_arns``
#: resolves. The model's OUTBOUND_EDGES declares exactly these.
GUARDDUTY_CONCERNS_TARGETS: tuple[str, ...] = (
    EC2_INSTANCE,
    S3_BUCKET,
    IAM_USER,
    "aws_core__aws_lambda",
    "aws_core__aws_rds_instance",
    "aws_core__aws_rds_db_shard_group",
    "aws_core__aws_ecs_cluster",
    "aws_core__aws_ecs_task",
    "aws_core__aws_eks_cluster",
    "aws_core__aws_ebs_volume",
)

HOLDS_GUARDDUTY_FINDING = "HOLDS_GUARDDUTY_FINDING__aws_core"
HOLDS_SECURITYHUB_FINDING = "HOLDS_SECURITYHUB_FINDING__aws_core"
HOLDS_STANDARDS_SUBSCRIPTION = "HOLDS_STANDARDS_SUBSCRIPTION__aws_core"
HOLDS_ACCESS_ANALYZER_FINDING = "HOLDS_ACCESS_ANALYZER_FINDING__aws_core"
HOSTS_CONFIG_RULE = "HOSTS_CONFIG_RULE__aws_core"
HOSTS_CONFORMANCE_PACK = "HOSTS_CONFORMANCE_PACK__aws_core"
CONCERNS_RESOURCE = "CONCERNS_RESOURCE__aws_core"
EVALUATED_UNDER_STANDARD = "EVALUATED_UNDER_STANDARD__aws_core"

RELATION_GUARDDUTY_FINDINGS = "guardduty_detector.findings"
RELATION_SECURITYHUB_FINDINGS = "securityhub_hub.findings"
RELATION_STANDARDS_SUBSCRIPTIONS = "securityhub_hub.standards_subscriptions"
RELATION_ANALYZER_FINDINGS = "access_analyzer.findings"
RELATION_CONFIG_RULES = "account_region.config_rules"
RELATION_CONFORMANCE_PACKS = "account_region.conformance_packs"

#: How far back the closed-findings read reaches: findings closed (archived, resolved) in the last 30
#: days are read beside the active ones (aws-core-tap#264, ruling Q115a). The active read comes first, so
#: under an operator's ``findings_max_per_region`` closed findings never crowd out active ones.
CLOSED_WINDOW_DAYS = 30
#: The batch-node metadata key that carries the watermark, and the overlap subtracted from the run's start so a
#: finding updated while the previous run was reading is read again rather than missed.
READ_THROUGH = "findings_read_through"
WATERMARK_OVERLAP = timedelta(minutes=15)
#: The sources a run reads incrementally (Access Analyzer has no date filter).
INCREMENTAL_SERVICES = frozenset({"guardduty", "securityhub", "inspector2"})


def watermark_key(service: str, account_id: str, region: str) -> str:
    """One source's key in ``findings_read_through``."""
    return f"{service}|{account_id}|{region}"


def read_through_of(source: str) -> dict[str, str]:
    """The watermark the most recent committed (closed) batch of ``source`` recorded; ``{}`` when there is none.

    A read of the grid's own batch rows (``tap_grid.models.Batch``), never a write. Values that are not an ISO time are
    dropped, so a damaged watermark forces a full read of that source rather than a filter on garbage.
    """
    from tap_grid.models import Batch, BatchStatus

    batch = Batch.objects.filter(source=source, status=BatchStatus.CLOSED).order_by("-closed_at", "-started_at").first()
    raw = (getattr(batch, "metadata", None) or {}).get(READ_THROUGH) if batch is not None else None
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str) and _when(v) is not None}


#: Access Analyzer's closed statuses (read: botocore ``FindingStatus``: ACTIVE, ARCHIVED, RESOLVED).
ACCESS_ANALYZER_CLOSED = ("ARCHIVED", "RESOLVED")
#: Page sizes: each API's documented maximum (read: botocore ``MaxResults`` shapes; Access
#: Analyzer's ``maxResults`` is an unbounded integer, so its documented default page of 100 is asked).
GUARDDUTY_PAGE = 50
SECURITYHUB_PAGE = 100
ACCESS_ANALYZER_PAGE = 100
#: ``guardduty:GetFindings`` takes at most 50 ids (read: botocore ``FindingIds`` max 50).
GUARDDUTY_GET_BATCH = 50
#: ``config:GetConformancePackComplianceSummary`` takes at most 5 pack names (read: botocore).
CONFORMANCE_SUMMARY_BATCH = 5

#: Security Hub's ``SeverityLabel`` enum, most severe first (read: botocore ``SeverityLabel``).
SECURITYHUB_SEVERITY_LABELS: tuple[str, ...] = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL")
#: GuardDuty's severity bands (web: https://docs.aws.amazon.com/guardduty/latest/ug/guardduty_findings-severity.html,
#: read 2026-10-02): Critical 9.0-10.0, High 7.0-8.9, Medium 4.0-6.9, Low 1.0-3.9.
GUARDDUTY_SEVERITY_BANDS: tuple[tuple[float, str], ...] = (
    (9.0, "CRITICAL"),
    (7.0, "HIGH"),
    (4.0, "MEDIUM"),
    (0.0, "LOW"),
)
#: Analyzer types whose findings ``ListFindings`` (v1) returns, with the principal, actions and
#: condition the v2 summary lacks. botocore: "ListFindings is supported only for external access
#: analyzers. You must use ListFindingsV2 for internal and unused access analyzers."
EXTERNAL_ACCESS_ANALYZER_TYPES = frozenset({"ACCOUNT", "ORGANIZATION"})

#: Paginated operations this module reads through the reader's page loop (a test walks them).
PAGINATED_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("guardduty", "list_findings"),
    ("securityhub", "get_findings"),
    ("accessanalyzer", "list_findings"),
    ("accessanalyzer", "list_findings_v2"),
    ("config", "describe_config_rules"),
    ("config", "describe_compliance_by_config_rule"),
    ("config", "describe_conformance_packs"),
    ("config", "get_conformance_pack_compliance_summary"),
)
SINGLE_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("guardduty", "get_findings"),
    ("guardduty", "get_findings_statistics"),
    ("config", "get_custom_rule_policy"),
)


def guardduty_severity_label(score: Any) -> str:
    """GuardDuty's label for a numeric severity, or ``""`` when there is no number."""
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return ""
    return next((label for floor, label in GUARDDUTY_SEVERITY_BANDS if score >= floor), "")


def securityhub_finding_key(product_arn: str, finding_id: str) -> str:
    """A Security Hub finding's natural key: ASFF identifies a finding by (``ProductArn``, ``Id``)."""
    return f"{product_arn}|{finding_id}"


def analyzer_finding_key(analyzer_arn: str, finding_id: str) -> str:
    """An Access Analyzer finding's natural key: a finding id is unique within its analyzer."""
    return f"{analyzer_arn}|{finding_id}"


def standards_id_of(standards_arn: str) -> str:
    """The resource portion of a standard's ARN: what ASFF ``Compliance.AssociatedStandards[].StandardsId``
    names (read: botocore ``AssociatedStandard`` documentation)."""
    parsed = parse_arn(standards_arn)
    return parsed.resource if parsed else ""


@dataclass(frozen=True)
class FindingsLimits:
    """The operator's trims on every findings read (``req-aws-core-secret-findings-settings``), off by default.

    ``max_per_region``: the most findings one service writes per region per run, shared by that service's reads
    there; None is no limit. ``read_budget_seconds``: a read stops at its next page once it has run this long; None
    is no budget. A read either one stops is recorded truncated, with the reason.
    """

    max_per_region: int | None = None
    read_budget_seconds: int | None = None

    @classmethod
    def of(cls, data: dict[str, Any] | Any) -> FindingsLimits:
        """The limits a credential's ``data`` sets (validated by its schema: positive integers or absent)."""

        def positive(key: str) -> int | None:
            value = data.get(key) if hasattr(data, "get") else None
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else None

        return cls(positive("findings_max_per_region"), positive("findings_read_budget_seconds"))


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _when(value: Any) -> datetime | None:
    """A timestamp AWS returned (a datetime, or an ISO 8601 string), in UTC; None when unreadable."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _str_list(values: Any) -> list[str]:
    return sorted({str(v) for v in values if v}) if isinstance(values, list) else []


def _doc(value: Any) -> Any:
    """A finding's own sub-document, JSON-safe, in AWS's shape; None when the finding carries none."""
    return None if value is None else jsonable(value)


def _parameters(raw: Any) -> Any:
    """A Config rule's ``InputParameters``: a JSON object AWS returns as a string. The object when it
    parses to one, ``{}`` when the rule has none, else the string verbatim (never dropped)."""
    if raw in (None, ""):
        return {}
    try:
        parsed = json.loads(str(raw))
    except ValueError:
        return str(raw)
    return parsed if isinstance(parsed, dict) else str(raw)


@dataclass
class Prepared:
    """A parent's findings, read but not yet written: the fields that go on the parent's own node,
    and ``emit``, which writes the findings under the parent once the parent itself was kept."""

    parent_fields: dict[str, Any]
    emit: Callable[[], None] = field(default=lambda: None)


class FindingsReads:
    """The findings and Config-rule half of one landing-zone read. ``reader`` is the landing-zone
    ``_Reader``; every node, edge, surface, notice and AWS call goes through it."""

    def __init__(self, reader: _Reader) -> None:
        self.r = reader

    # -- shared -------------------------------------------------------------

    def _counts(self, labels: list[str], *, complete: bool, truncated: bool | None) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for label in labels:
            counts[label or "UNKNOWN"] = counts.get(label or "UNKNOWN", 0) + 1
        return {
            "active_finding_counts": counts,
            "active_finding_counts_complete": complete,
            "active_findings_truncated": truncated,
        }

    def _concerns(self, from_type: str, from_key: str, target: tuple[str, str] | None, region: str) -> int:
        """A reference edge from a finding to the grid resource it names; 1 when emitted."""
        if target is None or not target[1]:
            return 0
        self.r.add_edge(CONCERNS_RESOURCE, from_type, from_key, target[0], target[1], region)
        return 1

    def _surface(
        self,
        read: _Walk,
        relation: str,
        edge_type: str,
        parent_type: str,
        parent_key: str,
        *,
        count: int,
        skipped: int,
        filter_text: str,
        truncated: bool,
    ) -> None:
        listing = self.r.parent_surface(
            read, relation, edge_type, parent_type, parent_key, count=count, skipped=skipped
        )
        listing.filter = filter_text
        listing.complete = False
        why = (
            f"filter_uncontrolled: the listing depends on the filter {filter_text!r} and no bogus-value control was run"
        )
        previous = listing.reasons.get("enumeration_complete")
        listing.reasons["enumeration_complete"] = f"{previous}; {why}" if previous else why
        if truncated:
            # Its own key: the recorder rewrites the enumeration_complete reason of a filtered
            # surface with its own, and the truncation must survive that.
            listing.reasons["truncated"] = f"truncated: {read.truncation or 'a limit stopped the read'}"

    # -- GuardDuty ----------------------------------------------------------

    def _since(self) -> datetime:
        return datetime.now(UTC) - timedelta(days=CLOSED_WINDOW_DAYS)

    def _guardduty_read(
        self, region: str, detector_id: str, criteria: dict[str, Any], sort: str
    ) -> tuple[_Walk, bool, list[dict[str, Any]], int]:
        """One ``ListFindings`` (to its end, or as far as the operator's limits allow) and its ``GetFindings``:
        ``(listing, truncated, findings, skipped)``."""
        listed, truncated = self.r.findings_walk(
            "guardduty",
            region,
            "list_findings",
            "FindingIds",
            DetectorId=detector_id,
            FindingCriteria=criteria,
            SortCriteria={"AttributeName": sort, "OrderBy": "DESC"},
            MaxResults=GUARDDUTY_PAGE,
        )
        ids = [str(i) for i in listed.items if i]
        skipped = len(listed.items) - len(ids)
        findings: list[dict[str, Any]] = []
        for start in range(0, len(ids), GUARDDUTY_GET_BATCH):
            chunk = ids[start : start + GUARDDUTY_GET_BATCH]
            response, _ = self.r.call("guardduty", region, "get_findings", DetectorId=detector_id, FindingIds=chunk)
            got = [f for f in (response or {}).get("Findings") or [] if isinstance(f, dict)]
            skipped += len(chunk) - len(got)
            findings.extend(got)
        return listed, truncated, findings, skipped

    def guardduty(self, region: str, detector_id: str, detector_key: str, detector_type: str) -> Prepared:
        """Active findings of one detector, for the run's own account, most severe first; then the
        findings it archived in the last ``CLOSED_WINDOW_DAYS`` days, most recently updated first."""
        account = self.r.account_id
        totals_criteria = {"Criterion": {"service.archived": {"Equals": ["false"]}, "accountId": {"Equals": [account]}}}
        since = self.r.since("guardduty", region)
        criteria: dict[str, Any] = {"Criterion": dict(totals_criteria["Criterion"])}
        if since is not None:
            criteria["Criterion"]["updatedAt"] = {"GreaterThanOrEqual": int(since.timestamp() * 1000)}
        closed_since = max(self._since(), since) if since is not None else self._since()
        closed_criteria = {
            "Criterion": {
                "service.archived": {"Equals": ["true"]},
                "accountId": {"Equals": [account]},
                # Epoch milliseconds (GuardDuty's documented form for updatedAt).
                "updatedAt": {"GreaterThanOrEqual": int(closed_since.timestamp() * 1000)},
            }
        }
        filter_text = (
            f"guardduty:ListFindings service.archived=false, accountId={account}; "
            f"and service.archived=true, accountId={account}, updatedAt in the last {CLOSED_WINDOW_DAYS} days"
            + (f"; incremental: updatedAt >= {self.r.iso(since)}" if since is not None else "")
        )
        listed, truncated, findings, skipped = self._guardduty_read(region, detector_id, criteria, "severity")
        closed, closed_cut, closed_findings, closed_skipped = self._guardduty_read(
            region, detector_id, closed_criteria, "updatedAt"
        )

        self.r.mark_read("guardduty", region, [listed, closed], clean=not (truncated or closed_cut or skipped or closed_skipped))
        exact = self._guardduty_statistics(region, detector_id, totals_criteria)
        if exact is not None:
            fields: dict[str, Any] = {
                "active_finding_counts": exact,
                "active_finding_counts_complete": True,
                "active_findings_truncated": truncated if listed.complete else None,
            }
        else:
            fields = self._counts(
                [guardduty_severity_label(f.get("Severity")) for f in findings],
                # An incremental read counts only what changed: a lower bound, never the total.
                complete=listed.complete and not truncated and skipped == 0 and since is None,
                truncated=truncated if listed.complete else None,
            )

        def emit() -> None:
            unwritten = skipped + closed_skipped
            for finding in findings + closed_findings:
                if not self._guardduty_finding(region, detector_id, detector_key, detector_type, finding):
                    unwritten += 1
            self._surface(
                self.r.aggregate([listed, closed]),
                RELATION_GUARDDUTY_FINDINGS,
                HOLDS_GUARDDUTY_FINDING,
                detector_type,
                detector_key,
                count=len(listed.items) + len(closed.items),
                skipped=unwritten,
                filter_text=filter_text,
                truncated=truncated or closed_cut,
            )

        return Prepared(fields, emit)

    def _guardduty_statistics(self, region: str, detector_id: str, criteria: dict[str, Any]) -> dict[str, int] | None:
        """Exact per-label totals from ``GetFindingsStatistics(GroupBy=SEVERITY)``, or None when the
        call failed or answered more groups than one page holds (its input takes no continuation
        token, read: botocore, so a second page cannot be asked for)."""
        response, _ = self.r.call(
            "guardduty",
            region,
            "get_findings_statistics",
            DetectorId=detector_id,
            GroupBy="SEVERITY",
            FindingCriteria=criteria,
            MaxResults=100,
        )
        if response is None or response.get("NextToken"):
            return None
        grouped = (response.get("FindingStatistics") or {}).get("GroupedBySeverity")
        if not isinstance(grouped, list):
            return None
        counts: dict[str, int] = {}
        for group in grouped:
            total = _int((group or {}).get("TotalFindings"))
            label = guardduty_severity_label((group or {}).get("Severity"))
            if total is None or not label:
                return None
            counts[label] = counts.get(label, 0) + total
        return counts

    def _guardduty_finding(
        self, region: str, detector_id: str, detector_key: str, detector_type: str, finding: dict[str, Any]
    ) -> bool:
        arn = str(finding.get("Arn") or "")
        finding_id = str(finding.get("Id") or "")
        if not arn or not finding_id:
            return False
        resource = finding.get("Resource") or {}
        service = finding.get("Service") or {}
        instance_id = str((resource.get("InstanceDetails") or {}).get("InstanceId") or "")
        buckets = [b for b in resource.get("S3BucketDetails") or [] if isinstance(b, dict)]
        access_key = resource.get("AccessKeyDetails") or {}
        user_name = str(access_key.get("UserName") or "")
        lambda_fn = resource.get("LambdaDetails") or {}
        rds = resource.get("RdsDbInstanceDetails") or {}
        ecs = resource.get("EcsClusterDetails") or {}
        resource_id = (
            instance_id
            or ",".join(str(b.get("Name") or "") for b in buckets if b.get("Name"))
            or user_name
            or str((resource.get("EksClusterDetails") or {}).get("Name") or "")
            or str(lambda_fn.get("FunctionName") or "")
            or str(rds.get("DbInstanceIdentifier") or "")
            or str((resource.get("RdsLimitlessDbDetails") or {}).get("DbShardGroupIdentifier") or "")
            or str(ecs.get("Name") or "")
            or str((resource.get("RecoveryPointDetails") or {}).get("RecoveryPointArn") or "")
        )
        severity = finding.get("Severity")
        title = str(finding.get("Title") or "")
        finding_type = str(finding.get("Type") or "")
        instance = resource.get("InstanceDetails") or {}
        fields: dict[str, Any] = {
            "name": (title or finding_type or finding_id)[:255],
            "finding_arn": arn,
            "finding_id": finding_id,
            "detector_id": detector_id,
            "account_id": str(finding.get("AccountId") or self.r.account_id),
            "region": str(finding.get("Region") or region),
            "finding_type": finding_type,
            "severity": float(severity)
            if isinstance(severity, (int, float)) and not isinstance(severity, bool)
            else None,
            "severity_label": guardduty_severity_label(severity),
            "title": title[:1024],
            "resource_type": str(resource.get("ResourceType") or ""),
            "resource_id": resource_id[:1024],
            "first_seen": str(service.get("EventFirstSeen") or ""),
            "last_seen": str(service.get("EventLastSeen") or ""),
            "count": _int(service.get("Count")),
            "archived": _bool(service.get("Archived")),
            "created_at": str(finding.get("CreatedAt") or ""),
            "updated_at": str(finding.get("UpdatedAt") or ""),
            # What the finding says about itself (aws-core-tap#264, Q114c); null when it carries none.
            "description": str(finding.get("Description") or ""),
            "action": _doc(service.get("Action")),
            "network_interfaces": _doc(instance.get("NetworkInterfaces")),
            "evidence": _doc(service.get("Evidence")),
            # AWS cannot tag a GuardDuty finding (lane `none`, tag_lanes.json).
            "tags": {},
        }
        if not self.r.add_node(GUARDDUTY_FINDING, arn, str(fields["name"]), fields, region):
            return False
        self.r.add_edge(HOLDS_GUARDDUTY_FINDING, detector_type, detector_key, GUARDDUTY_FINDING, arn, region)
        if instance_id:
            self._concerns(GUARDDUTY_FINDING, arn, (EC2_INSTANCE, instance_id), region)
        for bucket in buckets:
            bucket_arn = str(bucket.get("Arn") or "") or (
                f"arn:{self.r.partition}:s3:::{bucket['Name']}" if bucket.get("Name") else ""
            )
            self._concerns(GUARDDUTY_FINDING, arn, (S3_BUCKET, bucket_arn), region)
        if user_name and access_key.get("UserType") == "IAMUser":
            # Inferred key: GuardDuty names the user, not its ARN, so the ARN is built with the default
            # path. A user created under another path keys differently and this edge stays dangling.
            account = str(finding.get("AccountId") or self.r.account_id)
            self._concerns(
                GUARDDUTY_FINDING, arn, (IAM_USER, f"arn:{self.r.partition}:iam::{account}:user/{user_name}"), region
            )
        for target_arn in _guardduty_resource_arns(resource):
            target = resolve_arn(target_arn)
            if target is not None and target[0] in GUARDDUTY_CONCERNS_TARGETS:
                self._concerns(GUARDDUTY_FINDING, arn, target, region)
        return True

    # -- Security Hub -------------------------------------------------------

    def standards_subscriptions(self, region: str, hub_arn: str, hub_type: str, standards: _Walk) -> dict[str, str]:
        """One node per enabled standard, contained by the hub. Returns ``{standards id: subscription
        ARN}`` for the control findings' ``EVALUATED_UNDER_STANDARD`` edges."""
        by_standard: dict[str, str] = {}
        skipped = 0
        for item in standards.items:
            arn = str((item or {}).get("StandardsSubscriptionArn") or "")
            if not arn:
                skipped += 1
                continue
            standards_arn = str(item.get("StandardsArn") or "")
            standards_id = standards_id_of(standards_arn)
            name = (
                standards_id.split("/")[1] if standards_id.count("/") >= 1 else (standards_id or arn.rsplit("/", 1)[-1])
            )
            fields = {
                "name": f"{name} ({region})"[:255],
                "subscription_arn": arn,
                "standards_arn": standards_arn,
                "standards_id": standards_id,
                "status": str(item.get("StandardsStatus") or ""),
                "status_reason": str((item.get("StandardsStatusReason") or {}).get("StatusReasonCode") or ""),
                "controls_updatable": str(item.get("StandardsControlsUpdatable") or ""),
                # AWS cannot tag a standards subscription (lane `none`, tag_lanes.json).
                "tags": {},
            }
            if not self.r.add_node(STANDARDS_SUBSCRIPTION, arn, str(fields["name"]), fields, region):
                skipped += 1
                continue
            self.r.add_edge(HOLDS_STANDARDS_SUBSCRIPTION, hub_type, hub_arn, STANDARDS_SUBSCRIPTION, arn, region)
            if standards_id:
                by_standard[standards_id] = arn
        self.r.parent_surface(
            standards,
            RELATION_STANDARDS_SUBSCRIPTIONS,
            HOLDS_STANDARDS_SUBSCRIPTION,
            hub_type,
            hub_arn,
            count=len(standards.items),
            skipped=skipped,
        )
        return by_standard

    def securityhub(self, region: str) -> tuple[Prepared, Callable[[str, str, dict[str, str]], None]]:
        """Active findings for the run's own account in this region, one read per severity label from
        CRITICAL down; then the findings archived in the last ``CLOSED_WINDOW_DAYS`` days. Every read runs
        to its end unless the operator's limits stop it; ``findings_max_per_region`` is shared by all of
        them, most severe first. Returns the hub's count fields (active findings only) and the writer,
        called with the hub's key once the hub is kept."""
        account = self.r.account_id
        reads: list[_Walk] = []
        findings: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        exact = True
        truncated = False
        since = self.r.since("securityhub", region)
        updated = (
            {"UpdatedAt": [{"Start": self.r.iso(since), "End": self.r.iso(self.r.run_started + timedelta(days=1))}]}
            if since is not None
            else {}
        )
        for label in SECURITYHUB_SEVERITY_LABELS:
            read, cut = self.r.findings_walk(
                "securityhub",
                region,
                "get_findings",
                "Findings",
                Filters={
                    "AwsAccountId": [{"Value": account, "Comparison": "EQUALS"}],
                    "Region": [{"Value": region, "Comparison": "EQUALS"}],
                    "RecordState": [{"Value": "ACTIVE", "Comparison": "EQUALS"}],
                    "SeverityLabel": [{"Value": label, "Comparison": "EQUALS"}],
                    **updated,
                },
                MaxResults=SECURITYHUB_PAGE,
            )
            reads.append(read)
            findings.extend(f for f in read.items if isinstance(f, dict))
            counts[label] = len(read.items)
            if cut or not read.complete:
                exact = False
            if cut:
                truncated = True
                break
        active = self.r.aggregate(reads)
        fields = {
            # Security Hub has no count call: the counts are the reads'. An incremental read counts only what
            # changed, so it gives no total, and says so (null) rather than overwrite one with a lower bound.
            "active_finding_counts": counts if since is None else None,
            "active_finding_counts_complete": exact if since is None else None,
            "active_findings_truncated": truncated if active.complete or truncated else None,
        }
        closed_filter = (
            {"UpdatedAt": [{"Start": self.r.iso(max(self._since(), since)), "End": self.r.iso(self.r.run_started + timedelta(days=1))}]}
            if since is not None
            else {"UpdatedAt": [{"DateRange": {"Value": CLOSED_WINDOW_DAYS, "Unit": "DAYS"}}]}
        )
        # Findings whose record Security Hub archived in the window, most recently updated first.
        closed, closed_cut = self.r.findings_walk(
            "securityhub",
            region,
            "get_findings",
            "Findings",
            Filters={
                "AwsAccountId": [{"Value": account, "Comparison": "EQUALS"}],
                "Region": [{"Value": region, "Comparison": "EQUALS"}],
                "RecordState": [{"Value": "ARCHIVED", "Comparison": "EQUALS"}],
                **closed_filter,
            },
            SortCriteria=[{"Field": "UpdatedAt", "SortOrder": "desc"}],
            MaxResults=SECURITYHUB_PAGE,
        )
        reads.append(closed)
        findings.extend(f for f in closed.items if isinstance(f, dict))
        combined = self.r.aggregate(reads)
        self.r.mark_read("securityhub", region, reads, clean=not (truncated or closed_cut))
        filter_text = (
            f"securityhub:GetFindings AwsAccountId={account}, Region={region}, RecordState=ACTIVE, "
            f"one read per SeverityLabel; and RecordState=ARCHIVED, UpdatedAt in the last {CLOSED_WINDOW_DAYS} days"
            + (f"; incremental: UpdatedAt >= {self.r.iso(since)}" if since is not None else "")
        )

        def write(hub_arn: str, hub_type: str, standards: dict[str, str]) -> None:
            unwritten = 0
            for finding in findings:
                if not self._securityhub_finding(region, hub_arn, hub_type, finding, standards):
                    unwritten += 1
            unwritten += sum(1 for r in reads for f in r.items if not isinstance(f, dict))
            self._surface(
                combined,
                RELATION_SECURITYHUB_FINDINGS,
                HOLDS_SECURITYHUB_FINDING,
                hub_type,
                hub_arn,
                count=sum(len(r.items) for r in reads),
                skipped=unwritten,
                filter_text=filter_text,
                truncated=truncated or closed_cut,
            )

        return Prepared(fields), write

    def _securityhub_finding(
        self, region: str, hub_arn: str, hub_type: str, finding: dict[str, Any], standards: dict[str, str]
    ) -> bool:
        finding_id = str(finding.get("Id") or "")
        product_arn = str(finding.get("ProductArn") or "")
        if not finding_id or not product_arn:
            return False
        key = securityhub_finding_key(product_arn, finding_id)
        compliance = finding.get("Compliance") or {}
        associated = _str_list(
            [s.get("StandardsId") for s in compliance.get("AssociatedStandards") or [] if isinstance(s, dict)]
        )
        resources = [r for r in finding.get("Resources") or [] if isinstance(r, dict)]
        title = str(finding.get("Title") or "")
        severity = finding.get("Severity") or {}
        fields: dict[str, Any] = {
            "name": (title or finding_id)[:255],
            "finding_id": finding_id[:512],
            "product_arn": product_arn,
            "product_name": str(finding.get("ProductName") or ""),
            "generator_id": str(finding.get("GeneratorId") or "")[:512],
            "aws_account_id": str(finding.get("AwsAccountId") or ""),
            "region": str(finding.get("Region") or region),
            "title": title[:1024],
            "severity_label": str(severity.get("Label") or ""),
            "severity_normalized": _int(severity.get("Normalized")),
            "workflow_status": str((finding.get("Workflow") or {}).get("Status") or ""),
            "record_state": str(finding.get("RecordState") or ""),
            # Present only on a control finding: "" otherwise.
            "compliance_status": str(compliance.get("Status") or ""),
            "security_control_id": str(compliance.get("SecurityControlId") or ""),
            "associated_standards": associated,
            "resource_types": _str_list([r.get("Type") for r in resources]),
            "resource_ids": _str_list([str(r.get("Id") or "") for r in resources]),
            "first_observed_at": str(finding.get("FirstObservedAt") or ""),
            "last_observed_at": str(finding.get("LastObservedAt") or ""),
            "created_at": str(finding.get("CreatedAt") or ""),
            "updated_at": str(finding.get("UpdatedAt") or ""),
            # What the finding says about itself (aws-core-tap#264, Q114c), in ASFF's shape; null when absent.
            "description": str(finding.get("Description") or ""),
            "types": [str(v) for v in finding.get("Types") or [] if v],
            "remediation": _doc(finding.get("Remediation")),
            "network": _doc(finding.get("Network")),
            "malware": _doc(finding.get("Malware")),
            "vulnerabilities": _doc(finding.get("Vulnerabilities")),
            "product_fields": _doc(finding.get("ProductFields")),
            "compliance_status_reasons": _doc(compliance.get("StatusReasons")),
            "finding_provider_fields": _doc(finding.get("FindingProviderFields")),
            # AWS cannot tag a finding (lane `none`, tag_lanes.json).
            "tags": {},
        }
        if not self.r.add_node(SECURITYHUB_FINDING, key, str(fields["name"]), fields, region):
            return False
        self.r.add_edge(HOLDS_SECURITYHUB_FINDING, hub_type, hub_arn, SECURITYHUB_FINDING, key, region)
        for standards_id in associated:
            subscription = standards.get(standards_id)
            if subscription:
                self.r.add_edge(
                    EVALUATED_UNDER_STANDARD, SECURITYHUB_FINDING, key, STANDARDS_SUBSCRIPTION, subscription, region
                )
        for resource in resources:
            self._concerns(
                SECURITYHUB_FINDING,
                key,
                _asff_target(str(resource.get("Id") or "")),
                region,
            )
        return True

    # -- Access Analyzer ----------------------------------------------------

    def access_analyzer(self, region: str, analyzer_arn: str, analyzer_type: str, parent_type: str) -> Prepared:
        """Active findings of one analyzer on the run's own account's resources; then its ARCHIVED and
        RESOLVED findings, of which those updated in the last ``CLOSED_WINDOW_DAYS`` days are kept. The
        Access Analyzer filter has no date operator (read: botocore ``Criterion``: eq, neq, contains,
        exists), so the window is applied to what the read returns."""
        account = self.r.account_id
        external = analyzer_type in EXTERNAL_ACCESS_ANALYZER_TYPES
        operation = "list_findings" if external else "list_findings_v2"

        def read(statuses: list[str], **window: Any) -> tuple[_Walk, bool]:
            return self.r.findings_walk(
                "accessanalyzer",
                region,
                operation,
                "findings",
                analyzerArn=analyzer_arn,
                filter={"status": {"eq": statuses}, "resourceOwnerAccount": {"eq": [account]}},
                maxResults=ACCESS_ANALYZER_PAGE,
                **window,
            )

        since = self._since()

        def recent(finding: Any) -> bool:
            """In the window as the page arrives, so only recent closed findings count against an
            operator's limit. A finding without a readable updatedAt is kept, never silently dropped."""
            if not isinstance(finding, dict):
                return True
            when = _when(finding.get("updatedAt"))
            return when is None or when >= since

        listed, truncated = read(["ACTIVE"])
        # The closed read has no date filter, so it may page through old findings to find recent ones. It reads
        # every page by default (it had a 50-page bound until rulings Q125a and b); the operator's shared limits
        # govern it as every findings read: findings_max_per_region counts the in-window findings it keeps, and
        # findings_read_budget_seconds bounds how long it pages.
        closed, closed_cut = read(list(ACCESS_ANALYZER_CLOSED), keep=recent)
        findings = [f for f in listed.items if isinstance(f, dict)]
        closed_findings = [f for f in closed.items if isinstance(f, dict)]
        kinds = [str(f.get("findingType") or ("ExternalAccess" if external else "")) for f in findings]
        fields = self._counts(
            kinds, complete=listed.complete and not truncated, truncated=truncated if listed.complete else None
        )
        name = "ListFindings" if external else "ListFindingsV2"
        filter_text = (
            f"accessanalyzer:{name} status=ACTIVE, resourceOwnerAccount={account}; "
            f"and status in ARCHIVED, RESOLVED, resourceOwnerAccount={account}, "
            f"kept when updatedAt is in the last {CLOSED_WINDOW_DAYS} days (applied per page)"
        )

        def emit() -> None:
            unwritten = len(listed.items) - len(findings) + sum(1 for f in closed.items if not isinstance(f, dict))
            for finding in findings + closed_findings:
                if not self._analyzer_finding(region, analyzer_arn, parent_type, finding, external):
                    unwritten += 1
            self._surface(
                self.r.aggregate([listed, closed]),
                RELATION_ANALYZER_FINDINGS,
                HOLDS_ACCESS_ANALYZER_FINDING,
                parent_type,
                analyzer_arn,
                count=len(listed.items) + len(closed.items),
                skipped=unwritten,
                filter_text=filter_text,
                truncated=truncated or closed_cut,
            )

        return Prepared(fields, emit)

    def _analyzer_finding(
        self, region: str, analyzer_arn: str, parent_type: str, finding: dict[str, Any], external: bool
    ) -> bool:
        from .landing_zone import _iso

        finding_id = str(finding.get("id") or "")
        if not finding_id:
            return False
        key = analyzer_finding_key(analyzer_arn, finding_id)
        resource = str(finding.get("resource") or "")
        resource_type = str(finding.get("resourceType") or "")
        principal = finding.get("principal")
        condition = finding.get("condition")
        fields: dict[str, Any] = {
            "name": f"{resource_type or 'resource'} {resource.rsplit(':', 1)[-1] or finding_id}"[:255],
            "finding_id": finding_id,
            "analyzer_arn": analyzer_arn,
            "resource_arn": resource[:2048],
            "resource_type": resource_type,
            "resource_owner_account": str(finding.get("resourceOwnerAccount") or ""),
            "finding_type": str(finding.get("findingType") or ("ExternalAccess" if external else "")),
            "status": str(finding.get("status") or ""),
            # The external-access summary (ListFindings) only; null for a v2 summary, which has none.
            "is_public": _bool(finding.get("isPublic")) if external else None,
            "principal": {str(k): str(v) for k, v in principal.items()}
            if external and isinstance(principal, dict)
            else None,
            "actions": _str_list(finding.get("action")) if external else None,
            # The condition summary: the condition KEYS only. Values (org ids, VPCs, IP ranges) are not kept.
            "condition_keys": sorted(str(k) for k in condition) if external and isinstance(condition, dict) else None,
            "error": str(finding.get("error") or ""),
            "created_at": _iso(finding.get("createdAt")),
            "updated_at": _iso(finding.get("updatedAt")),
            "analyzed_at": _iso(finding.get("analyzedAt")),
            # AWS cannot tag an analyzer finding (lane `none`, tag_lanes.json).
            "tags": {},
        }
        if not self.r.add_node(ACCESS_ANALYZER_FINDING, key, str(fields["name"]), fields, region):
            return False
        self.r.add_edge(HOLDS_ACCESS_ANALYZER_FINDING, parent_type, analyzer_arn, ACCESS_ANALYZER_FINDING, key, region)
        target = {"AWS::S3::Bucket": S3_BUCKET, "AWS::IAM::Role": IAM_ROLE, "AWS::IAM::User": IAM_USER}.get(
            resource_type
        )
        if target and resource.startswith("arn:"):
            self._concerns(ACCESS_ANALYZER_FINDING, key, (target, resource), region)
        return True

    # -- Config rules and conformance packs ----------------------------------

    def config_rules(self, region: str) -> None:
        """Every Config rule in the region (``DescribeConfigRules`` with no names or filters, which
        botocore documents as the full, unfiltered set), with its compliance from
        ``DescribeComplianceByConfigRule`` (all rules, every compliance type). Contained by the
        footprint (``HOSTS_CONFIG_RULE``)."""
        read = self.r.walk("config", region, "describe_config_rules", "ConfigRules")
        compliance = self.r.walk("config", region, "describe_compliance_by_config_rule", "ComplianceByConfigRules")
        by_name: dict[str, dict[str, Any]] = {
            str(c.get("ConfigRuleName") or ""): (c.get("Compliance") or {})
            for c in compliance.items
            if isinstance(c, dict)
        }
        skipped = 0
        for rule in read.items:
            arn = str((rule or {}).get("ConfigRuleArn") or "")
            if not arn:
                skipped += 1
                continue
            name = str(rule.get("ConfigRuleName") or arn.rsplit("/", 1)[-1])
            source = rule.get("Source") or {}
            policy = source.get("CustomPolicyDetails") or {}
            state = by_name.get(name)
            contributors = (state or {}).get("ComplianceContributorCount") or {}
            known = compliance.complete or state is not None
            fields = {
                "name": name[:255],
                "rule_arn": arn,
                "rule_name": name[:128],
                "rule_id": str(rule.get("ConfigRuleId") or ""),
                "description": str(rule.get("Description") or "")[:256],
                "source_owner": str(source.get("Owner") or ""),
                "source_identifier": str(source.get("SourceIdentifier") or "")[:256],
                "state": str(rule.get("ConfigRuleState") or ""),
                "created_by": str(rule.get("CreatedBy") or ""),
                "maximum_execution_frequency": str(rule.get("MaximumExecutionFrequency") or ""),
                # null when the compliance listing failed before naming this rule; "" when it read to
                # its end and did not name the rule (no evaluation yet).
                "compliance_type": str((state or {}).get("ComplianceType") or "") if known else None,
                "non_compliant_resource_count": _int(contributors.get("CappedCount")) if state is not None else None,
                "non_compliant_count_capped": _bool(contributors.get("CapExceeded")) if state is not None else None,
                # What the rule evaluates and with what (aws-core-tap#264, Q114c).
                "scope": _doc(rule.get("Scope")) or {},
                "input_parameters": _parameters(rule.get("InputParameters")),
                "policy_runtime": str(policy.get("PolicyRuntime") or ""),
                "policy_text": self._policy_text(region, name, source),
                "tags": self.r.tags("config", region, "list_tags_for_resource", "list_kv", "Tags", ResourceArn=arn),
            }
            if not self.r.add_node(CONFIG_RULE, arn, name, fields, region):
                skipped += 1
                continue
            self.r.hosts(HOSTS_CONFIG_RULE, region, CONFIG_RULE, arn)
        if not compliance.complete:
            self.r.notice(
                "warn",
                "CONFIG_RULE_COMPLIANCE_INCOMPLETE",
                f"config:DescribeComplianceByConfigRule in {region} did not read to its end ({compliance.code}); "
                "rules it did not name carry a null compliance.",
                region=region,
            )
        self.r.footprint_surface(
            region, HOSTS_CONFIG_RULE, RELATION_CONFIG_RULES, read, count=len(read.items), skipped=skipped
        )

    def _policy_text(self, region: str, name: str, source: dict[str, Any]) -> str | None:
        """A custom policy rule's Guard policy body: ``""`` for a rule of another kind (it has none),
        the text ``DescribeConfigRules`` returned when it returned one, else ``GetCustomRulePolicy``'s,
        and None when that call failed."""
        if source.get("Owner") != "CUSTOM_POLICY":
            return ""
        inline = (source.get("CustomPolicyDetails") or {}).get("PolicyText")
        if inline:
            return str(inline)
        response, _ = self.r.call("config", region, "get_custom_rule_policy", ConfigRuleName=name)
        return None if response is None else str(response.get("PolicyText") or "")

    def conformance_packs(self, region: str) -> None:
        """Every conformance pack in the region with its compliance summary. Contained by the
        footprint (``HOSTS_CONFORMANCE_PACK``)."""
        from .landing_zone import _iso

        read = self.r.walk("config", region, "describe_conformance_packs", "ConformancePackDetails")
        packs = [p for p in read.items if isinstance(p, dict) and p.get("ConformancePackArn")]
        names = sorted({str(p.get("ConformancePackName") or "") for p in packs} - {""})
        summary: dict[str, str] = {}
        summary_failed = False
        for start in range(0, len(names), CONFORMANCE_SUMMARY_BATCH):
            got = self.r.walk(
                "config",
                region,
                "get_conformance_pack_compliance_summary",
                "ConformancePackComplianceSummaryList",
                ConformancePackNames=names[start : start + CONFORMANCE_SUMMARY_BATCH],
            )
            summary_failed = summary_failed or not got.complete
            for row in got.items:
                if isinstance(row, dict) and row.get("ConformancePackName"):
                    summary[str(row["ConformancePackName"])] = str(row.get("ConformancePackComplianceStatus") or "")
        skipped = len(read.items) - len(packs)
        for pack in packs:
            arn = str(pack["ConformancePackArn"])
            name = str(pack.get("ConformancePackName") or arn.rsplit("/", 1)[-1])
            fields = {
                "name": name[:255],
                "pack_arn": arn,
                "pack_name": name[:256],
                "pack_id": str(pack.get("ConformancePackId") or ""),
                "created_by": str(pack.get("CreatedBy") or ""),
                "delivery_s3_bucket": str(pack.get("DeliveryS3Bucket") or ""),
                "last_update_requested_at": _iso(pack.get("LastUpdateRequestedTime")),
                # null when the summary read failed before naming this pack.
                "compliance_status": summary.get(name, None if summary_failed else ""),
                "tags": self.r.tags("config", region, "list_tags_for_resource", "list_kv", "Tags", ResourceArn=arn),
            }
            if not self.r.add_node(CONFORMANCE_PACK, arn, name, fields, region):
                skipped += 1
                continue
            self.r.hosts(HOSTS_CONFORMANCE_PACK, region, CONFORMANCE_PACK, arn)
        self.r.footprint_surface(
            region, HOSTS_CONFORMANCE_PACK, RELATION_CONFORMANCE_PACKS, read, count=len(read.items), skipped=skipped
        )


def _guardduty_resource_arns(resource: dict[str, Any]) -> list[str]:
    """The ARNs a GuardDuty finding's ``Resource`` names beyond the instance, buckets and access-key
    user (aws-core-tap#264, ruling Q115b): a Lambda function, an RDS instance or Aurora Limitless shard
    group, an ECS cluster and task, an EKS cluster, and the EBS volumes a malware scan scanned. Read:
    botocore guardduty ``Resource``. Each is resolved by ``arn_resolver`` and the edge is sent only
    when it resolves to a type the model's ``CONCERNS_RESOURCE`` declaration names
    (``GUARDDUTY_CONCERNS_TARGETS``). An EBS snapshot, an AMI and a backup recovery point are named too,
    but no aws_core type models them, so they are not read; the recovery point stays in
    ``resource_id``."""
    ecs = resource.get("EcsClusterDetails") or {}
    candidates = [
        (resource.get("LambdaDetails") or {}).get("FunctionArn"),
        (resource.get("RdsDbInstanceDetails") or {}).get("DbInstanceArn"),
        (resource.get("RdsLimitlessDbDetails") or {}).get("DbShardGroupArn"),
        ecs.get("Arn"),
        (ecs.get("TaskDetails") or {}).get("Arn"),
        (resource.get("EksClusterDetails") or {}).get("Arn"),
    ]
    volumes = (resource.get("EbsVolumeDetails") or {}).get("ScannedVolumeDetails") or []
    candidates += [v.get("VolumeArn") for v in volumes if isinstance(v, dict)]
    return [str(c) for c in candidates if isinstance(c, str) and c.startswith("arn:")]


def _asff_target(resource_id: str) -> tuple[str, str] | None:
    """``(entity type, natural key)`` of the grid resource an ASFF ``Resources[]`` entry names, or None
    (aws-core-tap#242, #252). Security Hub names a resource by ARN (read: ASFF ``Resource.Id``), and an account by
    the pseudo-id ``AWS::::Account:<id>``; ``arn_resolver`` reads the target from the id alone, through each type's
    ARN key or its identity declaration (an EC2 instance's ``instance_id`` from ``instance/${InstanceId}``, the
    account's ``account_id`` from its declared ``other_ids``). The ASFF ``Type`` plays no part. An id no single
    keyed type claims names nothing and stays a string in ``resource_ids``."""
    return resolve_arn(resource_id)


__all__ = [
    "CLOSED_WINDOW_DAYS",
    "CONCERNS_RESOURCE",
    "FindingsLimits",
    "READ_THROUGH",
    "WATERMARK_OVERLAP",
    "read_through_of",
    "watermark_key",
    "GUARDDUTY_CONCERNS_TARGETS",
    "PAGINATED_OPERATIONS",
    "SINGLE_OPERATIONS",
    "FindingsReads",
    "Prepared",
    "analyzer_finding_key",
    "guardduty_severity_label",
    "securityhub_finding_key",
    "standards_id_of",
]
