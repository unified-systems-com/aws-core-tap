"""Completeness of an account-scoped listing (``req-aws-collector-reconcile``, aws-core-tap#43).

A retirement candidate (``tap_grid.candidates``) is a child the grid holds under a parent whose
listing this run **read to the end** and did not name it. Whether a listing was read to the end is a
fact about the walk, not about the collector's intentions, so it is measured here where the pages
are consumed and recorded — with a reason whenever it is not true — on the run's completeness
statement (``tap_grid.completeness``, ``req-grid-reconcile-evidence``).

This module holds the three things that statement needs and the collector should not improvise:

- :class:`ListingWalk` — what one walk of one listing established: did it end, was the credential
  allowed to ask, did the count the source reports agree with the count we saw, and did every item
  survive to the batch. The source drivers (:mod:`.source`, the IAM/S3 ``custom_fn`` s) fill it in
  while they consume pages; nothing else sets ``complete``.
- :func:`page_says_more` — the last page's own statement that it is not the last. A paginator that
  stopped on a page still carrying a continuation marker did not reach the end, however politely it
  returned.
- :func:`surface_statement` — the authored surface (``tap_grid/schemas/completeness.schema.json``),
  every negative or unknown attribute carrying its reason, which is the recorder's rule (-1).

Three states, never two: ``complete`` is ``True`` (read to the end), ``False`` (known not to have
been), or ``None`` (the walk cannot say). Only ``True`` licenses anything.

AWS makes no snapshot promise across the pages of a listing (IAM's ``ListRoles`` and S3's
``ListBuckets`` document none), so ``source_consistent`` is always ``"unknown"`` here, with the reason
that says so (``req-grid-reconcile-evidence-2``). The type's falsifier is what substitutes for it: a
candidate is only ever a question put to the source, never a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

#: Response keys whose presence on a page says another page exists. IAM answers ``IsTruncated`` and
#: ``Marker``; S3's ``ListBuckets`` echoes ``ContinuationToken`` only when more buckets remain; the
#: rest are the names other AWS list operations use, so a future entry on another service is judged
#: by the same rule rather than silently trusted.
_CONTINUATION_KEYS: tuple[str, ...] = ("Marker", "NextMarker", "NextToken", "NextContinuationToken", "ContinuationToken")

#: Error codes for "this credential may not ask", which is not the same as "the answer was empty".
_DENIED_CODES = frozenset({"AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "AuthFailure", "Forbidden"})
#: Error codes for a rate limit that outlasted the client's retries: the walk stopped, the source did
#: not say the list ended.
_THROTTLE_CODES = frozenset(
    {"Throttling", "ThrottlingException", "RequestLimitExceeded", "TooManyRequestsException", "SlowDown"}
)

#: Why source_consistent is never asserted for an AWS listing.
NO_SNAPSHOT_PROMISE = "no_promise: AWS documents no snapshot guarantee across the pages of this listing"


def page_says_more(page: Any) -> bool:
    """True when ``page`` itself reports that it is not the last.

    ``IsTruncated: true`` is IAM's statement; any continuation marker still present on the final page
    a paginator returned is the same statement in another dialect. A page that is not a mapping cannot
    say more, and is judged by its caller.
    """
    if not isinstance(page, dict):
        return False
    if page.get("IsTruncated") is True:
        return True
    return any(page.get(key) for key in _CONTINUATION_KEYS)


def error_code(exc: BaseException) -> str:
    """The AWS ``Error.Code`` off a ``ClientError``, or ``""``."""
    if isinstance(exc, ClientError):
        return str((exc.response or {}).get("Error", {}).get("Code", ""))
    return ""


@dataclass
class ListingWalk:
    """What one walk of one account-scoped listing established.

    Created by the collector before the source is driven, filled in by the source driver while it
    consumes pages, and turned into a completeness surface after the batch is submitted.
    """

    started: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished: datetime | None = None
    #: True only when the walk consumed the listing to a final page that did not say "more".
    complete: bool | None = None
    #: The credential was permitted to ask (False on a denial, None when unknown).
    authorized: bool | None = True
    #: Items the walk returned.
    count: int | None = None
    #: The total the source reports for the same relation (IAM ``GetAccountSummary``), when it offers one.
    count_reported: int | None = None
    #: Every listed item reached the batch. Cleared when an item could not be described and was dropped.
    admitted: bool = True
    #: Attribute -> "code: prose" for every attribute that is not true.
    reasons: dict[str, str] = field(default_factory=dict)

    def reached_end(self, count: int) -> None:
        """The walk consumed the listing to a final page with no continuation."""
        self.complete = True
        self.count = count
        self.finished = datetime.now(UTC)

    def stopped_short(self, count: int, why: str) -> None:
        """The walk returned, but the last page itself says there is more."""
        self.complete = False
        self.count = count
        self.finished = datetime.now(UTC)
        self.reasons["enumeration_complete"] = f"walk_capped: {why}"

    def drop(self, why: str) -> None:
        """An item was listed but could not be carried to the batch: the run did not process the list."""
        self.admitted = False
        self.reasons.setdefault("admitted", f"collection_partial: {why}")

    def fail(self, exc: BaseException) -> None:
        """The walk raised: record what that does and does not tell us. Nothing was enumerated."""
        self.finished = datetime.now(UTC)
        self.complete = False
        self.count = None
        self.admitted = False
        code = error_code(exc)
        if code in _DENIED_CODES:
            self.authorized = False
            self.reasons["scope_authorized"] = f"access_denied: {code}: the credential may not list this"
            self.reasons["enumeration_complete"] = f"access_denied: {code}: nothing was listed"
            self.reasons["admitted"] = f"access_denied: {code}: nothing to process"
        elif code in _THROTTLE_CODES:
            self.reasons["enumeration_complete"] = f"throttled: {code}: retries were exhausted before the end of the list"
            self.reasons["admitted"] = f"throttled: {code}: the walk did not finish"
        else:
            # A failure that is neither a denial nor a throttle does not say the credential is unable
            # to list: scope_authorized is not determinable, not false.
            self.authorized = None
            detail = code or type(exc).__name__
            self.reasons["scope_authorized"] = f"not_determinable: {detail}: the failure does not say whether listing is permitted"
            self.reasons["enumeration_complete"] = f"walk_failed: {detail}: the walk ended in an error"
            self.reasons["admitted"] = f"walk_failed: {detail}: the walk did not finish"


def surface_statement(
    walk: ListingWalk,
    *,
    relation: str,
    edge_type: str,
    subject: str,
    applied_batches: list[str],
) -> dict[str, Any]:
    """The authored completeness surface for one walked listing.

    ``subject`` is the parent's grid entity id (the AWS account node) and ``edge_type`` the containment
    edge its relation maps to, which is what candidate derivation fans out through.
    ``applied`` and ``reconcilable`` are derived by the recorder and must not be authored here.
    """
    reasons = dict(walk.reasons)
    reasons.setdefault("source_consistent", NO_SNAPSHOT_PROMISE)
    complete = walk.complete
    if complete is None:
        reasons.setdefault("enumeration_complete", "not_determinable: the walk cannot say whether it reached the end")
    authorized = walk.authorized
    if authorized is None:
        reasons.setdefault("scope_authorized", "not_determinable: permission for this listing is unknown")
    finished = walk.finished or datetime.now(UTC)
    surface: dict[str, Any] = {
        "relation": relation,
        "edge_type": edge_type,
        "subject": subject,
        "interval": {"first": walk.started.isoformat(), "last": finished.isoformat()},
        "scope_authorized": authorized,
        "enumeration_complete": complete,
        "source_consistent": "unknown",
        "admitted": walk.admitted,
        "count_observed": walk.count,
        "reasons": reasons,
        "applied_batches": list(applied_batches),
    }
    if walk.count_reported is not None:
        surface["count_reported"] = walk.count_reported
    return surface
