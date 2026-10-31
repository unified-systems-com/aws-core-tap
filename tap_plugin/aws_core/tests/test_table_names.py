"""Every table a model owns must have a name Postgres keeps whole.

Postgres silently truncates an identifier longer than 63 characters, so the table exists under a
shorter name than the model declares and the grid's table-presence health check (grid.tables) reports
it absent, which keeps a booted web container from ever becoming ready.
"""

from __future__ import annotations

import pytest
from django.apps import apps

_LIMIT = 63


def _owned_tables() -> list[str]:
    return sorted(
        model._meta.db_table
        for model in apps.get_app_config("aws_core").get_models()
    )


@pytest.mark.parametrize("table", _owned_tables())
def test_table_name_fits_postgres(table: str) -> None:
    assert len(table) <= _LIMIT, f"{table} is {len(table)} characters; Postgres keeps {_LIMIT}"
