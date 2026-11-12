"""The IAM policy the collector needs, generated from what the collector can call (``req-aws-collector-iam-policy``).

The collector's reads are named in the manifest (every ``aws_op`` of a source and its ``per`` parents, every tag and
hydrate operation) and in the Python that serves the custom functions, the Organizations tree, the landing zone and the
region facts. This module collects them into one set of (botocore service, operation) pairs, maps each to the IAM
actions that authorise it, and writes the result as a few customer-managed policy documents small enough to attach to
one role, plus an explicit deny for the actions that return secret material or read what a resource holds.

    uv run python -m tap_plugin.aws_core.collectors.boto3_collector.iam_policy --write      # regenerate the documents
    uv run python -m tap_plugin.aws_core.collectors.boto3_collector.iam_policy --refresh    # rebuild the action data
    uv run python -m tap_plugin.aws_core.collectors.boto3_collector.iam_policy --refresh-arns   # rebuild the ARN formats only

The operation-to-action mapping is AWS's own: the Service Authorization Reference
(https://servicereference.us-east-1.amazonaws.com/) names, for each SDK method, the actions that authorise it.
``--refresh`` reads it (network) and writes ``iam_operation_actions.json`` for the operations the collector makes;
generating the documents is offline. An action that writes, manages permissions or reads the data plane is dropped from
a read operation's list and recorded under ``dropped``.

The same refresh writes ``arn_formats.json``: the reference's ARN formats for every resource type a model names in its
``ARN_RESOURCE`` (``"<service>:<resource>"``, ``req-aws-collector-identity-11``), so building an ARN is offline and
reads the same data every time. ``--refresh-arns`` rebuilds ``arn_formats.json`` alone, reading only the services the
models name, so adding a model never rewrites the IAM action data as a side effect.
"""

from __future__ import annotations

import ast
import concurrent.futures
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import botocore.session
from botocore import xform_name

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "aws_resource_manifest.json"
OVERRIDES = HERE / "iam_policy_overrides.json"
CATALOG = HERE / "iam_operation_actions.json"
ARN_FORMATS = HERE / "arn_formats.json"
MODELS_DIR = HERE.parent.parent / "models"
OUT_DIR = HERE / "handoff"
PART_NAME = "collector-policy-{n:02d}.json"
REFERENCE = "https://servicereference.us-east-1.amazonaws.com/v1/"
#: IAM counts the characters of a managed policy without whitespace; the limit is 6,144.
PART_LIMIT = 6000
#: A role takes 10 managed policies by default.
MAX_PARTS = 10
#: Modules that name AWS operations outside the manifest.
CODE_MODULES = (
    "customfns.py", "customfns_longtail.py", "landing_zone.py", "organizations.py", "identity.py", "regions.py",
    "rgta.py", "ecs.py", "iam_trust.py", "policy_documents.py", "credentials.py", "authority.py", "hydrate.py",
)  # fmt: skip
_CLIENT_CALLS = {"client_for", "client", "get_client", "_client", "make_client"}
_OP_WORD = re.compile(r"^([a-z]+(_[a-z0-9]+)+|[A-Z][A-Za-z0-9]+)$")

_session = botocore.session.get_session()
_services = set(_session.get_available_services())
_ops_cache: dict[str, dict[str, str]] = {}


def operations_of(service: str) -> dict[str, str]:
    """``{snake_name: OperationName, OperationName: OperationName}`` for a botocore service ({} when unknown)."""
    if service not in _services:
        return {}
    if service not in _ops_cache:
        names = _session.get_service_model(service).operation_names
        _ops_cache[service] = {**{xform_name(n): n for n in names}, **{n: n for n in names}}
    return _ops_cache[service]


