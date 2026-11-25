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


# --- certificate_not_after (ruling Q150b, 2026-11-24) -------------------------------------------------------------------

#: A self-signed EC P-256 certificate made for these tests alone (no key was kept): notBefore 2026-01-01T00:00:00Z,
#: notAfter 2030-01-02T03:04:05Z.
TEST_CERTIFICATE = """-----BEGIN CERTIFICATE-----
MIIBKjCB0aADAgECAgEBMAoGCCqGSM49BAMCMB8xHTAbBgNVBAMMFHRhcCB0ZXN0
IGNlcnRpZmljYXRlMB4XDTI2MDEwMTAwMDAwMFoXDTMwMDEwMjAzMDQwNVowHzEd
MBsGA1UEAwwUdGFwIHRlc3QgY2VydGlmaWNhdGUwWTATBgcqhkjOPQIBBggqhkjO
PQMBBwNCAARyfnxHopwDM4FFaDd2vqyyeMUisFofzLpa3d+3kPz+lUZh5NEs9O15
YLkV0IgLr4MZKXMqIhmNsqz208ZxevmZMAoGCCqGSM49BAMCA0gAMEUCIQCAdRpF
e9ejOCAfbYEuQd2tbG5LIQ33a+uBt92+6QlBbQIgGepyaghC2Yu9vK9cSWl1oQo9
4CL+Eh3glAoVhkaheOU=
-----END CERTIFICATE-----
"""


def test_certificate_not_after_reads_the_certificates_own_end_as_a_zoned_datetime() -> None:
    read = times.certificate_not_after(TEST_CERTIFICATE)
    assert read == datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert read is not None and read.utcoffset() is not None
    reading = event_time.read_value(read)
    assert reading is not None and (reading.start, reading.level) == (datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC), "second")


def test_certificate_not_after_reads_the_first_of_several_and_ignores_surrounding_space() -> None:
    assert times.certificate_not_after("\n" + TEST_CERTIFICATE + TEST_CERTIFICATE) == datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    "stored",
    [
        None,
        "",
        "   ",
        b"not text",
        1893553445,
        {"CertificateBody": "x"},
        "-----BEGIN CERTIFICATE-----TAPCANARYCERTBODY",
        "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n",
        TEST_CERTIFICATE.replace("MIIBKjCB", "MIIBKjCC"),
        "certificate: é",
    ],
)
def test_certificate_not_after_is_none_for_anything_but_a_readable_certificate(stored: Any) -> None:
    assert times.certificate_not_after(stored) is None


def test_certificate_not_after_is_a_reader_core_accepts() -> None:
    declaration = event_time.Interval(
        start="upload_date",
        kind="created",
        end="configuration",
        end_member=("CertificateBody",),
        end_reader="tap_plugin.aws_core.times:certificate_not_after",
    )
    assert event_time.resolve_reader(declaration.end_reader) is times.certificate_not_after
    derived = event_time.derive(
        declaration,
        {"upload_date": "2026-10-01T12:30:00Z", "configuration": {"CertificateBody": TEST_CERTIFICATE}}.get,
    )
    assert (derived.event_start, derived.event_end, derived.warnings) == (
        datetime(2026, 10, 1, 12, 30, tzinfo=UTC),
        datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC),
        (),
    )


# --- either_created_date: an API Gateway stage's configuration, under either service's spelling -------------------


@pytest.mark.parametrize(
    "configuration",
    [
        # REST (apigateway GetStages item[]): createdDate, stored as the envelope renders a botocore timestamp.
        {"stageName": "prod", "createdDate": "2026-03-04T05:06:07Z", "_api_kind": "rest"},
        # HTTP and WebSocket (apigatewayv2 GetStages Items[]): CreatedDate.
        {"StageName": "prod", "CreatedDate": "2026-03-04T05:06:07Z", "_api_kind": "http"},
        # Both, agreeing: no service sends both, and the one value is read.
        {"createdDate": "2026-03-04T05:06:07Z", "CreatedDate": "2026-03-04T05:06:07Z"},
    ],
)
def test_either_created_date_returns_whichever_spelling_is_present(configuration: dict[str, Any]) -> None:
    assert times.either_created_date(configuration) == "2026-03-04T05:06:07Z"


@pytest.mark.parametrize("configuration", [{}, {"stageName": "prod"}, {"createdDate": None}, {"CreatedDate": ""}])
def test_either_created_date_is_none_when_neither_is_present(configuration: dict[str, Any]) -> None:
    assert times.either_created_date(configuration) is None


def test_either_created_date_picks_neither_of_two_different_values() -> None:
    with pytest.raises(ValueError):
        times.either_created_date({"createdDate": "2026-03-04T05:06:07Z", "CreatedDate": "2025-01-01T00:00:00Z"})


@pytest.mark.parametrize("stored", ["2026-03-04T05:06:07Z", ["createdDate"], 1767225600])
def test_either_created_date_raises_on_anything_not_a_dict(stored: Any) -> None:
    with pytest.raises(TypeError):
        times.either_created_date(stored)


def test_either_created_date_is_a_reader_core_accepts_by_function_and_by_path() -> None:
    by_path = event_time.Interval(
        start="configuration", kind="created", reader="tap_plugin.aws_core.times:either_created_date"
    )
    assert event_time.resolve_reader(by_path.reader) is times.either_created_date
    derived = event_time.derive(by_path, {"configuration": {"CreatedDate": "2026-03-04T05:06:07Z"}}.get)
    assert (derived.event_start, derived.event_end) == (datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC), None)

