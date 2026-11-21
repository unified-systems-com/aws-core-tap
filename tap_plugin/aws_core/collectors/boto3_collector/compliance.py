"""Inspector findings projected into compliance_core (aws-core-tap#261).

Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-inspector-compliance) and specs/spec-aws-core-secrets.md
(req-aws-core-secret-inspector-compliance).

Off by default: ``data.inspector_compliance_findings`` in the collector's credential turns it on. When on, the run's
last step reads the live ``aws_inspector2_finding`` rows of its account (the stored rows, not the API response, so
turning it on later back-fills) and writes one more GRIFT batch of compliance_core's neutral shape:

    compliance_finding (source aws_inspector, source_key = the finding ARN)
      -CONCERNS_COMPLIANCE_VULNERABILITY {fixed_versions, fix_state}-> compliance_vulnerability (vuln_id)
    <carrier> -CARRIES_COMPLIANCE_FINDING-> compliance_finding

compliance_core is an OPTIONAL ``depends_on`` of aws_core. Its types and edges are written by slug and read through
the entity and edge registries; nothing in this module imports compliance_core code, and aws_core's pyproject does not
name it. :func:`readiness` is the one check of what the projection needs; the self-test and the run both call it.

Every decision is a pure function of plain data (:func:`project`), so the rules are tested without a grid.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .edges import edge_envelope
from .identity import composite_natural_key, node_ref
from .inspector import concerned_resource

#: The credential key that turns the projection on (req-aws-core-secret-inspector-compliance).
OPTION = "inspector_compliance_findings"
#: The producer half of the neutral finding's natural key.
SOURCE = "aws_inspector"
#: compliance_core's slug, and the first release that carries everything below as written (fix_state 0.8.8,
#: dimension declarations 0.8.12, one CARRIES_COMPLIANCE_FINDING per pair 0.8.13).
PLUGIN = "compliance_core"
MIN_VERSION = "0.8.13"

FINDING = "compliance_core__compliance_finding"
VULNERABILITY = "compliance_core__compliance_vulnerability"
CONCERNS = "CONCERNS_COMPLIANCE_VULNERABILITY__compliance_core"
CARRIES = "CARRIES_COMPLIANCE_FINDING__compliance_core"
#: computing_core's package (a hard dependency of aws_core): the carrier of an image finding's neutral finding.
PACKAGE = "computing_core__package"
#: The fields the projection writes on each type: the narrow contract the spec names.
NEEDED_FIELDS: dict[str, tuple[str, ...]] = {
    FINDING: ("source", "source_key", "name", "summary", "description", "status", "first_detected_at"),
    VULNERABILITY: ("vuln_id", "aliases", "cvss_score", "cvss_vector", "cvss_version", "cvss_source"),
}
NEEDED_EDGES: tuple[str, ...] = (CONCERNS, CARRIES)
#: The CONCERNS properties it writes, and the fix_state values it maps to.
NEEDED_PROPERTIES: tuple[str, ...] = ("fixed_versions", "fix_state")
#: Inspector's code finding type: projected with no vulnerability record (ruling Q124b).
CODE_VULNERABILITY = "CODE_VULNERABILITY"
FIX_STATES: dict[str, str] = {"YES": "fixed", "NO": "not-fixed", "PARTIAL": "fixed"}

#: compliance_core's column limits (name 255, summary 500, source_key 512, vuln_id 128).
NAME_LIMIT = 255
SUMMARY_LIMIT = 500
SOURCE_KEY_LIMIT = 512
VULN_ID_LIMIT = 128

_CVE = re.compile(r"^CVE-\d{4}-\d{4,}$")


def enabled(data: Mapping[str, Any]) -> bool:
    """Whether the credential turns the projection on; absent or false is off."""
    return data.get(OPTION) is True


def _plugin_version() -> str | None | bool:
    """compliance_core's manifest version; False when the plugin is not loaded, None when it names no version."""
    from django.apps import apps

    for config in apps.get_app_configs():
        manifest = getattr(config, "manifest", None)
        if getattr(manifest, "slug", None) == PLUGIN:
            version = getattr(manifest, "plugin_version", None)
            return str(version) if version else None
    return False


