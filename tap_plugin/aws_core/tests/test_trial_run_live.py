"""Live trial-run harness: provision a real AWS resource per collected type, collect it, prove the contract.

The scar this exists to prevent (the v0.4.0 "blind build"): six collected types shipped
without ever being collected against a live instance. The collector emits ``tags``
unconditionally on EVERY node (``batch.node_envelope``: ``"tags": tags or {}`` —
"never omitted"), but ``SecretsManagerSecret``'s model never declared a ``tags``
field, so core's GRIFT import (create-verb schema, ``additionalProperties: false``)
rejects the WHOLE batch on any account with one or more Secrets Manager secrets.
A five-minute trial run would have caught it before release. This module is that
trial run, made repeatable: see ``skills/add-aws-type/SKILL.md`` (step 5).

What one trial does, per approved type:

1. PROVISION a minimal sacrificial instance via boto3, unmistakably marked
   (name prefix ``tap-trial-``, tags below).
2. COLLECT through the real engine path that produced the bug — manifest entry →
   ``iter_source`` → ``project_item`` → ``resolve_node_tags`` → ``node_envelope``
   → ``assemble_batch`` (document build; no grid required).
3. ASSERT the emitted node payload validates against the model's create-verb
   schema exactly as core's GRIFT import applies it (``additionalProperties:
   false`` + ``CREATE_REQUIRED``, with core's null-preparation semantics), and
   that the trial tags round-trip through the type's declared tag strategy.
4. TEAR DOWN in ``finally``. A leaked-resource sweep (find-by-tag, delete) is
   included below for anything a crashed run leaves behind.

Gating (this test costs real AWS calls and needs WRITE credentials — it must
NEVER run in plugin CI or the default lanes):

- ``TAP_AWS_TRIAL_RUN=1``      — master gate; absent, every test here skips.
- ``TAP_AWS_TRIAL_TYPES``      — comma-separated short names (e.g.
  ``sqs_queue,cognito_user_pool``). THE HUMAN-IN-THE-LOOP SEAM: nothing is
  provisioned unless a human explicitly listed it here; there is no "all"
  default. This is how the AWS bill stays boring.
- ``TAP_AWS_TRIAL_REGION``     — region override; else the session's default region.
- ``TAP_AWS_TRIAL_ACCOUNT``    — optional expected 12-digit account id, asserted via
  ``GetCallerIdentity`` BEFORE any write (mirrors the collector secret's
  ``expected_account_id`` assert-on-land).
- ``TAP_AWS_TRIAL_SESSION``    — optional per-run label override (default: minted per run).
- ``TAP_AWS_TRIAL_TIMEOUT_SECONDS`` — list-visibility poll budget (default 180;
  a new SQS queue can take up to 60s to appear in ``ListQueues``).
- ``TAP_AWS_TRIAL_SWEEP``      — ``all`` or a session label; enables the sweep test only.

Credentials (the provisioner seam):

- DEFAULT: the ambient boto3 chain (``AWS_PROFILE`` / ``AWS_ACCESS_KEY_ID`` env /
  ``~/.aws``) — local developer credentials OUTSIDE tap-secrets. Building a new
  AWS type is a command-line developer activity, not plugin runtime.
- ``TAP_AWS_TRIAL_SECRET_ENVELOPE=1``: resolve a tap-secrets envelope instead —
  scope ``aws_core``, key ``trial_provisioner``, kind ``aws_static_access_key``.
  This envelope is deliberately SEPARATE from ``aws_core/boto_collector`` (that
  one is SecurityAudit READ-ONLY and must never be reused for writes). Wiring
  ``trial_provisioner`` (kind, consumer declaration, detection) goes through the
  /manage-secret review before first use; until then the ambient default is the path.
- Least-privilege IAM policy for the provisioner:
  ``collectors/boto3_collector/handoff/trial-provisioner-policy.json``.

Trial-resource marking (sortable two ways, by design): every provisioned resource
carries ``tap:trial = sacrificial`` (ANYTHING bearing this tag may be deleted, any
time, by anyone) and ``tap:trial-session = <label>`` (which run created it). The
sweep filters on the first and can scope by the second.

Operator runbook (from the session worktree root, dev checkout at
``_dev-plugins/aws_core``, stack up):

    scripts/dc exec -T \\
      -e PYTHONPATH=/app/_dev-plugins/aws_core \\
      -e TAP_AWS_TRIAL_RUN=1 \\
      -e TAP_AWS_TRIAL_TYPES=sqs_queue,secrets_manager_secret,cognito_user_pool,apigateway_http_api \\
      -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN \\
      -e AWS_DEFAULT_REGION=us-east-1 \\
      web uv run pytest \\
      /app/_dev-plugins/aws_core/tap_plugin/aws_core/tests/test_trial_run_live.py -rs -v

(``PYTHONPATH`` makes the checkout's ``tap_plugin.aws_core`` shadow the installed
wheel so the code under trial is the code being edited. On a host with core
importable — the plugin-workspace model — plain ``uv run pytest <this file>`` with
``AWS_PROFILE`` works the same and picks up ``~/.aws`` directly.)

Leaked-resource sweep (same gating, plus the sweep var):

    ... -e TAP_AWS_TRIAL_RUN=1 -e TAP_AWS_TRIAL_SWEEP=all ... \\
      web uv run pytest <this file> -k sweep -rs -v

Deferred types (named, not built — see the skip reasons on their specs):
``kms_key`` and ``cloudtrail_trail``.
"""

