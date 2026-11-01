"""Read AWS's CloudFormation data into one normal form, by reading files only.

Two inputs, both public and both untrusted:

* a per-region resource specification (``CloudFormationResourceSpecification.json``, fetched by ``cfn_fetch.sh``):
  which resource types a region offers, their properties and their read-only ``GetAtt`` attributes;
* the schema bundle the coverage ledger is built from: ``readOnlyProperties``, ``createOnlyProperties``,
  ``writeOnlyProperties``, ``primaryIdentifier`` and ``tagging`` per type. It is read by the ledger's own reader
  (``tap_plugin/aws_core/ledger/sources.py``), not re-implemented here.

Nothing is imported or executed from either input, symbolic links are refused, and every string taken from a file
has control characters replaced before it can reach a report.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

MAX_SPEC_BYTES = 64 * 1024 * 1024
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
_TYPE_NAME = re.compile(r"^[A-Za-z0-9]+::[A-Za-z0-9]+::[A-Za-z0-9]+(::[A-Za-z0-9]+)*$")


class CfnReadError(ValueError):
    """A file that is not what it should be; refused rather than guessed at."""


def clean(value: Any) -> str:
    """Text from a file, with control characters (terminal escapes, newlines, NUL) replaced by a space."""
    return _CONTROL.sub(" ", str(value))


def _read_file(path: Path, limit: int) -> bytes:
    path = Path(path)
    if path.is_symlink():
        raise CfnReadError(f"{clean(path.name)} is a symbolic link; refused")
    if not path.is_file():
        raise CfnReadError(f"{clean(path)} is not a file")
    if path.stat().st_size > limit:
        raise CfnReadError(f"{clean(path.name)} is over {limit} bytes")
    return path.read_bytes()


def _kind(p: dict) -> str:
    """The value's shape as one string: a primitive, a named type, or a list/map of either."""
    base = p.get("PrimitiveType") or p.get("Type") or "Unknown"
    if base in ("List", "Map"):
        item = p.get("PrimitiveItemType") or p.get("ItemType") or "Unknown"
        return f"{base}<{item}>"
    return str(base)


def read_spec(path: Path) -> dict[str, Any]:
    """A regional specification as {version, sha256, bytes, types: {name: {properties, attributes}}}."""
    raw = _read_file(path, MAX_SPEC_BYTES)
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise CfnReadError(f"{clean(Path(path).name)} is not JSON: {clean(exc)}") from exc
    rtypes = doc.get("ResourceTypes") if isinstance(doc, dict) else None
    if not isinstance(rtypes, dict) or not rtypes:
        raise CfnReadError(f"{clean(Path(path).name)} holds no resource types; refusing an empty specification")
    types: dict[str, Any] = {}
    for name, body in rtypes.items():
        if not isinstance(name, str) or not _TYPE_NAME.match(name):
            raise CfnReadError(f"{clean(Path(path).name)}: {clean(name)!r} is not a CloudFormation type name")
        if not isinstance(body, dict):
            raise CfnReadError(f"{clean(name)}: entry is not an object")
        props, attrs = body.get("Properties") or {}, body.get("Attributes") or {}
        if not isinstance(props, dict) or not isinstance(attrs, dict):
            raise CfnReadError(f"{clean(name)}: Properties or Attributes is not an object")
        types[name] = {
            "properties": {
                clean(k): {
                    "required": bool(v.get("Required")) if isinstance(v, dict) else False,
                    "kind": _kind(v) if isinstance(v, dict) else "Unknown",
                    "update": clean(v.get("UpdateType", "")) if isinstance(v, dict) else "",
                }
                for k, v in sorted(props.items())
            },
            "attributes": {clean(k): _kind(v) if isinstance(v, dict) else "Unknown" for k, v in sorted(attrs.items())},
        }
    version = doc.get("ResourceSpecificationVersion")
    return {
        "version": clean(version) if isinstance(version, str) else "unknown",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "types": dict(sorted(types.items())),
    }


def read_manifest(path: Path) -> list[dict[str, Any]]:
    """The tab-separated manifest cfn_fetch.sh writes: file, URL, HTTP status, sha256, bytes, version."""
    rows = []
    for line in _read_file(path, 1 << 20).decode("utf-8", "replace").splitlines():
        parts = line.split("\t")
        if len(parts) != 6:
            raise CfnReadError(f"manifest line has {len(parts)} fields, not 6")
        f, url, status, sha, size, ver = (clean(x) for x in parts)
        rows.append({"file": f, "url": url, "http_status": status, "sha256": sha, "bytes": size, "version": ver})
    return sorted(rows, key=lambda r: r["file"])


def top_level(prop_path: str) -> str:
    """'/properties/Foo/Bar' or 'Foo.Bar' -> 'Foo'."""
    p = prop_path[len("/properties/"):] if prop_path.startswith("/properties/") else prop_path
    return re.split(r"[/.]", p, maxsplit=1)[0]


def _load_sources(plugin_root: Path) -> Any:
    src = Path(plugin_root) / "tap_plugin" / "aws_core" / "ledger" / "sources.py"
    spec = importlib.util.spec_from_file_location("_cfn_ledger_sources", src)
    if spec is None or spec.loader is None:
        raise CfnReadError(f"cannot load {clean(src)}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses looks its module up here
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return mod


def read_bundle(plugin_root: Path, bundle: Path) -> dict[str, Any]:
    """Per type, the schema fields the verifier compares, read through the ledger's own ``load_cfn_bundle``.

    The ledger reader keeps only what the ledger records, so its per-document parser is wrapped to also keep the
    property lists; its checks, size limits and zip handling are the ledger's own and run unchanged. The ledger's
    ``confine`` applies: the bundle must lie under the working directory or the temporary directory.
    """
    sources = _load_sources(plugin_root)
    extras: dict[str, dict[str, Any]] = {}
    original = sources._parse_type

    def capture(document: Any, member: str) -> Any:
        parsed = original(document, member)
        if parsed is not None:
            def names(key: str) -> list[str]:
                v = document.get(key, [])
                return sorted({top_level(x) for x in v if isinstance(x, str)}) if isinstance(v, list) else []

            extras[parsed.type_name] = {
                "read_only": names("readOnlyProperties"),
                "create_only": names("createOnlyProperties"),
                "write_only": names("writeOnlyProperties"),
            }
        return parsed

    sources._parse_type = capture
    try:
        types, digest = sources.load_cfn_bundle(Path(bundle))
    except sources.SourceError as exc:
        raise CfnReadError(clean(exc)) from exc
    finally:
        sources._parse_type = original
        sys.modules.pop("_cfn_ledger_sources", None)
    out = {}
    for name, t in sorted(types.items()):
        out[clean(name)] = {
            "primary_identifier": [clean(x) for x in t.primary_identifier],
            "taggable": t.taggable,
            "tag_property": clean(t.tag_property) if t.tag_property else None,
            "has_tagging_block": t.has_tagging_block,
            **extras.get(t.type_name, {"read_only": [], "create_only": [], "write_only": []}),
        }
    return {"sha256": digest, "types": out}
