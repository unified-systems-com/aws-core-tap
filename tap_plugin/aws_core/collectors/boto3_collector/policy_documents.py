"""AWS Organizations policy documents read into typed units (aws-core-tap#65).

Pure functions, no AWS calls, no Django: the Organizations reader and the statement and tag-rule
falsifiers both parse a ``DescribePolicy`` document through here, so the key a falsifier looks for
is computed exactly the way the collector computed it.

Spec: specs/spec-aws-core-v0.md, *Policy Statements* (req-aws-core-organizations-completeness-7,
-8, -9, -11). The canonical form, the three key forms and the tag-rule fields are the spec's; this
module is their one implementation.

- **Statements** (SCP, RCP). Every member AWS allows as a string or a list becomes a de-duplicated,
  sorted list. Action names, condition operators and condition keys are lowercased (IAM matches them
  case-insensitively); resources, principal values and condition values keep their case.
  ``content_sha256`` is the SHA-256 of ``{effect, actions, not_actions, resources, not_resources,
  principals, not_principals, conditions}`` serialized with sorted keys and no insignificant
  whitespace, ``Sid`` excluded. Keys: ``sid:<Sid>`` for a unique Sid, ``content:<sha>`` for none,
  ``dupsid:<sha256 of the canonical form with a "sid" member>`` for a repeated Sid. Identical
  statements under one key are one unit with ``occurrences``.
- **Tag rules** (TAG_POLICY). One unit per key under the document's ``tags`` block, keyed by the key
  lowercased.

A document this module cannot read with certainty raises :class:`PolicyDocumentError`. The caller
then treats the listing behind the containment edge as incomplete; nothing is guessed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

_EFFECTS = frozenset({"Allow", "Deny"})
_STATEMENT_MEMBERS = frozenset(
    {"Sid", "Effect", "Action", "NotAction", "Resource", "NotResource", "Principal", "NotPrincipal", "Condition"}
)


class PolicyDocumentError(ValueError):
    """The document is not one this module can read with certainty (the reason is the message)."""


@dataclass
class StatementUnit:
    """One statement node's worth of facts: the typed fields, its key, and where it appears."""

    statement_key: str
    sid: str
    fields: dict[str, Any]
    content_sha256: str
    positions: list[int] = field(default_factory=list)

    @property
    def occurrences(self) -> int:
        return len(self.positions)


@dataclass
class StatementSet:
    """Every statement unit of one document, by key, plus the Sids that were repeated."""

    units: dict[str, StatementUnit]
    duplicate_sids: list[str]


def _as_list(value: Any, member: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, (str, bool, int, float)):
        return [value]
    raise PolicyDocumentError(f"{member} is neither a string nor a list")


