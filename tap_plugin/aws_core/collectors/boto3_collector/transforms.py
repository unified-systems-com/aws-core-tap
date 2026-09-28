"""Edge value transforms + registry population for the boto3 collector.

Spec: plugins/aws_core/specs/spec-aws-core-collector-v0.md
(req-aws-collector-edges — derived edge keys).

An edge ``transform`` maps the raw extracted value to the *target's natural
key* so the edge resolves by deterministic identity with no cross-resource
lookup. Transforms are pure (value in, key out) and registered here — code is
never loaded from manifest data (``req-aws-collector-source-3``).

A transform returns ``None`` when the value is not a valid target of this
edge (e.g. a CloudFront origin that is not an S3 bucket); the edge pass drops
``None`` so no bogus edge is fabricated.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import partial
from typing import Any

from .edges import TransformRegistry
from .iam_trust import account_of_iam_arn
from .partition import PARTITION_AWS, PARTITION_RE, build_arn

# CloudFront S3 origin DomainName forms, all ending amazonaws.com (amazonaws.com.cn in the China
# partition; CloudFront itself does not exist in GovCloud, so a GovCloud run never reaches this):
#   bucket.s3.amazonaws.com
#   bucket.s3.us-east-1.amazonaws.com
#   bucket.s3-us-east-1.amazonaws.com
#   bucket.s3-website-us-east-1.amazonaws.com
#   bucket.s3-website.us-east-1.amazonaws.com
# The bucket is everything before the first ``.s3`` segment. A non-S3 origin
# (ALB, API Gateway, custom) does not match -> None (no edge).
# Segment content is [a-z0-9] WITHOUT the dash: every '-' acts as a separator starting a
# new segment instead of being ambiguous between separator and content. Same strings
# accepted ("s3-website-us-east-1" is just more, shorter segments), but the regex is
# linear — the old `(?:[.-][a-z0-9-]+)*` backtracked polynomially on crafted non-matching
# input (CodeQL py/redos).
_S3_ORIGIN_RE = re.compile(
    r"^(?P<bucket>[^/]+?)\.s3(?:[.-][a-z0-9]+)*\.amazonaws\.com(?:\.cn)?$",
    re.IGNORECASE,
)


def s3_bucket_name_from_origin_domain(value: object, *, partition: str = PARTITION_AWS) -> str | None:
    """A CloudFront origin DomainName -> the target S3 bucket's natural key.

    The S3 bucket natural key is its ARN, which is derivable from the name
    and the run's partition alone (``arn:<partition>:s3:::<bucket>`` — no
    account/region), so this stays a pure transform and the edge resolves by
    identity. ``partition`` is bound by ``build_transform_registry``.
    """
    if not isinstance(value, str):
        return None
    match = _S3_ORIGIN_RE.match(value.strip())
    if not match:
        return None
    return build_arn(partition, "s3", "", "", match.group("bucket"))


# A full KMS key ARN: arn:<partition>:kms:<region>:<acct>:key/<key-id>, any partition (a GovCloud
# key is arn:aws-us-gov:kms:...). Aliases (alias/...) and bare key ids don't match — see
# kms_key_arn_or_none.
_KMS_KEY_ARN_RE = re.compile(rf"^arn:{PARTITION_RE}:kms:[a-z0-9-]+:\d{{12}}:key/[0-9a-fA-F-]+$")


def kms_key_arn_or_none(value: object) -> str | None:
    """A KMS key reference -> the target key's natural key (its ARN), or None.

    AWS surfaces key references in three forms — full key ARN, bare key id,
    alias name. Only the full ARN equals the ``aws_kms_key`` natural key
    without an account/region join, so anything else drops (no bogus edge).
    """
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate if _KMS_KEY_ARN_RE.match(candidate) else None


_S3_ARN_PREFIX_RE = re.compile(rf"^arn:{PARTITION_RE}:s3:::")


def s3_bucket_arn_from_name(value: object, *, partition: str = PARTITION_AWS) -> str | None:
    """A bare S3 bucket name -> the bucket's natural key (its ARN).

    Like ``s3_bucket_name_from_origin_domain``, the S3 ARN is derivable from
    the name and the run's partition alone (``arn:<partition>:s3:::<bucket>``).
    A value that already is an S3 ARN — of ANY partition — passes through
    unchanged.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if _S3_ARN_PREFIX_RE.match(candidate):
        return candidate
    return build_arn(partition, "s3", "", "", candidate)


def log_group_name_from_arn(value: object) -> str | None:
    """A CloudWatch Logs log-group ARN -> the group's natural key (its name).

    The log-group entry's natural key is ``logGroupName``, but referrers
    (e.g. a trail's ``CloudWatchLogsLogGroupArn``) carry the ARN —
    ``arn:aws:logs:<region>:<acct>:log-group:<name>[:*]``. Extract the name;
    a non-log-group ARN drops.
    """
    if not isinstance(value, str):
        return None
    marker = ":log-group:"
    index = value.find(marker)
    if index == -1:
        return None
    name = value[index + len(marker) :].removesuffix(":*")
    return name or None


def customer_managed_policy_arn_or_none(value: object) -> str | None:
    """An attached managed-policy ARN -> the target policy's natural key, only if it is customer-managed.

    An AWS-managed policy is ``arn:<partition>:iam::aws:policy/...``: AWS's, identical in every account,
    and not a node of any account's collection, so an edge to it would dangle for ever. A
    customer-managed one carries the owning account id in that position and is collected by
    ``iam_customer_policies_listed``. The ARN is already the natural key, so it passes through unchanged;
    the partition is never assumed (a GovCloud ARN is ``arn:aws-us-gov:iam::...``).
    """
    return value.strip() if isinstance(value, str) and account_of_iam_arn(value) is not None else None


# Manifest transform name -> callable. The single source of truth wired into
# the engine's TransformRegistry by build_transform_registry().
_TRANSFORMS: dict[str, Callable[..., Any]] = {
    "customer_managed_policy_arn_or_none": customer_managed_policy_arn_or_none,
    "s3_bucket_name_from_origin_domain": s3_bucket_name_from_origin_domain,
    "kms_key_arn_or_none": kms_key_arn_or_none,
    "s3_bucket_arn_from_name": s3_bucket_arn_from_name,
    "log_group_name_from_arn": log_group_name_from_arn,
}


# Transforms that MINT an ARN from a partition-less value (a bucket name) and so need the run's
# partition. The rest only read an ARN they were handed, which already carries its partition.
_PARTITION_AWARE = frozenset({"s3_bucket_name_from_origin_domain", "s3_bucket_arn_from_name"})


def build_transform_registry(partition: str = PARTITION_AWS) -> TransformRegistry:
    """The populated edge-transform registry for the collector, bound to the run's ``partition``."""
    registry = TransformRegistry()
    for name, fn in _TRANSFORMS.items():
        registry.register(name, partial(fn, partition=partition) if name in _PARTITION_AWARE else fn)
    return registry
