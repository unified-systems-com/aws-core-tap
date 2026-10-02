"""aws-baseline — the security baseline matrix on /aws/baseline (req-aws-core-panel-baseline).

Spec: specs/spec-aws-core-v0.md (req-aws-core-page-baseline, req-aws-core-panel-baseline); the models and
what each of their fields means are spec-aws-core-landing-zone.md § Security Services (aws-core-tap#66).

One row per account and region (an ``aws_account_region`` footprint), one column per control, each cell
**on**, **off** or **unknown**:

- EBS default encryption: the footprint's ``ebs_encryption_by_default`` (true / false / null).
- S3 account public-access block: the four flags on the footprint's account (BELONGS_TO_ACCOUNT); on when
  all four are true, off when any is false, otherwise unknown. One account setting, so every region row of
  an account shows the same value.
- Config recorder, GuardDuty, Security Hub, Access Analyzer: the node the footprint HOSTS_*; on when one
  is recording / enabled / present / active, off when one exists and none is, unknown when none is on the
  grid.
- Control Tower: on when an enabled baseline that succeeded APPLIES_TO_TARGET the account or an OU above
  it (NESTED_UNDER_PARENT, any depth); off when every baseline covering it failed; otherwise unknown.

**Unknown is never off.** A null field is "not read" (the collector's null convention). A missing service
node is "not seen": the collector proves a service is off only by a complete, empty listing, and that
completeness statement lives on the run's batch, which Gryphon does not read. So absence is unknown here,
and "off" appears only where AWS itself answered off (a false flag, a stopped recorder, a disabled
detector or analyzer, a failed baseline).

Reads go through Gryphon (``execute_gryphon_raw``, gated on ``grid.read``), one query per control because
Gryphon's OPTIONAL MATCH v0 allows one optional hop and returns only its count; folding the rows into the
matrix is pure (``fold_baseline``), so the tests need no grid. A failed read marks its column failed and
never renders as off.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from django.http import HttpRequest

    from tap_web.models import Panel

logger = logging.getLogger(__name__)

FOOTPRINT = "aws_core__aws_account_region"
ON, OFF, UNKNOWN, FAILED = "on", "off", "unknown", "failed"

FOOTPRINTS_QUERY = (
    f"MATCH (f:{FOOTPRINT}) RETURN f.entity_id AS footprint, f.name AS name, f.data.account_id AS account_id, "
    "f.data.region_code AS region, f.data.ebs_encryption_by_default AS ebs, f.data.ebs_default_kms_key_id AS ebs_key"
)
ACCOUNTS_QUERY = (
    f"MATCH (f:{FOOTPRINT})-[:BELONGS_TO_ACCOUNT__aws_core]->(a:aws_core__aws_account) "
    "RETURN f.entity_id AS footprint, a.entity_id AS account, a.name AS account_name, "
    "a.data.s3_block_public_acls AS block_public_acls, a.data.s3_ignore_public_acls AS ignore_public_acls, "
    "a.data.s3_block_public_policy AS block_public_policy, a.data.s3_restrict_public_buckets AS restrict_public_buckets"
)
TREE_QUERY = "MATCH (c)-[:NESTED_UNDER_PARENT__aws_core]->(p) RETURN c.entity_id AS child, p.entity_id AS parent"
BASELINES_QUERY = (
    "MATCH (b:aws_core__aws_controltower_enabled_baseline)-[:APPLIES_TO_TARGET__aws_core]->(t) "
    "RETURN t.entity_id AS target, b.name AS name, b.data.status AS status"
)
PAB_FLAGS = ("block_public_acls", "ignore_public_acls", "block_public_policy", "restrict_public_buckets")


def _service_query(edge: str, etype: str, field: str) -> str:
    return (f"MATCH (f:{FOOTPRINT})-[:{edge}]->(x:{etype}) "
            f"RETURN f.entity_id AS footprint, x.name AS name, x.data.{field} AS value")


@dataclass(frozen=True)
class ServiceDef:
    """A security service the footprint hosts as a node, and how one node's value reads."""

    key: str
    label: str
    query: str
    #: One node's value → on / off / unknown.
    judge: Callable[[Any], str]
    #: What "on" means for this service, for the cell's title.
    on_means: str


def _recording(v: Any) -> str:
    return ON if v is True else OFF if v is False else UNKNOWN


def _enabled(v: Any) -> str:
    s = str(v or "").upper()
    return ON if s == "ENABLED" else OFF if s == "DISABLED" else UNKNOWN


