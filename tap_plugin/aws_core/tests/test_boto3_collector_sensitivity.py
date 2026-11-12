"""The collection manifest's per-entry ``sensitivity`` declaration.

Spec: spec-aws-core-collector-v0.md (req-aws-collector-manifest-6) and
spec-aws-core-v0.md (req-aws-core-fields-1). Every manifest entry must
declare whether its raw AWS response may carry sensitive values. Three states
are valid, ``unreviewed`` included; a missing declaration is not a state and
must fail, so "nobody looked" can never read as "safe".
"""

from __future__ import annotations

import copy
import json

import botocore.session
import jsonschema
import pytest
from tap_plugin.aws_core.collectors.boto3_collector.manifest import MANIFEST_PATH, SCHEMA_PATH

_STATES = {"unreviewed", "reviewed_none_known", "reviewed_may_contain"}


def _raw_manifest() -> dict:
    # Read the file directly rather than via load_manifest(), so this test does
    # not depend on the schema it is also checking.
    return json.loads(MANIFEST_PATH.read_text())


def _validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text()))


def _entries() -> list[dict]:
    return _raw_manifest()["entries"]


@pytest.mark.parametrize("entry", _entries(), ids=lambda e: e["entity_type"])
def test_every_manifest_entry_declares_sensitivity(entry):
    assert "sensitivity" in entry, (
        f"{entry['entity_type']} has no sensitivity declaration; declare "
        '{"status": "unreviewed"} if nobody has reviewed its response shape yet'
    )
    declared = entry["sensitivity"]
    assert declared["status"] in _STATES
    if declared["status"] == "reviewed_may_contain":
        assert declared["locations"], "reviewed_may_contain must name its locations"
    else:
        assert "locations" not in declared
    if declared["status"] != "unreviewed":
        assert declared.get("basis"), "a reviewed status must name its basis"


class TestSchema:
    def _entry(self) -> dict:
        return copy.deepcopy(_entries()[0])

    def _errors(self, entry: dict) -> list[str]:
        doc = {"manifest_version": "0", "entries": [entry]}
        return [e.message for e in _validator().iter_errors(doc)]

    def test_missing_declaration_is_rejected(self):
        entry = self._entry()
        del entry["sensitivity"]
        assert any("sensitivity" in m for m in self._errors(entry))

    def test_unreviewed_is_a_valid_declaration(self):
        entry = self._entry()
        entry["sensitivity"] = {"status": "unreviewed"}
        entry["persist_configuration"] = False
        assert self._errors(entry) == []

    def test_unreviewed_entry_that_persists_is_rejected(self):
        # req-aws-collector-manifest-7: unreviewed
        # means not stored. The schema carries the rule, so load_manifest()
        # refuses such a manifest before any collection runs.
        entry = self._entry()
        entry["sensitivity"] = {"status": "unreviewed"}
        entry["persist_configuration"] = True
        errors = self._errors(entry)
        assert errors, "an unreviewed entry that persists must fail schema validation"
        assert any("False was expected" in m for m in errors), errors

    @pytest.mark.parametrize("status", ["reviewed_none_known", "reviewed_may_contain"])
    def test_reviewed_entry_may_persist(self, status):
        # The rule binds only the unreviewed state; a reviewed entry decides
        # persistence on its own reason.
        entry = self._entry()
        entry["sensitivity"] = {"status": status, "basis": "read x"}
        if status == "reviewed_may_contain":
            entry["sensitivity"]["locations"] = [
                {"path": "A", "category": "free_text", "reason": "r", "evidence": "reviewer_judgement"}
            ]
        entry["persist_configuration"] = True
        assert self._errors(entry) == []

    def test_may_contain_without_locations_is_rejected(self):
        entry = self._entry()
        entry["sensitivity"] = {"status": "reviewed_may_contain", "basis": "read x"}
        assert self._errors(entry)

    def test_none_known_with_locations_is_rejected(self):
        entry = self._entry()
        entry["sensitivity"] = {
            "status": "reviewed_none_known",
            "basis": "read x",
            "locations": [{"path": "A", "category": "credential", "reason": "r", "evidence": "reviewer_judgement"}],
        }
        assert self._errors(entry)

    def test_reviewed_without_basis_is_rejected(self):
        entry = self._entry()
        entry["sensitivity"] = {"status": "reviewed_none_known"}
        assert self._errors(entry)

    @pytest.mark.parametrize("key", ["persist_configuration", "persist_configuration_why"])
    def test_missing_persist_decision_is_rejected(self, key):
        entry = self._entry()
        del entry[key]
        assert any(key in m for m in self._errors(entry))

    def test_empty_persist_reason_is_rejected(self):
        entry = self._entry()
        entry["persist_configuration"] = False
        entry["persist_configuration_why"] = ""
        assert self._errors(entry)

    def test_non_boolean_persist_flag_is_rejected(self):
        entry = self._entry()
        entry["persist_configuration"] = "false"
        assert self._errors(entry)

    def test_shipped_manifest_validates(self):
        assert list(_validator().iter_errors(_raw_manifest())) == []


