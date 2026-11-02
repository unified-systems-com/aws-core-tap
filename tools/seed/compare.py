"""Wave comparison: collect the seeded types through the real engine path and check them against the expected inventory.

Run inside the stack's web container, like tools/validate/wave0_smoke.py (read-only; creates nothing):

    scripts/dc exec -T -e SEED_EXPECTED=/app/_dev-plugins/aws_core/tools/seed/out/expected.json \\
        -e SEED_OUT=/app/_dev-plugins/aws_core/tools/seed/out/verdict.json web \\
        uv run python manage.py shell -c "exec(open('/app/_dev-plugins/aws_core/tools/seed/compare.py').read())"

For each entity type in the expected inventory (written by expected.py from the Terraform state) it drives
iter_source + project_item + resolve_node_tags + emit_edges with the collector identity, twice, and applies the
projection-layer rule of specs/spec-aws-core-live-validation.md (Verdict And Promotion): exactly one row per expected
resource; natural key equal; every `compares` field equal; tags equal (`{}` for untagged, never unread); every edge the
catalog expects (target also seeded) emitted; the second pass the same. The verdict record holds keys, field NAMES and
outcomes only, with any 12-digit run replaced. It builds no batch and writes nothing to AWS.

Environment: SEED_EXPECTED (required to run: path of the expected inventory), SEED_CATALOG (default: seeding.json
beside this file), SEED_OUT (json path for the verdict record).
Importing this module only defines functions; they are unit-tested without Django or AWS (tests/test_compare.py).
"""

import json
import os
import re
import sys

UNREAD_MARK = "<unread>"
LOOSE_NOTE = "scalars compare by their string form (the API returns some integers as strings); lists compare as sets"


MOUNT = "/app/_dev-plugins/aws_core/tools/seed"


def catalog_path(file=None, mount=MOUNT):
    """The seed catalog beside this file, or where the repository is mounted in the container. Under
    `manage.py shell -c "exec(...)"` there is no usable ``__file__`` (it can name manage.py), so the file next to a
    ``__file__`` is used only if it exists."""
    if file:
        beside = os.path.join(os.path.dirname(os.path.abspath(file)), "seeding.json")
        if os.path.isfile(beside):
            return beside
    return os.path.join(mount, "seeding.json")


def scrub(text):
    """Account numbers do not belong in a record: replace any 12-digit run."""
    return re.sub(r"(?<!\d)\d{12}(?!\d)", "<account>", str(text))


