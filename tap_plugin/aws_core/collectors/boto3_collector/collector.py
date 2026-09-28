"""The AWS Core boto3 collector — one CollectorBase for all of AWS.

Spec: plugins/aws_core/specs/spec-aws-core-collector-v0.md
(req-aws-collector-runtime).

Exactly one ``CollectorBase`` subclass drives every AWS resource type via the
manifest engine — no per-service classes (``req-aws-collector-runtime-7``).
The pipeline composes the pure engine collaborators:

    resolve credentials → load+validate manifest → for each entry, per region,
    drive source → project fields → emit nodes → emit edges → assemble one
    GRIFT batch → submit_grift → one-line summary.

Trust posture: this reads our own account with our own read-only credentials.
That input is trusted; the KSI-style paranoid denylist / mass-deletion layer
is deliberately not replicated (``req-aws-collector-runtime-6``).

Resilience: a per-(entry, region) failure — a missing permission, a region
where the service is absent, an unregistered ``custom_fn`` (e.g. Route 53
before its fan-out increment lands) — is classified, recorded as a structured
``warn``, and skipped; the run continues and never corrupts already-collected
data (``req-aws-collector-regions-2/-4``). Only an unrecoverable condition
(bad/missing secret, no region scope, unreachable STS) records a structured
error and raises, letting the framework task body write the FAILED terminal
patch (``req-aws-collector-runtime-3``).
"""

from __future__ import annotations

from typing import Any

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from tap_cares.collectors import (
    CollectorBase,
    CollectorDocRef,
    CollectorReadinessStatus,
    CollectorSelfTestResult,
    check_fail,
    check_pass,
)
from tap_cares.exceptions import (
    SecretError,
    SecretNotFoundError,
    SecretValidationError,
)

from .batch import assemble_batch, node_envelope
from .containment import (
    Listing,
    containment_envelopes,
    footprint_envelopes,
    footprint_id,
    owner_of,
    surface_of,
)
from .credentials import (
    AWS_SECRET_REF,
    CredentialError,
    account_mismatch_error,
    assume_role_session,
    build_session,
    caller_account_id,
    client_factory,
    is_assumed_role,
    resolve_aws_secret,
    resolve_regions,
)
from .customfns import build_custom_fn_registry
from .edges import EdgeError, emit_edges
from .hydrate import hydrate_item
from .ledger import CallLedger
from .manifest import load_manifest, manifest_entries
from .paths import eval_path
from .projection import ProjectionError, project_item
from .regions import (
    STATUS_DISABLED,
    RegionFacts,
    global_service_region,
    partition_of,
    read_region_facts,
)
from .rgta import rgta_resource_type_filters, sweep_tags
from .source import SourceError, iter_source
from .tags import normalize_tags, rgta_join_arn
from .transforms import build_transform_registry

_SOURCE = "tap_plugin.aws_core.collectors.boto3_collector.collector"

# record_* call-site tokens (minted by scripts/log-site-id; held unique by
# the repo-wide site-uniqueness test).
_SITE_RUN_STARTED = "ad94"
_SITE_IDENTITY = "2897"
_SITE_ENTRY_SKIPPED = "6946"
_SITE_EDGE_DROPPED = "9072"
_SITE_GRIFT_SUBMITTED = "18fc"
_SITE_RUN_COMPLETED = "2de7"
_SITE_ABORT_SECRET = "2d64"
_SITE_ABORT_REGIONS = "b528"
_SITE_ABORT_IDENTITY = "0623"
_SITE_ABORT_ACCOUNT_MISMATCH = "005c"
_SITE_HYDRATE_GAP = "bfd4"
_SITE_CALL_LEDGER = "bdf3"
_SITE_RGTA_SKIPPED = "f74e"
_SITE_REGION_INVARIANT = "b349"
_SITE_REGION_STATUS_UNREADABLE = "3a71"
_SITE_REGION_DISABLED = "c5e2"
_SITE_MIXED_PARTITIONS = "91b8"
_SITE_DUPLICATE_IDENTITY = "e40d"
_SITE_REGION_SKIPPED = "7f2a"

_DOCS = (
    CollectorDocRef(
        plugin="aws_core",
        doc="collector",
        section="self-test",
        label="AWS Core collector self-test",
    ),
)


