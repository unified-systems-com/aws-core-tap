#!/usr/bin/env python3
"""Check aws_core against AWS's own CloudFormation data, statically and deterministically.

Reads files only: per-region resource specifications (fetched beforehand by cfn_fetch.sh), the CloudFormation
schema bundle, the coverage ledger, the model sources, a weighting and, optionally, the wave-0 run record. It makes
no network call and no AWS call, and writes nothing but its report. The same inputs give the same report.

The downloaded inputs (specifications, bundle, manifest, run record) are data and are never imported. The plugin
checkout is code: the bundle is read through the ledger's own reader, loaded from <plugin>/tap_plugin/aws_core/
ledger/sources.py, so point --plugin only at a checkout you trust. The default is this one.

    cfn_verifier.py --spec spec-us-gov-west-1.json [--spec ...] [--bundle CloudformationSchema.zip]
                    [--plugin <aws-core-tap root>] [--weights weights/cartography-set-v1.json]
                    [--manifest manifest.tsv] [--run-record wave0.json] [--out DIR]
                    [--baseline report.json] [--fail-on-regression]

The specification is a REFERENCE, not ground truth. Absence from a regional specification is a lead: in the wave-0
record 117 types the specification lacks still had a working call path. Properties are compared at the top level
only, by normalised name; a nested property is credited to its top-level parent.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # sibling modules; the script is run isolated (-I), which drops its own directory

import cfn_reader  # noqa: E402
import tap_reader  # noqa: E402
import weighting  # noqa: E402
from carto_reader import norm  # noqa: E402
from cfn_reader import clean  # noqa: E402

SCHEMA_VERSION = 1
COLLECTED = ("collected-unverified", "collected-verified", "modeled")
WORKS = ("ok", "empty")
NOT_AVAILABLE = ("unsupported", "unsupported-in-partition")
#: Names that make a missing property matter more. A heuristic over property names (inferred, not measured).
SECURITY_NAME = re.compile(
    r"encrypt|kms|public|policy|role|iam|logging|log|ssl|tls|mfa|https|auth|secur|secret|password|cidr|ingress|egress|"
    r"versioning|deletionprotection|backup|retention|accesskey|principal|trust|endpoint|vpc|subnet|acl|permission",
    re.I,
)
IDENTITY_NAME = re.compile(r"^(arn|id|name)$|arn$|id$", re.I)


# ---------------------------------------------------------------- helpers

def _head(path: str) -> str:
    """The top-level property an API key or property path refers to: 'A.B[0].C' -> 'A'."""
    path = path[len("/properties/"):] if path.startswith("/properties/") else path
    return re.split(r"[./\[]", path, maxsplit=1)[0]


def _pct(a: float, b: float) -> float | None:
    return round(100 * a / b, 1) if b else None


def _sha(p: Path) -> str:
    """The sha256 of a regular file. A symlink or a non-file is refused: the path comes from the command line or a
    directory listing of an untrusted download, and a link would let it choose what is read."""
    if p.is_symlink() or not p.is_file():
        raise ValueError(f"not a regular file: {p.name}")
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _confined(path: Path, roots: tuple[Path, ...], what: str) -> Path:
    """``path`` resolved, required to lie inside one of ``roots``. The path comes from the command line, and without
    this a ``..`` or an absolute path would have the verifier read, hash and report on any file its user can read.
    A symlink is refused before resolving, so a link inside a root cannot point out of it. Same shape as the
    ledger's own confinement (tap_plugin/aws_core/ledger/sources.py)."""
    if path.is_symlink():
        raise ValueError(f"{what} is a symbolic link; refused: {clean(path.name)}")
    real = os.path.realpath(path)
    for root in roots:
        base = os.path.realpath(root)
        if real == base or real.startswith(base + os.sep):
            return Path(real)
    raise ValueError(f"{what} must lie inside the plugin checkout or the working directory: {clean(path.name)}")


def region_of(path: Path) -> str:
    m = re.match(r"^spec-(.+)\.json$", path.name)
    return clean(m.group(1) if m else path.stem)


def outcome_class(outcomes: list[str]) -> str | None:
    """works / not-available / other for the outcomes of a ledger type's entity types; None when there are none."""
    if not outcomes:
        return None
    if any(o in WORKS for o in outcomes):
        return "works"
    if any(o in NOT_AVAILABLE for o in outcomes):
        return "not-available"
    return "other"


