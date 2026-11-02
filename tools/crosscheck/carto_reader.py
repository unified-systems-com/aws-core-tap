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


_SHA = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


def commit_of(root: Path) -> str:
    """The checkout's HEAD commit, read from the .git files directly (no git process), or 'unknown'.

    Only a value shaped like a commit id is ever returned, and a ref must live under refs/, so a hostile tree
    cannot make the report quote some other file. A ``.git`` file, ``commondir`` or symlink that leads outside the
    tree is not followed: a worktree of a checkout therefore reports 'unknown'; use a clone.
    """
    sha = _commit_of(root)
    return sha if _SHA.match(sha) else "unknown"


def tree_digest(root: Path, patterns: list[str]) -> str:
    """A digest of the files a run actually analysed, so an edit that leaves the commit unchanged still shows."""
    import hashlib

    h = hashlib.sha256()
    for pat in patterns:
        for p in sorted(root.glob(pat)):
            if p.is_file():
                h.update(str(p.relative_to(root)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def _plain(path: Path, root: Path) -> Path:
    """``path``, or an OSError (answered as 'unknown' by the caller) if it is outside ``root`` or if it, or any
    directory between ``root`` and it, is a symlink: nothing in an analysed tree is read through a link, because
    the link, not the tree, would choose the file. A leaf check alone misses ``refs`` pointing elsewhere."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        raise OSError(f"outside the analysed tree: {path.name}") from None
    here = root
    for part in parts:
        here = here / part
        if here.is_symlink():
            raise OSError(f"refusing to read through a symlink: {here.name}")
    return path


_TAG = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def tag_commit(root: Path, tag: str) -> str | None:
    """The commit that tag ``tag`` of the checkout at ``root`` names, or None when the tag is not there or the
    checkout cannot be read plainly (a link anywhere on the way, a worktree pointer). A packed tag carries its
    peeled commit. A loose tag file holds the tag object when the tag is annotated, which is not followed: the
    value is returned as it stands and so will not equal the checkout's commit, which reads as not bound."""
    if not _TAG.match(tag):
        return None
    rroot = root.resolve()
    try:
        git = _plain(rroot / ".git", rroot)
        if not git.is_dir():
            return None
        loose = _plain(git / "refs" / "tags" / tag, rroot)
        if loose.is_file():
            value = loose.read_text().strip()
            return value if _SHA.match(value) else None
        packed = _plain(git / "packed-refs", rroot)
        if packed.is_file():
            lines = packed.read_text().splitlines()
            for i, line in enumerate(lines):
                if line.endswith(" refs/tags/" + tag) and not line.startswith(("#", "^")):
                    sha = line.split()[0]
                    if i + 1 < len(lines) and lines[i + 1].startswith("^"):
                        sha = lines[i + 1][1:].strip()
                    return sha if _SHA.match(sha) else None
    except OSError:
        pass
    return None


def _commit_of(root: Path) -> str:
    rroot = root.resolve()
    try:
        git = _plain(rroot / ".git", rroot)
        if git.is_file():  # a worktree or submodule: ".git" is a file pointing at the real directory
            line = git.read_text().strip()
            if line.startswith("gitdir:"):
                git = (root / line.split(":", 1)[1].strip()).resolve()
        if not git.resolve().is_relative_to(root.resolve()):
            return "unknown"  # a pointer out of the analysed tree is untrusted input, so a worktree reports no commit
        head = _plain(git / "HEAD", rroot).read_text().strip()
        if not head.startswith("ref:"):
            return head
        ref = head.split(":", 1)[1].strip()
        if not ref.startswith("refs/") or ".." in ref.split("/"):
            return "unknown"
        common = git
        if _plain(git / "commondir", rroot).is_file():  # a worktree keeps shared refs in the main git directory
            common = (git / _plain(git / "commondir", rroot).read_text().strip()).resolve()
            if not common.is_relative_to(root.resolve()):
                return "unknown"
        for base in (git, common):
            if _plain(base / ref, rroot).is_file():
                return _plain(base / ref, rroot).read_text().strip()
        packed = _plain(common / "packed-refs", rroot)
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


def _standalone_rels(path: Path, consts: dict[str, Any]) -> list[dict]:
    """Relationship schemas declared on their own (match-links) name both ends: source_node_label and target_node_label."""
    out = []
    for cls in (c for c in ast.parse(path.read_text()).body if isinstance(c, ast.ClassDef)):
        d = _defaults(cls)
        if "CartographyRelSchema" not in _base_names(cls) or "source_node_label" not in d:
            continue

        def lab(key: str) -> Any:
            v = d.get(key)
            return consts.get(v.id) if isinstance(v, ast.Name) else _const(v)

        dirn = d.get("direction")
        out.append(
            {
                "kind": "standalone",
                "class": cls.name,
                "source": lab("source_node_label"),
                "target": lab("target_node_label"),
                "rel": _const(d.get("rel_label")),
                "direction": dirn.attr if isinstance(dirn, ast.Attribute) else None,
            }
        )
    return out


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
    if not (models / "aws").is_dir():
        raise ValueError(f"{root} has no cartography/models/aws: this does not look like a Cartography checkout")
    nodes: dict[str, dict] = {}
    standalone: list[dict] = []
    for p in sorted((models / "aws").rglob("*.py")):
        standalone += _standalone_rels(p, consts)
        for n in _extract_file(p, gclasses, consts, root):
            m = nodes.setdefault(n["label"], {"label": n["label"], "properties": {}, "rels": [], "files": []})
            for k, v in n["properties"].items():
                # A label's sub-schemas (match-link schemas) key the same property from different datasets on purpose.
                m["properties"].setdefault(k, v)
            have = {(r["rel"], r["target"], r["direction"], r["kind"]) for r in m["rels"]}
            m["rels"] += [r for r in n["rels"] if (r["rel"], r["target"], r["direction"], r["kind"]) not in have]
            m["files"].append(n["file"])
    if not nodes:
        raise ValueError(f"no AWS node schemas found under {models / 'aws'}: refusing to score against an empty reference")
    for r in standalone:  # attach each to its source node, once
        n = nodes.get(r["source"])
        key = (r["rel"], r["target"], r["direction"], r["kind"])
        if n is not None and key not in {(x["rel"], x["target"], x["direction"], x["kind"]) for x in n["rels"]}:
            n["rels"].append({k: r[k] for k in ("kind", "class", "target", "rel", "direction")})
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
