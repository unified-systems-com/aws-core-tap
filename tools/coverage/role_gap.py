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
#: One service prefix and one operation, no wildcard: ``iam:Get*`` is not an action but a family of them.
ACTION_FORM = re.compile(r"^[a-z0-9-]+:[A-Z][A-Za-z0-9]*$")
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
        if section["in_policy"] or (include_opt_in and section.get("opt_in")):
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


def _client_names(function: ast.FunctionDef) -> set[str]:
    """The names in a function that hold a boto3 client: a parameter called ``client`` or any name assigned
    from ``client_for(...)`` or ``<something>.client(...)``."""
    names = {arg.arg for arg in function.args.args + function.args.kwonlyargs if arg.arg == "client"}
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            callee = node.value.func
            if (isinstance(callee, ast.Name) and callee.id == "client_for") or (
                isinstance(callee, ast.Attribute) and callee.attr == "client"
            ):
                names.update(target.id for target in node.targets if isinstance(target, ast.Name))
    return names


def custom_fn_calls(function: str, path: Path = CUSTOMFNS) -> set[str]:
    """The boto3 operations a custom function, and the module-level functions it calls (followed transitively),
    invoke on a client, in the two forms the module uses: ``client.list_applications(...)`` and
    ``_pages(client, "list_applications")``. The receiver must be a name that holds a client (see
    :func:`_client_names`); ``logger.list_applications()`` or ``print("list_applications")`` is not a call.
    A heuristic on the module's own idiom, not a proof of what is sent. Empty when the function is not defined."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    found: set[str] = set()
    pending, seen = [function], set()
    while pending:
        name = pending.pop()
        if name in seen or name not in defined:
            continue
        seen.add(name)
        clients = _client_names(defined[name])
        for node in ast.walk(defined[name]):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            if isinstance(callee, ast.Name):
                pending.append(callee.id)
                first = node.args[0] if node.args else None
                second = node.args[1] if len(node.args) > 1 else None
                if (
                    callee.id == "_pages"
                    and isinstance(first, ast.Name)
                    and first.id in clients
                    and isinstance(second, ast.Constant)
                    and isinstance(second.value, str)
                ):
                    found.add(second.value)
            elif isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Name) and callee.value.id in clients:
                found.add(callee.attr)
    return found


def snake_case(operation: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", operation).lower()


def problems_of(doc: dict, calls: set[tuple[str, str]], functions: dict[str, set[str]]) -> list[str]:
    """What is wrong with the list: a non-read verb, an operation that issues credentials, a duplicate, an
    entry without a reason, or a collection-gap action the manifest no longer makes under that service (the
    action's prefix is mapped to the boto service through ``iam_prefix_of_service``; an entry read by a
    custom function names it in ``custom_fn``, and the function, with the module-level helpers it calls, must call the snake_case operation, as a boto3 method or as the name passed to a call)."""
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
            if not ACTION_FORM.match(action):
                problems.append(f"{action}: not service:Operation (one operation, no wildcard)")
                continue
            if not operation.startswith(READ_VERBS):
                problems.append(f"{action}: not a read verb")
            if (section["in_policy"] or section.get("opt_in")) and CREDENTIAL_WORDS.search(operation) and section["id"] != "opt-in-credential-bearing":
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
                    elif snake_case(operation) not in custom_fn_calls(function):
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
