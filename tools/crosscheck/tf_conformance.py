#!/usr/bin/env python3
"""API-field conformance of aws_core against the Terraform AWS provider, statically.

For each of our entity types that maps to one or more Terraform resources, compare the AWS API key each of
our typed fields is filled from (the manifest entry's `fields`) with the API field the provider fills the
same attribute from (`d.Set` in its read function), and our read operations with the provider's.

Terraform is a reference, not ground truth: the provider can read a different field for good reasons, can be
wrong, and is a write-model (an attribute may be a setting we do not hold). A disagreement is a lead for a
human, decided against the AWS API model or a live account (specs/spec-aws-core-collection-oracle.md).

    tf_conformance.py --terraform-schema schema.json --terraform-source ~/src/terraform-provider-aws
                      [--terraform-version 6.71.0] [--plugin <aws-core-tap root>]
                      [--weights weights/cartography-set-v1.json] [--out DIR]

The schema file comes from terraform_dump.sh; the source is only parsed (tree-sitter), never built or run.
Needs `pip install -r tools/crosscheck/requirements-terraform.txt` for the source layer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # sibling modules; the script is run isolated (-I), which drops its own directory

import carto_reader  # noqa: E402
import tap_reader  # noqa: E402
import terraform_reader  # noqa: E402
import weighting  # noqa: E402
from carto_reader import norm  # noqa: E402

SCHEMA_VERSION = 1
IGNORED_ATTRS = {"id", "region", "timeouts"}  # added to every resource by the provider framework at runtime
TAG_ATTRS = {"tags", "tags_all"}  # compared by the tags metric of the main crosscheck, not here
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f  ]")


def _clean(s: object) -> str:
    return _CTRL.sub("?", str(s))


def _pct(a: float, b: float) -> float | None:
    return None if not b else round(100.0 * a / b, 1)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------- mapping

def resolve(tap_types: set[str], tf_types: set[str], amap: dict) -> tuple[dict[str, list[str]], list[str]]:
    """{our type: [Terraform resources]} and the stale alias entries.

    A Terraform resource named in the alias file maps only where the file says (an empty list is a reviewed gap);
    any other is matched to our type of the same name once `aws_core__aws_` / `aws_` are stripped and only lower-case
    letters and digits are compared. Several Terraform resources may map to one type of ours.
    """
    aliases = amap["aliases"]
    by_name: dict[str, str] = {}
    for t in sorted(tap_types):
        by_name.setdefault(norm(t.replace("aws_core__aws_", "").replace("aws_core__", "")), t)
    out: dict[str, list[str]] = {}
    stale: list[str] = []
    for tf in sorted(tf_types):
        if tf in aliases:
            targets = [t for t in aliases[tf] if t in tap_types]
            if len(targets) != len(aliases[tf]):
                stale.append(f"{tf}: target type not found")
        else:
            hit = by_name.get(norm(tf.replace("aws_", "", 1)))
            targets = [hit] if hit else []
        for t in targets:
            out.setdefault(t, []).append(tf)
    stale += [f"{tf}: not in the schema dump" for tf in sorted(set(aliases) - tf_types)]
    return out, stale


# ---------------------------------------------------------------- comparison

def _leaf(path: str) -> str:
    return norm(re.sub(r"\[\]", "", path).split(".")[-1])


def _segments(path: str) -> list[str]:
    return [norm(s) for s in re.sub(r"\[\]", "", path).split(".")]


def our_fields(entry: dict) -> tuple[dict[str, str], list[str]]:
    """({field: API path}, [derived fields]) of a type; a source starting with '_' is computed by the collector."""
    m = entry["manifest"]
    if not m:
        return {}, []
    typed = {f: p for f, p in m["field_sources"].items() if isinstance(p, str) and not p.startswith("_")}
    derived = sorted(f for f, p in m["field_sources"].items() if not isinstance(p, str) or p.startswith("_"))
    return typed, derived


def terraform_attrs(tf_types: list[str], dump: dict, src: dict) -> dict[tuple[str, str], dict[str, Any]]:
    """{(resource, attribute): {leaves, paths, at, expr, mapping}} for the top-level attributes the provider reads."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for tf in tf_types:
        d = dump["resources"][tf]
        s = src["resources"].get(tf)
        for a in d["top_level"]:
            if a in IGNORED_ATTRS or a in TAG_ATTRS or d["attributes"][a].get("write_only"):
                continue
            row = (s or {}).get("api", {}).get(a)
            paths = list(row["api"]) if row else []
            out[(tf, a)] = {
                "paths": paths,
                "leaves": sorted({_leaf(p) for p in paths}),
                "at": (row or {}).get("at", ""),
                "expr": (row or {}).get("expr", ""),
                "mapping": (s or {}).get("mapping") if row else None,
                "has_source": s is not None,
            }
    return out


