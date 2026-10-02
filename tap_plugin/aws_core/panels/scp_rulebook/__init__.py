"""aws-scp-rulebook — service control policy statements written out as rules (req-aws-core-panel-scp-rulebook).

Spec: specs/spec-aws-core-v0.md (req-aws-core-page-scps, req-aws-core-panel-scp-rulebook). The statements are
the ``aws_policy_statement`` nodes a policy DECLARES_STATEMENT (aws-core-tap#72), whose fields are already
normalised by the collector: ``effect``, ``actions`` / ``not_actions``, ``resources`` / ``not_resources`` and
``conditions`` as ``{condition_key, operator, values}`` with the operator and key lowercased.

Grouped by policy, each policy with what it is attached to (ATTACHED_TO_TARGET); each statement one rule
in plain words: "Denies every action on any resource when aws:principalarn matches arn:...:root". A policy
attached to nothing has no effect, and says so. ``config.effect`` picks the statements (default Deny).

Reads go through Gryphon; turning a statement into words is pure (``rule_of``), so the tests need no grid.
Nothing is reinterpreted: an operator the vocabulary below does not know is shown as AWS spells it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from django.http import HttpRequest

    from tap_web.models import Panel

logger = logging.getLogger(__name__)

STATEMENTS_QUERY = (
    "MATCH (p:aws_core__aws_service_control_policy)-[:DECLARES_STATEMENT__aws_core]->(s:aws_core__aws_policy_statement) "
    "WHERE s.data.effect = $effect "
    "RETURN p.entity_id AS policy_id, p.name AS policy, p.data.description AS description, p.data.aws_managed AS aws_managed, "
    "s.data.sid AS sid, s.data.actions AS actions, s.data.not_actions AS not_actions, s.data.resources AS resources, "
    "s.data.not_resources AS not_resources, s.data.conditions AS conditions, s.data.positions AS positions"
)
ATTACHMENTS_QUERY = (
    "MATCH (p:aws_core__aws_service_control_policy)-[:ATTACHED_TO_TARGET__aws_core]->(t) "
    "RETURN p.entity_id AS policy_id, t.name AS target, t.entity_type AS kind"
)

KIND = {
    "aws_core__aws_organization": "organization root",
    "aws_core__aws_organizational_unit": "OU",
    "aws_core__aws_account": "account",
}

#: Condition operators in words (IAM's condition operator names, lowercased as the collector stores them).
OPERATORS = {
    "stringequals": "is", "stringnotequals": "is not",
    "stringequalsignorecase": "is (any case)", "stringnotequalsignorecase": "is not (any case)",
    "stringlike": "matches", "stringnotlike": "does not match",
    "arnequals": "is", "arnnotequals": "is not", "arnlike": "matches", "arnnotlike": "does not match",
    "numericequals": "=", "numericnotequals": "≠", "numericlessthan": "<", "numericlessthanequals": "≤",
    "numericgreaterthan": ">", "numericgreaterthanequals": "≥",
    "dateequals": "is", "datenotequals": "is not", "datelessthan": "is before", "datelessthanequals": "is on or before",
    "dategreaterthan": "is after", "dategreaterthanequals": "is on or after",
    "bool": "is", "ipaddress": "is in", "notipaddress": "is not in", "null": "is absent:",
}
EFFECT_VERB = {"Deny": "Denies", "Allow": "Allows"}


def _list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return [str(v)]


def _scope(items: list[str], not_items: list[str], every: str, any_: str) -> dict[str, Any]:
    """``{"lead": words, "items": [...], "rest": words}`` for actions or resources."""
    if not_items:
        return {"lead": f"{every} except", "items": not_items}
    if not items or items == ["*"]:
        return {"lead": any_, "items": []}
    return {"lead": "", "items": items}


def _operator(op: str) -> dict[str, str]:
    raw = str(op or "")
    lower = raw.lower()
    qualifier = ""
    for prefix, words in (("forallvalues:", "every value "), ("foranyvalue:", "any value ")):
        if lower.startswith(prefix):
            lower, qualifier = lower[len(prefix):], words
    if_exists = lower.endswith("ifexists")
    if if_exists:
        lower = lower[: -len("ifexists")]
    words = OPERATORS.get(lower)
    return {"words": f"{qualifier}{words}" if words else raw, "if_exists": "if present" if if_exists else "",
            "raw": raw}


def rule_of(row: dict[str, Any]) -> dict[str, Any]:
    """One statement as a rule: what it does to which actions, on what, and under which conditions."""
    conditions = []
    for c in row.get("conditions") or []:
        if not isinstance(c, dict):
            continue
        conditions.append({"key": str(c.get("condition_key") or ""), **_operator(str(c.get("operator") or "")),
                           "values": _list(c.get("values"))})
    return {
        "sid": str(row.get("sid") or ""),
        "actions": _scope(_list(row.get("actions")), _list(row.get("not_actions")), "every action", "every action"),
        "resources": _scope(_list(row.get("resources")), _list(row.get("not_resources")), "any resource", "any resource"),
        "conditions": conditions,
        "position": min((p for p in (row.get("positions") or []) if isinstance(p, int)), default=0),
    }


def fold_rulebook(statements: list[dict[str, Any]], attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Policies in name order, each with its targets and its rules in document order."""
    targets: dict[str, list[dict[str, str]]] = {}
    for a in attachments or []:
        if a.get("policy_id"):
            targets.setdefault(a["policy_id"], []).append(
                {"name": str(a.get("target") or "?"), "kind": KIND.get(str(a.get("kind") or ""), str(a.get("kind") or ""))})
    policies: dict[str, dict[str, Any]] = {}
    for s in statements:
        pid = s.get("policy_id")
        if not pid:
            continue
        p = policies.setdefault(pid, {
            "name": str(s.get("policy") or "?"), "description": str(s.get("description") or ""),
            "aws_managed": s.get("aws_managed"),
            "targets": sorted(targets.get(pid, []), key=lambda t: (t["kind"], t["name"])),
            "targets_known": attachments is not None, "rules": []})
        p["rules"].append(rule_of(s))
    out = sorted(policies.values(), key=lambda p: p["name"].lower())
    n = 0
    for p in out:
        p["rules"].sort(key=lambda r: (r["position"], r["sid"]))
        for r in p["rules"]:
            n += 1
            r["number"] = n
    return out


