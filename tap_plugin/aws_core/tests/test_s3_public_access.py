"""S3 ``public_access_blocked`` is observed, never defaulted (req-aws-core-fields-9).

The field used to be ``BooleanField(default=True)`` and the collector never filled it, so every
collected bucket read "blocked". It is now nullable (null = not observed, req-aws-core-fields-8)
and ``s3_buckets_hydrated`` derives it from the ``GetPublicAccessBlock`` hydrate slot it already
reads. These tests pin each case through the real custom fn and the real manifest projection.
"""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector.customfns import public_access_blocked, s3_buckets_hydrated
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item

_ALL_ON = {
    "BlockPublicAcls": True,
    "IgnorePublicAcls": True,
    "BlockPublicPolicy": True,
    "RestrictPublicBuckets": True,
}


def _raise(code: str):
    def _call(**_kw: Any) -> Any:
        raise ClientError({"Error": {"Code": code, "Message": code}}, "GetPublicAccessBlock")

    return _call


class _FakeS3:
    """One bucket; ``get_public_access_block`` behaves as the test says; every other op is an
    empty success (a real client with nothing configured)."""

    def __init__(self, pab: Any) -> None:
        self._pab = pab

    def can_paginate(self, _method: str) -> bool:
        return False

    def list_buckets(self, **_kw: Any) -> Any:
        return {"Buckets": [{"Name": "b", "BucketArn": "arn:aws:s3:::b"}]}

    def get_bucket_location(self, **_kw: Any) -> Any:
        return {"LocationConstraint": "us-west-2"}

    def get_public_access_block(self, **kw: Any) -> Any:
        return self._pab(**kw) if callable(self._pab) else self._pab

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda **_kw: {}


class _Session:
    def __init__(self, s3: _FakeS3) -> None:
        self._s3 = s3

    def client(self, service: str, **_kw: Any) -> Any:
        return self._s3


def _projected(pab: Any) -> Any:
    """``public_access_blocked`` as the collector would write it for a bucket whose
    ``GetPublicAccessBlock`` behaves as ``pab``."""
    s3 = _FakeS3(pab)
    [item] = list(s3_buckets_hydrated(_Session(s3), client_for=lambda _svc: s3))
    entry = next(e for e in manifest_entries() if e["entity_type"] == "aws_core__aws_s3_bucket")
    return project_item(entry, item).fields["public_access_blocked"]


@pytest.mark.parametrize(
    ("pab", "expected"),
    [
        pytest.param({"PublicAccessBlockConfiguration": _ALL_ON}, True, id="all-four-on"),
        pytest.param(
            {"PublicAccessBlockConfiguration": {**_ALL_ON, "RestrictPublicBuckets": False}}, False, id="one-off"
        ),
        pytest.param(
            {"PublicAccessBlockConfiguration": {k: v for k, v in _ALL_ON.items() if k != "IgnorePublicAcls"}},
            False,
            id="one-missing",
        ),
        pytest.param(_raise("NoSuchPublicAccessBlockConfiguration"), False, id="no-bucket-configuration"),
        pytest.param(_raise("AccessDenied"), None, id="denied"),
        pytest.param(_raise("InternalError"), None, id="error"),
        pytest.param({}, None, id="ok-without-configuration"),
    ],
)
def test_public_access_blocked_is_projected_from_the_hydrate_slot(pab: Any, expected: bool | None) -> None:
    assert _projected(pab) is expected


def test_no_slot_is_not_observed() -> None:
    """A bucket whose hydrate never ran has no slot: null, never a guess."""
    assert public_access_blocked(None) is None
    assert public_access_blocked({}) is None


def test_the_manifest_projects_the_field() -> None:
    """The manifest maps the field, so the value reaches the node rather than only configuration."""
    entry = next(e for e in manifest_entries() if e["entity_type"] == "aws_core__aws_s3_bucket")
    assert entry["fields"]["public_access_blocked"] == "_public_access_blocked"
