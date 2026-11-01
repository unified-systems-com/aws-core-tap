"""Read aws_core's data model from its source tree, statically: models by AST, the manifest and edge files as JSON.

aws_core is never imported (that needs Django and a booted plugin); this reader runs anywhere Python does.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from carto_reader import norm, tree_digest

_READ_PREFIX = re.compile(r"^(Describe|List|Get|BatchGet|Lookup|Search)")


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
            if k in ("aws_op", "op") and isinstance(v, str) and _READ_PREFIX.match(v):
                out.add((norm(service), norm(v)))
            else:
                _ops_in(v, service, out)
    elif isinstance(node, list):
        for v in node:
            _ops_in(v, service, out)


_SNAKE_READ = re.compile(r"^(describe|list|get|batch_get|lookup|search)_[a-z0-9_]+$")


def _fn_ops(collector_dir: Path) -> dict[str, set[str]]:
    """Per hand-written function, the normalised read operations it makes, following calls to other functions.

    A manifest entry's `custom_fn` names one of these, so a type is credited only with reads its own reader makes.
    Functions are indexed by module and name, because helpers such as `_pages` are defined in several modules. A call
    resolves to the definition in its own module first, then to a definition that is unique across the directory; an
    ambiguous call is followed nowhere, so a collision can lose credit but never invent it. The result is keyed by the
    bare name for functions whose name is unique, which is how the manifest refers to them.
    """
    direct: dict[tuple[str, str], set[str]] = {}
    calls: dict[tuple[str, str], set[str]] = {}
    for p in sorted(collector_dir.glob("*.py")):
        mod = p.stem
        for fn in (n for n in ast.walk(ast.parse(p.read_text())) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            ops, callees = direct.setdefault((mod, fn.name), set()), calls.setdefault((mod, fn.name), set())
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    f = n.func
                    if isinstance(f, ast.Attribute) and _SNAKE_READ.match(f.attr):
                        ops.add(norm(f.attr))
                    if isinstance(f, ast.Name):
                        callees.add(f.id)
                    for a in n.args:  # a literal read name handed to a listing helper: _pages(client, "list_x")
                        if isinstance(a, ast.Constant) and isinstance(a.value, str) and _SNAKE_READ.match(a.value):
                            ops.add(norm(a.value))
    by_name: dict[str, list[tuple[str, str]]] = {}
    for key in direct:
        by_name.setdefault(key[1], []).append(key)

    def resolve(mod: str, name: str) -> tuple[str, str] | None:
        if (mod, name) in direct:
            return (mod, name)
        found = by_name.get(name, [])
        return found[0] if len(found) == 1 else None

    def closure(key: tuple[str, str]) -> set[str]:
        seen: set[tuple[str, str]] = set()
        stack, acc = [key], set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            acc |= direct[cur]
            for callee in calls[cur]:
                target = resolve(cur[0], callee)
                if target is not None:
                    stack.append(target)
        return acc

    out: dict[str, set[str]] = {}
    for name, keys in by_name.items():
        if len(keys) == 1:  # an ambiguous bare name gets no entry, so a manifest reference to it earns no credit
            out[name] = closure(keys[0])
    return out


def _custom_ops(collector_dir: Path) -> set[tuple[str, str]]:
    """Every read made by any hand-written reader (service unknown); the inventory for operation parity."""
    ops: set[tuple[str, str]] = set()
    for p in sorted(collector_dir.glob("*.py")):
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Call):
                if isinstance(n.func, ast.Attribute) and _SNAKE_READ.match(n.func.attr):
                    ops.add(("?", norm(n.func.attr)))
                for a in n.args:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str) and _SNAKE_READ.match(a.value):
                        ops.add(("?", norm(a.value)))
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
    fn_ops = _fn_ops(bdir)
    manifest = json.loads((bdir / "aws_resource_manifest.json").read_text())
    ops: set[tuple[str, str]] = set()
    for e in manifest["entries"]:
        t = types.setdefault(e["entity_type"], {"fields": [], "natural_key": [], "model_edges": [], "manifest": None})
        own: set[tuple[str, str]] = set()
        _ops_in(e, e.get("service", ""), own)
        ops |= own
        fns = sorted(set(re.findall(r'"custom_fn": "([^"]+)"', json.dumps(e))))
        t["manifest"] = {
            "service": e.get("service"),
            "ops": sorted({o for _, o in own} | {o for f in fns for o in fn_ops.get(f, set())}),
            "custom_fns": fns,
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
    custom = _custom_ops(bdir)
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
        "digest": tree_digest(plugin, [
            "tap_plugin/aws_core/models/*.py", "tap_plugin/aws_core/collectors/boto3_collector/*.py",
            "tap_plugin/aws_core/collectors/boto3_collector/aws_resource_manifest.json",
            "tap_plugin/aws_core/edges/*.edge.json", "tap_plugin/aws_core/ledger/aws_coverage_ledger.json",
        ]),
        "ledger_rows": sorted(
            (
                {"type_name": r["type_name"], "state": r["state"], "tier": r.get("tier"), "entity_types": r.get("entity_types", [])}
                for r in ledger["rows"]
            ),
            key=lambda r: r["type_name"],
        ),
        "types": types,
        "edge_defs": edge_defs,
        "ops": sorted(ops | custom),
        "ledger_state": states,
    }