def readiness() -> str | None:
    """Why the projection cannot run, or None when compliance_core is installed, at least ``MIN_VERSION``, and
    carries every type, field, edge and edge property the projection writes."""
    from packaging.version import InvalidVersion, Version

    from tap_grid.constraints import get_edge_property_schema, get_edge_type_constraints
    from tap_grid.registry import get_model_class

    version = _plugin_version()
    if version is False:
        return f"{PLUGIN} is not installed: the optional dependency the projection writes into is absent"
    if version is None:
        return f"{PLUGIN} is installed but its manifest names no version, so the {MIN_VERSION} floor cannot be checked"
    try:
        too_old = Version(str(version)) < Version(MIN_VERSION)
    except InvalidVersion:
        return f"{PLUGIN} {version} is not a version the {MIN_VERSION} floor can be compared with"
    if too_old:
        return f"{PLUGIN} {version} is older than {MIN_VERSION}, the first release with every type and edge written"
    for entity_type, fields in NEEDED_FIELDS.items():
        try:
            model = get_model_class(entity_type)
        except KeyError:
            return f"{PLUGIN} {version} does not register {entity_type}"
        declared = set(getattr(model, "FIELD_CRUD_SCHEMA", {}) or {})
        missing = [f for f in fields if f not in declared]
        if missing:
            return f"{PLUGIN} {version}: {entity_type} lacks {', '.join(missing)}"
    for edge_type in NEEDED_EDGES:
        if get_edge_type_constraints(edge_type) is None:
            return f"{PLUGIN} {version} does not register the edge {edge_type}"
    properties = (get_edge_property_schema(CONCERNS) or {}).get("properties") or {}
    missing = [p for p in NEEDED_PROPERTIES if p not in properties]
    if missing:
        return f"{PLUGIN} {version}: {CONCERNS} lacks the propert{'ies' if len(missing) > 1 else 'y'} {', '.join(missing)}"
    states = set((properties.get("fix_state") or {}).get("enum") or ())
    if not set(FIX_STATES.values()) <= states:
        return f"{PLUGIN} {version}: {CONCERNS} fix_state does not accept {sorted(set(FIX_STATES.values()) - states)}"
    return None


# --- the rules, as pure functions --------------------------------------------------------------------------------


def vuln_id_of(vulnerability_id: str | None, related: Sequence[str] | None) -> str | None:
    """The CVE id when Inspector's id is one, else the first CVE in ``relatedVulnerabilities``, else the id as given."""
    if vulnerability_id and _CVE.match(vulnerability_id):
        return vulnerability_id
    first = next((r for r in related or () if isinstance(r, str) and _CVE.match(r)), None)
    return first or vulnerability_id or None


def _cvss_rank(entry: Mapping[str, Any]) -> tuple[int, tuple[int, ...]] | None:
    """NVD 3.x first, then any other 3.x (the vendor's), then 2.x; the highest version first within a rank. A 4.x or
    unversioned entry is not ranked: the ruling names these three, and the node's single slot has no room for more."""
    version = str(entry.get("version") or "")
    score, vector = entry.get("baseScore"), entry.get("scoringVector")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not isinstance(vector, str) or not vector:
        return None
    parts = tuple(int(p) for p in re.findall(r"\d+", version))
    if not parts:
        return None
    nvd = str(entry.get("source") or "").upper() == "NVD"
    if parts[0] == 3:
        rank = 0 if nvd else 1
    elif parts[0] == 2:
        rank = 2
    else:
        return None
    return rank, tuple(-p for p in parts)


def choose_cvss(entries: Iterable[Mapping[str, Any]] | None) -> dict[str, Any] | None:
    """The vulnerability's ``cvss_*`` fields from Inspector's top-ranked entry, vector included; None when none ranks."""
    ranked = [(rank, i, e) for i, e in enumerate(entries or ()) if isinstance(e, Mapping) and (rank := _cvss_rank(e))]
    if not ranked:
        return None
    _rank, _i, entry = min(ranked, key=lambda r: (r[0], r[1]))
    return {
        "cvss_score": float(entry["baseScore"]),
        "cvss_vector": str(entry["scoringVector"])[:255],
        "cvss_version": str(entry.get("version") or "")[:16],
        "cvss_source": str(entry.get("source") or "")[:255] or None,
    }