def _kind(ours: str, theirs: list[str]) -> str:
    """'name-variant' when one API key is the other with a word added (Name / CatalogName), else 'different-field'."""
    a = _leaf(ours)
    for t in theirs:
        b = _leaf(t)
        if a and b and (a.endswith(b) or b.endswith(a) or a.startswith(b) or b.startswith(a)):
            return "name-variant"
    return "different-field"


def compare_pair(our_type: str, entry: dict, tf_types: list[str], dump: dict, src: dict, primary: set[str] | None = None) -> dict[str, Any]:
    typed, derived = our_fields(entry)
    attrs = terraform_attrs(tf_types, dump, src)
    agree: list[dict] = []
    partial: list[dict] = []
    differ: list[dict] = []
    unverified: list[dict] = []
    ours_only: list[dict] = []
    matched_attrs: set[tuple[str, str]] = set()
    for f, p in sorted(typed.items()):
        leaf, segs = _leaf(p), _segments(p)
        hit = [(k, v) for k, v in sorted(attrs.items()) if leaf in v["leaves"]]
        part = [(k, v) for k, v in sorted(attrs.items()) if not hit and v["leaves"] and any(x in segs[:-1] for x in v["leaves"])]
        named = [(k, v) for k, v in sorted(attrs.items()) if norm(k[1]) == norm(f)]
        if hit:
            matched_attrs.update(k for k, _ in hit)
            k, v = hit[0]
            agree.append({"field": f, "api": p, "terraform": f"{k[0]}.{k[1]}", "terraform_api": v["paths"], "at": v["at"], "basis": v["mapping"]})
        elif part:
            matched_attrs.update(k for k, _ in part)
            k, v = part[0]
            partial.append({"field": f, "api": p, "terraform": f"{k[0]}.{k[1]}", "terraform_api": v["paths"], "at": v["at"], "basis": v["mapping"]})
        elif named:
            # A name shared with a settings resource of a split type (a bucket's `name` and a tiering configuration's)
            # says nothing, so only the type's own resource can make a disagreement.
            named = [(k, v) for k, v in named if len(tf_types) == 1 or primary is None or k[0] in primary] or named
            k = next((k for k, v in named if v["leaves"]), named[0][0])
            v = attrs[k]
            matched_attrs.update(kk for kk, _ in named)
            row = {"field": f, "api": p, "terraform": f"{k[0]}.{k[1]}", "terraform_api": v["paths"], "at": v["at"], "expr": v["expr"], "basis": v["mapping"]}
            if v["leaves"] and (len(tf_types) == 1 or primary is None or k[0] in primary):
                row["kind"] = _kind(p, v["paths"])
                differ.append(row)
            else:
                unverified.append(row)
        else:
            ours_only.append({"field": f, "api": p})
    tf_only = [
        {"terraform": f"{k[0]}.{k[1]}", "terraform_api": v["paths"], "at": v["at"]}
        for k, v in sorted(attrs.items())
        if k not in matched_attrs and v["leaves"]
    ]
    unmapped = sum(1 for k, v in attrs.items() if not v["leaves"])
    ours_ops = set(entry["manifest"]["ops"]) if entry["manifest"] else set()
    tf_ops = {norm(o) for tf in tf_types for o in (src["resources"].get(tf) or {}).get("ops", [])}
    return {
        "type": our_type,
        "terraform_resources": sorted(tf_types),
        "persist_configuration": bool(entry["manifest"] and entry["manifest"]["persist_configuration"]),
        "our_typed_fields": len(typed),
        "our_derived_fields": len(derived),
        "terraform_attributes": len(attrs),
        "terraform_attributes_with_api_field": sum(1 for v in attrs.values() if v["leaves"]),
        "terraform_attributes_without_api_field": unmapped,
        "agree": agree,
        "partial": partial,
        "differ": differ,
        "unverified_name_match": unverified,
        "terraform_only": tf_only,
        "ours_only": ours_only,
        "operations": {
            "ours": sorted(ours_ops),
            "terraform": sorted(tf_ops),
            "shared": sorted(ours_ops & tf_ops),
            "ours_only": sorted(ours_ops - tf_ops),
            "terraform_only": sorted(tf_ops - ours_ops),
        },
        "has_manifest_mapping": bool(typed),
    }


