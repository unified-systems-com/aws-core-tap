"""Per-type falsifiers for aws_core's compute + network resources.

A retirement candidate (``tap_grid.candidates``) is a child the grid holds under a parent
whose listing this run read completely and did not name it. Nothing is retired on that
alone: a **falsifier** — one per entity type, declared in ``[falsifiers]`` of
``tap-plugin.toml`` — probes AWS for each candidate and hands what it found to
``tap_grid.falsifiers.verdict_from_probe``, which derives the verdict. HTTP/API success is not
a verdict; the identity is compared, never the status line, mirroring the pattern
``tap_plugin.github_core.falsifiers.RepositoryFalsifier`` established for this same core
mechanism (one API call per object, 404 = ``not_found``, compare a stable id). Authority stays
off here: the verdicts are recorded on the run's lifecycle batch and the reconcile verb
(``tap_grid.reconcile``) is what would act on them.

Covers the four most fundamental compute + network types, matching the models this plugin
already carries (``tap_plugin.aws_core.models``):

- ``aws_core__aws_vpc`` — ``VpcFalsifier``: ``describe_vpcs(VpcIds=[...])``;
  ``InvalidVpcID.NotFound`` is the not-found code.
- ``aws_core__aws_subnet`` — ``SubnetFalsifier``: ``describe_subnets(SubnetIds=[...])``;
  ``InvalidSubnetID.NotFound``.
- ``aws_core__aws_ec2_instance`` — ``Ec2InstanceFalsifier``: ``describe_instances(InstanceIds=
  [...])``; ``InvalidInstanceID.NotFound``. AWS keeps a *terminated* instance visible for a
  while rather than 404ing it immediately, so a successful response whose ``State.Name`` is
  ``terminated`` is treated as gone too — ``stopped`` is not: the instance is still there, only
  not running.
- ``aws_core__aws_security_group`` — ``SecurityGroupFalsifier``:
  ``describe_security_groups(GroupIds=[...])``; ``InvalidGroup.NotFound``.

**No stored region (the substitution this plugin's models force).** None of the four models
carries a ``region`` field — unlike ``transit_gateway.py`` / ``dx_connection.py`` /
``vpc_endpoint.py`` / ``route53_resolver_firewall_rule_group.py``, which do. Every describe
call above is region-scoped, so without a region on the row a falsifier cannot address a
single API call the way ``RepositoryFalsifier`` does. Rather than invent a schema change
mid-PR (a natural key that already resolves cleanly to ``vpc_id`` / ``subnet_id`` / ``group_id``
/ ``instance_id`` would need to move, or a new field would need a migration — either is a
model-level decision this PR does not make unilaterally), ``_Ec2Falsifier`` sweeps the
credential's own configured region scope (``resolve_regions``, the exact list the collector
itself sweeps) and stops at the first region that answers authoritatively. AWS resource ids in
this shape (``vpc-…`` / ``subnet-…`` / ``sg-…`` / ``i-…``) are minted per region and never
reused across regions in the same partition, so one authoritative answer (found, or an
instance confirmed terminated) settles it; ``not_found`` is only allowed to stand once *every*
configured region has said so — a region that refused or errored could be hiding the object,
so it is never let through as a retirement (fail closed). ``SubnetFalsifier`` shortcuts this:
the model already carries ``availability_zone`` (e.g. ``us-east-1a``), so its region is tried
first, before the sweep — extracted with ``_STANDARD_REGION_PREFIX`` rather than
``availability_zone[:-1]``, which mishandles a Local Zone or Wavelength Zone AZ
(``us-west-2-lax-1a``'s parent region is ``us-west-2``, not ``us-west-2-lax-1``). Client
construction for a derived region lives inside ``_describe_one``'s guarded try/except, not
before it, so a region string boto3 cannot resolve degrades that one candidate to
``UNDETERMINED(errored)`` rather than raising out of the whole batch.

**One credential, this plugin's own current region scope — not a new limitation (AI review,
PR #44).** Two related findings asked whether sweeping only *currently configured* regions
under *one* credential could retire a row this run simply cannot see (a resource collected
under a wider region scope that was later narrowed; a resource in another AWS account). Both
describe a real class of risk, but neither is new here, and neither is this falsifier's to
solve: ``AWS_SECRET_REF`` (``collectors/boto3_collector/credentials.py``) is a single constant
key — "v0 has no per-instance config" is the module's own docstring — so the boto3 collector
itself can observe exactly one account and exactly its own ``resolve_regions()`` scope; no
``aws_core__aws_vpc`` / ``aws_ec2_instance`` / ``aws_security_group`` row on the grid can
currently have been collected from anywhere this same falsifier cannot also reach, because
nothing else populates those types. A region narrowed out of ``regions_allowed`` already stops
the collector from observing that region's resources at all, on every run, not only a
falsifier's; a falsifier that swept a wider scope than the collector currently uses would be
the inconsistent choice, not this one. Multi-account / multi-credential support, if it
arrives, is a `_default_session` change (and an equivalent to GitHub's reach-narrowing
re-confirmation, ``tap_plugin.github_core.falsifiers._reach_after_probe``, would become the
right shape here too) — flagged for whoever builds it, not solved by inventing scope this
plugin does not have yet.

**Cascade (``CONTAINMENT_EDGES``) — what exists, what does not, and why nothing here adds it.**

- ``aws_core__aws_subnet`` is already covered: ``Vpc.CONTAINMENT_EDGES`` (``vpc.py``) declares
  ``PARTITIONED_INTO_SUBNET__aws_core``, so a VPC retiring already retires its subnets. No
  change needed.
- ``aws_core__aws_vpc`` and ``aws_core__aws_ec2_instance`` have ``BELONGS_TO_ACCOUNT__aws_core``
  reaching them from ``aws_core__aws_account``, but that edge's own manifest description
  states it is deliberately "a reference, not containment: a resource shared through AWS RAM is
  used from other accounts, and an account's subtree can exceed the cascade cap." Wiring
  account-root containment is the sibling foundation work this PR was told to coordinate with
  ("first CONTAINMENT_EDGES on the account/org root") — at the time this was written no such
  PR was visible on this repo (``gh pr list`` / ``gh api .../branches``), so nothing is added
  here to avoid colliding with it. Once it lands (whatever edge it uses to reach
  ``aws_vpc`` / ``aws_ec2_instance``), these two falsifiers are already registered and start
  producing real candidates with no further change on this side.
- ``aws_core__aws_security_group`` has no containment path at all today, and none is added
  here: the only edge reaching it, ``RESIDES_IN_VPC__aws_core``, runs security_group -> vpc
  (its own manifest description says so explicitly: "A reference, not containment (containment
  edges must point parent -> child)"), and the containment mechanism
  (``tap_grid.candidates.derive_candidates``) requires the edge to run parent -> child — it
  fans out FROM the declared parent. ``Vpc.py`` already documents this as a deliberate stop:
  "VPC-wide resources (security groups, route tables) point at the VPC with RESIDES_IN_VPC,
  which a cascade from the VPC cannot follow." Reversing that — a new VPC -> security-group
  edge duplicating ``RESIDES_IN_VPC`` in the other direction purely so cascade can walk it — is
  a real option but a deliberate architecture call (two edges stating the same relationship
  in opposite directions) that is out of scope for a falsifier PR to make unilaterally.
  ``SecurityGroupFalsifier`` is still registered and correct on its own terms (a straight
  listing-refresh of security groups would still produce candidates it can judge; the gap is
  only the parent-delete cascade path), and this is called out as an open question, not solved
  here.

Every probe is a single-object read via this plugin's own collector credential
(``tap_plugin.aws_core.collectors.boto3_collector.credentials``, resolved here, never taken
from the run context); no response body beyond the compared fields is recorded — ``Probe.detail``
carries an HTTP-style status/error-code summary only, mirroring the same discipline
``github_core``'s falsifiers hold to.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Sequence
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from tap_grid.falsifiers import (
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

from tap_plugin.aws_core.collectors.boto3_collector.credentials import (
    AWS_SECRET_REF,
    assume_role_session,
    build_session,
    is_assumed_role,
    resolve_aws_secret,
    resolve_regions,
)

logger = logging.getLogger(__name__)

#: What a probe needs of the client: an authenticated boto3 EC2 client, region-bound.
ProbeClient = Any

#: AWS authorization-failure codes — mirrors ``hydrate._DENIED_CODES`` / ``ledger._DENIED``
#: (this plugin's own established vocabulary for "could not read", value unknown). Kept as its
#: own copy rather than importing those private, underscore-prefixed module constants: each
#: boto3-error-classifying module in this collector owns its table by the same convention
#: ``hydrate.py`` documents ("a future cleanup may factor a single shared classifier; not now").
_FORBIDDEN_CODES = frozenset(
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
#: Mirrors ``ledger._THROTTLED``.
_THROTTLED_CODES = frozenset(
    {
        "RequestLimitExceeded",
        "Throttling",
        "ThrottlingException",
        "ThrottledException",
        "TooManyRequestsException",
        "429",
    }
)

#: The standard AWS region a plain availability zone name is prefixed with — ``us-east-1`` out
#: of ``us-east-1a``. Deliberately NOT ``az[:-1]`` (AI review, PR #44): a Local Zone or
#: Wavelength Zone AZ (``us-west-2-lax-1a``, ``us-east-1-wl1-bos-wlz-1``) carries the parent
#: region as this same leading ``xx-name-N`` shape, with an extra zone-specific suffix that
#: ``[:-1]`` would fold into the "region" instead of discarding — producing a string boto3 has
#: no endpoint for. Matching the shape explicitly and taking only the matched prefix handles
#: both a standard AZ and every zone-suffixed variant the same way, without special-casing them.
_STANDARD_REGION_PREFIX = re.compile(r"^([a-z]{2}(?:-gov)?-[a-z]+-\d+)")


def _default_session() -> tuple[Any, list[str]]:
    """The collector's own credential and region scope — the exact resolution the boto3
    collector itself uses (``credentials.py``), so a falsifier probes the same account and the
    same regions this plugin was configured to collect from."""
    secret = resolve_aws_secret(AWS_SECRET_REF)
    data = dict(secret.data)
    regions = resolve_regions(data)
    if is_assumed_role(data):
        base = build_session(data["base"])
        session = assume_role_session(base, data, regions[0])
    else:
        session = build_session(data)
    return session, regions


def _error_status(exc: ClientError, not_found_code: str) -> str:
    """The closed probe status a ``ClientError`` maps to: this type's own not-found code is
    ``not_found``; an authorization failure is ``forbidden``; a throttle is ``rate_limited``;
    everything else is ``errored`` — the probe could not answer."""
    code = str((exc.response or {}).get("Error", {}).get("Code", ""))
    if code == not_found_code:
        return "not_found"
    if code in _FORBIDDEN_CODES:
        return "forbidden"
    if code in _THROTTLED_CODES:
        return "rate_limited"
    return "errored"


def _error_detail(exc: ClientError) -> str:
    error = (exc.response or {}).get("Error", {})
    meta = (exc.response or {}).get("ResponseMetadata", {})
    code = error.get("Code", "Unknown")
    status = meta.get("HTTPStatusCode", "")
    return f"HTTP {status} ({code})" if status else f"({code})"


def _row_of(entity_id: uuid.UUID | None) -> Any | None:
    """The typed grid row behind an entity id through the service read, or None when it
    cannot be read (unknown id, unknown type, an edge)."""
    if entity_id is None:
        return None
    try:
        return get_node(entity_id)
    except Exception:  # noqa: BLE001 — a candidate the grid cannot show is answered, not raised
        logger.warning("[a1f3] falsifier could not read grid row %s", entity_id)
        return None


def _undetermined(candidate: Candidate, reason: str, note: str) -> Verdict:
    return Verdict(entity_id=candidate.entity_id, verdict=UNDETERMINED, reason=reason, surface=candidate.surface, note=note)


class _Ec2Falsifier(Falsifier):
    """The shared shape for the four EC2/VPC falsifiers: resolve one boto3 session per run,
    sweep the credential's configured regions per candidate (see the module docstring for why),
    fail closed.

    Subclasses declare the describe operation's shape (``_method``, ``ids_param``,
    ``not_found_code``, ``list_key``, ``item_id_key``) and the row's natural-key field
    (``_expected_of``); ``Ec2InstanceFalsifier`` additionally overrides ``_probe_from_response``
    to fold the terminated-state rule in.

    ``client_for`` / ``regions`` are injected by tests (bypassing real credential resolution
    entirely, the way ``RepositoryFalsifier`` accepts ``client=fake``); at runtime both are
    resolved from the collector's own secret on first use, via ``session_factory``.
    """

    #: The manifest ``service`` name (aws_resource_manifest.json convention): all four are EC2.
    service: str = "ec2"
    #: The AWS error code that means "gone" for this type's describe call.
    not_found_code: str = ""
    #: The describe call's id-list kwarg, e.g. ``"VpcIds"``.
    ids_param: str = ""
    #: The response key holding the list of found items, e.g. ``"Vpcs"``.
    list_key: str = ""
    #: The found item's own id field, e.g. ``"VpcId"``.
    item_id_key: str = ""

    def __init__(
        self,
        client_for: Callable[[str, str], ProbeClient] | None = None,
        regions: Sequence[str] | None = None,
        session_factory: Callable[[], tuple[Any, list[str]]] | None = None,
    ) -> None:
        self._client_for = client_for
        self._regions_override = list(regions) if regions is not None else None
        self._session_factory = session_factory or _default_session

    def _method(self) -> str:
        raise NotImplementedError

    def _expected_of(self, row: Any) -> Expected | None:
        raise NotImplementedError

    def _regions_for(self, row: Any, regions: list[str]) -> list[str]:
        """The region try-order for one row. The default is the configured sweep order;
        ``SubnetFalsifier`` overrides this to try the row's own availability-zone-derived
        region first."""
        return list(regions)

    def _probe_from_response(self, response: dict[str, Any], source_id: str) -> Probe:
        """The default shape: a successful describe call for a single id always returns exactly
        that item (AWS never returns a mismatched id for an id-filtered describe), so a probe
        that reaches here is always ``found``. ``Ec2InstanceFalsifier`` overrides this to fold
        in the terminated-state rule."""
        items = response.get(self.list_key) or []
        if not items:
            # Defensive only: a real AWS describe-by-id never succeeds with no items — either
            # the id exists (one item) or the call raises the type's NotFound code.
            return Probe(status="errored", detail="response carried no items and no error")
        item = items[0]
        return Probe(status="found", source_id=str(item.get(self.item_id_key) or ""), detail="HTTP 200")

    def _resolve(self) -> tuple[Callable[[str, str], ProbeClient], list[str]]:
        if self._client_for is not None:
            return self._client_for, list(self._regions_override or [])
        session, regions = self._session_factory()

        def client_for(service: str, region: str) -> ProbeClient:
            return session.client(service, region_name=region)

        return client_for, regions

    def _describe_one(
        self, client_for: Callable[[str, str], ProbeClient], region: str, source_id: str
    ) -> tuple[Probe, bool]:
        """One region's answer for one id, and whether it is authoritative (a successful HTTP
        response — found, or an instance confirmed terminated) or region-local (a ``ClientError``,
        which says nothing about any OTHER region and never stops the sweep on its own).

        Client construction happens INSIDE this try/except, not before it (AI review, PR #44):
        a malformed or unsupported region (a Local/Wavelength Zone id that slipped past
        ``_regions_for``'s parsing, say) must degrade this one candidate, not raise out of
        ``judge`` and cost every other candidate of this type its verdict too
        (``tap_grid.falsifiers._judge`` answers a whole group ``UNDETERMINED(errored)`` when a
        falsifier's ``batch_falsify`` raises — fail closed, but coarser than it needs to be).
        """
        try:
            client = client_for(self.service, region)
            response = getattr(client, self._method())(**{self.ids_param: [source_id]})
        except ClientError as exc:
            return Probe(status=_error_status(exc, self.not_found_code), detail=_error_detail(exc)), False  # type: ignore[arg-type]
        except BotoCoreError as exc:
            return Probe(status="errored", detail=f"{type(exc).__name__}: {exc}"), False
        return self._probe_from_response(response, source_id), True

    def judge(self, client_for: Callable[[str, str], ProbeClient], regions: list[str], candidate: Candidate) -> Verdict:
        row = _row_of(candidate.entity_id)
        if row is None:
            return _undetermined(candidate, "errored", "the grid row could not be read")
        expected = self._expected_of(row)
        if expected is None:
            return _undetermined(candidate, "scope_unknown", "the grid holds no stable id for this row")
        try_regions = self._regions_for(row, regions)
        seen_forbidden = seen_rate_limited = seen_errored = False
        for region in try_regions:
            probe, authoritative = self._describe_one(client_for, region, expected.source_id)
            if authoritative:
                return verdict_from_probe(candidate, expected, probe)
            if probe.status == "forbidden":
                seen_forbidden = True
            elif probe.status == "rate_limited":
                seen_rate_limited = True
            elif probe.status == "errored":
                seen_errored = True
            # not_found (region-local): keep sweeping — the id may live in another region.
        swept = ", ".join(try_regions) or "<none>"
        if seen_forbidden:
            return _undetermined(
                candidate,
                "forbidden",
                f"could not confirm absence in every configured region ({swept}); at least one refused the probe",
            )
        if seen_rate_limited:
            return _undetermined(candidate, "rate_limited", f"throttled probing one or more configured regions ({swept})")
        if seen_errored:
            return _undetermined(candidate, "errored", f"one or more configured regions could not be probed ({swept})")
        # Every configured region answered this type's own NotFound code: authoritative absence.
        return verdict_from_probe(
            candidate,
            expected,
            Probe(status="not_found", detail=f"{self.not_found_code} in every configured region ({swept})"),
        )

    def batch_falsify(self, candidates: Sequence[Candidate], context: FalsifyContext) -> list[Verdict]:
        try:
            client_for, regions = self._resolve()
        except Exception as exc:  # noqa: BLE001 — a missing credential is an answer, not a crash
            note = f"credential unavailable: {type(exc).__name__}"
            logger.warning("[c4b2] %s: %s", type(self).__name__, note)
            return [_undetermined(c, "errored", note) for c in candidates]
        if not regions:
            return [_undetermined(c, "errored", "no region scope resolved for this credential") for c in candidates]
        return [self.judge(client_for, regions, c) for c in candidates]


class VpcFalsifier(_Ec2Falsifier):
    """``describe_vpcs(VpcIds=[...])``; ``InvalidVpcID.NotFound``; identity is ``vpc_id``."""

    not_found_code = "InvalidVpcID.NotFound"
    ids_param = "VpcIds"
    list_key = "Vpcs"
    item_id_key = "VpcId"

    def _method(self) -> str:
        return "describe_vpcs"

    def _expected_of(self, row: Any) -> Expected | None:
        vpc_id = str(getattr(row, "vpc_id", "") or "")
        return Expected(source_id=vpc_id) if vpc_id else None


class SubnetFalsifier(_Ec2Falsifier):
    """``describe_subnets(SubnetIds=[...])``; ``InvalidSubnetID.NotFound``; identity is
    ``subnet_id``. The only one of the four with a region hint already on the model
    (``availability_zone``), tried first."""

    not_found_code = "InvalidSubnetID.NotFound"
    ids_param = "SubnetIds"
    list_key = "Subnets"
    item_id_key = "SubnetId"

    def _method(self) -> str:
        return "describe_subnets"

    def _expected_of(self, row: Any) -> Expected | None:
        subnet_id = str(getattr(row, "subnet_id", "") or "")
        return Expected(source_id=subnet_id) if subnet_id else None

    def _regions_for(self, row: Any, regions: list[str]) -> list[str]:
        az = str(getattr(row, "availability_zone", "") or "")
        match = _STANDARD_REGION_PREFIX.match(az)
        if match:
            region = match.group(1)
            return [region, *[r for r in regions if r != region]]
        return list(regions)


class SecurityGroupFalsifier(_Ec2Falsifier):
    """``describe_security_groups(GroupIds=[...])``; ``InvalidGroup.NotFound``; identity is
    ``group_id``."""

    not_found_code = "InvalidGroup.NotFound"
    ids_param = "GroupIds"
    list_key = "SecurityGroups"
    item_id_key = "GroupId"

    def _method(self) -> str:
        return "describe_security_groups"

    def _expected_of(self, row: Any) -> Expected | None:
        group_id = str(getattr(row, "group_id", "") or "")
        return Expected(source_id=group_id) if group_id else None


class Ec2InstanceFalsifier(_Ec2Falsifier):
    """``describe_instances(InstanceIds=[...])``; ``InvalidInstanceID.NotFound``; identity is
    ``instance_id``.

    AWS keeps a terminated instance describable for a while rather than 404ing it immediately —
    a real absence signal (a commit-equivalent: the instance is gone), not a collector defect —
    so a successful response whose ``State.Name`` is ``terminated`` is folded into ``not_found``
    here, authoritatively (the response DID answer; sweeping further regions would be both
    wasteful and wrong, since instance ids are not reused across regions). Every other state —
    ``pending``, ``running``, ``shutting-down``, ``stopping``, ``stopped`` — is ``found``:
    ``stopped`` is not gone, only not running.

    The terminated shortcut only fires once the returned ``InstanceId`` is checked against the
    requested id (AI review, PR #44): synthesizing ``not_found`` bypasses ``classify()``'s own
    identity comparison (a genuine ``not_found`` status is never re-checked against identity —
    the ClientError it came from already was, for the one id it named), so this is the one place
    that check has to be made explicitly rather than inherited. A mismatch falls through to the
    ordinary found path instead, where ``verdict_from_probe`` derives REIDENTIFIED on its own.
    """

    not_found_code = "InvalidInstanceID.NotFound"
    ids_param = "InstanceIds"

    #: read: AWS's own closed set (DescribeInstances State.Name); only this one means gone.
    _TERMINATED = "terminated"

    def _method(self) -> str:
        return "describe_instances"

    def _expected_of(self, row: Any) -> Expected | None:
        instance_id = str(getattr(row, "instance_id", "") or "")
        return Expected(source_id=instance_id) if instance_id else None

    def _probe_from_response(self, response: dict[str, Any], source_id: str) -> Probe:
        instances = [i for reservation in (response.get("Reservations") or []) for i in (reservation.get("Instances") or [])]
        if not instances:
            return Probe(status="errored", detail="response carried no instances and no error")
        instance = instances[0]
        state = str((instance.get("State") or {}).get("Name") or "")
        found_id = str(instance.get("InstanceId") or "")
        # Identity is checked BEFORE the terminated shortcut is trusted (AI review, PR #44): a
        # response naming a different instance must go through the ordinary found path, whose
        # source_id classify() compares against `expected` itself (yielding REIDENTIFIED, never
        # a silent retirement of the candidate under a state field that describes some OTHER
        # instance). A real DescribeInstances(InstanceIds=[id]) never returns a mismatched id,
        # but the check costs nothing and does not rest that on trust.
        if state == self._TERMINATED and found_id == source_id:
            return Probe(status="not_found", detail=f"HTTP 200, State.Name=terminated ({found_id})")
        return Probe(status="found", source_id=found_id, detail=f"HTTP 200, State.Name={state or 'unknown'}")


__all__ = [
    "Ec2InstanceFalsifier",
    "SecurityGroupFalsifier",
    "SubnetFalsifier",
    "VpcFalsifier",
]
