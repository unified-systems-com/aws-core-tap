"""Read a Terraform provider schema dump (`terraform providers schema -json`) into the crosscheck normal form.

This reads a FILE. It never runs Terraform: the dump is produced once, by `terraform_dump.sh`, and the
comparison only reads it as data. Terraform is a reference, not ground truth.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

PROVIDER = "registry.terraform.io/hashicorp/aws"
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff\u061c]")


def _clean(s: object) -> str:
    return _CTRL.sub("?", str(s))


def _type_text(t: Any) -> str:
    """A compact rendering of a Terraform type: "string", "list(string)", "object"."""
    if isinstance(t, str):
        return t
    if isinstance(t, list) and t:
        inner = t[1] if len(t) > 1 else ""
        return _clean(t[0]) + ("(" + _type_text(inner) + ")" if isinstance(inner, (str, list)) and inner else "")
    return "?"


def _flags(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": _type_text(a.get("type", a.get("nested_type", {}).get("nesting_mode") if isinstance(a.get("nested_type"), dict) else None)),
        "required": bool(a.get("required")),
        "optional": bool(a.get("optional")),
        "computed": bool(a.get("computed")),
        "sensitive": bool(a.get("sensitive")),
        "deprecated": bool(a.get("deprecated")),
        "write_only": bool(a.get("write_only")),
    }


def _flatten(block: dict[str, Any], prefix: str, out: dict[str, dict[str, Any]]) -> None:
    for name, a in sorted((block.get("attributes") or {}).items()):
        path = prefix + _clean(name)
        out[path] = {**_flags(a), "block": False}
        nested = a.get("nested_type")
        if isinstance(nested, dict):  # a framework nested attribute
            _flatten(nested, path + ".", out)
    for name, b in sorted((block.get("block_types") or {}).items()):
        path = prefix + _clean(name)
        out[path] = {
            "type": "block",
            "required": int(b.get("min_items", 0) or 0) > 0,
            "optional": int(b.get("min_items", 0) or 0) == 0,
            "computed": False,
            "sensitive": False,
            "deprecated": bool(b.get("block", {}).get("deprecated")),
            "write_only": False,
            "block": True,
            "nesting": _clean(b.get("nesting_mode", "")),
        }
        _flatten(b.get("block") or {}, path + ".", out)


def read(path: Path) -> dict[str, Any]:
    """Resources of the AWS provider in a schema dump file.

    Returns {"sha256", "format_version", "resources": {type: {"attributes": {dotted path: flags}, "top_level": [...],
    "taggable", "identity": [...], "deprecated"}}}. A file with no resources is refused.
    """
    raw = Path(path).read_bytes()
    try:
        d = json.loads(raw)
    except ValueError as e:
        raise ValueError(f"{path} is not JSON: {e}") from e
    prov = (d.get("provider_schemas") or {}).get(PROVIDER) if isinstance(d, dict) else None
    schemas = (prov or {}).get("resource_schemas") or {}
    if not schemas:
        raise ValueError(f"{path} has no resources for {PROVIDER}: refusing to score against an empty reference")
    idents = (prov or {}).get("resource_identity_schemas") or {}
    resources: dict[str, dict[str, Any]] = {}
    for rtype, rs in sorted(schemas.items()):
        flat: dict[str, dict[str, Any]] = {}
        block = rs.get("block") or {}
        _flatten(block, "", flat)
        top = sorted(k for k in flat if "." not in k)
        ident = idents.get(rtype, {}).get("attributes") or {}
        resources[_clean(rtype)] = {
            "attributes": flat,
            "top_level": top,
            "taggable": "tags" in flat or "tags_all" in flat,
            "identity": sorted(_clean(k) for k in ident),
            "identity_required": sorted(_clean(k) for k, v in ident.items() if v.get("required_for_import")),
            "deprecated": bool(block.get("deprecated")),
        }
    return {"sha256": hashlib.sha256(raw).hexdigest(), "format_version": _clean(d.get("format_version", "")), "resources": resources}
