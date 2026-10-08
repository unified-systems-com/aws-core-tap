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

import json
from collections.abc import Mapping
from typing import Any

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError
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

from .authority import (
    COMPLETE,
    anchor_reads,
    claims_for,
    importer_accepts_edge_cases,
    merge_claims,
    shared_scopes,
)
from .batch import (
    address_batch,
    assemble_batch,
    envelope_ref,
    node_anchor,
    node_envelope,
    resolve_subject,
    withhold_retired_undeclared_edges,
)
from .containment import (
    Listing,
    containment_envelopes,
    footprint_envelopes,
    footprint_ref,
    owner_of,
    surface_of,
)
from .credentials import (
    AWS_SECRET_REF,
    CredentialError,
    account_mismatch_error,
    assume_role_session,
    base_creds,
    build_session,
    caller_account_id,
    client_factory,
    fips_requested,
    is_assumed_role,
    resolve_aws_secret,
    resolve_partition,
    resolve_regions,
)
from .customfns import build_custom_fn_registry
from .edges import EdgeError, account_ref, emit_containment, emit_edges
from .hydrate import hydrate_item
from .identity import IdentityError
from .landing_zone import LandingZoneRead, collect_landing_zone
from .ledger import CallLedger
from .listing import ListingWalk, surface_statement
from .manifest import load_manifest, manifest_entries
from .organizations import OrganizationTree, collect_organization, organizations_client
from .partition import PARTITION_AWS, service_unavailable_reason
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
_SITE_ABORT_PARTITION = "7a1d"
_SITE_SERVICE_UNAVAILABLE = "c58e"
_SITE_REGION_STATUS_UNREADABLE = "3a71"
_SITE_REGION_DISABLED = "c5e2"
_SITE_MIXED_PARTITIONS = "91b8"
_SITE_DUPLICATE_IDENTITY = "e40d"
_SITE_REGION_SKIPPED = "7f2a"
_SITE_ORG_NOTICE = "c81a"
_SITE_ORG_DUPLICATE_ACCOUNT = "e6b2"
_SITE_ORG_READ_FAILED = "a4f0"
_SITE_LZ_NOTICE = "7e19"
_SITE_LZ_READ_FAILED = "b3c6"
_SITE_EDGE_AUTHORITY = "f237"
_SITE_ABORT_IDENTITY_INCOMPLETE = "93cd"
_SITE_ADDRESSING = "7f5b"

