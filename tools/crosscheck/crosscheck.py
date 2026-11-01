#!/usr/bin/env python3
"""Compare aws_core with Cartography's AWS model, statically and deterministically.

A test instrument, not a product feature: it reads two source trees (and a weighting file) and writes a
report. It imports neither project, calls no AWS API and writes nothing but its report. The same inputs
give the same report, so two runs can be diffed and the diff is the drift.

    crosscheck.py --cartography ~/src/cartography [--plugin <aws-core-tap root>]
                  [--weights weights/cartography-set-v1.json] [--out DIR] [--baseline report.json]
                  [--fail-on-regression]

Metrics: coverage, accuracy, linkage, operations, security attributes, tags, identity, containment, and
candidate defects in Cartography itself. Each is also scored under the weighting. Static comparison is the
cheap, always-available layer; a live account decides every disagreement it raises (see
specs/spec-aws-core-collection-oracle.md).
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # sibling modules; the script is run isolated (-I), which drops its own directory

import carto_reader  # noqa: E402
import tap_reader  # noqa: E402
import weighting  # noqa: E402
from carto_reader import norm  # noqa: E402
SCHEMA_VERSION = 1


# ---------------------------------------------------------------- mapping

def resolve_labels(nodes: dict[str, dict], tap_types: set[str], lmap: dict) -> dict[str, tuple[str, list[str]]]:
    by_name = {norm(t.replace("aws_core__aws_", "").replace("aws_core__", "")): t for t in tap_types}
    res: dict[str, tuple[str, list[str]]] = {}
    for label in sorted(nodes):
        if label == "AWSAccount" or label in lmap["artifacts"]:
            res[label] = ("artifact", [])
        elif label in lmap["aliases"]:
            tgt = [t for t in lmap["aliases"][label] if t in tap_types]
            res[label] = ("mapped", tgt) if tgt else ("known-gap", [])
        elif norm(re.sub(r"^AWS", "", label)) in by_name:
            res[label] = ("mapped", [by_name[norm(re.sub(r"^AWS", "", label))]])
        else:
            res[label] = ("unmapped", [])
    return res


def _pct(a: float, b: float) -> float | None:
    return None if not b else round(100.0 * a / b, 1)


# ---------------------------------------------------------------- metrics

def coverage(nodes, res, tap, w) -> dict:
    scored = {l: v for l, v in res.items() if v[0] != "artifact"}
    wt = {l: w.concept(l, tuple(v[1])) for l, v in scored.items()}
    mapped = {l for l, v in scored.items() if v[0] == "mapped"}
    mapped_types = {t for l in mapped for t in res[l][1]}
    ours_only = sorted(set(tap["types"]) - mapped_types)
    gaps = sorted(
        ({"label": l, "status": scored[l][0], "weight": wt[l]} for l in scored if l not in mapped),
        key=lambda r: (-r["weight"], r["label"]),
    )
    only_w = {t: w.concept(None, (t,)) for t in ours_only}
    return {
        "reference_labels": len(scored),
        "mapped": len(mapped),
        "known_gap": sum(1 for v in scored.values() if v[0] == "known-gap"),
        "unmapped_needs_review": sum(1 for v in scored.values() if v[0] == "unmapped"),
        "artifact_labels_excluded": len(res) - len(scored),
        "coverage_pct": _pct(len(mapped), len(scored)),
        "weighted_coverage_pct": _pct(sum(wt[l] for l in mapped), sum(wt.values())),
        "our_types": len(tap["types"]),
        "our_types_not_in_reference": len(ours_only),
        "our_only_weighted": round(sum(only_w.values()), 1),
        "our_only_with_weight": sorted(t for t, x in only_w.items() if x > 0),
        "gaps": gaps,
    }


def _tap_keys(t: dict) -> tuple[set[str], bool]:
    m = t["manifest"]
    if m:  # a model column the manifest never fills holds nothing, so only mapped fields count
        return {norm(re.sub(r"\[\]", "", v)) for v in m["field_sources"].values()}, bool(m["persist_configuration"])
    # Hand-written types carry no manifest; their columns are the model's own business.
    return {norm(f) for f in t["fields"]}, False


def accuracy(nodes, res, tap, w) -> dict:
    rows = []
    for label, (st, tgts) in sorted(res.items()):
        if st != "mapped":
            continue
        ck = {norm(p["key"]) for p in nodes[label]["properties"].values() if p["key"] and not p["kwargs"]} - {"id", "lastupdated"}
        for t in tgts:
            typed, cfg = _tap_keys(tap["types"][t])
            rows.append(
                {
                    "label": label,
                    "type": t,
                    "weight": w.concept(label, (t,)),
                    "reference_properties": len(ck),
                    "typed_overlap": len(ck & typed),
                    "configuration_stored": cfg,
                    "not_typed": sorted(ck - typed),
                }
            )
    tot = sum(r["reference_properties"] for r in rows)
    ov = sum(r["typed_overlap"] for r in rows)
    wtot = sum(r["weight"] * r["reference_properties"] for r in rows)
    wov = sum(r["weight"] * r["typed_overlap"] for r in rows)
    held = sum(r["reference_properties"] for r in rows if r["configuration_stored"])
    return {
        "pairs": len(rows),
        "reference_properties": tot,
        "typed_overlap": ov,
        "typed_overlap_pct": _pct(ov, tot),
        "weighted_typed_overlap_pct": _pct(wov, wtot),
        "pairs_storing_configuration": sum(1 for r in rows if r["configuration_stored"]),
        "properties_on_pairs_storing_configuration_pct": _pct(held, tot),
        "rows": sorted(rows, key=lambda r: (-r["weight"], r["label"], r["type"])),
    }


def _edge_pairs(tap: dict) -> tuple[set[frozenset], set[frozenset]]:
    emitted: set[frozenset] = set()
    for t, v in tap["types"].items():
        for e in (v["manifest"] or {}).get("edges", []):
            emitted.add(frozenset((t, e["target"])))
        for e in v["model_edges"]:
            emitted |= {frozenset((t, x)) for x in e["targets"]}
    declared = {frozenset((a, b)) for d in tap["edge_defs"].values() for a in d["sources"] for b in d["targets"]}
    return emitted, declared


def linkage(nodes, res, tap, w) -> dict:
    emitted, declared = _edge_pairs(tap)
    rows = []
    for label, n in sorted(nodes.items()):
        for r in n["rels"]:
            tgt = r.get("target")
            if not tgt or tgt == "AWSAccount" or r.get("rel") == "RESOURCE":
                continue
            if tgt not in res:
                continue
            sa, a = res[label]
            sb, b = res[tgt]
            if sa != "mapped" or sb != "mapped":
                status = "not-comparable:" + (sa if sa != "mapped" else sb)
            else:
                pairs = {frozenset((x, y)) for x in a for y in b}
                status = "matched" if pairs & emitted else "declared-only" if pairs & declared else "missing"
            weight = min(w.concept(label, tuple(a)), w.concept(tgt, tuple(b)))
            rows.append({"from": label, "rel": r.get("rel"), "to": tgt, "status": status, "weight": weight})
    rows.sort(key=lambda r: (-r["weight"], r["from"], r["to"], r["rel"] or ""))
    cmp_rows = [r for r in rows if not r["status"].startswith("not-comparable")]
    ok = [r for r in cmp_rows if r["status"] == "matched"]
    return {
        "reference_edges": len(rows),
        "comparable": len(cmp_rows),
        "matched": len(ok),
        "declared_only": sum(1 for r in rows if r["status"] == "declared-only"),
        "missing": sum(1 for r in rows if r["status"] == "missing"),
        "not_comparable": len(rows) - len(cmp_rows),
        "matched_pct_of_comparable": _pct(len(ok), len(cmp_rows)),
        "weighted_matched_pct_of_comparable": _pct(sum(r["weight"] for r in ok), sum(r["weight"] for r in cmp_rows)),
        "rows": rows,
    }


def ledger_view(tap: dict, w: weighting.Weighting) -> dict:
    """How the weighted part of the coverage ledger stands: collected, decided against, or still open."""
    if not w.has_cfn_rules():
        return {"applicable": False, "note": "This weighting names no CloudFormation types, so there is nothing to weigh in the ledger."}
    # In scope means available in both commercial and GovCloud, the project's standing scope ruling (aws-core-tap#107).
    rows = [(r, w.cfn(r["type_name"])) for r in tap["ledger_rows"] if r["tier"] == "both"]
    rows = [(r, x) for r, x in rows if x > 0]
    by_state: dict[str, float] = collections.defaultdict(float)
    for r, x in rows:
        by_state[r["state"]] += x
    total = sum(by_state.values())
    collected = by_state.get("collected-unverified", 0.0) + by_state.get("collected-verified", 0.0)
    decided = collected + by_state.get("excluded", 0.0) + by_state.get("not-enumerable", 0.0)  # modeled has no collector yet
    open_rows = sorted(
        ({"type": r["type_name"], "state": r["state"], "weight": x} for r, x in rows if r["state"] == "unclassified"),
        key=lambda r: (-r["weight"], r["type"]),
    )
    out_of_scope = sorted(
        (
            {"type": r["type_name"], "tier": r["tier"], "weight": x}
            for r in tap["ledger_rows"]
            if r["tier"] != "both" and r["state"] == "unclassified" and (x := w.cfn(r["type_name"])) > 0
        ),
        key=lambda r: (-r["weight"], r["type"]),
    )
    return {
        "applicable": True,
        "weighted_out_of_scope_unclassified": out_of_scope,
        "weighted_types": len(rows),
        "weighted_total": total,
        "weighted_by_state": dict(sorted(by_state.items())),
        "collected_pct": _pct(collected, total),
        "decided_pct": _pct(decided, total),
        "open_unclassified": open_rows,
        "note": "Counts rows in both commercial and GovCloud only; weighted_out_of_scope_unclassified lists weighted rows the ledger puts outside that scope on botocore's partition data, which is worth checking against AWS's own GovCloud service lists. decided = collected, excluded or not enumerable, each with a written reason in the ledger; unclassified is the open work.",
    }


def operations(carto_ops: set[tuple[str, str]], tap_ops: list[list[str]]) -> dict:
    ours = {o for _, o in tap_ops}
    matched = sorted(c for c in carto_ops if c[1] in ours)
    only = sorted(c for c in carto_ops if c[1] not in ours)
    by_service = collections.Counter(s or "unknown" for s, _ in only)
    return {
        "reference_operations": len(carto_ops),
        "matched": len(matched),
        "reference_only": len(only),
        "matched_pct": _pct(len(matched), len(carto_ops)),
        "our_operations": len(ours),
        "reference_only_by_service": dict(sorted(by_service.items(), key=lambda kv: (-kv[1], kv[0]))),
        "reference_only_operations": [{"service": s or "unknown", "operation": o} for s, o in only],
        "note": "Matched on the normalised operation name alone; a service is only known to Cartography where a file uses one client, and hand-written readers carry none.",
    }


def security(attrs: dict, nodes, tap, w, res) -> dict:
    """Verdicts, best to worst: typed (a column the collector fills), configuration-only (no column, but the
    read is one we make and the type keeps its whole configuration), column-unfilled (a model column the manifest
    never maps), not-evidenced (nothing shows we read it), type-not-collected, and the two stale kinds."""
    custom_ops = set(tap["custom_ops"])
    rows = []
    for a in attrs["attributes"]:
        label, prop = a["carto"]["label"], a["carto"]["property"]
        ty, fld, read_op = a["tap"]["type"], a["tap"]["field"], a["tap"].get("read_op")
        carto_ok = label in nodes and prop in nodes[label]["properties"]
        t = tap["types"].get(ty)
        if t is None:
            verdict = "type-not-collected"
        elif fld and fld not in t["fields"]:
            verdict = "stale-tap-field"
        elif fld:
            m = t["manifest"]
            verdict = "typed" if (m is None or fld in m["field_sources"]) else "column-unfilled"
        else:
            m = t["manifest"]
            keeps = bool(m and m["persist_configuration"])
            # The read must belong to this type: named in its own manifest entry, or made by the hand-written reader
            # that serves it. A same-named call made for another service or type does not count.
            made = bool(m and read_op and (norm(read_op) in m["ops"] or (m["custom_fn"] and norm(read_op) in custom_ops)))
            verdict = "configuration-only" if keeps and made else "not-evidenced"
        if not carto_ok:
            verdict = "stale-reference-property"
        base = w.concept(label, (ty,))
        rows.append({"id": a["id"], "concept": a["concept"], "weight": w.attribute(a["id"], base), "verdict": verdict})
    rows.sort(key=lambda r: (-r["weight"], r["id"]))
    live = [r for r in rows if not r["verdict"].startswith("stale")]
    typed = [r for r in live if r["verdict"] == "typed"]
    held = [r for r in live if r["verdict"] in ("typed", "configuration-only")]
    return {
        "attributes": len(rows),
        "stale": len(rows) - len(live),
        "typed": len(typed),
        "typed_pct": _pct(len(typed), len(live)),
        "weighted_typed_pct": _pct(sum(r["weight"] for r in typed), sum(r["weight"] for r in live)),
        "held_in_any_form_pct": _pct(len(held), len(live)),
        "rows": rows,
    }


def tags(nodes, res, tap, w) -> dict:
    rows = []
    for label, (st, tgts) in sorted(res.items()):
        if st != "mapped":
            continue
        carto = any(r.get("target") == "AWSTag" for r in nodes[label]["rels"])
        for t in tgts:
            T = tap["types"][t]
            ours = (T["manifest"] or {}).get("tags") not in (None, "none") if T["manifest"] else "tags" in T["fields"]
            rows.append(
                {
                    "label": label,
                    "type": t,
                    "weight": w.concept(label, (t,)),
                    "reference_reads_tags": carto,
                    "we_read_tags": bool(ours),
                    "verdict": "both" if carto and ours else "reference-only" if carto else "ours-only" if ours else "neither",
                }
            )
    c = collections.Counter(r["verdict"] for r in rows)
    return {
        "pairs": len(rows),
        "verdicts": dict(sorted(c.items())),
        "reference_only": [f"{r['label']} -> {r['type']}" for r in sorted(rows, key=lambda r: (-r["weight"], r["label"])) if r["verdict"] == "reference-only"],
        "note": "Cartography models a tag as a node linked to the tagged resource; aws_core keeps tags as a field of the row. The comparison is whether tags are read at all, not how they are shaped.",
    }


def _key_class(key: str | None) -> str:
    """An ARN key names the resource across accounts and regions; a bare id or name does not."""
    return "unknown" if not key else "arn" if "arn" in norm(key) else "id-or-name"


def identity(nodes, res, tap) -> dict:
    rows = []
    for label, (st, tgts) in sorted(res.items()):
        if st != "mapped":
            continue
        rid = nodes[label]["properties"].get("id", {}).get("key")
        for t in tgts:
            m = tap["types"][t]["manifest"]
            ours = m["natural_key"] if m else None
            kr, ko = _key_class(rid), _key_class(ours)
            verdict = "unknown" if not rid or not ours else "same" if norm(rid) == norm(ours) or kr == ko == "arn" else "differs"
            rows.append({"label": label, "type": t, "reference_id": rid, "our_key": ours, "reference_key_class": kr, "our_key_class": ko, "verdict": verdict})
    c = collections.Counter(r["verdict"] for r in rows)
    return {"pairs": len(rows), "verdicts": dict(sorted(c.items())), "differs": [r for r in rows if r["verdict"] == "differs"]}


def containment(nodes, res, tap) -> dict:
    contained = sum(1 for n in nodes.values() if any(r["kind"] == "sub_resource" for r in n["rels"]))
    mapped_types = {t for _, (st, ts) in res.items() if st == "mapped" for t in ts}
    regional = sorted(t for t in mapped_types if (tap["types"][t]["manifest"] or {}).get("containment"))
    return {
        "reference_labels_owned_by_account": contained,
        "our_types_with_regional_containment_among_mapped": len(regional),
        "note": "Cartography links every resource to its account with a RESOURCE relationship. aws_core records the account as a dimension every node carries, not an edge, so account membership is met by design; only regional containment is an edge.",
    }


# ---------------------------------------------------------------- run

def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(carto_root: Path, plugin_root: Path, weights_path: Path) -> dict:
    models = carto_reader.read_models(carto_root)
    nodes = models["nodes"]
    tap = tap_reader.read(plugin_root)
    lmap_p, attr_p, find_p = HERE / "label_map.json", HERE / "security_attributes.json", HERE / "cartography_findings.json"
    lmap, attrs = json.loads(lmap_p.read_text()), json.loads(attr_p.read_text())
    findings = json.loads(find_p.read_text())["findings"] if find_p.exists() else []
    w = weighting.load(weights_path)
    res = resolve_labels(nodes, set(tap["types"]), lmap)
    rep = {
        "schema_version": SCHEMA_VERSION,
        "inputs": {
            "cartography": {
                "commit": carto_reader.commit_of(carto_root),
                "aws_node_labels": len(nodes),
                "unresolved_relationships": sorted(
                    f"{label}:{r['class']}" for label, n in nodes.items() for r in n["rels"] if r["target"] is None
                ),
            },
            "aws_core": {"commit": tap_reader.commit_of(plugin_root), "types": len(tap["types"])},
            "weighting": {"name": w.name, "version": w.version, "status": w.status, "chain": list(w.chain), "sha256": w.sha256},
            "label_map_sha256": _sha(lmap_p),
            "security_attributes_sha256": _sha(attr_p),
        },
        "coverage": coverage(nodes, res, tap, w),
        "accuracy": accuracy(nodes, res, tap, w),
        "linkage": linkage(nodes, res, tap, w),
        "ledger": ledger_view(tap, w),
        "operations": operations(carto_reader.read_ops(carto_root), tap["ops"]),
        "security_attributes": security(attrs, nodes, tap, w, res),
        "tags": tags(nodes, res, tap, w),
        "identity": identity(nodes, res, tap),
        "containment": containment(nodes, res, tap),
        "cartography_candidate_defects": {
            "from_static_checks": [x for x in carto_reader.self_checks(models) if x["id"] not in {f.get("lead_id") for f in findings}],
            "recorded_findings": findings,
            "note": "Static-check entries are leads, not verdicts: verify each, then record it in cartography_findings.json with its evidence before it goes to the Cartography team.",
        },
    }
    rep["headline"] = headline(rep)
    rep["gap_ids"] = gap_ids(rep)
    return rep


def headline(r: dict) -> dict:
    return {
        "coverage_pct": r["coverage"]["coverage_pct"],
        "weighted_coverage_pct": r["coverage"]["weighted_coverage_pct"],
        "accuracy_typed_overlap_pct": r["accuracy"]["typed_overlap_pct"],
        "accuracy_weighted_pct": r["accuracy"]["weighted_typed_overlap_pct"],
        "linkage_matched_pct": r["linkage"]["matched_pct_of_comparable"],
        "linkage_weighted_pct": r["linkage"]["weighted_matched_pct_of_comparable"],
        "operations_matched_pct": r["operations"]["matched_pct"],
        "security_attributes_typed_pct": r["security_attributes"]["typed_pct"],
        "security_attributes_weighted_pct": r["security_attributes"]["weighted_typed_pct"],
        "unmapped_labels_needing_review": r["coverage"]["unmapped_needs_review"],
        "ledger_weighted_collected_pct": r["ledger"].get("collected_pct"),
        "ledger_weighted_decided_pct": r["ledger"].get("decided_pct"),
    }


def gap_ids(r: dict) -> list[str]:
    """Everything the run counts as a shortfall, with a stable id, so a baseline diff shows what got worse."""
    ids = [f"coverage:{g['label']}" for g in r["coverage"]["gaps"]]
    # declared-only is a gap too: the edge definition survives but nothing emits it
    ids += [f"edge:{e['from']}>{e['rel']}>{e['to']}" for e in r["linkage"]["rows"] if e["status"] in ("missing", "declared-only")]
    ids += [f"op:{o['service']}:{o['operation']}" for o in r["operations"]["reference_only_operations"]]
    ids += [f"ledger-open:{x['type']}" for x in r["ledger"].get("open_unclassified", [])]
    # the verdict is in the id, so a drop from typed to configuration-only (or to stale) is a new gap
    ids += [f"security:{a['id']}:{a['verdict']}" for a in r["security_attributes"]["rows"] if a["verdict"] != "typed"]
    ids += [f"accuracy:{a['label']}>{a['type']}:{p}" for a in r["accuracy"]["rows"] for p in a["not_typed"]]
    ids += [f"tags:{x}" for x in r["tags"]["reference_only"]]
    ids += [f"identity:{x['label']}>{x['type']}" for x in r["identity"]["differs"]]
    return sorted(set(ids))


def drift(now: dict, before: dict) -> dict:
    a, b = set(now["gap_ids"]), set(before["gap_ids"])
    delta = {
        k: [before["headline"].get(k), v]
        for k, v in now["headline"].items()
        if before["headline"].get(k) != v
    }
    return {
        "comparable": before.get("schema_version") == now["schema_version"],
        "headline_changes": delta,
        "new_gaps": sorted(a - b),
        "closed_gaps": sorted(b - a),
        "inputs_changed": {k: [before["inputs"].get(k), now["inputs"][k]] for k in now["inputs"] if before["inputs"].get(k) != now["inputs"][k]},
    }


def markdown(r: dict, d: dict | None) -> str:
    h, i = r["headline"], r["inputs"]
    out = [
        "# aws_core against Cartography — static crosscheck",
        "",
        f"Cartography `{i['cartography']['commit'][:12]}` · aws_core `{i['aws_core']['commit'][:12]}` · weighting `{i['weighting']['name']}` v{i['weighting']['version']} ({i['weighting']['status']})",
        "",
        "| Metric | Plain | Weighted |",
        "| --- | ---: | ---: |",
        f"| Coverage (reference labels we collect) | {h['coverage_pct']}% | {h['weighted_coverage_pct']}% |",
        f"| Accuracy (reference properties held as typed fields, on mapped pairs) | {h['accuracy_typed_overlap_pct']}% | {h['accuracy_weighted_pct']}% |",
        f"| Linkage (comparable reference edges we emit) | {h['linkage_matched_pct']}% | {h['linkage_weighted_pct']}% |",
        f"| Operations (reference API reads we also make) | {h['operations_matched_pct']}% | — |",
        f"| Security attributes held as typed fields | {h['security_attributes_typed_pct']}% | {h['security_attributes_weighted_pct']}% |",
        f"| Weighted ledger types collected / decided | — | {h['ledger_weighted_collected_pct']}% / {h['ledger_weighted_decided_pct']}% |",
        "",
        f"Labels still needing a mapping decision: {h['unmapped_labels_needing_review']}.",
        "",
        "## Heaviest coverage gaps",
        "",
    ]
    out += [f"- `{g['label']}` ({g['status']}, weight {g['weight']:g})" for g in r["coverage"]["gaps"][:15]]
    out += ["", "## Heaviest missing edges", ""]
    out += [f"- `{e['from']}` —{e['rel']}→ `{e['to']}` (weight {e['weight']:g})" for e in [x for x in r["linkage"]["rows"] if x["status"] == "missing"][:15]]
    out += ["", "## Security attributes we do not hold as typed fields", ""]
    out += [f"- `{a['id']}`: {a['verdict']} (weight {a['weight']:g})" for a in r["security_attributes"]["rows"] if a["verdict"] != "typed"][:20]
    out += ["", "## Weighted ledger types still unclassified", ""]
    out += [f"- `{x['type']}` (weight {x['weight']:g})" for x in r["ledger"].get("open_unclassified", [])[:20]] or ["- none"]
    oos = r["ledger"].get("weighted_out_of_scope_unclassified", [])
    if oos:
        out += ["", "## Weighted types the ledger puts outside commercial+GovCloud scope (verify the partition data)", ""]
        out += [f"- `{x['type']}` ({x['tier']}, weight {x['weight']:g})" for x in oos[:20]]
    out += ["", "## Candidate defects in Cartography", ""]
    cd = r["cartography_candidate_defects"]
    out += [f"- lead: {f['kind']} — {f['evidence']}" for f in cd["from_static_checks"][:15]] or ["- none from static checks"]
    out += [f"- recorded: {f['id']} ({f.get('status', 'open')}): {f['summary']}" for f in cd["recorded_findings"]]
    if d:
        out += ["", "## Drift since the baseline", "", f"New gaps: {len(d['new_gaps'])}; closed: {len(d['closed_gaps'])}."]
        out += [f"- new: `{g}`" for g in d["new_gaps"][:30]] + [f"- closed: `{g}`" for g in d["closed_gaps"][:30]]
        out += [f"- {k}: {v[0]} → {v[1]}" for k, v in d["headline_changes"].items()]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cartography", required=True, type=Path, help="a clone of cartography-cncf/cartography")
    ap.add_argument("--plugin", type=Path, default=HERE.parents[1], help="aws-core-tap checkout (default: this one)")
    ap.add_argument("--weights", type=Path, default=HERE / "weights" / "cartography-set-v1.json")
    ap.add_argument("--out", type=Path, default=None, help="directory for report.json and report.md")
    ap.add_argument("--baseline", type=Path, default=None, help="an earlier report.json to diff against")
    ap.add_argument("--fail-on-regression", action="store_true", help="exit 1 when a gap appears that the baseline did not have")
    a = ap.parse_args(argv)
    if a.fail_on_regression and not a.baseline:
        ap.error("--fail-on-regression needs --baseline: without one there is nothing to compare, and the gate would pass vacuously")
    rep = run(a.cartography, a.plugin, a.weights)
    d = drift(rep, json.loads(a.baseline.read_text())) if a.baseline else None
    if d:
        rep["drift"] = d
    text = json.dumps(rep, indent=1, sort_keys=True) + "\n"
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "report.json").write_text(text)
        (a.out / "report.md").write_text(markdown(rep, d))
    sys.stdout.write(markdown(rep, d))
    return 1 if (a.fail_on_regression and d and d["new_gaps"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