from __future__ import annotations

import functools
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid7

import boto3
import jsonschema
import pytest
from tap_plugin.aws_core.collectors.boto3_collector.batch import assemble_batch, node_envelope
from tap_plugin.aws_core.collectors.boto3_collector.collector import resolve_node_tags
from tap_plugin.aws_core.collectors.boto3_collector.credentials import client_factory
from tap_plugin.aws_core.collectors.boto3_collector.customfns import build_custom_fn_registry
from tap_plugin.aws_core.collectors.boto3_collector.manifest import load_manifest, manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.projection import ProjectionError, project_item
from tap_plugin.aws_core.collectors.boto3_collector.source import iter_source
from tap_plugin.aws_core.models.apigateway_http_api import ApiGatewayHttpApi
from tap_plugin.aws_core.models.cloudtrail_trail import CloudtrailTrail
from tap_plugin.aws_core.models.cognito_user_pool import CognitoUserPool
from tap_plugin.aws_core.models.kms_key import KmsKey
from tap_plugin.aws_core.models.secrets_manager_secret import SecretsManagerSecret
from tap_plugin.aws_core.models.sqs_queue import SqsQueue

# --- trial-resource marking (the two-level sort: sacrificial-at-all + this-run) ---
TRIAL_NAME_PREFIX = "tap-trial-"
TRIAL_MARKER_TAG_KEY = "tap:trial"
TRIAL_MARKER_TAG_VALUE = "sacrificial"
TRIAL_SESSION_TAG_KEY = "tap:trial-session"

_GATE_REASON = (
    "live AWS trial run: costs real AWS calls and needs write credentials; "
    "opt in with TAP_AWS_TRIAL_RUN=1 (never set in CI or the default lanes)"
)

_KMS_DEFERRED = (
    "kms_key trial deferred: a KMS key CANNOT be hard-deleted — ScheduleKeyDeletion has a "
    "7-day minimum, so every trial would leave pending-deletion residue in the account. "
    "Policy decision (accept residue vs a long-lived reusable trial key) still open."
)
_CLOUDTRAIL_DEFERRED = (
    "cloudtrail_trail trial deferred: a trail needs an S3 bucket plus a bucket policy first "
    "(more moving parts and its own teardown ordering); build once the one-call types are habitual."
)
_ECS_DEFERRED = (
    "ecs trial deferred: provisioning a cluster, a task definition and a Fargate task needs write "
    "credentials and a human-approved cost (a few cents per run, task billed per second, no residue after "
    "teardown), and none is approved yet (George, 2026-10-16: no write keys until he says). The unit tests "
    "cover the call shape and the payload against the model schema; the digest-equals-DescribeTasks check "
    "(req-aws-collector-ecs-13) is NOT OBSERVED against a live task."
)

