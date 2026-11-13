"""Migration 0056 fills aws.account from each aws_core row's own ARN (req-aws-core-account-dimension-11).

George, 2026-11-13 (aws-build Q62): 0055 dropped the old observer values, and a row nothing re-collects (an ECS node
only Anchore created) would keep no owner. Its spine natural key is its ARN, whose account field is the owner.
Every account id here is a fake test id.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

OWNER = "111122223333"
OTHER = "444455556666"


def _fill() -> None:
    from django.db import connection

    migration = importlib.import_module("tap_plugin.aws_core.migrations.0056_aws_account_from_arn")
    migration.fill_account_from_arn(None, SimpleNamespace(connection=connection))


def _row(entity_type: str, natural_key: str | None, dimensions: dict[str, str]):  # type: ignore[no-untyped-def]
    from tap_grid.models import Entity
    from tap_grid.write_guard import unguarded_write

    with unguarded_write():
        return Entity.objects.create(
            entity_type=entity_type, name=entity_type, natural_key=natural_key, dimensions=dict(dimensions)
        )


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-account-dimension-11")
def test_the_owner_is_filled_from_the_arn_and_a_rerun_is_a_no_op() -> None:
    cluster = _row(
        "aws_core__ecs_cluster", f"arn:aws:ecs:us-east-1:{OWNER}:cluster/c", {"tap.computing.cloud": "aws"}
    )
    managed = _row("aws_core__iam_policy", "arn:aws:iam::aws:policy/ReadOnlyAccess", {})
    gov = _row("aws_core__ecs_service", f"arn:aws-us-gov:ecs:us-gov-west-1:{OWNER}:service/c/s", {})
    regionless = _row("aws_core__iam_role", f"arn:aws:iam::{OWNER}:role/r", {})  # a global service, empty region
    for _ in range(2):
        _fill()
    for row in (cluster, managed, gov, regionless):
        row.refresh_from_db()
    assert cluster.dimensions == {"tap.computing.cloud": "aws", "aws.account": OWNER}
    assert managed.dimensions == {"aws.account": "aws"}, "an AWS-managed resource's owner is aws"
    assert gov.dimensions == {"aws.account": OWNER}
    assert regionless.dimensions == {"aws.account": OWNER}


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-account-dimension-11")
def test_rows_it_cannot_derive_are_left_alone() -> None:
    bucket = _row("aws_core__s3_bucket", "arn:aws:s3:::my-bucket", {})  # an S3 ARN has no account field
    not_arn = _row("aws_core__aws_vpc", "vpc-0abc", {})
    composite = _row("aws_core__thing", f"arn:aws:ecs:us-east-1:{OWNER}:cluster/c|child", {})
    unkeyed = _row("aws_core__other", None, {})
    theirs = _row("anchore__image", f"arn:aws:ecr:us-east-1:{OWNER}:repository/r", {})
    # Malformed ARN-like keys stay fail-closed: no partition or service, or no resource.
    empty_parts = _row("aws_core__bad_one", f"arn::::{OWNER}:x", {})
    no_resource = _row("aws_core__bad_two", f"arn:aws:ecs:us-east-1:{OWNER}", {})
    empty_resource = _row("aws_core__bad_three", f"arn:aws:ecs:us-east-1:{OWNER}:", {})
    # "aws" is an owner only on an AWS-managed IAM ARN; on any other service it is malformed.
    fake_managed = _row("aws_core__ecs_cluster", "arn:aws:ecs:us-east-1:aws:cluster/x", {})
    _fill()
    for row in (bucket, not_arn, composite, unkeyed, theirs, empty_parts, no_resource, empty_resource, fake_managed):
        row.refresh_from_db()
        assert "aws.account" not in row.dimensions, row.entity_type


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-account-dimension-11")
def test_an_existing_owner_is_never_overwritten() -> None:
    stamped = _row("aws_core__ecs_cluster", f"arn:aws:ecs:us-east-1:{OWNER}:cluster/c", {"aws.account": OTHER})
    _fill()
    stamped.refresh_from_db()
    assert stamped.dimensions == {"aws.account": OTHER}