def read_record(path: Path, plugin: Path) -> dict[str, Any]:
    """The run record named on the command line, which must lie inside the plugin checkout or the working directory
    (a record kept elsewhere is copied in). Returns its digest, partition, regions, size and outcomes per entity type."""
    p = _confined(Path(path), (Path(plugin), Path.cwd()), "the run record")
    doc = json.loads(cfn_reader._read_file(p, 64 << 20))
    if not isinstance(doc, dict) or not isinstance(doc.get("results"), list) or not isinstance(doc.get("run"), dict):
        raise cfn_reader.CfnReadError("the run record has no results list and run object")
    by_entity: dict[str, list[str]] = collections.defaultdict(list)
    for r in doc["results"]:
        by_entity[clean(r["entity_type"])].append(clean(r["outcome"]))
    run = doc["run"]
    return {
        "sha256": _sha(p),
        "partition": clean(run.get("partition", "")),
        "regions": sorted(clean(x) for x in run.get("regions", [])),
        "entries": len(doc["results"]),
        "outcomes": {k: sorted(v) for k, v in sorted(by_entity.items())},
    }


# ---------------------------------------------------------------- (a) availability and the backtest

def _flags(tier: str, present: dict[str, bool], regions: list[str], rec_region: str | None, obs: str | None) -> list[str]:
    flags = []
    gov = [g for g in regions if g.startswith("us-gov")]
    if rec_region and obs:
        p = present[rec_region]
        if p and obs == "not-available":
            flags.append("specification-offers-but-call-unsupported")
        if not p and obs == "works":
            flags.append("specification-lacks-but-call-works")
        if tier == "both" and obs == "not-available":
            flags.append("tier-both-but-call-unsupported")
        if tier == "commercial-only" and obs == "works":
            flags.append("tier-commercial-only-but-call-works")
        if tier == "both" and not p and obs == "not-available":
            flags.append("tier-both-and-specification-lacks-and-call-unsupported")
    elif gov:
        if tier == "both" and not any(present[g] for g in gov):
            flags.append("tier-both-but-specification-lacks-in-gov")
        if tier == "commercial-only" and any(present[g] for g in gov):
            flags.append("tier-commercial-only-but-specification-offers-in-gov")
    return flags


def availability(rows: list[dict], specs: dict[str, dict], record: dict | None) -> dict:
    """Leads per ledger type; contradictions and the backtest per collected unit.

    The unit of the run record is the entity type (what the collector runs), and several ledger types can share
    one, so with a record the contradictions and the backtest are counted per entity type: present means any of
    its ledger types is in the specification, tier is `both` when any of them is.
    """
    regions = sorted(specs)
    rec_region = next((r for r in record["regions"] if r in specs), None) if record else None
    type_rows = []
    for r in rows:
        present = {g: r["type_name"] in specs[g]["types"] for g in regions}
        type_rows.append({"type": r["type_name"], "state": r["state"], "tier": r["tier"], "present": present,
                          "lead_absent_in": [g for g in regions if not present[g]]})
    contradictions: list[dict] = []
    entity_rows: list[dict] = []
    if record and rec_region:
        by_entity: dict[str, list[dict]] = collections.defaultdict(list)
        for r in rows:
            for et in r["entity_types"]:
                by_entity[et].append(r)
        for et, rs in sorted(by_entity.items()):
            present = {g: any(r["type_name"] in specs[g]["types"] for r in rs) for g in regions}
            tier = "both" if any(r["tier"] == "both" for r in rs) else rs[0]["tier"]
            obs = outcome_class(record["outcomes"].get(et, []))
            flags = _flags(tier, present, regions, rec_region, obs)
            entity_rows.append({"entity_type": et, "types": sorted(r["type_name"] for r in rs), "tier": tier, "present": present, "observed": obs, "flags": flags})
            contradictions += [{"entity_type": et, "type": rs[0]["type_name"], "flag": f} for f in flags]
        for tr in type_rows:
            tr["observed"] = next((e["observed"] for e in entity_rows if tr["type"] in e["types"] and e["observed"]), None)
    else:
        for tr in type_rows:
            for f in _flags(tr["tier"], tr["present"], regions, None, None):
                contradictions.append({"entity_type": None, "type": tr["type"], "flag": f})
    summary = {
        g: {"collected_types": len(type_rows), "present": sum(1 for x in type_rows if x["present"][g]), "absent": sum(1 for x in type_rows if not x["present"][g])}
        for g in regions
    }
    return {
        "note": "Absence from a regional specification is a LEAD, never a verdict: see the backtest for how often it was wrong.",
        "regions": regions,
        "per_region": summary,
        "contradiction_counts": dict(sorted(collections.Counter(c["flag"] for c in contradictions).items())),
        "contradictions": sorted(contradictions, key=lambda c: (c["flag"], c["type"], c["entity_type"] or "")),
        "rows": sorted(type_rows, key=lambda x: x["type"]),
        "backtest": backtest(entity_rows, rec_region, record),
    }