def _scalar(value: Any, member: str) -> str:
    """A JSON scalar as the string IAM compares it as (``true``/``false`` for booleans)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise PolicyDocumentError(f"{member} holds a non-scalar value")


def _strings(value: Any, member: str, *, lower: bool = False) -> list[str]:
    if value is None:
        return []
    items = [_scalar(v, member) for v in _as_list(value, member)]
    if lower:
        items = [v.lower() for v in items]
    return sorted(set(items))


def _principals(value: Any, member: str) -> list[dict[str, str]]:
    if value is None:
        return []
    if value == "*":
        return [{"type": "*", "value": "*"}]
    if not isinstance(value, dict):
        raise PolicyDocumentError(f"{member} is neither \"*\" nor a map of principal types")
    entries = {(str(kind), v) for kind, values in value.items() for v in _strings(values, member)}
    return [{"type": kind, "value": v} for kind, v in sorted(entries)]


def _conditions(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, dict):
        raise PolicyDocumentError("Condition is not a map of operators")
    merged: dict[tuple[str, str], set[str]] = {}
    for operator, keys in value.items():
        if not isinstance(keys, dict):
            raise PolicyDocumentError(f"Condition operator {operator!r} is not a map of keys")
        for key, values in keys.items():
            # Operator and key names fold case (IAM matches both case-insensitively), so two
            # spellings of one key under one operator are one entry; values keep their case.
            merged.setdefault((str(operator).lower(), str(key).lower()), set()).update(_strings(values, "Condition"))
    return [
        {"operator": operator, "condition_key": key, "values": sorted(values)}
        for (operator, key), values in sorted(merged.items())
    ]


def normalize_statement(statement: Any) -> tuple[str, dict[str, Any]]:
    """``(sid, typed fields)`` for one raw statement. Raises :class:`PolicyDocumentError`."""
    if not isinstance(statement, dict):
        raise PolicyDocumentError("a Statement entry is not an object")
    unknown = sorted(set(statement) - _STATEMENT_MEMBERS)
    if unknown:
        raise PolicyDocumentError(f"a statement carries members this reader does not model: {unknown}")
    effect = statement.get("Effect")
    if effect not in _EFFECTS:
        raise PolicyDocumentError(f"Effect is {effect!r}, not Allow or Deny")
    sid = statement.get("Sid", "")
    if not isinstance(sid, str):
        raise PolicyDocumentError("Sid is not a string")
    fields = {
        "effect": effect,
        "actions": _strings(statement.get("Action"), "Action", lower=True),
        "not_actions": _strings(statement.get("NotAction"), "NotAction", lower=True),
        "resources": _strings(statement.get("Resource"), "Resource"),
        "not_resources": _strings(statement.get("NotResource"), "NotResource"),
        "principals": _principals(statement.get("Principal"), "Principal"),
        "not_principals": _principals(statement.get("NotPrincipal"), "NotPrincipal"),
        "conditions": _conditions(statement.get("Condition")),
    }
    if bool(fields["actions"]) == bool(fields["not_actions"]):
        raise PolicyDocumentError("a statement must name exactly one of Action and NotAction")
    return sid, fields


def canonical_form(fields: dict[str, Any]) -> str:
    """The canonical serialization of a statement's stored typed fields (``Sid`` excluded)."""
    body = {name: fields[name] for name in ("effect", "actions", "not_actions", "resources", "not_resources", "principals", "not_principals", "conditions")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_sha256(fields: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_form(fields).encode("utf-8")).hexdigest()


def _dupsid_key(sid: str, fields: dict[str, Any]) -> str:
    body = json.loads(canonical_form(fields))
    body["sid"] = sid
    serialized = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "dupsid:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def parse_statements(content: Any) -> StatementSet:
    """Every statement of an SCP or RCP document, keyed. Raises :class:`PolicyDocumentError`."""
    try:
        document = json.loads(content) if isinstance(content, str) else None
    except json.JSONDecodeError as exc:
        raise PolicyDocumentError(f"the document is not JSON: {exc.msg}") from None
    if not isinstance(document, dict):
        raise PolicyDocumentError("the document is not a JSON object")
    raw = document.get("Statement")
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise PolicyDocumentError("the document has no Statement list")
    parsed = [normalize_statement(statement) for statement in raw]
    sid_counts: dict[str, int] = {}
    for sid, _fields in parsed:
        if sid:
            sid_counts[sid] = sid_counts.get(sid, 0) + 1
    duplicated = sorted(sid for sid, count in sid_counts.items() if count > 1)
    units: dict[str, StatementUnit] = {}
    for position, (sid, fields) in enumerate(parsed):
        digest = content_sha256(fields)
        if not sid:
            key = f"content:{digest}"
        elif sid in duplicated:
            key = _dupsid_key(sid, fields)
        else:
            key = f"sid:{sid}"
        unit = units.get(key)
        if unit is None:
            unit = units[key] = StatementUnit(statement_key=key, sid=sid, fields=fields, content_sha256=digest)
        unit.positions.append(position)
    return StatementSet(units=units, duplicate_sids=duplicated)


@dataclass
class TagRuleUnit:
    """One tag key's rule in a tag policy."""

    tag_key_lower: str
    tag_key: str
    allowed_values: list[str] | None
    enforced_for: list[str] | None
    inheritance_operators: list[str]


def _operators(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and key.startswith("@@"):
                found.add(key)
            found |= _operators(value)
    elif isinstance(node, list):
        for value in node:
            found |= _operators(value)
    return found


def _assigned_values(block: Any, member: str) -> list[str] | None:
    """``@@assign`` ∪ ``@@append`` values of a setting block, sorted; None when the block is absent."""
    if block is None:
        return None
    if not isinstance(block, dict):
        raise PolicyDocumentError(f"{member} is not a setting block")
    values: set[str] = set()
    for operator in ("@@assign", "@@append"):
        if operator in block:
            values.update(_strings(block[operator], member))
    return sorted(values)


def parse_tag_rules(content: Any) -> dict[str, TagRuleUnit]:
    """Every tag key's rule in a TAG_POLICY document, by lowercased key. A document with no
    ``tags`` block has no rules. Raises :class:`PolicyDocumentError`."""
    try:
        document = json.loads(content) if isinstance(content, str) else None
    except json.JSONDecodeError as exc:
        raise PolicyDocumentError(f"the document is not JSON: {exc.msg}") from None
    if not isinstance(document, dict):
        raise PolicyDocumentError("the document is not a JSON object")
    tags = document.get("tags")
    if tags is None:
        return {}
    if not isinstance(tags, dict):
        raise PolicyDocumentError("the tags block is not an object")
    rules: dict[str, TagRuleUnit] = {}
    for key, rule in tags.items():
        if not isinstance(rule, dict):
            raise PolicyDocumentError(f"the rule for {key!r} is not an object")
        lower = str(key).lower()
        if lower in rules:
            raise PolicyDocumentError(f"two rules fold to the tag key {lower!r}")
        tag_key_block = rule.get("tag_key")
        assigned = tag_key_block.get("@@assign") if isinstance(tag_key_block, dict) else None
        rules[lower] = TagRuleUnit(
            tag_key_lower=lower,
            tag_key=assigned if isinstance(assigned, str) and assigned else str(key),
            allowed_values=_assigned_values(rule.get("tag_value"), "tag_value"),
            enforced_for=_assigned_values(rule.get("enforced_for"), "enforced_for"),
            inheritance_operators=sorted(_operators(rule)),
        )
    return rules


__all__ = [
    "PolicyDocumentError",
    "StatementSet",
    "StatementUnit",
    "TagRuleUnit",
    "canonical_form",
    "content_sha256",
    "normalize_statement",
    "parse_statements",
    "parse_tag_rules",
]