_MODEL_BY_ENTITY_TYPE = {
    model.ENTITY_TYPE: model
    for model in (
        ApiGatewayHttpApi,
        CloudtrailTrail,
        CognitoUserPool,
        KmsKey,
        SecretsManagerSecret,
        SqsQueue,
    )
}


def _trial_run_enabled() -> bool:
    return os.environ.get("TAP_AWS_TRIAL_RUN") == "1"


def _approved_types() -> set[str]:
    """The human-approved short names from TAP_AWS_TRIAL_TYPES (empty set = provision nothing)."""
    raw = os.environ.get("TAP_AWS_TRIAL_TYPES", "")
    return {name.strip() for name in raw.split(",") if name.strip()}


def _visibility_timeout_seconds() -> float:
    return float(os.environ.get("TAP_AWS_TRIAL_TIMEOUT_SECONDS", "180"))


def provisioner_session() -> boto3.session.Session:
    """The WRITE-credentialed boto3 session for provisioning trial resources.

    Default: the ambient boto3 credential chain (AWS_PROFILE / env vars /
    ``~/.aws``) — developer-local credentials outside tap-secrets, because the
    trial run is a command-line build-time activity. With
    ``TAP_AWS_TRIAL_SECRET_ENVELOPE=1`` it instead resolves the dedicated
    tap-secrets envelope (scope ``aws_core``, key ``trial_provisioner``, kind
    ``aws_static_access_key``) — never the read-only ``boto_collector`` envelope.
    That envelope's wiring goes through the /manage-secret review before first use.
    """
    if os.environ.get("TAP_AWS_TRIAL_SECRET_ENVELOPE") == "1":
        from tap_plugin.aws_core.collectors.boto3_collector.credentials import (
            AWS_STATIC_SCHEMA,
            build_session,
        )

        from tap_cares.secrets import SecretRef, require_secret_kind, resolve_secret

        secret = resolve_secret(SecretRef(scope="aws_core", key="trial_provisioner"))
        require_secret_kind(secret, "aws_static_access_key", data_schema=AWS_STATIC_SCHEMA)
        return build_session(dict(secret.data))
    return boto3.session.Session()


@dataclass(frozen=True)
class TrialContext:
    """Everything one trial run shares: session, region, landed account, run label."""

    session: boto3.session.Session
    region: str
    account_id: str
    label: str

    @property
    def tags(self) -> dict[str, str]:
        """The mandatory trial tags: sacrificial marker + this run's session label."""
        return {
            TRIAL_MARKER_TAG_KEY: TRIAL_MARKER_TAG_VALUE,
            TRIAL_SESSION_TAG_KEY: self.label,
        }

    def resource_name(self, short_name: str) -> str:
        """An unmistakable trial-resource name: ``tap-trial-<label>-<type>``."""
        return f"{TRIAL_NAME_PREFIX}{self.label}-{short_name.replace('_', '-')}"


@functools.cache
def _trial_context() -> TrialContext:
    """Build the trial context (once per run); assert-on-land BEFORE any write can happen.

    Deliberately NOT a pytest fixture: it is only called AFTER the approval /
    deferral skips, so an unapproved run makes zero AWS calls of any kind.
    """
    session = provisioner_session()
    region = os.environ.get("TAP_AWS_TRIAL_REGION") or session.region_name
    if not region:
        pytest.fail("no region: set TAP_AWS_TRIAL_REGION or AWS_DEFAULT_REGION / profile region")
    account_id = str(session.client("sts", region_name=region).get_caller_identity()["Account"])
    expected = os.environ.get("TAP_AWS_TRIAL_ACCOUNT")
    if expected and account_id != expected:
        pytest.fail(
            f"landed in AWS account {account_id}, expected {expected} (TAP_AWS_TRIAL_ACCOUNT) — "
            f"refusing to provision anything"
        )
    label = os.environ.get("TAP_AWS_TRIAL_SESSION") or f"{time.strftime('%Y%m%d')}-{uuid7().hex[:8]}"
    return TrialContext(session=session, region=region, account_id=account_id, label=label)