def resolve_node_tags(
    entry: dict[str, Any],
    item: Any,
    *,
    rgta_map: dict[str, dict[str, str]],
    client_for: Any,
) -> tuple[dict[str, str], dict[str, Any] | None, dict[str, Any] | None]:
    """Resolve one node's canonical tags (``req-aws-collector-tags``).

    Returns ``(tags, hydrate_slot, hydrate_mapping)``:

    - ``rgta`` source — join by ARN against the per-run RGTA map;
      ``{}`` if untagged (correct, not a gap). No raw slot (RGTA's
      ``list_kv``↔``map`` is information-preserving).
    - ``field`` source — the enumeration itself already carried the tags
      (an inline response field, or a ``_``-prefixed slot a custom fn
      hydrated); normalize straight off the item. The cheapest lane: zero
      extra API calls. No raw slot (normalization is shape-preserving).
    - ``service`` side-quest — the tag op run through the hydrate template
      (so ``ok|absent|denied|error`` status + raw land in ``_hydrate``,
      and a ``denied``/``error`` is surfaced as ``HYDRATE_GAP`` by the
      existing run scan); the slot's data is normalized to ``{str:str}``.
    - no ``tags`` block — ``({}, None, None)``.

    Tags reach the node envelope ONLY through this resolver — a manifest
    entry must never project tags via its ``fields`` map (the envelope
    stamps the resolved map after the projected fields, so a projected
    ``tags`` field is silently clobbered; the v0.4.0 scar).
    """
    block = entry.get("tags")
    if not block:
        return {}, None, None
    if block["source"] == "rgta":
        return rgta_map.get(rgta_join_arn(entry, item) or "", {}), None, None
    if block["source"] == "field":
        return normalize_tags(eval_path(item, block["from"]), block["shape"]), None, None

    call_kwargs: dict[str, Any] = {}
    for param_name, spec in block["params"].items():
        if "literal" in spec:
            call_kwargs[param_name] = spec["literal"]
        else:
            call_kwargs[param_name] = eval_path(item, spec["from"])
    env = hydrate_item(
        client_for(entry["service"]),
        {},
        [{"key": "tags", "op": block["op"], "why": block.get("why", "resource tags")}],
        call_kwargs=call_kwargs,
    )
    slot = env["_hydrate"]["tags"]
    mapping = env["_hydrate_mapping"]["tags"]
    tags: dict[str, str] = {}
    if slot.get("status") == "ok":
        tags = normalize_tags(eval_path(slot.get("data"), block["path"]), block["shape"])
    return tags, slot, mapping


