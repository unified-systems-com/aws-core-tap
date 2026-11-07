"""Make one edge type read as having no declared identity, to exercise the path that keeps an explicit uuid5 id.

No aws_core edge type is undeclared any more (``ROUTES_TRAFFIC`` declares a plain key now that its emitters exist), but
the batch still supports one, for an edge type a plugin ships without a declaration; these tests pin that path."""

from __future__ import annotations

import pytest
from tap_grid import edge_identity

UNDECLARED = "ROUTES_TRAFFIC__aws_core"


def read_as_undeclared(monkeypatch: pytest.MonkeyPatch, edge_type: str = UNDECLARED) -> None:
    real = edge_identity.get_edge_identity
    monkeypatch.setattr(edge_identity, "get_edge_identity", lambda slug: None if slug == edge_type else real(slug))