def _present(_v: Any) -> str:
    return ON


def _active(v: Any) -> str:
    s = str(v or "").upper()
    return ON if s == "ACTIVE" else OFF if s in {"DISABLED", "FAILED"} else UNKNOWN


SERVICES: tuple[ServiceDef, ...] = (
    ServiceDef("config", "Config recorder",
               _service_query("HOSTS_CONFIG_RECORDER__aws_core", "aws_core__aws_config_recorder", "recording"),
               _recording, "a configuration recorder is recording"),
    ServiceDef("guardduty", "GuardDuty",
               _service_query("HOSTS_GUARDDUTY_DETECTOR__aws_core", "aws_core__aws_guardduty_detector", "status"),
               _enabled, "a detector is ENABLED"),
    ServiceDef("securityhub", "Security Hub",
               _service_query("HOSTS_SECURITYHUB_HUB__aws_core", "aws_core__aws_securityhub_hub", "hub_arn"),
               _present, "the account is subscribed (a hub exists)"),
    ServiceDef("access_analyzer", "Access Analyzer",
               _service_query("HOSTS_ACCESS_ANALYZER__aws_core", "aws_core__aws_access_analyzer", "status"),
               _active, "an analyzer is ACTIVE"),
)

#: Column order on the page: the two account settings, the four services, Control Tower.
COLUMNS: tuple[tuple[str, str], ...] = (
    ("ebs", "EBS default encryption"),
    ("s3_pab", "S3 public-access block"),
    *((s.key, s.label) for s in SERVICES),
    ("control_tower", "Control Tower"),
)


def _cell(state: str, note: str) -> dict[str, str]:
    return {"state": state, "note": note}


def ebs_cell(value: Any, key_id: Any = None) -> dict[str, str]:
    if value is True:
        return _cell(ON, f"Encrypted by default{f' with {key_id}' if key_id else ''}.")
    if value is False:
        return _cell(OFF, "GetEbsEncryptionByDefault answered false: new volumes are not encrypted by default.")
    return _cell(UNKNOWN, "Not read: the setting is null on the grid.")


def s3_pab_cell(flags: dict[str, Any] | None) -> dict[str, str]:
    if flags is None:
        return _cell(UNKNOWN, "No account node is linked to this footprint (BELONGS_TO_ACCOUNT).")
    values = [flags.get(f) for f in PAB_FLAGS]
    detail = ", ".join(f"{f.replace('_', ' ')}: {'not read' if v is None else str(v).lower()}"
                       for f, v in zip(PAB_FLAGS, values, strict=True))
    if any(v is False for v in values):
        return _cell(OFF, f"At least one of the four account flags is off ({detail}).")
    if all(v is True for v in values):
        return _cell(ON, f"All four account flags are on ({detail}).")
    return _cell(UNKNOWN, f"Not every flag was read ({detail}).")


