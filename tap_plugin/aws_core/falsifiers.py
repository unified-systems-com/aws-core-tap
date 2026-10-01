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
from dataclasses import dataclass
from datetime import datetime
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
from tap_plugin.aws_core.collectors.boto3_collector.iam_trust import iam_endpoint_region
from tap_plugin.aws_core.collectors.boto3_collector.organizations import (
    ACCOUNT_NOT_REGISTERED,
    INACTIVE_ACCOUNT_STATES,
    NESTED_UNDER_PARENT,
    account_state,
    is_aws_managed_policy_arn,
    organization_id_of_account_arn,
    organization_id_of_policy_arn,
    policy_id_of_arn,
)
from tap_plugin.aws_core.collectors.boto3_collector.policy_documents import (
    PolicyDocumentError,
    parse_statements,
    parse_tag_rules,
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
        return _read_org_reach(client)

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


def _read_org_reach(client: Any) -> _OrgReach:
    """Prove the credential is inside an organization and can read its tree (shared by the
    Organizations falsifiers and the Identity Center assignment falsifier's account probe)."""
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


# ---------------------------------------------------------------------------
# Organizations completeness (aws-core-tap#65): delegations, policies, statements, tag rules.
# Registered, not armed: reconcile authority stays off, so none of these is dispatched in
# production until a later step arms it.
# ---------------------------------------------------------------------------

#: A page loop that never ends is a defect in the source, not an answer.
_MAX_PROBE_PAGES = 500


def _unanswered(candidate: Candidate, exc: Exception) -> Verdict:
    """``UNDETERMINED`` with the reason the failure maps to, never a destructive verdict: for the
    calls below only a named code means "gone", so a generic not-found is ``errored``."""
    status = probe_status_of(exc)
    reason = status if status in ("forbidden", "rate_limited") else "errored"
    code = error_code_of(exc) if isinstance(exc, ClientError) else type(exc).__name__
    return _undetermined(candidate, reason, f"{code}: the probe could not answer")


class DelegatedAdministrationFalsifier(_OrganizationsFalsifier):
    """``organizations:ListDelegatedServicesForAccount(AccountId)``, read to its last page; is the
    candidate's service principal still named?

    A candidate is a delegation the organization-wide ``HOLDS_DELEGATION`` listing no longer named
    (``req-aws-core-organizations-completeness-4``). What "gone" means, from the spec:

    - A successful answer that no longer names the service principal is ``DROPPED_FROM_OBSERVATION``.
    - ``AccountNotRegisteredException`` ("the specified account is not a delegated administrator",
      botocore) is ``DROPPED_FROM_OBSERVATION``: it is AWS's answer once the account's last
      delegation is removed.
    - Every other error (``AccessDeniedException``, ``AccountNotFoundException``, a throttle, a page
      after the first failing) is ``UNDETERMINED``.

    Source identity is the service principal, qualified by the ``DelegationEnabledDate`` the grid
    recorded when it recorded one: a delegation deregistered and registered again between the
    listing and the probe is a new registration, ``REIDENTIFIED``, not the same one present. The
    credential must be inside the delegation's own organization (``organization_id`` on the row).
    """

    def _judge_one(self, client: Any, reach: _OrgReach, row: Any, candidate: Candidate) -> Verdict:
        organization_id = str(getattr(row, "organization_id", "") or "")
        account = str(getattr(row, "account_id", "") or "")
        principal = str(getattr(row, "service_principal", "") or "")
        if not organization_id or not account or not principal:
            return _undetermined(candidate, "scope_unknown", "the grid holds no (organization, account, service principal) for this delegation")
        if organization_id != reach.organization_id:
            return _undetermined(
                candidate,
                "scope_unknown",
                f"this credential is in organization {reach.organization_id}, not {organization_id}: an absence "
                "here says nothing about that organization's delegations",
            )
        recorded_date = str(getattr(row, "delegation_enabled_at", "") or "")
        expected = Expected(source_id=_delegation_identity(principal, recorded_date))
        services: list[dict[str, Any]] = []
        token: str | None = None
        try:
            for _ in range(_MAX_PROBE_PAGES):
                kwargs: dict[str, Any] = {"AccountId": account, "MaxResults": 20}
                if token:
                    kwargs["NextToken"] = token
                response = client.list_delegated_services_for_account(**kwargs)
                services.extend(response.get("DelegatedServices") or [])
                token = response.get("NextToken")
                if not token:
                    break
            else:
                return _undetermined(candidate, "errored", "ListDelegatedServicesForAccount did not reach its last page")
        except ClientError as exc:
            if error_code_of(exc) == ACCOUNT_NOT_REGISTERED:
                return verdict_from_probe(
                    candidate, expected, Probe(status="not_found", detail=f"{ACCOUNT_NOT_REGISTERED}: the account is not a delegated administrator")
                )
            return _unanswered(candidate, exc)
        except BotoCoreError as exc:
            return _unanswered(candidate, exc)
        named = next((s for s in services if str(s.get("ServicePrincipal") or "") == principal), None)
        if named is None:
            return verdict_from_probe(
                candidate, expected, Probe(status="not_found", detail="ListDelegatedServicesForAccount no longer names this service principal")
            )
        enabled = named.get("DelegationEnabledDate")
        probe_date = _iso_of(enabled) if recorded_date else ""
        probe = Probe(
            status="found",
            source_id=_delegation_identity(principal, probe_date),
            created_at=enabled if isinstance(enabled, datetime) else None,
            detail="ListDelegatedServicesForAccount names the service principal",
        )
        return _finish(candidate, expected, probe)


def _delegation_identity(principal: str, enabled_at: str) -> str:
    return f"{principal}@{enabled_at}" if enabled_at else principal


def _iso_of(value: Any) -> str:
    """``DelegationEnabledDate`` in the collector's own ISO form (``organizations._iso``)."""
    from tap_plugin.aws_core.collectors.boto3_collector.organizations import _iso

    return _iso(value)


class OrganizationsPolicyFalsifier(_OrganizationsFalsifier):
    """``organizations:DescribePolicy(PolicyId)``; compare the policy ARN, its organization and its name.

    Registered for both ``aws_service_control_policy`` and ``aws_organizations_policy``: a candidate
    is a customer-managed policy its organization's complete ``ListPolicies`` no longer named
    (``req-aws-core-organizations-completeness-6``). ``PolicyNotFoundException`` is
    ``DROPPED_FROM_OBSERVATION``. Source identity is the ARN; the owner is the organization id the
    ARN embeds (``arn:<partition>:organizations::<mgmt>:policy/<o-id>/<type>/<p-id>``).

    An AWS-managed policy is never a containment child (one ARN in every organization), so a
    candidate whose row says AWS-managed, or does not say, is refused before any call. So is one
    whose ARN names an organization other than the credential's.
    """

    def _judge_one(self, client: Any, reach: _OrgReach, row: Any, candidate: Candidate) -> Verdict:
        arn = str(getattr(row, "policy_arn", "") or "")
        if getattr(row, "aws_managed", None) is not False:
            return _undetermined(
                candidate, "scope_unknown", "not recorded as customer-managed: no organization contains an AWS-managed policy"
            )
        recorded_org = organization_id_of_policy_arn(arn)
        policy_id = str(getattr(row, "policy_id", "") or "") or policy_id_of_arn(arn)
        if not recorded_org or not policy_id:
            return _undetermined(candidate, "scope_unknown", "the grid holds no organization-scoped policy ARN for this policy")
        if recorded_org != reach.organization_id:
            return _undetermined(
                candidate,
                "scope_unknown",
                f"this credential is in organization {reach.organization_id}, not {recorded_org}: an absence "
                "here says nothing about that organization's policies",
            )
        expected = Expected(source_id=arn, owner=recorded_org, name=str(getattr(row, "name", "") or "") or None)
        try:
            summary = (client.describe_policy(PolicyId=policy_id).get("Policy") or {}).get("PolicySummary") or {}
        except (ClientError, BotoCoreError) as exc:
            return self._error_verdict(candidate, expected, exc)
        found_arn = str(summary.get("Arn") or "")
        probe = Probe(
            status="found",
            source_id=found_arn or None,
            owner=organization_id_of_policy_arn(found_arn) or None,
            name=str(summary.get("Name") or "") or None,
            detail="DescribePolicy 200",
        )
        return _finish(candidate, expected, probe)


class _PolicyBodyFalsifier(_OrganizationsFalsifier):
    """Shared shape of the statement and tag-rule falsifiers: one ``DescribePolicy`` per policy per
    batch, parsed by the collector's own parser (``policy_documents.py``), so the key looked for is
    computed exactly as the collector computed it.

    The candidate's own ``policy_arn`` names the policy. ``PolicyNotFoundException`` is
    ``DROPPED_FROM_OBSERVATION`` (the policy, and with it the unit, is gone); a refused call or an
    unparseable document is ``UNDETERMINED``. A customer-managed policy's ARN must name the
    credential's organization; only the exact AWS-managed ARN form names none, and for it the reach
    proof alone (the credential is inside an organization) is what lets it read one. Any other ARN
    is refused as ``scope_unknown`` before a call.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._documents: dict[str, tuple[str, str] | Exception] = {}

    def judge_all(self, session: ProbeSession, account_id: str, candidates: list[Candidate]) -> list[Verdict]:
        self._documents = {}
        return super().judge_all(session, account_id, candidates)

    def _document(self, client: Any, policy_id: str) -> tuple[str, str]:
        """``(the policy's ARN as AWS reports it, its document)``; raises what the call raised."""
        if policy_id not in self._documents:
            try:
                policy = client.describe_policy(PolicyId=policy_id).get("Policy") or {}
                summary = policy.get("PolicySummary") or {}
                content = policy.get("Content")
                self._documents[policy_id] = (
                    str(summary.get("Arn") or ""),
                    content if isinstance(content, str) else "",
                )
            except (ClientError, BotoCoreError) as exc:
                self._documents[policy_id] = exc
        cached = self._documents[policy_id]
        if isinstance(cached, Exception):
            raise cached
        return cached

    def _judge_one(self, client: Any, reach: _OrgReach, row: Any, candidate: Candidate) -> Verdict:
        arn = str(getattr(row, "policy_arn", "") or "")
        key = self._key_of(row)
        policy_id = policy_id_of_arn(arn)
        if not policy_id or not key:
            return _undetermined(candidate, "scope_unknown", "the grid holds no policy ARN or key for this unit")
        recorded_org = organization_id_of_policy_arn(arn)
        if not recorded_org and not is_aws_managed_policy_arn(arn):
            # Only the exact AWS-managed ARN form may skip the organization check; any other ARN
            # that names no organization says nothing about which organization to ask.
            return _undetermined(candidate, "scope_unknown", "the policy ARN is neither customer-managed nor AWS-managed in form")
        if recorded_org and recorded_org != reach.organization_id:
            return _undetermined(
                candidate,
                "scope_unknown",
                f"this credential is in organization {reach.organization_id}, not {recorded_org}: an absence "
                "here says nothing about that organization's policies",
            )
        expected = Expected(source_id=key, owner=arn)
        try:
            found_arn, document = self._document(client, policy_id)
        except (ClientError, BotoCoreError) as exc:
            return self._error_verdict(candidate, expected, exc)
        try:
            present, replaced_by = self._find(document, key)
        except PolicyDocumentError as exc:
            return _undetermined(candidate, "errored", f"the policy document could not be read: {exc}")
        if present:
            probe = Probe(status="found", source_id=key, owner=found_arn or None, detail="DescribePolicy names the key")
        elif replaced_by:
            probe = Probe(
                status="found", source_id=replaced_by, owner=found_arn or None, detail="the same unit is present under a new key"
            )
        else:
            probe = Probe(status="not_found", detail="DescribePolicy's document no longer holds this key")
        return _finish(candidate, expected, probe)

    def _key_of(self, row: Any) -> str:
        raise NotImplementedError

    def _find(self, document: str, key: str) -> tuple[bool, str]:
        """``(key present, the key the same unit now has when it changed identity)``."""
        raise NotImplementedError


class PolicyStatementFalsifier(_PolicyBodyFalsifier):
    """Is the statement's key still in its policy's document
    (``req-aws-core-organizations-completeness-10``)?

    Present: ``PRESENT_AT_PROBE``. Absent, or the policy gone: ``DROPPED_FROM_OBSERVATION``. A
    ``sid:<Sid>`` statement whose Sid the document now repeats is the same named statement under a
    new key (``dupsid:``): ``REIDENTIFIED``, the spec's "becomes duplicated" row, which retires the
    old node while the new one is collected.
    """

    def _key_of(self, row: Any) -> str:
        return str(getattr(row, "statement_key", "") or "")

    def _find(self, document: str, key: str) -> tuple[bool, str]:
        units = parse_statements(document).units
        if key in units:
            return True, ""
        if key.startswith("sid:"):
            sid = key[len("sid:"):]
            renamed = sorted(k for k, unit in units.items() if unit.sid == sid)
            if renamed:
                return False, renamed[0]
        return False, ""


class TagPolicyRuleFalsifier(_PolicyBodyFalsifier):
    """Is the rule's tag key still in its tag policy's document
    (``req-aws-core-organizations-completeness-11``)?

    Present: ``PRESENT_AT_PROBE``. Absent, or the policy gone: ``DROPPED_FROM_OBSERVATION``. A rule
    is keyed by the lowercased tag key alone, so a rule cannot come back under another key:
    ``REIDENTIFIED`` is structurally impossible here, and its tests prove present, dropped and
    forbidden individually, as the S3 and IAM-policy falsifiers do.
    """

    def _key_of(self, row: Any) -> str:
        return str(getattr(row, "tag_key_lower", "") or "")

    def _find(self, document: str, key: str) -> tuple[bool, str]:
        return key in parse_tag_rules(document), ""


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
    """Like the shared ``probe_status_of``, extended for two S3-specific shapes it does not
    cover:

    - ``HeadBucket``'s own quirk: a bodyless response reports only a bare numeric string in
      ``Error.Code`` ("404"/"403"), never one of the shared classifier's named codes (its
      ``NoSuchBucket`` entry is for OTHER S3 operations that DO return a body —
      ``GetBucketPolicy``, ``DeleteBucket`` — not ``HeadBucket``). Verified against AWS's own
      ``HeadBucket`` documentation: *"If the bucket doesn't exist or you don't have permission
      to access it, the HEAD request returns a generic 400 Bad Request, 403 Forbidden, or 404
      Not Found HTTP status code."*
    - S3's own throttle code, ``SlowDown``, which is not in the shared classifier's
      ``_RATE_LIMIT_CODES`` (built against EC2's ``Throttling``/``RequestLimitExceeded`` shapes).

    Checked first, falling back to the shared classifier for everything else.
    """
    code = error_code_of(exc)
    if code == "404":
        return "not_found"
    if code == "403":
        return "forbidden"
    if code == "SlowDown":
        return "rate_limited"
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


def _arn_names_s3_bucket(arn: str | None, name: str) -> bool:
    """True when ``arn`` is shaped like ``arn:partition:s3:::name`` AND its resource segment is
    exactly ``name``. ``head_bucket`` takes only ``Bucket=name``, never the ARN: without this
    check, a row whose two independently-stored fields (``name`` / ``bucket_arn``) have drifted
    apart would probe a DIFFERENT bucket than the one its own ARN names — the same risk
    ``_arn_resource_name`` closes for IAM role/user, adapted for S3's simpler ARN shape (no
    path, the resource part IS the name).
    """
    if not arn:
        return False
    parts = str(arn).split(":", 5)
    return len(parts) == 6 and parts[0] == "arn" and parts[2] == "s3" and parts[5] == name


def _created_at(payload: Mapping[str, Any]) -> datetime | None:
    """boto3 hands back ``CreateDate`` as a real ``datetime`` already (unlike a JSON API's ISO
    string), so this is a type check, not a parse."""
    value = payload.get("CreateDate")
    return value if isinstance(value, datetime) else None


class _IamFalsifier(_AwsFalsifier):
    """Shared shape for the three name/ARN-keyed IAM falsifiers: resolve the ``iam`` client, run
    one call, and turn a ``ClientError``/``BotoCoreError`` into the matching absence/refusal
    verdict — the one piece identical across ``GetRole``/``GetUser``/``GetPolicy``, factored out
    once rather than repeated per type. Each subclass supplies the call itself and, via
    ``_probe_of``, how its own response shape becomes a found ``Probe``.
    """

    def _iam_client(self, session: ProbeSession) -> Any:
        return session.client("iam", region_name=_GLOBAL_CLIENT_REGION)

    def _probe_call(
        self, candidate: Candidate, expected: Expected, call: Callable[[], dict[str, Any]]
    ) -> Verdict:
        try:
            result = call()
        except ClientError as exc:
            status = _iam_probe_status_of(exc)
            detail = NOT_FOUND_DETAIL if status == "not_found" else f"{error_code_of(exc)}: {exc}"
            return verdict_from_probe(candidate, expected, Probe(status=status, detail=detail))  # type: ignore[arg-type]
        except BotoCoreError as exc:
            return _undetermined(candidate, "errored", str(exc))
        return verdict_from_probe(candidate, expected, self._probe_of(result))

    def _probe_of(self, result: dict[str, Any]) -> Probe:
        raise NotImplementedError


class IamRoleFalsifier(_IamFalsifier):
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
        expected_account = _dimensions_of(row).get("aws_account") or None
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
        client = self._iam_client(session)
        return self._probe_call(candidate, expected, lambda: client.get_role(RoleName=name))

    def _probe_of(self, result: dict[str, Any]) -> Probe:
        role = result.get("Role") or {}
        return Probe(
            status="found",
            source_id=str(role.get("Arn") or "") or None,
            name=str(role.get("RoleName") or "") or None,
            created_at=_created_at(role),
            detail="get_role 200",
        )


class IamUserFalsifier(_IamFalsifier):
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
        expected_account = _dimensions_of(row).get("aws_account") or None
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
        client = self._iam_client(session)
        return self._probe_call(candidate, expected, lambda: client.get_user(UserName=name))

    def _probe_of(self, result: dict[str, Any]) -> Probe:
        user = result.get("User") or {}
        return Probe(
            status="found",
            source_id=str(user.get("Arn") or "") or None,
            name=str(user.get("UserName") or "") or None,
            created_at=_created_at(user),
            detail="get_user 200",
        )


class IamPolicyFalsifier(_IamFalsifier):
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
        expected_account = _dimensions_of(row).get("aws_account") or None
        scoped = self._scope_check(candidate, account_id, expected_account)
        if scoped is not None:
            return scoped
        expected = Expected(source_id=arn, owner=None, name=name or None)
        client = self._iam_client(session)
        return self._probe_call(candidate, expected, lambda: client.get_policy(PolicyArn=arn))

    def _probe_of(self, result: dict[str, Any]) -> Probe:
        policy = result.get("Policy") or {}
        return Probe(
            status="found",
            source_id=str(policy.get("Arn") or "") or None,
            name=str(policy.get("PolicyName") or "") or None,
            created_at=_created_at(policy),
            detail="get_policy 200",
        )


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

    **Known limitation, not fixed here: ``ListAllMyBuckets`` covers general-purpose buckets
    only.** S3 directory buckets (S3 Express One Zone) and Outposts buckets do not appear in the
    ``list_buckets`` response used for the tie-break above; a directory/Outposts bucket that
    answers an ambiguous ``HeadBucket`` status would read as absent from an inventory that was
    never going to contain it, and could misread as gone. The model does not currently carry a
    bucket-type field to gate on, so this falsifier cannot distinguish the two kinds of bucket at
    all — named here rather than guessed around, matching this module's own "AWS RAM share"
    limitation note on ``_scope_check``.
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
        expected_account = _dimensions_of(row).get("aws_account") or None
        scoped = self._scope_check(candidate, account_id, expected_account)
        if scoped is not None:
            return scoped
        if not _arn_names_s3_bucket(arn, name):
            # head_bucket takes Bucket=name, never the ARN: without this check, a row whose two
            # independently-stored fields have drifted apart would probe a DIFFERENT bucket than
            # the one its own ARN names, and that bucket's presence/absence could be misapplied
            # to the ARN the grid actually recorded.
            return _undetermined(
                candidate,
                "scope_unknown",
                f"the grid's stored name ({name!r}) does not match its own bucket_arn ({arn!r}); probing by "
                "name would ask about a different bucket than the one this ARN claims to be",
            )
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


# ---------------------------------------------------------------------------
# IAM OIDC provider (tap-plugin-aws-core#43)
# ---------------------------------------------------------------------------


class IamOidcProviderFalsifier(_AwsFalsifier):
    """``iam:GetOpenIDConnectProvider`` (global) in the candidate's own account; the response
    carries no separate id to compare, since the request itself is by ARN.

    A candidate reaches this falsifier only once ``OWNS_OIDC_PROVIDER__aws_core`` makes an OIDC
    provider node reconcilable (tap-plugin-aws-core#43) — this class has no dependency on that; it
    only judges whatever candidate it is handed, the same discipline ``SubnetFalsifier`` follows.

    Identity is the provider's ARN, and ``GetOpenIDConnectProvider`` is looked up BY that ARN, so a
    "found" response is definitionally about the requested object — the same reasoning
    ``IamPolicyFalsifier`` (aws-core-tap#41) gives for why a customer-managed policy can never
    answer ``REIDENTIFIED``. Ownership is implicit in the ARN's own account segment
    (``arn:<partition>:iam::<account>:oidc-provider/...``), which is exactly what
    ``_scope_check`` already gates on before any call is made — the response carries no separate
    owner field to cross-check, so ``Expected.owner`` and ``Probe.owner`` are both left unset here
    (the ``owner_not_compared`` convention ``SubnetFalsifier`` uses when the grid holds none).
    """

    def judge(self, session: ProbeSession, account_id: str, candidate: Candidate) -> Verdict:
        row = _row_of(candidate.entity_id)
        if row is None:
            return _undetermined(candidate, "errored", "the grid row could not be read")
        arn = str(getattr(row, "provider_arn", "") or "")
        if not arn:
            return _undetermined(candidate, "scope_unknown", "the grid holds no provider_arn for this provider")
        expected_account = _dimensions_of(row).get("aws_account") or None
        scoped = self._scope_check(candidate, account_id, expected_account)
        if scoped is not None:
            return scoped
        expected = Expected(source_id=arn, name=str(getattr(row, "name", "") or "") or None)
        try:
            # The ARN's own partition decides the region, never a hardcoded us-east-1 (aws-core-tap#43):
            # GovCloud has no us-east-1 at all, and this falsifier must reach whatever partition
            # collected the row.
            client = session.client("iam", region_name=iam_endpoint_region(arn))
            result = client.get_open_id_connect_provider(OpenIDConnectProviderArn=arn)
        except ClientError as exc:
            status = probe_status_of(exc)
            detail = NOT_FOUND_DETAIL if status == "not_found" else f"{error_code_of(exc)}: {exc}"
            return verdict_from_probe(candidate, expected, Probe(status=status, detail=detail))  # type: ignore[arg-type]
        except BotoCoreError as exc:
            return verdict_from_probe(candidate, expected, Probe(status="errored", detail=str(exc)))
        probe = Probe(
            status="found", source_id=arn, name=str(result.get("Url") or "") or None, detail="GetOpenIDConnectProvider 200"
        )
        return verdict_from_probe(candidate, expected, probe)


# ---------------------------------------------------------------------------
# Landing zone (aws-core-tap#66, spec-aws-core-landing-zone.md): Control Tower, Identity Center and
# the per-region security services. Registered, not armed: reconcile authority stays off, so none of
# these is dispatched in production until a later step arms it.
#
# Every not-found code below was checked against botocore 1.43.107's error list and documentation
# for the operation (aws-core-tap#15's rule): each is distinct from that operation's "you may not
# look" code. securityhub:DescribeHub is the exception: its InvalidAccessException is documented as
# "the account doesn't have permission to perform this action", which is also what an account
# without Security Hub receives, so that code is UNDETERMINED, never a drop.
# ---------------------------------------------------------------------------


class _ProbePagesExceeded(Exception):
    """A continuation chain that never ended: the probe could not answer."""


def _probe_all(fn: Callable[..., dict[str, Any]], result_key: str, *, token: str = "NextToken", **params: Any) -> list[Any]:
    """Every item of a paginated probe call, read to its last page (``req-aws-collector-pagination-1``).
    Raises what the call raises; a failure on any page leaves the probe unanswered (``-2``)."""
    items: list[Any] = []
    next_token: str | None = None
    for _ in range(_MAX_PROBE_PAGES):
        kwargs = dict(params)
        if next_token:
            kwargs[token] = next_token
        response = fn(**kwargs)
        items.extend(response.get(result_key) or [])
        next_token = response.get(token)
        if not next_token:
            return items
    raise _ProbePagesExceeded(f"{result_key}: the continuation chain did not end")


def _arn_account(arn: str) -> str | None:
    """The account segment of an ARN, or None."""
    from tap_plugin.aws_core.collectors.boto3_collector.partition import parse_arn

    parsed = parse_arn(arn)
    return parsed.account if parsed and parsed.account and parsed.account != "aws" else None


def _arn_region(arn: str) -> str:
    from tap_plugin.aws_core.collectors.boto3_collector.partition import parse_arn

    parsed = parse_arn(arn)
    return parsed.region if parsed else ""


def _failed_probe(candidate: Candidate, expected: Expected, exc: Exception, *, gone_codes: frozenset[str] = frozenset()) -> Verdict:
    """The verdict for a probe call that raised. ``gone_codes`` names the operation's own verified
    not-found codes beyond the generic ``*NotFound*`` shapes; everything else that is not a
    not-found is ``UNDETERMINED`` through ``verdict_from_probe``'s own classification."""
    if isinstance(exc, ClientError):
        code = error_code_of(exc)
        status = "not_found" if code in gone_codes else probe_status_of(exc)
        detail = NOT_FOUND_DETAIL if status == "not_found" else f"{code}: the probe could not answer"
        return verdict_from_probe(candidate, expected, Probe(status=status, detail=detail))  # type: ignore[arg-type]
    return verdict_from_probe(candidate, expected, Probe(status="errored", detail=type(exc).__name__))


class _LandingZoneFalsifier(_AwsFalsifier):
    """Shared shape: read the row, check the account, find the region, probe once.

    Every landing-zone type is regional (Control Tower and Identity Center in their home region),
    and the collector stamps that region on ``dimensions["aws_region"]``, so it is trusted. A row
    with no region is refused (``scope_unknown``), never swept: these listings are cheap to read
    whole, but a sweep could only show where a resource is, never where it was collected.
    """

    service = ""

    def _region_hint(self, row: Any) -> str | None:
        return None

    def judge(self, session: ProbeSession, account_id: str, candidate: Candidate) -> Verdict:
        row = _row_of(candidate.entity_id)
        if row is None:
            return _undetermined(candidate, "errored", "the grid row could not be read")
        dimensions = _dimensions_of(row)
        expected_account = dimensions.get("aws_account") or None
        scoped = self._scope_check(candidate, account_id, expected_account)
        if scoped is not None:
            return scoped
        region = self._region_hint(row) or dimensions.get("aws_region") or ""
        if not region or region == "global":
            return _undetermined(candidate, "scope_unknown", "the grid holds no region for this resource")
        try:
            client = session.client(self.service, region_name=region)
        except Exception as exc:  # noqa: BLE001 — an unbuildable client is an answer, not a crash
            return _undetermined(candidate, "errored", f"{self.service} client unavailable: {type(exc).__name__}")
        try:
            return self._probe(client, row, candidate, expected_account or "")
        except (ClientError, BotoCoreError, _ProbePagesExceeded) as exc:
            return self._failed(candidate, row, expected_account or "", exc)

    def _expected(self, row: Any, expected_account: str) -> Expected:
        raise NotImplementedError

    def _probe(self, client: Any, row: Any, candidate: Candidate, expected_account: str) -> Verdict:
        raise NotImplementedError

    #: This operation's verified not-found codes beyond the generic ``*NotFound*`` shapes.
    gone_codes: frozenset[str] = frozenset()

    def _failed(self, candidate: Candidate, row: Any, expected_account: str, exc: Exception) -> Verdict:
        expected = self._expected(row, expected_account)
        if not expected.source_id:
            return _undetermined(candidate, "scope_unknown", "the grid holds no source identity for this resource")
        return _failed_probe(candidate, expected, exc, gone_codes=self.gone_codes)


class _GetByArnFalsifier(_LandingZoneFalsifier):
    """A ``Get*``/``Describe*`` by ARN whose ``ResourceNotFoundException`` is the operation's own
    not-found (read: botocore 1.43.107, distinct from its ``AccessDeniedException``). The owner is the
    account in the ARN, compared with the account the row was collected under."""

    arn_field = ""

    def _region_hint(self, row: Any) -> str | None:
        return _arn_region(str(getattr(row, self.arn_field, "") or "")) or None

    def _expected(self, row: Any, expected_account: str) -> Expected:
        arn = str(getattr(row, self.arn_field, "") or "")
        # The owner is compared only when the ARN carries an account to compare it with.
        owner = (expected_account or None) if _arn_account(arn) else None
        return Expected(source_id=arn, owner=owner)

    def _probe(self, client: Any, row: Any, candidate: Candidate, expected_account: str) -> Verdict:
        expected = self._expected(row, expected_account)
        if not expected.source_id:
            return _undetermined(candidate, "scope_unknown", f"the grid holds no {self.arn_field} for this resource")
        found = self._get(client, row, expected.source_id)
        probe = Probe(status="found", source_id=found or None, owner=_arn_account(found), detail=f"{self.service} probe 200")
        return _finish(candidate, expected, probe)

    def _get(self, client: Any, row: Any, arn: str) -> str:
        """The ARN AWS reports for the object the grid's ARN names. Raises what the call raises."""
        raise NotImplementedError


class LandingZoneFalsifier(_GetByArnFalsifier):
    """``controltower:GetLandingZone(landingZoneIdentifier)``; ``ResourceNotFoundException`` is
    ``DROPPED_FROM_OBSERVATION`` (``req-aws-landing-zone-control-tower-3``)."""

    service = "controltower"
    arn_field = "landing_zone_arn"

    def _get(self, client: Any, row: Any, arn: str) -> str:
        return str((client.get_landing_zone(landingZoneIdentifier=arn).get("landingZone") or {}).get("arn") or "")


class EnabledControlFalsifier(_GetByArnFalsifier):
    """``controltower:GetEnabledControl(enabledControlIdentifier)``."""

    service = "controltower"
    arn_field = "enabled_control_arn"

    def _get(self, client: Any, row: Any, arn: str) -> str:
        return str((client.get_enabled_control(enabledControlIdentifier=arn).get("enabledControlDetails") or {}).get("arn") or "")


class EnabledBaselineFalsifier(_GetByArnFalsifier):
    """``controltower:GetEnabledBaseline(enabledBaselineIdentifier)``."""

    service = "controltower"
    arn_field = "enabled_baseline_arn"

    def _get(self, client: Any, row: Any, arn: str) -> str:
        return str((client.get_enabled_baseline(enabledBaselineIdentifier=arn).get("enabledBaselineDetails") or {}).get("arn") or "")


class ConfigAggregatorFalsifier(_GetByArnFalsifier):
    """``config:DescribeConfigurationAggregators(ConfigurationAggregatorNames=[name])``;
    ``NoSuchConfigurationAggregatorException`` ("you have specified a configuration aggregator that
    does not exist", botocore) is ``DROPPED_FROM_OBSERVATION``."""

    service = "config"
    arn_field = "aggregator_arn"
    gone_codes = frozenset({"NoSuchConfigurationAggregatorException"})

    def _get(self, client: Any, row: Any, arn: str) -> str:
        name = str(getattr(row, "aggregator_name", "") or "") or arn.rsplit("/", 1)[-1]
        found = client.describe_configuration_aggregators(ConfigurationAggregatorNames=[name]).get("ConfigurationAggregators") or []
        return str((found[0] if found else {}).get("ConfigurationAggregatorArn") or "")


class SecurityHubHubFalsifier(_GetByArnFalsifier):
    """``securityhub:DescribeHub(HubArn)``. ``ResourceNotFoundException`` is ``DROPPED_FROM_OBSERVATION``.
    ``InvalidAccessException`` is documented as "the account doesn't have permission to perform this
    action", and is also the answer for an account that disabled Security Hub: the two cannot be told
    apart, so it is ``UNDETERMINED(forbidden)``, never a drop."""

    service = "securityhub"
    arn_field = "hub_arn"

    def _get(self, client: Any, row: Any, arn: str) -> str:
        return str(client.describe_hub(HubArn=arn).get("HubArn") or "")

    def _failed(self, candidate: Candidate, row: Any, expected_account: str, exc: Exception) -> Verdict:
        if isinstance(exc, ClientError) and error_code_of(exc) == "InvalidAccessException":
            return _undetermined(
                candidate, "forbidden", "InvalidAccessException: Security Hub disabled and access refused share this code"
            )
        return super()._failed(candidate, row, expected_account, exc)


class AccessAnalyzerFalsifier(_GetByArnFalsifier):
    """``accessanalyzer:GetAnalyzer(analyzerName)``; ``ResourceNotFoundException`` is
    ``DROPPED_FROM_OBSERVATION``."""

    service = "accessanalyzer"
    arn_field = "analyzer_arn"

    def _get(self, client: Any, row: Any, arn: str) -> str:
        name = str(getattr(row, "analyzer_name", "") or "") or arn.rsplit("/", 1)[-1]
        return str((client.get_analyzer(analyzerName=name).get("analyzer") or {}).get("arn") or "")


class _ListingFalsifier(_LandingZoneFalsifier):
    """Gone when a complete listing in the resource's own region no longer names it (the spec's
    "absent from <listing>"). A listing that failed on any page answers nothing. A key cannot come
    back under another identity in a listing looked up by that same key, so ``REIDENTIFIED`` is
    structurally impossible here; the tests prove present, dropped and forbidden one by one."""

    def _identity(self, row: Any) -> str:
        raise NotImplementedError

    def _listed(self, client: Any, row: Any) -> dict[str, str | None]:
        """``{identity: owner}`` for every object the listing names."""
        raise NotImplementedError

    def _owner_of(self, row: Any, expected_account: str) -> str | None:
        return None

    def _expected(self, row: Any, expected_account: str) -> Expected:
        return Expected(source_id=self._identity(row), owner=self._owner_of(row, expected_account))

    def _probe(self, client: Any, row: Any, candidate: Candidate, expected_account: str) -> Verdict:
        expected = self._expected(row, expected_account)
        if not expected.source_id:
            return _undetermined(candidate, "scope_unknown", "the grid holds no source identity for this resource")
        listed = self._listed(client, row)
        if expected.source_id not in listed:
            return verdict_from_probe(candidate, expected, Probe(status="not_found", detail="the complete listing no longer names it"))
        probe = Probe(status="found", source_id=expected.source_id, owner=listed[expected.source_id], detail="the listing names it")
        return _finish(candidate, expected, probe)


class IdentityCenterInstanceFalsifier(_ListingFalsifier):
    """Absent from ``sso-admin:ListInstances`` in its home region (read to its last page). The owner
    is the instance's ``OwnerAccountId``, compared when the grid holds one."""

    service = "sso-admin"

    def _region_hint(self, row: Any) -> str | None:
        return str(getattr(row, "home_region", "") or "") or None

    def _identity(self, row: Any) -> str:
        return str(getattr(row, "instance_arn", "") or "")

    def _owner_of(self, row: Any, expected_account: str) -> str | None:
        return str(getattr(row, "owner_account_id", "") or "") or None

    def _listed(self, client: Any, row: Any) -> dict[str, str | None]:
        return {
            str(i.get("InstanceArn") or ""): str(i.get("OwnerAccountId") or "") or None
            for i in _probe_all(client.list_instances, "Instances")
        }


class ConfigRecorderFalsifier(_ListingFalsifier):
    """Absent from ``config:ListConfigurationRecorders`` (paginated, unfiltered) in its region."""

    service = "config"

    def _region_hint(self, row: Any) -> str | None:
        return _arn_region(str(getattr(row, "recorder_arn", "") or "")) or None

    def _identity(self, row: Any) -> str:
        return str(getattr(row, "recorder_arn", "") or "")

    def _owner_of(self, row: Any, expected_account: str) -> str | None:
        return (expected_account or None) if _arn_account(self._identity(row)) else None

    def _listed(self, client: Any, row: Any) -> dict[str, str | None]:
        summaries = _probe_all(client.list_configuration_recorders, "ConfigurationRecorderSummaries")
        return {str(r.get("arn") or ""): _arn_account(str(r.get("arn") or "")) for r in summaries}


class ConfigDeliveryChannelFalsifier(_ListingFalsifier):
    """Absent from ``config:DescribeDeliveryChannels`` (one call, not paginated) in its region."""

    service = "config"

    def _region_hint(self, row: Any) -> str | None:
        return str(getattr(row, "region", "") or "") or None

    def _identity(self, row: Any) -> str:
        return str(getattr(row, "channel_name", "") or "")

    def _listed(self, client: Any, row: Any) -> dict[str, str | None]:
        return {str(c.get("name") or ""): None for c in client.describe_delivery_channels().get("DeliveryChannels") or []}


class GuardDutyDetectorFalsifier(_ListingFalsifier):
    """Absent from ``guardduty:ListDetectors`` (read to its last page) in its region. ``GetDetector``'s
    only failure code is the generic ``BadRequestException``, which cannot say "gone", so the listing
    is the probe."""

    service = "guardduty"

    def _region_hint(self, row: Any) -> str | None:
        return str(getattr(row, "region", "") or "") or None

    def _identity(self, row: Any) -> str:
        return str(getattr(row, "detector_id", "") or "")

    def _listed(self, client: Any, row: Any) -> dict[str, str | None]:
        return {str(d): None for d in _probe_all(client.list_detectors, "DetectorIds")}


class PermissionSetFalsifier(_LandingZoneFalsifier):
    """``sso-admin:DescribePermissionSet(InstanceArn, PermissionSetArn)``. Its
    ``ResourceNotFoundException`` names either the permission set or its instance; both mean the
    permission set is gone (an instance's permission sets go with it), so either is
    ``DROPPED_FROM_OBSERVATION``."""

    service = "sso-admin"

    def _expected(self, row: Any, expected_account: str) -> Expected:
        return Expected(source_id=str(getattr(row, "permission_set_arn", "") or ""))

    def _probe(self, client: Any, row: Any, candidate: Candidate, expected_account: str) -> Verdict:
        expected = self._expected(row, expected_account)
        instance = str(getattr(row, "instance_arn", "") or "")
        if not expected.source_id or not instance:
            return _undetermined(candidate, "scope_unknown", "the grid holds no (instance, permission set) ARN pair")
        found = client.describe_permission_set(InstanceArn=instance, PermissionSetArn=expected.source_id).get("PermissionSet") or {}
        probe = Probe(status="found", source_id=str(found.get("PermissionSetArn") or "") or None, detail="DescribePermissionSet 200")
        return _finish(candidate, expected, probe)


class IdentityGroupFalsifier(_LandingZoneFalsifier):
    """``identitystore:DescribeGroup(IdentityStoreId, GroupId)``. ``ResourceNotFoundException`` names
    the group or its identity store; either way the group is gone. A renamed group is
    ``RELOCATED(renamed)``, not retired."""

    service = "identitystore"

    def _expected(self, row: Any, expected_account: str) -> Expected:
        return Expected(source_id=str(getattr(row, "group_id", "") or ""), name=str(getattr(row, "display_name", "") or "") or None)

    def _probe(self, client: Any, row: Any, candidate: Candidate, expected_account: str) -> Verdict:
        expected = self._expected(row, expected_account)
        store = str(getattr(row, "identity_store_id", "") or "")
        if not expected.source_id or not store:
            return _undetermined(candidate, "scope_unknown", "the grid holds no (identity store, group) id pair")
        found = client.describe_group(IdentityStoreId=store, GroupId=expected.source_id)
        probe = Probe(
            status="found",
            source_id=str(found.get("GroupId") or "") or None,
            name=str(found.get("DisplayName") or "") or None,
            detail="DescribeGroup 200",
        )
        return _finish(candidate, expected, probe)


class AccountAssignmentFalsifier(_LandingZoneFalsifier):
    """``sso-admin:ListAccountAssignments(InstanceArn, AccountId, PermissionSetArn)``, read to its
    last page: does it still name the (principal type, principal id)?
    (``req-aws-landing-zone-identity-center-4``, ``-6``.)

    - A complete answer that names it: ``PRESENT_AT_PROBE``. One that does not:
      ``DROPPED_FROM_OBSERVATION``.
    - ``ResourceNotFoundException`` alone proves nothing: sso-admin raises it for the instance, the
      account and the permission set alike (read: botocore). Two probes disambiguate:
      ``DescribePermissionSet`` answering not-found means the permission set is gone (dropped); else
      the account's absence from the organization, proven by ``organizations:DescribeAccount``
      answering ``AccountNotFoundException`` after the credential's organization reach is proven and
      the credential is the instance's owner (dropped: an assignment to a departed account would
      otherwise stay forever). Neither confirmed: ``UNDETERMINED``.

    The account probe is the one ``AccountFalsifier`` makes today. When the membership node lands
    (aws-core-tap#68, ``req-aws-core-organization-membership-4``) it is the membership falsifier's.
    """

    service = "sso-admin"

    def __init__(self, *args: Any, org_region: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._org_region = org_region
        self._session_for_org: ProbeSession | None = None
        self._credential_account = ""

    def _organizations_region(self) -> str:
        if self._org_region is None:
            self._org_region = resolve_regions(dict(resolve_aws_secret().data))[0]
        return self._org_region

    def _expected(self, row: Any, expected_account: str) -> Expected:
        principal = f"{getattr(row, 'principal_type', '') or ''}:{getattr(row, 'principal_id', '') or ''}"
        return Expected(source_id=principal if principal != ":" else "")

    def judge(self, session: ProbeSession, account_id: str, candidate: Candidate) -> Verdict:
        self._session_for_org = session
        self._credential_account = account_id
        return super().judge(session, account_id, candidate)

    def _probe(self, client: Any, row: Any, candidate: Candidate, expected_account: str) -> Verdict:
        expected = self._expected(row, expected_account)
        instance = str(getattr(row, "instance_arn", "") or "")
        member = str(getattr(row, "account_id", "") or "")
        permission_set = str(getattr(row, "permission_set_arn", "") or "")
        if not expected.source_id or not instance or not member or not permission_set:
            return _undetermined(candidate, "scope_unknown", "the grid holds no complete assignment key")
        try:
            listed = _probe_all(
                client.list_account_assignments, "AccountAssignments", InstanceArn=instance, AccountId=member, PermissionSetArn=permission_set
            )
        except ClientError as exc:
            if error_code_of(exc) != "ResourceNotFoundException":
                raise
            return self._disambiguate(client, row, candidate, expected, instance, member, permission_set)
        named = {f"{a.get('PrincipalType') or ''}:{a.get('PrincipalId') or ''}" for a in listed}
        if expected.source_id not in named:
            return verdict_from_probe(candidate, expected, Probe(status="not_found", detail="ListAccountAssignments no longer names the principal"))
        return _finish(candidate, expected, Probe(status="found", source_id=expected.source_id, detail="ListAccountAssignments names the principal"))

    def _disambiguate(
        self, client: Any, row: Any, candidate: Candidate, expected: Expected, instance: str, member: str, permission_set: str
    ) -> Verdict:
        try:
            client.describe_permission_set(InstanceArn=instance, PermissionSetArn=permission_set)
        except ClientError as exc:
            if error_code_of(exc) == "ResourceNotFoundException":
                return verdict_from_probe(
                    candidate, expected, Probe(status="not_found", detail="DescribePermissionSet: the permission set is gone")
                )
            return _unanswered(candidate, exc)
        except BotoCoreError as exc:
            return _unanswered(candidate, exc)
        departed = self._account_departed(candidate, member)
        if isinstance(departed, Verdict):
            return departed
        if departed:
            return verdict_from_probe(
                candidate, expected, Probe(status="not_found", detail="DescribeAccount: the account is no longer in the organization")
            )
        return _undetermined(
            candidate,
            "errored",
            "ListAccountAssignments answered ResourceNotFoundException, but neither the permission set nor the account is confirmed gone",
        )

    def _account_departed(self, candidate: Candidate, member: str) -> bool | Verdict:
        """True when the organization proves ``member`` is no longer in it; False when it is still
        there; an ``UNDETERMINED`` verdict when that cannot be proven."""
        owner = str(getattr(_row_of(candidate.parent), "owner_account_id", "") or "") if candidate.parent else ""
        if not owner or owner != self._credential_account:
            return _undetermined(
                candidate,
                "scope_unknown",
                "the credential is not recorded as this assignment's instance owner, so its organization says nothing about the account",
            )
        try:
            if self._session_for_org is None:
                raise RuntimeError("no session")
            org = self._session_for_org.client("organizations", region_name=self._organizations_region())
        except Exception as exc:  # noqa: BLE001 — an unbuildable client is an answer, not a crash
            return _undetermined(candidate, "errored", f"organizations client unavailable: {type(exc).__name__}")
        reach = _read_org_reach(org)
        if reach.status != "ok":
            return _undetermined(candidate, reach.status, reach.note)
        try:
            org.describe_account(AccountId=member)
        except ClientError as exc:
            if error_code_of(exc) == "AccountNotFoundException":
                return True
            return _unanswered(candidate, exc)
        except BotoCoreError as exc:
            return _unanswered(candidate, exc)
        return False


__all__ = [
    "NOT_FOUND_DETAIL",
    "AccessAnalyzerFalsifier",
    "AccountAssignmentFalsifier",
    "AccountFalsifier",
    "ConfigAggregatorFalsifier",
    "ConfigDeliveryChannelFalsifier",
    "ConfigRecorderFalsifier",
    "EnabledBaselineFalsifier",
    "EnabledControlFalsifier",
    "GuardDutyDetectorFalsifier",
    "IdentityCenterInstanceFalsifier",
    "IdentityGroupFalsifier",
    "LandingZoneFalsifier",
    "PermissionSetFalsifier",
    "SecurityHubHubFalsifier",
    "Ec2InstanceFalsifier",
    "IamOidcProviderFalsifier",
    "IamPolicyFalsifier",
    "IamRoleFalsifier",
    "IamUserFalsifier",
    "OrganizationalUnitFalsifier",
    "S3BucketFalsifier",
    "SecurityGroupFalsifier",
    "SubnetFalsifier",
    "VpcFalsifier",
    "error_code_of",
    "probe_status_of",
]
