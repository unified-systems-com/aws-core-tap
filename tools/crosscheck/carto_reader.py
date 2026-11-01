"""Read Cartography's AWS data model from its source tree, by AST only.

Cartography is never imported or run: its models are dataclasses with literal labels, property
references and relationship classes, so a parse is enough and executes nothing from the clone.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

# Boto3 client methods that read. Matches Cartography's call style (`client.describe_x`, paginators).
_READ_PREFIX = re.compile(r"^(describe|list|get|batch_get|lookup|search)_")


def _const(node: ast.AST | None) -> Any:
    return node.value if isinstance(node, ast.Constant) else None


def _call_name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Call):
        f = node.func
        return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
    return None


def _defaults(cls: ast.ClassDef) -> dict[str, ast.AST]:
    """Annotated class attributes with a default: `label: str = "X"` -> {"label": <node>}."""
    return {
        s.target.id: s.value
        for s in cls.body
        if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name) and s.value is not None
    }


def _base_names(cls: ast.ClassDef) -> list[str]:
    return [b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in cls.bases]


def commit_of(root: Path) -> str:
    """The checkout's HEAD commit, read from the .git files directly (no git process), or 'unknown'."""
    try:
        git = root / ".git"
        if git.is_file():  # a worktree or submodule: ".git" is a file pointing at the real directory
            line = git.read_text().strip()
            if line.startswith("gitdir:"):
                git = (root / line.split(":", 1)[1].strip()).resolve()
        head = (git / "HEAD").read_text().strip()
        if not head.startswith("ref:"):
            return head
        ref = head.split(":", 1)[1].strip()
        common = git
        if (git / "commondir").is_file():  # a worktree keeps shared refs in the main git directory
            common = (git / (git / "commondir").read_text().strip()).resolve()
        for base in (git, common):
            if (base / ref).is_file():
                return (base / ref).read_text().strip()
        packed = common / "packed-refs"
        if packed.is_file():
            for line in packed.read_text().splitlines():
                if line.endswith(" " + ref) and not line.startswith(("#", "^")):
                    return line.split()[0]
    except OSError:
        pass
    return "unknown"


def _index(models_dir: Path) -> tuple[dict[str, ast.ClassDef], dict[str, Any]]:
    """Every class and module constant under models/: relationship classes are imported across files."""
    classes: dict[str, ast.ClassDef] = {}
    consts: dict[str, Any] = {}
    for p in sorted(models_dir.rglob("*.py")):
        for c in ast.parse(p.read_text()).body:
            if isinstance(c, ast.ClassDef):
                classes.setdefault(c.name, c)
            elif isinstance(c, ast.Assign) and len(c.targets) == 1 and isinstance(c.targets[0], ast.Name):
                consts.setdefault(c.targets[0].id, _const(c.value))
    return classes, consts


def _extract_file(path: Path, gclasses: dict[str, ast.ClassDef], consts: dict[str, Any], root: Path) -> list[dict]:
    tree = ast.parse(path.read_text())
    local = {c.name: c for c in tree.body if isinstance(c, ast.ClassDef)}
    classes = {**gclasses, **local}  # a same-file class wins over a same-named one elsewhere
    nodes = []
    for name, cls in local.items():
        if "CartographyNodeSchema" not in _base_names(cls):
            continue
        d = _defaults(cls)
        label_node = d.get("label")
        label = _const(label_node)
        if label is None and isinstance(label_node, ast.Name):
            label = consts.get(label_node.id)
        extra: list[str] = []
        ex = d.get("extra_node_labels")
        if isinstance(ex, ast.Call) and ex.args and isinstance(ex.args[0], (ast.List, ast.Tuple)):
            for e in ex.args[0].elts:
                v = _const(e) if isinstance(e, ast.Constant) else consts.get(e.id) if isinstance(e, ast.Name) else None
                if isinstance(v, str):
                    extra.append(v)
        props: dict[str, dict] = {}
        pcls = classes.get(_call_name(d.get("properties")) or "")
        if pcls:
            for field, v in _defaults(pcls).items():
                if _call_name(v) == "PropertyRef" and isinstance(v, ast.Call) and v.args:
                    kw = {k.arg: _const(k.value) for k in v.keywords}
                    props[field] = {"key": _const(v.args[0]), "kwargs": bool(kw.get("set_in_kwargs"))}
        rel_classes: list[tuple[str, str | None]] = []
        sub = d.get("sub_resource_relationship")
        if sub is not None:
            rel_classes.append(("sub_resource", _call_name(sub)))
        oth = d.get("other_relationships")
        if isinstance(oth, ast.Call) and oth.args and isinstance(oth.args[0], (ast.List, ast.Tuple)):
            rel_classes += [("other", _call_name(e)) for e in oth.args[0].elts]
        rels = []
        for kind, rname in rel_classes:
            rc = classes.get(rname or "")
            if rc is None:
                rels.append({"kind": kind, "class": rname, "target": None, "rel": None, "direction": None})
                continue
            rd = _defaults(rc)
            tl = rd.get("target_node_label")
            target = _const(tl)
            if target is None and isinstance(tl, ast.Name):
                target = consts.get(tl.id)
            dirn = rd.get("direction")
            rels.append(
                {
                    "kind": kind,
                    "class": rname,
                    "target": target,
                    "rel": _const(rd.get("rel_label")),
                    "direction": dirn.attr if isinstance(dirn, ast.Attribute) else None,
                }
            )
        nodes.append(
            {
                "label": label,
                "extra_labels": extra,
                "class": name,
                "file": str(path.relative_to(root)),
                "properties": props,
                "rels": rels,
            }
        )
    return nodes