def _manifest_pairs() -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for entry in json.loads(MANIFEST.read_text())["entries"]:
        service = entry["service"]
        source = entry.get("source") or {}
        if "aws_op" in source:
            pairs.add((service, source["aws_op"]))
        per, parent_service = source.get("per"), service
        while isinstance(per, dict):
            parent_service = per.get("service", parent_service)
            if "aws_op" in per:
                pairs.add((parent_service, per["aws_op"]))
            per = per.get("per")
        tags = entry.get("tags") or {}
        if tags.get("source") == "service":
            pairs.add((service, tags["op"]))
        if tags.get("source") == "rgta":
            pairs.add(("resourcegroupstaggingapi", "GetResources"))
        for hop in entry.get("hydrate") or []:
            pairs.add((service, hop["op"]))
        if entry.get("enrich"):
            pairs.add((service, entry["enrich"]["op"]))
    return pairs


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _string_args(call: ast.Call) -> list[str]:
    values = [a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    values += [k.value.value for k in call.keywords if isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)]
    return values


def _code_pairs() -> set[tuple[str, str]]:
    """Operations the collector's Python names. Per function: every service it builds a client for, crossed with every
    operation-shaped name it uses (a method called on a client, or a string handed to a helper) that the service has."""
    pairs: set[tuple[str, str]] = set()
    for module in CODE_MODULES:
        path = HERE / module
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        module_services: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) in _CLIENT_CALLS:
                module_services |= {s for s in _string_args(node)[:1] if s in _services}
        scopes: list[ast.AST] = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))] or [tree]
        for scope in scopes:
            services: set[str] = set()
            names: set[str] = set()
            for node in ast.walk(scope):
                if isinstance(node, ast.Call):
                    if _call_name(node) in _CLIENT_CALLS:
                        services |= {s for s in _string_args(node)[:1] if s in _services}
                    if isinstance(node.func, ast.Attribute):
                        names.add(node.func.attr)
                    names |= {s for s in _string_args(node) if _OP_WORD.match(s)}
                elif isinstance(node, ast.Constant) and isinstance(node.value, str) and _OP_WORD.match(node.value):
                    names.add(node.value)
            for service in services or module_services:
                known = operations_of(service)
                pairs |= {(service, known[n]) for n in names if n in known}
    return pairs


def overrides() -> dict[str, Any]:
    return json.loads(OVERRIDES.read_text())


def catalog() -> dict[str, Any]:
    return json.loads(CATALOG.read_text())


def inventory() -> set[tuple[str, str]]:
    """Every (botocore service, operation) the collector can make, except those that need no permission."""
    ov = overrides()
    return {p for p in _manifest_pairs() | _code_pairs() if f"{p[0]}:{p[1]}" not in ov["no_permission_needed"]}


def _key(service: str, operation: str) -> str:
    return f"{service}:{xform_name(operation)}"


def iam_actions(service: str, operation: str, ov: dict[str, Any], cat: dict[str, Any]) -> list[str]:
    """The IAM actions that authorise ``operation`` of botocore ``service``.

    In order: an explicit override; a rule (API Gateway's one verb); AWS's reference data; otherwise the operation's own
    name under the service's signing name, which is right for most services and is reported by ``unverified()``."""
    explicit = (ov["actions"].get(f"{service}:{operation}") or {}).get("actions")
    if explicit is not None:
        return list(explicit)
    for rule in ov.get("rules", []):
        if service in rule["services"] and operation.startswith(rule["operation_prefix"]):
            return list(rule["actions"])
    known = cat["operations"].get(_key(service, operation))
    if known is not None and known["actions"]:
        return list(known["actions"])
    meta = _session.get_service_model(service).metadata
    prefix = (ov["prefixes"].get(service) or {}).get("prefix") or meta.get("signingName") or meta.get("endpointPrefix") or service
    return [f"{prefix}:{operation}"]


