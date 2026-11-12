"""Configuration envelope + deterministic serialization for the boto3 collector.

Spec: plugins/aws_core/specs/spec-aws-core-collector-v0.md
(req-aws-collector-field-projection "Reserved envelope keys and stable
serialization").

Two engine rules keep a node's ``configuration`` byte-identical across runs
when the resource is unchanged (so re-runs upsert cleanly and History/FLIP
does not churn):

1. ``ResponseMetadata`` is stripped from every boto3 response before it
   becomes an item / ``configuration`` — it carries request ids, retry
   counts, and timestamped headers that would otherwise change every run.
2. Values are normalized deterministically: ``datetime``/``date`` ->
   ISO 8601 UTC (``...Z``); the engine serializes with sorted keys.

Everything here builds the in-memory envelope; whether it is persisted is
decided at emit time by the manifest entry's ``persist_configuration`` flag.
The node ``configuration`` is the enumerate item at its root plus the
engine-reserved ``_source`` ({op, why}); ``_hydrate`` / ``_hydrate_mapping``
are added by the fan-out seam (later). ``_source`` is present on every node
so even a single-call object is self-describing without the manifest.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any


def without_response_metadata(response: Any) -> Any:
    """Return ``response`` minus a top-level ``ResponseMetadata`` key."""
    if isinstance(response, dict):
        return {k: v for k, v in response.items() if k != "ResponseMetadata"}
    return response


def jsonable(value: Any) -> Any:
    """Recursively normalize a value to a deterministic, JSON-safe form.

    ``datetime``/``date`` -> ISO 8601 UTC ``...Z``; tz-naive datetimes are
    assumed UTC. dict/list recurse; scalars pass through; anything else falls
    back to ``str()`` (AWS payloads are JSON + datetime, so this is rare).
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def build_configuration(item: Any, *, source_op: str, why: str) -> dict[str, Any]:
    """Build a node's ``configuration``: the item at root + reserved ``_source``.

    ``item`` is the raw enumerate item (already free of ``ResponseMetadata``).
    The result is deterministic and JSON-safe.
    """
    config = jsonable(item)
    if not isinstance(config, dict):
        config = {"value": config}
    config["_source"] = {"op": source_op, "why": why}
    return config


# --- redaction (req-aws-collector-redaction) -----------------------------------------------------------------------
#
# The collector stores everything AWS returns and removes only obvious secret material: keys, passwords, credentials.
# Two things remove it: the paths a manifest entry declares (``sensitivity.locations`` with ``redact: true``), which
# are AWS's own sensitive members and the reviewed secrets, and a scrub of any string value whose key is named like a
# secret. Operator-authored content (tags, descriptions, names, policies) is kept: a secret an operator typed there is
# the operator's.

#: A key that names secret material.
SECRET_KEY = re.compile(
    r"(password|passwd|passphrase|secret|private_?key|api_?key|access_?key|auth_?key|pre_?shared|bearer|"
    r"oauth_?token|auth_?token|hec_?token|secret_?token|session_?token|token_?value|^token$|_token$)",
    re.IGNORECASE,
)
#: Keys that look like it and are not secret: a reference (ARN, id, name, URL), a flag, a date, a policy or a number.
SAFE_KEY = re.compile(
    r"(arn$|id$|name$|status|url$|uri$|type$|version|enabled|required|expir|rotation|length|policy|kms|count|"
    r"last|date|time|reuse|prevention|allow|min|max|hard|xpath|location|provider|selection|claim|param|source)",
    re.IGNORECASE,
)


def _segments(expr: str) -> list[tuple[str, bool]]:
    return [(part[:-2], True) if part.endswith("[]") else (part, False) for part in expr.split(".")]


def _drop(node: Any, segments: list[tuple[str, bool]]) -> bool:
    """Remove the value at ``segments`` from ``node`` (every element of a ``[]`` list); True when something was removed."""
    if not segments:
        return False
    name, is_list = segments[0]
    rest = segments[1:]
    if is_list and not name:  # a bare "[]": the node itself is the list
        return isinstance(node, list) and any([_drop(element, rest) for element in node]) if rest else False
    if not isinstance(node, dict) or name not in node:
        return False
    if not rest and not is_list:
        del node[name]
        return True
    if not rest and is_list:
        del node[name]
        return True
    child = node[name]
    if is_list:
        return isinstance(child, list) and any([_drop(element, rest) for element in child])
    return _drop(child, rest)


def _scrub_keys(node: Any, path: str, found: set[str]) -> None:
    if isinstance(node, dict):
        # A name/value pair whose name is a secret ({"name": "DB_PASSWORD", "value": "..."}: an environment variable,
        # a build parameter): the value is the secret.
        for name_key, value_key in (("name", "value"), ("Name", "Value")):
            name = node.get(name_key)
            if isinstance(name, str) and isinstance(node.get(value_key), str) and SECRET_KEY.search(name) and not SAFE_KEY.search(name):
                del node[value_key]
                found.add(f"{path}.{value_key}" if path else value_key)
        for key in list(node):
            value = node[key]
            here = f"{path}.{key}" if path else str(key)
            if isinstance(value, str) and value and SECRET_KEY.search(str(key)) and not SAFE_KEY.search(str(key)):
                del node[key]
                found.add(here)
            else:
                _scrub_keys(value, here, found)
    elif isinstance(node, list):
        for element in node:
            _scrub_keys(element, f"{path}[]", found)


def redact_configuration(config: dict[str, Any], paths: Iterable[str] = ()) -> dict[str, Any]:
    """A copy of ``config`` without the declared secret paths and without any string whose key names a secret.

    The result lists what it removed under ``_redacted`` (sorted, with list positions written ``[]``), so a reader of
    the grid can tell a withheld value from an absent one. Nothing is added when nothing was removed."""
    out = copy.deepcopy(config)
    removed = {path for path in paths if _drop(out, _segments(path))}
    _scrub_keys(out, "", removed)
    if removed:
        out["_redacted"] = sorted(removed)
    return out
