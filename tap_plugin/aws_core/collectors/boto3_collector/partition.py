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

#: Every AWS partition name ARNs are known to carry, longest first (a prefix partition earlier
#: in the alternation would shadow a longer one sharing its start, e.g. ``aws`` before
#: ``aws-us-gov``). The single source both ``PARTITION_RE`` and ``_REGION_PARTITIONS`` build
#: from, so the two can never drift apart.
_KNOWN_PARTITIONS: tuple[str, ...] = (
    PARTITION_US_GOV,
    PARTITION_CN,
    "aws-iso-b",
    "aws-iso-e",
    "aws-iso-f",
    "aws-iso",
    PARTITION_AWS,
)

#: The partition segment of an ARN, as a regex fragment (``aws``, ``aws-us-gov``, ``aws-cn``,
#: ``aws-iso``, ``aws-iso-b`` ...). Use this instead of a literal ``aws``. A flat alternation
#: over the known names, not a repeated group (``(?:-[a-z]+)*``): the earlier, more general
#: form is flagged by static analysis as a nested-quantifier ReDoS shape even though the
#: leading literal ``-`` on each repetition makes it unambiguous in practice — enumerating the
#: (small, fixed) partition set sidesteps the question entirely rather than arguing it.
PARTITION_RE = "(?:" + "|".join(re.escape(p) for p in _KNOWN_PARTITIONS) + ")"

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
        # Not collected anywhere (req-aws-landing-zone-nongoals); named so the gap is data.
        "macie2": (
            "Amazon Macie is not offered in AWS GovCloud (US): no GovCloud endpoint "
            "(https://docs.aws.amazon.com/general/latest/gr/macie.html)."
        ),
    },
}


@dataclass(frozen=True)
class Availability:
    """One service's availability in one partition, with how it was established.

    ``method`` is the spec's method vocabulary: ``web`` (an AWS page, cited in ``evidence``),
    ``read`` (offline data such as botocore's endpoint rules) or ``inferred``. ``verified`` is False
    where the evidence does not settle the question; a failing call to such a service is reported
    with a partition hint and never read as an empty listing (``req-aws-landing-zone-availability-2``).
    """

    available: bool
    method: str
    evidence: str
    verified: bool = True


#: Availability of every service the landing-zone reader calls, in each supported partition
#: (``req-aws-landing-zone-availability-1``; spec-aws-core-landing-zone.md, *GovCloud Availability*).
#: A service marked unavailable is skipped with ``SERVICE_NOT_AVAILABLE_IN_PARTITION`` and no call.
LANDING_ZONE_AVAILABILITY: dict[str, dict[str, Availability]] = {
    "controltower": {
        PARTITION_AWS: Availability(True, "web", "https://docs.aws.amazon.com/controltower/latest/userguide/region-how.html"),
        PARTITION_US_GOV: Availability(
            True,
            "web",
            "https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-controltower.html: both GovCloud "
            "regions; Account Factory cannot create accounts. The baseline APIs were excluded from GovCloud in "
            "February 2024 (https://docs.aws.amazon.com/controltower/latest/userguide/2024-all.html) and are not "
            "re-verified.",
            verified=False,
        ),
    },
    "sso-admin": {
        PARTITION_AWS: Availability(True, "read", "botocore endpoint rules"),
        PARTITION_US_GOV: Availability(
            True, "web", "https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-sso.html: both regions, no multi-region"
        ),
    },
    "identitystore": {
        PARTITION_AWS: Availability(True, "read", "botocore endpoint rules"),
        PARTITION_US_GOV: Availability(
            True, "web", "https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-sso.html (Identity Center's identity store)"
        ),
    },
    "config": {
        PARTITION_AWS: Availability(True, "read", "botocore endpoint rules"),
        PARTITION_US_GOV: Availability(
            True,
            "inferred",
            "Control Tower's baseline Config recorder is part of GovCloud Control Tower; not verified against a GovCloud page",
            verified=False,
        ),
    },
    "guardduty": {
        PARTITION_AWS: Availability(True, "read", "botocore endpoint rules"),
        PARTITION_US_GOV: Availability(True, "web", "AWS GovCloud (US) User Guide, GuardDuty page: available with feature gaps"),
    },
    "securityhub": {
        PARTITION_AWS: Availability(True, "read", "botocore endpoint rules"),
        PARTITION_US_GOV: Availability(
            True,
            "web",
            "https://docs.aws.amazon.com/govcloud-us/latest/UserGuide/govcloud-controltower.html: available; some "
            "Control Tower Security Hub controls unavailable",
        ),
    },
    "accessanalyzer": {
        PARTITION_AWS: Availability(True, "read", "botocore endpoint rules"),
        PARTITION_US_GOV: Availability(True, "web", "AWS GovCloud (US) User Guide, IAM Access Analyzer: available except policy generation"),
    },
    "ec2": {
        PARTITION_AWS: Availability(True, "read", "botocore endpoint rules"),
        PARTITION_US_GOV: Availability(True, "read", "botocore 1.43.104 endpoint data (EBS default encryption)"),
    },
    "s3control": {
        PARTITION_AWS: Availability(True, "read", "botocore endpoint rules"),
        PARTITION_US_GOV: Availability(True, "read", "botocore 1.43.104 endpoint data (S3 account public-access block)"),
    },
    "macie2": {
        PARTITION_AWS: Availability(True, "read", "botocore endpoint rules; not collected (req-aws-landing-zone-nongoals)"),
        PARTITION_US_GOV: Availability(
            False, "inferred", "https://docs.aws.amazon.com/general/latest/gr/macie.html lists no GovCloud endpoint"
        ),
    },
}