# ---------------------------------------------------------------------------
# Per-type provisioners: create the CHEAPEST possible instance, tagged through
# the service's native tag mechanism (the same surface the collector reads),
# and hand back the natural key plus an idempotent teardown.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrialResource:
    """A provisioned sacrificial resource: its collector natural key + teardown."""

    natural_key: str
    teardown: Callable[[], None]


def _provision_sqs_queue(ctx: TrialContext, name: str) -> TrialResource:
    """SQS queue: single call, free tier, DeleteQueue is immediate."""
    sqs = ctx.session.client("sqs", region_name=ctx.region)
    queue_url = sqs.create_queue(QueueName=name, tags=ctx.tags)["QueueUrl"]
    attrs = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])
    return TrialResource(
        natural_key=attrs["Attributes"]["QueueArn"],
        teardown=lambda: sqs.delete_queue(QueueUrl=queue_url),
    )


def _provision_secrets_manager_secret(ctx: TrialContext, name: str) -> TrialResource:
    """Secrets Manager secret: metadata-only (NO SecretString — no secret material exists)."""
    sm = ctx.session.client("secretsmanager", region_name=ctx.region)
    arn = sm.create_secret(
        Name=name,
        Description="TAP trial-run sacrificial resource; holds no secret material.",
        Tags=[{"Key": key, "Value": value} for key, value in ctx.tags.items()],
    )["ARN"]
    return TrialResource(
        natural_key=arn,
        teardown=lambda: sm.delete_secret(SecretId=arn, ForceDeleteWithoutRecovery=True),
    )


def _provision_cognito_user_pool(ctx: TrialContext, name: str) -> TrialResource:
    """Cognito user pool: DeleteUserPool is instant; natural key is the pool Id."""
    cognito = ctx.session.client("cognito-idp", region_name=ctx.region)
    pool_id = cognito.create_user_pool(PoolName=name, UserPoolTags=ctx.tags)["UserPool"]["Id"]
    return TrialResource(
        natural_key=pool_id,
        teardown=lambda: cognito.delete_user_pool(UserPoolId=pool_id),
    )


def _provision_apigateway_http_api(ctx: TrialContext, name: str) -> TrialResource:
    """API Gateway v2 HTTP API: DeleteApi is instant; natural key is the synthesized _api_arn."""
    apigw = ctx.session.client("apigatewayv2", region_name=ctx.region)
    api_id = apigw.create_api(Name=name, ProtocolType="HTTP", Tags=ctx.tags)["ApiId"]
    return TrialResource(
        natural_key=f"arn:aws:apigateway:{ctx.region}::/apis/{api_id}",
        teardown=lambda: apigw.delete_api(ApiId=api_id),
    )


@dataclass(frozen=True)
class TrialTypeSpec:
    """One covered type: its manifest identity, provisioner, or a named deferral."""

    short_name: str
    entity_type: str
    provision: Callable[[TrialContext, str], TrialResource] | None = None
    deferred_reason: str | None = None