def read_models(root: Path) -> dict[str, Any]:
    """Node schemas under cartography/models/aws (merged by label) and every label defined anywhere in models/."""
    models = root / "cartography" / "models"
    gclasses, consts = _index(models)
    all_labels: set[str] = set()
    for p in sorted(models.rglob("*.py")):
        # Labels declared on helper objects (`ExtraNodeLabel(label="AWSPolicy", ...)`, the ontology's shared labels).
        for call in (c for c in ast.walk(ast.parse(p.read_text())) if isinstance(c, ast.Call)):
            all_labels.update(
                k.value.value for k in call.keywords if k.arg == "label" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)
            )
        for n in _extract_file(p, gclasses, consts, root):
            if n["label"]:
                all_labels.add(n["label"])
            all_labels.update(n["extra_labels"])
    nodes: dict[str, dict] = {}
    for p in sorted((models / "aws").rglob("*.py")):
        for n in _extract_file(p, gclasses, consts, root):
            m = nodes.setdefault(n["label"], {"label": n["label"], "properties": {}, "rels": [], "files": []})
            for k, v in n["properties"].items():
                # A label's sub-schemas (match-link schemas) key the same property from different datasets on purpose.
                m["properties"].setdefault(k, v)
            have = {(r["rel"], r["target"], r["direction"], r["kind"]) for r in m["rels"]}
            m["rels"] += [r for r in n["rels"] if (r["rel"], r["target"], r["direction"], r["kind"]) not in have]
            m["files"].append(n["file"])
    return {"nodes": nodes, "all_labels": sorted(all_labels)}


def read_ops(root: Path) -> set[tuple[str, str]]:
    """(service, operation) pairs Cartography's AWS intel calls, normalised; service is '?' when a file uses several."""
    out: set[tuple[str, str]] = set()
    for p in sorted((root / "cartography" / "intel" / "aws").rglob("*.py")):
        tree = ast.parse(p.read_text())
        services: set[str] = set()
        methods: set[str] = set()
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            fname = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if fname in ("client", "create_boto3_client") and n.args:
                for a in n.args[:2]:
                    s = _const(a)
                    if isinstance(s, str) and re.fullmatch(r"[a-z0-9-]+", s):
                        services.add(s)
            if fname == "get_paginator" and n.args and isinstance(_const(n.args[0]), str):
                methods.add(_const(n.args[0]))
            elif isinstance(f, ast.Attribute) and _READ_PREFIX.match(f.attr):
                methods.add(f.attr)
        svc = next(iter(services)) if len(services) == 1 else "?"
        out |= {(norm(svc), norm(m)) for m in methods}
    return out


def self_checks(models: dict[str, Any]) -> list[dict]:
    """Candidate defects in Cartography's own model, found statically. Each is a lead to verify, not a verdict."""
    findings: list[dict] = []
    known = set(models["all_labels"])
    for label, n in sorted(models["nodes"].items()):
        for r in n["rels"]:
            t = r.get("target")
            if t is None:
                continue
            if t not in known:
                findings.append(
                    {
                        "id": f"dangling-target:{label}:{r.get('rel')}:{t}",
                        "kind": "relationship targets a label no schema defines",
                        "label": label,
                        "evidence": f"{r.get('class')} in {n['files'][0]}: target_node_label={t!r}, rel_label={r.get('rel')!r}",
                    }
                )
    return findings


def norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())
