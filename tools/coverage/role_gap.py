"""Print the IAM policy that closes the collector's known read-permission gaps, and check the list.

    python3 -I tools/coverage/role_gap.py            # the policy for the default sections, as JSON
    python3 -I tools/coverage/role_gap.py --include-opt-in
    python3 -I tools/coverage/role_gap.py --check    # exit 1 if the list has drifted from the manifest

Reads ``extended-read-actions.json`` and the manifest as data. Calls no AWS API and applies nothing:
the policy is for the person who owns the collector's role.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIST_FILE = HERE / "extended-read-actions.json"
CUSTOMFNS = HERE.parents[1] / "tap_plugin" / "aws_core" / "collectors" / "boto3_collector" / "customfns.py"
MANIFEST = HERE.parents[1] / "tap_plugin" / "aws_core" / "collectors" / "boto3_collector" / "aws_resource_manifest.json"
READ_VERBS = ("Get", "List", "Describe")
#: A read verb is not enough: ``sts:GetFederationToken`` and ``ecr:GetAuthorizationToken`` begin with ``Get`` and
#: issue credentials. This screen is a heuristic on the operation name, not IAM's own metadata (the AWS service
#: authorization reference), so it catches the obvious cases and a person still reads the list.
CREDENTIAL_WORDS = re.compile(r"Token|Secret|Password|Credential|Federation", re.IGNORECASE)


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


def manifest_calls(path: Path = MANIFEST) -> tuple[set[tuple[str, str]], dict[str, set[str]]]:
    """What the manifest calls: ``(boto service, operation)`` pairs from each entry's ``aws_op`` and the
    ``aws_op`` of its ``per`` follow-up, and ``{custom function: services}`` for entries a function reads
    (their operations are not visible in the manifest)."""
    calls: set[tuple[str, str]] = set()
    functions: dict[str, set[str]] = {}
    for entry in json.loads(path.read_text(encoding="utf-8"))["entries"]:
        source = entry.get("source", {})
        service = entry["service"]
        for step in (source, source.get("per") if isinstance(source.get("per"), dict) else {}):
            if isinstance(step.get("aws_op"), str):
                calls.add((service, step["aws_op"]))
        if isinstance(source.get("custom_fn"), str):
            functions.setdefault(source["custom_fn"], set()).add(service)
    return calls, functions


def custom_fn_strings(function: str, path: Path = CUSTOMFNS) -> set[str]:
    """The string constants in a custom function and in the module-level functions it calls, followed
    transitively. A boto3 call is written ``_pages(client, "list_applications")`` or
    ``client.list_applications(...)``, so the snake_case operation name is among them or among its
    attribute names. Returns the empty set when the function is not defined."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    found: set[str] = set()
    pending, seen = [function], set()
    while pending:
        name = pending.pop()
        if name in seen or name not in defined:
            continue
        seen.add(name)
        for node in ast.walk(defined[name]):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.add(node.value)
            elif isinstance(node, ast.Attribute):
                found.add(node.attr)
            elif isinstance(node, ast.Name):
                pending.append(node.id)
    return found


def snake_case(operation: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", operation).lower()


def problems_of(doc: dict, calls: set[tuple[str, str]], functions: dict[str, set[str]]) -> list[str]:
    """What is wrong with the list: a non-read verb, an operation that issues credentials, a duplicate, an
    entry without a reason, or a collection-gap action the manifest no longer makes under that service (the
    action's prefix is mapped to the boto service through ``iam_prefix_of_service``; an entry read by a
    custom function names it in ``custom_fn``, and the function, with the module-level helpers it calls, must name the snake_case operation)."""
    prefix_of = doc.get("iam_prefix_of_service", {})
    pairs = {(prefix_of.get(service, service), operation) for service, operation in calls}
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
            if section["in_policy"] and CREDENTIAL_WORDS.search(operation):
                problems.append(f"{action}: the operation name suggests it returns a credential or secret")
            if action in seen:
                problems.append(f"{action}: in {seen[action]} and {section['id']}")
            seen[action] = section["id"]
            if section["id"] == "collection-gaps":
                function = item.get("custom_fn")
                if function is not None:
                    services = {prefix_of.get(name, name) for name in functions.get(function, set())}
                    if service not in services:
                        problems.append(f"{action}: no manifest entry read by {function} is under service {service}")
                    elif snake_case(operation) not in custom_fn_strings(function):
                        problems.append(f"{action}: {function} does not call {snake_case(operation)}")
                elif (service, operation) not in pairs:
                    problems.append(f"{action}: no manifest entry calls {operation} under service {service}")
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
        found = problems_of(doc, *manifest_calls())
        for line in found:
            print(line)
        return 1 if found else 0
    json.dump(policy_of(doc, include_opt_in=args.include_opt_in), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