# --- declared paths resolve against the real botocore response shapes -------
#
# For entries sourced by a plain aws_op, every declared location must name a
# member that exists in botocore's output shape for that op, reached through
# the entry's items_path. custom_fn entries build their own item and are
# checked by reading the custom_fn; they are skipped here, as are paths under
# an engine-added ``_`` key (for example ``_hydrate.tags``), which is not part
# of the AWS payload.


def _step(shape, segment: str):
    name, is_list = (segment[:-2], True) if segment.endswith("[]") else (segment, False)
    if name:
        assert shape.type_name == "structure", f"{name!r}: parent is {shape.type_name}"
        assert name in shape.members, f"{name!r} not in {shape.name} members"
        shape = shape.members[name]
    if is_list:
        assert shape.type_name == "list", f"{segment!r}: not a list"
        shape = shape.member
    return shape


def _aws_op_locations():
    for entry in _entries():
        op = entry["source"].get("aws_op")
        for loc in entry.get("sensitivity", {}).get("locations", []):
            if op and not loc["path"].startswith("_"):
                yield pytest.param(entry, loc, id=f"{entry['entity_type']}:{loc['path']}")


@pytest.mark.parametrize(("entry", "location"), list(_aws_op_locations()))
def test_declared_path_exists_in_botocore_shape(entry, location):
    model = botocore.session.get_session().get_service_model(entry["service"])
    shape = model.operation_model(entry["source"]["aws_op"]).output_shape
    for segment in entry["items_path"].split("."):
        shape = _step(shape, segment)
    for segment in location["path"].split("."):
        shape = _step(shape, segment)
    if location["evidence"] == "botocore_sensitive":
        flagged = shape.metadata.get("sensitive") or (
            shape.type_name == "map" and shape.value.metadata.get("sensitive")
        )
        assert flagged, f"{location['path']} is not marked sensitive in botocore"


def _tag_carrier(entry: dict) -> str | None:
    """Where an entry's tag values sit inside the configuration envelope.

    field lane: the item path the tags are read from. service lane: the
    collector stores the tag call's response at ``_hydrate.tags``. rgta lane:
    tags come from the per-run sweep, not the item, so nothing is in the
    envelope.
    """
    block = entry.get("tags") or {}
    if block.get("source") == "field":
        return block["from"]
    if block.get("source") == "service":
        return "_hydrate.tags"
    return None


@pytest.mark.parametrize(
    "entry",
    [e for e in _entries() if _tag_carrier(e)],
    ids=lambda e: e["entity_type"],
)
def test_tag_values_in_the_envelope_are_declared(entry):
    # Tag values are operator-set arbitrary strings; where they ride inside
    # the raw envelope they must be on the declared work list.
    paths = {loc["path"] for loc in entry.get("sensitivity", {}).get("locations", [])}
    assert _tag_carrier(entry) in paths


def _sensitive_member_paths(shape, prefix: str = "", seen: frozenset = frozenset()) -> list[str]:
    """Every botocore-``sensitive`` member path under ``shape``, in the manifest dialect.

    A map is a leaf (the dialect cannot address map keys), so a sensitive map or
    map value reports the map's own path.
    """
    if shape.name in seen:
        return []
    seen = seen | {shape.name}
    found: list[str] = []
    if shape.type_name == "structure":
        for name, member in shape.members.items():
            path = f"{prefix}.{name}" if prefix else name
            if member.metadata.get("sensitive"):
                found.append(path)
            else:
                found.extend(_sensitive_member_paths(member, path, seen))
    elif shape.type_name == "list":
        found.extend(_sensitive_member_paths(shape.member, f"{prefix}[]", seen))
    elif shape.type_name == "map" and shape.value.metadata.get("sensitive"):
        found.append(prefix)
    return found


def _covered(path: str, declared: set[str]) -> bool:
    return any(path == d or path.startswith((d + ".", d + "[]")) for d in declared)


