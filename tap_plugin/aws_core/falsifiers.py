"""Per-type falsifiers for aws_core (tap-plugin-aws-core#42) — the foundation.

A retirement candidate (``tap_grid.candidates``) is a child the grid holds under a parent
whose listing this run read completely and did not name it. Nothing is retired on that
alone: a **falsifier** — one per entity type, declared in ``[falsifiers]`` of
``tap-plugin.toml`` — probes AWS for each candidate and hands what it found to
``tap_grid.falsifiers.verdict_from_probe``, which derives the verdict. HTTP/API success is
not a verdict; the identity and the owning account are compared, never the response's mere
presence (``req-grid-reconcile-falsifier``). Authority stays off: this module never
tombstones, renames or ends an edge; the reconcile verb (core, ``req-grid-reconcile-verb``)
is what would act on a recorded verdict.

This mirrors ``tap_plugin.github_core.falsifiers`` (github-core#151) but is simpler for one
concrete reason: ``Boto3Collector`` is **single-account** ("manifest-driven, single account,
no deletes" — its own docstring). A GitHub App installation can see a *subset* of an
account's repositories, which is why github_core needs a whole ``Reach`` abstraction
(``tap_plugin.github_core.reach``) to judge whether a 404 is trustworthy. aws_core's
collector credential resolves to exactly ONE AWS account via STS ``GetCallerIdentity``
(``collectors/boto3_collector/collector.py``), and every node it writes is stamped with
that account on ``dimensions["aws_account"]``
(``collectors/boto3_collector/collector.py``, the ``dimensions = {"cloud": "aws",
"aws_account": account_id, "aws_region": region_label}`` block). So the reach question
collapses to one equality check: does the falsifier's OWN resolved credential account match
the candidate's recorded account? A mismatch means this credential cannot speak to this
candidate's absence at all (``scope_unknown``), the same refusal ``Reach.holds_repository``
would produce for an out-of-reach repository, without needing the full apparatus.

**Known limitation, not fixed here: a revoked AWS RAM share can misread as deletion.** The
"single-account" framing above is only exactly true for a resource this account owns outright.
AWS RAM lets a subnet (among other types) be *shared into* an account that does not own it; a
shared subnet still appears in this credential's own ``DescribeSubnets`` listing, so the
collector still writes it with ``dimensions["aws_account"]`` set to the *observing* account (the
caller identity), not the true ``OwnerId`` — which ``_scope_check`` never sees, since it compares
against the dimension, not the probe response. If the share is later revoked rather than the
subnet deleted, this credential starts getting ``InvalidSubnetID.NotFound`` for a subnet that
still exists in its owner's account, and nothing here tells that apart from a real deletion —
the same "404 means gone OR means access narrowed" ambiguity ``tap_plugin.github_core.reach``
exists to resolve, unresolved here. Closing it for real needs an AWS-side reach concept (cross-
referencing RAM's own share state, or comparing the probe's ``OwnerId`` against the resolved
credential account rather than against the collector's stamped dimension) — a bigger, separate
piece of work, named so the gap is not mistaken for an oversight.

**AwsAccount and AwsOrganization have no falsifier, on purpose.** ``Boto3Collector.run()``
already treats credential/region-scope/account-identity failure as an *unrecoverable*
condition — ``self._abort(..., "STS_UNREACHABLE", ...)`` /
``self._abort(..., "ACCOUNT_MISMATCH", ...)`` — which is exactly
``tap_plugin.github_core``'s "foundation" layer
(``specs/spec-github-core-reliability.md``, ``req-github-core-reliability-absence``: a
foundation failure aborts the run rather than degrading one surface). An account the
collector's own credential cannot see is a collection-configuration problem to fix, not a
retirement candidate to probe. ``AwsOrganization`` additionally has **no collector at all
yet** (design vocabulary only — ``specs/spec-aws-core-v0.md``, ``req-aws-core-organizations``:
"no collector emits them yet"), so it can never produce a completeness surface for a
candidate to come from in the first place.

**Why Subnet is the one concrete falsifier here — not VPC.** The task that opened this
foundation (tap-plugin-aws-core#42) suggested VPC, "given it already has SOME cascade
wiring." Checking that wiring against how core actually consumes it
(``tap_plugins/validate/service.py::_check_falsifier_coverage``, which runs at the ``loads``
level and — since every plugin repo's CI runs ``validate_plugin --strict`` — turns its
WARNING into a hard CI failure) shows the wiring points the other way: a **candidate** is a
child the grid holds under a parent whose listing did not name it, so ``CONTAINMENT_EDGES``
on a PARENT makes its declared edge TARGETS reconcilable, never the parent itself.
``Vpc.CONTAINMENT_EDGES == ("PARTITIONED_INTO_SUBNET__aws_core",)`` and that edge's target is
``aws_core__aws_subnet`` (``edges/PARTITIONED_INTO_SUBNET.edge.json``) — so **Subnet**, not
VPC, is the one entity type this plugin's own existing containment declaration already marks
reconcilable. Nothing today makes VPC itself a containment target (see
``models/aws_account.py`` / ``models/aws_organization.py`` for why neither Account nor
Organization can be, without contradicting their own already-documented design), so a
``VpcFalsifier`` would be registered infrastructure nothing ever calls — exactly the "just
plumbing with nothing using it" this foundation is supposed to avoid, and it would leave the
coverage check's one real warning (``aws_core__aws_subnet is a containment target and
declares no [falsifiers] row``) unaddressed, redding ``validate_plugin --strict`` the moment
``requires_tap`` moves to a core release that carries that check (it does not exist at the
``>=0.1.5`` floor this plugin pinned before this PR). ``SubnetFalsifier`` clears it.

**REIDENTIFIED is structurally rare for an AWS-id-keyed type, and the tests still cover it.**
``DescribeSubnets(SubnetIds=[subnet_id])`` looks up by AWS's own opaque, non-reused resource
id — the same string the grid's ``NATURAL_KEY`` rests on — so a "found" response naming a
*different* id is not a shape AWS's real API produces for this call. ``classify()`` (core)
still handles it generically from whatever ``Expected``/``Probe`` a falsifier hands it, so the
fake-source test exercises the classification wiring, not a claim about AWS's real behaviour.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from tap_plugin.aws_core.collectors.boto3_collector.credentials import (
    assume_role_session,
    base_creds,
    build_session,
    caller_account_id,
    is_assumed_role,
    resolve_aws_secret,
    resolve_partition,
    resolve_regions,
)

from tap_grid.falsifiers import (
    Candidate,
    Expected,
    Falsifier,
    FalsifyContext,
    Probe,
    UNDETERMINED,
    Verdict,
    verdict_from_probe,
)
from tap_grid.services import get_node

logger = logging.getLogger(__name__)

#: What a probe needs of the session: a boto3 ``Session`` whose ``.client(service,
#: region_name=...)`` returns an authenticated client. Injected by tests.
ProbeSession = Any

#: The self-test / STS reachability timeout the collector itself uses
#: (``Boto3Collector.SELF_TEST_LIVE_CHECK_TIMEOUT_SECONDS``); a falsifier is not the collector
#: run, so this is a plain module constant rather than importing the collector class.
_STS_TIMEOUT_SECONDS = 10

#: Free text recorded when a probe found nothing at the id the grid holds.
NOT_FOUND_DETAIL = "the AWS API reports no such resource at this id"


def _default_session() -> tuple[ProbeSession, str]:
    """The collector's own credential, resolved from the secret store, and the AWS account it
    resolves to (via STS ``GetCallerIdentity`` — the same call ``Boto3Collector.run()`` makes
    before any resource read).

    Both are needed together: the session probes, the account id is what every candidate's
    ``aws_account`` dimension is checked against (this plugin's single-account "reach").

    Runs the same ``resolve_partition`` gate ``Boto3Collector.run()`` does (mixed-partition
    regions, a declared-partition mismatch, an unsupported partition, or — on the assumed-role
    kind — a ``role_arn`` in a different partition than the regions or a wrong
    ``expected_account_id``) before this identity ever reaches AWS. A falsifier resolves its
    own credential independently of any collector run, so a secret edited to something
    partition-inconsistent between runs must be refused here too, not only at collection time —
    a raised ``CredentialError`` is caught by ``_AwsFalsifier.batch_falsify`` and answered as
    ``UNDETERMINED(errored)`` for every candidate, the same as any other credential failure.
    """
    secret = resolve_aws_secret()
    data = dict(secret.data)
    regions = resolve_regions(data)
    resolve_partition(data, regions)
    if is_assumed_role(data):
        base = build_session(base_creds(data))
        session = assume_role_session(
            base, data, regions[0], timeout_seconds=_STS_TIMEOUT_SECONDS
        )
    else:
        session = build_session(data)
    account_id = caller_account_id(session, regions[0], timeout_seconds=_STS_TIMEOUT_SECONDS)
    return session, account_id


#: AWS ``Error.Code`` values this falsifier layer recognises as "the object is gone", beyond the
#: generic ``*.NotFound`` / ``*NotFoundException`` shapes every service follows. ``NoSuchBucket``
#: is S3's own not-found code — named here, not only in a future S3 falsifier, so every
#: ``_AwsFalsifier`` subclass gets it for free.
_NOT_FOUND_CODES = frozenset({"ResourceNotFoundException", "NoSuchBucket"})
#: AWS ``Error.Code`` values recognised as "this credential may not look", not "it is gone".
_FORBIDDEN_CODES = frozenset({"UnauthorizedOperation", "AccessDenied", "AccessDeniedException"})
#: AWS ``Error.Code`` values recognised as a rate limit rather than a real answer.
_RATE_LIMIT_CODES = frozenset(
    {"RequestLimitExceeded", "Throttling", "ThrottlingException", "TooManyRequestsException"}
)


def error_code_of(exc: ClientError) -> str:
    """The AWS ``Error.Code`` off a ``ClientError``'s response, or ``""`` when absent."""
    return str((exc.response or {}).get("Error", {}).get("Code", ""))


def probe_status_of(exc: Exception) -> str:
    """The closed probe status an AWS API failure maps to.

    A ``*.NotFound`` / ``*NotFoundException`` code (every AWS service's own convention for "no
    such resource at this id") is the only ``not_found``; a credential refusal is
    ``forbidden``; a rate limit is named as such; everything else — including any
    ``BotoCoreError`` (network, timeout, malformed response) — is ``errored``: the probe could
    not answer, never guessed at.
    """
    if isinstance(exc, ClientError):
        code = error_code_of(exc)
        if code in _NOT_FOUND_CODES or code.endswith(".NotFound") or code.endswith("NotFoundException"):
            return "not_found"
        if code in _FORBIDDEN_CODES:
            return "forbidden"
        if code in _RATE_LIMIT_CODES:
            return "rate_limited"
        return "errored"
    return "errored"


def _undetermined(candidate: Candidate, reason: str, note: str) -> Verdict:
    return Verdict(
        entity_id=candidate.entity_id, verdict=UNDETERMINED, reason=reason, surface=candidate.surface, note=note
    )


def _row_of(entity_id: Any) -> Any | None:
    """The typed grid row behind an entity id, or None when it cannot be read (unknown id,
    unknown type, an edge) — answered, never raised, the same discipline
    ``tap_plugin.github_core.falsifiers._row_of`` uses."""
    if entity_id is None:
        return None
    try:
        return get_node(entity_id)
    except Exception:  # noqa: BLE001 — a candidate the grid cannot show is answered, not raised
        logger.warning("[a1f2] falsifier could not read grid row %s", entity_id)
        return None


def _dimensions_of(row: Any) -> dict[str, str]:
    """The entity's own dimensions dict (``{"cloud": "aws", "aws_account": ..., "aws_region":
    ...}`` as the collector stamps it), or ``{}`` when the row carries none."""
    entity = getattr(row, "entity", None)
    dimensions = getattr(entity, "dimensions", None)
    return dict(dimensions) if isinstance(dimensions, dict) else {}


class _AwsFalsifier(Falsifier):
    """The shared shape: one credential per batch, one verdict per candidate, fail closed.

    ``session``/``account_id`` are injected by tests; at runtime both are resolved from the
    collector's own secret on the first batch of a run. A credential that cannot be resolved
    answers ``UNDETERMINED(errored)`` for every candidate rather than raising.
    """

    def __init__(
        self,
        session: ProbeSession | None = None,
        account_id: str | None = None,
        session_factory: Callable[[], tuple[ProbeSession, str]] | None = None,
    ) -> None:
        self._session = session
        self._account_id = account_id
        self._session_factory = session_factory or _default_session
        #: True when this falsifier owns (resolved) its own credential, which is the production
        #: case and the only one where a new run may throw it away and re-resolve — an
        #: injected credential's lifetime belongs to its caller (a test).
        self._owns_session = session is None and account_id is None
        self._batch_id = ""

    def _resolve(self) -> tuple[ProbeSession, str]:
        if self._session is None or self._account_id is None:
            session, account_id = self._session_factory()
            self._session, self._account_id = session, account_id
        return self._session, self._account_id

    def _begin_run(self, batch_id: str) -> None:
        """A session this falsifier owns is thrown away between runs, so a later run
        re-resolves the credential rather than reusing a stale one (mirrors
        ``_GithubFalsifier._begin_run``)."""
        if batch_id == self._batch_id:
            return
        self._batch_id = batch_id
        if self._owns_session:
            self._session = None
            self._account_id = None

    def batch_falsify(self, candidates: Sequence[Candidate], context: FalsifyContext) -> list[Verdict]:
        self._begin_run(context.batch_id)
        try:
            session, account_id = self._resolve()
        except Exception as exc:  # noqa: BLE001 — a missing credential is an answer, not a crash
            note = f"credential unavailable: {type(exc).__name__}"
            logger.warning("[7c3e] %s: %s", type(self).__name__, note)
            return [_undetermined(c, "errored", note) for c in candidates]
        return self.judge_all(session, account_id, list(candidates))

    def judge_all(self, session: ProbeSession, account_id: str, candidates: list[Candidate]) -> list[Verdict]:
        return [self.judge(session, account_id, c) for c in candidates]

    def judge(self, session: ProbeSession, account_id: str, candidate: Candidate) -> Verdict:
        raise NotImplementedError

    def _scope_check(self, candidate: Candidate, account_id: str, expected_account: str | None) -> Verdict | None:
        """None when it is safe to probe; an ``UNDETERMINED(scope_unknown)`` verdict when this
        credential's own account does not match the candidate's recorded account — the
        single-account analogue of ``_GithubFalsifier._absence_verdict``'s reach check. A
        candidate with no recorded account (an old write predating the dimension, or a design
        row AWS never minted) cannot be scope-checked and is refused the same way.

        Does NOT protect against a revoked AWS RAM share reading as a deletion — see the module
        docstring's "Known limitation" paragraph. This compares the falsifier's resolved account
        against the OBSERVING account the collector stamped, never the probe's own ``OwnerId``.
        """
        if not expected_account:
            return _undetermined(
                candidate, "scope_unknown", "the grid holds no aws_account dimension for this resource"
            )
        # Fail CLOSED on an empty account_id too, not just a mismatched one: `_resolve` only
        # short-circuits re-resolution on `is None` (`credentials.py::caller_account_id` returns
        # a 12-digit string or the caller already turned the exception into UNDETERMINED, so ""
        # should not occur in production) — but a falsifier is instantiated with an explicit
        # `account_id=""` by nothing today, and this guard must not silently trust that credential
        # if one ever were.
        if not account_id or account_id != expected_account:
            return _undetermined(
                candidate,
                "scope_unknown",
                f"this credential resolves to account {account_id or '<empty>'}, not {expected_account}: an "
                "absence here says nothing about the resource's own account",
            )
        return None


class SubnetFalsifier(_AwsFalsifier):
    """``ec2:DescribeSubnets(SubnetIds=[subnet_id])`` in the candidate's own region; compare
    AWS's ``SubnetId`` and ``OwnerId``.

    Identity is the subnet id itself (the grid's ``NATURAL_KEY``), so a ``not_found`` from this
    call is unambiguous: AWS's ``InvalidSubnetID.NotFound`` names the exact id that stopped
    existing, not a private object this credential cannot see (there is no cross-account
    visibility question once the account check has already passed). This is the type
    ``Vpc.CONTAINMENT_EDGES`` already marks reconcilable — see the module docstring's "Why
    Subnet, not VPC" for the coverage-check evidence.
    """

    def judge(self, session: ProbeSession, account_id: str, candidate: Candidate) -> Verdict:
        row = _row_of(candidate.entity_id)
        if row is None:
            return _undetermined(candidate, "errored", "the grid row could not be read")
        subnet_id = str(getattr(row, "subnet_id", "") or "")
        if not subnet_id:
            return _undetermined(candidate, "scope_unknown", "the grid holds no subnet_id for this subnet")
        dimensions = _dimensions_of(row)
        region = dimensions.get("aws_region", "")
        expected_account = dimensions.get("aws_account") or None
        if not region or region == "global":
            return _undetermined(candidate, "scope_unknown", "the grid holds no region for this subnet")
        scoped = self._scope_check(candidate, account_id, expected_account)
        if scoped is not None:
            return scoped
        expected = Expected(
            source_id=subnet_id, owner=expected_account, name=str(getattr(row, "name", "") or "") or None
        )
        # Client construction is INSIDE the try: botocore can raise while building a client
        # (bad region name, broken config) with no network call made yet, and that must fail
        # this one candidate closed, never escape judge() and take the rest of the batch's
        # verdicts down with it (judge_all is a plain list comprehension over judge()).
        try:
            client = session.client("ec2", region_name=region)
            result = client.describe_subnets(SubnetIds=[subnet_id])
        except ClientError as exc:
            status = probe_status_of(exc)
            detail = NOT_FOUND_DETAIL if status == "not_found" else f"{error_code_of(exc)}: {exc}"
            return verdict_from_probe(candidate, expected, Probe(status=status, detail=detail))  # type: ignore[arg-type]
        except BotoCoreError as exc:
            return verdict_from_probe(candidate, expected, Probe(status="errored", detail=str(exc)))
        subnets = result.get("Subnets") or []
        if not subnets:
            # A successful, empty response for an id filter: some services answer this way
            # instead of raising NotFound. Same meaning as the exception path.
            return verdict_from_probe(candidate, expected, Probe(status="not_found", detail=NOT_FOUND_DETAIL))
        found = subnets[0]
        found_id = str(found.get("SubnetId") or "") or None
        found_owner = str(found.get("OwnerId") or "") or None
        name = next(
            (str(tag.get("Value") or "") for tag in found.get("Tags", []) if tag.get("Key") == "Name"),
            None,
        )
        probe = Probe(
            status="found",
            source_id=found_id,
            # Compared only when the grid holds an owner (Option A, the same convention core's
            # own owner_not_compared reading applies) — every subnet candidate here has one,
            # since _scope_check already refused a candidate with no aws_account dimension.
            owner=found_owner if expected.owner is not None else None,
            name=name,
            detail="DescribeSubnets 200",
        )
        return verdict_from_probe(candidate, expected, probe)


__all__ = [
    "NOT_FOUND_DETAIL",
    "SubnetFalsifier",
    "error_code_of",
    "probe_status_of",
]
