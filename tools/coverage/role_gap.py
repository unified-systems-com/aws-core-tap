"""Print the IAM policy that closes the collector's known read-permission gaps, and check the list.

    python3 -I tools/coverage/role_gap.py            # the policy for the default sections, as JSON
    python3 -I tools/coverage/role_gap.py --include-opt-in
    python3 -I tools/coverage/role_gap.py --check    # exit 1 if the list has drifted from the manifest

Reads ``extended-read-actions.json`` and the manifest as data. Calls no AWS API and applies nothing:
the policy is for the person who owns the collector's role.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIST_FILE = HERE / "extended-read-actions.json"
MANIFEST = HERE.parents[1] / "tap_plugin" / "aws_core" / "collectors" / "boto3_collector" / "aws_resource_manifest.json"
READ_VERBS = ("Get", "List", "Describe")


def load(path: Path = LIST_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def actions_of(doc: dict, *, include_opt_in: bool = False) -> list[str]:
    """The actions of every section that goes in the policy (and of the opt-in one when asked for)."""
    out: set[str] = set()
    for section in doc["sections"]:
        if section["in_policy"] or (include_opt_in and section["id"] == "opt-in-credential-bearing"):
            out.update(item["action"] for item in section["actions"])
    return sorted(out)


def policy_of(doc: dict, *, include_opt_in: bool = False) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "TapCollectorExtendedRead", "Effect": "Allow", "Action": actions_of(doc, include_opt_in=include_opt_in), "Resource": "*"}
        ],
    }


def manifest_operations(path: Path = MANIFEST) -> set[str]:
    """Every operation name the manifest's entries call (``aws_op`` and the per-item follow-up ``per``)."""
    ops: set[str] = set()
    for entry in json.loads(path.read_text(encoding="utf-8"))["entries"]:
        source = entry.get("source", {})
        for key in ("aws_op", "per"):
            value = source.get(key)
            if isinstance(value, str):
                ops.add(value)
    return ops


def problems_of(doc: dict, operations: set[str]) -> list[str]:
    """What is wrong with the list: a non-read verb, a duplicate, an entry without a description, or a
    collection-gap action whose operation no manifest entry calls (the manifest moved and the list did not)."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for section in doc["sections"]:
        if not section.get("description"):
            problems.append(f"section {section['id']}: no description")
        for item in section["actions"]:
            action = item["action"]
            service, _, operation = action.partition(":")
            if not service or not operation:
                problems.append(f"{action}: not service:Operation")
                continue
            if not operation.startswith(READ_VERBS):
                problems.append(f"{action}: not a read verb")
            if action in seen:
                problems.append(f"{action}: in {seen[action]} and {section['id']}")
            seen[action] = section["id"]
            if section["id"] == "collection-gaps" and operation not in operations:
                problems.append(f"{action}: no manifest entry calls {operation}")
            if not section["in_policy"] and "reason" not in item:
                problems.append(f"{action}: left out of the policy with no reason")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--include-opt-in", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    doc = load()
    if args.check:
        found = problems_of(doc, manifest_operations())
        for line in found:
            print(line)
        return 1 if found else 0
    json.dump(policy_of(doc, include_opt_in=args.include_opt_in), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
