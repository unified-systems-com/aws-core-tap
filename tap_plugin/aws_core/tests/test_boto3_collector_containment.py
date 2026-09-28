"""Unit coverage of ``containment.surface_of``'s full decision table (tap-plugin-aws-core#49).

The end-to-end test (``test_boto3_collector_regional_containment.py``) proves the enabled-data
and disabled-skip paths through a real collector run; this module proves the remaining branches
directly against the pure function, which needs no database, no fake AWS client, and no
collector — the branches an AI reviewer flagged as implemented but unexercised: a truncated
(unpaginated) response, a listing failure (refused vs. merely erroring), and an empty listing
from a region whose status is not positively known ``enabled``.

No database required: none of this module touches the grid.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError

from tap_plugin.aws_core.collectors.boto3_collector.containment import (
    Listing,
    surface_of,
)
from tap_plugin.aws_core.collectors.boto3_collector.regions import (
    STATUS_DISABLED,
    STATUS_ENABLED,
    STATUS_UNKNOWN,
    RegionFacts,
)

_REGION = "us-gov-west-1"
_SUBJECT = "footprint-id"
_KW = {"relation": "account_region.vpcs", "edge_type": "HOSTS_VPC__aws_core", "subject": _SUBJECT}


def _facts(status: str, opt_in: str = "", why: str = "test") -> RegionFacts:
    return RegionFacts(_REGION, "aws-us-gov", opt_in, status, why)


def _access_denied() -> ClientError:
    return ClientError({"Error": {"Code": "AccessDenied", "Message": "nope"}}, "DescribeVpcs")


def _throttled() -> ClientError:
    return ClientError({"Error": {"Code": "Throttling", "Message": "slow down"}}, "DescribeVpcs")


class TestTruncated:
    """A call that could not be paginated and returned a continuation marker: partial, never
    complete — this PR's guard against reading a partial page as the whole answer."""

    def test_enumeration_incomplete_when_truncated(self):
        listing = Listing(truncated=["NextToken"])
        listing.count = 100
        surface = surface_of(**_KW, facts=_facts(STATUS_ENABLED), listing=listing)
        assert surface["enumeration_complete"] is False
        assert "truncated" in surface["reasons"]["enumeration_complete"]
        # Scope and admission are untouched — the credential COULD read this region; the walk
        # just did not finish.
        assert surface["scope_authorized"] is True
        assert surface["admitted"] is True

    def test_untruncated_call_is_complete(self):
        listing = Listing()
        listing.count = 3
        surface = surface_of(**_KW, facts=_facts(STATUS_ENABLED), listing=listing)
        assert surface["enumeration_complete"] is True
        assert "enumeration_complete" not in surface["reasons"]


class TestListingFailure:
    """A listing that raised: a refusal (credential or region) is KNOWN not read
    (``scope_authorized: false``); anything else is merely undeterminable (``null``), never
    a false ``true``."""

    def test_access_denied_is_a_known_refusal(self):
        listing = Listing(error=_access_denied())
        surface = surface_of(**_KW, facts=_facts(STATUS_ENABLED), listing=listing)
        assert surface["scope_authorized"] is False
        assert surface["enumeration_complete"] is False
        assert surface["admitted"] is False
        assert surface["count_observed"] is None
        assert "access_denied" in surface["reasons"]["scope_authorized"]

    def test_unrecognised_error_is_undeterminable_not_false(self):
        """The refusal/region code sets are closed; an error outside both must not silently
        become 'the credential may not read this' (false) OR 'it can' (true) — it is unknown."""
        listing = Listing(error=_throttled())
        surface = surface_of(**_KW, facts=_facts(STATUS_ENABLED), listing=listing)
        assert surface["scope_authorized"] is None
        assert surface["enumeration_complete"] is False
        assert "not_determinable" in surface["reasons"]["scope_authorized"]

    def test_region_unavailable_code_is_also_a_known_refusal(self):
        exc = ClientError({"Error": {"Code": "OptInRequired", "Message": "x"}}, "DescribeVpcs")
        listing = Listing(error=exc)
        surface = surface_of(**_KW, facts=_facts(STATUS_ENABLED), listing=listing)
        assert surface["scope_authorized"] is False
        assert "region_unavailable" in surface["reasons"]["scope_authorized"]


