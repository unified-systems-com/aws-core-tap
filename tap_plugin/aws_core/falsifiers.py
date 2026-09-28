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

- **S3 Bucket** (``aws_core__aws_s3_bucket``) — ``head_bucket``. 404 is unambiguous; 403 is not —
  S3 answers 403 identically for a bucket that is gone and one this credential may not look at,
  by design (it will not confirm a private bucket's existence to a stranger). github_core's
  ``RepositoryFalsifier`` faced the same "a refusal and an absence look alike" problem for private
  GitHub repositories and resolved it with a probe of the containing repository
  (``tap_plugin.github_core.falsifiers._absence_verdict``). AWS gives an S3 bucket no single
  parent to probe that way, so the tie-break here is this account's own bucket inventory instead
  (``list_buckets`` / ``ListAllMyBuckets``, which needs no per-bucket permission): present in it,
  the 403 is a permission gap and the bucket stands; absent from it, the 403 is read as gone.
- **IAM Role** (``aws_core__aws_iam_role``) — ``get_role``; ``NoSuchEntity``.
- **IAM User** (``aws_core__aws_iam_user``) — ``get_user``; ``NoSuchEntity``.
- **IAM Policy, customer-managed only** (``aws_core__aws_iam_policy``) — ``get_policy``;
  ``NoSuchEntity``. The model already carries ``is_aws_managed`` (aws-core-tap PR #23). AWS-managed
  policies are provisioned and retired by AWS, not this account, so their absence from a listing
  is never evidence of deletion; ``IamPolicyFalsifier`` refuses to probe one at all rather than
  spending an AWS call on a question that cannot come back positive.

None of these four can answer ``REIDENTIFIED`` (checked, not assumed): each is identified by an
ARN that is a deterministic function of account + name (+ path), and the corresponding GET call
is looked up BY that same name — the response can never disagree with the request. S3 is
structurally this way for good (bucket ARNs carry no separate id, ever). IAM is different: AWS
does expose a genuinely immutable identifier separate from the ARN on each of these three objects
(``RoleId`` / ``UserId`` / ``PolicyId``, e.g. ``AROA...`` — changes on a delete+recreate under the
same name), but the model does not currently carry it (checked against
``tap_plugin/aws_core/models/iam_role.py`` / ``iam_user.py`` / ``iam_policy.py`` before writing
this: only ``name`` / the ARN field / ``path`` and a couple of type-specific fields). Adding a
stable-id column is a model change, outside this falsifier slice's scope — flagged in the PR as a
genuinely open follow-up (aws-core-tap#41), not guessed around by fabricating a scenario the AWS
API cannot actually produce.

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
  exactly that. ``_AwsFalsifier`` fails closed the simple way instead: ``forbidden`` stays
  ``UNDETERMINED(forbidden)``, never promoted to a retirement. S3's OWN ambiguity gets one narrow,
  self-contained tie-break (this account's own listing), not a general reach system.

Every probe is a single-object read of the source under this plugin's own collector credential
(``aws_core:boto_collector``, resolved here, never taken from the run context); no response body
is recorded — ``Probe.detail`` carries an error code or a status line only.
"""

from __future__ import annotations

import logging
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
    is_assumed_role,
    resolve_aws_secret,
    resolve_regions,
)

logger = logging.getLogger(__name__)

#: What a probe needs of the client: a boto3 service client that raises ``ClientError`` /
#: ``BotoCoreError``.
ProbeClient = Any

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
    named codes)."""
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


def _owner_of(candidate: Candidate) -> str | None:
    """The account id this candidate's parent names, when the grid holds a parent at all.

    No containment edge reaches any of these four types today (see the module docstring), so
    ``candidate.parent`` is always None in production; read anyway so a future containment
    declaration over ``AwsAccount`` is honoured without a further change here (Option A,
    matching github_core's ``Expected.owner`` convention: no parent on the grid means the owner
    is not compared, never a mismatch).
    """
    if candidate.parent is None:
        return None
    parent = _row_of(candidate.parent)
    if parent is None:
        return None
    return str(getattr(parent, "account_id", "") or "") or None


def _arn_account(arn: str | None) -> str | None:
    """The account segment of an ARN (``arn:partition:service:region:account:resource``), or None
    when the ARN carries none (S3 bucket ARNs have no account segment)."""
    if not arn:
        return None
    parts = str(arn).split(":")
    return parts[4] if len(parts) > 4 and parts[4] else None


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

    Deliberately carries no cross-account "reach" gate (see the module docstring): that is an
    open design question this slice does not answer. ``client`` / ``client_factory`` are for
    tests; at runtime the client is built from ``session_factory`` (default: the collector's own
    credential).
    """

    #: The boto3 service name this falsifier's client speaks (``"s3"`` / ``"iam"``).
    SERVICE: str = ""

    def __init__(
        self,
        client: ProbeClient | None = None,
        client_factory: Callable[[], ProbeClient] | None = None,
        session_factory: Callable[[], tuple[Any, str]] | None = None,
    ) -> None:
        self._client = client
        self._client_factory = client_factory
        self._session_factory = session_factory or _default_session
        #: True when this falsifier builds its own credential — the production case, and the
        #: only one where it may throw a session away between runs.
        self._owns_session = client is None and client_factory is None
        self._batch_id = ""

    def _resolve_client(self) -> ProbeClient:
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                session, region = self._session_factory()
                self._client = session.client(self.SERVICE, region_name=region)
        return self._client

    def _begin_run(self, batch_id: str) -> None:
        if batch_id == self._batch_id:
            return
        self._batch_id = batch_id
        if self._owns_session:
            self._client = None

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

    @staticmethod
    def _from_transport_error(candidate: Candidate, exc: BotoCoreError) -> Verdict:
        return _undetermined(candidate, "errored", f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# IAM
# ---------------------------------------------------------------------------


class IamRoleFalsifier(_AwsFalsifier):
    """``get_role``; ``NoSuchEntity`` -> gone.

    Cannot answer ``REIDENTIFIED`` (module docstring): ``role_arn`` (the model's only identity
    field, and its ``NATURAL_KEY``) is a deterministic function of account + path + name, and
    ``get_role`` is looked up BY that same name — the response's ``Arn`` can never disagree with
    the request.
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
        expected = Expected(source_id=arn, owner=_owner_of(candidate), name=name)
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
    """``get_user``; ``NoSuchEntity`` -> gone. Cannot answer ``REIDENTIFIED`` (module docstring):
    ``user_arn`` is a deterministic function of account + path + name, and ``get_user`` is looked
    up BY that same name."""

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
        expected = Expected(source_id=arn, owner=_owner_of(candidate), name=name)
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
    """``get_policy``; ``NoSuchEntity`` -> gone. Customer-managed policies only.

    AWS-managed policies (``is_aws_managed=True``) are provisioned and retired by AWS, not this
    account: their absence from a listing is never evidence of deletion, so this falsifier
    refuses the candidate without spending an AWS call on it (never dispatches ``get_policy`` for
    one) — a falsifier for something that structurally cannot be absent is pointless work, not a
    fail-closed default. Also cannot answer ``REIDENTIFIED`` for a customer policy (module
    docstring): ``policy_arn`` is a deterministic function of account + path + name.
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
        expected = Expected(
            source_id=arn, owner=_owner_of(candidate), name=name or None
        )
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
    """``head_bucket``; the 403/404 ambiguity resolved by this account's own ``list_buckets``.

    S3 bucket ARNs (``arn:aws:s3:::name``) are a pure function of the name and carry no account
    segment: a bucket deleted and recreated under the same name — by this account or, since S3
    bucket names are globally unique, by a stranger — is byte-identical to this falsifier. It can
    therefore never answer ``REIDENTIFIED`` for a bucket; that is a structural S3 limit
    (aws-core-tap#15: "that type should be armed last, if ever"), not a gap in this code.
    """

    SERVICE = "s3"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        #: This account's own bucket names (``ListAllMyBuckets``), cached per run — the 403
        #: tie-break needs at most one extra call for however many bucket candidates a run judges.
        self._own_buckets: frozenset[str] | None = None
        self._own_buckets_for = ""

    def _begin_run(self, batch_id: str) -> None:
        if batch_id != self._batch_id:
            self._own_buckets = None
            self._own_buckets_for = ""
        super()._begin_run(batch_id)

    def _own_bucket_names(self, client: ProbeClient) -> frozenset[str] | None:
        """This run's ``ListAllMyBuckets`` answer, or None when it could not be read — which must
        never be read as an empty account (the same "unobserved is not empty" rule
        github_core's reach walk applies to its own listing failures)."""
        if self._own_buckets is not None and self._own_buckets_for == self._batch_id:
            return self._own_buckets
        try:
            names = frozenset(
                str(b.get("Name") or "")
                for b in (client.list_buckets().get("Buckets") or [])
            )
        except (ClientError, BotoCoreError) as exc:
            logger.warning(
                "[8ad1] S3BucketFalsifier: list_buckets tie-break failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            return None
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
        expected = Expected(source_id=arn, owner=_owner_of(candidate), name=name)
        try:
            client.head_bucket(Bucket=name)
        except ClientError as exc:
            return self._judge_absence(client, candidate, expected, exc, name)
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
    ) -> Verdict:
        status, detail = probe_status_of(exc)
        if status != "forbidden":
            # A plain 404, a throttle, or an unclassified error: no ambiguity, no tie-break.
            return verdict_from_probe(
                candidate, expected, Probe(status=status, detail=detail)
            )
        # S3's specific ambiguity (module docstring): HeadBucket answers 403 identically whether
        # the bucket is gone or merely not ours to look at. The tie-break is this account's own
        # bucket inventory, which needs no per-bucket permission.
        names = self._own_bucket_names(client)
        if names is None:
            return _undetermined(
                candidate,
                "scope_unknown",
                f"head_bucket({name}) answered 403 — S3 returns 403 both for a bucket that is gone and for one "
                "this credential may not look at — and this account's own ListBuckets (the tie-break) could not "
                "be read either, so nothing here separates the two",
            )
        if name not in names:
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
            f"head_bucket({name}) answered 403 but {name} is present in this account's own ListBuckets: the "
            "bucket is not gone, only this credential's head_bucket permission on it",
        )


__all__ = [
    "IamPolicyFalsifier",
    "IamRoleFalsifier",
    "IamUserFalsifier",
    "S3BucketFalsifier",
    "probe_status_of",
]
