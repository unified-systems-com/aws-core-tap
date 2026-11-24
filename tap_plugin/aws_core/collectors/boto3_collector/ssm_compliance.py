"""SSM patch state projected into compliance_core (aws-core-tap#281, rulings Q141a, Q141b and Q141c, 2026-11-23).

Spec: specs/spec-aws-core-v0.md (req-aws-core-ssm-compliance) and specs/spec-aws-core-secrets.md
(req-aws-core-secret-findings-settings).

Built as the Inspector projection is (:mod:`.compliance`), behind a gate of its own: ``data.ssm_compliance_findings``
in the collector's credential turns it on, and it is off by default, as ``inspector_compliance_findings`` is (Q141c).
When on, the run's last step reads the stored SSM patch state of its account (the managed instances, their live
``REPORTS_PATCH`` edges and the patches those reach; the stored rows, not the API response, so turning it on later
back-fills) and writes one more GRIFT batch:

    aws_ssm_patch -RESOLVES_VULNERABILITY-> compliance_vulnerability (vuln_id), for each CVE in its cve_ids  (Q141a)
    compliance_finding (source aws_ssm_patch, source_key = <account>:<instance id>:<CVE>)                     (Q141b)
      -CONCERNS_COMPLIANCE_VULNERABILITY {fix_state: fixed}-> compliance_vulnerability
    <the instance> -CARRIES_COMPLIANCE_FINDING-> compliance_finding

A finding is written for an (instance, CVE) pair only while a patch that resolves the CVE is not in effect on the
instance (:data:`EXPOSED_STATES`), and is written ``resolved`` once every patch the instance reports for the CVE is in
a state that is not exposure, when a finding for the pair is already held. compliance_core is written by slug and read
through the registries, never imported; readiness is the Inspector projection's own check (:func:`.compliance.readiness`),
since both write the same narrow contract.

Every decision is a pure function of plain data (:func:`project`), so the rules are tested without a grid.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .authority import COMPLETE, EDGE_READS
from .compliance import (
    CARRIES,
    CONCERNS,
    FINDING,
    NAME_LIMIT,
    SOURCE_KEY_LIMIT,
    SUMMARY_LIMIT,
    VULN_ID_LIMIT,
    VULNERABILITY,
    HeldVulnerability,
    Projection,
    _CVE,
    _vulnerability,
)
from .edges import edge_envelope
from .identity import composite_natural_key, node_ref
from .ssm_patch import EC2_RESOURCE_TYPE, MANAGED_INSTANCE_TYPE, PATCH_TYPE

#: The credential key that turns the projection on (Q141c: a gate of its own, off by default like Inspector's).
OPTION = "ssm_compliance_findings"
#: The producer half of the neutral finding's natural key.
SOURCE = "aws_ssm_patch"
#: aws_core's edge from a patch to each vulnerability its CVEIds name (Q141a).
RESOLVES = "RESOLVES_VULNERABILITY__aws_core"
#: The edge the stored patch state is read from.
REPORTS = "REPORTS_PATCH__aws_core"
EC2_INSTANCE = "aws_core__aws_ec2_instance"
#: The dimension that names the account owning a managed instance (collector.py stamps it on every node).
ACCOUNT_DIMENSION = "aws.account"

#: The DescribeInstancePatches states in which the patch that resolves a CVE is not in effect on the instance, so the
#: instance is exposed to the CVE. MISSING and FAILED are ruled (Q141b); the other two in, and INSTALLED_REJECTED out,
#: are ruled Q148b. INSTALLED_PENDING_REBOOT: the patch is on
#: disk but AWS says it may not be in effect until the reboot, and Patch Manager reports the node non-compliant for
#: it. AVAILABLE_SECURITY_UPDATE: a security patch the baseline has not approved is available and not installed, so
#: the CVE is as present as with MISSING; only the baseline's approval differs. Not exposure: INSTALLED and
#: INSTALLED_OTHER (in effect), INSTALLED_REJECTED (installed, so the fix is in effect; that the baseline rejects it is
#: a patch-policy fact, held on the REPORTS_PATCH edge and the compliance summary, not a vulnerability) and
#: NOT_APPLICABLE.
EXPOSED_STATES: frozenset[str] = frozenset({"MISSING", "FAILED", "INSTALLED_PENDING_REBOOT", "AVAILABLE_SECURITY_UPDATE"})
#: The fix, on the CONCERNS pair: the patch that resolves the CVE exists, since the patch is what names it.
FIX_STATE = "fixed"


def enabled(data: Mapping[str, Any]) -> bool:
    """Whether the credential turns the projection on; absent or false is off."""
    return data.get(OPTION) is True


@dataclass(frozen=True)
class Report:
    """One stored ``REPORTS_PATCH``: the instance, the patch it reaches and the state the instance reports."""

    instance_id: str
    resource_type: str | None
    partition: str
    operating_system: str
    kb_id: str
    title: str | None
    cve_ids: tuple[str, ...]
    state: str | None
    severity: str | None


@dataclass
class _Pair:
    vuln_id: str
    resource_type: str | None
    reports: list[Report] = field(default_factory=list)


def source_key(account_id: str, instance_id: str, cve: str) -> str:
    """The finding's key under ``aws_ssm_patch``: one finding per (instance, CVE), scoped by the owning account."""
    return f"{account_id}:{instance_id}:{cve}"


