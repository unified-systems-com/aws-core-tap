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

**AwsOrganization has no falsifier — nothing contains it — but AwsAccount and
AwsOrganizationalUnit now do (tap-plugin-aws-core#50).** The distinction this section originally
drew (the collector's *own* account/region scope is unrecoverable-abort territory, per
``self._abort(..., "STS_UNREACHABLE"/"ACCOUNT_MISMATCH", ...)``, mirroring
``tap_plugin.github_core``'s foundation-abort pattern, ``specs/spec-github-core-reliability.md``
``req-github-core-reliability-absence``) still holds for the boto3 manifest engine's own
single-account scope. It does not apply to the Organizations tree: the credential's *own* account
identity is unconditional and proven once per collector run, but which OUs and accounts an
**organization** currently holds is exactly the kind of external, falsifiable fact
``req-grid-reconcile-falsifier`` exists for — an OU or account can be removed by someone else
entirely, observed only on the next run. ``OrganizationalUnitFalsifier`` and ``AccountFalsifier``
below are that falsifier, and ``collectors/boto3_collector/organizations.py`` is the collector
that gives them completeness surfaces to act on.

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
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from tap_plugin.aws_core.collectors.boto3_collector.credentials import (
    assume_role_session,
    build_session,
    caller_account_id,
    is_assumed_role,
    resolve_aws_secret,
    resolve_regions,
)
from tap_plugin.aws_core.collectors.boto3_collector.organizations import (
    INACTIVE_ACCOUNT_STATES,
    account_state,
    organization_id_of_account_arn,
)

from tap_grid.falsifiers import (
    UNDETERMINED,
    Candidate,
    Expected,
    Falsifier,
    FalsifyContext,
    Probe,
    Verdict,
    incomplete,
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
    """
    secret = resolve_aws_secret()
    data = dict(secret.data)
    regions = resolve_regions(data)
    if is_assumed_role(data):
        base = build_session(data["base"])
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


# ---------------------------------------------------------------------------
# The Organizations tree (tap-plugin-aws-core#50)
# ---------------------------------------------------------------------------

_ORGANIZATION_TYPE = "aws_core__aws_organization"
_OU_TYPE = "aws_core__aws_organizational_unit"

#: Organizations ``Error.Code`` values that mean "this credential is not in an organization",
#: which is not the same fact as "the thing is gone".
_NOT_IN_ORGANIZATION_CODES = frozenset({"AWSOrganizationsNotInUseException"})


@dataclass(frozen=True)
class _OrgReach:
    """What one batch's credential was proven able to speak about, read once per batch.

    ``AccountNotFoundException`` is documented as raised both when the account id does not exist in
    the organization AND when the account whose credentials made the call "isn't a member of an
    organization" — so a bare not-found says nothing until the credential is shown to be inside the
    very organization the candidate was recorded under. The same proof is why ``reach`` exists at
    all: it is the Organizations analogue of ``tap_plugin.github_core.reach``, reduced to one
    organization id and one root.
    """

    status: str  # "ok" | "forbidden" | "rate_limited" | "errored" | "scope_unknown"
    organization_id: str = ""
    #: The alphanumeric part of each root id (``r-ab12`` -> ``ab12``): AWS embeds it in every OU id
    #: of that root (``ou-ab12-xxxxxxxx``), which is how an OU is tied to an organization without
    #: the grid having to walk to its organization node.
    root_suffixes: frozenset[str] = frozenset()
    note: str = ""


def _finish(candidate: Candidate, expected: Expected, probe: Probe, *, note: str = "") -> Verdict:
    """``verdict_from_probe``, except that evidence core would REFUSE is answered instead.

    ``classify`` raises ``FalsifierError`` for a found probe with no source identity, or none owner
    while the grid holds one; an exception out of ``judge`` would take the rest of the batch's
    verdicts with it. Incomplete evidence is an ``UNDETERMINED``, never a destructive default.
    """
    why = incomplete(expected, probe)
    if why is not None:
        return _undetermined(candidate, "errored", why)
    return verdict_from_probe(candidate, expected, probe, note=note)


class _OrganizationsFalsifier(_AwsFalsifier):
    """Shared shape of the Organizations falsifiers: one ``organizations`` client and one proof of
    organization membership per batch, then one probe per candidate.

    The Organizations API is global: one endpoint per partition, no per-resource region. The client
    is built in the collector's own first region so that the endpoint (and with it the partition,
    e.g. ``organizations.us-gov-west-1`` for GovCloud) follows the credential exactly as the
    collector's does; ``region`` is injected by tests.
    """

    def __init__(
        self,
        session: ProbeSession | None = None,
        account_id: str | None = None,
        session_factory: Callable[[], tuple[ProbeSession, str]] | None = None,
        region: str | None = None,
    ) -> None:
        super().__init__(session, account_id, session_factory)
        self._region_name = region

    def _region(self) -> str:
        if self._region_name is None:
            self._region_name = resolve_regions(dict(resolve_aws_secret().data))[0]
        return self._region_name

    def judge(self, session: ProbeSession, account_id: str, candidate: Candidate) -> Verdict:
        return self.judge_all(session, account_id, [candidate])[0]

    def judge_all(self, session: ProbeSession, account_id: str, candidates: list[Candidate]) -> list[Verdict]:
        # The account-dimension scope check needs no organization read at all (it is this
        # plugin's single-account "reach", same as every other falsifier here) — apply it FIRST,
        # per candidate, so a batch of nothing but out-of-scope candidates never touches
        # Organizations, and only candidates that pass it pay for the one shared reach read.
        verdicts: dict[int, Verdict] = {}
        to_probe: list[tuple[int, Any, Candidate]] = []
        for index, candidate in enumerate(candidates):
            row = _row_of(candidate.entity_id)
            if row is None:
                verdicts[index] = _undetermined(candidate, "errored", "the grid row could not be read")
                continue
            scoped = self._scope_check(candidate, account_id, _dimensions_of(row).get("aws_account") or None)
            if scoped is not None:
                verdicts[index] = scoped
                continue
            to_probe.append((index, row, candidate))
        if to_probe:
            try:
                client = session.client("organizations", region_name=self._region())
                reach = self._read_reach(client)
            except Exception as exc:  # noqa: BLE001 — an unbuildable client is an answer, not a crash
                note = f"organizations client unavailable: {type(exc).__name__}"
                logger.warning("[b47d] %s: %s", type(self).__name__, note)
                reach = None
            for index, row, candidate in to_probe:
                if reach is None:
                    verdicts[index] = _undetermined(candidate, "errored", "organizations client unavailable")
                elif reach.status != "ok":
                    verdicts[index] = _undetermined(candidate, reach.status, reach.note)
                else:
                    verdicts[index] = self._judge_one(client, reach, row, candidate)
        return [verdicts[i] for i in range(len(candidates))]

    def _read_reach(self, client: Any) -> _OrgReach:
        """Prove the credential is inside an organization and can read its tree."""
        try:
            organization = (client.describe_organization().get("Organization")) or {}
            roots = client.list_roots().get("Roots") or []
        except ClientError as exc:
            code = error_code_of(exc)
            if code in _NOT_IN_ORGANIZATION_CODES:
                return _OrgReach("scope_unknown", note="this credential's account is not in an organization")
            status = probe_status_of(exc)
            reason = {"forbidden": "forbidden", "rate_limited": "rate_limited"}.get(status, "errored")
            return _OrgReach(reason, note=f"organization reach unproven: {code or type(exc).__name__}")
        except BotoCoreError as exc:
            return _OrgReach("errored", note=f"organization reach unproven: {type(exc).__name__}")
        suffixes = frozenset(
            str(r["Id"]).split("-", 1)[1] for r in roots if str(r.get("Id") or "").startswith("r-")
        )
        if not organization.get("Id") or not suffixes:
            return _OrgReach("errored", note="the organization read returned no organization id or no root")
        return _OrgReach("ok", organization_id=str(organization["Id"]), root_suffixes=suffixes)

    def _judge_one(self, client: Any, reach: _OrgReach, row: Any, candidate: Candidate) -> Verdict:
        raise NotImplementedError

    @staticmethod
    def _error_verdict(candidate: Candidate, expected: Expected, exc: Exception) -> Verdict:
        """The verdict for a failed probe call. Not-found is evidence only because ``reach`` proved
        the credential is in the same organization; every other failure is an ``UNDETERMINED``."""
        if isinstance(exc, ClientError):
            if error_code_of(exc) in _NOT_IN_ORGANIZATION_CODES:
                return _undetermined(candidate, "scope_unknown", "this credential's account is not in an organization")
            status = probe_status_of(exc)
            detail = NOT_FOUND_DETAIL if status == "not_found" else f"{error_code_of(exc)}: {exc}"
            return verdict_from_probe(candidate, expected, Probe(status=status, detail=detail))  # type: ignore[arg-type]
        return verdict_from_probe(candidate, expected, Probe(status="errored", detail=str(exc)))


class OrganizationalUnitFalsifier(_OrganizationsFalsifier):
    """``organizations:DescribeOrganizationalUnit`` then ``ListParents``; compare the OU id, its
    current parent and its name.

    An OU is contained by its parent (``PARTITIONED_INTO_OU``), so a candidate is an OU that a
    complete listing of its parent no longer names. Its source identity is the ``ou-…`` id. Its
    **owner** is its parent in AWS's terms — the root id for a top-level OU (the ``root_id`` the
    organization node carries), the parent OU's id otherwise. AWS has no operation that moves an OU,
    so a different owner is not something the API is expected to produce; it is compared anyway,
    because the comparison is what the verdict is defined as, and it costs one ``ListParents``.

    What "gone" means: ``OrganizationalUnitNotFoundException`` (an OU is deleted only when empty, so
    nothing it contained can be alive) is ``DROPPED_FROM_OBSERVATION``. A renamed OU
    (``RELOCATED(renamed)``) has its name updated and is not retired.

    The credential must first be proven to be inside the candidate's organization: the OU id
    embeds the root id it belongs to, and ``ListRoots`` must name that root.
    """

    def _judge_one(self, client: Any, reach: _OrgReach, row: Any, candidate: Candidate) -> Verdict:
        ou_id = str(getattr(row, "ou_id", "") or "")
        if not ou_id:
            return _undetermined(candidate, "scope_unknown", "the grid holds no ou_id for this OU")
        parts = ou_id.split("-")
        if len(parts) != 3 or parts[1] not in reach.root_suffixes:
            return _undetermined(
                candidate,
                "scope_unknown",
                f"this credential's organization has no root that OU {ou_id} belongs to: an absence here says "
                "nothing about another organization's OU",
            )
        expected = Expected(
            source_id=ou_id,
            owner=self._expected_parent(candidate),
            name=str(getattr(row, "name", "") or "") or None,
        )
        try:
            unit = client.describe_organizational_unit(OrganizationalUnitId=ou_id).get("OrganizationalUnit") or {}
            parents = client.list_parents(ChildId=ou_id).get("Parents") or []
        except (ClientError, BotoCoreError) as exc:
            return self._error_verdict(candidate, expected, exc)
        probe = Probe(
            status="found",
            source_id=str(unit.get("Id") or "") or None,
            owner=(str(parents[0].get("Id") or "") or None) if parents else None,
            name=str(unit.get("Name") or "") or None,
            detail="DescribeOrganizationalUnit 200",
        )
        return _finish(candidate, expected, probe)

    @staticmethod
    def _expected_parent(candidate: Candidate) -> str | None:
        """The parent's AWS id as the grid holds it, or None when it holds none (owner not compared)."""
        parent = _row_of(candidate.parent)
        kind = getattr(getattr(parent, "entity", None), "entity_type", "")
        if kind == _ORGANIZATION_TYPE:
            return str(getattr(parent, "root_id", "") or "") or None
        if kind == _OU_TYPE:
            return str(getattr(parent, "ou_id", "") or "") or None
        return None


