#!/usr/bin/env python3
"""Write the expected inventory of a seed wave from `terraform show -json` output.

Usage:
    python3 -I expected.py SHOW_JSON [--catalog seeding.json] [--out expected.json]

The Terraform state is the known truth (req-aws-core-livevalidation-seed): this reads it, never the
collector. For each managed resource whose Terraform type the seed catalog (seeding.json) names it writes the
entity type, natural key, ARN, tags (`tags_all`, so the `tap-seed*` defaults are included; `{}` for a type that
cannot be tagged), the attribute values the catalog lists in `compares`, and the edges whose target was also
seeded. Standard library only; output is deterministic (sorted keys, sorted resources).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MISSING = object()


class ExpectedError(Exception):
    """The state or the catalog could not be turned into an expected inventory."""


def walk_resources(module: dict[str, Any]) -> list[dict[str, Any]]:
    """Every managed resource of a `terraform show -json` module tree (root and children)."""
    found = [r for r in module.get("resources", []) if r.get("mode") == "managed"]
    for child in module.get("child_modules", []):
        found.extend(walk_resources(child))
    return found


def read_json_file(path: Path) -> Any:
    """A JSON document from a regular file the operator named. A link, a directory or a device is refused, so a
    path argument cannot be made to read something it was not pointed at."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ExpectedError(f"{path.name}: not a regular file")
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(path: Path) -> list[dict[str, Any]]:
    doc = read_json_file(path)
    values = doc.get("values")
    if not isinstance(values, dict) or "root_module" not in values:
        raise ExpectedError("no `values.root_module` in the input: pass `terraform show -json` of the applied STATE, not a plan")
    return walk_resources(values["root_module"])


def dig(values: Any, path: str) -> Any:
    """A dotted path into Terraform resource values; numeric segments index lists. MISSING if absent."""
    cur = values
    for part in path.split("."):
        if isinstance(cur, list):
            if not part.isdigit() or int(part) >= len(cur):
                return MISSING
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            if part not in cur:
                return MISSING
            cur = cur[part]
        else:
            return MISSING
    return cur


def _get(resource: dict[str, Any], path: str) -> Any:
    got = dig(resource.get("values") or {}, path)
    return None if got is MISSING else got


def evaluate(spec: Any, resource: dict[str, Any], resources: list[dict[str, Any]]) -> Any:
    """Evaluate one catalog value spec against a resource (and, for joins, the whole state).

    - a string: a dotted path into the resource's values
    - {"path": p, "strip_suffix": s}: the path, with a trailing suffix removed
    - {"const": v}: v
    - {"all_true": {terraform, own, other, flags}, "absent": v}: True iff a resource of that type whose `other` equals
      this resource's `own` exists and every flag attribute on it is true; `v` (default False) if there is none
    - {"join": {terraform, own, other, target}}: the `target` (a spec) of every resource of that type whose
      `other` equals this resource's `own`; a list, sorted
    """
    if isinstance(spec, str):
        return _get(resource, spec)
    if not isinstance(spec, dict):
        raise ExpectedError(f"bad value spec {spec!r}")
    if "const" in spec:
        return spec["const"]
    if "path" in spec:
        value = _get(resource, spec["path"])
        suffix = spec.get("strip_suffix")
        if isinstance(value, str) and suffix and value.endswith(suffix):
            value = value[: -len(suffix)]
        return value
    if "all_true" in spec:
        j = spec["all_true"]
        own = _get(resource, j["own"])
        for other in resources:
            if other.get("type") == j["terraform"] and own is not None and _get(other, j["other"]) == own:
                return all(_get(other, flag) is True for flag in j["flags"])
        # No such resource: the value is the service default the spec names (S3 blocks public access on a new bucket),
        # False when it names none.
        return spec.get("absent", False)
    if "join" in spec:
        j = spec["join"]
        own = _get(resource, j["own"])
        out = []
        for other in resources:
            if other.get("type") == j["terraform"] and own is not None and _get(other, j["other"]) == own:
                got = evaluate(j["target"], other, resources)
                if got is not None:
                    out.append(got)
        return sorted(out, key=str)
    raise ExpectedError(f"bad value spec {spec!r}")