def finding_ref(key: str) -> str:
    return node_ref(FINDING, composite_natural_key({"source": SOURCE, "source_key": key}))


def patch_ref(report: Report) -> str:
    """The patch, named by its composite key so the endpoint resolves against the live grid."""
    return node_ref(
        PATCH_TYPE,
        composite_natural_key(
            {"partition": report.partition, "operating_system": report.operating_system, "kb_id": report.kb_id}
        ),
    )


def carrier_of(instance_id: str, resource_type: str | None) -> tuple[str, str]:
    """``(entity type, natural key)`` of the instance that carries the finding (Q148a): the EC2 instance for an
    EC2-backed node, the node Inspector's finding for the same host is carried by; the managed instance for a hybrid
    one, which has no other node."""
    if resource_type == EC2_RESOURCE_TYPE:
        return EC2_INSTANCE, instance_id
    return MANAGED_INSTANCE_TYPE, instance_id


def names_of(reports: Iterable[Report]) -> set[str]:
    """Every CVE id the reports' patches name, to look up as a held vulnerability's id or alias."""
    return {cve for report in reports for cve in report.cve_ids if cve}


@dataclass(frozen=True)
class CompleteRead:
    """One managed instance's ``REPORTS_PATCH`` read in this run, when it was ``complete``: every edge it asserted, as
    reports. A failed or partial read is never one (Q161a)."""

    resource_type: str | None
    reports: tuple[Report, ...]


