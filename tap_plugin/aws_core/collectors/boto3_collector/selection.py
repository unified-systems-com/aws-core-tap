"""Collection selection: which types and which accounts a run reads.

Spec: specs/spec-aws-core-secrets.md (req-aws-core-secret-selection) and
specs/spec-aws-core-collector-v0.md (req-aws-collector-selection).

A run can be narrowed to chosen manifest entries (``include_types`` / ``exclude_types``) and chosen accounts
(``accounts_allowed``). The four keys sit in the credential's ``data`` for now, beside ``regions_allowed``; they
describe scope, not secret material. Everything here is a pure function of the keys and the manifest, so the
grammar, the matching and the fail-closed checks are tested without a run.

The rules this module holds:

- A type pattern is ``<service>:<entity>``, ``*`` and ``?`` the only glob characters, matched case-sensitively
  against the entry's ``service`` and its ``entity_type`` without the ``aws_core__aws_`` prefix. An entry is selected
  when it matches an include pattern (or none is given) and no exclude pattern. Exclusion wins.
- The run's own account node is an anchor and is never filtered, nor are the per-(account, region) footprints.
- A pattern that matches no entry stops the run before any call (``SELECTION_PATTERN_UNMATCHED``): the selection
  lives in a secret the operator cannot inspect, and an exclude that matched nothing would widen the run silently.
- An account reference is a 12-digit id or an ARN naming an account. Every reference is normalised to the 12-digit
  id, de-duplicated and sorted.
- ``retire_within_selection: true`` is refused until core honours it (unified-systems-com/tap#1156).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from .partition import parse_arn

#: The prefix every manifest entity type carries; a pattern's entity half is matched without it.
ENTITY_PREFIX = "aws_core__aws_"

#: Entries that are anchors, not types to choose: the run's own account node. Never filtered, never counted as
#: skipped (``req-aws-collector-selection-3``). The per-(account, region) footprints are not manifest entries at all.
ANCHOR_ENTITIES = frozenset({"aws_core__aws_account"})

#: ``<service>:<entity>``, both halves required, ``*`` and ``?`` the only glob characters (no character classes).
TYPE_PATTERN = r"^[a-z0-9*?-]+:[a-z0-9_*?]+$"
_TYPE_RE = re.compile(TYPE_PATTERN)

#: An account reference in a secret: a 12-digit id, or an ARN (checked further by ``account_id_of``).
ACCOUNT_REFERENCE_PATTERN = r"^([0-9]{12}|arn:.+)$"
_ACCOUNT_ID_RE = re.compile(r"^[0-9]{12}$")

#: What ``retire_within_selection: true`` waits on.
RETIRE_BLOCKER = "unified-systems-com/tap#1156"

#: Run-log codes (stable; the spec names the first two).
PATTERN_UNMATCHED = "SELECTION_PATTERN_UNMATCHED"
ACCOUNT_UNKNOWN = "SELECTION_ACCOUNT_UNKNOWN"
SELECTION_INVALID = "SELECTION_INVALID"


class SelectionError(Exception):
    """The selection is unusable. ``code`` is the run-log code the collector aborts with."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Selection:
    """The four selection keys of a secret, validated and normalised."""

    include_types: tuple[str, ...] = ()
    exclude_types: tuple[str, ...] = ()
    #: Normalised 12-digit ids, de-duplicated and sorted; empty means every account the run can reach.
    accounts_allowed: tuple[str, ...] = ()
    retire_within_selection: bool = False

    @property
    def narrows_types(self) -> bool:
        """Whether a type pattern was given (it may still select every entry; see ``TypeSelection``)."""
        return bool(self.include_types or self.exclude_types)

    @property
    def narrows_accounts(self) -> bool:
        return bool(self.accounts_allowed)

    def account_selected(self, account_id: str) -> bool:
        """True when ``account_id`` is a selected account (every account is, with no ``accounts_allowed``)."""
        return not self.accounts_allowed or account_id in self.accounts_allowed

    def matches(self, entry: Mapping[str, Any]) -> bool:
        """Whether one manifest entry is selected: an include match (or no include) and no exclude match."""
        service = str(entry["service"])
        entity = entity_of(entry)
        if self.include_types and not any(_matches(p, service, entity) for p in self.include_types):
            return False
        return not any(_matches(p, service, entity) for p in self.exclude_types)