def _norm_attr(value: Any) -> Any:
    """An empty string in the state is an absent value in the API (public_ip of a private instance)."""
    return None if value == "" else value


def build_expected(resources: list[dict[str, Any]], catalog: dict[str, Any]) -> dict[str, Any]:
    by_tf: dict[str, tuple[str, dict[str, Any]]] = {}
    for cfn, entry in catalog["types"].items():
        by_tf[entry["terraform"]] = (cfn, entry)

    seeded: list[dict[str, Any]] = []
    unseeded: list[str] = []
    for res in resources:
        hit = by_tf.get(res.get("type"))
        if hit is None:
            unseeded.append(res["address"])
            continue
        cfn, entry = hit
        key = evaluate(entry["natural_key"], res, resources)
        if not isinstance(key, str) or not key:
            raise ExpectedError(f"{res['address']}: natural key did not resolve")
        tags: dict[str, str] = {}
        if entry.get("tags") == "tags_all":
            tags = dict(_get(res, "tags_all") or {})
        attrs = {f: _norm_attr(evaluate(spec, res, resources)) for f, spec in sorted(entry["tf_attrs"].items())}
        arn = _get(res, "arn")
        seeded.append(
            {
                "address": res["address"],
                "cfn_type": cfn,
                "entity_type": entry["entity_type"],
                "terraform": entry["terraform"],
                "natural_key": key,
                "arn": arn if isinstance(arn, str) else None,
                "tags": tags,
                "attrs": attrs,
                "edges": [],
                "_edge_specs": entry.get("edges", []),
                "_res": res,
            }
        )

    keys_by_type: dict[str, set[str]] = {}
    for s in seeded:
        keys_by_type.setdefault(s["entity_type"], set()).add(s["natural_key"])
    for s in seeded:
        edges = set()
        for spec in s.pop("_edge_specs"):
            got = evaluate(spec["target"], s["_res"], resources)
            for target_key in got if isinstance(got, list) else [got]:
                if isinstance(target_key, str) and target_key in keys_by_type.get(spec["target_type"], ()):
                    edges.add((spec["edge_type"], spec["direction"], spec["target_type"], target_key))
        s["edges"] = [dict(zip(("edge_type", "direction", "target_type", "target_key"), e, strict=True)) for e in sorted(edges)]
        del s["_res"]
    seeded.sort(key=lambda s: (s["entity_type"], s["natural_key"], s["address"]))

    run_ids = sorted({s["tags"].get("tap-seed-run") for s in seeded if s["tags"].get("tap-seed-run")})
    waves = sorted({s["tags"].get("tap-seed") for s in seeded if s["tags"].get("tap-seed")})
    return {
        "description": "Expected inventory of a seed wave, read from Terraform state. Not a record of what the collector saw. Holds account-bearing ARNs: keep it local, never commit it.",
        "wave": waves,
        "run_id": run_ids,
        "resources": seeded,
        "unseeded_resources": sorted(unseeded),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("show_json", type=Path, help="output of `terraform show -json` for the applied state")
    ap.add_argument("--catalog", type=Path, default=HERE / "seeding.json")
    ap.add_argument("--out", type=Path, default=None, help="write here instead of stdout")
    args = ap.parse_args(argv)
    try:
        catalog = read_json_file(args.catalog)
        text = json.dumps(build_expected(load_state(args.show_json), catalog), indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    except (ExpectedError, OSError, ValueError) as exc:
        print(f"expected.py: {exc}", file=sys.stderr)
        return 2
    if args.out:
        if args.out.is_symlink() or (args.out.exists() and not args.out.is_file()):
            print(f"expected.py: {args.out.name}: not a regular file", file=sys.stderr)
            return 2
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