def unverified(ov: dict[str, Any] | None = None, cat: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """Operations whose action is the default name because neither an override nor AWS's reference data gave one."""
    ov, cat = ov or overrides(), cat or catalog()
    out = []
    for service, operation in sorted(inventory()):
        explicit = f"{service}:{operation}" in ov["actions"]
        ruled = any(service in r["services"] and operation.startswith(r["operation_prefix"]) for r in ov.get("rules", []))
        known = cat["operations"].get(_key(service, operation))
        if not explicit and not ruled and not (known and known["actions"]):
            out.append((service, operation))
    return out


def actions() -> list[str]:
    ov, cat = overrides(), catalog()
    found: set[str] = set()
    for service, operation in inventory():
        found |= set(iam_actions(service, operation, ov, cat))
    return sorted(found)


def deny_actions() -> list[str]:
    """Actions written as an explicit deny, so no other policy attached to the role can allow them: those that return
    secret material, and those that read what a resource holds (its objects, items, parameters)."""
    return sorted(overrides()["deny"])


def _statement(sid: str, acts: list[str]) -> dict[str, Any]:
    return {"Sid": sid, "Effect": "Allow", "Action": acts, "Resource": "*"}


def _size(doc: dict[str, Any]) -> int:
    return len(re.sub(r"\s", "", json.dumps(doc, separators=(",", ":"))))


def _doc(statements: list[dict[str, Any]]) -> dict[str, Any]:
    return {"Version": "2012-10-17", "Statement": statements}


def build_parts() -> list[dict[str, Any]]:
    """The policy documents: allow statements grouped by IAM service prefix, packed in order into parts of at most
    ``PART_LIMIT`` characters. The first part also carries the explicit deny."""
    by_prefix: dict[str, list[str]] = {}
    for action in actions():
        by_prefix.setdefault(action.split(":")[0].lower(), []).append(action)
    parts: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = [{"Sid": "NeverReturnSecretsOrContents", "Effect": "Deny", "Action": deny_actions(), "Resource": "*"}]
    pending: list[tuple[str, list[str]]] = [("Read" + re.sub(r"[^A-Za-z0-9]", "", p.title()), by_prefix[p]) for p in sorted(by_prefix)]
    while pending:
        sid, acts = pending.pop(0)
        stmt = _statement(sid, acts)
        if _size(_doc(current + [stmt])) <= PART_LIMIT:
            current.append(stmt)
        elif _size(_doc([stmt])) <= PART_LIMIT:
            parts.append(_doc(current))
            current = [stmt]
        else:  # one service alone exceeds a part: split its actions
            half = len(acts) // 2
            pending = [(sid + "A", acts[:half]), (sid + "B", acts[half:])] + pending
    parts.append(_doc(current))
    return parts


def render() -> dict[str, str]:
    """File name to file text for every policy document."""
    return {PART_NAME.format(n=i + 1): json.dumps(p, indent=2) + "\n" for i, p in enumerate(build_parts())}


# --- refreshing AWS's reference data (network) ---------------------------------------------------------------------


def _fetch(url: str) -> Any:
    """One reference document, retried: the host serves hundreds of small files and drops some connections."""
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - a fixed https URL
                return json.loads(response.read())
        except OSError:
            if attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))


def refresh() -> dict[str, Any]:
    """Rebuild ``iam_operation_actions.json`` from the Service Authorization Reference, for the collector's operations."""
    wanted = {_key(s, o): (s, o) for s, o in inventory()}
    services = _fetch(REFERENCE + "service-list.json")
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        docs = list(pool.map(lambda s: _fetch(s["url"]), services))
    props: dict[str, dict[str, bool]] = {}
    for doc in docs:
        prefix = doc["Name"]
        for action in doc.get("Actions", []):
            p = action.get("Annotations", {}).get("Properties", {})
            props[f"{prefix}:{action['Name']}"] = {k: bool(p.get(k)) for k in ("IsWrite", "IsPermissionManagement", "IsDataPlane")}
    operations: dict[str, Any] = {}
    for doc in docs:
        for op in doc.get("Operations", []):
            for sdk in op.get("SDK", []):
                key = f"{sdk['Name']}:{sdk['Method']}"
                if sdk.get("Package") != "Boto3" or key not in wanted:
                    continue
                entry = operations.setdefault(key, {"actions": [], "dropped": []})
                for authorised in op.get("AuthorizedActions", []):
                    action = f"{authorised['Service']}:{authorised['Name']}"
                    flags = props.get(action, {})
                    if any(flags.values()):
                        entry["dropped"].append({"action": action, "why": ", ".join(k for k, v in flags.items() if v)})
                    elif action not in entry["actions"]:
                        entry["actions"].append(action)
    for entry in operations.values():
        entry["actions"].sort()
    write_arn_formats(docs)
    data = {
        "description": "For each operation the collector makes, the IAM actions that authorise it, from AWS's Service Authorization Reference (https://servicereference.us-east-1.amazonaws.com/). Rebuilt by iam_policy.py --refresh. 'dropped' lists actions the reference attaches to the operation that write, manage permissions or read the data plane; a read operation does not need them and the collector is not granted them.",
        "operations": dict(sorted(operations.items())),
    }
    CATALOG.write_text(json.dumps(data, indent=1) + "\n")
    return data