@dataclass(frozen=True)
class TypeSelection:
    """The result of applying the type patterns to the manifest."""

    selected: list[dict[str, Any]]
    skipped: list[dict[str, Any]]

    @property
    def leaves_unselected(self) -> bool:
        """Whether any entry was left out. Only then does a run state no completeness
        (``req-aws-collector-selection-5``): a pattern like ``*:*`` selects everything and changes nothing."""
        return bool(self.skipped)


def entity_of(entry: Mapping[str, Any]) -> str:
    """The entry's entity type without the ``aws_core__aws_`` prefix: the pattern's entity half."""
    entity_type = str(entry["entity_type"])
    return entity_type.removeprefix(ENTITY_PREFIX)


def _matches(pattern: str, service: str, entity: str) -> bool:
    service_pattern, entity_pattern = pattern.split(":", 1)
    return fnmatchcase(service, service_pattern) and fnmatchcase(entity, entity_pattern)


def account_id_of(reference: str, partition: str | None = None) -> str:
    """Normalise one account reference (a 12-digit id or an ARN) to its 12-digit id.

    An ARN names an account by its account field (``arn:<partition>:iam::<account>:role/x``), except an
    Organizations account ARN (``arn:<partition>:organizations::<management account>:account/<org id>/<account>``),
    which names the account in its last segment. An ARN with a wildcard, an empty account field (an S3 bucket ARN)
    or, when ``partition`` is given, another partition is refused.
    """
    if not isinstance(reference, str):
        raise SelectionError(SELECTION_INVALID, "accounts_allowed holds a value that is not a string")
    text = reference.strip()
    if _ACCOUNT_ID_RE.match(text):
        return text
    if "*" in text or "?" in text:
        raise SelectionError(SELECTION_INVALID, f"accounts_allowed: {_shown(text)} contains a wildcard")
    parsed = parse_arn(text)
    if parsed is None:
        raise SelectionError(SELECTION_INVALID, f"accounts_allowed: {_shown(text)} is neither a 12-digit account id nor an ARN")
    if partition is not None and parsed.partition != partition:
        raise SelectionError(
            SELECTION_INVALID,
            f"accounts_allowed: {_shown(text)} is in partition {parsed.partition}, but this run is in {partition}",
        )
    if parsed.service == "organizations" and parsed.resource.startswith("account/"):
        last = parsed.resource.rsplit("/", 1)[-1]
        if _ACCOUNT_ID_RE.match(last):
            return last
        raise SelectionError(SELECTION_INVALID, f"accounts_allowed: {_shown(text)} names no member account")
    if not _ACCOUNT_ID_RE.match(parsed.account):
        raise SelectionError(SELECTION_INVALID, f"accounts_allowed: {_shown(text)} has no account field")
    return parsed.account


def _shown(text: str) -> str:
    """A reference as it is shown in a message: bounded, so a malformed value cannot flood the run log."""
    return repr(text if len(text) <= 80 else text[:77] + "...")


def parse_selection(data: Mapping[str, Any], *, partition: str | None = None) -> Selection:
    """Validate and normalise the selection keys of a secret's ``data``.

    ``partition`` is the run's partition when it is known (it is checked against an ARN's); a secret validated
    before the partition is resolved passes ``None`` and the collector checks again once it has one.
    Raises ``SelectionError`` for a pattern outside the grammar, an empty list, an account reference outside the
    forms, a contradiction with ``expected_account_id``, and ``retire_within_selection: true``.
    """
    include = _patterns(data, "include_types")
    exclude = _patterns(data, "exclude_types")
    accounts = _accounts(data, partition)
    retire = data.get("retire_within_selection", False)
    if not isinstance(retire, bool):
        raise SelectionError(SELECTION_INVALID, "retire_within_selection must be a boolean")
    if retire:
        raise SelectionError(
            SELECTION_INVALID,
            f"retire_within_selection: true is not available yet: core does not accept a selection block "
            f"({RETIRE_BLOCKER}), and a flag that is accepted and ignored would read as retirement being on",
        )
    expected = data.get("expected_account_id")
    if accounts and expected and expected not in accounts:
        raise SelectionError(
            SELECTION_INVALID,
            "expected_account_id is not in accounts_allowed: two statements about the same scope that disagree",
        )
    return Selection(include, exclude, accounts, retire)