def concerns_properties(fix_available: str | None, packages: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """``fixed_versions`` from every package's ``fixedInVersion`` (``[]`` when none names one; absent when the row
    holds no package list) and ``fix_state`` from ``fixAvailable`` (absent when Inspector said nothing)."""
    out: dict[str, Any] = {}
    if isinstance(packages, list):
        out["fixed_versions"] = sorted(
            {str(p["fixedInVersion"]) for p in packages if isinstance(p, Mapping) and p.get("fixedInVersion")}
            - {"NotAvailable"}
        )
    state = FIX_STATES.get(str(fix_available or ""))
    if state:
        out["fix_state"] = state
    return out


@dataclass(frozen=True)
class HeldVulnerability:
    """A live vulnerability the grid holds: its id, its aliases and whether its CVSS slot is filled."""

    vuln_id: str
    aliases: tuple[str, ...]
    has_cvss: bool


@dataclass
class Projection:
    """The envelopes of one projection batch, and what it could not project."""

    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    #: ``(code, message)`` for the run log.
    notices: list[tuple[str, str]] = field(default_factory=list)
    projected: int = 0
    skipped: int = 0


def _summary(row: Mapping[str, Any], vuln_id: str) -> str:
    names = sorted({str(p.get("name")) for p in row.get("vulnerable_packages") or [] if isinstance(p, Mapping) and p.get("name")})
    parts = [str(row.get("severity") or "").title() or None, vuln_id, ", ".join(names) or None]
    return " ".join(p for p in parts if p)[:SUMMARY_LIMIT]


def finding_ref(arn: str) -> str:
    return node_ref(FINDING, composite_natural_key({"source": SOURCE, "source_key": arn}))


def carriers_of(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    """``(entity type, natural key)`` of what carries a row's neutral finding.

    An ECR image finding whose vulnerable packages got computing_core keys is carried by those packages, which the
    image host installs: what fedramp_20x_vdr's reach walks (package <- INSTALLS_PACKAGE <- host <- RUNS_IMAGE <-
    container; req-aws-landing-zone-inspector-packages-3), and instead of the repository, whose extra carrier would
    add a reach row with no owner. Any other row is carried by the aws_core resource it concerns.
    """
    if row.get("resource_type") == "AWS_ECR_CONTAINER_IMAGE":
        keys = [i["key"] for i in row.get("package_identities") or [] if isinstance(i, Mapping) and i.get("key")]
        packages = sorted({composite_natural_key(k) for k in keys})
        if packages:
            return [(PACKAGE, key) for key in packages]
    target = concerned_resource(row.get("resource_type"), row.get("resource_id"))
    return [target] if target is not None else []


def project(rows: Iterable[Mapping[str, Any]], held: Iterable[HeldVulnerability]) -> Projection:
    """The neutral findings, vulnerabilities and edges for ``rows`` (stored ``aws_inspector2_finding`` fields).

    A row is skipped, and said, when it has no ARN, an ARN longer than ``source_key`` holds, or no vulnerability id;
    and when its vulnerability names two held nodes (ambiguous, not guessed between).
    """
    out = Projection()
    index: dict[str, set[str]] = {}
    by_id: dict[str, HeldVulnerability] = {}
    for vulnerability in held:
        by_id[vulnerability.vuln_id] = vulnerability
        for name in (vulnerability.vuln_id, *vulnerability.aliases):
            index.setdefault(name, set()).add(vulnerability.vuln_id)
    staged: set[str] = set()
    for row in sorted(rows, key=lambda r: str(r.get("finding_arn") or "")):
        arn = str(row.get("finding_arn") or "")
        if row.get("finding_type") == CODE_VULNERABILITY:
            # Ruling Q124b: a code finding names a CWE and a detector rule, not a CVE. Its neutral finding and carrier
            # are written; no vulnerability node and no CONCERNS edge, so no key is invented for it.
            if not arn or len(arn) > SOURCE_KEY_LIMIT:
                out.skipped += 1
                out.notices.append(("INSPECTOR_COMPLIANCE_ROW_SKIPPED", f"{arn or 'a row'}: no usable finding ARN"))
                continue
            _finding_and_carriers(out, row, arn, str(row.get("title") or row.get("detector_name") or "") or arn, _code_summary(row))
            continue
        given = row.get("vulnerability_id")
        chosen = vuln_id_of(given, row.get("related_vulnerabilities"))
        if not arn or len(arn) > SOURCE_KEY_LIMIT or not chosen or len(chosen) > VULN_ID_LIMIT:
            out.skipped += 1
            out.notices.append(("INSPECTOR_COMPLIANCE_ROW_SKIPPED", f"{arn or 'a row'}: no usable finding ARN or vulnerability id"))
            continue
        names = {chosen, *([given] if given and given != chosen else [])}
        found = {node for name in names for node in index.get(name, ())}
        if len(found) > 1:
            out.skipped += 1
            out.notices.append(
                ("INSPECTOR_COMPLIANCE_VULNERABILITY_AMBIGUOUS", f"{arn}: {sorted(names)} name {len(found)} vulnerabilities; not projected")
            )
            continue
        cvss = choose_cvss(row.get("cvss"))
        if found:
            existing = by_id[next(iter(found))]
            vuln_id = existing.vuln_id
            if cvss and not existing.has_cvss and vuln_id not in staged:
                staged.add(vuln_id)
                out.nodes.append(_vulnerability(vuln_id, cvss))
        else:
            vuln_id = chosen
            if vuln_id not in staged:
                staged.add(vuln_id)
                aliases = [given] if given and given != chosen else []
                out.nodes.append(_vulnerability(vuln_id, cvss, aliases=aliases))
        ref = _finding_and_carriers(out, row, arn, str(row.get("title") or "") or vuln_id, _summary(row, vuln_id))
        out.edges.append(
            edge_envelope(
                CONCERNS,
                from_ref=ref,
                to_ref=node_ref(VULNERABILITY, vuln_id),
                dimensions={},
                properties=concerns_properties(row.get("fix_available"), row.get("vulnerable_packages")),
            )
        )
    return out


def _code_summary(row: Mapping[str, Any]) -> str:
    cwes = ", ".join(str(c) for c in row.get("cwes") or [] if c)
    parts = [str(row.get("severity") or "").title() or None, cwes or None, row.get("rule_id") or row.get("detector_name")]
    return " ".join(str(p) for p in parts if p)[:SUMMARY_LIMIT]


def _finding_and_carriers(out: Projection, row: Mapping[str, Any], arn: str, name: str, summary: str) -> str:
    """Stage one neutral finding and its carrier edges; returns the finding's ref."""
    fields: dict[str, Any] = {
        "source": SOURCE,
        "source_key": arn,
        "name": name[:NAME_LIMIT],
        "summary": summary,
        "description": str(row.get("description") or ""),
        "status": "resolved" if row.get("status") == "CLOSED" else "open",
    }
    if row.get("first_observed_at"):
        fields["first_detected_at"] = str(row["first_observed_at"])
    ref = finding_ref(arn)
    out.nodes.append({"entity": {"ref": ref, "entity_type": FINDING, "name": fields["name"], "dimensions": {}}, "node": fields})
    for carrier_type, carrier_key in carriers_of(row):
        out.edges.append(edge_envelope(CARRIES, from_ref=node_ref(carrier_type, carrier_key), to_ref=ref, dimensions={}))
    out.projected += 1
    return ref


def _vulnerability(vuln_id: str, cvss: dict[str, Any] | None, *, aliases: list[str] | None = None) -> dict[str, Any]:
    """A vulnerability envelope: the key, and only the fields this projection owns writing. A held node is sent only
    to fill its empty CVSS slot; its other fields are left as they are (the importer's keep-absent upsert)."""
    fields: dict[str, Any] = {"vuln_id": vuln_id}
    if aliases is not None:
        fields["aliases"] = aliases
    if cvss:
        fields.update(cvss)
    return {"entity": {"ref": node_ref(VULNERABILITY, vuln_id), "entity_type": VULNERABILITY, "name": vuln_id, "dimensions": {}}, "node": fields}


# --- the grid reads ----------------------------------------------------------------------------------------------

#: The stored fields a projection reads from each Inspector row.
ROW_FIELDS: tuple[str, ...] = (
    "finding_arn",
    "finding_type",
    "cwes",
    "rule_id",
    "detector_name",
    "status",
    "severity",
    "title",
    "description",
    "first_observed_at",
    "vulnerability_id",
    "related_vulnerabilities",
    "cvss",
    "fix_available",
    "vulnerable_packages",
    "package_identities",
    "resource_type",
    "resource_id",
)


def stored_rows(account_id: str) -> list[dict[str, Any]]:
    """The live Inspector package-finding rows of one account, as plain data (a read; nothing is written here)."""
    from tap_plugin.aws_core.models.aws_inspector2_finding import AwsInspector2Finding

    return list(AwsInspector2Finding.objects.filter(account_id=account_id).values(*ROW_FIELDS))


def held_vulnerabilities(names: Iterable[str]) -> list[HeldVulnerability]:
    """The live vulnerabilities named by any of ``names``, as a ``vuln_id`` or an alias, read by slug."""
    from django.db.models import Q

    from tap_grid.registry import get_model_class

    model = get_model_class(VULNERABILITY)
    wanted = {n for n in names if n}
    if not wanted:
        return []
    rows = model.objects.filter(Q(vuln_id__in=wanted) | Q(aliases__has_any_keys=sorted(wanted))).values_list("vuln_id", "aliases", "cvss_score")
    out = []
    for vuln_id, aliases, score in rows:
        aliases = tuple(str(a) for a in aliases or ())
        if vuln_id in wanted or wanted.intersection(aliases):
            out.append(HeldVulnerability(str(vuln_id), aliases, score is not None))
    return out


def names_of(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    """Every id a row's vulnerability can be found under: the chosen id and Inspector's own."""
    names: set[str] = set()
    for row in rows:
        if row.get("finding_type") == CODE_VULNERABILITY:
            continue
        given = row.get("vulnerability_id")
        chosen = vuln_id_of(given, row.get("related_vulnerabilities"))
        names |= {n for n in (given, chosen) if n}
    return names


__all__ = [
    "MIN_VERSION",
    "OPTION",
    "SOURCE",
    "HeldVulnerability",
    "Projection",
    "choose_cvss",
    "concerns_properties",
    "enabled",
    "held_vulnerabilities",
    "project",
    "readiness",
    "stored_rows",
    "vuln_id_of",
]
