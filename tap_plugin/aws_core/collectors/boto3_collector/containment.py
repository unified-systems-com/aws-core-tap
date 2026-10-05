"""Region-scoped containment for the boto3 collector: the parent, the edges, the completeness claim.

Spec: ``specs/spec-aws-core-v0.md`` (``req-aws-core-regional-containment``).

What the collector adds to a run for every manifest entry that declares ``containment``:

1. **A parent per (account, region)** — an ``aws_account_region`` node, emitted for every region in
   the run's scope whether or not it turned out readable (a footprint the run could not read is a
   fact worth recording, and the parent must be observed for a candidate to be derived from it).
2. **A parent -> child edge** of the entry's ``edge_type`` for each listed resource the account owns.
3. **A completeness surface** for the region's listing (``tap_grid.completeness``): the six evidence
   attributes, honestly. A surface is ``enumeration_complete`` only when the listing ran to its end,
   in a region the credential was positively able to read; anything less says why and, because the
   recorder derives ``reconcilable`` from these, licenses nothing.

The ownership rule is the part that keeps the RAM case honest. ``ec2:DescribeVpcs`` (and subnets, route
tables, ...) also lists resources *shared into* the account by another. Such a resource is observed and
attributed to its real owner, but it is not hosted by this account's footprint: were it, the owner
revoking the share would drop it from the listing and read as a deletion, when nothing was deleted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from tap_plugin.aws_core.regional import PARENT_ENTITY_TYPE

from .batch import node_envelope
from .edges import edge_envelope
from .identity import node_ref
from .paths import eval_path
from .projection import ProjectedNode
from .regions import (
    STATUS_DISABLED,
    STATUS_ENABLED,
    RegionFacts,
    error_code_of,
    refusal_of,
)

ACCOUNT_TYPE = "aws_core__aws_account"
BELONGS_TO_ACCOUNT = "BELONGS_TO_ACCOUNT__aws_core"


def footprint_key(account_id: str, region: str) -> str:
    """The natural key of the (account, region) footprint — the pair, in one string."""
    return f"{account_id}:{region}"


def footprint_ref(account_id: str, region: str) -> str:
    """The batch-local ref of the (account, region) footprint; its grid id is core's to assign."""
    return node_ref(PARENT_ENTITY_TYPE, footprint_key(account_id, region))


def footprint_envelopes(
    account_id: str, region: str, facts: RegionFacts, dimensions: dict[str, str]
) -> list[dict[str, Any]]:
    """The footprint node and its ``BELONGS_TO_ACCOUNT`` reference edge to the account.

    The edge is a reference, not containment (#46: an account declares none). Its target is the
    account node the run collects in the same batch, or, when that read failed, the account's row
    on the grid, found by its natural key.
    """
    key = footprint_key(account_id, region)
    fields = {
        "name": f"{account_id} / {region}",
        "account_id": account_id,
        "region_code": region,
        "partition": facts.partition,
        "opt_in_status": facts.opt_in_status,
        "status": facts.status,
    }
    node = ProjectedNode(
        entity_type=PARENT_ENTITY_TYPE,
        natural_key=key,
        name=fields["name"],
        fields=fields,
        configuration={},
        raw_item={},
    )
    return [
        node_envelope(node, dimensions, {}, persist_configuration=False),
        edge_envelope(
            BELONGS_TO_ACCOUNT, from_ref=node.ref, to_ref=node_ref(ACCOUNT_TYPE, account_id), dimensions=dimensions
        ),
    ]


def owner_of(entry: dict[str, Any], item: Any, account_id: str) -> str:
    """The account that owns ``item``: the API's own owner field when the entry declares one and the
    item carries it, else the account the run is collecting."""
    path = (entry.get("containment") or {}).get("owner_path")
    owner = eval_path(item, path) if path else None
    return str(owner) if owner else account_id


def containment_envelopes(
    node: ProjectedNode,
    entry: dict[str, Any],
    *,
    account_id: str,
    region: str,
    dimensions: dict[str, str],
) -> list[dict[str, Any]]:
    """The structural edges for one listed resource of a ``containment`` entry.

    Always ``BELONGS_TO_ACCOUNT`` to the resource's real owner. ``HOSTS_*`` from the footprint only when
    that owner is this account — see the module docstring.
    """
    block = entry["containment"]
    owner = owner_of(entry, node.raw_item, account_id)
    envelopes = [
        edge_envelope(
            BELONGS_TO_ACCOUNT, from_ref=node.ref, to_ref=node_ref(ACCOUNT_TYPE, owner), dimensions=dimensions
        )
    ]
    if owner == account_id:
        envelopes.append(
            edge_envelope(
                block["edge_type"],
                from_ref=footprint_ref(account_id, region),
                to_ref=node.ref,
                dimensions=dimensions,
            )
        )
    return envelopes


@dataclass
class Listing:
    """What happened when one entry's listing was read in one region.

    Filled by the collector as it drives the source; read by :func:`surface_of`. It records *facts*
    (how many items, what failed, whether the call was truncated) and never a conclusion — the
    conclusion is the surface's, in one place.
    """

    first: datetime = field(default_factory=lambda: datetime.now(UTC))
    last: datetime = field(default_factory=lambda: datetime.now(UTC))
    #: Items the source yielded.
    count: int = 0
    #: The AWS or botocore error the listing raised, when it did.
    error: BaseException | None = None
    #: Continuation markers seen on a call that could not be paginated.
    truncated: list[str] = field(default_factory=list)
    #: Why the items the source yielded did not all reach the batch (projection, edge or identity
    #: failure). The listing itself was read; processing it was not finished.
    processing: list[str] = field(default_factory=list)
    #: Items skipped because they were not this account's own (shared in). Observed, not hosted.
    not_hosted: int = 0

    def done(self) -> None:
        self.last = datetime.now(UTC)


