"""Make one edge type read as having no declared identity, to exercise the path that keeps an explicit uuid5 id.

No aws_core edge type is undeclared any more, but the batch still supports one, for an edge type a plugin ships without
a declaration; these tests pin that path with ``RESOLVES_TO_TARGET`` (a record set to the CloudFront distribution it
aliases), which the slice's canned run emits."""

from __future__ import annotations

import pytest
from tap_grid import edge_identity

UNDECLARED = "RESOLVES_TO_TARGET__aws_core"


def read_as_undeclared(monkeypatch: pytest.MonkeyPatch, edge_type: str = UNDECLARED) -> None:
    real = edge_identity.get_edge_identity
    monkeypatch.setattr(edge_identity, "get_edge_identity", lambda slug: None if slug == edge_type else real(slug))
