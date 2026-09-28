"""AWS credential / session / region resolution for the boto3 collector.

Spec: plugins/aws_core/specs/spec-aws-core-secrets.md
(req-aws-core-secret-aws-static / req-aws-core-secret-aws-assumed-role) and
plugins/aws_core/specs/spec-aws-core-collector-v0.md
(req-aws-collector-credentials / req-aws-collector-regions).

``aws_core`` owns the ``data`` shape of both AWS credential kinds and validates
them consumer-side; ``tap_cares`` owns only the secrets *mechanics*
(``req-tap-cares-secrets-consumer-kinds``). Two kinds are supported:

- ``aws_static_access_key`` — a session bound directly to static credentials
  (our own account).
- ``aws_assumed_role`` — cross-account: a *base* session (static credentials)
  calls STS ``AssumeRole`` with a **mandatory** External ID, and the returned
  short-lived credentials back the working session. This is how the collector
  reaches a running service in an AWS account we do not own.

Region scope is operator-owned and carried on the secret (identically for both
kinds): a non-empty ``data.regions_allowed`` scopes regional collection to
exactly those regions; absent, the singular ``data.region`` is the sole region;
with neither, the run fails visibly.

The optional ``data.expected_account_id`` is likewise carried by both kinds: if
set, the account resolved by ``GetCallerIdentity`` must equal it or the run fails
visibly (``req-aws-core-secret-aws-static-5`` /
``req-aws-core-secret-aws-assumed-role-4``). On the cross-account kind it catches
a role that landed in the wrong account; on the static kind it catches the more
ordinary mistake of keys belonging to a different account than the operator
thought — the failure mode that otherwise collects a *real but wrong* system and
looks entirely successful while doing it.

The collector never reads credential files directly — credentials resolve
through the ``tap_cares`` secrets subsystem.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import boto3
import botocore.session
from botocore.config import Config

from tap_cares.secrets import SecretRef, require_secret_kind, resolve_secret
from tap_cares.secrets.models import Secret

from .partition import (
    PARTITION_RE,
    REGION_NAME_PATTERN,
    SUPPORTED_PARTITIONS,
    known_region,
    parse_arn,
    partition_of_region,
)

# The well-known SecretRef for the AWS collector. v0 has no per-instance
# config (CollectorConfig carries only entity ids), so the key is a constant;
# the operator drops ``aws_core/boto_collector.secret.json`` under TAP_SECRETS_ROOT
# (no plugin config in core infra — operator-owned, off-grid). `scope` names the
# consuming plugin's slug, not the credential provider
# (req-tap-cares-secrets-consumer-scoping).
AWS_SECRET_REF = SecretRef(scope="aws_core", key="boto_collector")
AWS_SECRET_KIND = "aws_static_access_key"
AWS_ASSUMED_ROLE_KIND = "aws_assumed_role"

# Region scope is shared by both kinds; kept as one fragment so the two schemas
# cannot drift.
#
# GovCloud (req-aws-collector-partition): region names are shape-checked (a typo fails at
# validation, not as a mid-run EndpointConnectionError); ``partition`` is OPTIONAL and, when
# given, must agree with the regions (it is derived from them otherwise — see
# ``resolve_partition``); ``use_fips_endpoint`` is a tri-state (true / false / absent =
# defer to ``AWS_USE_FIPS_ENDPOINT`` and the shared AWS config, botocore's own resolution).
_REGION_SCOPE_PROPS: dict[str, Any] = {
    "region": {"type": "string", "pattern": REGION_NAME_PATTERN},
    "regions_allowed": {
        "type": "array",
        "minItems": 1,
        "items": {"type": "string", "pattern": REGION_NAME_PATTERN},
    },
    "partition": {"type": "string", "enum": list(SUPPORTED_PARTITIONS)},
    "use_fips_endpoint": {"type": "boolean"},
}

# Assert-on-land is shared by both kinds, for the same reason region scope is:
# `account_mismatch_error` reads `data['expected_account_id']` without consulting
# the kind, and both call sites invoke it unconditionally. Kept as one fragment so
# the two schemas cannot drift into disagreeing about a check that is already
# uniform in the code.
_EXPECTED_ACCOUNT_PROPS: dict[str, Any] = {
    # 12-digit target account; enables the assert-on-land check.
    "expected_account_id": {"type": "string", "pattern": "^[0-9]{12}$"},
}

# The static-credential fragment: reused verbatim as the `aws_assumed_role`
# kind's `data.base` (the identity that CALLS AssumeRole).
_STATIC_CREDS_PROPS: dict[str, Any] = {
    "access_key_id": {"type": "string", "minLength": 1},
    "secret_access_key": {"type": "string", "minLength": 1},
    "session_token": {"type": "string", "minLength": 1},
}

# aws_core owns this schema for the kind's `data` (req-aws-core-secret-aws-static-2).
# Strict: `data` is exactly credentials + region scope + the optional account
# assertion; operator metadata belongs in the secret's separate `metadata`, not here.
AWS_STATIC_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["access_key_id", "secret_access_key"],
    "properties": {**_STATIC_CREDS_PROPS, **_REGION_SCOPE_PROPS, **_EXPECTED_ACCOUNT_PROPS},
}

# aws_core owns this schema for the cross-account kind's `data`
# (req-aws-core-secret-aws-assumed-role). `external_id` is REQUIRED — the target
# role's trust policy demands it, and we never call AssumeRole without the
# confused-deputy guard (req-aws-core-secret-aws-assumed-role-2).
AWS_ASSUMED_ROLE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["role_arn", "external_id", "base"],
    "properties": {
        # An IAM role ARN of any partition; ``resolve_partition`` then checks it against the
        # region scope (a commercial role ARN with GovCloud regions cannot work).
        "role_arn": {"type": "string", "pattern": rf"^arn:{PARTITION_RE}:iam::[0-9]{{12}}:role/.+$"},
        "external_id": {"type": "string", "minLength": 1},
        "base": {
            "type": "object",
            "additionalProperties": False,
            "required": ["access_key_id", "secret_access_key"],
            "properties": dict(_STATIC_CREDS_PROPS),
        },
        **_EXPECTED_ACCOUNT_PROPS,
        # STS RoleSessionName grammar: [\w+=,.@-]{2,64}.
        "role_session_name": {
            "type": "string",
            "minLength": 2,
            "maxLength": 64,
            "pattern": r"^[\w+=,.@-]+$",
        },
        # AssumeRole DurationSeconds bounds (15 min .. 12 h).
        "duration_seconds": {"type": "integer", "minimum": 900, "maximum": 43200},
        **_REGION_SCOPE_PROPS,
    },
}

# Kind → consumer-owned `data` schema. The one place the collector enumerates
# which AWS credential kinds it accepts.
_KIND_SCHEMAS: dict[str, dict[str, Any]] = {
    AWS_SECRET_KIND: AWS_STATIC_SCHEMA,
    AWS_ASSUMED_ROLE_KIND: AWS_ASSUMED_ROLE_SCHEMA,
}

# Default RoleSessionName when the run supplies none (self-test path, or a
# secret without `role_session_name`). The collect path overrides this with a
# run-identifying value (req-aws-core-secret-aws-assumed-role-5).
DEFAULT_ROLE_SESSION_NAME = "tap-aws-core-collector"


class CredentialError(Exception):
    """The AWS secret is missing region scope or is otherwise unusable."""


def resolve_aws_secret(ref: SecretRef = AWS_SECRET_REF) -> Secret:
    """Resolve and validate the AWS collector secret (either supported kind).

    Dispatches on ``secret.kind``: ``aws_static_access_key`` or
    ``aws_assumed_role``. Each is validated against its ``aws_core``-owned
    schema. Raises ``SecretNotFoundError`` (missing) or ``SecretValidationError``
    (unsupported/wrong kind / bad ``data`` shape) from the secrets subsystem.
    """
    secret = resolve_secret(ref)
    if secret.kind not in _KIND_SCHEMAS:
        # Unsupported kind: let the harness raise the canonical redacted error.
        # (Only reachable when kind is neither of ours; this call always raises.)
        require_secret_kind(secret, AWS_SECRET_KIND, data_schema=AWS_STATIC_SCHEMA)
    require_secret_kind(secret, secret.kind, data_schema=_KIND_SCHEMAS[secret.kind])
    return secret


def is_assumed_role(data: Mapping[str, Any]) -> bool:
    """True when the resolved secret ``data`` describes a cross-account assume.

    Presence of ``role_arn`` is the discriminator: the two kinds' schemas are
    disjoint on it (the static kind forbids it via ``additionalProperties:
    false``), so a validated ``data`` carrying ``role_arn`` is unambiguously the
    ``aws_assumed_role`` kind.
    """
    return "role_arn" in data


def base_creds(data: Mapping[str, Any]) -> dict[str, Any]:
    """``data['base']`` (the ``aws_assumed_role`` kind's calling identity), with the secret's
    top-level ``use_fips_endpoint`` merged in.

    ``data['base']``'s own schema (``_STATIC_CREDS_PROPS``) carries no ``use_fips_endpoint`` of
    its own — FIPS is a property of the *secret*, declared once, not duplicated per credential
    set. Every ``build_session(data["base"])`` call site should go through this instead of
    reading ``data["base"]`` directly, so the base session — used only to call AssumeRole, but
    still a real client-bearing ``boto3.session.Session`` — is pinned the same way the working
    session ``assume_role_session`` returns already is, rather than defaulting to whatever
    ambient environment/shared-config FIPS setting happens to be in effect.
    """
    return {**data["base"], "use_fips_endpoint": data.get("use_fips_endpoint")}


def resolve_regions(data: Mapping[str, Any]) -> list[str]:
    """Regions to sweep: ``data.regions_allowed`` if non-empty, else ``[region]``.

    Raises ``CredentialError`` if the secret defines neither.
    """
    regions = data.get("regions_allowed")
    if regions:
        return list(regions)
    region = data.get("region")
    if region:
        return [region]
    raise CredentialError("AWS secret defines no region: set data.regions_allowed (list) " "or data.region")


def resolve_partition(data: Mapping[str, Any], regions: list[str]) -> str:
    """The single AWS partition this run is scoped to (req-aws-collector-partition).

    Derived from the region scope (``us-gov-*`` -> ``aws-us-gov``; otherwise commercial),
    because a credential, an Organization and every ARN live in exactly one partition and
    the regions are the operator's own declaration of where that is. Fails visibly — never
    quietly picks one — when:

    - a region is not recognised as belonging to ANY partition, by botocore's own bundled
      endpoint data or this collector's own table (:func:`partition.known_region`) — a typo of
      a GovCloud/China/iso region name (``us-gvo-west-1``) matches none of the specific
      patterns and must never be silently classified as commercial (see
      ``known_region``'s docstring for exactly what this does and does not catch);
    - the regions span partitions (one credential cannot reach both);
    - the optional ``data.partition`` disagrees with the regions;
    - the partition is not one this collector supports (``aws-cn`` and the isolated
      partitions are recognised but untested; see ``SUPPORTED_PARTITIONS``);
    - on the assumed-role kind, ``role_arn`` names a different partition than the regions
      (a commercial role ARN cannot be assumed against GovCloud STS, and vice versa), or
      its account disagrees with ``expected_account_id`` (a role always lands in the
      account its own ARN names, so that mismatch is knowable before any AWS call).
    """
    unrecognised = [region for region in regions if not known_region(region)]
    if unrecognised:
        raise CredentialError(
            f"AWS region(s) {unrecognised} are not recognised by botocore or this collector's "
            "own partition table — check for a typo in data.regions_allowed/data.region"
        )
    partitions = {partition_of_region(region) for region in regions}
    if len(partitions) > 1:
        raise CredentialError(
            f"AWS region scope spans partitions {sorted(partitions)}: one credential cannot reach "
            "more than one partition. Use one secret per partition."
        )
    partition = partitions.pop()
    declared = data.get("partition")
    if declared and declared != partition:
        raise CredentialError(
            f"data.partition is {declared!r} but the regions {regions} belong to partition {partition!r}"
        )
    if partition not in SUPPORTED_PARTITIONS:
        raise CredentialError(
            f"AWS partition {partition!r} is not supported (supported: {', '.join(SUPPORTED_PARTITIONS)})"
        )
    role_arn = data.get("role_arn")
    if role_arn:
        parsed = parse_arn(role_arn)
        if parsed is None or parsed.service != "iam" or not parsed.resource.startswith("role/"):
            raise CredentialError(f"data.role_arn is not an IAM role ARN: {role_arn!r}")
        if parsed.partition != partition:
            raise CredentialError(
                f"data.role_arn is in partition {parsed.partition!r} but the regions are in {partition!r}: "
                "AssumeRole cannot cross partitions"
            )
        expected = data.get("expected_account_id")
        if expected and parsed.account != expected:
            raise CredentialError(
                f"data.role_arn is in account {parsed.account} but expected_account_id is {expected}"
            )
    return partition


def fips_requested(data: Mapping[str, Any]) -> bool:
    """Whether FIPS endpoints will be used for this secret's run: the secret's explicit
    ``use_fips_endpoint`` if set, else botocore's own effective resolution of
    ``use_fips_endpoint`` — the ``AWS_USE_FIPS_ENDPOINT`` environment variable, then the shared
    AWS config file (``~/.aws/config`` / ``AWS_CONFIG_FILE``), in botocore's own precedence
    order.

    This is what ``_botocore_session`` and every client it builds actually resolve to when the
    secret sets nothing — it is used for the ``self_test`` ``AWS_PARTITION`` check and the
    ``IDENTITY_RESOLVED`` log line precisely so those match a real client's own posture: reading
    only the secret and the environment variable would report FIPS "off" for a deployment that
    enables it only through ``~/.aws/config``, even though every client built here would still
    use FIPS endpoints. A throwaway ``botocore.session.Session()`` read-only queries the same
    resolution chain botocore always consults; nothing here constructs a client or makes a
    network call.
    """
    explicit = data.get("use_fips_endpoint")
    if explicit is not None:
        return bool(explicit)
    return bool(botocore.session.Session().get_config_variable("use_fips_endpoint"))


def _botocore_session(use_fips_endpoint: bool | None) -> botocore.session.Session:
    """A botocore session with FIPS pinned when the secret says so.

    Pinning it on the SESSION (not per-client ``Config``) is what makes it reach every client
    made from it — the manifest engine's, the custom fns', the RGTA sweep's and the
    falsifiers' — without each call site threading a Config. ``None`` leaves botocore's own
    resolution (``AWS_USE_FIPS_ENDPOINT`` / shared config) untouched.
    """
    session = botocore.session.Session()
    if use_fips_endpoint is not None:
        session.set_config_variable("use_fips_endpoint", use_fips_endpoint)
    return session


def build_session(creds: Mapping[str, Any]) -> boto3.session.Session:
    """A boto3 Session bound to a static credential set.

    ``creds`` is the ``aws_static_access_key`` kind's ``data`` (our own account) or, for the
    ``aws_assumed_role`` kind's calling identity, the result of :func:`base_creds` — never
    ``data['base']`` directly, which carries no ``use_fips_endpoint`` of its own. Both carry
    ``access_key_id`` / ``secret_access_key`` / optional ``session_token`` /
    ``use_fips_endpoint``.
    """
    return boto3.session.Session(
        aws_access_key_id=creds["access_key_id"],
        aws_secret_access_key=creds["secret_access_key"],
        aws_session_token=creds.get("session_token"),
        botocore_session=_botocore_session(creds.get("use_fips_endpoint")),
    )


def assume_role_session(
    base: boto3.session.Session,
    data: Mapping[str, Any],
    region: str,
    *,
    role_session_name: str | None = None,
    timeout_seconds: int | None = None,
) -> boto3.session.Session:
    """Assume ``data['role_arn']`` from ``base``; return a session on the
    returned short-lived credentials (cross-account collection).

    The External ID (``data['external_id']``) is always sent — the target role's
    trust policy requires it (req-aws-core-secret-aws-assumed-role-2). The
    returned session carries only STS-issued temporary credentials; nothing is
    persisted. ``RoleSessionName`` precedence: explicit arg → secret's
    ``role_session_name`` → ``DEFAULT_ROLE_SESSION_NAME``.
    """
    retries = {"max_attempts": 1}
    fips = data.get("use_fips_endpoint")
    fips_kwargs: dict[str, Any] = {} if fips is None else {"use_fips_endpoint": bool(fips)}
    config = (
        Config(
            connect_timeout=timeout_seconds,
            read_timeout=timeout_seconds,
            retries=retries,
            **fips_kwargs,
        )
        if timeout_seconds is not None
        else Config(retries=retries, **fips_kwargs)
    )
    sts = base.client("sts", region_name=region, config=config)
    kwargs: dict[str, Any] = {
        "RoleArn": data["role_arn"],
        "RoleSessionName": (role_session_name or data.get("role_session_name") or DEFAULT_ROLE_SESSION_NAME),
        "ExternalId": data["external_id"],
    }
    duration = data.get("duration_seconds")
    if duration:
        kwargs["DurationSeconds"] = duration
    creds = sts.assume_role(**kwargs)["Credentials"]
    return boto3.session.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        botocore_session=_botocore_session(fips),
    )


def account_mismatch_error(data: Mapping[str, Any], account_id: str) -> str | None:
    """Assert-on-land: a message if the resolved account ≠ expected, else None.

    ``data['expected_account_id']`` is the operator's declaration of the target
    account. Kind-agnostic by design: on ``aws_assumed_role`` a mismatch means the
    assumed role landed somewhere unexpected (req-aws-core-secret-aws-assumed-role-4);
    on ``aws_static_access_key`` it means the keys belong to a different account than
    the operator declared (req-aws-core-secret-aws-static-5). Account ids are
    non-secret identifiers and are safe to surface in the message.
    """
    expected = data.get("expected_account_id")
    if expected and account_id != expected:
        return f"resolved AWS account {account_id} does not match the expected " f"account {expected}"
    return None


def client_factory(session: boto3.session.Session, region: str) -> Callable[[str], Any]:
    """A ``client_for(service)`` bound to ``region`` (for ``iter_source``)."""

    def client_for(service: str) -> Any:
        return session.client(service, region_name=region)

    return client_for


def caller_account_id(session: boto3.session.Session, region: str, *, timeout_seconds: int) -> str:
    """The AWS account id via STS ``GetCallerIdentity``.

    A cheap read-only reachability probe requiring no resource permissions
    (also the self-test live check). Bounded by ``timeout_seconds``.
    """
    sts = session.client(
        "sts",
        region_name=region,
        config=Config(
            connect_timeout=timeout_seconds,
            read_timeout=timeout_seconds,
            retries={"max_attempts": 1},
        ),
    )
    return str(sts.get_caller_identity()["Account"])
