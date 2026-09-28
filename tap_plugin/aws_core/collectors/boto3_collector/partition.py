"""AWS partition awareness for the boto3 collector (GovCloud readiness).

Spec: specs/spec-aws-core-collector-v0.md (req-aws-collector-partition) and
README.md § Deploying to GovCloud.

An AWS *partition* is a hard isolation boundary: ``aws`` (commercial),
``aws-us-gov`` (GovCloud (US)), ``aws-cn`` (China), and the isolated ``aws-iso*``
partitions. Credentials, IAM principals, Organizations and ARNs never cross a
partition, and the partition is the second segment of every ARN
(``arn:<partition>:<service>:<region>:<account>:<resource>``). Everything in this
module is a pure function of a region name or an ARN string — no network, no
boto3 — so the rest of the collector can be partition-correct without asking AWS.

Two rules the collector follows and this module makes cheap:

- **Never hardcode ``arn:aws:``.** Parse the partition out of an ARN a service
  handed back (:func:`parse_arn`, :data:`PARTITION_RE`), or build one from the
  partition the run is scoped to (:func:`build_arn`).
- **Never hardcode ``us-east-1``.** A "global" service (IAM, Route 53, Organizations,
  CloudFront) is still addressed *through a region of its own partition*; botocore
  then picks the partition's global endpoint (``iam.us-gov.amazonaws.com`` for
  GovCloud). The collector therefore binds a global client to the run's own region
  (the first region of the secret's scope), never a literal.

Sources for the endpoint claims (checked 2026-09-28): botocore's bundled endpoint
rule sets (``client.meta.endpoint_url`` for each service in each partition, asserted
in ``tests/test_partition.py``), and the AWS GovCloud (US) User Guide
(``docs.aws.amazon.com/govcloud-us``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PARTITION_AWS = "aws"
PARTITION_US_GOV = "aws-us-gov"
PARTITION_CN = "aws-cn"

#: Partitions this collector is exercised against. ``aws-cn`` and the ``aws-iso*``
#: partitions are RECOGNISED (so an ARN or region from one is classified rather than
#: mistaken for commercial) but REFUSED at credential resolution: nothing here has been
#: run against them, and a partition we cannot test is one we do not claim.
SUPPORTED_PARTITIONS: tuple[str, ...] = (PARTITION_AWS, PARTITION_US_GOV)

#: The partition segment of an ARN, as a regex fragment (``aws``, ``aws-us-gov``,
#: ``aws-cn``, ``aws-iso``, ``aws-iso-b`` ...). Use this instead of a literal ``aws``.
PARTITION_RE = r"aws(?:-[a-z]+)*"

# Region-name -> partition. These are botocore's own ``regionRegex`` per partition
# (endpoints.json), so a region classifies the way ``client.meta.partition`` will
# (asserted against a real botocore client in tests). The specific partitions are
# tried before the generic commercial one.
_REGION_PARTITIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (PARTITION_US_GOV, re.compile(r"^us-gov-\w+-\d+$")),
    (PARTITION_CN, re.compile(r"^cn-\w+-\d+$")),
    ("aws-iso-b", re.compile(r"^us-isob-\w+-\d+$")),
    ("aws-iso-e", re.compile(r"^eu-isoe-\w+-\d+$")),
    ("aws-iso-f", re.compile(r"^us-isof-\w+-\d+$")),
    ("aws-iso", re.compile(r"^us-iso-\w+-\d+$")),
)

#: A region name's shape (all partitions). Used by the secret schema so a typo is caught
#: at validation, not as a botocore ``EndpointConnectionError`` mid-run.
REGION_NAME_PATTERN = r"^[a-z]{2,3}(-[a-z]+)+-[0-9]+$"

#: The region a partition's *global* services are anchored to when a literal is
#: unavoidable (a fallback with no run region in hand). Commercial ``us-east-1``;
#: GovCloud ``us-gov-west-1`` (IAM/Organizations/Route 53 resolve there).
_HOME_REGIONS = {
    PARTITION_AWS: "us-east-1",
    PARTITION_US_GOV: "us-gov-west-1",
    PARTITION_CN: "cn-north-1",
}

#: Services the manifest collects that DO NOT EXIST in a partition. A run scoped to that
#: partition records a clear "not available in this partition" result for the entry instead
#: of calling an endpoint that is not there (botocore will happily synthesise a hostname such
#: as ``cloudfront.us-gov-west-1.amazonaws.com`` that no DNS server knows).
#: CloudFront: "not available in AWS GovCloud (US)" (AWS GovCloud (US) User Guide,
#: "Setting Up Amazon CloudFront with Your AWS GovCloud (US) Resources"); botocore's
#: endpoints.json carries no ``aws-us-gov`` CloudFront endpoint.
_UNAVAILABLE_SERVICES: dict[str, dict[str, str]] = {
    PARTITION_US_GOV: {
        "cloudfront": (
            "Amazon CloudFront is not offered in AWS GovCloud (US); a GovCloud account cannot list "
            "distributions. Distributions that front GovCloud resources live in a commercial account."
        ),
    },
}

_ARN_RE = re.compile(
    rf"^arn:(?P<partition>{PARTITION_RE}):(?P<service>[a-z0-9-]+):(?P<region>[a-z0-9-]*):"
    r"(?P<account>[0-9]{12}|aws|):(?P<resource>.+)$"
)


@dataclass(frozen=True)
class ParsedArn:
    """The six segments of an ARN. ``region`` / ``account`` are ``""`` when the ARN omits them
    (an S3 bucket ARN has neither; an IAM ARN has no region). ``account`` is ``"aws"`` for an
    AWS-managed resource (``arn:aws:iam::aws:policy/...``)."""

    partition: str
    service: str
    region: str
    account: str
    resource: str


def partition_of_region(region: str | None) -> str:
    """The partition a region name belongs to. An empty or unrecognised name is commercial,
    which is what botocore does with a region it has no partition for."""
    if not region:
        return PARTITION_AWS
    for partition, pattern in _REGION_PARTITIONS:
        if pattern.match(region):
            return partition
    return PARTITION_AWS


def home_region(partition: str) -> str:
    """The partition's anchor region for global services (see :data:`_HOME_REGIONS`)."""
    return _HOME_REGIONS.get(partition, _HOME_REGIONS[PARTITION_AWS])


def parse_arn(value: object) -> ParsedArn | None:
    """Parse ``value`` as an ARN of ANY partition, or ``None`` if it is not one."""
    if not isinstance(value, str):
        return None
    match = _ARN_RE.match(value.strip())
    if not match:
        return None
    return ParsedArn(**match.groupdict())


def partition_of_arn(value: object) -> str | None:
    """The partition segment of ``value`` if it is an ARN, else ``None``."""
    parsed = parse_arn(value)
    return parsed.partition if parsed else None


def build_arn(partition: str, service: str, region: str, account: str, resource: str) -> str:
    """``arn:<partition>:<service>:<region>:<account>:<resource>``."""
    return f"arn:{partition}:{service}:{region}:{account}:{resource}"


def service_unavailable_reason(partition: str, service: str) -> str | None:
    """Why ``service`` cannot be collected in ``partition``, or ``None`` if it can (or if we
    do not know it cannot — an unknown gap surfaces as a normal per-entry skip at run time)."""
    return _UNAVAILABLE_SERVICES.get(partition, {}).get(service)