def backtest(rows: list[dict], region: str | None, record: dict | None) -> dict:
    if not record or not region:
        return {"applicable": False, "note": "needs a run record whose region has a loaded specification"}
    classifiable = [r for r in rows if r["observed"] in ("works", "not-available")]
    present = [r for r in classifiable if r["present"][region]]
    absent = [r for r in classifiable if not r["present"][region]]
    unsupported = [r for r in classifiable if r["observed"] == "not-available"]
    return {
        "applicable": True,
        "region": region,
        "unit": "entity type (the unit the run record reports)",
        "with_a_classifiable_outcome": len(classifiable),
        "present_in_specification": len(present),
        "present_and_worked": sum(1 for r in present if r["observed"] == "works"),
        "present_but_unsupported": sorted(t for r in present if r["observed"] == "not-available" for t in r["types"]),
        "absent_from_specification": len(absent),
        "absent_but_worked": sum(1 for r in absent if r["observed"] == "works"),
        "unsupported": len(unsupported),
        "unsupported_and_absent": sum(1 for r in unsupported if not r["present"][region]),
        "unsupported_with_tier_both": sum(1 for r in unsupported if r["tier"] == "both"),
        "note": "ok and empty count as a working call path; unsupported and unsupported-in-partition as not available. Other outcomes (access denied, throttled, validation, error) are not classifiable and are left out.",
    }


# ---------------------------------------------------------------- (b) property conformance

def _security_score(prop: str, read_only: bool, identity: set[str]) -> int:
    s = 0
    if norm(prop) in identity or (read_only and IDENTITY_NAME.search(prop)):
        s += 3
    if SECURITY_NAME.search(prop):
        s += 2
    return s


