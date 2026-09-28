"""Partition and region facts for the boto3 collector.

Spec: ``specs/spec-aws-core-v0.md`` (``req-aws-core-regional-containment``).

Two questions the collector must answer before it may say a regional listing was *empty* rather
than *unread*:

* Which AWS partition is this region in? (``aws``, ``aws-us-gov`` for GovCloud, ``aws-cn``.) A
  credential resolves in exactly one partition; the global-service region, the ARN partition and
  the meaning of "the usual region" all follow from it.
* Was this region positively usable by the credential? An account can have a region disabled
  (commercial opt-in regions), a service control policy can deny the region, or the service may
  not exist there. In each case the listing fails or returns nothing, and *nothing returned* is
  exactly the answer that must never be mistaken for *nothing exists* — reconcile would read it
  as every resource in that region having been deleted.

Everything here is pure: the one AWS call (``ec2:DescribeRegions``) is made by the caller with a
client it builds, so tests inject a fake and no module-level state exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from botocore.exceptions import BotoCoreError, ClientError

PARTITION_AWS: Final = "aws"
PARTITION_GOV: Final = "aws-us-gov"
PARTITION_CN: Final = "aws-cn"

#: Region-code prefix -> partition. Longest prefix first; anything unlisted is the commercial
#: partition. (GovCloud regions are ``us-gov-west-1`` and ``us-gov-east-1``.)
_PARTITION_PREFIXES: Final[tuple[tuple[str, str], ...]] = (
    ("us-gov-", PARTITION_GOV),
    ("cn-", PARTITION_CN),
    ("us-isob-", "aws-iso-b"),
    ("us-isof-", "aws-iso-f"),
    ("us-iso-", "aws-iso"),
    ("eu-isoe-", "aws-iso-e"),
)

#: Where a partition's *global* services (IAM, Organizations, CloudFront, Route 53 control plane)
#: are homed. Only partitions this plugin has a settled answer for are listed; an unlisted one has
#: no invariant to warn about rather than a wrong one.
_GLOBAL_SERVICE_REGION: Final = {PARTITION_AWS: "us-east-1", PARTITION_GOV: "us-gov-west-1"}

#: ``DescribeRegions`` ``OptInStatus`` values under which the credential can use the region.
_ENABLED_OPT_IN: Final = frozenset({"opt-in-not-required", "opted-in"})
#: The one value that positively says the account has not enabled the region.
_DISABLED_OPT_IN: Final = "not-opted-in"

STATUS_ENABLED: Final = "enabled"
STATUS_DISABLED: Final = "disabled"
STATUS_UNKNOWN: Final = "unknown"

#: ``Error.Code`` values meaning "this credential may not ask" — the listing is out of scope for
#: the credential, so nothing it did not return says anything about what exists.
AUTHORIZATION_CODES: Final = frozenset(
    {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "UnauthorizedAccess", "AuthorizationError"}
)
#: ``Error.Code`` values a region that is disabled for the account (or that does not accept this
#: credential) answers with. Treated like a refusal: the region was not readable.
REGION_UNAVAILABLE_CODES: Final = frozenset(
    {"OptInRequired", "AuthFailure", "InvalidClientTokenId", "UnrecognizedClientException"}
)


def partition_of(region: str) -> str:
    """The AWS partition ``region`` belongs to, from its code.

    Prefix-based because a region code is the only thing available before any call is made, and it
    is how AWS itself names partitions' regions.
    """
    for prefix, partition in _PARTITION_PREFIXES:
        if region.startswith(prefix):
            return partition
    return PARTITION_AWS


def global_service_region(partition: str) -> str | None:
    """The region a partition's global services are homed in, or ``None`` when not settled."""
    return _GLOBAL_SERVICE_REGION.get(partition)


@dataclass(frozen=True)
class RegionFacts:
    """What the collector knows about reading one region."""

    region: str
    partition: str
    #: ``DescribeRegions`` ``OptInStatus`` verbatim; ``""`` when it could not be read.
    opt_in_status: str
    #: ``enabled`` (positively usable), ``disabled`` (positively not opted in) or ``unknown``.
    status: str
    #: Why the status is what it is; carried into completeness reasons.
    why: str


def _unknown(region: str, why: str) -> RegionFacts:
    return RegionFacts(region, partition_of(region), "", STATUS_UNKNOWN, why)


def read_region_facts(client: Any, regions: list[str]) -> tuple[dict[str, RegionFacts], str | None]:
    """Region facts for each of ``regions`` from ``ec2:DescribeRegions(AllRegions=True)``.

    Returns ``(facts, error)``. ``error`` is ``None`` when the call answered; otherwise every region
    is ``unknown`` and ``error`` names why, so the caller can warn once. A region the answer does not
    list is ``unknown`` too: a code the partition has never heard of is not evidence the region is
    usable, and is not evidence it is empty.

    ``AllRegions=True`` is deliberate: the default omits regions the account has not opted in to, so
    "absent from the answer" could mean either disabled or nonexistent. With it, a disabled region is
    *present and says* ``not-opted-in``.
    """
    try:
        response = client.describe_regions(AllRegions=True)
    except (BotoCoreError, ClientError) as exc:
        why = f"ec2:DescribeRegions failed: {type(exc).__name__}"
        return {r: _unknown(r, why) for r in regions}, why
    listed = {
        str(row.get("RegionName")): str(row.get("OptInStatus") or "") for row in response.get("Regions") or [] if row
    }
    facts: dict[str, RegionFacts] = {}
    for region in regions:
        if region not in listed:
            facts[region] = _unknown(region, "ec2:DescribeRegions does not list this region for this credential")
            continue
        opt_in = listed[region]
        if opt_in in _ENABLED_OPT_IN:
            facts[region] = RegionFacts(region, partition_of(region), opt_in, STATUS_ENABLED, f"opt-in status {opt_in}")
        elif opt_in == _DISABLED_OPT_IN:
            facts[region] = RegionFacts(
                region, partition_of(region), opt_in, STATUS_DISABLED, "the account has not opted in to this region"
            )
        else:
            facts[region] = RegionFacts(
                region, partition_of(region), opt_in, STATUS_UNKNOWN, f"unrecognised opt-in status {opt_in!r}"
            )
    return facts, None


def error_code_of(exc: BaseException) -> str:
    """The AWS ``Error.Code`` of a ``ClientError``, else ``""``."""
    if isinstance(exc, ClientError):
        return str((exc.response or {}).get("Error", {}).get("Code", ""))
    return ""


def refusal_of(exc: BaseException) -> str | None:
    """``"authorization"`` / ``"region"`` when ``exc`` is the credential or the region refusing, else ``None``.

    The distinction between a refusal and every other failure is the whole point: a refused listing
    is *known* not to have been read (``scope_authorized: false``); any other failure leaves it
    *undeterminable* (``null``).
    """
    code = error_code_of(exc)
    if code in AUTHORIZATION_CODES:
        return "authorization"
    if code in REGION_UNAVAILABLE_CODES:
        return "region"
    return None
