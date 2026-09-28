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

**Which types are registered, and why some are ahead of a containment path.** The foundation
(tap-plugin-aws-core#42) registered Subnet alone, because
``Vpc.CONTAINMENT_EDGES == ("PARTITIONED_INTO_SUBNET__aws_core",)`` and that edge's target is
``aws_core__aws_subnet`` (``edges/PARTITIONED_INTO_SUBNET.edge.json``): a **candidate** is a child
the grid holds under a parent whose listing did not name it, so ``CONTAINMENT_EDGES`` on a PARENT
makes its declared edge TARGETS reconcilable, never the parent itself
(``tap_plugins/validate/service.py::_check_falsifier_coverage``). tap-plugin-aws-core#43 adds the
other compute + network types beside it — ``VpcFalsifier``, ``Ec2InstanceFalsifier``,
``SecurityGroupFalsifier`` — **registered ahead of a containment path**: no edge names them as a
target yet (``BELONGS_TO_ACCOUNT`` is a reference, not containment; ``RESIDES_IN_VPC`` /
``RESIDES_IN_SUBNET`` run child -> parent, which ``tap_grid.candidates`` cannot fan out along), so
today they are exercised by tests only, exactly as Subnet is until a collector run produces
completeness statements. They are cheap to carry, become live the moment a containment edge
reaches them, and an extra ``[falsifiers]`` row never trips the coverage check (it warns only on
a *missing* row). Reversing ``RESIDES_IN_*`` into parent -> child edges purely so cascade can walk
them would state one relationship twice in opposite directions; that is an architecture call this
module does not make.

**Storage + IAM (aws-core-tap#41) join the same "ahead of a containment path" shape.**
``S3BucketFalsifier``, ``IamRoleFalsifier``, ``IamUserFalsifier`` and ``IamPolicyFalsifier``
(customer-managed policies only — an AWS-managed policy is provisioned and retired by AWS, not
this account, so that falsifier refuses one before spending any AWS call) reuse ``_AwsFalsifier``
and ``_scope_check`` exactly as the compute/network types do; they need no region-sweep machinery
(``_region_hint`` / ``_sweep_regions``) at all, because S3 (for the calls made here) and IAM are
genuinely global services, not regional ones — there is no "which region was this collected in"
question for them to answer. ``IamRoleFalsifier`` and ``IamUserFalsifier`` additionally bind the
grid's stored ``name`` field to the resource-name segment of its own ARN before probing:
``get_role``/``get_user`` take only a bare name, never the ARN, so nothing else guarantees the
two independently-stored fields still agree. ``S3BucketFalsifier`` carries its own, narrower
addition on top of the shared shape: AWS's ``HeadBucket`` documents 403 and 404 as EQUALLY
ambiguous ("gone" vs. "this credential may not look"), so both route through a tie-break against
this account's own ``list_buckets`` — a check ``_scope_check`` does not need to make for the
EC2/VPC types, whose ``Invalid*ID.NotFound`` codes are unambiguous once the account itself is
confirmed. See each class's own docstring for the specifics.

**Where the region comes from (``_AwsFalsifier._regions_of``).** Every describe call is
region-scoped and no model stores a region, but the collector stamps
``dimensions["aws_region"]`` on every node it writes, so the dimension is the region, trusted
(``regions_trustworthy=True``): a not-found *there* is a real absence. Failing that, a subclass
may supply ``_region_hint`` (``SubnetFalsifier`` parses its ``availability_zone`` — the leading
``xx-name-N`` region shape, NOT ``az[:-1]``, which mishandles a Local/Wavelength Zone such as
``us-west-2-lax-1a``). Failing that, the falsifier sweeps the account's enabled regions
(``ec2:DescribeRegions``: one extra IAM action and bootstrap call; ``_enabled_regions``) — and a
sweep is **untrustworthy by construction** (``regions_trustworthy=False``): it cannot show where
the row was collected, and a row collected under a since-narrowed ``regions_allowed`` would read
as gone in every region a narrower sweep covers. So a fallback sweep may FIND the resource (and
answer PRESENT / REIDENTIFIED / RELOCATED) but may never answer ``DROPPED_FROM_OBSERVATION``:
that verdict is downgraded to ``UNDETERMINED(scope_unknown)`` in ``_Ec2Falsifier.judge``. Storage
+ IAM's falsifiers do not use this machinery at all — see the paragraph above.

**REIDENTIFIED is structurally rare for an AWS-id-keyed type, and the tests still cover it.**
``DescribeSubnets(SubnetIds=[subnet_id])`` looks up by AWS's own opaque, non-reused resource
id — the same string the grid's ``NATURAL_KEY`` rests on — so a "found" response naming a
*different* id is not a shape AWS's real API produces for this call. ``classify()`` (core)
still handles it generically from whatever ``Expected``/``Probe`` a falsifier hands it, so the
fake-source test exercises the classification wiring, not a claim about AWS's real behaviour.
Storage + IAM differ per type — see each class's own docstring: S3 and customer-managed IAM
policies can never answer it (structurally, not just rarely); IAM role/user CAN, for a
delete+recreate under a different path (same name).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
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

from tap_grid.falsifiers import (
    DROPPED_FROM_OBSERVATION,
    UNDETERMINED,
    Candidate,
    Expected,
    Falsifier,
    FalsifyContext,
    Probe,
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


def _enabled_regions(session: ProbeSession, configured_regions: list[str]) -> list[str]:
    """The account's enabled regions (``ec2:DescribeRegions``, ``AllRegions=False``), anchored on
    the first configured region only to place the one bootstrap call. Falls back to
    ``configured_regions`` if the call fails or names nothing — the caller treats any sweep as
    untrustworthy either way, so the fallback list never authorizes a retirement."""
    try:
        client = session.client("ec2", region_name=configured_regions[0])
        response = client.describe_regions(AllRegions=False)
    except Exception as exc:  # noqa: BLE001 — degrade to the configured scope, never crash the run
        logger.warning("[b6a1] ec2:DescribeRegions failed; falling back to the configured region scope: %s", exc)
        return list(configured_regions)
    names = sorted({str(r["RegionName"]) for r in (response.get("Regions") or []) if r.get("RegionName")})
    return names or list(configured_regions)


def _default_region_sweep(session: ProbeSession) -> list[str]:
    """Production fallback: the account's enabled regions, anchored on the collector's own
    configured region scope (``credentials.resolve_regions``)."""
    configured = resolve_regions(dict(resolve_aws_secret().data))
    return _enabled_regions(session, configured)


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
        region_sweep: Callable[[ProbeSession], list[str]] | None = None,
    ) -> None:
        self._session = session
        self._account_id = account_id
        self._session_factory = session_factory or _default_session
        #: The fallback for a candidate that records no region (see ``_regions_of``); injected by
        #: tests, the account's enabled regions in production. Cached once per run.
        self._region_sweep = region_sweep or _default_region_sweep
        self._sweep_cache: list[str] | None = None
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
        self._sweep_cache = None
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

    def _region_hint(self, row: Any) -> str | None:
        """A region the ROW itself implies when its ``aws_region`` dimension is absent (a type
        whose own fields name one), or None. Trusted like the dimension: it is the resource's
        own attribute, not a guess."""
        return None

    def _sweep_regions(self, session: ProbeSession) -> list[str]:
        """The fallback region list, resolved once per run. An unresolvable sweep is ``[]`` —
        the candidate is then refused, never probed against a guessed region."""
        if self._sweep_cache is None:
            try:
                self._sweep_cache = list(self._region_sweep(session))
            except Exception:  # noqa: BLE001 — no region scope is an answer (UNDETERMINED), not a crash
                logger.warning("[e2d4] %s: could not resolve a fallback region sweep", type(self).__name__)
                self._sweep_cache = []
        return list(self._sweep_cache)

    def _regions_of(self, row: Any, dimensions: dict[str, str], session: ProbeSession) -> tuple[list[str], bool]:
        """``(regions to probe, regions_trustworthy)`` for one candidate.

        The row's own recorded region (the ``aws_region`` dimension the collector stamps, then
        ``_region_hint``) is ONE region and trustworthy: a not-found there is a real absence.
        With neither, the account's enabled regions are swept and the list is NOT trustworthy —
        the sweep cannot show where the row was collected, so a clean sweep must never authorize
        ``DROPPED_FROM_OBSERVATION`` (callers downgrade that verdict; see ``_Ec2Falsifier.judge``).
        """
        region = dimensions.get("aws_region") or ""
        if region and region != "global":
            return [region], True
        hint = self._region_hint(row)
        if hint:
            return [hint], True
        return self._sweep_regions(session), False

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


#: The standard AWS region a plain availability zone name is prefixed with — ``us-east-1`` out of
#: ``us-east-1a``. Deliberately NOT ``az[:-1]``: a Local Zone or Wavelength Zone AZ
#: (``us-west-2-lax-1a``, ``us-east-1-wl1-bos-wlz-1``) carries the parent region as this same
#: leading ``xx-name-N`` shape plus a zone-specific suffix that ``[:-1]`` would fold into the
#: "region", producing a string boto3 has no endpoint for.
_STANDARD_REGION_PREFIX = re.compile(r"^([a-z]{2}(?:-gov)?-[a-z]+-\d+)")


class _Ec2Falsifier(_AwsFalsifier):
    """The shared shape for the EC2/VPC id-keyed types (tap-plugin-aws-core#43): a single
    ``describe_*`` call by id, in the candidate's own region(s), comparing AWS's own id, owning
    account and (where the type carries a ``Name`` tag) name.

    Subclasses declare the call's shape (``method``, ``ids_param``, ``list_key``,
    ``item_id_key``) and the row's natural-key field (``id_field``). ``Ec2InstanceFalsifier``
    additionally overrides ``_interpret`` for the terminated-state rule; ``SubnetFalsifier``
    overrides ``_region_hint``.

    A not-found from a region is region-local: with several regions (a fallback sweep) it never
    stops the sweep or proves absence on its own. A successful response that names the id is
    authoritative, and stops the sweep.
    """

    #: The boto3 ec2 client method, e.g. ``"describe_vpcs"``.
    method: str = ""
    #: The id-list kwarg of that method, e.g. ``"VpcIds"``.
    ids_param: str = ""
    #: The response key holding the found items, e.g. ``"Vpcs"``.
    list_key: str = ""
    #: The found item's own id field, e.g. ``"VpcId"``.
    item_id_key: str = ""
    #: The grid row's natural-key attribute, e.g. ``"vpc_id"``.
    id_field: str = ""
    #: Whether the probe's ``Name`` tag is compared to the row's ``name``. Off for a type whose
    #: row name is not known to be the ``Name`` tag (a mismatch would misread as a rename).
    compare_name: bool = True

    def _found_probe(self, item: dict[str, Any], owner: str | None, expected: Expected) -> Probe:
        """A ``found`` probe from one response item. The owner is compared only when the grid
        holds one (Option A, core's ``owner_not_compared`` reading); a response that then carries
        no owner cannot be classified (``incomplete``) and is answered ``errored``, never
        raised into ``verdict_from_probe``."""
        if expected.owner is not None and not owner:
            return Probe(status="errored", detail=f"{self.method} response carried no owner for the found resource")
        name = None
        if self.compare_name:
            name = next(
                (str(tag.get("Value") or "") for tag in item.get("Tags") or [] if tag.get("Key") == "Name"),
                None,
            )
        return Probe(
            status="found",
            source_id=str(item.get(self.item_id_key) or "") or None,
            owner=owner if expected.owner is not None else None,
            name=name or None,
            detail=f"{self.method} 200",
        )

    def _interpret(self, response: dict[str, Any], expected: Expected) -> tuple[Probe, bool]:
        """One region's successful response as ``(probe, authoritative)``. An empty list for an
        id filter is region-local not-found (some services answer that way instead of raising)."""
        items = response.get(self.list_key) or []
        if not items:
            return Probe(status="not_found", detail=NOT_FOUND_DETAIL), False
        item = items[0]
        return self._found_probe(item, str(item.get("OwnerId") or "") or None, expected), True

    def _probe_region(self, session: ProbeSession, region: str, expected: Expected) -> tuple[Probe, bool]:
        """One region's answer for one id, and whether it is authoritative (a successful response
        naming the resource) rather than region-local (an error, or a not-found that says nothing
        about any other region).

        Client construction is INSIDE the try: botocore can raise while building a client (bad
        region name, broken config) with no network call made yet, and that must fail this one
        candidate closed, never escape ``judge()`` and take the rest of the batch's verdicts
        down with it (``judge_all`` is a plain list comprehension over ``judge()``).
        """
        try:
            client = session.client("ec2", region_name=region)
            response = getattr(client, self.method)(**{self.ids_param: [expected.source_id]})
        except ClientError as exc:
            status = probe_status_of(exc)
            detail = NOT_FOUND_DETAIL if status == "not_found" else f"{error_code_of(exc)}: {exc}"
            return Probe(status=status, detail=detail), False  # type: ignore[arg-type]
        except BotoCoreError as exc:
            return Probe(status="errored", detail=str(exc)), False
        return self._interpret(response, expected)

    def _sweep(
        self, session: ProbeSession, regions: list[str], candidate: Candidate, expected: Expected
    ) -> Verdict:
        """Probe ``regions`` in order. A successful answer for the id ends it; otherwise the
        verdict is a not-found only if EVERY region said not-found — a region that refused,
        throttled or errored could be hiding the resource, so it never lets absence through."""
        seen_forbidden = seen_rate_limited = seen_errored = False
        for region in regions:
            probe, authoritative = self._probe_region(session, region, expected)
            if authoritative:
                return verdict_from_probe(candidate, expected, probe)
            if probe.status == "forbidden":
                seen_forbidden = True
            elif probe.status == "rate_limited":
                seen_rate_limited = True
            elif probe.status == "errored":
                seen_errored = True
        swept = ", ".join(regions)
        for seen, reason, why in (
            (seen_forbidden, "forbidden", "at least one refused the probe"),
            (seen_rate_limited, "rate_limited", "at least one was throttled"),
            (seen_errored, "errored", "at least one could not be probed"),
        ):
            if seen:
                return _undetermined(candidate, reason, f"could not confirm absence in every region ({swept}); {why}")
        return verdict_from_probe(candidate, expected, Probe(status="not_found", detail=NOT_FOUND_DETAIL))

    def judge(self, session: ProbeSession, account_id: str, candidate: Candidate) -> Verdict:
        row = _row_of(candidate.entity_id)
        if row is None:
            return _undetermined(candidate, "errored", "the grid row could not be read")
        source_id = str(getattr(row, self.id_field, "") or "")
        if not source_id:
            return _undetermined(candidate, "scope_unknown", f"the grid holds no {self.id_field} for this resource")
        dimensions = _dimensions_of(row)
        expected_account = dimensions.get("aws_account") or None
        scoped = self._scope_check(candidate, account_id, expected_account)
        if scoped is not None:
            return scoped
        regions, regions_trustworthy = self._regions_of(row, dimensions, session)
        if not regions:
            return _undetermined(
                candidate,
                "scope_unknown",
                "the grid holds no region for this resource and no fallback region sweep could be resolved",
            )
        expected = Expected(
            source_id=source_id, owner=expected_account, name=str(getattr(row, "name", "") or "") or None
        )
        verdict = self._sweep(session, regions, candidate, expected)
        if verdict.verdict == DROPPED_FROM_OBSERVATION and not regions_trustworthy:
            # A sweep of the account's enabled regions cannot show where this row was collected,
            # so a clean sweep (or a terminated answer found in it) is not evidence of absence.
            return _undetermined(
                candidate,
                "scope_unknown",
                "the grid records no region for this resource, so a fallback sweep of "
                f"{', '.join(regions)} cannot establish absence (a fallback sweep may only find, never drop)",
            )
        return verdict


class VpcFalsifier(_Ec2Falsifier):
    """``ec2:DescribeVpcs(VpcIds=[vpc_id])``; identity is ``vpc_id``."""

    method = "describe_vpcs"
    ids_param = "VpcIds"
    list_key = "Vpcs"
    item_id_key = "VpcId"
    id_field = "vpc_id"


class SubnetFalsifier(_Ec2Falsifier):
    """``ec2:DescribeSubnets(SubnetIds=[subnet_id])`` in the candidate's own region; compare AWS's
    ``SubnetId`` and ``OwnerId``.

    Identity is the subnet id itself (the grid's ``NATURAL_KEY``), so a ``not_found`` from this
    call is unambiguous: AWS's ``InvalidSubnetID.NotFound`` names the exact id that stopped
    existing (there is no cross-account visibility question once the account check has already
    passed). This is the type ``Vpc.CONTAINMENT_EDGES`` already marks reconcilable — see the
    module docstring. With no ``aws_region`` dimension it falls back to its own
    ``availability_zone``.
    """

    method = "describe_subnets"
    ids_param = "SubnetIds"
    list_key = "Subnets"
    item_id_key = "SubnetId"
    id_field = "subnet_id"

    def _region_hint(self, row: Any) -> str | None:
        match = _STANDARD_REGION_PREFIX.match(str(getattr(row, "availability_zone", "") or ""))
        return match.group(1) if match else None


class SecurityGroupFalsifier(_Ec2Falsifier):
    """``ec2:DescribeSecurityGroups(GroupIds=[group_id])``; identity is ``group_id``. The row's
    name is not compared (a security group's ``GroupName`` is not a ``Name`` tag)."""

    method = "describe_security_groups"
    ids_param = "GroupIds"
    list_key = "SecurityGroups"
    item_id_key = "GroupId"
    id_field = "group_id"
    compare_name = False


class Ec2InstanceFalsifier(_Ec2Falsifier):
    """``ec2:DescribeInstances(InstanceIds=[instance_id])``; identity is ``instance_id``.

    AWS keeps a terminated instance describable for a while rather than 404ing it immediately, so
    a successful response whose ``State.Name`` is ``terminated`` is folded into ``not_found`` —
    authoritatively (the response DID answer; sweeping further regions would be wasteful, since
    instance ids are not reused across regions). Every other state (``pending``, ``running``,
    ``shutting-down``, ``stopping``, ``stopped``) is ``found``: stopped is not gone.

    The shortcut fires only once the returned ``InstanceId`` equals the requested id: a
    synthesized ``not_found`` bypasses ``classify()``'s own identity comparison, so this is the one
    place that check has to be made explicitly. A mismatch falls through to the ordinary found
    path, where ``verdict_from_probe`` derives REIDENTIFIED on its own. The owner lives on the
    enclosing reservation, not the instance.
    """

    method = "describe_instances"
    ids_param = "InstanceIds"
    item_id_key = "InstanceId"
    id_field = "instance_id"

    _TERMINATED = "terminated"

    def _interpret(self, response: dict[str, Any], expected: Expected) -> tuple[Probe, bool]:
        pairs = [
            (instance, str(reservation.get("OwnerId") or "") or None)
            for reservation in response.get("Reservations") or []
            for instance in reservation.get("Instances") or []
        ]
        if not pairs:
            return Probe(status="not_found", detail=NOT_FOUND_DETAIL), False
        instance, owner = pairs[0]
        found_id = str(instance.get(self.item_id_key) or "")
        state = str((instance.get("State") or {}).get("Name") or "")
        if state == self._TERMINATED and found_id == expected.source_id:
            return Probe(status="not_found", detail=f"{NOT_FOUND_DETAIL} (State.Name=terminated)"), True
        return self._found_probe(instance, owner, expected), True


# ---------------------------------------------------------------------------
# Storage + IAM (aws-core-tap#41)
# ---------------------------------------------------------------------------

#: A region string for constructing an IAM/S3 client. Both are effectively global for the calls
#: this module makes (IAM has a single global endpoint regardless of the region_name passed; S3's
#: HeadBucket/ListBuckets calls reach the right place too), but boto3 always requires SOME region
#: string to build a client — this exists only for that, not to scope the request.
_GLOBAL_CLIENT_REGION = "us-east-1"


def _iam_probe_status_of(exc: ClientError) -> str:
    """Like the shared ``probe_status_of``, extended for IAM's own not-found convention:
    ``NoSuchEntity`` (``get_role``/``get_user``/``get_policy`` alike) starts with ``NoSuch`` but
    does not end with ``.NotFound``/``NotFoundException``, so the shared classifier — built
    against EC2's ``Invalid*ID.NotFound`` shape — does not recognize it on its own. Checked
    first, falling back to the shared classifier for everything else (``AccessDenied``,
    throttling, ...), so this is additive, not a divergent copy of it."""
    code = error_code_of(exc)
    if code.startswith("NoSuch"):
        return "not_found"
    return probe_status_of(exc)


def _s3_probe_status_of(exc: ClientError) -> str:
    """Like the shared ``probe_status_of``, extended for ``HeadBucket``'s own quirk: a bodyless
    response reports only a bare numeric string in ``Error.Code`` ("404"/"403"), never one of
    the shared classifier's named codes (its ``NoSuchBucket`` entry is for OTHER S3 operations
    that DO return a body — ``GetBucketPolicy``, ``DeleteBucket`` — not ``HeadBucket``). Verified
    against AWS's own ``HeadBucket`` documentation: *"If the bucket doesn't exist or you don't
    have permission to access it, the HEAD request returns a generic 400 Bad Request, 403
    Forbidden, or 404 Not Found HTTP status code."* Checked first, falling back to the shared
    classifier for everything else.
    """
    code = error_code_of(exc)
    if code == "404":
        return "not_found"
    if code == "403":
        return "forbidden"
    return probe_status_of(exc)


def _arn_resource_name(arn: str | None) -> str | None:
    """The trailing name segment of an IAM role/user ARN's resource part
    (``role/optional/path/NAME`` or ``user/optional/path/NAME`` -> ``NAME``), or None when the
    ARN is not IAM-shaped (``arn:partition:iam::account:resource``) or its resource part carries
    no ``/`` at all.

    IAM's ``RoleName``/``UserName`` is always the LAST path segment; everything before it,
    including the leading ``role/``/``user/`` type marker, is ``Path``. Used to bind the grid's
    stored ``name`` field to what its own ``role_arn``/``user_arn`` field actually names before
    ``get_role``/``get_user`` (which take only ``name``, never the ARN) are asked anything: the
    two are independently stored fields, and nothing else guarantees they still agree.
    """
    if not arn:
        return None
    parts = str(arn).split(":", 5)
    if len(parts) < 6 or parts[0] != "arn" or parts[2] != "iam":
        return None
    resource = parts[5]
    return resource.rsplit("/", 1)[-1] if "/" in resource else None


def _created_at(payload: Mapping[str, Any]) -> datetime | None:
    """boto3 hands back ``CreateDate`` as a real ``datetime`` already (unlike a JSON API's ISO
    string), so this is a type check, not a parse."""
    value = payload.get("CreateDate")
    return value if isinstance(value, datetime) else None


class IamRoleFalsifier(_AwsFalsifier):
    """``iam:GetRole(RoleName=name)``; ``NoSuchEntity`` -> gone.

    Cannot answer ``REIDENTIFIED`` for a delete+recreate under the SAME path: that yields an
    identical ARN (account + path + name are all unchanged). CAN answer it for a delete+recreate
    under a DIFFERENT path, same name: ``get_role`` looks up by ``RoleName`` alone, and IAM role
    names are unique per account across every path, not per path.
    """

    def judge(self, session: ProbeSession, account_id: str, candidate: Candidate) -> Verdict:
        row = _row_of(candidate.entity_id)
        if row is None:
            return _undetermined(candidate, "errored", "the grid row could not be read")
        name = str(getattr(row, "name", "") or "")
        arn = str(getattr(row, "role_arn", "") or "")
        if not name or not arn:
            return _undetermined(candidate, "scope_unknown", "the grid holds no name or ARN for this IAM role")
        dimensions = _dimensions_of(row)
        expected_account = dimensions.get("aws_account") or None
        scoped = self._scope_check(candidate, account_id, expected_account)
        if scoped is not None:
            return scoped
        if _arn_resource_name(arn) != name:
            # get_role takes RoleName, never the ARN: without this check, a row whose two
            # independently-stored fields have drifted apart would query a DIFFERENT role than
            # the one its own ARN names, and a NoSuchEntity for that wrong name could retire the
            # grid row for an ARN that still exists.
            return _undetermined(
                candidate,
                "scope_unknown",
                f"the grid's stored name ({name!r}) does not match the resource name in its own ARN ({arn!r}); "
                "querying by name would ask about a different object than the one this ARN claims to be",
            )
        expected = Expected(source_id=arn, owner=None, name=name)
        try:
            client = session.client("iam", region_name=_GLOBAL_CLIENT_REGION)
            result = client.get_role(RoleName=name)
        except ClientError as exc:
            status = _iam_probe_status_of(exc)
            detail = NOT_FOUND_DETAIL if status == "not_found" else f"{error_code_of(exc)}: {exc}"
            return verdict_from_probe(candidate, expected, Probe(status=status, detail=detail))  # type: ignore[arg-type]
        except BotoCoreError as exc:
            return _undetermined(candidate, "errored", str(exc))
        role = result.get("Role") or {}
        probe = Probe(
            status="found",
            source_id=str(role.get("Arn") or "") or None,
            name=str(role.get("RoleName") or "") or None,
            created_at=_created_at(role),
            detail="get_role 200",
        )
        return verdict_from_probe(candidate, expected, probe)


class IamUserFalsifier(_AwsFalsifier):
    """``iam:GetUser(UserName=name)``; ``NoSuchEntity`` -> gone.

    Cannot answer ``REIDENTIFIED`` for a delete+recreate under the SAME path: that yields an
    identical ARN. CAN answer it for a delete+recreate under a DIFFERENT path, same name:
    ``get_user`` looks up by ``UserName`` alone (see ``IamRoleFalsifier``'s identical reasoning).
    """

    def judge(self, session: ProbeSession, account_id: str, candidate: Candidate) -> Verdict:
        row = _row_of(candidate.entity_id)
        if row is None:
            return _undetermined(candidate, "errored", "the grid row could not be read")
        name = str(getattr(row, "name", "") or "")
        arn = str(getattr(row, "user_arn", "") or "")
        if not name or not arn:
            return _undetermined(candidate, "scope_unknown", "the grid holds no name or ARN for this IAM user")
        dimensions = _dimensions_of(row)
        expected_account = dimensions.get("aws_account") or None
        scoped = self._scope_check(candidate, account_id, expected_account)
        if scoped is not None:
            return scoped
        if _arn_resource_name(arn) != name:
            return _undetermined(
                candidate,
                "scope_unknown",
                f"the grid's stored name ({name!r}) does not match the resource name in its own ARN ({arn!r}); "
                "querying by name would ask about a different object than the one this ARN claims to be",
            )
        expected = Expected(source_id=arn, owner=None, name=name)
        try:
            client = session.client("iam", region_name=_GLOBAL_CLIENT_REGION)
            result = client.get_user(UserName=name)
        except ClientError as exc:
            status = _iam_probe_status_of(exc)
            detail = NOT_FOUND_DETAIL if status == "not_found" else f"{error_code_of(exc)}: {exc}"
            return verdict_from_probe(candidate, expected, Probe(status=status, detail=detail))  # type: ignore[arg-type]
        except BotoCoreError as exc:
            return _undetermined(candidate, "errored", str(exc))
        user = result.get("User") or {}
        probe = Probe(
            status="found",
            source_id=str(user.get("Arn") or "") or None,
            name=str(user.get("UserName") or "") or None,
            created_at=_created_at(user),
            detail="get_user 200",
        )
        return verdict_from_probe(candidate, expected, probe)


class IamPolicyFalsifier(_AwsFalsifier):
    """``iam:GetPolicy(PolicyArn=arn)``; ``NoSuchEntity`` -> gone. Customer-managed policies only.

    AWS-managed policies (``is_aws_managed=True``) are provisioned and retired by AWS, not this
    account: their absence from a listing is never evidence of deletion, so this falsifier
    refuses the candidate without spending an AWS call on it — a falsifier for something that
    structurally cannot be absent is pointless work, not a fail-closed default. Cannot answer
    ``REIDENTIFIED`` for a customer policy: ``get_policy`` is looked up BY the full ARN, so the
    response's ``Arn`` is definitionally the one requested — no name-binding check is needed
    either, unlike role/user, for the same reason.
    """

    def judge(self, session: ProbeSession, account_id: str, candidate: Candidate) -> Verdict:
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
            return _undetermined(candidate, "scope_unknown", "the grid holds no ARN for this IAM policy")
        dimensions = _dimensions_of(row)
        expected_account = dimensions.get("aws_account") or None
        scoped = self._scope_check(candidate, account_id, expected_account)
        if scoped is not None:
            return scoped
        expected = Expected(source_id=arn, owner=None, name=name or None)
        try:
            client = session.client("iam", region_name=_GLOBAL_CLIENT_REGION)
            result = client.get_policy(PolicyArn=arn)
        except ClientError as exc:
            status = _iam_probe_status_of(exc)
            detail = NOT_FOUND_DETAIL if status == "not_found" else f"{error_code_of(exc)}: {exc}"
            return verdict_from_probe(candidate, expected, Probe(status=status, detail=detail))  # type: ignore[arg-type]
        except BotoCoreError as exc:
            return _undetermined(candidate, "errored", str(exc))
        policy = result.get("Policy") or {}
        probe = Probe(
            status="found",
            source_id=str(policy.get("Arn") or "") or None,
            name=str(policy.get("PolicyName") or "") or None,
            created_at=_created_at(policy),
            detail="get_policy 200",
        )
        return verdict_from_probe(candidate, expected, probe)


class S3BucketFalsifier(_AwsFalsifier):
    """``s3:HeadBucket(Bucket=name)``; both the 404 AND the 403 case are resolved by this
    account's own ``list_buckets`` — AWS's own ``HeadBucket`` documentation says neither status
    code is conclusive on its own: *"If the bucket doesn't exist or you don't have permission to
    access it, the HEAD request returns a generic 400 Bad Request, 403 Forbidden, or 404 Not
    Found HTTP status code."*

    ``_scope_check`` runs first, exactly as it does for every other type here — but S3's own
    ambiguity means a THIRD signal is needed on top of it: even once the credential's account is
    confirmed to be the one the grid recorded this bucket under, an ambiguous ``HeadBucket``
    status still does not distinguish "gone" from "merely not visible to this credential's
    ``s3:ListBucket`` permission on THIS bucket specifically" (a permission that can be scoped
    per-bucket, unlike the account-wide IAM actions the other falsifiers here check). The
    tie-break is this account's own bucket inventory (``list_buckets`` / ``ListAllMyBuckets``,
    which needs no per-bucket permission): present in it, the answer is a permission/visibility
    gap and the bucket stands; absent from it, it is read as gone. (400 is left as ``errored`` —
    already conservative, since it never becomes a retirement.)

    S3 bucket ARNs (``arn:aws:s3:::name``) are a pure function of the name and carry no account
    segment: a bucket deleted and recreated under the same name — by this account or, since S3
    bucket names are globally unique, by a stranger — is byte-identical to this falsifier. It can
    therefore never answer ``REIDENTIFIED`` for a bucket; that is a structural S3 limit, not a
    gap in this code.
    """

    #: Both status codes ``head_bucket`` uses for "gone or forbidden, indistinguishably" (class
    #: docstring). 400 is deliberately excluded: it already lands as ``errored``, already
    #: conservative (never becomes a retirement).
    _AMBIGUOUS_STATUSES = frozenset({"not_found", "forbidden"})

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        #: This account's own bucket names (``ListAllMyBuckets``), resolved ONCE per batch and
        #: cached whether it succeeds or fails (``_own_buckets_attempted_for`` tracks the attempt
        #: independent of outcome: a failure cached only as "no value yet" would otherwise be
        #: retried once per ambiguous-status candidate instead of once for the whole batch).
        self._own_buckets: frozenset[str] | None = None
        self._own_buckets_attempted_for = ""

    def _begin_run(self, batch_id: str) -> None:
        if batch_id != self._batch_id:
            self._own_buckets = None
            self._own_buckets_attempted_for = ""
        super()._begin_run(batch_id)

    def _own_bucket_names(self, client: Any) -> frozenset[str] | None:
        """This run's ``ListAllMyBuckets`` answer, or None when it could not be read (including a
        partial page) — which must never be read as an empty or complete account (the same
        "unobserved is not empty" rule github_core's reach walk applies to its own listing
        failures).

        An unparameterised ``list_buckets()`` call returns AWS's complete bucket inventory for an
        account at or under the default 10,000-bucket quota, or is rejected outright for an
        account with an approved quota above it (AWS's own ``ListBuckets`` documentation,
        verified directly: *"Unpaginated ListBuckets requests are only supported for AWS
        accounts set to the default general purpose bucket quota of 10,000 ... All unpaginated
        ListBuckets requests will be rejected for AWS accounts with a general purpose bucket
        quota greater than 10,000"*) — so a genuinely partial page should not normally occur
        here. It is still checked for, rather than assumed away: AWS's own doc for the response
        element is explicit — *"ContinuationToken is included in the response when there are
        more buckets that can be listed with pagination"* — a documented signal on THIS specific
        API, not an echoed request token; ``ListObjectsV2``'s distinct
        ``IsTruncated``/``NextContinuationToken`` fields belong to a different API and do not
        apply here.
        """
        if self._own_buckets_attempted_for == self._batch_id:
            return self._own_buckets
        try:
            response = client.list_buckets()
        except (ClientError, BotoCoreError) as exc:
            logger.warning(
                "[8ad1] S3BucketFalsifier: list_buckets tie-break failed: %s: %s", type(exc).__name__, exc
            )
            self._own_buckets = None
            self._own_buckets_attempted_for = self._batch_id
            return None
        if response.get("ContinuationToken"):
            logger.warning(
                "[3f0a] S3BucketFalsifier: list_buckets returned a ContinuationToken (a partial page); refusing "
                "to treat it as this account's complete bucket inventory"
            )
            self._own_buckets = None
            self._own_buckets_attempted_for = self._batch_id
            return None
        if "Buckets" not in response or response.get("Buckets") is None:
            # A `Buckets` key present but empty (`[]`) is a genuine, positive "this account owns
            # zero buckets" observation and is trusted below. The key being ABSENT or None
            # entirely is a different thing — a malformed or incomplete response — and must not
            # collapse to the same empty inventory via `or []`'s silent default (the same
            # null-is-unobserved-vs-empty-is-observed distinction this module applies elsewhere).
            logger.warning(
                "[6b12] S3BucketFalsifier: list_buckets returned no Buckets key/value; refusing to treat this "
                "as a (possibly empty) complete inventory"
            )
            self._own_buckets = None
            self._own_buckets_attempted_for = self._batch_id
            return None
        names = frozenset(str(b.get("Name") or "") for b in response["Buckets"])
        self._own_buckets = names
        self._own_buckets_attempted_for = self._batch_id
        return names

    def judge(self, session: ProbeSession, account_id: str, candidate: Candidate) -> Verdict:
        row = _row_of(candidate.entity_id)
        if row is None:
            return _undetermined(candidate, "errored", "the grid row could not be read")
        name = str(getattr(row, "name", "") or "")
        arn = str(getattr(row, "bucket_arn", "") or "")
        if not name or not arn:
            return _undetermined(candidate, "scope_unknown", "the grid holds no name or ARN for this bucket")
        dimensions = _dimensions_of(row)
        expected_account = dimensions.get("aws_account") or None
        scoped = self._scope_check(candidate, account_id, expected_account)
        if scoped is not None:
            return scoped
        expected = Expected(source_id=arn, owner=None, name=name)
        client = session.client("s3", region_name=_GLOBAL_CLIENT_REGION)
        try:
            client.head_bucket(Bucket=name)
        except ClientError as exc:
            return self._judge_absence(client, candidate, expected, exc, name)
        except BotoCoreError as exc:
            return _undetermined(candidate, "errored", str(exc))
        probe = Probe(status="found", source_id=arn, name=name, detail="head_bucket 200")
        return verdict_from_probe(candidate, expected, probe)

    def _judge_absence(
        self, client: Any, candidate: Candidate, expected: Expected, exc: ClientError, name: str
    ) -> Verdict:
        status = _s3_probe_status_of(exc)
        if status not in self._AMBIGUOUS_STATUSES:
            # A throttle, or an unclassified error (including the bare-400 case): no ambiguity
            # this falsifier resolves, no tie-break.
            detail = f"{error_code_of(exc)}: {exc}"
            return verdict_from_probe(candidate, expected, Probe(status=status, detail=detail))  # type: ignore[arg-type]
        # `_scope_check` already confirmed the credential's account matches this bucket's own
        # recorded account before any probe was made — the ambiguity left is S3's own (class
        # docstring), not a cross-account one, so the tie-break below needs no further owner
        # re-check of its own.
        names = self._own_bucket_names(client)
        if names is None:
            return _undetermined(
                candidate,
                "scope_unknown",
                f"head_bucket({name}) answered {status} — S3 documents this status as meaning either gone or "
                "merely not visible to this credential — and this account's own ListBuckets (the tie-break) "
                "could not be read either, so nothing here separates the two",
            )
        if name not in names:
            return verdict_from_probe(
                candidate,
                expected,
                Probe(status="not_found", detail=f"{NOT_FOUND_DETAIL}; absent from this account's own ListBuckets"),
            )
        return _undetermined(
            candidate,
            "forbidden",
            f"head_bucket({name}) answered {status} but {name} is present in this account's own ListBuckets: the "
            "bucket is not gone, only this credential's head_bucket permission on it",
        )


__all__ = [
    "NOT_FOUND_DETAIL",
    "Ec2InstanceFalsifier",
    "IamPolicyFalsifier",
    "IamRoleFalsifier",
    "IamUserFalsifier",
    "S3BucketFalsifier",
    "SecurityGroupFalsifier",
    "SubnetFalsifier",
    "VpcFalsifier",
    "error_code_of",
    "probe_status_of",
]
