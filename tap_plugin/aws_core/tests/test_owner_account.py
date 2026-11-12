"""``aws.account`` is the account that OWNS a resource (George 2026-11-12, aws-build Q57).

Filled in order: the account segment of the resource's own ARN (``aws`` for AWS-managed resources), else an
explicit owner field, else the account whose credential listed it. Organizations: an account node carries its own
id; every other node and edge of the tree carries the management account. Account numbers here are the documented
example placeholders, never real accounts.
"""

from __future__ import annotations

from typing import Any

import pytest
from tap_plugin.aws_core.collectors.boto3_collector.containment import arn_account, resource_owner
from tap_plugin.aws_core.collectors.boto3_collector.organizations import ACCOUNT, ORGANIZATIONAL_UNIT, _Reader
from tap_plugin.aws_core.collectors.boto3_collector.projection import ProjectedNode

RUN = "111122223333"  # the account whose credential listed the resource
OWNER = "444455556666"  # another account that owns it
MGMT = "777788889999"


def _node(natural_key: str, raw: dict[str, Any] | None = None, fields: dict[str, Any] | None = None) -> ProjectedNode:
    return ProjectedNode("aws_core__x", natural_key, "x", fields or {}, {}, raw or {})


pytestmark = pytest.mark.spec("req-aws-core-account-dimension-9")


class TestArnAccount:
    def test_the_account_segment_of_an_arn(self) -> None:
        assert arn_account(f"arn:aws:ec2:us-east-1:{OWNER}:subnet/subnet-1") == OWNER

    def test_aws_managed_resources_carry_aws(self) -> None:
        assert arn_account("arn:aws:iam::aws:policy/ReadOnlyAccess") == "aws"

    def test_an_account_less_arn_and_a_non_arn_give_nothing(self) -> None:
        assert arn_account("arn:aws:s3:::my-bucket") is None
        assert arn_account("subnet-1") is None
        assert arn_account(None) is None


class TestResourceOwner:
    def test_one_the_resources_own_arn(self) -> None:
        node = _node(f"arn:aws-us-gov:ecs:us-gov-west-1:{OWNER}:cluster/c", raw={"OwnerId": RUN})
        assert resource_owner({"containment": {"owner_path": "OwnerId"}}, node, RUN) == OWNER, "the ARN wins"

    def test_two_an_explicit_owner_field(self) -> None:
        entry = {"containment": {"owner_path": "OwnerId"}}
        assert resource_owner(entry, _node("subnet-1", raw={"OwnerId": OWNER}), RUN) == OWNER
        assert resource_owner({}, _node("tgw-1", fields={"owner_account_id": OWNER}), RUN) == OWNER
        assert resource_owner({}, _node("x-1", fields={"resource_owner_account_id": OWNER}), RUN) == OWNER

    def test_three_otherwise_the_listing_account(self) -> None:
        assert resource_owner({}, _node("arn:aws:s3:::my-bucket"), RUN) == RUN
        assert resource_owner({"containment": {"owner_path": "OwnerId"}}, _node("vpc-1", raw={}), RUN) == RUN

    def test_a_ram_shared_subnet_belongs_to_its_owner_not_the_account_that_sees_it(self) -> None:
        """The receiving account lists a subnet shared in through RAM; its OwnerId names the sharing account."""
        shared = _node("subnet-shared", raw={"SubnetId": "subnet-shared", "OwnerId": OWNER})
        assert resource_owner({"containment": {"owner_path": "OwnerId"}}, shared, RUN) == OWNER


class TestOrganizationsOwnership:
    def _reader(self) -> _Reader:
        reader = _Reader(client=None, dimensions={"aws.account": RUN, "aws.region": "global"}, sensitivity={})
        reader.management_account = MGMT
        return reader

    def test_an_account_owns_itself(self) -> None:
        assert self._reader()._owned_by(ACCOUNT, {"account_id": OWNER})["aws.account"] == OWNER

    def test_everything_else_belongs_to_the_management_account(self) -> None:
        dims = self._reader()._owned_by(ORGANIZATIONAL_UNIT, {"name": "ou"})
        assert dims == {"aws.account": MGMT, "aws.region": "global"}

    def test_the_run_account_until_the_organization_is_described(self) -> None:
        reader = self._reader()
        reader.management_account = ""
        assert reader._owned_by(ORGANIZATIONAL_UNIT)["aws.account"] == RUN