def project(
    reports: Iterable[Report],
    held: Iterable[HeldVulnerability],
    *,
    account_id: str,
    held_open: Iterable[str] = (),
    complete: Mapping[str, CompleteRead] | None = None,
) -> Projection:
    """The patch links, vulnerabilities, findings and edges for ``reports``.

    ``held_open`` is the ``source_key`` of every ``aws_ssm_patch`` finding the grid holds that is not resolved. A held
    open finding is written ``resolved`` on a positive record only, never on the mere absence of a report:

    - its pair is reported with no exposed patch (a stored state that is not exposure, such as ``INSTALLED_REJECTED``);
    - or (George's ruling Q161 option a) its instance is in ``complete``, the instances whose ``REPORTS_PATCH`` read
      was ``complete`` in this run, and that read asserted no exposed patch for the CVE. Since Q147 an installed patch
      is no edge, so a closed gap is the pair's absence from a complete read. The caller passes, for those instances,
      the read's own reports in ``reports`` rather than the stored edges, so an edge the read left behind (a removal
      proposal not yet applied) is not read as exposure. An instance with no complete read in this run, whether its
      read failed or was partial or the instance is no longer reported at all, resolves nothing by absence.

    A CVE token that is not a CVE id, or longer than ``vuln_id`` holds, is skipped and said; so is a CVE that names
    two held vulnerabilities (ambiguous, not guessed between), with its patch link and its findings.
    """
    out = Projection()
    index: dict[str, set[str]] = {}
    by_id: dict[str, HeldVulnerability] = {}
    for vulnerability in held:
        by_id[vulnerability.vuln_id] = vulnerability
        for name in (vulnerability.vuln_id, *vulnerability.aliases):
            index.setdefault(name, set()).add(vulnerability.vuln_id)
    held_keys = set(held_open)
    staged: set[str] = set()
    linked: set[tuple[str, str]] = set()
    refused: set[str] = set()
    pairs: dict[tuple[str, str], _Pair] = {}

    def vulnerability_of(cve: str, named_by: str) -> str | None:
        """The vuln_id a CVE resolves to (found by id or alias, else staged), or None when it is refused."""
        if cve in refused:
            return None
        if not _CVE.match(cve) or len(cve) > VULN_ID_LIMIT:
            refused.add(cve)
            out.notices.append(("SSM_COMPLIANCE_CVE_SKIPPED", f"{named_by}: {cve!r} is not a CVE id; not linked"))
            return None
        found = index.get(cve, set())
        if len(found) > 1:
            refused.add(cve)
            out.notices.append(
                ("SSM_COMPLIANCE_VULNERABILITY_AMBIGUOUS", f"{cve} names {len(found)} vulnerabilities; not projected")
            )
            return None
        if found:
            return by_id[next(iter(found))].vuln_id
        if cve not in staged:
            staged.add(cve)
            out.nodes.append(_vulnerability(cve, None, aliases=[]))
        return cve

    ordered = sorted(reports, key=lambda r: (r.instance_id, r.operating_system, r.kb_id))
    for report in ordered:
        for cve in report.cve_ids:
            vuln_id = vulnerability_of(cve, report.kb_id)
            if vuln_id is None:
                continue
            ref = patch_ref(report)
            if (ref, vuln_id) not in linked:
                linked.add((ref, vuln_id))
                out.edges.append(
                    edge_envelope(RESOLVES, from_ref=ref, to_ref=node_ref(VULNERABILITY, vuln_id), dimensions={})
                )
            pair = pairs.setdefault((report.instance_id, cve), _Pair(vuln_id, report.resource_type))
            pair.reports.append(report)
    for (instance_id, cve), pair in sorted(pairs.items()):
        key = source_key(account_id, instance_id, cve)
        if len(key) > SOURCE_KEY_LIMIT:
            out.skipped += 1
            out.notices.append(("SSM_COMPLIANCE_ROW_SKIPPED", f"{instance_id} {cve}: the finding key is too long"))
            continue
        exposed = [r for r in pair.reports if r.state in EXPOSED_STATES]
        if not exposed and key not in held_keys:
            continue
        _finding(out, key, instance_id, cve, pair, exposed)
    # Q161a: a held open finding whose instance's complete read this run asserted nothing for its CVE.
    for key in sorted(held_keys):
        parsed = parse_source_key(account_id, key)
        if parsed is None:
            continue
        instance_id, cve = parsed
        read = (complete or {}).get(instance_id)
        if read is None or (instance_id, cve) in pairs:
            continue  # no complete read this run, or the pair is reported and was decided above
        vuln_id = vulnerability_of(cve, key)
        if vuln_id is None:
            continue
        _finding(out, key, instance_id, cve, _Pair(vuln_id, read.resource_type), [])
    return out


def parse_source_key(account_id: str, key: str) -> tuple[str, str] | None:
    """``(instance id, CVE id)`` of an ``aws_ssm_patch`` finding key of ``account_id``, or None for another account's.
    A CVE id has no colon, so the CVE is the last segment and the instance id what lies between."""
    prefix = f"{account_id}:"
    if not key.startswith(prefix) or key.count(":") < 2:
        return None
    instance_id, _, cve = key[len(prefix) :].rpartition(":")
    return (instance_id, cve) if instance_id and cve else None