def conformance(rows: list[dict], tap: dict, specs: dict[str, dict], bundle: dict | None, w: weighting.Weighting, primary: str) -> dict:
    order = [primary] + [g for g in sorted(specs) if g != primary]
    scored, no_manifest = [], []
    for r in rows:
        for et in r["entity_types"]:
            t = tap["types"].get(et)
            m = t["manifest"] if t else None
            if not m:
                no_manifest.append({"type": r["type_name"], "entity_type": et})
                continue
            region = next((g for g in order if r["type_name"] in specs[g]["types"]), None)
            if region is None:
                continue
            spec = specs[region]["types"][r["type_name"]]
            sch = (bundle or {}).get("types", {}).get(r["type_name"], {})
            read_only = {norm(_head(a)): _head(a) for a in spec["attributes"]}
            read_only.update({norm(a): a for a in sch.get("read_only", [])})
            write_only = {norm(a) for a in sch.get("write_only", [])}
            writable = {norm(p): p for p in spec["properties"] if norm(p) not in read_only}
            held_raw = {norm(_head(str(v))): _head(str(v)) for v in m["field_sources"].values()}
            nk = m.get("natural_key")
            if isinstance(nk, str) and not nk.startswith("_"):
                held_raw[norm(_head(nk))] = _head(nk)
            if m.get("tags") not in (None, "none"):
                held_raw["tags"] = "Tags"
            held = set(held_raw)
            identity = {norm(_head(x)) for x in sch.get("primary_identifier", [])}
            unreadable = sorted(writable[k] for k in writable if k in write_only)
            w_missing = sorted(writable[k] for k in writable if k not in held and k not in write_only)
            r_missing = sorted(read_only[k] for k in read_only if k not in held)
            w_held = sorted(writable[k] for k in writable if k in held)
            r_held = sorted(read_only[k] for k in read_only if k in held)
            denom = len(w_held) + len(w_missing) + len(r_held) + len(r_missing)
            names_lacking = sorted(v for k, v in held_raw.items() if k not in writable and k not in read_only and not v.startswith("_"))
            scored.append({
                "type": r["type_name"], "entity_type": et, "spec_region": region, "weight": w.cfn(r["type_name"]),
                "stores_whole_configuration": bool(m.get("persist_configuration", True)),
                "held_writable": w_held, "held_read_only": r_held,
                "missing_writable": w_missing, "missing_read_only": r_missing,
                "write_only_unreadable": unreadable, "named_but_not_in_specification": names_lacking,
                "denominator": denom, "held_pct": _pct(len(w_held) + len(r_held), denom),
                "priority": sum(_security_score(p, False, identity) for p in w_missing) + sum(_security_score(p, True, identity) for p in r_missing),
            })
    scored.sort(key=lambda x: (x["type"], x["entity_type"]))
    tot_held = sum(len(x["held_writable"]) + len(x["held_read_only"]) for x in scored)
    tot = sum(x["denominator"] for x in scored)
    ro_held, ro_tot = sum(len(x["held_read_only"]) for x in scored), sum(len(x["held_read_only"]) + len(x["missing_read_only"]) for x in scored)
    wt = [(x["weight"], x["held_pct"]) for x in scored if x["weight"] > 0 and x["held_pct"] is not None]
    wsum = sum(a for a, _ in wt)
    ranked = sorted(
        (x for x in scored if x["priority"] > 0 and x["weight"] > 0),
        key=lambda x: (-x["weight"] * x["priority"], x["type"]),
    )
    return {
        "scope": "Top-level properties only; a nested property counts toward its top-level parent. Names are compared after normalisation (case and punctuation folded).",
        "reference": "The CloudFormation specification is a reference, not ground truth: API and CloudFormation names for one thing can differ, so a 'missing' property is a lead.",
        "types_scored": len(scored),
        "pooled_held_pct": _pct(tot_held, tot),
        "mean_held_pct": round(sum(x["held_pct"] for x in scored if x["held_pct"] is not None) / max(1, sum(1 for x in scored if x["held_pct"] is not None)), 1),
        "weighted_held_pct": round(sum(a * b for a, b in wt) / wsum, 1) if wsum else None,
        "weighted_types": len(wt),
        "read_only_held_pct": _pct(ro_held, ro_tot),
        "types_storing_whole_configuration": sum(1 for x in scored if x["stores_whole_configuration"]),
        "top_disagreements": [
            {k: x[k] for k in ("type", "entity_type", "weight", "priority", "held_pct")}
            | {"missing_read_only": x["missing_read_only"][:8], "missing_writable_security": [p for p in x["missing_writable"] if SECURITY_NAME.search(p)][:8]}
            for x in ranked[:10]
        ],
        "types": scored,
        "types_without_manifest_entry": sorted(no_manifest, key=lambda x: (x["type"], x["entity_type"])),
    }


# ---------------------------------------------------------------- (c) identity and tags

def _is_arn_key(k: str) -> bool:
    return norm(k).endswith("arn")


def identity_tags(rows: list[dict], tap: dict, bundle: dict | None, tag_findings: dict) -> dict:
    if not bundle:
        return {"applicable": False, "note": "needs the schema bundle (--bundle)"}
    ident, tagd = [], []
    for r in rows:
        sch = bundle["types"].get(r["type_name"])
        if not sch:
            continue
        for et in r["entity_types"]:
            m = (tap["types"].get(et) or {}).get("manifest")
            if not m:
                continue
            pid = sch["primary_identifier"]
            nk = m.get("natural_key")
            nk_s = nk if isinstance(nk, str) else json.dumps(nk, sort_keys=True)
            pid_heads = {norm(_head(x)) for x in pid}
            ours_arn = _is_arn_key(nk_s)  # norm drops a leading underscore, so a derived `_arn` counts
            schema_arn = any(_is_arn_key(_head(x)) for x in pid)
            if norm(_head(nk_s)) in pid_heads or (ours_arn and schema_arn):
                verdict = "agrees"
            elif ours_arn:
                verdict = "ours-arn-schema-identifier-is-not"
            elif schema_arn:
                verdict = "schema-identifier-is-arn-ours-is-not"
            else:
                verdict = "differs"
            if verdict != "agrees":
                ident.append({"type": r["type_name"], "entity_type": et, "ours": clean(nk_s), "schema": pid, "verdict": verdict})
            finding = tag_findings.get(r["type_name"])
            taggable = finding["taggable"] if isinstance(finding, dict) and isinstance(finding.get("taggable"), bool) else sch["taggable"]
            ours = m.get("tags") not in (None, "none")
            if taggable is None:
                continue
            if ours != taggable:
                tagd.append({
                    "type": r["type_name"], "entity_type": et, "ours_source": clean(m.get("tags")), "schema_taggable": sch["taggable"],
                    "after_decision": taggable, "decision_recorded": finding is not None,
                    "verdict": "we-skip-tags-schema-says-taggable" if taggable else "we-collect-tags-schema-says-not-taggable",
                })
    return {
        "applicable": True,
        "identity_disagreements": sorted(ident, key=lambda x: (x["type"], x["entity_type"])),
        "tag_disagreements": sorted(tagd, key=lambda x: (x["type"], x["entity_type"])),
        "note": "Identity: ours is the manifest natural_key, theirs is the schema primaryIdentifier; two ARN-shaped keys agree. Tags: the schema's tagging.taggable, overridden by the ledger's recorded tag_findings decision where one exists.",
    }


