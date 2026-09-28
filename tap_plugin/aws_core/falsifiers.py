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

**Known limitation, not fixed here: the ``aws_account`` dimension can flap across credentials for
one entity (flagged on tap-plugin-aws-core#50's review).** Every node this run writes — including
an ``AwsAccount`` the Organizations walk discovers under a *management or delegated-administrator*
credential — is stamped ``dimensions["aws_account"] = <this run's own resolved account>``
(``collector.py``'s ``org_dimensions``), the observing credential, not necessarily the account the
row represents. If that same deterministic account id is *also* collected directly, on a separate
run, by a credential scoped to that member account itself (the ordinary manifest-driven sweep run
against it), GRIFT's upsert (``replace_node``) overwrites the row's dimensions with THAT run's
credential instead. ``_scope_check`` then compares whichever credential is falsifying against
whichever run's dimension happened to write last, and a genuinely-in-scope
``AccountFalsifier``/``OrganizationalUnitFalsifier`` candidate can read as ``UNDETERMINED
(scope_unknown)`` until the next org-level run rewrites the dimension back. Closing it for real
needs either a per-type stamping rule (an ``AwsAccount``/``AwsOrganizationalUnit`` node's own
dimension should arguably be its OWN account, not the observing credential's, since the row IS
that account) or a reach concept that does not rely on the dimension at all — a design question
for whoever owns the dimension convention across collectors, not a fix made unilaterally here.

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
that verdict is downgraded to ``UNDETERMINED(scope_unknown)`` in ``_Ec2Falsifier.judge``.

**REIDENTIFIED is structurally rare for an AWS-id-keyed type, and the tests still cover it.**
``DescribeSubnets(SubnetIds=[subnet_id])`` looks up by AWS's own opaque, non-reused resource
id — the same string the grid's ``NATURAL_KEY`` rests on — so a "found" response naming a
*different* id is not a shape AWS's real API produces for this call. ``classify()`` (core)
still handles it generically from whatever ``Expected``/``Probe`` a falsifier hands it, so the
fake-source test exercises the classification wiring, not a claim about AWS's real behaviour.
"""

from __future__ import annotations

import logging
import re
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
    NESTED_UNDER_PARENT,
    account_state,
    organization_id_of_account_arn,
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


#: The most NESTED_UNDER_PARENT hops _organization_id_of will follow before giving up — real
#: Organizations trees nest a handful of levels deep; this only guards a graph anomaly.
_MAX_PARENT_HOPS = 50


def _organization_id_of(entity_id: Any) -> str:
    """Walk ``NESTED_UNDER_PARENT`` from ``entity_id`` up to its ``AwsOrganization`` ancestor and
    return its ``organization_id``, or ``""`` when the chain does not reach one.

    ``AwsOrganizationalUnit`` carries no ``organization_id`` field of its own (only ``AwsOrganization``
    does), so a nested OU's organization is not read off its row or off ``Candidate.parent`` alone —
    ``Candidate.parent`` names only the OU's IMMEDIATE parent, which for a nested OU is another OU,
    not the organization. This is the OU-side analogue of ``AccountFalsifier``'s organization
    comparison (Codex on unified-ai-review#55: a bare root-id-suffix comparison could authorize
    probing the wrong organization if two organizations' root suffixes happened to collide — AWS
    documents no global uniqueness for the short alphanumeric suffix). Read straight off the edge
    table, the same way ``tap_grid.candidates._children`` does, rather than through the service
    layer's read path: this is graph topology, not a typed field.
    """
    from tap_grid.models import Edge

    current = entity_id
    for _ in range(_MAX_PARENT_HOPS):
        parent_id = (
            Edge.objects.filter(
                from_entity_id=current, edge_type=NESTED_UNDER_PARENT, to_entity__deleted_at__isnull=True
            )
            .values_list("to_entity_id", "to_entity__entity_type")
            .first()
        )
        if parent_id is None:
            return ""
        to_id, to_type = parent_id
        if to_type == _ORGANIZATION_TYPE:
            organization = _row_of(to_id)
            return str(getattr(organization, "organization_id", "") or "")
        current = to_id
    logger.warning("[d9a3] _organization_id_of(%s): exceeded %d parent hops without reaching an organization", entity_id, _MAX_PARENT_HOPS)
    return ""


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
        has_root = any(str(r.get("Id") or "").startswith("r-") for r in roots)
        if not organization.get("Id") or not has_root:
            return _OrgReach("errored", note="the organization read returned no organization id or no root")
        return _OrgReach("ok", organization_id=str(organization["Id"]))

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

    The credential must first be proven to be inside the candidate's own organization: its
    ``organization_id``, walked from the OU up through ``NESTED_UNDER_PARENT`` to its
    ``AwsOrganization`` ancestor (``_organization_id_of``), must equal ``reach.organization_id`` —
    the same comparison ``AccountFalsifier`` makes, not a root-id-suffix heuristic (AWS documents
    no global uniqueness for that short alphanumeric string).
    """

    def _judge_one(self, client: Any, reach: _OrgReach, row: Any, candidate: Candidate) -> Verdict:
        ou_id = str(getattr(row, "ou_id", "") or "")
        if not ou_id:
            return _undetermined(candidate, "scope_unknown", "the grid holds no ou_id for this OU")
        recorded_org = _organization_id_of(candidate.entity_id)
        if not recorded_org:
            return _undetermined(
                candidate, "scope_unknown", "the grid holds no organization for this OU (its NESTED_UNDER_PARENT "
                "chain does not reach an AwsOrganization row)"
            )
        if recorded_org != reach.organization_id:
            return _undetermined(
                candidate,
                "scope_unknown",
                f"this credential is in organization {reach.organization_id}, not {recorded_org}: an absence "
                "here says nothing about that organization's OUs",
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
    "Ec2InstanceFalsifier",
    "OrganizationalUnitFalsifier",
    "SecurityGroupFalsifier",
    "SubnetFalsifier",
    "VpcFalsifier",
    "error_code_of",
    "probe_status_of",
]