def names_check(dump: dict, src: dict) -> dict[str, Any]:
    """Attribute names read from the Go source against the schema dump, per resource, ignoring id, region and timeouts."""
    same = 0
    diffs: list[dict] = []
    both = sorted(set(dump["resources"]) & set(src["resources"]))
    for t in both:
        s = src["resources"][t]
        a = set(dump["resources"][t]["top_level"]) - IGNORED_ATTRS
        b = set(s["attributes"]) - IGNORED_ATTRS
        if s["schema_found"] and a == b:
            same += 1
        else:
            diffs.append({"type": t, "schema_found": s["schema_found"], "only_in_dump": sorted(a - b), "only_in_source": sorted(b - a)})
    return {
        "resources_in_dump": len(dump["resources"]),
        "resources_in_source": len(src["resources"]),
        "compared": len(both),
        "identical": same,
        "identical_pct": _pct(same, len(both)),
        "in_source_not_in_dump": sorted(set(src["resources"]) - set(dump["resources"])),
        "in_dump_not_in_source": sorted(set(dump["resources"]) - set(src["resources"])),
        "different": diffs,
    }


# ---------------------------------------------------------------- run

def run(schema: Path, source: Path, plugin: Path, weights_path: Path, version: str = "unknown") -> dict[str, Any]:
    import terraform_source  # imported here: the one module that needs tree-sitter

    dump = terraform_reader.read(schema)
    src = terraform_source.read(source)
    tap = tap_reader.read(plugin)
    amap_p = HERE / "terraform_label_map.json"
    amap = json.loads(amap_p.read_text())
    w = weighting.load(weights_path)
    mapping, stale = resolve(set(tap["types"]), set(dump["resources"]), amap)
    pairs = []
    for t in sorted(mapping):
        by_name = {r for r in mapping[t] if r not in amap["aliases"]}
        row = compare_pair(t, tap["types"][t], mapping[t], dump, src, by_name or None)
        row["weight"] = w.concept(None, (t,))
        pairs.append(row)
    compared = [p for p in pairs if p["has_manifest_mapping"]]
    no_tf = sorted(
        ({"type": t, "weight": w.concept(None, (t,))} for t in tap["types"] if t not in mapping),
        key=lambda r: (-r["weight"], r["type"]),
    )
    rep: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "inputs": {
            "terraform_schema": {"sha256": dump["sha256"], "provider_version": _clean(version), "resources": len(dump["resources"])},
            "terraform_source": {
                "commit": src["commit"],
                "source_sha256": src["source_sha256"],
                "files_parsed": src["files_parsed"],
                "files_with_parse_error": src["files_with_parse_error"],
                "resources": len(src["resources"]),
            },
            "aws_core": {"commit": carto_reader.commit_of(plugin), "types": len(tap["types"]), "source_sha256": tap["digest"]},
            "weighting": {"name": w.name, "version": w.version, "status": w.status, "chain": list(w.chain), "sha256": w.sha256},
            "terraform_label_map_sha256": _sha(amap_p),
        },
        "mapping": {
            "our_types": len(tap["types"]),
            "types_with_terraform_resource": len(mapping),
            "types_compared": len(compared),
            "types_without_terraform_resource": len(no_tf),
            "terraform_resources_used": len({r for v in mapping.values() for r in v}),
            "stale_aliases": stale,
            "note": "Source and schema dump can be different provider versions; see names_check.",
        },
        "names_check": names_check(dump, src),
        "pairs": pairs,
        "types_without_terraform_resource": no_tf,
    }
    rep["headline"] = headline(compared)
    rep["top_disagreements"] = top_disagreements(compared, 10)
    rep["gaps"] = sorted(
        (
            {"type": p["type"], "weight": p["weight"], "terraform_only": len(p["terraform_only"]), "persist_configuration": p["persist_configuration"]}
            for p in compared
            if p["terraform_only"] and p["weight"] > 0
        ),
        key=lambda g: (-g["weight"] * g["terraform_only"], g["type"]),
    )
    return rep