def arn_resources() -> set[str]:
    """Every ``ARN_RESOURCE`` a model names, read from the model sources (nothing is imported)."""
    named: set[str] = set()
    for path in MODELS_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "ARN_RESOURCE"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                named.add(node.value.value)
    return named


def arn_formats_from(docs: list[dict[str, Any]], wanted: set[str]) -> dict[str, Any]:
    """The reference's ARN formats for each wanted ``<service>:<resource>``; one the reference lacks is left out, and
    the test over the models names it."""
    formats = {
        f"{doc['Name']}:{resource['Name']}": resource.get("ARNFormats", [])
        for doc in docs
        for resource in doc.get("Resources", [])
        if f"{doc['Name']}:{resource['Name']}" in wanted
    }
    return {
        "description": "For each resource type an aws_core model names in ARN_RESOURCE, its ARN formats from AWS's Service Authorization Reference (https://servicereference.us-east-1.amazonaws.com/v1/<service>/<service>.json, Resources[].ARNFormats). Rebuilt by iam_policy.py --refresh or --refresh-arns; do not edit.",
        "resources": dict(sorted(formats.items())),
    }


#: A whole ARN template: the partition left open, a service, region and account parts (either may be empty), and a
#: non-empty resource; every ``${`` closes, and nothing has whitespace.
ARN_FORMAT = re.compile(
    r"arn:\$\{Partition\}:[a-z0-9-]+:(?:[^:\s$]|\$\{\w+\})*:(?:[^:\s$]|\$\{\w+\})*:(?:[^\s$]|\$\{\w+\})+"
)


def write_arn_formats(docs: list[dict[str, Any]]) -> None:
    """Write the formats, or refuse and write nothing when the reference is missing a resource type a model names: a
    short, failed or malformed fetch must not change the vendored file, and the file is replaced whole."""
    wanted = arn_resources()
    data = arn_formats_from(docs, wanted)
    missing = sorted(wanted - set(data["resources"]))
    if missing:
        raise SystemExit(f"the reference has no entry for {', '.join(missing)}; {ARN_FORMATS.name} left as it was")
    malformed = sorted(
        r for r, formats in data["resources"].items() if not formats or not all(ARN_FORMAT.fullmatch(f) for f in formats)
    )
    if malformed:
        raise SystemExit(f"the reference gives no usable ARN format for {', '.join(malformed)}; {ARN_FORMATS.name} left as it was")
    staged = ARN_FORMATS.with_suffix(".json.tmp")
    staged.write_text(json.dumps(data, indent=1) + "\n")
    staged.replace(ARN_FORMATS)


def refresh_arn_formats() -> int:
    """Rebuild ``arn_formats.json`` alone, from the reference files of the services the models name (network)."""
    wanted = arn_resources()
    prefixes = {r.split(":", 1)[0] for r in wanted}
    services = [s for s in _fetch(REFERENCE + "service-list.json") if s["service"] in prefixes]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        docs = list(pool.map(lambda s: _fetch(s["url"]), services))
    write_arn_formats(docs)
    return len(wanted)


def main(argv: list[str]) -> int:
    if "--refresh-arns" in argv:
        print(f"wrote {refresh_arn_formats()} resource types to {ARN_FORMATS.name}")
    if "--refresh" in argv:
        data = refresh()
        print(f"wrote {len(data['operations'])} operations to {CATALOG.name}")
    if "--write" in argv:
        files = render()
        for old in OUT_DIR.glob("collector-policy-*.json"):
            old.unlink()
        for name, text in files.items():
            (OUT_DIR / name).write_text(text)
        print(f"wrote {len(files)} policy documents, {len(actions())} actions")
    if not argv:
        print(f"{len(render())} policy documents, {len(actions())} actions, {len(inventory())} operations, {len(unverified())} unverified")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