# ---------------------------------------------------------------- run, drift, output

def run(plugin: Path, spec_paths: list[Path], weights_path: Path, bundle_path: Path | None, record_path: Path | None,
        manifest_path: Path | None, primary: str | None) -> dict:
    plugin = Path(plugin)
    specs = {}
    for p in spec_paths:
        g = region_of(Path(p))
        if g in specs:
            raise cfn_reader.CfnReadError(f"two specification files for region {g}")
        specs[g] = cfn_reader.read_spec(Path(p))
        specs[g]["file"] = clean(Path(p).name)
    if not specs:
        raise cfn_reader.CfnReadError("at least one --spec is needed")
    primary = primary or ("us-gov-west-1" if "us-gov-west-1" in specs else sorted(specs)[0])
    if primary not in specs:
        raise cfn_reader.CfnReadError(f"primary region {clean(primary)} has no specification loaded")
    bundle = cfn_reader.read_bundle(plugin, bundle_path) if bundle_path else None
    record = read_record(record_path, plugin) if record_path else None
    manifest = cfn_reader.read_manifest(manifest_path) if manifest_path else None
    tap = tap_reader.read(plugin)
    w = weighting.load(weights_path)
    ledger_path = plugin / "tap_plugin" / "aws_core" / "ledger" / "aws_coverage_ledger.json"
    ledger = json.loads(ledger_path.read_text())
    decisions = json.loads((ledger_path.parent / "decisions.json").read_text())
    rows = sorted((r for r in ledger["rows"] if r["state"] in COLLECTED), key=lambda r: r["type_name"])
    rep = {
        "schema_version": SCHEMA_VERSION,
        "inputs": {
            "specifications": {g: {k: s[k] for k in ("file", "version", "sha256", "bytes")} | {"resource_types": len(s["types"])} for g, s in sorted(specs.items())},
            "fetch_manifest": manifest,
            "schema_bundle": {"sha256": bundle["sha256"], "types": len(bundle["types"])} if bundle else None,
            "run_record": {k: record[k] for k in ("sha256", "partition", "regions", "entries")} if record else None,
            "aws_core": {"types": len(tap["types"]), "source_sha256": tap["digest"]},
            "ledger": {"sha256": _sha(ledger_path), "cfn_bundle_sha256": ledger.get("cfn_bundle_sha256")},
            "weighting": {"name": w.name, "version": w.version, "status": w.status, "chain": list(w.chain), "sha256": w.sha256},
            "primary_region": primary,
        },
        "availability": availability(rows, specs, record),
        "properties": conformance(rows, tap, specs, bundle, w, primary),
        "identity_tags": identity_tags(rows, tap, bundle, decisions.get("tag_findings", {})),
    }
    rep["headline"] = headline(rep)
    rep["gap_ids"] = gap_ids(rep)
    return rep


