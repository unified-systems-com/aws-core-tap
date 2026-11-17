"""A squashed migration keeps the migrations it replaces, so an existing database can still upgrade.

Django applies a squashed migration only to a database that has applied none of the migrations it replaces. A database
part-way through them (one that ran v0.8.0 stops at 0019) needs the originals to finish. v0.8.1 shipped the squash
without them, and such a database could not migrate at all (unified-systems-com/aws-core-tap#235).
"""

import ast
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def _replaces(path: Path) -> list[str]:
    """The migration names a migration file lists in ``replaces``, read without importing it."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "replaces" for t in node.targets):
            return [name for _app, name in ast.literal_eval(node.value)]
    return []


def test_every_replaced_migration_is_still_shipped() -> None:
    present = {p.stem for p in MIGRATIONS.glob("[0-9]*.py")}
    squashes = {p.name: _replaces(p) for p in MIGRATIONS.glob("[0-9]*_squashed_*.py")}
    assert squashes, "no squashed migration found; delete this test once the squash itself is retired"
    missing = {name: sorted(set(replaced) - present) for name, replaced in squashes.items()}
    assert not any(missing.values()), missing
