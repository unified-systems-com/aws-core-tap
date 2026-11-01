#!/usr/bin/env python3
"""Rank AWS services by weight and track, per type, what stands between a collected row and a retirable one.

A test instrument like tools/crosscheck: it parses the plugin's source (models by AST, the manifest, edge
definitions, tap-plugin.toml and the coverage ledger as data), imports nothing of it, calls no AWS API and
writes only its output. The same inputs give the same file, so the committed hit-list.json can be regenerated
and compared (tests/test_hit_list.py), and a stale one fails.

    hit_list.py [--plugin <aws-core-tap root>] [--weights tools/crosscheck/weights/fedramp-additions-v1.json]
                [--out tools/coverage/hit-list.json] [--check]

Service weight = the sum, over the in-scope ledger types of that service (tier ``both``, the standing scope
ruling), of the weighting's cfn_type weight for each type. Services whose weight is 0 are left out.
"""

from __future__ import annotations

import argparse
import ast
import collections
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "crosscheck"))  # the script is run isolated (-I), which drops its own directory

import weighting  # noqa: E402

PKG = Path("tap_plugin") / "aws_core"
DEFAULT_WEIGHTS = HERE.parent / "crosscheck" / "weights" / "fedramp-additions-v1.json"
COLLECTED = ("collected-unverified", "collected-verified")


def _classvar(cls: ast.ClassDef, name: str) -> Any:
    for s in cls.body:
        if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name) and s.target.id == name and s.value is not None:
            try:
                return ast.literal_eval(s.value)
            except ValueError:
                return None
    return None


def read_plugin(plugin: Path) -> dict[str, Any]:
    """What the plugin declares about retirement: containment, falsifiers, and the ledger rows."""
    pkg = plugin / PKG
    edge_targets: dict[str, list[str]] = {}
    for p in sorted((pkg / "edges").glob("*.edge.json")):
        d = json.loads(p.read_text())
        edge_targets[d["slug"]] = list(d.get("targets", []))
    parents: dict[str, list[str]] = {}  # parent entity type -> contained entity types
    contained: dict[str, str] = {}  # contained entity type -> the edge that contains it
    for p in sorted((pkg / "models").glob("*.py")):
        for c in ast.parse(p.read_text()).body:
            if not isinstance(c, ast.ClassDef):
                continue
            et, edges = _classvar(c, "ENTITY_TYPE"), _classvar(c, "CONTAINMENT_EDGES")
            if not et or not edges:
                continue
            kids = sorted({t for e in edges for t in edge_targets.get(e, [])})
            parents[et] = kids
            for e in edges:
                for t in edge_targets.get(e, []):
                    contained.setdefault(t, e)
    falsifiers = tomllib.loads((pkg / "tap-plugin.toml").read_text()).get("falsifiers", {})
    manifest = json.loads((pkg / "collectors" / "boto3_collector" / "aws_resource_manifest.json").read_text())
    ledger = json.loads((pkg / "ledger" / "aws_coverage_ledger.json").read_text())
    return {
        "parents": parents,
        "contained": contained,
        "falsifiers": falsifiers,
        "manifest_containment": sorted(e["entity_type"] for e in manifest["entries"] if e.get("containment")),
        "ledger": ledger,
    }


def build(plugin: Path, weights_path: Path) -> dict[str, Any]:
    w = weighting.load(weights_path)
    src = read_plugin(plugin)
    config = json.loads((HERE / "config-resource-types.json").read_text())
    config_types = set(config["types"])
    decisions = json.loads((HERE / "decisions.json").read_text())["decisions"]
    services: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in src["ledger"]["rows"]:
        if row.get("tier") != "both":
            continue
        weight = w.cfn(row["type_name"])
        if weight <= 0:
            continue
        ets = sorted(row.get("entity_types", []))
        collected = row["state"] in COLLECTED
        is_contained = any(t in src["contained"] for t in ets)
        has_falsifier = any(t in src["falsifiers"] for t in ets)
        children = sorted({k for t in ets for k in src["parents"].get(t, [])})
        services[row["type_name"].split("::")[1]].append(
            {
                "type_name": row["type_name"],
                "weight": weight,
                "state": row["state"],
                "entity_types": ets,
                "has_completeness_surface": is_contained,
                "has_falsifier": has_falsifier,
                "reconcilable": is_contained and has_falsifier,
                "cascade_parent_of": children,
                "config_supported": row["type_name"] in config_types,
                "falsifier_gap": collected and not has_falsifier,
                "reconcile_gap": collected and not (is_contained and has_falsifier),
                "cascade_decision": decisions.get(row["type_name"], "undecided"),
            }
        )
    out = []
    for name, types in services.items():
        types.sort(key=lambda t: (-t["weight"], t["type_name"]))
        collected = [t for t in types if t["state"] in COLLECTED]
        out.append(
            {
                "service": name,
                "weight": sum(t["weight"] for t in types),
                "types": len(types),
                "collected": len(collected),
                "unclassified": sum(t["state"] == "unclassified" for t in types),
                "with_falsifier": sum(t["has_falsifier"] for t in collected),
                "reconcilable": sum(t["reconcilable"] for t in collected),
                "cascade_parents": sum(bool(t["cascade_parent_of"]) for t in collected),
                "config_supported": sum(t["config_supported"] for t in types),
                "rows": types,
            }
        )
    out.sort(key=lambda s: (-s["weight"], s["service"]))
    for rank, s in enumerate(out, 1):
        s["rank"] = rank
    return {
        "description": "Per weighted service: how many in-scope types the ledger holds, how many are collected, and for those how many have a falsifier, a completeness surface and both (reconcilable). Generated by tools/coverage/hit_list.py; do not edit.",
        "formula": "service weight = sum of the weighting's cfn_type weight over the service's in-scope (tier both) ledger types; weight 0 omitted",
        "inputs": {
            "weighting": {"name": w.name, "version": w.version, "status": w.status, "chain": list(w.chain), "sha256": w.sha256},
            "ledger_botocore_version": src["ledger"]["botocore_version"],
            "config_types_botocore_version": config["botocore_version"],
            "manifest_containment_entries": len(src["manifest_containment"]),
            "falsifier_rows": len(src["falsifiers"]),
        },
        "services": out,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plugin", type=Path, default=HERE.parents[1])
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument("--out", type=Path, default=HERE / "hit-list.json")
    ap.add_argument("--check", action="store_true", help="exit 1 if --out is not what the inputs produce")
    args = ap.parse_args()
    text = json.dumps(build(args.plugin, args.weights), indent=1, sort_keys=True) + "\n"
    if args.check:
        same = args.out.exists() and args.out.read_text() == text
        print("hit list is current" if same else "hit list is stale: regenerate it")
        return 0 if same else 1
    args.out.write_text(text)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
