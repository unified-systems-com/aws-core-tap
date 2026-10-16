"""The canonical `tags` field on the collected aws_core models.

Covers req-aws-core-fields-4. Uniform name + shape + default so cross-resource
tag queries work by convention; declared in both schemas; never an Entity-spine
facet.

The covered set is DERIVED FROM THE COLLECTOR MANIFEST, not hand-listed. The
v0.4.0 scar: this file used to enumerate "the 8 manifest-collected models" by
hand, six types were added to the manifest without extending the list, and one
of them (secrets_manager_secret) shipped without a `tags` field — the collector
stamps `tags` on every node envelope unconditionally, so core's GRIFT import
(additionalProperties: false) rejected the whole batch on any account with a
Secrets Manager secret. Deriving from the manifest makes the guard fail closed:
a future manifest entry is covered the moment it exists.
"""

from __future__ import annotations

import pytest
from tap_plugin.aws_core import models as models_pkg
from tap_plugin.aws_core.collectors.boto3_collector.manifest import load_manifest

_MANIFEST_ENTRIES = load_manifest()["entries"]

_MODELS_BY_ENTITY_TYPE = {
    cls.ENTITY_TYPE: cls for cls in vars(models_pkg).values() if isinstance(cls, type) and hasattr(cls, "ENTITY_TYPE")
}


def _collected_model(entry):
    model = _MODELS_BY_ENTITY_TYPE.get(entry["entity_type"])
    assert model is not None, f"manifest entry {entry['entity_type']} has no model class"
    return model


@pytest.mark.parametrize("entry", _MANIFEST_ENTRIES, ids=lambda e: e["entity_type"])
class TestCanonicalTagsField:
    def test_field_exists_defaults_empty_dict(self, entry):
        model = _collected_model(entry)
        field = model._meta.get_field("tags")
        assert field.get_internal_type() == "JSONField"
        assert field.default is dict  # uniform empty-map default
        assert field.blank is True

    def test_declared_in_both_schemas(self, entry):
        model = _collected_model(entry)
        assert model.FIELD_CRUD_SCHEMA["tags"] == {"type": "object"}
        assert model.FIELD_VALIDATION_SCHEMA["tags"] == {
            "validation": "jsonschema",
            "schema": {"type": "object"},
        }

    def test_uniform_name_across_family(self, entry):
        # The query-by-convention contract: same attribute name everywhere.
        assert hasattr(_collected_model(entry), "tags")

    def test_tags_never_projected_via_fields(self, entry):
        """Tags reach the envelope ONLY through resolve_node_tags.

        node_envelope stamps the resolved tags map AFTER the projected fields,
        so a `fields.tags` projection is silently clobbered to {} (the second
        v0.4.0 scar: five types fetched real tags in their custom fns and lost
        them here). An entry whose enumeration carries tags declares
        `tags: {source: "field", from: ..., shape: ...}` instead.
        """
        assert "tags" not in entry.get("fields", {}), (
            f"{entry['entity_type']} projects tags via fields — the envelope clobbers "
            f"projected tags; declare a tags block with source 'field' instead"
        )

    def test_tags_block_shape_when_declared(self, entry):
        block = entry.get("tags")
        if block is None:
            return  # extraction is optional (e.g. aws_account is untaggable); the FIELD is not
        assert block["source"] in ("rgta", "field", "service")
        if block["source"] == "field":
            assert block["shape"] in ("list_kv", "list_kv_lower", "map")
            assert block["from"], "field-lane tags block needs a source path"