TRIAL_SPECS = [
    TrialTypeSpec("sqs_queue", "aws_core__aws_sqs_queue", _provision_sqs_queue),
    TrialTypeSpec(
        "secrets_manager_secret",
        "aws_core__aws_secrets_manager_secret",
        _provision_secrets_manager_secret,
    ),
    TrialTypeSpec("cognito_user_pool", "aws_core__aws_cognito_user_pool", _provision_cognito_user_pool),
    TrialTypeSpec("apigateway_http_api", "aws_core__aws_apigateway_http_api", _provision_apigateway_http_api),
    TrialTypeSpec("kms_key", "aws_core__aws_kms_key", deferred_reason=_KMS_DEFERRED),
    TrialTypeSpec("cloudtrail_trail", "aws_core__aws_cloudtrail_trail", deferred_reason=_CLOUDTRAIL_DEFERRED),
    TrialTypeSpec("ecs_task", "aws_core__aws_ecs_task", deferred_reason=_ECS_DEFERRED),
    TrialTypeSpec("ecs_container", "aws_core__aws_ecs_container", deferred_reason=_ECS_DEFERRED),
]


# ---------------------------------------------------------------------------
# The real collection path (the code that produced the v0.4.0 bug), plus the
# payload contract exactly as core's GRIFT import enforces it.
# ---------------------------------------------------------------------------


def _manifest_entry(entity_type: str) -> dict[str, Any]:
    entry = next((e for e in manifest_entries() if e["entity_type"] == entity_type), None)
    assert entry is not None, f"{entity_type} has no manifest entry — nothing collects it"
    return entry


def _entry_declares_tags(entry: dict[str, Any]) -> bool:
    """Whether the type lands real tags: a ``tags`` block (rgta / service side-quest) or a projected field."""
    return bool(entry.get("tags")) or "tags" in entry["fields"]


def _collect_trial_envelope(ctx: TrialContext, entry: dict[str, Any], natural_key: str) -> dict[str, Any]:
    """Drive the real engine path until the trial resource appears; return its node envelope.

    Polls because AWS listings are eventually consistent (a new SQS queue can take
    up to 60s to show in ListQueues). ``rgta_map`` is empty: none of the covered
    types declares an ``rgta`` tag source, and RGTA's own propagation lag would
    make it a flaky trial surface — extend with a real ``sweep_tags`` pass when a
    covered type first declares ``source: rgta``.
    """
    custom_fns = build_custom_fn_registry()
    client_for = client_factory(ctx.session, ctx.region)
    dimensions = {"cloud": "aws", "aws_account": ctx.account_id, "aws_region": ctx.region}
    deadline = time.monotonic() + _visibility_timeout_seconds()
    while True:
        for item in iter_source(entry, client_for=client_for, custom_fns=custom_fns, fn_context=ctx.session):
            try:
                node = project_item(entry, item)
            except ProjectionError:
                continue  # a foreign item without the natural key is not this trial's problem
            if node.natural_key != natural_key:
                continue
            tags, tag_slot, tag_mapping = resolve_node_tags(entry, item, rgta_map={}, client_for=client_for)
            if tag_slot is not None:
                node.configuration.setdefault("_hydrate", {})["tags"] = tag_slot
                node.configuration.setdefault("_hydrate_mapping", {})["tags"] = tag_mapping
            return node_envelope(node, dimensions, tags, persist_configuration=entry["persist_configuration"])
        if time.monotonic() > deadline:
            pytest.fail(
                f"{entry['entity_type']}: trial resource {natural_key!r} never appeared in the "
                f"collection path within {_visibility_timeout_seconds():.0f}s "
                f"(eventual consistency budget: TAP_AWS_TRIAL_TIMEOUT_SECONDS)"
            )
        time.sleep(5)


def _create_verb_schema(model: type) -> dict[str, Any]:
    """Mirror of core's create-verb service schema (tap_grid.models._build_service_schemas)."""
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": dict(model.FIELD_CRUD_SCHEMA),
    }
    required = list(getattr(model, "CREATE_REQUIRED", []))
    if required:
        schema["required"] = required
    return schema