def canon(value):
    """A comparable form: bool/number/string scalars by string form, dicts sorted, lists as sorted canon forms."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    if isinstance(value, (int, float, str)):
        return str(value)
    if isinstance(value, dict):
        return {str(k): canon(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple, set)):
        return sorted((canon(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return str(value)


def _row_signature(row):
    return json.dumps(
        {"fields": canon(row["fields"]), "tags": canon(row["tags"]), "edges": sorted(map(list, row["edges"]))},
        sort_keys=True,
        default=str,
    )


def _check_resource(exp, rows, compared):
    """The first mismatch name for one expected resource against the rows of its type, or None."""
    matching = [r for r in rows if r["natural_key"] == exp["natural_key"]]
    if not matching:
        return "missing-row"
    if len(matching) > 1:
        return "duplicate-rows"
    row = matching[0]
    for name in compared:
        if canon(row["fields"].get(name)) != canon(exp["attrs"].get(name)):
            return f"field-differs:{name}"
    if row["tags"] == UNREAD_MARK:
        return "tags-unread"
    if row["tags"] is None:
        return "tags-null"
    if canon(row["tags"]) != canon(exp["tags"]):
        return "tags-differ"
    seen = {tuple(e) for e in row["edges"]}
    for edge in exp["edges"]:
        if (edge["edge_type"], edge["direction"], edge["target_type"], edge["target_key"]) not in seen:
            return f"edge-missing:{edge['edge_type']}"
    return None


def compare_type(entity_type, cfn_type, expected, compared, rows, rows_again, manifest_edges=(), seeded_types=(), read_error=None):
    """The verdict record of one type.

    expected: the expected-inventory resources of this type; rows / rows_again: the first and second collection,
    each a list of {natural_key, fields, tags (dict or UNREAD_MARK), edges [(edge_type, direction, target_type,
    target_key)]}; manifest_edges: the (edge_type, target_type) pairs the manifest declares for the type; seeded_types:
    the entity types in this wave. `uncovered_edges` names the declared edges whose target type was seeded but which
    the catalog gives no expected target for (not checked, said so rather than passed).
    """
    expected = sorted(expected, key=lambda e: e["natural_key"])
    covered = {(e["edge_type"], e["target_type"]) for x in expected for e in x["edges"]}
    uncovered = sorted(f"{et}->{tt}" for et, tt in set(manifest_edges) if tt in set(seeded_types) and (et, tt) not in covered)
    rec = {
        "entity_type": entity_type,
        "cfn_type": cfn_type,
        "expected": len(expected),
        "compared_fields": sorted(compared),
        "edges_expected": sum(len(x["edges"]) for x in expected),
        "uncovered_edges": uncovered,
        "first_mismatch": None,
        "verdict": None,
    }
    if read_error:
        rec["verdict"], rec["first_mismatch"] = "fail", scrub(f"read-error:{read_error}")
        return rec
    if not expected:
        rec["verdict"] = "call-path-only"
        return rec
    by_key_again = {}
    for r in rows_again or []:
        by_key_again.setdefault(r["natural_key"], []).append(r)
    for exp in expected:
        problem = _check_resource(exp, rows, compared)
        where = "first-pass"
        if problem is None:
            again = by_key_again.get(exp["natural_key"], [])
            if len(again) != 1:
                problem, where = ("second-pass-missing" if not again else "second-pass-duplicate"), "second-pass"
            else:
                first = next(r for r in rows if r["natural_key"] == exp["natural_key"])
                if _row_signature(first) != _row_signature(again[0]):
                    problem, where = "second-pass-differs", "second-pass"
        if problem:
            rec["verdict"] = "fail"
            rec["first_mismatch"] = scrub(f"{problem} @ {exp['natural_key']} ({where})")
            return rec
    rec["verdict"] = "pass"
    return rec


def build_report(expected_doc, catalog, collected, collected_again, errors, manifest_edges_by_type):
    """The whole verdict record: one entry per entity type in the catalog that the wave seeded, sorted."""
    by_type = {}
    for res in expected_doc["resources"]:
        by_type.setdefault(res["entity_type"], []).append(res)
    seeded_types = set(by_type)
    waves = set(expected_doc.get("wave") or ())
    records = []
    for cfn, entry in sorted(catalog["types"].items(), key=lambda kv: kv[1]["entity_type"]):
        et = entry["entity_type"]
        if et not in by_type:
            if entry.get("module") in waves:
                # The wave is meant to seed this type and the state has none of it: the type is neither collected
                # nor compared, which must not look like a pass.
                records.append({"entity_type": et, "cfn_type": cfn, "verdict": "fail", "first_mismatch": "seeded-type-absent-from-state"})
            continue
        records.append(
            compare_type(
                et,
                cfn,
                by_type[et],
                entry["compares"],
                collected.get(et),
                collected_again.get(et),
                manifest_edges_by_type.get(et, ()),
                seeded_types,
                errors.get(et),
            )
        )
    unresolved = int(expected_doc.get("unresolved_edge_targets") or 0)
    if unresolved:
        # An expected edge whose target matched no seeded resource was dropped from the inventory, so a collector
        # that fails to emit it would pass; the record fails instead (fail closed).
        records.append({"entity_type": "(expected inventory)", "verdict": "fail", "first_mismatch": f"unresolved-edge-targets:{unresolved}"})
    counts = {}
    for r in records:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {
        "layer": "projection",
        "wave": expected_doc.get("wave"),
        "comparison": LOOSE_NOTE,
        "counts": dict(sorted(counts.items())),
        "types": records,
    }


def _collect(types, entries_by_type, session, partition, region, account, modeled_types, transforms):
    """One collection of the given types: {entity_type: [row]} and {entity_type: error class}."""
    from tap_plugin.aws_core.collectors.boto3_collector.collector import resolve_node_tags
    from tap_plugin.aws_core.collectors.boto3_collector.credentials import client_factory
    from tap_plugin.aws_core.collectors.boto3_collector.customfns import build_custom_fn_registry
    from tap_plugin.aws_core.collectors.boto3_collector.edges import emit_edges
    from tap_plugin.aws_core.collectors.boto3_collector.identity import split_node_ref
    from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
    from tap_plugin.aws_core.collectors.boto3_collector.rgta import rgta_resource_type_filters, sweep_tags
    from tap_plugin.aws_core.collectors.boto3_collector.source import iter_source
    from botocore.config import Config

    custom_fns = build_custom_fn_registry()
    entries = [entries_by_type[t] for t in types]
    rgta_map, rgta_failed = {}, False
    try:
        rgta_map = sweep_tags(
            session.client("resourcegroupstaggingapi", region_name=region, config=Config(retries={"mode": "standard"})),
            rgta_resource_type_filters(entries),
        )
    except Exception:  # noqa: BLE001 - an unreadable sweep makes rgta tags unread, which the verdict reports
        rgta_failed = True
    dims = {"cloud": "aws", "aws_account": account, "aws_region": region}
    out, errors = {}, {}
    for entry in entries:
        et = entry["entity_type"]
        rows = []
        try:
            for item in iter_source(
                entry,
                client_for=client_factory(session, region),
                custom_fns=custom_fns,
                fn_context=session,
                walk=None,
                truncated=None,
                account_id=account,
                scope={"partition": partition, "region": region, "account": account},
            ):
                node = project_item(entry, item)
                tags, _slot, _mapping = resolve_node_tags(
                    entry, item, rgta_map=rgta_map, client_for=client_factory(session, region), rgta_unread=rgta_failed
                )
                edges = set()
                for env in emit_edges(node, entry, modeled_types=modeled_types, transforms=transforms, dimensions=dims).envelopes:
                    e = env["edge"]
                    if e["from_ref"] == node.ref:
                        other, direction = split_node_ref(e["to_ref"]), "outbound"
                    else:
                        other, direction = split_node_ref(e["from_ref"]), "inbound"
                    edges.add((e["edge_type"], direction, other[0], other[1]))
                rows.append(
                    {
                        "natural_key": node.natural_key,
                        "fields": node.fields,
                        "tags": tags if isinstance(tags, dict) else UNREAD_MARK,
                        "edges": sorted(edges),
                    }
                )
        except Exception as exc:  # noqa: BLE001 - every failure is a verdict, none stops the wave
            errors[et] = type(exc).__name__
        out[et] = rows
    return out, errors


def main():
    from tap_plugin.aws_core.collectors.boto3_collector.credentials import (
        AWS_SECRET_REF,
        account_mismatch_error,
        build_session,
        caller_account_id,
        resolve_aws_secret,
        resolve_partition,
        resolve_regions,
    )
    from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
    from tap_plugin.aws_core.collectors.boto3_collector.transforms import build_transform_registry

    expected_doc = json.load(open(os.environ["SEED_EXPECTED"]))
    catalog = json.load(open(os.environ.get("SEED_CATALOG") or catalog_path(globals().get("__file__"))))
    entries = manifest_entries()
    entries_by_type = {e["entity_type"]: e for e in entries}
    modeled = {e["entity_type"] for e in entries}
    seeded = sorted({r["entity_type"] for r in expected_doc["resources"]})
    if expected_doc.get("unresolved_edge_targets"):
        raise SystemExit(f"STOP: the expected inventory has {expected_doc['unresolved_edge_targets']} edge target(s) that match no seeded resource; fix the catalog or the state before comparing")
    unknown = [t for t in seeded if t not in entries_by_type]
    if unknown:
        raise SystemExit(f"STOP: expected inventory names types the manifest lacks: {unknown}")

    secret = resolve_aws_secret(AWS_SECRET_REF)
    data = dict(secret.data)
    regions = resolve_regions(data)
    partition = resolve_partition(data, regions)
    if partition != "aws-us-gov" or "us-gov-west-1" not in regions:
        raise SystemExit(f"STOP: wave 1 compares only in aws-us-gov / us-gov-west-1, credential says {partition} {regions}")
    region = "us-gov-west-1"
    session = build_session(data)
    # The same guard as wave 0, before any client is built: a read verb is not enough (it refuses GetSecretValue,
    # GetObject, GetSessionToken and the rest of its list) and a request that asks the service to reveal a secret.
    sys.path.insert(0, os.path.join(MOUNT, "..", "validate"))
    from readguard import install  # noqa: E402

    install(session)
    account = caller_account_id(session, region, timeout_seconds=30)
    mismatch = account_mismatch_error(data, account)
    if mismatch:
        raise SystemExit(f"STOP: {mismatch}")
    transforms = build_transform_registry(partition)
    first, err1 = _collect(seeded, entries_by_type, session, partition, region, account, modeled, transforms)
    second, err2 = _collect(seeded, entries_by_type, session, partition, region, account, modeled, transforms)
    errors = {**err2, **err1}
    edges_by_type = {t: [(r["edge_type"], r["target_type"]) for r in entries_by_type[t].get("edges", [])] for t in seeded}
    report = build_report(expected_doc, catalog, first, second, errors, edges_by_type)
    text = scrub(json.dumps(report, indent=1, sort_keys=True))
    path = os.environ.get("SEED_OUT")
    if path:
        with open(path, "w") as fh:
            fh.write(text + "\n")
    print("SEED_VERDICT_BEGIN")
    print(text)
    print("SEED_VERDICT_END")


if os.environ.get("SEED_EXPECTED"):
    main()
