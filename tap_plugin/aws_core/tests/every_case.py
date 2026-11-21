"""Run one invariant over every case and fail once, naming every case that breaks it.

An invariant that must hold for every manifest entry, model or table used to be one parametrized
test per case, so the suite collected thousands of near-identical tests. ``assert_every`` keeps the
check per case and the coverage whole: each case is checked, every failure is collected, and the
test fails once with the failing cases sorted by name and the reason each one failed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import pytest


def _reason(exc: Exception) -> str:
    text = str(exc).strip()
    if not isinstance(exc, AssertionError):
        text = f"{type(exc).__name__}: {text}" if text else type(exc).__name__
    return text or "assertion failed"


def assert_every[T](cases: Iterable[tuple[str, T]], check: Callable[[T], object]) -> None:
    """Call ``check`` on every ``(name, case)``; fail once listing each failing name and its reason.

    Any exception a check raises is a failure of that case, as it was when each case was its own test.
    An empty set of cases fails too: an invariant that walks nothing proves nothing.
    """
    failures: list[tuple[str, str]] = []
    seen = 0
    for name, case in cases:
        seen += 1
        try:
            check(case)
        except Exception as exc:  # noqa: BLE001 - any error fails that case, as a per-case test would
            failures.append((name, _reason(exc)))
    if not seen:
        pytest.fail("no cases to check", pytrace=False)
    if failures:
        lines = [f"{len(failures)} of {seen} cases fail:"]
        for name, reason in sorted(failures):
            lines.append(f"- {name}")
            lines.extend(f"    {line}" for line in reason.splitlines())
        pytest.fail("\n".join(lines), pytrace=False)
