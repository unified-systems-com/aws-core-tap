"""The generated collector policy (``req-aws-collector-iam-policy-1``)."""

from __future__ import annotations

import json
import re

from tap_plugin.aws_core.collectors.boto3_collector import iam_policy as iam
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries

LIMIT = 6144


def _handoff_files() -> dict[str, str]:
    return {p.name: p.read_text() for p in sorted(iam.OUT_DIR.glob("collector-policy-*.json"))}


def test_the_committed_documents_are_what_the_generator_writes() -> None:
    assert _handoff_files() == iam.render(), "run iam_policy --write and commit the result"


def test_every_document_fits_an_iam_managed_policy() -> None:
    for name, text in _handoff_files().items():
        assert len(re.sub(r"\s", "", text)) <= LIMIT, name


def test_the_documents_are_read_only_and_deny_secrets() -> None:
    first = json.loads(_handoff_files()["collector-policy-01.json"])
    deny = [s for s in first["Statement"] if s["Effect"] == "Deny"]
    assert len(deny) == 1 and "secretsmanager:GetSecretValue" in deny[0]["Action"]
    allowed = {a for t in _handoff_files().values() for s in json.loads(t)["Statement"] if s["Effect"] == "Allow" for a in s["Action"]}
    writes = [a for a in allowed if re.match(r"^[\w-]+:(Create|Delete|Put|Update|Start|Stop|Terminate|Attach|Detach|Modify)", a)]
    assert not writes
    assert not allowed & set(deny[0]["Action"])


def test_every_manifest_operation_is_granted() -> None:
    allowed = {a for t in _handoff_files().values() for s in json.loads(t)["Statement"] if s["Effect"] == "Allow" for a in s["Action"]}
    ov, cat = iam.overrides(), iam.catalog()
    missing = [
        (e["service"], e["enrich"]["op"])
        for e in manifest_entries()
        if e.get("enrich") and not set(iam.iam_actions(e["service"], e["enrich"]["op"], ov, cat)) <= allowed
    ]
    assert not missing
    for service, operation in iam.inventory():
        assert set(iam.iam_actions(service, operation, ov, cat)) <= allowed, (service, operation)
