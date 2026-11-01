"""Named outcomes of a listing that is not a failure of the call (``req-aws-collector-outcome``).

A listing that raised is one of four things, and the collector must not blur them:

- ``not_configured`` — the feature is not set up in this account (DRS never initialised, no QuickSight
  subscription). The honest result is "nothing was listed", with the reason. It is **not** an
  authoritative complete-empty observation: the error is the service refusing to answer, not the
  service saying the set is empty, so it licenses no retirement (``Listing`` and ``ListingWalk`` both
  record it as not complete, with the reason).
- ``unsupported_in_partition`` — the partition does not offer the service or the operation. A clear,
  recorded result rather than a crash; also not complete.
- ``throttled`` — the service rate-limited the call past the client's retry budget. The walk stopped;
  the source did not say the list ended. Never read as empty.
- anything else is a failed call, as before.

The first two are **data**, not code and not a broad catch: ``error_outcomes.json`` holds one reviewed
row per (service, operation or entity type, error code) with a ``why``, validated against
``error_outcomes.schema.json`` at load. A ``not_configured`` row must name its service, error code and
operation or entity type. An error no row matches is classified as nothing and fails the listing.
Throttling is classified from the error code alone (``listing.THROTTLE_CODES``), because every
throttling answer means the same thing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
from botocore.exceptions import BotoCoreError, ClientError

from tap.jsonfiles import JsonFileError, load_json_file, load_schema, validate_json

from .listing import THROTTLE_CODES, error_code

NOT_CONFIGURED = "not_configured"
UNSUPPORTED_IN_PARTITION = "unsupported_in_partition"
THROTTLED = "throttled"

_DIR = Path(__file__).resolve().parent
OUTCOMES_PATH = _DIR / "error_outcomes.json"
OUTCOMES_SCHEMA_PATH = _DIR / "error_outcomes.schema.json"


class OutcomesError(Exception):
    """The error-outcomes file is missing, unparseable, or schema-invalid: an author error, loud."""


@dataclass(frozen=True)
class Outcome:
    """What a raised listing error means: ``kind`` (one of the three names above), the error ``code``
    it carried, and ``why`` (the reviewed row's reason, or the fixed reason for throttling)."""

    kind: str
    code: str
    why: str

    @property
    def reason(self) -> str:
        """The ``code: prose`` form a completeness surface carries for an attribute that is not true."""
        return f"{self.kind}: {self.code}: {self.why}"


@lru_cache(maxsize=1)
def load_rows() -> tuple[dict[str, Any], ...]:
    """The validated rows of ``error_outcomes.json``."""
    try:
        data: dict[str, Any] = load_json_file(OUTCOMES_PATH)
        schema = load_schema(OUTCOMES_SCHEMA_PATH)
    except (JsonFileError, OSError, json.JSONDecodeError) as exc:
        raise OutcomesError(f"Cannot read/parse error outcomes or schema: {exc}") from exc
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        validate_json(data, schema, source=OUTCOMES_PATH)
    except jsonschema.SchemaError as exc:
        raise OutcomesError(f"Error-outcomes schema is itself invalid: {exc.message}") from exc
    except JsonFileError as exc:
        raise OutcomesError(f"Error outcomes failed schema validation: {exc}") from exc
    return tuple(data["rows"])


def _message_of(exc: BaseException) -> str:
    if isinstance(exc, ClientError):
        return str((exc.response or {}).get("Error", {}).get("Message", ""))
    return str(exc)


def _row_matches(row: dict[str, Any], entry: dict[str, Any], exc: BaseException, code: str, partition: str) -> bool:
    if row["service"] not in ("*", entry["service"]):
        return False
    if partition in row.get("not_in_partitions", ()):
        return False
    if "error_code" in row and row["error_code"] != code:
        return False
    if "exception" in row and row["exception"] not in {cls.__name__ for cls in type(exc).__mro__}:
        return False
    if "operations" in row or "entity_types" in row:
        operation = getattr(exc, "operation_name", None)
        named = operation in row.get("operations", ()) or entry["entity_type"] in row.get("entity_types", ())
        if not named:
            return False
    if "message_contains" in row and row["message_contains"].lower() not in _message_of(exc).lower():
        return False
    return True


def classify(
    entry: dict[str, Any], exc: BaseException, partition: str, rows: tuple[dict[str, Any], ...] | None = None
) -> Outcome | None:
    """The named outcome of ``exc`` raised while listing ``entry`` in ``partition``, or ``None``.

    ``None`` means a failed call: the caller records it as before. ``rows`` defaults to the shipped file.
    """
    if not isinstance(exc, (ClientError, BotoCoreError)):
        return None
    code = error_code(exc)
    if code in THROTTLE_CODES:
        return Outcome(THROTTLED, code, "the service rate-limited the call past the client's retries; the listing did not finish")
    for row in rows if rows is not None else load_rows():
        if _row_matches(row, entry, exc, code, partition):
            return Outcome(row["outcome"], code or type(exc).__name__, row["why"])
    return None