def surface_of(
    *,
    relation: str,
    edge_type: str,
    subject: str,
    facts: RegionFacts,
    listing: Listing | None,
) -> dict[str, Any]:
    """The authored completeness surface for one region's listing (``tap_grid/schemas/completeness.schema.json``).

    ``listing`` is ``None`` when no call was made because the region is positively disabled. The
    ``applied_batches`` are added by the caller once the batch id is known; ``applied`` and
    ``reconcilable`` are derived by the recorder and refused if authored here.

    Decision table (each non-true attribute carries a reason, which the recorder requires):

    * region ``disabled``: nothing was read; ``scope_authorized`` false, nothing enumerated or admitted.
    * the credential or region refused the call (``AccessDenied``, ``OptInRequired``, ...):
      ``scope_authorized`` false — known not read.
    * any other error: ``scope_authorized`` and ``enumeration_complete`` undeterminable (``null``).
    * a call that returned a continuation marker it could not follow: not complete.
    * an EMPTY listing from a region whose status is not positively ``enabled``: undeterminable, not
      complete. An empty answer is the one that reconcile would read as "everything there was deleted",
      so it needs positive evidence the region is readable that a non-empty one supplies by existing.
    * a listing that ran to its end but whose items were not all processed: complete but not ``admitted``
      (the observations it licenses never all reached the batch).
    """
    reasons: dict[str, str] = {
        "source_consistent": "no_promise: EC2 and its sibling Describe APIs make no snapshot promise across pages"
    }
    now = datetime.now(UTC)
    first = (listing.first if listing else now).isoformat()
    last = (listing.last if listing else now).isoformat()
    scope: bool | None = True
    complete: bool | None = True
    admitted = True
    count: int | None = listing.count if listing else None

    if listing is None or facts.status == STATUS_DISABLED:
        scope, complete, admitted, count = False, False, False, None
        why = f"region_disabled: {facts.why}; no listing was attempted"
        reasons.update(scope_authorized=why, enumeration_complete=why, admitted=why)
    elif listing.error is not None:
        code = error_code_of(listing.error) or type(listing.error).__name__
        complete, admitted, count = False, False, None
        reasons["enumeration_complete"] = f"listing_failed: {code}"
        reasons["admitted"] = f"listing_failed: {code}: nothing to process"
        refusal = refusal_of(listing.error)
        if refusal is not None:
            scope = False
            reasons["scope_authorized"] = f"{'region_unavailable' if refusal == 'region' else 'access_denied'}: {code}"
        else:
            scope = None
            reasons["scope_authorized"] = f"not_determinable: {code} does not say whether the credential may list this"
            reasons["enumeration_complete"] = f"listing_failed: {code}: the walk did not reach its end"
    elif listing.truncated:
        complete = False
        reasons["enumeration_complete"] = (
            f"truncated: the call returned {listing.truncated[0]} and cannot be paged, so the listing is partial"
        )
    elif listing.count == 0 and facts.status != STATUS_ENABLED:
        scope, complete = None, None
        reasons["scope_authorized"] = f"region_status_{facts.status}: {facts.why}"
        reasons["enumeration_complete"] = (
            f"empty_unverified: an empty answer from a region whose status is {facts.status} "
            "cannot be told from a region the credential could not read"
        )

    if listing is not None and listing.error is None and listing.processing:
        admitted = False
        reasons["admitted"] = f"processing_failed: {listing.processing[0]}"

    # count_observed is the walk's own row count — every item this account's credential could
    # SEE, RAM-shared ones included (the schema's own words: "how many rows the walk returned").
    # A shared-in item is one of those rows without being one of THIS edge_type's HOSTS_* targets
    # (containment_envelopes withholds that edge for it) — reviewer-flagged as a discrepancy
    # (unified-ai-review, Codex seat, PR#56) worth making explicit rather than silent: this is not
    # a completeness defect (count_observed is never compared against the edge set, only against
    # count_reported, which these AWS APIs never supply), but a reader comparing count_observed to
    # the HOSTS_* fan-out without this note would see a mismatch that looks like a bug.
    if listing is not None and listing.not_hosted:
        reasons["count_observed"] = (
            f"includes_shared: {listing.not_hosted} of {listing.count} row(s) are shared into this "
            "account (RAM) and are not this footprint's HOSTS_* children — see BELONGS_TO_ACCOUNT "
            "on each for its real owner"
        )

    return {
        "relation": relation,
        "edge_type": edge_type,
        "subject": subject,
        "interval": {"first": first, "last": last},
        "scope_authorized": scope,
        "enumeration_complete": complete,
        "source_consistent": "unknown",
        "admitted": admitted,
        "count_observed": count,
        "reasons": reasons,
    }


#: The exception types a listing can raise as a *fact about the source* (the AWS call), as opposed to
#: a defect in processing what came back. The collector records the former as ``Listing.error`` and
#: the latter as ``Listing.processing``.
AWS_ERRORS: tuple[type[BaseException], ...] = (BotoCoreError, ClientError)