def headline(r: dict) -> dict:
    a, p, it = r["availability"], r["properties"], r["identity_tags"]
    h = {f"absent_in_{g}": v["absent"] for g, v in a["per_region"].items()}
    h.update({
        "contradictions": sum(a["contradiction_counts"].values()),
        "property_pooled_held_pct": p["pooled_held_pct"],
        "property_weighted_held_pct": p["weighted_held_pct"],
        "property_read_only_held_pct": p["read_only_held_pct"],
        "identity_not_arn_on_one_side_or_differs": len([x for x in it.get("identity_disagreements", []) if x["verdict"] != "ours-arn-schema-identifier-is-not"]),
        "identity_ours_arn_schema_not": len([x for x in it.get("identity_disagreements", []) if x["verdict"] == "ours-arn-schema-identifier-is-not"]),
        "tag_disagreements": len(it.get("tag_disagreements", [])),
    })
    return h


def gap_ids(r: dict) -> list[str]:
    ids = [f"absent:{g}:{x['type']}" for x in r["availability"]["rows"] for g in x["lead_absent_in"]]
    ids += [f"contradiction:{c['flag']}:{c['type']}" for c in r["availability"]["contradictions"]]
    for x in r["properties"]["types"]:
        ids += [f"property:{x['type']}:{p}" for p in x["missing_read_only"] + x["missing_writable"]]
    ids += [f"identity:{x['verdict']}:{x['type']}" for x in r["identity_tags"].get("identity_disagreements", [])]
    ids += [f"tags:{x['type']}:{x['verdict']}" for x in r["identity_tags"].get("tag_disagreements", [])]
    return sorted(set(ids))


def drift(now: dict, before: dict) -> dict:
    a, b = set(now["gap_ids"]), set(before["gap_ids"])
    ref_keys = ("specifications", "schema_bundle", "run_record", "fetch_manifest")
    ours_keys = ("aws_core", "ledger", "weighting", "primary_region")
    changed = {k: [before["inputs"].get(k), now["inputs"][k]] for k in now["inputs"] if before["inputs"].get(k) != now["inputs"][k]}
    ref, ours = sorted(k for k in changed if k in ref_keys), sorted(k for k in changed if k in ours_keys)
    return {
        "comparable": before.get("schema_version") == now["schema_version"],
        "headline_changes": {k: [before["headline"].get(k), v] for k, v in now["headline"].items() if before["headline"].get(k) != v},
        "new_gaps": sorted(a - b),
        "closed_gaps": sorted(b - a),
        "reference_inputs_changed": ref,
        "our_inputs_changed": ours,
        "cause": "both" if ref and ours else "reference" if ref else "ours" if ours else "none",
        "inputs_changed": changed,
    }