def _prepare_null_payload(payload: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Mirror of core's null preparation (tap_grid.services._impl._prepare_null_payload).

    A null on a KNOWN field that does not permit null is dropped (treated as
    absent — projection's graceful-missing Nones import cleanly); a null on an
    UNKNOWN field is preserved so ``additionalProperties: false`` still rejects it.
    """

    def permits_null(prop_schema: dict[str, Any]) -> bool:
        declared = prop_schema.get("type")
        return "null" in declared if isinstance(declared, list) else declared == "null"

    props: dict[str, Any] = schema.get("properties", {})
    return {
        name: value
        for name, value in payload.items()
        if not (value is None and name in props and not permits_null(props[name]))
    }


def _assert_payload_imports(entity_type: str, payload: dict[str, Any]) -> None:
    """THE assertion that catches the v0.4.0 class of bug.

    The collector-emitted node payload must satisfy the model's create-verb
    schema under ``additionalProperties: false`` — any key the collector emits
    that the model never declared (v0.4.0: ``tags`` on SecretsManagerSecret)
    rejects the WHOLE batch at GRIFT import.
    """
    model = _MODEL_BY_ENTITY_TYPE[entity_type]
    schema = _create_verb_schema(model)
    prepared = _prepare_null_payload(payload, schema)
    try:
        jsonschema.validate(prepared, schema)
    except jsonschema.ValidationError as exc:
        pytest.fail(
            f"{entity_type}: collector-emitted payload does NOT satisfy the model's create schema — "
            f"core's GRIFT import would reject the whole batch (the v0.4.0 secrets_manager bug class). "
            f"Schema error: {exc.message} at payload path {list(exc.absolute_path)!r}"
        )


@pytest.mark.skipif(not _trial_run_enabled(), reason=_GATE_REASON)
@pytest.mark.parametrize("spec", TRIAL_SPECS, ids=lambda spec: spec.short_name)
def test_trial_type_collects_and_validates(spec: TrialTypeSpec) -> None:
    """Provision → collect via the real path → payload validates → tags round-trip → teardown."""
    if spec.deferred_reason:
        pytest.skip(spec.deferred_reason)
    if spec.short_name not in _approved_types():
        pytest.skip(
            f"not approved: a human must list {spec.short_name!r} in TAP_AWS_TRIAL_TYPES "
            f"before this test may provision anything"
        )
    entry = _manifest_entry(spec.entity_type)
    assert spec.provision is not None
    trial_ctx = _trial_context()
    resource = spec.provision(trial_ctx, trial_ctx.resource_name(spec.short_name))
    try:
        envelope = _collect_trial_envelope(trial_ctx, entry, resource.natural_key)

        # The whole-document build must also hold together (same producer path as a real run).
        document = assemble_batch(
            source="tap_plugin.aws_core.tests.test_trial_run_live",
            manifest_version=load_manifest()["manifest_version"],
            account_id=trial_ctx.account_id,
            regions=[trial_ctx.region],
            node_envelopes=[envelope],
            edge_envelopes=[],
        )
        assert document["batches"][0]["nodes"] == [envelope]

        payload = envelope["node"]
        _assert_payload_imports(spec.entity_type, payload)

        if _entry_declares_tags(entry):
            landed = payload.get("tags") or {}
            missing = {k: v for k, v in trial_ctx.tags.items() if landed.get(k) != v}
            assert not missing, (
                f"{spec.entity_type}: trial tags {missing!r} did not round-trip into the emitted "
                f"payload (landed: {landed!r}). Check the entry's tag strategy (rgta block / service "
                f"side-quest / projected field) AND node_envelope's unconditional 'tags' key, which "
                f"overwrites a projected 'tags' field with the resolve_node_tags result."
            )
    finally:
        resource.teardown()


# ---------------------------------------------------------------------------
# Leaked-resource sweep: find-by-tag, delete. The safety net for crashed runs.
# ---------------------------------------------------------------------------

_SWEEP_DELETERS: dict[str, Callable[[boto3.session.Session, str, str], None]] = {
    "sqs": lambda s, r, arn: s.client("sqs", region_name=r).delete_queue(
        QueueUrl=s.client("sqs", region_name=r).get_queue_url(QueueName=arn.rsplit(":", 1)[-1])["QueueUrl"]
    ),
    "secretsmanager": lambda s, r, arn: s.client("secretsmanager", region_name=r).delete_secret(
        SecretId=arn, ForceDeleteWithoutRecovery=True
    ),
    "cognito-idp": lambda s, r, arn: s.client("cognito-idp", region_name=r).delete_user_pool(
        UserPoolId=arn.rsplit("/", 1)[-1]
    ),
    "apigateway": lambda s, r, arn: s.client("apigatewayv2", region_name=r).delete_api(
        ApiId=arn.rsplit("/apis/", 1)[-1]
    ),
}


def sweep_trial_resources(
    session: boto3.session.Session,
    region: str,
    *,
    session_label: str | None = None,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Find trial resources by tag via RGTA and delete them (one region per call).

    Filters on ``tap:trial = sacrificial`` — the marker every provisioner stamps —
    optionally narrowed to one run's ``tap:trial-session`` label. Fail-safe by
    construction: the marker tag is re-verified on each returned resource, an ARN
    whose service has no registered deleter is reported (never guessed at), and
    ``dry_run=True`` only reports. RGTA indexing lags creation by a minute or
    two, so a just-crashed run's leak may need a second sweep.

    Returns:
        ``{"deleted": [...], "skipped": [...], "errors": [...]}`` (ARNs; errors
        as ``"<arn>: <exception>"``).
    """
    tag_filters = [{"Key": TRIAL_MARKER_TAG_KEY, "Values": [TRIAL_MARKER_TAG_VALUE]}]
    if session_label:
        tag_filters.append({"Key": TRIAL_SESSION_TAG_KEY, "Values": [session_label]})
    rgta = session.client("resourcegroupstaggingapi", region_name=region)
    report: dict[str, list[str]] = {"deleted": [], "skipped": [], "errors": []}
    for page in rgta.get_paginator("get_resources").paginate(TagFilters=tag_filters):
        for mapping in page.get("ResourceTagMappingList", []):
            arn = mapping["ResourceARN"]
            tag_map = {t["Key"]: t["Value"] for t in mapping.get("Tags", [])}
            if tag_map.get(TRIAL_MARKER_TAG_KEY) != TRIAL_MARKER_TAG_VALUE:
                report["skipped"].append(arn)  # belt-and-braces: never delete an unmarked resource
                continue
            deleter = _SWEEP_DELETERS.get(arn.split(":")[2])
            if deleter is None or dry_run:
                report["skipped"].append(arn)
                continue
            try:
                deleter(session, region, arn)
                report["deleted"].append(arn)
            except Exception as exc:  # noqa: BLE001 — a sweep reports per-resource failures, never dies mid-list
                # RGTA's tag index lags DELETION too: a resource the trial's own
                # teardown already removed can still be listed for minutes, and
                # re-deleting it raises the service's not-found error. Already
                # gone IS the sweep's goal state — count it deleted, not failed.
                code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
                if "NotFound" in code or "NoSuch" in code or "does not exist" in str(exc):
                    report["deleted"].append(arn)
                else:
                    report["errors"].append(f"{arn}: {exc}")
    return report


@pytest.mark.skipif(not _trial_run_enabled(), reason=_GATE_REASON)
def test_sweep_leaked_trial_resources() -> None:
    """Operator-run cleanup: TAP_AWS_TRIAL_SWEEP=all sweeps every sacrificial resource, =<label> one run's."""
    scope = os.environ.get("TAP_AWS_TRIAL_SWEEP", "")
    if not scope:
        pytest.skip("sweep not requested: set TAP_AWS_TRIAL_SWEEP=all or =<session label>")
    label = None if scope == "all" else scope
    trial_ctx = _trial_context()
    report = sweep_trial_resources(trial_ctx.session, trial_ctx.region, session_label=label)
    print(f"trial sweep [{scope}] in {trial_ctx.region}: {report}")  # noqa: T201 — operator-facing summary
    assert not report["errors"], f"sweep could not delete: {report['errors']}"
