"""Falsifiers for storage + IAM (aws-core-tap#41, a slice of the falsification epic aws-core-tap#15).

A retirement candidate (``tap_grid.candidates``) is a child the grid holds under a parent whose
listing this run read completely and did not name it. Nothing is retired on that alone: a
**falsifier** — one per entity type, declared in ``[falsifiers]`` of ``tap-plugin.toml`` — probes
AWS for each candidate and hands what it found to ``tap_grid.falsifiers.verdict_from_probe``,
which derives the verdict. A successful API call is not a verdict; the identity and the owner are
compared, never the HTTP status line (``req-grid-reconcile-falsifier``). Authority stays off: the
verdicts are recorded on the run's lifecycle batch and the reconcile verb (tap#652) is what would
act on them.

Covers four types:

- **S3 Bucket** (``aws_core__aws_s3_bucket``) — ``head_bucket``. Per AWS's own ``HeadBucket``
  documentation: "If the bucket doesn't exist or you don't have permission to access it, the HEAD
  request returns a generic 400 Bad Request, 403 Forbidden, or 404 Not Found HTTP status code. A
  message body isn't included, so you can't determine the exception beyond these HTTP response
  codes." **404 is therefore just as ambiguous as 403 here** — 404 is NOT conclusive proof of
  absence on its own. Both status codes get the same tie-break: this account's own bucket
  inventory (``list_buckets`` / ``ListAllMyBuckets``, which needs no per-bucket permission).
  Present in it, the answer is a permission/visibility gap and the bucket stands; absent from it,
  it is read as gone. (400 is left as ``errored`` — already conservative, since it never becomes a
  retirement.) github_core's ``RepositoryFalsifier`` faced the analogous "a refusal and an absence
  look alike" problem for private GitHub repositories and resolved it with a probe of the
  containing repository (``tap_plugin.github_core.falsifiers._absence_verdict``); AWS gives an S3
  bucket no single parent to probe that way, hence the account-inventory tie-break instead.
- **IAM Role** (``aws_core__aws_iam_role``) — ``get_role``; ``NoSuchEntity``.
- **IAM User** (``aws_core__aws_iam_user``) — ``get_user``; ``NoSuchEntity``.
- **IAM Policy, customer-managed only** (``aws_core__aws_iam_policy``) — ``get_policy``;
  ``NoSuchEntity``. The model already carries ``is_aws_managed`` (aws-core-tap PR #23). AWS-managed
  policies are provisioned and retired by AWS, not this account, so their absence from a listing
  is never evidence of deletion; ``IamPolicyFalsifier`` refuses to probe one at all rather than
  spending an AWS call on a question that cannot come back positive.

**The account-match gate.** ``get_role`` / ``get_user`` / ``get_policy`` are looked up by
name/ARN within whichever AWS account the collector's credential currently resolves to. A
credential for account A asking about a role the grid recorded under account B does not merely
get ``NoSuchEntity`` — if account A happens to have its OWN, unrelated role of the same name, the
call SUCCEEDS and hands back a live ARN that has nothing to do with the object the grid recorded.
So the gate runs BEFORE any probe, not only on the error path: ``_account_gate`` resolves this
run's own AWS account (STS ``GetCallerIdentity``, ``credentials.caller_account_id`` — the same
call the collector itself uses to assert-on-land) once per batch and refuses the candidate outright
— without spending the AWS call at all — unless it matches the account segment of the row's own
ARN, AND (independently) the candidate's grid-recorded parent account, when a future containment
edge populates one — the object's own ARN and its containment parent are two different
provenance signals, and an inconsistency between them refuses rather than resolving itself in
whichever direction happens to let the probe proceed. A missing/malformed ARN account segment
refuses exactly like a mismatch (``FIELD_VALIDATION_SCHEMA`` does not constrain ARN shape on any
of the three ARN fields, so a malformed stored value is possible), and so does an unresolvable
caller account — a failed resolution is cached per batch exactly like a successful one, so an STS
outage costs one timeout for the whole batch, not one per candidate. This is deliberately
narrower than a general cross-account "reach" gate (see below): it only answers "was this
credential ever capable of finding this exact object", never "does this credential's grant still
cover it" (github_core's harder question).

**What can and cannot answer ``REIDENTIFIED`` (checked per type, not assumed uniformly).** S3
never can: bucket ARNs (``arn:aws:s3:::name``) carry no separate id, ever — a structural S3 limit.
Customer-managed IAM policies never can either: ``get_policy`` is looked up BY the full ARN
(including path), so the response's ``Arn`` is definitionally the one requested — there is no
other ARN it could disagree with. **IAM roles and users are different**: ``get_role`` /
``get_user`` look up BY NAME ONLY — the request carries no path — and IAM role/user names are
unique per account across every path, not per path. A role or user deleted and recreated under a
DIFFERENT path but the SAME name is found by the same ``RoleName``/``UserName`` lookup, with a
different full ARN (the path segment differs): a genuine, detectable ``REIDENTIFIED``. What
neither falsifier can detect is a delete+recreate under the SAME path: that yields the identical
ARN, so only AWS's own immutable ``RoleId`` / ``UserId`` (e.g. ``AROA...`` / ``AIDA...``) would
catch it, and the model does not currently carry that field (checked against
``tap_plugin/aws_core/models/iam_role.py`` / ``iam_user.py`` before writing this: only ``name`` /
the ARN field / ``path`` and a couple of type-specific fields). Adding a stable-id column is a
model change, outside this falsifier slice's scope — flagged in the PR as a genuinely open
follow-up (aws-core-tap#41), not guessed around by fabricating a scenario the AWS API cannot
actually produce.

Two things this module deliberately does NOT do, both flagged in aws-core-tap#41 as open beyond
this slice:

- It does not declare ``CONTAINMENT_EDGES`` on ``AwsAccount`` for these types.
  ``BELONGS_TO_ACCOUNT.edge.json`` — the only edge connecting an account-owned resource to its
  account — describes itself as "a reference, not containment: a resource shared through AWS RAM
  is used from other accounts, and an account's subtree can exceed the cascade cap." Treating it
  as containment here would contradict that and reproduce exactly the over-derivation
  aws-core-tap#15 warns against ("the enumeration unit in aws_core is exactly (account, region,
  entity type)"; one edge from the account fans out every child of every region on every surface).
  The real substrate — a scope node per account and region — is aws-core-tap#15's sub-issue 2 and
  is not built. Until it is, no candidate for any of these four types can be derived and none of
  this module is dispatched in production; it is registered in ``[falsifiers]`` so it is ready the
  moment that substrate lands, per ``req-grid-reconcile-falsifier-1`` (an unregistered type is
  simply not reconcilable, which is also a true and honest statement about these types today).
- It does not build AWS's equivalent of github_core's cross-account "reach" gate
  (``tap_plugin.github_core.reach``): aws-core-tap#15 names that question — whether an assumed
  role's own reach is observable at all — as open and explicitly scopes it as "resolve whether the
  reach is observable and record it, not build the judge." Inventing an answer here would be
  exactly that. The account-match gate above is narrower and answers a different, cheaper question
  (same account, not still-in-grant); S3's OWN 403/404 ambiguity gets its own narrow,
  self-contained tie-break (this account's own listing), not a general reach system.

Every probe is a single-object read of the source under this plugin's own collector credential
(``aws_core:boto_collector``, resolved here, never taken from the run context); no response body
is recorded — ``Probe.detail`` carries an error code or a status line only.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from tap_grid.falsifiers import (
    UNDETERMINED,
    Candidate,
    Expected,
    Falsifier,
    FalsifyContext,
    Probe,
    ProbeStatus,
    Verdict,
    verdict_from_probe,
)
from tap_grid.services import get_node
from tap_plugin.aws_core.collectors.boto3_collector.credentials import (
    assume_role_session,
    build_session,
    caller_account_id,
    is_assumed_role,
    resolve_aws_secret,
    resolve_regions,
)

logger = logging.getLogger(__name__)

#: What a probe needs of the client: a boto3 service client that raises ``ClientError`` /
#: ``BotoCoreError``.
ProbeClient = Any

#: Timeout for the account-match gate's STS call — cheap and read-only, but must not hang a
#: falsifier run indefinitely.
_CALLER_ACCOUNT_TIMEOUT_SECONDS = 10

# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

#: Mirrors ``tap_plugin.aws_core.collectors.boto3_collector.ledger._DENIED`` and
#: ``...hydrate._DENIED_CODES``. aws-core-tap#15 (proposed sub-issue 5) already names the
#: duplication between those two as a defect to fold into one shared classifier; this is a THIRD
#: reader of the same table, kept in the same shape on purpose rather than inventing a fourth,
#: divergent one. "403"/"401" are literal codes, not HTTP statuses: a bodyless operation like
#: ``HeadBucket`` reports only a bare numeric string in ``Error.Code``, never a named code.
_DENIED_CODES = frozenset(
    {
        "AccessDenied",
        "AccessDeniedException",
        "UnauthorizedOperation",
        "AuthFailure",
        "Forbidden",
        "403",
        "401",
    }
)
_THROTTLED_CODES = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "ThrottledException",
        "RequestThrottled",
        "RequestThrottledException",
        "RequestLimitExceeded",
        "TooManyRequestsException",
        "SlowDown",
        "429",
    }
)


def _is_absent_code(code: str) -> bool:
    """AWS's "not configured"/"not found" signal — shares the ledger/hydrate dialect
    (``NoSuch*`` / ``*NotFound*``), plus the bare ``"404"`` a bodyless operation reports (HTTP 404
    always means Not Found in REST semantics, whatever vocabulary the particular API uses for its
    named codes). This is a PROBE-status classification only: whether a ``"404"``/``not_found``
    status is then trusted as evidence of absence is a per-falsifier question — see
    ``S3BucketFalsifier``, which does not trust it alone."""
    return (
        code == "404"
        or code.startswith("NoSuch")
        or code.endswith(("NotFound", "NotFoundError"))
    )


def probe_status_of(exc: ClientError) -> tuple[ProbeStatus, str]:
    """The closed probe status a boto3 ``ClientError`` maps to, and the detail line for it.

    IAM's ``get_role`` / ``get_user`` / ``get_policy`` all raise ``NoSuchEntityException``
    (``Error.Code`` ``NoSuchEntity``), which ``_is_absent_code`` already covers. S3's
    ``head_bucket`` reports bare ``"404"``/``"403"`` with no named code at all — also covered,
    the latter by ``_DENIED_CODES``.
    """
    error = exc.response.get("Error") or {}
    code = str(error.get("Code") or "")
    detail = f"error code {code}" if code else f"{type(exc).__name__}: no error code"
    if code in _DENIED_CODES:
        return "forbidden", detail
    if code in _THROTTLED_CODES:
        return "rate_limited", detail
    if _is_absent_code(code):
        return "not_found", detail
    return "errored", detail


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _undetermined(candidate: Candidate, reason: str, note: str) -> Verdict:
    return Verdict(
        entity_id=candidate.entity_id,
        verdict=UNDETERMINED,
        reason=reason,
        surface=candidate.surface,
        note=note,
    )


def _row_of(entity_id: Any) -> Any | None:
    """The typed grid row behind an entity id through the service read, or None when it cannot be
    read (unknown id, unknown type, an edge)."""
    if entity_id is None:
        return None
    try:
        return get_node(entity_id)
    except Exception:  # noqa: BLE001 — a candidate the grid cannot show is answered, not raised
        logger.warning("[a3e1] falsifier could not read grid row %s", entity_id)
        return None


def _resolve_owner(candidate: Candidate) -> tuple[str | None, bool]:
    """``(owner, unreadable)`` for a candidate's parent.

    ``owner`` is the parent ``AwsAccount``'s ``account_id`` when the grid holds a parent and
    could read it, or None when there is legitimately no parent to compare against (Option A,
    matching github_core's ``Expected.owner`` convention: no parent on the grid means the owner
    is not compared, never a mismatch). ``unreadable`` is True ONLY when a parent WAS recorded
    but ``_row_of`` could not read it — a data problem the caller must treat as *worse* than "no
    owner recorded", never the same: a candidate that names a parent it then cannot produce is
    not evidence of anything, and a caller (the account-match gate) must refuse rather than
    silently read that failure as "nothing to compare".

    No containment edge reaches any of these four types today (see the module docstring), so
    ``candidate.parent`` is always None in production; read anyway so a future containment
    declaration over ``AwsAccount`` is honoured without a further change here.
    """
    if candidate.parent is None:
        return None, False
    parent = _row_of(candidate.parent)
    if parent is None:
        return None, True
    return str(getattr(parent, "account_id", "") or "") or None, False


#: AWS account ids are always exactly 12 digits — the one part of an ARN's shape this module
#: can validate without a service-specific parser.
_ACCOUNT_ID_RE = re.compile(r"^[0-9]{12}$")


def _arn_account(arn: str | None) -> str | None:
    """The account segment of an IAM ARN (``arn:partition:iam::account-id:resource``), or None
    when the string is not shaped like one — a full, validated parse, not a blind colon-split-
    and-index. Splitting alone would let a malformed or wrong-service stored value with an
    account-shaped SUBSTRING at the right position pass the account-match gate; this checks the
    literal ``arn:`` prefix, the ``iam`` service segment, and that the account segment is AWS's
    own 12-digit shape, closing that path.

    Used only for IAM ARNs (role/user/policy): S3 bucket ARNs have no account segment at all and
    are never passed here.
    """
    if not arn:
        return None
    parts = str(arn).split(":", 5)
    if len(parts) < 6 or parts[0] != "arn" or parts[2] != "iam":
        return None
    account = parts[4]
    return account if _ACCOUNT_ID_RE.match(account) else None


def _created_at(payload: Mapping[str, Any]) -> datetime | None:
    """boto3 hands back ``CreateDate`` as a real ``datetime`` already (unlike a JSON API's ISO
    string), so this is a type check, not a parse."""
    value = payload.get("CreateDate")
    return value if isinstance(value, datetime) else None


def _default_session() -> tuple[boto3.session.Session, str]:
    """The collector's own credential (``aws_core:boto_collector``, consumer-scoped), resolved
    fresh on every run — never taken from the run context. Both supported secret kinds are
    handled identically to the collector's own path (``credentials.py``): a static session, or a
    base session that assumes the declared role.

    Returns the session and the first region of the secret's declared scope. IAM is a global
    service; S3's ``HeadBucket`` and ``ListBuckets`` need no region-specific endpoint for what
    this module calls. ``req-aws-collector-regions`` covers the multi-region *collection* sweep;
    falsifying a candidate probes one already-named object, not a region.
    """
    secret = resolve_aws_secret()
    data = dict(secret.data)
    region = resolve_regions(data)[0]
    if is_assumed_role(data):
        base = build_session(data["base"])
        session = assume_role_session(base, data, region)
    else:
        session = build_session(data)
    return session, region


# ---------------------------------------------------------------------------
# The shared falsifier shape
# ---------------------------------------------------------------------------


class _AwsFalsifier(Falsifier):
    """One boto3 client per batch, resolved once and thrown away at the next run; fail closed on
    a credential that cannot be resolved.

    Deliberately carries no general cross-account "reach" gate (see the module docstring): that
    is an open design question this slice does not answer. It does carry the narrower
    account-match gate the IAM falsifiers use (``_caller_account``) — a different, cheaper
    question ("is this the right account to even ask") than reach's ("does the grant still
    cover it"). ``client`` / ``client_factory`` / ``caller_account`` are for tests; at runtime the
    client and the caller account are both resolved from ``session_factory`` (default: the
    collector's own credential).
    """

    #: The boto3 service name this falsifier's client speaks (``"s3"`` / ``"iam"``).
    SERVICE: str = ""

    def __init__(
        self,
        client: ProbeClient | None = None,
        client_factory: Callable[[], ProbeClient] | None = None,
        session_factory: Callable[[], tuple[Any, str]] | None = None,
        caller_account: str | None = None,
    ) -> None:
        self._client = client
        self._client_factory = client_factory
        self._session_factory = session_factory or _default_session
        #: True when this falsifier builds its own credential — the production case, and the
        #: only one where it may throw a session away between runs.
        self._owns_session = client is None and client_factory is None
        self._batch_id = ""
        #: The session/region behind ``self._client``, when it was built via
        #: ``session_factory`` — needed to mint the separate STS client the account-match gate
        #: uses. None for an injected ``client``/``client_factory`` (its credential's account is
        #: not observable from here, which is why the gate fails closed rather than assumes).
        self._session: Any = None
        self._region = ""
        #: A caller account handed in by a caller (tests) pins the answer and is never re-resolved.
        self._injected_caller_account = caller_account
        #: A caller account RESOLVED from the credential is scoped to the batch it was resolved
        #: for, matching every other per-run cache in this module. ``_caller_account_attempted_for``
        #: tracks whether resolution was ATTEMPTED this batch, independent of whether it
        #: succeeded: a failure is cached too, so an STS outage costs one timeout per batch, not
        #: one per candidate.
        self._resolved_caller_account: str | None = None
        self._caller_account_attempted_for = ""

    def _resolve_client(self) -> ProbeClient:
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                self._session, self._region = self._session_factory()
                self._client = self._session.client(
                    self.SERVICE, region_name=self._region
                )
        return self._client

    def _begin_run(self, batch_id: str) -> None:
        if batch_id == self._batch_id:
            return
        self._batch_id = batch_id
        if self._owns_session:
            self._client = None
            self._session = None

    def _caller_account(self) -> str | None:
        """This run's own AWS account id (STS ``GetCallerIdentity``), resolved ONCE per batch and
        cached whether it succeeds or fails — the account-match gate every IAM falsifier uses
        before trusting a ``NoSuchEntity`` as gone. None when it could not be resolved: an
        injected ``client`` with no session behind it (its credential's account is simply not
        observable this way), or STS itself failing. A falsifier that cannot prove which account
        it speaks for must not use this gate to promote an absence into a retirement — callers
        treat None the same as a proven mismatch, never as a pass.

        The failure case is cached too, not just success: an earlier version only cached a
        resolved account, so a batch hitting an STS outage repeated the call (and its timeout)
        once per candidate instead of failing closed once for the whole batch.
        """
        if self._injected_caller_account is not None:
            return self._injected_caller_account
        if self._caller_account_attempted_for == self._batch_id:
            return self._resolved_caller_account
        if self._session is None:
            self._resolved_caller_account = None
            self._caller_account_attempted_for = self._batch_id
            return None
        try:
            account = caller_account_id(
                self._session,
                self._region,
                timeout_seconds=_CALLER_ACCOUNT_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 — an unreadable caller identity is an answer, not a crash
            logger.warning(
                "[9c2e] %s: could not resolve the caller account: %s",
                type(self).__name__,
                exc,
            )
            account = None
        self._resolved_caller_account = account
        self._caller_account_attempted_for = self._batch_id
        return account

    def batch_falsify(
        self, candidates: Sequence[Candidate], context: FalsifyContext
    ) -> list[Verdict]:
        self._begin_run(context.batch_id)
        try:
            client = self._resolve_client()
        except Exception as exc:  # noqa: BLE001 — a missing credential is an answer, not a crash
            note = f"credential unavailable: {type(exc).__name__}"
            logger.warning("[c1a4] %s: %s", type(self).__name__, note)
            return [_undetermined(c, "errored", note) for c in candidates]
        return self.judge_all(client, list(candidates))

    def judge_all(
        self, client: ProbeClient, candidates: list[Candidate]
    ) -> list[Verdict]:
        return [self.judge(client, c) for c in candidates]

    def judge(self, client: ProbeClient, candidate: Candidate) -> Verdict:
        raise NotImplementedError

    def _from_error(
        self, candidate: Candidate, expected: Expected, exc: ClientError
    ) -> Verdict:
        status, detail = probe_status_of(exc)
        return verdict_from_probe(
            candidate, expected, Probe(status=status, detail=detail)
        )

    def _account_gate(
        self,
        candidate: Candidate,
        *,
        row_account: str | None,
        owner: str | None,
        owner_unreadable: bool,
    ) -> Verdict | None:
        """The account-match gate, run BEFORE any probe — not only before trusting an absence.

        A credential whose account does not match the object's own ARN account cannot answer
        ANY question about that object usefully: a ``found`` response under the wrong account
        is a DIFFERENT object that merely shares a name (IAM role/user/policy names are only
        unique per account, not globally), and comparing its live ARN to the grid's stored one
        would be exactly the false-``REIDENTIFIED``/false-``PRESENT_AT_PROBE`` shape an earlier
        version of this gate missed by only checking on the error path.

        ``owner`` (from ``_resolve_owner(candidate)``, the account a future containment edge
        would record on ``candidate.parent``) is checked too, independently of ``row_account``:
        the object's OWN ARN and the candidate's GRID-RECORDED parent are two different
        provenance signals, and an earlier version of this gate only checked the first. A
        candidate whose parent claims account B while its own stored ARN names account A is
        itself an inconsistency that must refuse, not resolve itself in whichever direction
        happens to let the probe proceed. ``owner_unreadable`` covers the case that check alone
        would miss: a candidate that NAMES a parent the grid then fails to read is worse than one
        naming no parent at all, and must refuse identically — treating an unreadable parent the
        same as "nothing recorded" would silently drop the very check it exists to make.

        Returns the refusal ``Verdict`` when the gate fails, or ``None`` when the probe may
        proceed — and in the refusal case, no AWS call is made at all.
        """
        caller_account = self._caller_account()
        if caller_account is None:
            return _undetermined(
                candidate,
                "scope_unknown",
                f"this credential's own AWS account could not be verified against this object's ARN account "
                f"({row_account}); without that proof, nothing this credential's IAM API returns — found or "
                "not — is comparable to the object the grid recorded",
            )
        if row_account is None:
            # A missing, malformed, or non-IAM-shaped account segment: FIELD_VALIDATION_SCHEMA
            # does not enforce ARN shape on any of the three ARN fields, so a row with a garbled
            # ARN is possible; `_arn_account` validates the shape rather than blindly indexing.
            return _undetermined(
                candidate,
                "scope_unknown",
                f"this object's own ARN carries no recognizable IAM account segment to verify against this "
                f"credential's account ({caller_account}); without that proof, nothing this credential's IAM "
                "API returns is comparable to the object the grid recorded",
            )
        if caller_account != row_account:
            return _undetermined(
                candidate,
                "scope_unknown",
                f"this credential's account ({caller_account}) does not match this object's ARN account "
                f"({row_account}); a role/user/policy of the same name in the WRONG account is a different "
                "object, and nothing this credential's IAM API returns about it is comparable to the one the "
                "grid recorded",
            )
        if owner_unreadable:
            return _undetermined(
                candidate,
                "scope_unknown",
                "this candidate names a containment parent the grid could not read; an unreadable recorded "
                "parent is a data problem, not the same as no parent recorded, and this candidate's owner "
                f"cannot be verified against this credential's account ({caller_account}) without it",
            )
        if owner is not None and owner != caller_account:
            return _undetermined(
                candidate,
                "scope_unknown",
                f"this object's own ARN account ({row_account}) matches this credential, but the candidate's "
                f"grid-recorded parent account ({owner}) does not; the object's ARN and its containment parent "
                "disagree about which account this is, and that inconsistency refuses rather than resolving "
                "itself in whichever direction happens to let the probe proceed",
            )
        return None

    @staticmethod
    def _from_transport_error(candidate: Candidate, exc: BotoCoreError) -> Verdict:
        return _undetermined(candidate, "errored", f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# IAM
# ---------------------------------------------------------------------------


class IamRoleFalsifier(_AwsFalsifier):
    """``get_role``; ``NoSuchEntity`` -> gone, gated by the account-match check (module docstring).

    Cannot answer ``REIDENTIFIED`` for a delete+recreate under the SAME path (module docstring):
    that yields an identical ARN. CAN answer it for a delete+recreate under a DIFFERENT path,
    same name: ``get_role`` looks up by ``RoleName`` alone.
    """

    SERVICE = "iam"

    def judge(self, client: ProbeClient, candidate: Candidate) -> Verdict:
        row = _row_of(candidate.entity_id)
        if row is None:
            return _undetermined(candidate, "errored", "the grid row could not be read")
        name = str(getattr(row, "name", "") or "")
        arn = str(getattr(row, "role_arn", "") or "")
        if not name or not arn:
            return _undetermined(
                candidate,
                "scope_unknown",
                "the grid holds no name or ARN for this IAM role",
            )
        owner, owner_unreadable = _resolve_owner(candidate)
        refusal = self._account_gate(
            candidate,
            row_account=_arn_account(arn),
            owner=owner,
            owner_unreadable=owner_unreadable,
        )
        if refusal is not None:
            return refusal
        expected = Expected(source_id=arn, owner=owner, name=name)
        try:
            result = client.get_role(RoleName=name)
        except ClientError as exc:
            return self._from_error(candidate, expected, exc)
        except BotoCoreError as exc:
            return self._from_transport_error(candidate, exc)
        role = result.get("Role") or {}
        probe = Probe(
            status="found",
            source_id=str(role.get("Arn") or "") or None,
            owner=_arn_account(role.get("Arn")),
            name=str(role.get("RoleName") or "") or None,
            created_at=_created_at(role),
            detail="200",
        )
        return verdict_from_probe(candidate, expected, probe)


class IamUserFalsifier(_AwsFalsifier):
    """``get_user``; ``NoSuchEntity`` -> gone, gated by the account-match check (module docstring).

    Cannot answer ``REIDENTIFIED`` for a delete+recreate under the SAME path (module docstring):
    that yields an identical ARN. CAN answer it for a delete+recreate under a DIFFERENT path,
    same name: ``get_user`` looks up by ``UserName`` alone.
    """

    SERVICE = "iam"

    def judge(self, client: ProbeClient, candidate: Candidate) -> Verdict:
        row = _row_of(candidate.entity_id)
        if row is None:
            return _undetermined(candidate, "errored", "the grid row could not be read")
        name = str(getattr(row, "name", "") or "")
        arn = str(getattr(row, "user_arn", "") or "")
        if not name or not arn:
            return _undetermined(
                candidate,
                "scope_unknown",
                "the grid holds no name or ARN for this IAM user",
            )
        owner, owner_unreadable = _resolve_owner(candidate)
        refusal = self._account_gate(
            candidate,
            row_account=_arn_account(arn),
            owner=owner,
            owner_unreadable=owner_unreadable,
        )
        if refusal is not None:
            return refusal
        expected = Expected(source_id=arn, owner=owner, name=name)
        try:
            result = client.get_user(UserName=name)
        except ClientError as exc:
            return self._from_error(candidate, expected, exc)
        except BotoCoreError as exc:
            return self._from_transport_error(candidate, exc)
        user = result.get("User") or {}
        probe = Probe(
            status="found",
            source_id=str(user.get("Arn") or "") or None,
            owner=_arn_account(user.get("Arn")),
            name=str(user.get("UserName") or "") or None,
            created_at=_created_at(user),
            detail="200",
        )
        return verdict_from_probe(candidate, expected, probe)


class IamPolicyFalsifier(_AwsFalsifier):
    """``get_policy``; ``NoSuchEntity`` -> gone (gated by the account-match check, module
    docstring). Customer-managed policies only.

    AWS-managed policies (``is_aws_managed=True``) are provisioned and retired by AWS, not this
    account: their absence from a listing is never evidence of deletion, so this falsifier
    refuses the candidate without spending an AWS call on it (never dispatches ``get_policy`` for
    one) — a falsifier for something that structurally cannot be absent is pointless work, not a
    fail-closed default. Also cannot answer ``REIDENTIFIED`` for a customer policy (module
    docstring): ``get_policy`` is looked up BY the full ``policy_arn``, so the response's ``Arn``
    is definitionally the one requested.
    """

    SERVICE = "iam"

    def judge(self, client: ProbeClient, candidate: Candidate) -> Verdict:
        row = _row_of(candidate.entity_id)
        if row is None:
            return _undetermined(candidate, "errored", "the grid row could not be read")
        if getattr(row, "is_aws_managed", False):
            return _undetermined(
                candidate,
                "scope_unknown",
                "AWS-managed policies are provisioned and retired by AWS, not this account; absence from a "
                "listing of them is never evidence of deletion, so this falsifier does not probe one",
            )
        arn = str(getattr(row, "policy_arn", "") or "")
        name = str(getattr(row, "name", "") or "")
        if not arn:
            return _undetermined(
                candidate, "scope_unknown", "the grid holds no ARN for this IAM policy"
            )
        owner, owner_unreadable = _resolve_owner(candidate)
        refusal = self._account_gate(
            candidate,
            row_account=_arn_account(arn),
            owner=owner,
            owner_unreadable=owner_unreadable,
        )
        if refusal is not None:
            return refusal
        expected = Expected(source_id=arn, owner=owner, name=name or None)
        try:
            result = client.get_policy(PolicyArn=arn)
        except ClientError as exc:
            return self._from_error(candidate, expected, exc)
        except BotoCoreError as exc:
            return self._from_transport_error(candidate, exc)
        policy = result.get("Policy") or {}
        probe = Probe(
            status="found",
            source_id=str(policy.get("Arn") or "") or None,
            owner=_arn_account(policy.get("Arn")),
            name=str(policy.get("PolicyName") or "") or None,
            created_at=_created_at(policy),
            detail="200",
        )
        return verdict_from_probe(candidate, expected, probe)


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------


class S3BucketFalsifier(_AwsFalsifier):
    """``head_bucket``; both the 404 AND the 403 case are resolved by this account's own
    ``list_buckets`` (module docstring: AWS's own ``HeadBucket`` documentation says neither
    status code is conclusive on its own).

    S3 bucket ARNs (``arn:aws:s3:::name``) are a pure function of the name and carry no account
    segment: a bucket deleted and recreated under the same name — by this account or, since S3
    bucket names are globally unique, by a stranger — is byte-identical to this falsifier. It can
    therefore never answer ``REIDENTIFIED`` for a bucket; that is a structural S3 limit
    (aws-core-tap#15: "that type should be armed last, if ever"), not a gap in this code.
    """

    SERVICE = "s3"

    #: Both status codes ``head_bucket`` uses for "gone or forbidden, indistinguishably"
    #: (module docstring). 400 is deliberately excluded: it already lands as ``errored`` via
    #: ``probe_status_of``, which is already conservative (never becomes a retirement).
    _AMBIGUOUS_STATUSES = frozenset({"not_found", "forbidden"})

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        #: This account's own bucket names (``ListAllMyBuckets``), cached per run — the tie-break
        #: needs at most one extra call for however many bucket candidates a run judges.
        self._own_buckets: frozenset[str] | None = None
        self._own_buckets_for = ""

    def _begin_run(self, batch_id: str) -> None:
        if batch_id != self._batch_id:
            self._own_buckets = None
            self._own_buckets_for = ""
        super()._begin_run(batch_id)

    def _own_bucket_names(self, client: ProbeClient) -> frozenset[str] | None:
        """This run's ``ListAllMyBuckets`` answer, or None when it could not be read (including a
        partial page) — which must never be read as an empty or complete account (the same
        "unobserved is not empty" rule github_core's reach walk applies to its own listing
        failures).

        An unparameterised ``list_buckets()`` call returns AWS's complete bucket inventory for an
        account at or under the default 10,000-bucket quota, or is rejected outright for an
        account with an approved quota above it (AWS's own ``ListBuckets`` documentation) — so a
        genuinely partial page should not normally occur here. It is still checked for, rather
        than assumed away: a response carrying a ``ContinuationToken`` is a partial page by
        AWS's own definition, and a partial page must never be read as this account's complete
        inventory.
        """
        if self._own_buckets is not None and self._own_buckets_for == self._batch_id:
            return self._own_buckets
        try:
            response = client.list_buckets()
        except (ClientError, BotoCoreError) as exc:
            logger.warning(
                "[8ad1] S3BucketFalsifier: list_buckets tie-break failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            return None
        if response.get("ContinuationToken"):
            logger.warning(
                "[3f0a] S3BucketFalsifier: list_buckets returned a ContinuationToken (a partial page); refusing "
                "to treat it as this account's complete bucket inventory"
            )
            return None
        if "Buckets" not in response or response.get("Buckets") is None:
            # A ``Buckets`` key present but empty (``[]``) is a genuine, positive "this account
            # owns zero buckets" observation and is trusted below. The key being ABSENT or None
            # entirely is a different thing — a malformed or incomplete response — and must not
            # collapse to the same empty inventory by way of `or []`'s silent default (the same
            # null-is-unobserved-vs-empty-is-observed distinction this module applies elsewhere).
            logger.warning(
                "[6b12] S3BucketFalsifier: list_buckets returned no Buckets key/value; refusing to treat this "
                "as a (possibly empty) complete inventory"
            )
            return None
        names = frozenset(str(b.get("Name") or "") for b in response["Buckets"])
        self._own_buckets, self._own_buckets_for = names, self._batch_id
        return names

    def judge(self, client: ProbeClient, candidate: Candidate) -> Verdict:
        row = _row_of(candidate.entity_id)
        if row is None:
            return _undetermined(candidate, "errored", "the grid row could not be read")
        name = str(getattr(row, "name", "") or "")
        arn = str(getattr(row, "bucket_arn", "") or "")
        if not name or not arn:
            return _undetermined(
                candidate,
                "scope_unknown",
                "the grid holds no name or ARN for this bucket",
            )
        owner, owner_unreadable = _resolve_owner(candidate)
        expected = Expected(source_id=arn, owner=owner, name=name)
        try:
            client.head_bucket(Bucket=name)
        except ClientError as exc:
            return self._judge_absence(
                client,
                candidate,
                expected,
                exc,
                name,
                owner_unreadable=owner_unreadable,
            )
        except BotoCoreError as exc:
            return self._from_transport_error(candidate, exc)
        probe = Probe(status="found", source_id=arn, name=name, detail="200")
        return verdict_from_probe(candidate, expected, probe)

    def _judge_absence(
        self,
        client: ProbeClient,
        candidate: Candidate,
        expected: Expected,
        exc: ClientError,
        name: str,
        *,
        owner_unreadable: bool,
    ) -> Verdict:
        status, detail = probe_status_of(exc)
        if status not in self._AMBIGUOUS_STATUSES:
            # A throttle, or an unclassified error (including the bare-400 case): no ambiguity
            # this falsifier resolves, no tie-break.
            return verdict_from_probe(
                candidate, expected, Probe(status=status, detail=detail)
            )
        # AWS's own HeadBucket documentation (module docstring): 404 and 403 are equally
        # ambiguous. The tie-break is this account's own bucket inventory, which needs no
        # per-bucket permission.
        names = self._own_bucket_names(client)
        if names is None:
            return _undetermined(
                candidate,
                "scope_unknown",
                f"head_bucket({name}) answered {status} ({detail}) — S3 documents this status as meaning either "
                "gone or merely not visible to this credential — and this account's own ListBuckets (the "
                "tie-break) could not be read either, so nothing here separates the two",
            )
        if name not in names:
            # The tie-break REQUIRES a verified owner match before an absence from THIS
            # credential's own inventory is read as evidence of anything: S3 bucket names are
            # global but not account-scoped, so "not in my ListBuckets" is equally what a
            # bucket genuinely owned by a DIFFERENT account looks like. Today `expected.owner`
            # is always None (no containment edge reaches this type yet — module docstring), so
            # this falsifier cannot currently prove ownership at all and this branch always
            # refuses; it is written as a positive requirement, not a check that is skipped
            # when there is nothing to check, so it stays correct the moment a future
            # containment edge starts populating `candidate.parent` (an unowned or
            # unverified-owner candidate must never be trusted, never only a mismatched one).
            # `owner_unreadable` (a parent WAS recorded but could not be read) refuses
            # identically to a missing owner, never more permissively: an unreadable parent is
            # a data problem, not the same as "nothing recorded".
            owner = expected.owner
            caller_account = self._caller_account()
            if (
                owner_unreadable
                or owner is None
                or caller_account is None
                or owner != caller_account
            ):
                return _undetermined(
                    candidate,
                    "scope_unknown",
                    f"head_bucket({name}) answered {status} and {name} is absent from this credential's own "
                    f"ListBuckets, but this bucket's owning account could not be verified (grid-recorded owner: "
                    f"{owner!r}, unreadable parent: {owner_unreadable}, this credential's account: "
                    f"{caller_account!r}); S3 bucket names are globally unique, so absence from one account's "
                    "inventory says nothing about a bucket that belongs to a different or unrecorded account",
                )
            return verdict_from_probe(
                candidate,
                expected,
                Probe(
                    status="not_found",
                    detail=f"{detail}; absent from this account's own ListBuckets",
                ),
            )
        return _undetermined(
            candidate,
            "forbidden",
            f"head_bucket({name}) answered {status} but {name} is present in this account's own ListBuckets: the "
            "bucket is not gone, only this credential's head_bucket permission on it",
        )


__all__ = [
    "IamPolicyFalsifier",
    "IamRoleFalsifier",
    "IamUserFalsifier",
    "S3BucketFalsifier",
    "probe_status_of",
]