@pytest.mark.parametrize(
    "entry",
    [e for e in _entries() if e["source"].get("aws_op")],
    ids=lambda e: e["entity_type"],
)
def test_every_botocore_sensitive_member_is_declared(entry):
    # The completeness ratchet for aws_op entries: whatever botocore marks
    # sensitive in the item shape must be on the declared list (a declared
    # ancestor covers its subtree). custom_fn entries compose their items and
    # are reviewed by reading the custom_fn.
    if entry.get("sensitivity", {}).get("status") == "unreviewed":
        pytest.skip("unreviewed declares nothing to be complete against")
    model = botocore.session.get_session().get_service_model(entry["service"])
    shape = model.operation_model(entry["source"]["aws_op"]).output_shape
    for segment in entry["items_path"].split("."):
        shape = _step(shape, segment)
    declared = {loc["path"] for loc in entry["sensitivity"].get("locations", [])}
    missing = [p for p in _sensitive_member_paths(shape) if not _covered(p, declared)]
    assert missing == [], f"{entry['entity_type']}: botocore-sensitive members not declared: {missing}"


# --- persist_configuration ↔ sensitivity ------------------------------------
#
# Every entry stores its whole response; what is removed is secret material only (req-aws-collector-redaction).


def _credential_locations(entry: dict) -> list[dict]:
    return [loc for loc in entry.get("sensitivity", {}).get("locations", []) if loc["category"] == "credential"]


#: Credential locations AWS marks sensitive that are not secret material, each with why they are stored.
_NOT_SECRET = {
    ("aws_core__aws_cognito_user_pool_client", "ClientId"): "an app client id is a public identifier, not a secret",
    (
        "aws_core__aws_verifiedpermissions_identity_source",
        "configuration.openIdConnectConfiguration.tokenSelection.accessTokenOnly.principalIdClaim",
    ): "the name of a claim, not a token",
    (
        "aws_core__aws_verifiedpermissions_identity_source",
        "configuration.openIdConnectConfiguration.tokenSelection.identityTokenOnly.principalIdClaim",
    ): "the name of a claim, not a token",
    ("aws_core__aws_appstream_directory_config", "ServiceAccountCredentials.AccountName"): "a directory account name, not its password",
}


@pytest.mark.parametrize("entry", [e for e in _entries() if _credential_locations(e)], ids=lambda e: e["entity_type"])
def test_every_member_aws_marks_sensitive_is_removed_before_storage(entry):
    for loc in _credential_locations(entry):
        if loc["evidence"] != "botocore_sensitive" or (entry["entity_type"], loc["path"]) in _NOT_SECRET:
            continue
        assert loc.get("redact") is True, f"{entry['entity_type']}: AWS marks {loc['path']} sensitive and it is stored"


def test_only_secret_material_is_ever_redacted():
    # Customer content, free text, policies and personal data are collected (George, 2026-11-05).
    wrong = [
        (e["entity_type"], loc["path"], loc["category"])
        for e in _entries()
        for loc in e.get("sensitivity", {}).get("locations", [])
        if loc.get("redact") and loc["category"] != "credential"
    ]
    assert wrong == []


def test_every_entry_stores_its_response():
    assert [e["entity_type"] for e in _entries() if not e["persist_configuration"]] == []


@pytest.mark.parametrize("entry", _entries(), ids=lambda e: e["entity_type"])
def test_the_reason_names_what_is_removed(entry):
    for loc in entry.get("sensitivity", {}).get("locations", []):
        if loc.get("redact"):
            assert loc["path"] in entry["persist_configuration_why"], loc["path"]


def _plant(path: str, value: str):
    """A response with ``value`` at ``path`` (a list segment becomes a one-element list)."""
    root: dict = {}
    node = root
    segments = path.split(".")
    for n, part in enumerate(segments):
        last = n == len(segments) - 1
        key, is_list = (part[:-2], True) if part.endswith("[]") else (part, False)
        if is_list and last:
            node[key] = [value]
        elif is_list:
            child: dict = {}
            node[key] = [child]
            node = child
        elif last:
            node[key] = value
        else:
            child = {}
            node[key] = child
            node = child
    return root


def _contains(obj, needle: str) -> bool:
    if isinstance(obj, dict):
        return any(_contains(v, needle) or needle in str(k) for k, v in obj.items())
    if isinstance(obj, list):
        return any(_contains(v, needle) for v in obj)
    return obj == needle


@pytest.mark.parametrize("entry", [e for e in _entries() if any(loc.get("redact") for loc in e["sensitivity"].get("locations", []))], ids=lambda e: e["entity_type"])
def test_a_secret_planted_at_every_redacted_path_is_not_stored(entry):
    from tap_plugin.aws_core.collectors.boto3_collector.batch import entry_redact_paths, persisted_configuration
    from tap_plugin.aws_core.collectors.boto3_collector.projection import ProjectedNode

    canary = "CANARY-secret-8f3a"
    for path in entry_redact_paths(entry):
        node = ProjectedNode(entry["entity_type"], "k", "n", {}, _plant(path, canary), {})
        stored = persisted_configuration(node, persist_configuration=True, redact_paths=entry_redact_paths(entry))
        assert not _contains(stored, canary), f"{entry['entity_type']}: {path} was stored"
        assert path in stored["_redacted"]