def headline(pairs: list[dict]) -> dict[str, Any]:
    def n(key: str) -> int:
        return sum(len(p[key]) for p in pairs)

    def wn(key: str) -> float:
        return sum(p["weight"] * len(p[key]) for p in pairs)

    ag, pa, di = n("agree"), n("partial"), n("differ")
    wag, wpa, wdi = wn("agree"), wn("partial"), wn("differ")
    tfo = n("terraform_only")
    tfa = sum(p["terraform_attributes_with_api_field"] for p in pairs)
    ops_ours = sum(len(p["operations"]["ours"]) for p in pairs)
    ops_shared = sum(len(p["operations"]["shared"]) for p in pairs)
    ops_tf = sum(len(p["operations"]["terraform"]) for p in pairs)
    return {
        "types_compared": len(pairs),
        "fields_agree": ag,
        "fields_agree_inferred_from_autoflex": sum(1 for p in pairs for d in p["agree"] if d["basis"] != "d.Set"),
        "fields_partial": pa,
        "fields_differ": di,
        "fields_differ_different_field": sum(1 for p in pairs for d in p["differ"] if d["kind"] == "different-field"),
        "fields_differ_name_variant": sum(1 for p in pairs for d in p["differ"] if d["kind"] == "name-variant"),
        "fields_name_match_unverified": n("unverified_name_match"),
        "fields_ours_only": n("ours_only"),
        "terraform_attributes_read_from_api": tfa,
        "terraform_only_attributes": tfo,
        "terraform_only_on_types_storing_configuration": sum(len(p["terraform_only"]) for p in pairs if p["persist_configuration"]),
        "agreement_pct": _pct(ag + pa, ag + pa + di),
        "weighted_agreement_pct": _pct(wag + wpa, wag + wpa + wdi),
        "terraform_attributes_we_hold_pct": _pct(tfa - tfo, tfa),
        "weighted_terraform_attributes_we_hold_pct": _pct(
            sum(p["weight"] * (p["terraform_attributes_with_api_field"] - len(p["terraform_only"])) for p in pairs),
            sum(p["weight"] * p["terraform_attributes_with_api_field"] for p in pairs),
        ),
        "operations_ours": ops_ours,
        "operations_terraform": ops_tf,
        "operations_shared": ops_shared,
        "operations_shared_of_ours_pct": _pct(ops_shared, ops_ours),
        "operations_shared_of_terraform_pct": _pct(ops_shared, ops_tf),
    }


def top_disagreements(pairs: list[dict], n: int) -> list[dict]:
    rows = []
    for p in pairs:
        for d in p["differ"]:
            rows.append({"type": p["type"], "weight": p["weight"], "terraform_resources": p["terraform_resources"], **d})
    # A d.Set line is direct evidence; an autoflex field name is an inference, so it ranks after it.
    rows.sort(key=lambda r: (r["kind"] != "different-field", r["basis"] != "d.Set", -r["weight"], r["type"], r["field"]))
    return rows[:n]


# ---------------------------------------------------------------- output

