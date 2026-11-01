"""Read aws_core's data model from its source tree, statically: models by AST, the manifest and edge files as JSON.

aws_core is never imported (that needs Django and a booted plugin); this reader runs anywhere Python does.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from carto_reader import norm

_READ_PREFIX = re.compile(r"^(Describe|List|Get|BatchGet|Lookup|Search)")


def commit_of(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=30
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _classvar(cls: ast.ClassDef, name: str) -> Any:
    for s in cls.body:
        if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name) and s.target.id == name and s.value is not None:
            try:
                return ast.literal_eval(s.value)
            except ValueError:
                return None
    return None


def _ops_in(node: Any, service: str, out: set[tuple[str, str]]) -> None:
    """Every `aws_op` named anywhere in a manifest entry, under the nearest enclosing `service`."""
    if isinstance(node, dict):
        service = node.get("service", service)
        for k, v in node.items():
            if k == "aws_op" and isinstance(v, str):
                out.add((norm(service), norm(v)))
            else:
                _ops_in(v, service, out)
    elif isinstance(node, list):
        for v in node:
            _ops_in(v, service, out)


def _custom_ops(collector_dir: Path) -> set[tuple[str, str]]:
    """Reads made by hand-written readers (service unknown): any `x.DescribeFoo`-style snake_case call."""
    ops: set[tuple[str, str]] = set()
    snake = re.compile(r"^(describe|list|get|batch_get|lookup|search)_")
    for p in sorted(collector_dir.glob("*.py")):
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and snake.match(n.func.attr):
                ops.add(("?", norm(n.func.attr)))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get_paginator":
                if n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                    ops.add(("?", norm(n.args[0].value)))
    return ops


def read(plugin: Path) -> dict[str, Any]:
    pkg = plugin / "tap_plugin" / "aws_core"
    types: dict[str, dict] = {}
    for p in sorted((pkg / "models").glob("*.py")):
        for c in ast.parse(p.read_text()).body:
            if isinstance(c, ast.ClassDef):
                et = _classvar(c, "ENTITY_TYPE")
                if et:
                    types[et] = {
                        "fields": sorted(_classvar(c, "FIELD_CRUD_SCHEMA") or {}),
                        "natural_key": list(_classvar(c, "NATURAL_KEY") or []),
                        "model_edges": [
                            {"edge": e["type"], "targets": [n["type"] for n in o["nodes"]]}
                            for o in (_classvar(c, "OUTBOUND_EDGES") or [])
                            for e in o["edges"]
                        ],
                        "manifest": None,
                    }
    bdir = pkg / "collectors" / "boto3_collector"
    manifest = json.loads((bdir / "aws_resource_manifest.json").read_text())
    ops: set[tuple[str, str]] = set()
    for e in manifest["entries"]:
        t = types.setdefault(e["entity_type"], {"fields": [], "natural_key": [], "model_edges": [], "manifest": None})
        _ops_in(e, e.get("service", ""), ops)
        t["manifest"] = {
            "service": e.get("service"),
            "natural_key": e.get("natural_key"),
            "persist_configuration": e.get("persist_configuration", True),
            "field_sources": e.get("fields", {}),
            "tags": (e.get("tags") or {}).get("source"),
            "containment": bool(e.get("containment")),
            "edges": [
                {"edge": r["edge_type"], "target": r["target_type"], "direction": r.get("direction", "outbound")}
                for r in e.get("edges", [])
            ],
        }
    edge_defs = {}
    for p in sorted((pkg / "edges").glob("*.edge.json")):
        d = json.loads(p.read_text())
        edge_defs[d["slug"]] = {"sources": d.get("sources", []), "targets": d.get("targets", [])}
    ledger = json.loads((pkg / "ledger" / "aws_coverage_ledger.json").read_text())
    states: dict[str, str] = {}
    for row in ledger["rows"]:
        for et in row.get("entity_types", []):
            states[et] = row["state"]
    return {
        "ledger_rows": sorted(
            (
                {"type_name": r["type_name"], "state": r["state"], "tier": r.get("tier"), "entity_types": r.get("entity_types", [])}
                for r in ledger["rows"]
            ),
            key=lambda r: r["type_name"],
        ),
        "types": types,
        "edge_defs": edge_defs,
        "ops": sorted(ops | _custom_ops(bdir)),
        "ledger_state": states,
    }