class AwsScpRulebookPanelType:
    """SCP statements of one effect, read as a rulebook."""

    slug: ClassVar[str] = "aws-scp-rulebook"
    label: ClassVar[str] = "SCP rulebook"
    view: ClassVar[str] = "aws_core/panels/scp_rulebook.html"
    css: ClassVar[list[str]] = ["aws_core/css/posture.css"]
    js: ClassVar[list[str]] = []
    editor_view: ClassVar[str] = ""
    config_defaults: ClassVar[dict[str, Any]] = {"effect": "Deny"}

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        from tap_grid.gryphon.executor import execute_gryphon_raw

        config = {**cls.config_defaults, **(panel.config or {})}
        effect = "Allow" if config.get("effect") == "Allow" else "Deny"
        context: dict[str, Any] = {"effect": effect, "verb": EFFECT_VERB[effect], "title": config.get("title") or "",
                                   "intro": config.get("intro") or ""}
        try:
            statements = execute_gryphon_raw(STATEMENTS_QUERY, {"effect": effect}, layer="full").get("rows") or []
        except Exception:  # noqa: BLE001 — a failed read says so; it is never an empty rulebook
            logger.exception("[c4d1] aws scp rulebook: statements read failed for panel %s", panel.entity_id)
            return {**context, "error": True, "policies": []}
        try:
            attachments = execute_gryphon_raw(ATTACHMENTS_QUERY, {}, layer="full").get("rows") or []
        except Exception:  # noqa: BLE001 — targets unknown, rules still shown
            logger.exception("[c4d1] aws scp rulebook: attachments read failed for panel %s", panel.entity_id)
            attachments = None
        policies = fold_rulebook(list(statements), None if attachments is None else list(attachments))
        return {**context, "error": False, "policies": policies,
                "rule_count": sum(len(p["rules"]) for p in policies)}
