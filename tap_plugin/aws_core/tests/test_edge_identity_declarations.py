"""Every aws_core edge type declares how one of its edges is found again.

C11a of the edge identity epic (aws-core-tap#78, epic unified-systems-com/tap#911). Core reads the
``identity`` member of each edge definition (``req-grid-edge-identity-declaration``): a plain key
(``discriminators: []``, an edge found by type, source and target), declared discriminators, or
keyless with a reason. A type with none is *undeclared*, which core tolerates only in warn mode
(unified-systems-com/tap#928 makes a ref-addressed edge of an undeclared type fail its batch), so
a new edge type without a declaration fails here first.

Every type here but one is a plain key. aws_core derives each edge id from (type, source, target)
today (``collectors/boto3_collector/identity.py``), so there is at most one edge per type and pair
already; the plain key says the same thing, now that edges are found rather than derived.
"""

import json
from pathlib import Path

import pytest

from tap_grid.edge_identity_shape import check_edge_identity

EDGES = Path(__file__).resolve().parent.parent / "edges"

#: Types left undeclared on purpose, each with the issue that settles it. ROUTES_TRAFFIC's unit of
#: meaning (separate types, ``destination_cidr`` / ``port`` discriminators, or routes as nodes) is
#: decided when its emitters are built.
DEFERRED = {"ROUTES_TRAFFIC__aws_core": "aws-core-tap#64"}

DEFINITIONS = sorted(EDGES.glob("*.edge.json"))


def test_the_definitions_are_found() -> None:
    assert len(DEFINITIONS) > 50, f"expected aws_core's edge definitions under {EDGES}"


@pytest.mark.parametrize("path", DEFINITIONS, ids=lambda path: path.name)
def test_every_edge_type_declares_its_identity(path: Path) -> None:
    definition = json.loads(path.read_text())
    slug = definition["slug"]
    if slug in DEFERRED:
        assert "identity" not in definition, f"{slug} now declares identity: drop it from DEFERRED ({DEFERRED[slug]})"
        return
    assert "identity" in definition, (
        f"{slug} declares no identity: add {{'discriminators': []}} for a plain key, or declare discriminators "
        "or keyless with a reason (req-grid-edge-identity-declaration)"
    )
    check_edge_identity(slug, definition["identity"], property_schema=definition.get("property_schema"))