def _finding(out: Projection, key: str, instance_id: str, cve: str, pair: _Pair, exposed: list[Report]) -> None:
    """Stage one neutral finding, its CONCERNS edge and its carrier edge."""
    shown = exposed or pair.reports
    severities = sorted({r.severity for r in shown if r.severity})
    kb_ids = sorted({r.kb_id for r in shown})
    summary = " ".join(p for p in (", ".join(severities) or None, cve, ", ".join(kb_ids)) if p)[:SUMMARY_LIMIT]
    states = sorted({f"{r.kb_id} {r.state}" for r in pair.reports})
    if not pair.reports:  # resolved by a complete read that asserted no exposed patch for the CVE (Q161a)
        states = ["no exposed patch in the instance's latest complete DescribeInstancePatches read"]
    titles = sorted({r.title for r in shown if r.title})
    fields: dict[str, Any] = {
        "source": SOURCE,
        "source_key": key,
        "name": f"{cve} on {instance_id}"[:NAME_LIMIT],
        "summary": summary,
        "description": "; ".join([*titles, *states]),
        "status": "open" if exposed else "resolved",
    }
    ref = finding_ref(key)
    out.nodes.append({"entity": {"ref": ref, "entity_type": FINDING, "name": fields["name"], "dimensions": {}}, "node": fields})
    out.edges.append(
        edge_envelope(
            CONCERNS,
            from_ref=ref,
            to_ref=node_ref(VULNERABILITY, pair.vuln_id),
            dimensions={},
            properties={"fix_state": FIX_STATE},
        )
    )
    carrier_type, carrier_key = carrier_of(instance_id, pair.resource_type)
    out.edges.append(edge_envelope(CARRIES, from_ref=node_ref(carrier_type, carrier_key), to_ref=ref, dimensions={}))
    out.projected += 1


# --- the grid reads ----------------------------------------------------------------------------------------------


def stored_reports(account_id: str) -> list[Report]:
    """Every live ``REPORTS_PATCH`` from the account's managed instances, with the patch it reaches (a read; nothing is
    written here). Only aws_core rows are read."""
    from tap_grid.dimension_names import containment
    from tap_grid.models import Edge
    from tap_plugin.aws_core.models.ssm_managed_instance import SsmManagedInstance
    from tap_plugin.aws_core.models.ssm_patch import SsmPatch

    instances = {
        row["entity_id"]: row
        for row in SsmManagedInstance.objects.filter(
            entity__dimensions__contains=containment(ACCOUNT_DIMENSION, account_id)
        ).values("entity_id", "instance_id", "resource_type")
    }
    if not instances:
        return []
    edges = list(
        Edge.objects.filter(
            edge_type=REPORTS, from_entity_id__in=list(instances), to_entity__deleted_at__isnull=True
        ).values("from_entity_id", "to_entity_id", "properties")
    )
    patches = {
        row["entity_id"]: row
        for row in SsmPatch.objects.filter(entity_id__in={e["to_entity_id"] for e in edges}).values(
            "entity_id", "partition", "operating_system", "kb_id", "title", "cve_ids"
        )
    }
    out: list[Report] = []
    for edge in edges:
        instance, patch = instances.get(edge["from_entity_id"]), patches.get(edge["to_entity_id"])
        if instance is None or patch is None or not patch["kb_id"]:
            continue
        properties = edge["properties"] or {}
        out.append(
            Report(
                instance_id=str(instance["instance_id"]),
                resource_type=instance["resource_type"],
                partition=str(patch["partition"]),
                operating_system=str(patch["operating_system"]),
                kb_id=str(patch["kb_id"]),
                title=patch["title"],
                cve_ids=tuple(str(c) for c in patch["cve_ids"] or () if c),
                state=properties.get("state"),
                severity=properties.get("severity"),
            )
        )
    return out