class TestEmptyUnverified:
    """The whole point of this PR: an empty listing must never read as 'checked, found nothing'
    unless the region's readability is positively known — this is the exact GovCloud case
    (one of two regions enabled, the listing for the other comes back empty because nothing was
    ever read, not because nothing exists)."""

    def test_empty_listing_in_unknown_region_is_not_complete(self):
        listing = Listing()
        listing.count = 0
        surface = surface_of(**_KW, facts=_facts(STATUS_UNKNOWN), listing=listing)
        assert surface["scope_authorized"] is None
        assert surface["enumeration_complete"] is None
        assert "empty_unverified" in surface["reasons"]["enumeration_complete"]

    def test_empty_listing_in_positively_enabled_region_is_complete(self):
        """The one case an empty answer IS trusted: the region's own status positively says the
        credential could read it, so nothing there really means nothing there."""
        listing = Listing()
        listing.count = 0
        surface = surface_of(**_KW, facts=_facts(STATUS_ENABLED), listing=listing)
        assert surface["scope_authorized"] is True
        assert surface["enumeration_complete"] is True
        assert "enumeration_complete" not in surface["reasons"]

    def test_nonempty_listing_in_unknown_region_is_still_complete(self):
        """A NON-empty listing needs no positive region-status backing — it found something,
        which is direct evidence the credential really could read the region."""
        listing = Listing()
        listing.count = 5
        surface = surface_of(**_KW, facts=_facts(STATUS_UNKNOWN), listing=listing)
        assert surface["scope_authorized"] is True
        assert surface["enumeration_complete"] is True


class TestRegionDisabled:
    def test_no_listing_at_all_reads_as_never_attempted(self):
        surface = surface_of(**_KW, facts=_facts(STATUS_DISABLED), listing=None)
        assert surface["scope_authorized"] is False
        assert surface["enumeration_complete"] is False
        assert surface["admitted"] is False
        assert surface["count_observed"] is None
        assert "region_disabled" in surface["reasons"]["scope_authorized"]


class TestProcessingFailure:
    """A listing that was READ (no error) but whose items were not all turned into nodes: complete,
    but not admitted — the observations it licenses never all reached the batch."""

    def test_processing_failure_is_not_admitted_but_is_complete(self):
        listing = Listing(processing=["duplicate identity vpc-x"])
        listing.count = 2
        surface = surface_of(**_KW, facts=_facts(STATUS_ENABLED), listing=listing)
        assert surface["enumeration_complete"] is True
        assert surface["admitted"] is False
        assert "processing_failed" in surface["reasons"]["admitted"]


def test_interval_uses_the_listing_clock_when_present():
    listing = Listing(first=datetime(2026, 1, 1, tzinfo=UTC), last=datetime(2026, 1, 1, 0, 5, tzinfo=UTC))
    listing.count = 1
    surface = surface_of(**_KW, facts=_facts(STATUS_ENABLED), listing=listing)
    assert surface["interval"]["first"] == "2026-01-01T00:00:00+00:00"
    assert surface["interval"]["last"] == "2026-01-01T00:05:00+00:00"


def test_no_reconcilable_or_applied_authored():
    """surface_of NEVER authors the two recorder-derived fields — the recorder refuses them if
    a producer does (tap_grid.completeness.record_completeness), so a caller trying to forge
    'this is reconcilable' here would already be structurally unable to."""
    listing = Listing()
    listing.count = 1
    surface = surface_of(**_KW, facts=_facts(STATUS_ENABLED), listing=listing)
    assert "reconcilable" not in surface
    assert "applied" not in surface


@pytest.mark.parametrize("relation", ["account_region.vpcs"])
def test_source_consistent_is_always_unknown_with_a_reason(relation):
    """EC2's Describe family makes no cross-page snapshot promise — source_consistent is never
    true here, on any branch, and it always carries the required reason."""
    listing = Listing()
    listing.count = 1
    surface = surface_of(relation=relation, edge_type="HOSTS_VPC__aws_core", subject=_SUBJECT, facts=_facts(STATUS_ENABLED), listing=listing)
    assert surface["source_consistent"] == "unknown"
    assert "no_promise" in surface["reasons"]["source_consistent"]