class AccountFalsifier(_OrganizationsFalsifier):
    """``organizations:DescribeAccount``; compare the account id, its organization and its name.

    A candidate is an account the organization-wide ``ListAccounts`` (``ENROLLS_ACCOUNT``) no longer
    names. Its source identity is the 12-digit id and its **owner** is the organization: the
    ``o-…`` id embedded in the account's own ARN
    (``arn:<partition>:organizations::<mgmt>:account/<o-id>/<account id>``), compared with the
    ``organization_id`` of the organization node the candidate was recorded under.

    What "gone" means, and does not:

    - ``AccountNotFoundException`` is ``DROPPED_FROM_OBSERVATION``: the account left the organization
      (``RemoveAccountFromOrganization``) or AWS finally removed it after closure. It is the AWS
      account that still exists in the first case; what ends is this organization's observation.
    - A **closed or suspended** account is still listed and still describable (``State`` SUSPENDED,
      PENDING_CLOSURE or CLOSED) — it is present, its ``status`` is what changed. It is reported in
      the verdict's note and never retired here.
    - A **moved** account never reaches this falsifier: the membership listing is organization-wide,
      and ``MoveAccount`` does not change it. A move is a change of ``NESTED_UNDER_PARENT`` only.

    ``AccountNotFoundException`` is also documented as raised when the *calling* account is not in an
    organization, so nothing is concluded before ``_read_reach`` proves the credential is inside the
    organization the candidate was recorded under.
    """

    def _judge_one(self, client: Any, reach: _OrgReach, row: Any, candidate: Candidate) -> Verdict:
        member_id = str(getattr(row, "account_id", "") or "")
        if not member_id:
            return _undetermined(candidate, "scope_unknown", "the grid holds no account_id for this account")
        parent = _row_of(candidate.parent)
        recorded_org = str(getattr(parent, "organization_id", "") or "")
        if not recorded_org:
            return _undetermined(
                candidate, "scope_unknown", "the grid holds no organization id for the organization this account was enrolled under"
            )
        if recorded_org != reach.organization_id:
            return _undetermined(
                candidate,
                "scope_unknown",
                f"this credential is in organization {reach.organization_id}, not {recorded_org}: an absence "
                "here says nothing about that organization's accounts",
            )
        expected = Expected(source_id=member_id, owner=recorded_org, name=str(getattr(row, "name", "") or "") or None)
        try:
            account = client.describe_account(AccountId=member_id).get("Account") or {}
        except (ClientError, BotoCoreError) as exc:
            return self._error_verdict(candidate, expected, exc)
        state = account_state(account)
        joined = account.get("JoinedTimestamp")
        probe = Probe(
            status="found",
            source_id=str(account.get("Id") or "") or None,
            owner=organization_id_of_account_arn(str(account.get("Arn") or "")) or None,
            name=str(account.get("Name") or "") or None,
            created_at=joined if isinstance(joined, datetime) else None,
            detail=f"DescribeAccount 200 state={state or 'unreported'}",
        )
        note = (
            f"account is {state} but still listed by Organizations: present, not gone"
            if state in INACTIVE_ACCOUNT_STATES
            else ""
        )
        return _finish(candidate, expected, probe, note=note)


__all__ = [
    "NOT_FOUND_DETAIL",
    "AccountFalsifier",
    "OrganizationalUnitFalsifier",
    "SubnetFalsifier",
    "error_code_of",
    "probe_status_of",
]