def _patterns(data: Mapping[str, Any], key: str) -> tuple[str, ...]:
    if key not in data:
        return ()
    value = data[key]
    if not isinstance(value, list) or not value:
        raise SelectionError(SELECTION_INVALID, f"{key} must be a non-empty list")
    for pattern in value:
        if not isinstance(pattern, str) or not _TYPE_RE.match(pattern):
            raise SelectionError(
                SELECTION_INVALID,
                f"{key}: {_shown(str(pattern))} is not a type pattern (<service>:<entity>, lower case, * and ? only)",
            )
    return tuple(dict.fromkeys(value))


def _accounts(data: Mapping[str, Any], partition: str | None) -> tuple[str, ...]:
    if "accounts_allowed" not in data:
        return ()
    value = data["accounts_allowed"]
    if not isinstance(value, list) or not value:
        raise SelectionError(SELECTION_INVALID, "accounts_allowed must be a non-empty list")
    return tuple(sorted({account_id_of(ref, partition) for ref in value}))


def apply_type_selection(entries: Sequence[dict[str, Any]], selection: Selection) -> TypeSelection:
    """Split the manifest entries into selected and skipped, or stop the run on a pattern that matches nothing.

    Every include pattern and every exclude pattern must match at least one entry of the manifest: a typo, or a
    manifest rename, must not narrow (an include) or widen (an exclude) a run silently
    (``req-aws-collector-selection-4``). The check is against the whole manifest, before exclusion is applied.
    """
    for key, patterns in (("include_types", selection.include_types), ("exclude_types", selection.exclude_types)):
        for pattern in patterns:
            if not any(_matches(pattern, str(e["service"]), entity_of(e)) for e in entries):
                raise SelectionError(PATTERN_UNMATCHED, f"{key}: the pattern {pattern!r} matches no manifest entry")
    selected = [e for e in entries if e["entity_type"] in ANCHOR_ENTITIES or selection.matches(e)]
    selected_ids = {id(e) for e in selected}
    return TypeSelection(selected, [e for e in entries if id(e) not in selected_ids])


def parent_reads(selected: Iterable[Mapping[str, Any]]) -> list[str]:
    """The parent list calls selected entries fan out from (a ``per`` source), as ``<service>:<operation>``.

    A parent is read as the input of the child that needs it and emits nothing unless it is itself selected; the
    role's grant must include the call, so the echo names it (``req-aws-collector-selection-2`` and ``-9``). A ``per``
    block can nest (a grandparent is listed to reach the parent), can name its own service, and can be a fixed list of
    ``values`` (no call): the chain is walked the way the engine walks it (``source._iter_parents``).
    """
    found: set[str] = set()
    for entry in selected:
        per = (entry.get("source") or {}).get("per")
        service = str(entry["service"])
        while isinstance(per, Mapping):
            service = str(per.get("service", service))
            if "values" not in per and per.get("aws_op"):
                found.add(f"{service}:{per['aws_op']}")
            per = per.get("per")
    return sorted(found)


def echo(selection: Selection, *, entries_total: int, type_selection: TypeSelection) -> dict[str, Any]:
    """The effective selection as run-record data (``req-aws-collector-selection-9``): the patterns, the normalised
    account ids, and the counts. Scope, not secret material; no credential value is in it."""
    return {
        "include_types": list(selection.include_types),
        "exclude_types": list(selection.exclude_types),
        "accounts_allowed": list(selection.accounts_allowed),
        "entries_total": entries_total,
        "entries_selected": len(type_selection.selected),
        "entries_skipped": len(type_selection.skipped),
        "parent_reads": parent_reads(type_selection.selected),
    }
