"""Weighting files: how much each thing matters when the crosscheck scores aws_core against a reference.

A weighting is data (see weights/weights.schema.json). It names no code and the script embeds none of it, so
different situations use different files. Rules are tried in order and the first match wins; a file that
extends another puts its own rules first, so it overrides the parent for the things it names.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SELECTORS = ("carto_label", "tap_type", "attribute", "cfn_type")


class WeightingError(ValueError):
    """A weighting file that does not follow the schema; refused rather than guessed at."""


@dataclass(frozen=True)
class Weighting:
    name: str
    version: int
    status: str
    chain: tuple[str, ...]
    sha256: str
    default: float
    rules: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def _first(self, kind: str, values: tuple[str, ...]) -> float | None:
        for rule in self.rules:
            pat = rule.get(kind)
            if pat is not None and any(fnmatch.fnmatchcase(v, pat) for v in values):
                return float(rule["weight"])
        return None

    def concept(self, label: str | None, tap_types: tuple[str, ...] = ()) -> float:
        """Weight of a Cartography label, the aws_core types it maps to, or both: the first rule in order that
        matches any of them, so an overlay naming a type overrides a base rule naming the label."""
        for rule in self.rules:
            hit = (label is not None and "carto_label" in rule and fnmatch.fnmatchcase(label, rule["carto_label"])) or (
                "tap_type" in rule and any(fnmatch.fnmatchcase(t, rule["tap_type"]) for t in tap_types)
            )
            if hit:
                return float(rule["weight"])
        return self.default

    def cfn(self, type_name: str) -> float:
        """Weight of a CloudFormation type in the coverage ledger, whether or not either side models it."""
        w = self._first("cfn_type", (type_name,))
        return self.default if w is None else w

    def has_cfn_rules(self) -> bool:
        return any("cfn_type" in r for r in self.rules)

    def attribute(self, attr_id: str, fallback: float) -> float:
        """A security attribute's own rule if one names it, else the weight of what it belongs to."""
        w = self._first("attribute", (attr_id,))
        return fallback if w is None else w


def _check(d: Any, where: str) -> None:
    for key in ("name", "version", "description", "default_weight", "rules"):
        if key not in d:
            raise WeightingError(f"{where}: missing {key!r}")
    if not isinstance(d["rules"], list):
        raise WeightingError(f"{where}: rules must be a list")
    for i, r in enumerate(d["rules"]):
        sel = [k for k in SELECTORS if k in r]
        extra = set(r) - set(SELECTORS) - {"weight", "why"}
        if len(sel) != 1 or extra or "weight" not in r or not r.get("why"):
            raise WeightingError(f"{where}: rule {i} needs exactly one selector, a weight and a why (got {sorted(r)})")
        if not isinstance(r["weight"], (int, float)) or r["weight"] < 0:
            raise WeightingError(f"{where}: rule {i} weight must be a non-negative number")


def load(path: Path, _seen: tuple[str, ...] = ()) -> Weighting:
    path = Path(path)
    raw = path.read_bytes()
    d = json.loads(raw)
    _check(d, path.name)
    if path.name in _seen:
        raise WeightingError(f"{path.name}: extends itself through {list(_seen)}")
    rules: list[dict[str, Any]] = list(d["rules"])
    chain = [path.name]
    digest = hashlib.sha256(raw).hexdigest()
    default = float(d["default_weight"])
    if d.get("extends"):
        parent = load(path.parent / d["extends"], (*_seen, path.name))
        rules += list(parent.rules)
        chain += list(parent.chain)
        digest = hashlib.sha256((digest + parent.sha256).encode()).hexdigest()
    return Weighting(d["name"], int(d["version"]), d.get("status", "draft"), tuple(chain), digest, default, tuple(rules))
