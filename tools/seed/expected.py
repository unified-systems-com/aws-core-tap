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
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
OUT_ROOT = HERE / "out"  # run state, the expected inventory and the verdict live here (git-ignored)
MISSING = object()


class ExpectedError(Exception):
    """The state or the catalog could not be turned into an expected inventory."""


def walk_resources(module: dict[str, Any]) -> list[dict[str, Any]]:
    """Every managed resource of a `terraform show -json` module tree (root and children)."""
    found = [r for r in module.get("resources", []) if r.get("mode") == "managed"]
    for child in module.get("child_modules", []):
        found.extend(walk_resources(child))
    return found


def confine(path: Path, root: Path) -> Path:
    """``path`` made real, if it is not a link and lies under ``root``: an argument cannot point the tool at a file
    outside the tool's own directories."""
    path = Path(path)
    if path.is_symlink():
        raise ExpectedError(f"{path.name}: a symlink")
    real = os.path.realpath(path)
    base = os.path.realpath(root)
    if real != base and not real.startswith(base + os.sep):
        raise ExpectedError(f"{path.name}: not under {root.name}/")
    return Path(real)


def read_json_file(path: Path) -> Any:
    """A JSON document from a regular file the operator named. A link, a directory or a device is refused, so a
    path argument cannot be made to read something it was not pointed at."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ExpectedError(f"{path.name}: not a regular file")
    return json.loads(path.read_text(encoding="utf-8"))  # NOSONAR: the operator names the file; links and paths outside out/ are refused by confine()


def load_state(path: Path) -> list[dict[str, Any]]:
    doc = read_json_file(path)
    values = doc.get("values")
    if not isinstance(values, dict) or "root_module" not in values:
        raise ExpectedError("no `values.root_module` in the input: pass `terraform show -json` of the applied STATE, not a plan")
    return walk_resources(values["root_module"])


def load_context(path: Path) -> dict[str, str]:
    """The partition, account id and region the state was applied in, read from the module's `aws_caller_identity` (its
    `arn` names the partition) and `aws_region` data sources, for keys the collector builds as
    `<partition>:<account>:<region>:<name>` (req-aws-collector-identity-8)."""
    root = (read_json_file(path).get("values") or {}).get("root_module") or {}
    found: dict[str, str] = {}

    def note(key: str, value: str) -> None:
        # Two data sources that disagree (a provider alias, a child module) would build keys from the wrong account or
        # region, so the state is refused rather than one of them picked.
        if found.setdefault(key, value) != value:
            raise ExpectedError(f"the state holds more than one {key}; a key built from account or region would be ambiguous")

    def visit(module: dict[str, Any]) -> None:
        for r in module.get("resources", []):
            vals = r.get("values") or {}
            if r.get("mode") == "data" and r.get("type") == "aws_caller_identity" and isinstance(vals.get("account_id"), str):
                note("account_id", vals["account_id"])
                arn = vals.get("arn")
                if isinstance(arn, str) and arn.startswith("arn:") and arn.count(":") >= 5:
                    note("partition", arn.split(":")[1])
            if r.get("mode") == "data" and r.get("type") == "aws_region":
                region = vals.get("region") or vals.get("name")
                if isinstance(region, str):
                    note("region", region)
        for child in module.get("child_modules", []):
            visit(child)

    visit(root)
    return found


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


def evaluate(spec: Any, resource: dict[str, Any], resources: list[dict[str, Any]], context: dict[str, str] | None = None) -> Any:
    """Evaluate one catalog value spec against a resource (and, for joins, the whole state).

    - a string: a dotted path into the resource's values
    - {"path": p, "strip_suffix": s}: the path, with a trailing suffix removed
    - {"const": v}: v
    - {"context": "partition" | "account_id" | "region"}: the partition, account or region the state was applied in (the `aws_caller_identity` and
      `aws_region` data sources); an error if the state has none
    - {"concat": [spec, ...]}: the parts' values joined into one string (a key the collector builds, `<group>:<name>`);
      None if any part is absent
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
    if "context" in spec:
        got = (context or {}).get(spec["context"])
        if not got:
            raise ExpectedError(f"value spec {spec!r} needs the {spec['context']} data source in the state")
        return got
    if "concat" in spec:
        parts = [evaluate(part, resource, resources, context) for part in spec["concat"]]
        return None if any(not isinstance(part, str) or not part for part in parts) else "".join(parts)
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
                got = evaluate(j["target"], other, resources, context)
                if isinstance(got, (list, tuple, set)):
                    out.extend(got)  # a target that is itself a list (a subnet group's subnets) adds its members
                elif got is not None:
                    out.append(got)
        return sorted(out, key=str)
    raise ExpectedError(f"bad value spec {spec!r}")