def markdown(r: dict, d: dict | None) -> str:
    a, p, it, i, h = r["availability"], r["properties"], r["identity_tags"], r["inputs"], r["headline"]
    out = ["# aws_core against the CloudFormation specification", "",
           "The specification is a reference, not ground truth. Absence is a lead; a missing property may be a naming difference.", "",
           "## Inputs", ""]
    out += [f"- `{g}`: specification {s['version']}, {s['resource_types']} types, sha256 `{s['sha256'][:16]}`" for g, s in i["specifications"].items()]
    out += [f"- schema bundle sha256 `{i['schema_bundle']['sha256'][:16]}`" if i["schema_bundle"] else "- no schema bundle given",
            f"- aws_core source sha256 `{i['aws_core']['source_sha256'][:16]}`; weighting `{i['weighting']['name']}` v{i['weighting']['version']}", "",
            "## Availability leads", ""]
    out += [f"- `{g}`: {v['absent']} of {v['collected_types']} collected types absent from the specification (leads)" for g, v in a["per_region"].items()]
    bt = a["backtest"]
    if bt["applicable"]:
        out += ["", f"### Backtest against the run record (`{bt['region']}`)", "",
                f"- entity types with a classifiable outcome: {bt['with_a_classifiable_outcome']}",
                f"- present in the specification: {bt['present_in_specification']}, of which the call path worked: {bt['present_and_worked']}",
                f"- present but unsupported: {', '.join(bt['present_but_unsupported']) or 'none'}",
                f"- absent from the specification: {bt['absent_from_specification']}, of which the call path worked: {bt['absent_but_worked']}",
                f"- unsupported types: {bt['unsupported']}, of which absent from the specification: {bt['unsupported_and_absent']}, of which the ledger tier called available in both: {bt['unsupported_with_tier_both']}"]
    out += ["", "### Contradictions", ""]
    out += [f"- {k}: {v}" for k, v in a["contradiction_counts"].items()] or ["- none"]
    out += ["", "## Property conformance (top-level properties only)", "",
            f"- types scored: {p['types_scored']}; held {p['pooled_held_pct']}% pooled, {p['mean_held_pct']}% mean per type, {p['weighted_held_pct']}% weighted ({p['weighted_types']} weighted types)",
            f"- read-only attributes held: {p['read_only_held_pct']}%; types storing their whole configuration: {p['types_storing_whole_configuration']}",
            f"- types with no manifest entry (hand-written readers, not scored): {len(p['types_without_manifest_entry'])}", "",
            "### Heaviest disagreements (security and identity names, a heuristic)", ""]
    out += [f"- `{x['type']}` (weight {x['weight']:g}, holds {x['held_pct']}%): read-only missing {', '.join(x['missing_read_only']) or 'none'}; writable security missing {', '.join(x['missing_writable_security']) or 'none'}" for x in p["top_disagreements"]]
    out += ["", "## Identity and tags", ""]
    if it["applicable"]:
        out += [f"- identity disagreements: {len(it['identity_disagreements'])}; tag disagreements: {len(it['tag_disagreements'])}"]
        out += [f"- identity `{x['type']}`: ours `{x['ours']}`, schema {', '.join(x['schema'])} ({x['verdict']})" for x in it["identity_disagreements"][:20]]
        out += [f"- tags `{x['type']}`: {x['verdict']}" for x in it["tag_disagreements"][:20]]
    else:
        out += [f"- {it['note']}"]
    if d:
        out += ["", "## Drift since the baseline", "",
                f"Cause: {d['cause']} (reference inputs changed: {', '.join(d['reference_inputs_changed']) or 'none'}; ours: {', '.join(d['our_inputs_changed']) or 'none'}).",
                f"New gaps: {len(d['new_gaps'])}; closed: {len(d['closed_gaps'])}."]
        out += [f"- new: `{g}`" for g in d["new_gaps"][:30]] + [f"- closed: `{g}`" for g in d["closed_gaps"][:30]]
        out += [f"- {k}: {v[0]} -> {v[1]}" for k, v in d["headline_changes"].items()]
    out += ["", f"Headline: {json.dumps(h, sort_keys=True)}"]
    return clean_md("\n".join(out)) + "\n"


def clean_md(text: str) -> str:
    return re.sub(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]", " ", text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True, action="append", type=Path, help="a regional specification file (spec-<region>.json); repeatable")
    ap.add_argument("--bundle", type=Path, default=None, help="the CloudFormation schema bundle (zip or extracted directory)")
    ap.add_argument("--plugin", type=Path, default=HERE.parents[1], help="aws-core-tap checkout (default: this one)")
    ap.add_argument("--weights", type=Path, default=HERE / "weights" / "cartography-set-v1.json")
    ap.add_argument("--manifest", type=Path, default=None, help="manifest.tsv written by cfn_fetch.sh")
    ap.add_argument("--run-record", type=Path, default=None, help="a wave-0 run record (tools/validate/runs/*.json); must lie inside the plugin checkout or the working directory")
    ap.add_argument("--primary-region", default=None, help="region whose specification the property comparison prefers")
    ap.add_argument("--out", type=Path, default=None, help="directory for report.json and report.md")
    ap.add_argument("--baseline", type=Path, default=None, help="an earlier report.json to diff against")
    ap.add_argument("--fail-on-regression", action="store_true", help="exit 1 when a gap appears that the baseline did not have")
    a = ap.parse_args(argv)
    if a.fail_on_regression and not a.baseline:
        ap.error("--fail-on-regression needs --baseline: without one there is nothing to compare, and the gate would pass vacuously")
    try:
        rep = run(a.plugin, a.spec, a.weights, a.bundle, a.run_record, a.manifest, a.primary_region)
        d = drift(rep, json.loads(a.baseline.read_text())) if a.baseline else None
    except (ValueError, OSError, KeyError) as e:
        ap.error(clean(e))
    if d:
        rep["drift"] = d
    text = json.dumps(rep, indent=1, sort_keys=True) + "\n"
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "report.json").write_text(text)
        (a.out / "report.md").write_text(markdown(rep, d))
    sys.stdout.write(markdown(rep, d))
    if a.fail_on_regression and d and not d["comparable"]:
        sys.stderr.write("cfn_verifier: the baseline has a different schema_version, so no regression check was possible; failing closed\n")
        return 1
    return 1 if (a.fail_on_regression and d and d["new_gaps"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