def service_cell(service: ServiceDef, rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    """The service in one footprint, from the nodes it hosts (``rows`` already narrowed to the footprint)."""
    rows = list(rows)
    if not rows:
        return _cell(UNKNOWN, f"No {service.label} node on the grid for this account and region: not seen, "
                              "which is not the same as off.")
    states = [service.judge(r.get("value")) for r in rows]
    names = ", ".join(sorted(str(r.get("name") or "?") for r in rows))
    if ON in states:
        return _cell(ON, f"On: {service.on_means} ({names}).")
    if all(s == OFF for s in states):
        return _cell(OFF, f"Present but off ({names}).")
    return _cell(UNKNOWN, f"Present, state not read ({names}).")


def control_tower_cell(account: str | None, parent: dict[str, str], covering: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    """Enrollment: an enabled baseline on the account or any OU above it (cycle-safe walk)."""
    if not account:
        return _cell(UNKNOWN, "No account node is linked to this footprint.")
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    node: str | None = account
    while node and node not in seen:
        seen.add(node)
        found += covering.get(node, [])
        node = parent.get(node)
    if not found:
        return _cell(UNKNOWN, "No Control Tower enabled baseline applies to this account or an OU above it on the grid: "
                              "not seen, which is not the same as not enrolled.")
    statuses = {str(b.get("status") or "").upper() for b in found}
    names = ", ".join(sorted({str(b.get("name") or "?") for b in found}))
    if "SUCCEEDED" in statuses:
        return _cell(ON, f"Enrolled: an enabled baseline applies ({names}).")
    if statuses == {"FAILED"}:
        return _cell(OFF, f"Every baseline covering it failed ({names}).")
    return _cell(UNKNOWN, f"A baseline applies but has not succeeded ({names}).")


def fold_baseline(footprints: list[dict[str, Any]], accounts: list[dict[str, Any]],
                  services: dict[str, list[dict[str, Any]] | None], tree: list[dict[str, Any]] | None,
                  baselines: list[dict[str, Any]] | None, account_failed: bool = False) -> dict[str, Any]:
    """The matrix. A ``None`` read is a failed read: its column says failed, never off."""
    by_fp_account = {r["footprint"]: r for r in accounts if r.get("footprint")}
    parent = {r["child"]: r["parent"] for r in (tree or []) if r.get("child") and r.get("parent")}
    covering: dict[str, list[dict[str, Any]]] = {}
    for b in baselines or []:
        if b.get("target"):
            covering.setdefault(b["target"], []).append(b)
    by_fp_service: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for key, rows in services.items():
        for r in rows or []:
            by_fp_service.setdefault(key, {}).setdefault(r.get("footprint"), []).append(r)

    failed = _cell(FAILED, "The read failed; see the server log ([b7e2]).")
    out_rows = []
    for fp in sorted(footprints, key=lambda r: (str(r.get("account_id") or ""), str(r.get("region") or ""))):
        fid = fp.get("footprint")
        acct = by_fp_account.get(fid)
        cells: dict[str, dict[str, str]] = {"ebs": ebs_cell(fp.get("ebs"), fp.get("ebs_key"))}
        cells["s3_pab"] = failed if account_failed else s3_pab_cell(
            None if acct is None else {f: acct.get(f) for f in PAB_FLAGS})
        for s in SERVICES:
            rows = services.get(s.key)
            cells[s.key] = failed if rows is None else service_cell(s, by_fp_service.get(s.key, {}).get(fid, []))
        cells["control_tower"] = (failed if tree is None or baselines is None or account_failed
                                  else control_tower_cell(acct.get("account") if acct else None, parent, covering))
        out_rows.append({
            "account": fp.get("account_id") or "",
            "account_name": (acct or {}).get("account_name") or "",
            "region": fp.get("region") or "",
            "cells": [{"key": k, "label": label, **cells[k]} for k, label in COLUMNS],
        })
    summary = []
    for i, (key, label) in enumerate(COLUMNS):
        states = [r["cells"][i]["state"] for r in out_rows]
        summary.append({"key": key, "label": label, "on": states.count(ON), "off": states.count(OFF),
                        "unknown": states.count(UNKNOWN), "failed": states.count(FAILED)})
    total = len(out_rows) * len(COLUMNS)
    on = sum(s["on"] for s in summary)
    off = sum(s["off"] for s in summary)
    return {"rows": out_rows, "columns": [{"key": k, "label": label} for k, label in COLUMNS], "summary": summary,
            "cells_total": total, "cells_on": on, "cells_off": off, "cells_unknown": total - on - off,
            "accounts": len({r["account"] for r in out_rows})}


class AwsBaselinePanelType:
    """The security baseline matrix: one row per account and region, each control on / off / unknown."""

    slug: ClassVar[str] = "aws-baseline"
    label: ClassVar[str] = "AWS security baseline"
    view: ClassVar[str] = "aws_core/panels/baseline.html"
    css: ClassVar[list[str]] = ["aws_core/css/posture.css"]
    js: ClassVar[list[str]] = []
    editor_view: ClassVar[str] = ""
    config_defaults: ClassVar[dict[str, Any]] = {}

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        from tap_grid.gryphon.executor import execute_gryphon_raw

        def rows(query: str, what: str) -> list[dict[str, Any]] | None:
            try:
                return list(execute_gryphon_raw(query, {}, layer="full").get("rows") or [])
            except Exception:  # noqa: BLE001 — a failed read marks its column failed, never off
                logger.exception("[b7e2] aws baseline: %s read failed for panel %s", what, panel.entity_id)
                return None

        footprints = rows(FOOTPRINTS_QUERY, "footprints")
        if footprints is None:
            return {"error": True, "matrix": None}
        accounts = rows(ACCOUNTS_QUERY, "accounts")
        services = {s.key: rows(s.query, s.key) for s in SERVICES}
        matrix = fold_baseline(footprints, accounts or [], services, rows(TREE_QUERY, "tree"),
                               rows(BASELINES_QUERY, "control tower baselines"), account_failed=accounts is None)
        return {"error": False, "matrix": matrix}