class _Unreadable:
    """A stand-in EC2 client whose only call raises: what `read_region_facts` sees when the client
    itself could not be built, so that path yields the same all-unknown answer as a refused call."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def describe_regions(self, **_kw: Any) -> Any:
        raise ClientError({"Error": {"Code": "ClientUnavailable", "Message": str(self._exc)}}, "DescribeRegions")


class Boto3CollectorError(Exception):
    """An unrecoverable collector condition; the run aborts (FAILED)."""


class Boto3Collector(CollectorBase):
    """AWS resource collector — manifest-driven, single account, no deletes."""

    def _abort(
        self,
        site: str,
        code: str,
        message: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Record a structured error and raise to halt the run."""
        self.record_error(site, code, message, message_data=context)
        raise Boto3CollectorError(message)

    def _read_region_facts(self, session: Any, regions: list[str]) -> dict[str, RegionFacts]:
        """Region facts for the run's scope, warning once for what could not be established.

        The client is built inside the guard: botocore can refuse a region name before any call.
        """
        try:
            client = session.client("ec2", region_name=regions[0], config=Config(retries={"mode": "standard"}))
            facts, error = read_region_facts(client, regions)
        except (BotoCoreError, ValueError) as exc:
            facts = read_region_facts(_Unreadable(exc), regions)[0]
            error = f"ec2 client unavailable: {type(exc).__name__}"
        if error:
            self.record_warn(
                _SITE_REGION_STATUS_UNREADABLE,
                "REGION_STATUS_UNREADABLE",
                f"{error}: regional listings that return nothing will not be counted as observed-empty.",
                message_data={"regions": regions},
            )
        for region, fact in facts.items():
            if fact.status == STATUS_DISABLED:
                self.record_warn(
                    _SITE_REGION_DISABLED,
                    "REGION_DISABLED",
                    f"Region {region} is not enabled for this account ({fact.opt_in_status}); nothing is read from it.",
                    message_data={"region": region, "opt_in_status": fact.opt_in_status},
                )
        return facts

    def run(self) -> None:
        self.record_info(_SITE_RUN_STARTED, "RUN_STARTED", "AWS Core collection started.")

        # --- credentials / region scope / account identity (unrecoverable) ---
        try:
            secret = resolve_aws_secret(AWS_SECRET_REF)
        except SecretError as exc:
            self._abort(
                _SITE_ABORT_SECRET,
                "SECRET_UNUSABLE",
                f"AWS secret unusable: {exc}",
            )
        data = dict(secret.data)
        try:
            regions = resolve_regions(data)
        except CredentialError as exc:
            self._abort(_SITE_ABORT_REGIONS, "NO_REGION_SCOPE", str(exc))
        # Attach the audit ledger before any client/STS call so every AWS call
        # this run makes is recorded — including a cross-account AssumeRole,
        # which is captured on the base session
        # (req-aws-collector-audit-ledger, req-aws-core-secret-aws-assumed-role-6).
        ledger = CallLedger()
        try:
            if is_assumed_role(data):
                base = build_session(data["base"])
                ledger.attach(base)
                session = assume_role_session(
                    base,
                    data,
                    regions[0],
                    role_session_name=f"tap-aws-core-{self.config.collection_job_entity_id}",
                    timeout_seconds=self.SELF_TEST_LIVE_CHECK_TIMEOUT_SECONDS,
                )
            else:
                session = build_session(data)
            ledger.attach(session)
            account_id = caller_account_id(
                session,
                regions[0],
                timeout_seconds=self.SELF_TEST_LIVE_CHECK_TIMEOUT_SECONDS,
            )
        except (BotoCoreError, ClientError) as exc:
            self._abort(
                _SITE_ABORT_IDENTITY,
                "STS_UNREACHABLE",
                f"STS AssumeRole/GetCallerIdentity failed: {exc}",
            )
        # Assert-on-land: the resolved account must match the operator's declared
        # `expected_account_id` when one is set. Applies to BOTH kinds — a
        # cross-account role that landed in the wrong account
        # (req-aws-core-secret-aws-assumed-role-4), and static keys that belong to a
        # different account than declared (req-aws-core-secret-aws-static-5). A
        # secret that omits the field is unaffected.
        mismatch = account_mismatch_error(data, account_id)
        if mismatch:
            self._abort(_SITE_ABORT_ACCOUNT_MISMATCH, "ACCOUNT_MISMATCH", mismatch)
        self.record_info(
            _SITE_IDENTITY,
            "IDENTITY_RESOLVED",
            f"Collecting AWS account {account_id} across {len(regions)} region(s).",
            message_data={"account_id": account_id, "regions": regions},
        )

        # --- manifest + engine collaborators ---
        manifest = load_manifest()
        entries = manifest_entries()
        modeled_types = {e["entity_type"] for e in entries}
        custom_fns = build_custom_fn_registry()
        transforms = build_transform_registry()

        # --- partition + region facts (req-aws-core-regional-containment) ---
        # A credential resolves in exactly one partition, so a scope that spans two cannot be read
        # whole: name it once rather than let every entry in the far partition fail on its own.
        partitions = {partition_of(r) for r in regions}
        if len(partitions) > 1:
            self.record_warn(
                _SITE_MIXED_PARTITIONS,
                "MIXED_PARTITION_SCOPE",
                f"Region scope spans partitions {sorted(partitions)}: a credential resolves in one, so the "
                "regions of the others cannot be read and will be recorded as unreadable.",
                message_data={"regions": regions, "partitions": sorted(partitions)},
            )
        # --- per-run RGTA tag sweep (req-aws-collector-tags -2/-6/-7) ---
        home_region = global_service_region(partition_of(regions[0]))
        if home_region is not None and home_region not in regions:
            self.record_warn(
                _SITE_REGION_INVARIANT,
                "REGION_INVARIANT",
                f"Region scope omits {home_region}: the global-service home region of partition "
                f"{partition_of(regions[0])}. CloudFront-bound ACM certs and global-resource tags are "
                "silently missed.",
                message_data={"regions": regions, "home_region": home_region},
            )
        facts = self._read_region_facts(session, regions)
        rgta_filters = rgta_resource_type_filters(entries)
        rgta_map: dict[str, dict[str, str]] = {}
        for region in regions:
            try:
                rgta_map.update(
                    sweep_tags(
                        session.client(
                            "resourcegroupstaggingapi",
                            region_name=region,
                            config=Config(retries={"mode": "standard"}),
                        ),
                        rgta_filters,
                    )
                )
            except (BotoCoreError, ClientError) as exc:
                self.record_warn(
                    _SITE_RGTA_SKIPPED,
                    "RGTA_SWEEP_SKIPPED",
                    f"RGTA tag sweep failed in {region}: {exc}",
                    message_data={"region": region},
                )

        node_envelopes: list[dict[str, Any]] = []
        edge_envelopes: list[dict[str, Any]] = []
        skipped = 0
        # Identities already in this batch. A repeated id is a batch-fatal duplicate_entity_id at
        # import (the whole run's data lost); skip the repeat and say so instead.
        seen_nodes: set[str] = set()
        seen_edges: set[str] = set()
        # One completeness surface per contained (entry, region) listing (req-grid-reconcile-evidence).
        surfaces: list[dict[str, Any]] = []

        # The parent of every regional containment: one footprint per (account, region) in scope,
        # emitted whether or not the region turned out readable.
        for region in regions:
            for envelope in footprint_envelopes(
                account_id,
                region,
                facts[region],
                {"cloud": "aws", "aws_account": account_id, "aws_region": region},
            ):
                bucket = node_envelopes if envelope["entity"]["entity_type"] != "edge" else edge_envelopes
                (seen_edges if bucket is edge_envelopes else seen_nodes).add(envelope["entity"]["entity_id"])
                bucket.append(envelope)

        for entry in entries:
            entry_regions = regions if entry["scope"] == "regional" else [regions[0]]
            contained = entry.get("containment")
            for region in entry_regions:
                region_label = region if entry["scope"] == "regional" else "global"
                dimensions = {
                    "cloud": "aws",
                    "aws_account": account_id,
                    "aws_region": region_label,
                }
                region_facts = facts[region]
                if entry["scope"] == "regional" and region_facts.status == STATUS_DISABLED:
                    # Positively known not opted in: no call would be honoured, and an "empty" answer
                    # would be a lie. Say so on the surface instead of reading an empty region.
                    if contained:
                        surfaces.append(
                            surface_of(
                                relation=contained["relation"],
                                edge_type=contained["edge_type"],
                                subject=str(footprint_id(account_id, region)),
                                facts=region_facts,
                                listing=None,
                            )
                        )
                    continue
                listing = Listing() if contained else None
                listed = False
                try:
                    items = list(
                        iter_source(
                            entry,
                            client_for=client_factory(session, region),
                            custom_fns=custom_fns,
                            fn_context=session,
                            truncated=listing.truncated if listing else None,
                        )
                    )
                    listed = True
                    if listing:
                        listing.count = len(items)
                        listing.done()
                    for item in items:
                        node = project_item(entry, item)
                        if str(node.entity_id) in seen_nodes:
                            self.record_warn(
                                _SITE_DUPLICATE_IDENTITY,
                                "DUPLICATE_IDENTITY",
                                f"{node.entity_type} {node.natural_key} appeared twice in one run "
                                f"(second sighting in {region_label}); the repeat is skipped.",
                                message_data={"entity_type": node.entity_type, "region": region_label},
                            )
                            if listing:
                                listing.processing.append(f"duplicate identity {node.natural_key}")
                            continue
                        seen_nodes.add(str(node.entity_id))
                        tags, tag_slot, tag_mapping = resolve_node_tags(
                            entry,
                            item,
                            rgta_map=rgta_map,
                            client_for=client_factory(session, region),
                        )
                        if tag_slot is not None:
                            node.configuration.setdefault("_hydrate", {})["tags"] = tag_slot
                            node.configuration.setdefault("_hydrate_mapping", {})["tags"] = tag_mapping
                        node_envelopes.append(
                            node_envelope(
                                node,
                                dimensions,
                                tags,
                                persist_configuration=entry["persist_configuration"],
                            )
                        )
                        for slot, rec in node.configuration.get("_hydrate", {}).items():
                            if rec.get("status") in ("denied", "error"):
                                self.record_warn(
                                    _SITE_HYDRATE_GAP,
                                    "HYDRATE_GAP",
                                    f"{node.entity_type} {node.natural_key}: "
                                    f"hydrate slot {slot!r} {rec['status']} "
                                    f"({rec.get('error_code')})",
                                    message_data={
                                        "entity_type": node.entity_type,
                                        "slot": slot,
                                        "status": rec["status"],
                                    },
                                )
                        emission = emit_edges(
                            node,
                            entry,
                            modeled_types=modeled_types,
                            transforms=transforms,
                            dimensions=dimensions,
                        )
                        new_edges = list(emission.envelopes)
                        if contained:
                            new_edges.extend(
                                containment_envelopes(
                                    node,
                                    entry,
                                    account_id=account_id,
                                    region=region,
                                    dimensions=dimensions,
                                )
                            )
                            if listing and owner_of(entry, node.raw_item, account_id) != account_id:
                                listing.not_hosted += 1
                        for envelope in new_edges:
                            if envelope["entity"]["entity_id"] not in seen_edges:
                                seen_edges.add(envelope["entity"]["entity_id"])
                                edge_envelopes.append(envelope)
                        for warning in emission.warnings:
                            self.record_warn(_SITE_EDGE_DROPPED, "EDGE_DROPPED", warning)
                except (
                    SourceError,
                    EdgeError,
                    ProjectionError,
                    BotoCoreError,
                    ClientError,
                ) as exc:
                    skipped += 1
                    self.record_warn(
                        _SITE_ENTRY_SKIPPED,
                        "ENTRY_SKIPPED",
                        f"Skipped {entry['entity_type']} in {region_label}: {exc}",
                        message_data={
                            "entity_type": entry["entity_type"],
                            "region": region_label,
                        },
                    )
                    if listing:
                        listing.done()
                        if not listed:
                            # The source could not be read to its end: a fact about the source.
                            listing.error = exc
                        else:
                            # The listing was read; what was done with it was not finished.
                            listing.processing.append(f"{type(exc).__name__}: {exc}")
                if contained:
                    # `listing` is always set here (`Listing() if contained else None`, above) —
                    # `surface_of`'s own `listing: Listing | None` parameter tolerates None
                    # regardless, so no assert is needed to narrow the type for a check that
                    # would vanish under `-O` anyway (Bandit B101).
                    surfaces.append(
                        surface_of(
                            relation=contained["relation"],
                            edge_type=contained["edge_type"],
                            subject=str(footprint_id(account_id, region)),
                            facts=region_facts,
                            listing=listing,
                        )
                    )

        # --- one GRIFT batch per run (permissive: dangling edges resolve on a
        # later run by deterministic identity, never fail) ---
        document = assemble_batch(
            source=_SOURCE,
            manifest_version=manifest["manifest_version"],
            account_id=account_id,
            regions=regions,
            node_envelopes=node_envelopes,
            edge_envelopes=edge_envelopes,
        )
        # Abort-on-rejection is owned by CollectorBase.submit_grift
        # (on_rejection="abort" default): a rejected batch records a
        # structured GRIFT_BATCH_REJECTED error and raises GriftRejectedError,
        # which the task body turns into the FAILED terminal patch. No
        # per-collector guard — see req-tap-cares-collector-grift-import-9.
        result = self.submit_grift(document, dangling_edge_mode="permissive")
        # Every listing this run read is recorded against the batch that carries its observations;
        # `applied` is derived by the recorder from that batch's commit. The subject is the
        # footprint's deterministic grid id, already real once the batch imported. A run that read
        # no contained listing says so (a statement with zero surfaces, not no statement).
        collection_batch_id = str(document["batches"][0]["batch_entity"]["entity_id"])
        for surface in surfaces:
            self.record_surface(**surface, applied_batches=[collection_batch_id])
        if not surfaces:
            self.declare_no_surfaces()
        self.record_info(
            _SITE_GRIFT_SUBMITTED,
            "GRIFT_SUBMITTED",
            "AWS Core GRIFT batch submitted.",
            message_data={"imported": [str(b.batch_entity_id) for b in result.imported_batches]},
        )

        imported = result.counts.batches_imported
        self.summary = (
            f"Collected {len(node_envelopes)} nodes, {len(edge_envelopes)} "
            f"edges for account {account_id} across {len(regions)} region(s) "
            f"({skipped} skipped, {imported} batch imported)."
        )
        # Drain the per-run AWS call audit ledger as one structured run-log
        # entry (req-aws-collector-audit-ledger): the evidentiary spine for
        # the future audit-verifiability theme. One event, full machine
        # ledger in message_data — not one row per call.
        self.record_info(
            _SITE_CALL_LEDGER,
            "AWS_CALL_LEDGER",
            ledger.summary(),
            message_data={"calls": ledger.entries},
        )
        self.record_info(_SITE_RUN_COMPLETED, "RUN_COMPLETED", "AWS Core collection complete.")

    @classmethod
    def self_test(cls) -> CollectorSelfTestResult:
        checks = []

        # 1. Secret resolves and is the right kind/shape.
        try:
            secret = resolve_aws_secret(AWS_SECRET_REF)
        except SecretNotFoundError as exc:
            checks.append(
                check_fail(
                    "AWS_SECRET_PRESENT",
                    f"AWS collector secret is not configured: {exc}",
                    readiness_status=CollectorReadinessStatus.UNCONFIGURED,
                    docs=_DOCS,
                )
            )
            return CollectorSelfTestResult.from_checks(
                checks,
                summary="AWS collector secret is not configured.",
                docs=_DOCS,
            )
        except (SecretValidationError, SecretError) as exc:
            checks.append(
                check_fail(
                    "AWS_SECRET_VALID",
                    f"AWS collector secret is malformed: {exc}",
                    readiness_status=CollectorReadinessStatus.MISCONFIGURED,
                    docs=_DOCS,
                )
            )
            return CollectorSelfTestResult.from_checks(
                checks,
                summary="AWS collector secret is malformed.",
                docs=_DOCS,
            )
        checks.append(
            check_pass(
                "AWS_SECRET_VALID",
                "AWS collector secret resolves and is the expected kind.",
                docs=_DOCS,
            )
        )

        # 2. Region scope is defined.
        data = dict(secret.data)
        try:
            regions = resolve_regions(data)
        except CredentialError as exc:
            checks.append(
                check_fail(
                    "AWS_REGION_SCOPE",
                    str(exc),
                    readiness_status=CollectorReadinessStatus.MISCONFIGURED,
                    docs=_DOCS,
                )
            )
            return CollectorSelfTestResult.from_checks(
                checks,
                summary="AWS collector has no region scope.",
                docs=_DOCS,
            )
        checks.append(
            check_pass(
                "AWS_REGION_SCOPE",
                f"AWS collector will sweep {len(regions)} region(s).",
                context={"regions": regions},
                docs=_DOCS,
            )
        )

        # 3. Read-only reachability: STS within budget. For the assumed-role
        #    kind this also performs the AssumeRole (proving the cross-account
        #    trust is wired) before the GetCallerIdentity probe.
        try:
            if is_assumed_role(data):
                session = assume_role_session(
                    build_session(data["base"]),
                    data,
                    regions[0],
                    timeout_seconds=cls.SELF_TEST_LIVE_CHECK_TIMEOUT_SECONDS,
                )
            else:
                session = build_session(data)
            account_id = caller_account_id(
                session,
                regions[0],
                timeout_seconds=cls.SELF_TEST_LIVE_CHECK_TIMEOUT_SECONDS,
            )
        except (BotoCoreError, ClientError) as exc:
            checks.append(
                check_fail(
                    "AWS_STS_REACHABLE",
                    f"STS AssumeRole/GetCallerIdentity failed: {exc}",
                    readiness_status=CollectorReadinessStatus.ERROR,
                    docs=_DOCS,
                )
            )
        else:
            mismatch = account_mismatch_error(data, account_id)
            if mismatch:
                checks.append(
                    check_fail(
                        "AWS_STS_REACHABLE",
                        mismatch,
                        readiness_status=CollectorReadinessStatus.MISCONFIGURED,
                        docs=_DOCS,
                    )
                )
            else:
                checks.append(
                    check_pass(
                        "AWS_STS_REACHABLE",
                        f"AWS reachable; collecting account {account_id}.",
                        context={"account_id": account_id},
                        docs=_DOCS,
                    )
                )

        return CollectorSelfTestResult.from_checks(
            checks,
            summary=(
                "AWS collector is ready."
                if all(not c.is_failure for c in checks)
                else "AWS collector cannot reach AWS."
            ),
            docs=_DOCS,
        )
