"""Unit tests for :mod:`tap_plugin.aws_core.collectors.boto3_collector.listing` (aws-core-tap#43).

Pure logic, no DB, no boto3.
"""

from __future__ import annotations

from botocore.exceptions import ClientError

from tap_plugin.aws_core.collectors.boto3_collector.listing import (
    NO_SNAPSHOT_PROMISE,
    ListingWalk,
    page_says_more,
    surface_statement,
)


class TestPageSaysMore:
    def test_is_truncated_true(self):
        assert page_says_more({"IsTruncated": True}) is True

    def test_is_truncated_false(self):
        assert page_says_more({"IsTruncated": False}) is False

    def test_continuation_marker_present(self):
        assert page_says_more({"Marker": "abc"}) is True
        assert page_says_more({"ContinuationToken": "abc"}) is True

    def test_no_marker(self):
        assert page_says_more({"Roles": []}) is False

    def test_non_dict_page(self):
        assert page_says_more(None) is False
        assert page_says_more([1, 2]) is False

    def test_empty_string_marker_is_not_more(self):
        assert page_says_more({"Marker": ""}) is False


class TestListingWalk:
    def test_reached_end(self):
        walk = ListingWalk()
        walk.reached_end(5)
        assert walk.complete is True
        assert walk.count == 5
        assert walk.reasons == {}

    def test_stopped_short(self):
        walk = ListingWalk()
        walk.stopped_short(3, "still has a marker")
        assert walk.complete is False
        assert walk.count == 3
        assert "walk_capped" in walk.reasons["enumeration_complete"]

    def test_drop_sets_admitted_false(self):
        walk = ListingWalk()
        walk.reached_end(2)
        walk.drop("an item had no name")
        assert walk.admitted is False
        assert "collection_partial" in walk.reasons["admitted"]

    def test_fail_denied(self):
        walk = ListingWalk()
        exc = ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "ListRoles")
        walk.fail(exc)
        assert walk.complete is False
        assert walk.authorized is False
        assert walk.admitted is False
        assert "access_denied" in walk.reasons["scope_authorized"]

    def test_fail_throttled(self):
        walk = ListingWalk()
        exc = ClientError({"Error": {"Code": "Throttling", "Message": "slow down"}}, "ListRoles")
        walk.fail(exc)
        assert walk.complete is False
        assert walk.authorized is True  # a throttle says nothing about permission
        assert "throttled" in walk.reasons["enumeration_complete"]

    def test_fail_other_is_not_determinable_for_authorized(self):
        walk = ListingWalk()
        exc = ClientError({"Error": {"Code": "InternalError", "Message": "boom"}}, "ListRoles")
        walk.fail(exc)
        assert walk.authorized is None
        assert "not_determinable" in walk.reasons["scope_authorized"]

    def test_fail_non_client_error(self):
        walk = ListingWalk()
        walk.fail(TimeoutError("timed out"))
        assert walk.complete is False
        assert walk.authorized is None


class TestSurfaceStatement:
    def test_complete_surface(self):
        walk = ListingWalk()
        walk.reached_end(4)
        surface = surface_statement(
            walk,
            relation="account.iam_roles",
            edge_type="OWNS_IAM_ROLE__aws_core",
            subject="11111111-1111-1111-1111-111111111111",
            applied_batches=["batch-1"],
        )
        assert surface["scope_authorized"] is True
        assert surface["enumeration_complete"] is True
        assert surface["admitted"] is True
        assert surface["source_consistent"] == "unknown"
        assert surface["reasons"]["source_consistent"] == NO_SNAPSHOT_PROMISE
        assert surface["count_observed"] == 4
        assert surface["applied_batches"] == ["batch-1"]
        # applied / reconcilable are NOT authored here — the core recorder derives them.
        assert "applied" not in surface
        assert "reconcilable" not in surface

    def test_incomplete_surface_carries_a_reason(self):
        walk = ListingWalk()
        walk.stopped_short(2, "still has a marker")
        surface = surface_statement(
            walk,
            relation="account.iam_roles",
            edge_type="OWNS_IAM_ROLE__aws_core",
            subject="acct-id",
            applied_batches=[],
        )
        assert surface["enumeration_complete"] is False
        assert "walk_capped" in surface["reasons"]["enumeration_complete"]

    def test_never_walked_is_not_determinable(self):
        walk = ListingWalk()  # complete stays None: nothing consumed it
        surface = surface_statement(
            walk, relation="r", edge_type="E", subject="s", applied_batches=[]
        )
        assert surface["enumeration_complete"] is None
        assert "not_determinable" in surface["reasons"]["enumeration_complete"]