def availability_of(partition: str, service: str) -> Availability | None:
    """The recorded availability of ``service`` in ``partition``, or None when none is recorded."""
    return LANDING_ZONE_AVAILABILITY.get(service, {}).get(partition)

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
    which is what botocore does with a region it has no partition for.

    Permissive by design — every internal caller here hands it a region already sourced from a
    real, constructed botocore client (``client.meta.region_name``) or one already accepted by
    :func:`known_region`, so a graceful commercial default for the unreachable "no region at
    all" case is correct. It is NOT how an operator-supplied region (a secret's
    ``regions_allowed``) should be classified — see :func:`known_region` for that gate, used by
    ``credentials.resolve_partition``.
    """
    if not region:
        return PARTITION_AWS
    for partition, pattern in _REGION_PARTITIONS:
        if pattern.match(region):
            return partition
    return PARTITION_AWS


def known_region(region: str) -> bool:
    """Whether ``region`` is recognised as belonging to some partition, by EITHER this
    module's own pattern table or botocore's own bundled endpoint data — never silently
    defaulted to commercial.

    Used to validate an operator-supplied region (a secret's ``regions_allowed``) before it
    drives which partition the whole run resolves to. Without this gate, a typo of a
    GovCloud/China/iso region (``us-gvo-west-1``) matches none of this module's specific
    patterns and ``partition_of_region`` would silently classify it as commercial — the
    fail-*open* case a partition guard exists to prevent.

    botocore's ``get_partition_for_region`` is authoritative (it is what a real client's own
    endpoint resolution consults) and knows the full commercial region set this module does
    not attempt to enumerate; this module's own table is the fallback for a region newer than
    the vendored botocore. A region neither source places anywhere is unknown, full stop —
    never assumed commercial.

    This is a partition-*shape* check, not a real-region existence check: botocore places a
    region by matching each partition's own regex (``regionRegex`` in its bundled endpoint
    data), so a fabricated-but-plausible commercial-shaped name (``us-east-97``) still passes —
    the same way an equally fabricated real region would, before AWS itself was asked. Closing
    that would mean hardcoding or fetching the literal list of regions that currently exist,
    which goes stale the moment AWS adds one; the goal here is narrower and durable: a region
    that cannot even be placed in a partition never silently becomes "commercial".
    """
    if any(pattern.match(region) for _partition, pattern in _REGION_PARTITIONS):
        return True
    try:
        import botocore.session

        botocore.session.get_session().get_partition_for_region(region)
    except Exception:  # noqa: BLE001 — an unrecognised/malformed region answers False, never raises
        return False
    return True


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