def markdown(r: dict) -> str:
    h, m, nc = r["headline"], r["mapping"], r["names_check"]
    L = [
        "# aws_core against the Terraform AWS provider",
        "",
        "Terraform is a reference, not ground truth. Static comparison only; a live account decides every disagreement.",
        "",
        f"Provider schema {r['inputs']['terraform_schema']['provider_version']} (sha256 {r['inputs']['terraform_schema']['sha256'][:12]}), "
        f"source commit {r['inputs']['terraform_source']['commit'][:12]}, aws_core {r['inputs']['aws_core']['commit'][:12]}.",
        "",
        "## Headline",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Our types | {m['our_types']} |",
        f"| With a Terraform resource | {m['types_with_terraform_resource']} ({m['terraform_resources_used']} Terraform resources) |",
        f"| Compared (typed manifest fields) | {h['types_compared']} |",
        f"| Fields agree (same API field) | {h['fields_agree']} ({h['fields_agree_inferred_from_autoflex']} of them by autoflex naming, an inference) |",
        f"| Fields partial (we hold a part of what Terraform reads whole) | {h['fields_partial']} |",
        f"| Fields differ (same attribute name, different API field) | {h['fields_differ']} ({h['fields_differ_different_field']} a different field, {h['fields_differ_name_variant']} a name variant) |",
        f"| Fields matched by name only (Terraform has no API field to compare) | {h['fields_name_match_unverified']} |",
        f"| Fields ours only | {h['fields_ours_only']} |",
        f"| Agreement on comparable fields | {h['agreement_pct']}% (weighted {h['weighted_agreement_pct']}%) |",
        f"| Terraform attributes read from the API | {h['terraform_attributes_read_from_api']} |",
        f"| Of those, not held by us | {h['terraform_only_attributes']} ({h['terraform_only_on_types_storing_configuration']} on types that store their whole configuration) |",
        f"| Terraform attributes we hold | {h['terraform_attributes_we_hold_pct']}% (weighted {h['weighted_terraform_attributes_we_hold_pct']}%) |",
        f"| Read operations shared | {h['operations_shared']} of ours {h['operations_ours']}, of Terraform's {h['operations_terraform']} |",
        "",
        "## Source against schema dump",
        "",
        f"{nc['identical']} of {nc['compared']} resources have the same top-level attribute names ({nc['identical_pct']}%), ignoring id, region and timeouts.",
        "",
        "## Largest disagreements",
        "",
    ]
    for d in r["top_disagreements"]:
        L.append(
            f"- {_clean(d['type'])} `{_clean(d['field'])}` is filled from `{_clean(d['api'])}`; Terraform `{_clean(d['terraform'])}` reads "
            f"{', '.join('`' + _clean(x) + '`' for x in d['terraform_api'])} ({_clean(d['basis'])}; {_clean(d['at'])})"
        )
    L += ["", "## Largest gaps: Terraform attributes we do not hold (weight times count)", ""]
    for g in r["gaps"][:15]:
        cfg = "stores its configuration" if g["persist_configuration"] else "does not store its configuration"
        L.append(f"- {_clean(g['type'])} (weight {g['weight']}): {g['terraform_only']} attributes; {cfg}")
    L += ["", "## Types with no Terraform resource (highest weight first)", ""]
    for x in r["types_without_terraform_resource"][:30]:
        L.append(f"- {_clean(x['type'])} (weight {x['weight']})")
    if m["stale_aliases"]:
        L += ["", "## Stale alias entries", ""] + [f"- {_clean(s)}" for s in m["stale_aliases"]]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--terraform-schema", required=True, type=Path, help="schema dump file from terraform_dump.sh")
    ap.add_argument("--terraform-source", required=True, type=Path, help="a checkout of hashicorp/terraform-provider-aws")
    ap.add_argument("--terraform-version", default="unknown", help="the provider version the dump was made with (recorded, not checked)")
    ap.add_argument("--plugin", type=Path, default=HERE.parents[1], help="aws-core-tap checkout (default: this one)")
    ap.add_argument("--weights", type=Path, default=HERE / "weights" / "cartography-set-v1.json")
    ap.add_argument("--out", type=Path, default=None, help="directory for report.json and report.md")
    a = ap.parse_args(argv)
    try:
        rep = run(a.terraform_schema, a.terraform_source, a.plugin, a.weights, a.terraform_version)
    except (ValueError, OSError) as e:
        ap.error(_clean(e))
    except RuntimeError as e:  # MissingDependency
        ap.error(_clean(e))
    text = json.dumps(rep, indent=1, sort_keys=True) + "\n"
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "report.json").write_text(text)
        (a.out / "report.md").write_text(markdown(rep))
    sys.stdout.write(markdown(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