def _norm_attr(value: Any) -> Any:
    """An empty string in the state is an absent value in the API (public_ip of a private instance)."""
    return None if value == "" else value


def build_expected(resources: list[dict[str, Any]], catalog: dict[str, Any], context: dict[str, str] | None = None) -> dict[str, Any]:
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
        key = evaluate(entry["natural_key"], res, resources, context)
        if not isinstance(key, str) or not key:
            raise ExpectedError(f"{res['address']}: natural key did not resolve")
        tags: dict[str, str] = {}
        if entry.get("tags") == "tags_all":
            tags = dict(_get(res, "tags_all") or {})
        attrs = {f: _norm_attr(evaluate(spec, res, resources, context)) for f, spec in sorted(entry["tf_attrs"].items())}
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

    # A target is named by the state in whichever form the resource uses (a KMS key by id or by ARN), so it is
    # matched against every identifier the seeded resource has, and an edge whose target is not found is reported
    # in `unresolved_edge_targets`, never dropped without trace.
    aliases_by_type: dict[str, dict[str, str]] = {}
    for s in seeded:
        names = {s["natural_key"], s["arn"], _get(s["_res"], "id"), _get(s["_res"], "key_id"), _get(s["_res"], "arn")}
        for name in names:
            if isinstance(name, str) and name:
                aliases_by_type.setdefault(s["entity_type"], {})[name] = s["natural_key"]
    unresolved = 0
    for s in seeded:
        edges = set()
        for spec in s.pop("_edge_specs"):
            got = evaluate(spec["target"], s["_res"], resources, context)
            for target_key in got if isinstance(got, list) else [got]:
                if not isinstance(target_key, str) or not target_key:  # an empty value means the resource names no target (a topic with no key)
                    continue
                resolved = aliases_by_type.get(spec["target_type"], {}).get(target_key)
                if resolved:
                    edges.add((spec["edge_type"], spec["direction"], spec["target_type"], resolved))
                elif spec["target_type"] in aliases_by_type:
                    unresolved += 1  # the target type was seeded but this value names none of its resources
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
        "unresolved_edge_targets": unresolved,
        "unseeded_resources": sorted(unseeded),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("show_json", type=Path, help="output of `terraform show -json` for the applied state")
    ap.add_argument("--catalog", type=Path, default=HERE / "seeding.json")
    ap.add_argument("--out", type=Path, default=None, help="write here instead of stdout")
    args = ap.parse_args(argv)
    try:
        show_json = confine(args.show_json, OUT_ROOT)
        catalog = read_json_file(confine(args.catalog, HERE))
        out = confine(args.out, OUT_ROOT) if args.out else None
        text = json.dumps(build_expected(load_state(show_json), catalog, load_context(show_json)), indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    except (ExpectedError, OSError, ValueError) as exc:
        print(f"expected.py: {exc}", file=sys.stderr)
        return 2
    if out:
        if out.exists() and not out.is_file():
            print(f"expected.py: {out.name}: not a regular file", file=sys.stderr)
            return 2
        out.write_text(text, encoding="utf-8")  # NOSONAR: confined to out/ and not a link, see confine()
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