#: How many non-complete claims the run log names one by one; the counts always cover all of them.
_AUTHORITY_DETAIL_CAP = 200

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
    - no ``tags`` block, or ``{"source": "none", ...}`` (AWS cannot tag the
      type, ``req-aws-collector-tags-12``) — ``({}, None, None)``.

    Tags reach the node envelope ONLY through this resolver — a manifest
    entry must never project tags via its ``fields`` map (the envelope
    stamps the resolved map after the projected fields, so a projected
    ``tags`` field is silently clobbered; the v0.4.0 scar).
    """
    block = entry.get("tags")
    if not block or block["source"] == "none":
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


def _anchor_name(anchor: Mapping[str, Any]) -> str:
    """An authority anchor as a hashable lookup key."""
    return json.dumps(anchor, sort_keys=True, default=str)


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

    def _record_authority(
        self, claims: list[dict[str, Any]], *, emitted: bool, node_envelopes: list[dict[str, Any]]
    ) -> None:
        """One run-log entry for the run's edge-authority claims (req-aws-collector-edge-authority).

        The counts by read status cover every claim; the claims that are not ``complete`` are named
        (entity type, name, edge type, direction, read) up to a cap, so a reader can see which anchors
        could not be read without opening the batch. ``emitted`` is false when the importer this run
        submits to does not accept an ``edge_cases`` section: the claims were judged and not sent.
        """
        counts = {"complete": 0, "partial": 0, "failed": 0}
        for claim in claims:
            counts[claim["read"]] = counts.get(claim["read"], 0) + 1
        names = {_anchor_name(node_anchor(n)): n["entity"]["name"] for n in node_envelopes}
        incomplete = [
            {
                "entity_type": claim["anchor"]["entity_type"],
                "name": names.get(_anchor_name(claim["anchor"]), ""),
                "edge_type": claim["edge_type"],
                "direction": claim["direction"],
                "read": claim["read"],
            }
            for claim in claims
            if claim["read"] != COMPLETE
        ]
        sent = "sent in the batch" if emitted else "not sent: the importer does not accept edge_cases"
        self.record_info(
            _SITE_EDGE_AUTHORITY,
            "EDGE_AUTHORITY_CLAIMS",
            f"{len(claims)} edge-authority claim(s), {sent}: {counts['complete']} complete, "
            f"{counts['partial']} partial, {counts['failed']} failed.",
            message_data={
                "emitted": emitted,
                "counts": counts,
                "incomplete": incomplete[:_AUTHORITY_DETAIL_CAP],
                "incomplete_truncated": len(incomplete) > _AUTHORITY_DETAIL_CAP,
            },
        )

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
        # The partition (commercial / GovCloud) is derived from the regions and checked against the
        # optional declared partition and the role ARN, so a wrong-partition secret fails here,
        # by name, rather than as an opaque InvalidClientTokenId from the wrong STS
        # (req-aws-collector-partition).
        try:
            partition = resolve_partition(data, regions)
        except CredentialError as exc:
            self._abort(_SITE_ABORT_PARTITION, "PARTITION_UNUSABLE", str(exc))
        # Attach the audit ledger before any client/STS call so every AWS call
        # this run makes is recorded — including a cross-account AssumeRole,
        # which is captured on the base session
        # (req-aws-collector-audit-ledger, req-aws-core-secret-aws-assumed-role-6).
        ledger = CallLedger()
        try:
            if is_assumed_role(data):
                base = build_session(base_creds(data))
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
                f"STS AssumeRole/GetCallerIdentity failed (partition {partition}, region {regions[0]}): {exc}",
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
            f"Collecting AWS account {account_id} ({partition}) across {len(regions)} region(s).",
            message_data={
                "account_id": account_id,
                "regions": regions,
                "partition": partition,
                "use_fips_endpoint": fips_requested(data),
            },
        )

        # --- manifest + engine collaborators ---
        manifest = load_manifest()
        entries = manifest_entries()
        modeled_types = {e["entity_type"] for e in entries}
        custom_fns = build_custom_fn_registry()
        transforms = build_transform_registry(partition)

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
        # The partition's global-service home region: us-east-1 commercial, us-gov-west-1
        # GovCloud, None for a partition with no settled answer (req-aws-core-regional-containment).
        # Deliberately NOT partition.home_region: that function always returns a concrete
        # region (falling back to the commercial anchor) because customfns.py needs one to bind
        # an actual client to; here a guess would misname the invariant for an unsettled
        # partition, so the None case is "nothing to warn about", not "assume commercial".
        home_region = global_service_region(partition)
        if home_region is not None and home_region not in regions:
            self.record_warn(
                _SITE_REGION_INVARIANT,
                "REGION_INVARIANT",
                f"Region scope omits {home_region}: global-resource tags"
                + (" and CloudFront-bound ACM certs" if partition == PARTITION_AWS else "")
                + " are silently missed.",
                message_data={"regions": regions, "partition": partition, "home_region": home_region},
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
        unavailable = 0
        # Refs already in this batch. Two refs describing one source object are a batch-fatal
        # duplicate_entity_id at import (the whole run's data lost); skip the repeat and say so instead.
        seen_nodes: set[str] = set()
        seen_edges: set[str] = set()
        # One completeness surface per contained (entry, region) listing, region-scoped containment
        # only (tap-plugin-aws-core#49, req-grid-reconcile-evidence).
        surfaces: list[dict[str, Any]] = []
        #: One (containment declaration, walk) per account-scoped listing this run attempted — region-
        #: scoped containment's counterpart to `surfaces` above; turned into completeness surfaces
        #: after the batch is submitted (tap-plugin-aws-core#43, req-aws-collector-reconcile).
        listings: list[tuple[dict[str, Any], ListingWalk]] = []
        #: Edge-authority claims (req-aws-collector-edge-authority): one per (edge type, anchor,
        #: direction) the manifest's edge rules cover at a node this run emitted, and the Organizations
        #: tree's reference edges (organizations.py, "Edge authority"), each with how it was read.
        #: Held as (sent node envelope, its per-scope reads) and made into claims once the batch is
        #: addressed, when every node's key is known to be whole.
        judged: list[tuple[dict[str, Any], dict[tuple[str, str], str]]] = []
        unclaimable = shared_scopes(entries)

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
                (seen_edges if bucket is edge_envelopes else seen_nodes).add(envelope_ref(envelope))
                bucket.append(envelope)

        for entry in entries:
            # A service the partition does not offer is a clear result, not a failed call.
            not_offered = service_unavailable_reason(partition, entry["service"])
            if not_offered:
                unavailable += 1
                self.record_info(
                    _SITE_SERVICE_UNAVAILABLE,
                    "SERVICE_NOT_AVAILABLE_IN_PARTITION",
                    f"{entry['entity_type']}: not available in partition {partition} — {not_offered}",
                    message_data={
                        "entity_type": entry["entity_type"],
                        "service": entry["service"],
                        "partition": partition,
                    },
                )
                continue
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
                                subject=footprint_ref(account_id, region),
                                facts=region_facts,
                                listing=None,
                            )
                        )
                    continue
                # Region-scoped containment (tap-plugin-aws-core#49) drives a `Listing`, tallied into
                # `surfaces` below; account-scoped containment (tap-plugin-aws-core#43) drives a
                # `ListingWalk`, tallied into `listings` and recorded once per run after the batch
                # (its subject is the account itself, not a per-region footprint). `entry["scope"]`
                # decides which applies — no entry declares both.
                listing = Listing() if (contained and entry["scope"] == "regional") else None
                walk = ListingWalk() if (contained and entry["scope"] != "regional") else None
                if walk is not None:
                    listings.append((contained, walk))
                listed = False
                try:
                    items = list(
                        iter_source(
                            entry,
                            client_for=client_factory(session, region),
                            custom_fns=custom_fns,
                            fn_context=session,
                            walk=walk,
                            truncated=listing.truncated if listing else None,
                        )
                    )
                    listed = True
                    if listing:
                        listing.count = len(items)
                        listing.done()
                    for item in items:
                        node = project_item(entry, item)
                        if node.ref in seen_nodes:
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
                        seen_nodes.add(node.ref)
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
                        if contained and entry["scope"] == "regional":
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
                            if envelope_ref(envelope) not in seen_edges:
                                seen_edges.add(envelope_ref(envelope))
                                edge_envelopes.append(envelope)
                        # Only once the node's edges are in the batch: a node whose edge pass raised
                        # gets no claim, so no scope is ever claimed over edges that were not sent.
                        # The claim is made once the batch is addressed (its anchor is the node's
                        # checked natural key), from the envelope this node was sent as.
                        judged.append(
                            (
                                node_envelopes[-1],
                                anchor_reads(node, entry, modeled_types=modeled_types, transforms=transforms),
                            )
                        )
                        for warning in emission.warnings:
                            self.record_warn(_SITE_EDGE_DROPPED, "EDGE_DROPPED", warning)
                        if contained and entry["scope"] != "regional":
                            edge_envelopes.append(
                                emit_containment(
                                    node, contained, account_id=account_id, dimensions=dimensions
                                )
                            )
                except (
                    SourceError,
                    EdgeError,
                    ProjectionError,
                    BotoCoreError,
                    ClientError,
                ) as exc:
                    if walk is not None:
                        # A listing that ended before the failure was read to the end but not carried
                        # to the batch (admitted=false); one that had not ended is simply not known
                        # to be complete (fail).
                        if walk.complete is True:
                            walk.drop(f"{type(exc).__name__} while processing the listed items")
                        else:
                            walk.fail(exc)
                    skipped += 1
                    hint = ""
                    if isinstance(exc, EndpointConnectionError) and partition != PARTITION_AWS:
                        hint = (
                            f" (no reachable {entry['service']} endpoint in partition {partition}: "
                            "the service may not be offered there)"
                        )
                    self.record_warn(
                        _SITE_ENTRY_SKIPPED,
                        "ENTRY_SKIPPED",
                        f"Skipped {entry['entity_type']} in {region_label}: {exc}{hint}",
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
                if contained and entry["scope"] == "regional":
                    # `listing` is always set here (`Listing() if ... else None`, above) —
                    # `surface_of`'s own `listing: Listing | None` parameter tolerates None
                    # regardless, so no assert is needed to narrow the type for a check that
                    # would vanish under `-O` anyway (Bandit B101).
                    surfaces.append(
                        surface_of(
                            relation=contained["relation"],
                            edge_type=contained["edge_type"],
                            subject=footprint_ref(account_id, region),
                            facts=region_facts,
                            listing=listing,
                        )
                    )

        # --- AWS Organizations tree (req-aws-core-organizations-collect, tap-plugin-aws-core#50) ---
        # One structure, not a per-account resource list, so it is its own read rather than a
        # manifest entry — see collectors/boto3_collector/organizations.py. Global scope, the run's
        # own first region: the endpoint (and with it the partition — GovCloud, commercial or China)
        # follows the credential exactly as every other global-scope entry's client does.
        # collect_organization itself never lets an AWS call escape (every one is wrapped in
        # ClientError/BotoCoreError handling and degrades to a reasoned, incomplete Listing). This
        # try/except is defense against a defect INSIDE this collector's own shaping code — an
        # unregistered entity type, a malformed schema lookup, an unexpected None — the same
        # failure class every per-entry manifest read below is already isolated against
        # (ENTRY_SKIPPED); the Organizations tree is one more optional surface, not a reason to
        # fail the whole run and lose every already-gathered resource.
        org_dimensions = {"cloud": "aws", "aws_account": account_id, "aws_region": "global"}
        try:
            org_tree = collect_organization(organizations_client(session, regions[0]), org_dimensions)
        except Exception as exc:  # noqa: BLE001 — isolates a defect in this read, never the run
            self.record_warn(
                _SITE_ORG_READ_FAILED,
                "ORG_READ_FAILED",
                f"Organizations tree collection failed unexpectedly and was skipped: "
                f"{type(exc).__name__}: {exc}",
            )
            org_tree = OrganizationTree()
        for org_notice in org_tree.notices:
            (self.record_warn if org_notice.level == "warn" else self.record_info)(
                _SITE_ORG_NOTICE, org_notice.code, org_notice.message, message_data=org_notice.data
            )
        # The account this run is scoped to may itself be a member the tree walk names: the
        # manifest's `aws_account_singleton` entry above already wrote a node under that same ref
        # (same entity_type + account_id). A batch cannot carry two refs for one source object
        # (req-grid-import-grift-identity-3), so the richer org-tree node (email, status, tags, its
        # OU) wins and the plainer singleton envelope is dropped, never the reverse — the singleton
        # exists so a non-organization account still gets one.
        existing_ids = {envelope_ref(n) for n in node_envelopes}
        org_node_ids = {envelope_ref(n) for n in org_tree.nodes}
        overridden = existing_ids & org_node_ids
        if overridden:
            self.record_info(
                _SITE_ORG_DUPLICATE_ACCOUNT,
                "ORG_ACCOUNT_NODE_MERGED",
                "The collector's own account is also a member the Organizations tree named; "
                "its richer node from the tree replaces the manifest singleton.",
                message_data={"count": len(overridden)},
            )
            node_envelopes = [n for n in node_envelopes if envelope_ref(n) not in overridden]
        node_envelopes.extend(org_tree.nodes)
        edge_envelopes.extend(org_tree.edges)
        # The tree's reference edges are claimed per node as well (req-aws-collector-edge-authority-7,
        # -8): only nodes the tree wrote, each with the read organizations.py judged for it.
        judged.extend(
            (envelope, org_tree.edge_reads[envelope_ref(envelope)])
            for envelope in org_tree.nodes
            if envelope_ref(envelope) in org_tree.edge_reads
        )

        # --- Landing-zone governance (aws-core-tap#66, spec-aws-core-landing-zone.md) ---
        # Control Tower, Identity Center and the per-region security services of this run's account:
        # its own collaborator for the same reason the Organizations tree is (collectors/boto3_collector/
        # landing_zone.py). Collect-only: every surface it records is inert until reconcile authority is
        # armed. It never lets an AWS call escape; this guard isolates a defect in its own shaping code,
        # exactly as the Organizations read above is isolated.
        try:
            landing_zone = collect_landing_zone(
                lambda service, region: session.client(
                    service, region_name=region, config=Config(retries={"mode": "standard"})
                ),
                account_id=account_id,
                partition=partition,
                regions=regions,
                facts=facts,
                member_accounts=org_tree.member_accounts,
            )
        except Exception as exc:  # noqa: BLE001 — isolates a defect in this read, never the run
            self.record_warn(
                _SITE_LZ_READ_FAILED,
                "LANDING_ZONE_READ_FAILED",
                f"Landing-zone collection failed unexpectedly and was skipped: {type(exc).__name__}: {exc}",
            )
            landing_zone = LandingZoneRead()
        for lz_notice in landing_zone.notices:
            (self.record_warn if lz_notice.level == "warn" else self.record_info)(
                _SITE_LZ_NOTICE, lz_notice.code, lz_notice.message, message_data=lz_notice.data
            )
        present = {envelope_ref(n) for n in node_envelopes}
        node_envelopes.extend(n for n in landing_zone.nodes if envelope_ref(n) not in present)
        edge_envelopes.extend(landing_zone.edges)
        surfaces.extend(landing_zone.regional_surfaces)
        # The two account settings are typed fields on nodes this run already writes: EBS default
        # encryption on each footprint, the S3 account public-access block on the run's own account
        # node (whichever path wrote it, the manifest singleton or the Organizations tree).
        by_ref = {envelope_ref(n): n for n in node_envelopes}
        for region, fields in landing_zone.footprint_fields.items():
            footprint = by_ref.get(footprint_ref(account_id, region))
            if footprint is not None:
                footprint["node"].update(fields)
        own_account = by_ref.get(account_ref(account_id))
        if own_account is not None and landing_zone.account_fields:
            own_account["node"].update(landing_zone.account_fields)

        # --- one GRIFT batch per run, everything named by identity (req-aws-collector-identity) ---
        # A node whose declared key has a hole would be created afresh on every run, so the run
        # fails here rather than send it. Permissive dangling mode: an endpoint naming a node no
        # live row matches skips that edge and core records a skip event, never a failure.
        try:
            addressed = address_batch(node_envelopes, edge_envelopes)
        except IdentityError as exc:
            self._abort(_SITE_ABORT_IDENTITY_INCOMPLETE, "IDENTITY_INCOMPLETE", str(exc))
            raise  # unreachable: _abort raises; keeps `addressed` bound for the type checker
        withhold_retired_undeclared_edges(addressed)
        for code, message in addressed.notices:
            self.record_warn(_SITE_ADDRESSING, code, message)
        node_envelopes, edge_envelopes = addressed.nodes, addressed.edges
        claims = merge_claims(
            claim
            for envelope, reads in judged
            for claim in claims_for(node_anchor(envelope), reads, unclaimable=unclaimable)
        )
        authority_emitted = bool(claims) and importer_accepts_edge_cases()
        document = assemble_batch(
            source=_SOURCE,
            manifest_version=manifest["manifest_version"],
            account_id=account_id,
            regions=regions,
            node_envelopes=node_envelopes,
            edge_envelopes=edge_envelopes,
            authority=claims if authority_emitted else None,
        )
        self._record_authority(claims, emitted=authority_emitted, node_envelopes=node_envelopes)
        # Abort-on-rejection is owned by CollectorBase.submit_grift
        # (on_rejection="abort" default): a rejected batch records a
        # structured GRIFT_BATCH_REJECTED error and raises GriftRejectedError,
        # which the task body turns into the FAILED terminal patch. No
        # per-collector guard — see req-tap-cares-collector-grift-import-9.
        result = self.submit_grift(document, dangling_edge_mode="permissive")
        # Every listing this run read is recorded against the batch that carries its observations;
        # `applied` is derived by the recorder from that batch's commit. Each surface's subject was
        # written as the parent's ref (the footprint for region-scoped containment,
        # tap-plugin-aws-core#49; the account for account-scoped, #43); here it becomes the grid id
        # core found or assigned for that ref, read from the import result. Candidate derivation
        # resolves the subject as a grid entity id and needs the parent observed this run before it
        # fans out from it (tap_grid/candidates.py::_derive_surface). A run that read no contained
        # listing of either kind says so (a statement with zero surfaces, not no statement).
        collection_batch_id = str(document["batches"][0]["batch_entity"]["entity_id"])
        resolved_refs: dict[str, str] = {}
        for imported_batch in result.imported_batches:
            resolved_refs.update(imported_batch.resolved_refs)
        for surface in surfaces:
            surface = {**surface, "subject": resolve_subject(surface["subject"], addressed, resolved_refs)}
            self.record_surface(**surface, applied_batches=[collection_batch_id])
        for containment, walk in listings:
            self.record_surface(
                **surface_statement(
                    walk,
                    relation=containment["relation"],
                    edge_type=containment["edge_type"],
                    subject=resolve_subject(account_ref(account_id), addressed, resolved_refs),
                    applied_batches=[collection_batch_id],
                )
            )
        if not surfaces and not listings:
            self.declare_no_surfaces()
        self.record_info(
            _SITE_GRIFT_SUBMITTED,
            "GRIFT_SUBMITTED",
            "AWS Core GRIFT batch submitted.",
            message_data={"imported": [str(b.batch_entity_id) for b in result.imported_batches]},
        )

        # Completeness surfaces for the Organizations tree and the landing zone
        # (req-grid-reconcile-evidence): each `subject` was recorded as the parent's ref and becomes
        # the grid id the import resolved it to, so the surfaces are authored once the batch that
        # carries their observations has imported, which `submit_grift` above just did (a rejected
        # batch aborts the run before this line is reached — `submit_grift`'s default `on_rejection`).
        applied_batches = [str(b.batch_entity_id) for b in result.imported_batches]
        for parent_listing in [*org_tree.listings, *landing_zone.listings]:
            statement = parent_listing.surface(applied_batches)
            statement["subject"] = resolve_subject(statement["subject"], addressed, resolved_refs)
            self.record_surface(**statement)
        if not org_tree.listings and not landing_zone.listings:
            self.declare_no_surfaces()

        imported = result.counts.batches_imported
        self.summary = (
            f"Collected {len(node_envelopes)} nodes, {len(edge_envelopes)} "
            f"edges for account {account_id} ({partition}) across {len(regions)} region(s) "
            f"({skipped} skipped, {unavailable} not offered in this partition, {imported} batch imported)."
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

        # 2b. Partition is coherent (regions, declared partition, role ARN) and supported.
        try:
            partition = resolve_partition(data, regions)
        except CredentialError as exc:
            checks.append(
                check_fail(
                    "AWS_PARTITION",
                    str(exc),
                    readiness_status=CollectorReadinessStatus.MISCONFIGURED,
                    docs=_DOCS,
                )
            )
            return CollectorSelfTestResult.from_checks(
                checks,
                summary="AWS collector partition is not usable.",
                docs=_DOCS,
            )
        checks.append(
            check_pass(
                "AWS_PARTITION",
                f"AWS collector is scoped to partition {partition} "
                f"(FIPS endpoints {'on' if fips_requested(data) else 'off'}).",
                context={"partition": partition, "use_fips_endpoint": fips_requested(data)},
                docs=_DOCS,
            )
        )

        # 3. Read-only reachability: STS within budget. For the assumed-role
        #    kind this also performs the AssumeRole (proving the cross-account
        #    trust is wired) before the GetCallerIdentity probe.
        try:
            if is_assumed_role(data):
                session = assume_role_session(
                    build_session(base_creds(data)),
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
