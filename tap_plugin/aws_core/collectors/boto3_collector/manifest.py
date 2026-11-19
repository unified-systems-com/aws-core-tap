"""Manifest loader for the boto3 collector.

Spec: plugins/aws_core/specs/spec-aws-core-collector-v0.md
(req-aws-collector-manifest). The manifest is pure data; this loads it and
validates it against the shipped JSON Schema at load. An invalid manifest is
an author error, not a runtime condition — it fails loud (per the AGENTS.md
Core TAP Rule: structured-data formats validate at load).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from tap.jsonfiles import JsonFileError, load_json_file, load_schema, validate_json

_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = _DIR / "aws_resource_manifest.json"
SCHEMA_PATH = _DIR / "aws_resource_manifest.schema.json"


class ManifestError(Exception):
    """The resource manifest is missing, unparseable, or schema-invalid."""


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    """Load and schema-validate the resource manifest.

    Returns the parsed manifest dict. Raises ``ManifestError`` if the file or
    schema is missing/unparseable or the manifest fails schema validation.
    """
    try:
        manifest: dict[str, Any] = load_json_file(MANIFEST_PATH)
        schema = load_schema(SCHEMA_PATH)
    except (JsonFileError, OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"Cannot read/parse manifest or schema: {exc}") from exc

    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        validate_json(manifest, schema, source=MANIFEST_PATH)
    except jsonschema.SchemaError as exc:
        raise ManifestError(f"Manifest schema is itself invalid: {exc.message}") from exc
    except JsonFileError as exc:
        raise ManifestError(f"Manifest failed schema validation: {exc}") from exc

    return manifest


def manifest_entries() -> list[dict[str, Any]]:
    """The validated manifest entries (one per resource type)."""
    entries: list[dict[str, Any]] = load_manifest()["entries"]
    return entries


#: The attribute a model no manifest entry collects declares its identity in (``req-aws-collector-identity-12``):
#: the readers that are not manifest-driven (Organizations, landing zone, findings) write those types, and the
#: model is where their identity already lives (``NATURAL_KEY``, ``ARN_RESOURCE``).
MODEL_IDENTITY_ATTR = "AWS_IDENTITY"
_APP_LABEL = "aws_core"


@lru_cache(maxsize=1)
def identity_schema() -> dict[str, Any]:
    """The manifest schema's ``identity`` declaration, as a standalone schema for a model's ``AWS_IDENTITY``."""
    schema = load_schema(SCHEMA_PATH)
    return {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/identity"}


def identity_declarations() -> dict[str, dict[str, Any]]:
    """``{entity type: identity declaration}`` for every aws_core type that declares one
    (``req-aws-collector-identity-12``): a manifest entry's ``identity`` block, or a model's ``AWS_IDENTITY`` for a
    type no manifest entry collects. A model declaration is validated against the same schema as the manifest's;
    a type declared in both places, or a model declaration that fails the schema, raises ``ManifestError``."""
    from tap_grid.registry import get_model_class, list_entity_types

    out: dict[str, dict[str, Any]] = {
        str(e["entity_type"]): e["identity"] for e in manifest_entries() if isinstance(e.get("identity"), dict)
    }
    validator = jsonschema.Draft202012Validator(identity_schema())
    for entity_type in list_entity_types():
        model = get_model_class(entity_type)
        declared = getattr(model, MODEL_IDENTITY_ATTR, None)
        if declared is None or getattr(getattr(model, "_meta", None), "app_label", None) != _APP_LABEL:
            continue
        if entity_type in out:
            raise ManifestError(f"{entity_type} declares its identity in both the manifest and {MODEL_IDENTITY_ATTR}")
        errors = sorted(validator.iter_errors(declared), key=lambda e: list(e.path))
        if errors:
            raise ManifestError(f"{entity_type}.{MODEL_IDENTITY_ATTR} fails the identity schema: {errors[0].message}")
        out[entity_type] = dict(declared)
    return out