def complete_reads(walks: Iterable[Any]) -> dict[str, CompleteRead]:
    """Instance id -> its ``REPORTS_PATCH`` read in this run's SSM walks (``ssm_patch.SsmWalk``), for every instance
    whose read was ``complete``; each asserted edge becomes a report, its patch read from the same walk (Q161a).

    An instance with no patch state (``DescribeInstancePatchStates`` holds no scan result for it: never scanned, or the
    state aged out) is left out: its empty read is an absence of evidence, not a scan showing its gaps gone, so like
    a vanished instance it resolves nothing."""
    out: dict[str, CompleteRead] = {}
    for walk in walks:
        for instance in walk.instances:
            if (instance.get(EDGE_READS) or {}).get("_patches") != COMPLETE:
                continue
            if not instance.get("_patch_state"):
                continue  # no scan result: nothing positive to resolve by
            instance_id = str(instance.get("InstanceId") or "")
            if not instance_id:
                continue
            reports: list[Report] = []
            for edge in instance.get("_patches") or []:
                patch = walk.patches.get(edge["key"])
                if patch is None:
                    continue
                properties = edge.get("properties") or {}
                reports.append(
                    Report(
                        instance_id=instance_id,
                        resource_type=instance.get("ResourceType"),
                        partition=str(edge["key"]).split(":", 1)[0],
                        operating_system=str(patch["OperatingSystem"]),
                        kb_id=str(patch["KBId"]),
                        title=patch.get("Title"),
                        cve_ids=tuple(str(c) for c in patch.get("_cve_ids") or () if c),
                        state=properties.get("state"),
                        severity=properties.get("severity"),
                    )
                )
            out[instance_id] = CompleteRead(instance.get("ResourceType"), tuple(reports))
    return out


def merged_reports(stored: Iterable[Report], complete: Mapping[str, CompleteRead]) -> list[Report]:
    """The stored reports of every instance with no complete read this run, and this run's own reports for those with
    one, so an edge a complete read left behind is never read as exposure (Q161a)."""
    kept = [r for r in stored if r.instance_id not in complete]
    return kept + [r for read in complete.values() for r in read.reports]


def held_open_for_instances(account_id: str, instance_ids: Iterable[str]) -> set[str]:
    """The ``source_key`` of every live, unresolved ``aws_ssm_patch`` finding of the account on any of
    ``instance_ids``, read by slug: the findings a complete read may resolve by asserting nothing (Q161a)."""
    from django.db.models import Q
    from tap_grid.registry import get_model_class

    wanted = sorted({i for i in instance_ids if i})
    if not wanted:
        return set()
    model = get_model_class(FINDING)
    found: set[str] = set()
    for start in range(0, len(wanted), 200):
        clause = Q()
        for instance_id in wanted[start : start + 200]:
            clause |= Q(source_key__startswith=source_key(account_id, instance_id, ""))
        rows = model.objects.filter(clause, source=SOURCE).exclude(status="resolved")
        found.update(str(k) for k in rows.values_list("source_key", flat=True))
    return {k for k in found if (parsed := parse_source_key(account_id, k)) is not None and parsed[0] in wanted}


def held_open_findings(keys: Iterable[str]) -> set[str]:
    """The ``source_key`` of every live ``aws_ssm_patch`` finding among ``keys`` that is not resolved, read by slug."""
    from tap_grid.registry import get_model_class

    wanted = sorted({k for k in keys if k})
    if not wanted:
        return set()
    model = get_model_class(FINDING)
    rows = model.objects.filter(source=SOURCE, source_key__in=wanted).exclude(status="resolved")
    return {str(k) for k in rows.values_list("source_key", flat=True)}


def resolvable_keys(account_id: str, reports: Iterable[Report]) -> set[str]:
    """The finding keys a resolution could apply to: each reported (instance, CVE) pair none of whose patches is
    exposed. An exposed pair is written open whatever is held, so it is not looked up."""
    exposed: set[str] = set()
    every: set[str] = set()
    for report in reports:
        for cve in report.cve_ids:
            if not cve:
                continue
            key = source_key(account_id, report.instance_id, cve)
            every.add(key)
            if report.state in EXPOSED_STATES:
                exposed.add(key)
    return every - exposed


__all__ = [
    "EXPOSED_STATES",
    "CompleteRead",
    "complete_reads",
    "held_open_for_instances",
    "merged_reports",
    "parse_source_key",
    "OPTION",
    "RESOLVES",
    "SOURCE",
    "Report",
    "carrier_of",
    "enabled",
    "held_open_findings",
    "names_of",
    "project",
    "resolvable_keys",
    "source_key",
    "stored_reports",
]
