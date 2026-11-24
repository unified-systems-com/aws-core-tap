"""The plugin's reader functions (tap_plugin.aws_core.times; tap req-grid-entity-event-time rules 23 to 28).

Each takes the value AWS sent, as the field stores it, and returns a form core's one reader takes; a value it cannot
read raises, which core turns into no event time and a warning naming the field.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from tap_plugin.aws_core import times

from tap_grid import event_time


@pytest.mark.parametrize(
    ("stored", "read"),
    [
        # Lambda's documented example (ListLayerVersions CreatedDate).
        ("2018-11-27T15:10:45.123+0000", "2018-11-27T15:10:45.123+00:00"),
        ("2026-10-01T00:00:00.000+0000", "2026-10-01T00:00:00.000+00:00"),
        # An offset other than UTC keeps its instant: the colon is the only change.
        ("2026-10-01T05:30:00.000+0530", "2026-10-01T05:30:00.000+05:30"),
        ("2026-10-01T00:00:00-0700", "2026-10-01T00:00:00-07:00"),
        # Already in a form core reads (W3C ISO 8601, as the function URL's shape is documented): unchanged.
        ("2026-10-01T00:00:00.123456Z", "2026-10-01T00:00:00.123456Z"),
        ("2026-10-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00"),
    ],
)
def test_offset_without_colon_returns_text_core_reads(stored: str, read: str) -> None:
    assert times.offset_without_colon(stored) == read
    assert event_time.read_value(read) is not None


def test_the_instant_is_the_one_lambda_stated() -> None:
    reading = event_time.read_value(times.offset_without_colon("2026-10-01T05:30:00.000+0530"))
    assert reading is not None
    assert (reading.start, reading.level) == (datetime(2026, 10, 1, 0, 0, tzinfo=UTC), "second")


@pytest.mark.parametrize(
    "stored",
    [
        "2026-10-01T00:00:00.000",  # no zone: a reader may not assume one (core rule 24)
        "2026-10-01 00:00:00+0000",  # not ISO 8601's T
        "2026-10-01T00:00+0000",  # stops at the minute
        "2026-10-01T00:00:00.000+00",  # a two-digit offset
        "2026-10-01",
        "",
        " 2026-10-01T00:00:00.000+0000",
        "1767225600",
    ],
)
def test_offset_without_colon_raises_on_text_in_neither_form(stored: str) -> None:
    with pytest.raises(ValueError):
        times.offset_without_colon(stored)


@pytest.mark.parametrize("stored", [1767225600, 1767225600.5, None, True, {"CreatedDate": "x"}, datetime(2026, 1, 1)])
def test_offset_without_colon_raises_on_anything_not_text(stored: Any) -> None:
    with pytest.raises(TypeError):
        times.offset_without_colon(stored)


def test_a_failure_reaches_core_as_unreadable_not_as_a_crash() -> None:
    """Core rule 25: a raise is handled by core (no event time, a warning), never propagated to the write."""
    derived = event_time.derive(
        event_time.Interval(start="created_date", kind="created", reader=times.offset_without_colon),
        {"created_date": "2026-10-01T00:00:00.000"}.get,
    )
    assert derived.event_start is None
    assert derived.warnings and "created_date" in derived.warnings[0] and "ValueError" in derived.warnings[0]


def test_it_is_a_module_level_function_core_accepts_by_function_and_by_path() -> None:
    """Core rule 26: a declaration may name it directly or by its import path, and both reach the same function."""
    by_path = event_time.Interval(
        start="created_date", kind="created", reader="tap_plugin.aws_core.times:offset_without_colon"
    )
    assert event_time.resolve_reader(by_path.reader) is times.offset_without_colon
    assert event_time.reader_name(times.offset_without_colon) == "tap_plugin.aws_core.times:offset_without_colon"
