"""Account membership is a dimension, not an edge (req-aws-core-account-dimension, aws-core-tap#81)."""

import json
from pathlib import Path

import pytest

import tap_plugin.aws_core.collectors.boto3_collector as collector_pkg

_MANIFEST = Path(collector_pkg.__file__).parent / "aws_resource_manifest.json"
_EDGE = "BELONGS_TO_ACCOUNT__aws_core"


@pytest.mark.spec("req-aws-core-account-dimension-4")
def test_no_manifest_edge_rule_writes_the_account_edge() -> None:
    # The edge is written only by containment.py, and only for a different owner. A manifest ``edges`` rule
    # that named it would write it for every item, which is the hub this requirement removes.
    entries = json.loads(_MANIFEST.read_text())["entries"]
    writers = [
        entry["entity_type"]
        for entry in entries
        for rule in entry.get("edges") or []
        if rule.get("edge_type") == _EDGE
    ]
    assert writers == []
