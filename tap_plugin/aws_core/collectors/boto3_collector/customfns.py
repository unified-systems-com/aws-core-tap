"""Registered ``custom_fn`` callables for the boto3 collector.

Spec: plugins/aws_core/specs/spec-aws-core-collector-v0.md
(req-aws-collector-source / req-aws-collector-hydrate).

A ``custom_fn`` is the thin per-service glue for resources AWS cannot
enumerate richly in one call. It composes the reusable :func:`hydrate_item`
template (it does not hand-roll multi-call logic) and yields raw items in the
same shape an ``aws_op`` would. Code is never loaded from manifest data; the
manifest only names the callable.

S3 is the worst-case fan-out the seam exists for: ``ListBuckets`` returns a
few fields and the compliance-relevant state comes from independent
per-bucket ``GetBucket*`` calls. The hydrate op list lives in the manifest
(``req-aws-collector-hydrate-3``); this glue only supplies the S3-specific
identifier binding (``Bucket=<name>``) and per-bucket region routing (S3
redirects ``GetBucket*`` to the bucket's own region).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from .authority import COMPLETE, FAILED, PARTIAL, with_edge_reads
from .envelope import jsonable, without_response_metadata
from .hydrate import hydrate_item
from .iam_trust import account_of_iam_arn, summarize_trust_policy
from .listing import ListingWalk, error_code, page_says_more
from .manifest import manifest_entries
from .partition import (
    PARTITION_AWS,
    PARTITION_RE,
    build_arn,
    home_region,
    partition_of_region,
    service_unavailable_reason,
)
from .source import CustomFnRegistry, iter_listing


def _hydrate_ops(entity_type: str) -> list[dict[str, str]]:
    """The manifest-declared hydrate list for ``entity_type`` (the manifest is the source)."""
    for entry in manifest_entries():
        if entry["entity_type"] == entity_type:
            ops: list[dict[str, str]] = entry.get("hydrate", [])
            return ops
    return []

# The region used to reach a partition-global service ONLY when a caller supplies neither a
# ``client_for`` nor a session with a region (unit tests, an ad-hoc call). At run time the
# collector always passes ``client_for``, bound to the run's own region — in the run's own
# partition — so no literal region decides the partition (req-aws-collector-partition).
_FALLBACK_REGION = home_region(PARTITION_AWS)


def _run_client(session: Any, client_for: Any, service: str) -> Any:
    """A client for ``service`` in the RUN's partition.

    A "global" service (IAM, STS, Route 53, CloudFront, S3 ListBuckets) is still addressed
    through a region of the credential's own partition: botocore then resolves the partition's
    global endpoint (``iam.us-gov.amazonaws.com`` in GovCloud). ``client_for`` is the run's
    region-bound factory; without one, fall back to the session's own region, then to the
    commercial anchor (never reached by ``Boto3Collector.run``).
    """
    if client_for is not None:
        return client_for(service)
    return session.client(service, region_name=getattr(session, "region_name", None) or _FALLBACK_REGION)


def _client_partition(client: Any) -> str:
    """The partition a client is bound to (``client.meta.partition``), tolerating test doubles
    that carry none — those are commercial, as an empty region is."""
    partition = getattr(getattr(client, "meta", None), "partition", None)
    if isinstance(partition, str) and partition:
        return partition
    return partition_of_region(_client_region(client))


def _s3_hydrate_ops() -> list[dict[str, str]]:
    """The manifest-declared S3 hydrate list (manifest is the source)."""
    return _hydrate_ops("aws_core__aws_s3_bucket")


def _resolve_bucket_region(base_client: Any, bucket_name: str) -> str:
    """Resolve a bucket's home region.

    ``GetBucket*`` calls are region-bound (S3 redirects otherwise);
    ``GetBucketLocation`` gives the region. A failed lookup falls back to the
    partition's anchor region (``home_region``) — never a literal
    ``us-east-1``, which does not exist in GovCloud. An empty
    ``LocationConstraint`` is S3's encoding of the partition's classic region
    (``us-east-1`` in the commercial partition; GovCloud always names its region).
    """
    home = home_region(_client_partition(base_client))
    try:
        location = base_client.get_bucket_location(Bucket=bucket_name)
        return location.get("LocationConstraint") or home
    except ClientError, BotoCoreError:
        return home


# BucketSizeBytes has no all-tiers rollup dimension — it must be queried per
# storage tier. NumberOfObjects has the convenient AllStorageTypes. The
# collector sums whichever size tiers return data, so a lifecycled bucket
# (objects tiered to Glacier etc.) reports a complete total.
_S3_SIZE_STORAGE_TYPES = (
    "StandardStorage",
    "IntelligentTieringFAStorage",
    "IntelligentTieringIAStorage",
    "StandardIAStorage",
    "OneZoneIAStorage",
    "GlacierInstantRetrievalStorage",
    "GlacierStorage",
    "DeepArchiveStorage",
    "ReducedRedundancyStorage",
)


def _bucket_size_metrics(cw_client: Any, bucket_name: str) -> dict[str, Any]:
    """Aggregate bucket size + object count from CloudWatch storage metrics.

    S3 publishes ``BucketSizeBytes`` / ``NumberOfObjects`` to the ``AWS/S3``
    CloudWatch namespace daily, free. One ``get_metric_data`` call per bucket
    batches the ``NumberOfObjects`` query and a ``BucketSizeBytes`` query per
    storage tier; tiers with data are summed. This is the fast path — the
    alternative (summing ``list_objects_v2``) is one call per 1000 objects.

    ``size_observed_at`` is the datapoint's own ``Timestamp`` — the
    data-currency disclosure (the metrics are daily, so the values are not
    real-time; the consumer derives staleness from this timestamp). See
    req-aws-collector-s3-bucket-size.

    A denied/failed CloudWatch call is non-fatal: the three fields come back
    empty/null (unknown, never a misleading 0) and the bucket still collects.
    """
    from datetime import UTC, datetime, timedelta

    empty: dict[str, Any] = {"size_bytes": None, "object_count": None, "size_observed_at": ""}
    end = datetime.now(UTC)
    start = end - timedelta(days=3)  # daily metric — a 3-day window catches the latest

    def _query(qid: str, metric: str, storage_type: str) -> dict[str, Any]:
        return {
            "Id": qid,
            "MetricStat": {
                "Metric": {
                    "Namespace": "AWS/S3",
                    "MetricName": metric,
                    "Dimensions": [
                        {"Name": "BucketName", "Value": bucket_name},
                        {"Name": "StorageType", "Value": storage_type},
                    ],
                },
                "Period": 86400,
                "Stat": "Average",
            },
            "ReturnData": True,
        }

    queries = [_query("objcount", "NumberOfObjects", "AllStorageTypes")]
    queries += [_query(f"size{i}", "BucketSizeBytes", st) for i, st in enumerate(_S3_SIZE_STORAGE_TYPES)]

    try:
        resp = cw_client.get_metric_data(
            MetricDataQueries=queries,
            StartTime=start,
            EndTime=end,
            ScanBy="TimestampDescending",
        )
    except BotoCoreError, ClientError:
        return dict(empty)

    object_count: int | None = None
    size_bytes: int | None = None
    latest: Any = None
    for result in resp.get("MetricDataResults", []):
        values = result.get("Values") or []
        if not values:
            continue
        timestamps = result.get("Timestamps") or []
        # ScanBy=TimestampDescending -> index 0 is the most recent datapoint.
        value = values[0]
        ts = timestamps[0] if timestamps else None
        if ts is not None and (latest is None or ts > latest):
            latest = ts
        if result.get("Id") == "objcount":
            object_count = int(value)
        else:
            size_bytes = (size_bytes or 0) + int(value)

    if object_count is None and size_bytes is None:
        return dict(empty)
    return {
        "size_bytes": size_bytes,
        "object_count": object_count,
        "size_observed_at": latest.isoformat() if latest is not None else "",
    }


#: The four S3 Block Public Access settings. A bucket is blocked only when every one is on.
_PAB_FLAGS = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")


def public_access_blocked(slot: dict[str, Any] | None) -> bool | None:
    """The bucket's ``public_access_blocked`` from its ``GetPublicAccessBlock`` hydrate slot
    (req-aws-core-fields-9).

    - ``ok`` with all four flags true -> ``True``; any flag false or missing -> ``False``.
    - ``absent`` (``NoSuchPublicAccessBlockConfiguration``) -> ``False``: the bucket has no
      bucket-level block. Account-level Block Public Access is not read or modelled, so this
      says nothing about it.
    - ``denied`` / ``error`` / no slot -> ``None``: not observed, never a guess either way.
    """
    if not slot:
        return None
    status = slot.get("status")
    if status == "absent":
        return False
    if status != "ok":
        return None
    config = (slot.get("data") or {}).get("PublicAccessBlockConfiguration")
    if not isinstance(config, dict):
        return None
    return all(config.get(flag) is True for flag in _PAB_FLAGS)


def s3_buckets_hydrated(
    session: Any, *, client_for: Any = None, walk: ListingWalk | None = None
) -> Iterator[dict[str, Any]]:
    """Enumerate S3 buckets and fan out each bucket's compliance sub-config.

    Yields one envelope per bucket: the ``ListBuckets`` item at the root
    (carrying ``BucketArn`` — the stable natural key), the ``_hydrate`` /
    ``_hydrate_mapping`` siblings the hydrate template assembles, and the
    aggregate ``size_bytes`` / ``object_count`` / ``size_observed_at`` from
    CloudWatch storage metrics (req-aws-collector-s3-bucket-size).

    The listing is paginated to its end: ``ListBuckets`` pages by continuation token and AWS supports
    the unpaginated call only for accounts at the default 10,000-bucket quota, so a single call is a
    silent truncation for a larger account. ``walk`` records whether the last page still reported more,
    which is what decides whether the account's bucket list may be treated as complete. The client is the
    engine's region-bound one, so a GovCloud account is listed against the GovCloud endpoint.
    """
    walk = walk if walk is not None else ListingWalk()
    base = client_for("s3") if client_for is not None else session.client("s3")
    buckets = list(iter_listing(base, "list_buckets", "Buckets[]", walk))
    hydrate_ops = _s3_hydrate_ops()
    partition = _client_partition(base)

    for bucket in buckets:
        name = bucket.get("Name")
        if name and not bucket.get("BucketArn"):
            # ListBuckets echoes BucketArn on current API versions; if a partition's endpoint does
            # not, the ARN is a pure function of the name and the partition (it is the natural key).
            bucket = {**bucket, "BucketArn": build_arn(partition, "s3", "", "", name)}
        region = _resolve_bucket_region(base, name)
        regional = session.client("s3", region_name=region)
        envelope = hydrate_item(regional, bucket, hydrate_ops, call_kwargs={"Bucket": name})
        envelope["_public_access_blocked"] = public_access_blocked(envelope["_hydrate"].get("public_access_block"))
        # CloudWatch S3 storage metrics are region-bound, like GetBucket*.
        cw = session.client("cloudwatch", region_name=region)
        envelope.update(_bucket_size_metrics(cw, name))
        yield envelope


def _pages(client: Any, method: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
    """Yield response pages for ``method``, paginated when botocore can.

    Mirrors :func:`.source.iter_aws_op`'s paginate-or-single robustness,
    with ``ResponseMetadata`` stripped per page.
    """
    if client.can_paginate(method):
        for page in client.get_paginator(method).paginate(**kwargs):
            yield without_response_metadata(page)
        return
    yield without_response_metadata(getattr(client, method)(**kwargs))


@dataclass(frozen=True)
class SubRead:
    """One per-resource sub-listing an edge rule reads, and how it went (authority.py's three values).

    ``failed`` carries no items (what an errored walk returned is not the answer); ``partial`` keeps the
    items read before the listing stopped short.
    """

    items: list[Any]
    status: str
    reason: str = ""


def read_sub_listing(client: Any, method: str, items_key: str, **kwargs: Any) -> SubRead:
    """Read one per-resource sub-listing to its end and say whether it got there.

    A raised call is ``failed`` and a final page that still reports more is ``partial``: neither is
    ever handed back as a complete answer, which is what lets an empty ``complete`` mean "none".
    """
    items: list[Any] = []
    last: Any = None
    try:
        for page in _pages(client, method, **kwargs):
            last = page
            items.extend(page.get(items_key) or [])
    except (BotoCoreError, ClientError) as exc:
        return SubRead([], FAILED, f"{method}: {error_code(exc) or type(exc).__name__}")
    if page_says_more(last):
        return SubRead(items, PARTIAL, f"{method}: the last page still reports more")
    return SubRead(items, COMPLETE)


def route53_zones_with_alias_targets(session: Any, *, client_for: Any = None) -> Iterator[dict[str, Any]]:
    """Enumerate Route 53 hosted zones, resolving CloudFront alias targets.

    Route 53's ``ListHostedZones`` is shallow; the routing relationship
    lives in each zone's record sets, where an A/AAAA *alias* whose
    ``AliasTarget.DNSName`` is a CloudFront distribution domain expresses
    "this zone routes traffic to that distribution". The edge target
    (``aws_cloudfront_distribution``) is ARN-keyed, but a record set only
    carries the CloudFront *domain* — bridging domain -> ARN is a
    cross-resource join no pure scalar transform can do. That join is
    exactly what this ``custom_fn`` seam exists for: it lists CloudFront
    once, builds a ``domain -> ARN`` map, and yields each zone enriched
    with the resolved ``alias_cloudfront_arns`` so ``ROUTES_TRAFFIC``
    resolves by deterministic identity with no transform (the make-it-work
    natural-key discipline; req-aws-collector-edges-7). The raw
    ``alias_cloudfront_domains`` stay lossless in ``configuration``.

    CloudFront and Route 53 are global; their clients are bound to the RUN's
    region (a region of the credential's own partition — ``us-east-1`` in the
    commercial partition, ``us-gov-*`` in GovCloud). CloudFront does not exist
    in GovCloud: the join is skipped there (zones still collect, with their raw
    ``alias_cloudfront_domains`` and no resolved ARNs).
    """
    r53 = _run_client(session, client_for, "route53")
    arn_by_domain: dict[str, str] = {}
    if service_unavailable_reason(_client_partition(r53), "cloudfront") is None:
        cf = _run_client(session, client_for, "cloudfront")
        for page in _pages(cf, "list_distributions"):
            for dist in (page.get("DistributionList", {}) or {}).get("Items", []) or []:
                domain = (dist.get("DomainName") or "").rstrip(".").lower()
                arn = dist.get("ARN")
                if domain and arn:
                    arn_by_domain[domain] = arn

    for zpage in _pages(r53, "list_hosted_zones"):
        for zone in zpage.get("HostedZones", []):
            zone_id = zone.get("Id")
            domains: list[str] = []
            arns: list[str] = []
            # How the zone's ROUTES_TRAFFIC scope was read (authority.py). A record-set listing that
            # raises still fails the whole entry, as before; one that stops on a page saying "more",
            # or an alias whose distribution is not in this account's listing (another account's, or
            # a partition without CloudFront), leaves the scope partial: a routing the collector saw
            # but could not wire is not an absence.
            routes_read = COMPLETE
            last_page: Any = None
            for rpage in _pages(r53, "list_resource_record_sets", HostedZoneId=zone_id):
                last_page = rpage
                for rr in rpage.get("ResourceRecordSets", []):
                    dns = (rr.get("AliasTarget") or {}).get("DNSName") or ""
                    domain = dns.rstrip(".").lower()
                    if not domain.endswith(".cloudfront.net"):
                        continue
                    domains.append(domain)
                    arn = arn_by_domain.get(domain)
                    if arn is not None:
                        arns.append(arn)
                    else:
                        routes_read = PARTIAL
            if page_says_more(last_page):
                routes_read = PARTIAL
            # Dedupe order-preserving: a zone routing to one distribution
            # via BOTH an A and an AAAA alias (the standard IPv4+IPv6
            # setup) yields the domain/ARN twice. Without dedup, edge
            # fan-out emits two edges with the same deterministic
            # edge_entity_id -> a duplicate_entity_id that GRIFT rejects
            # the whole batch over. One CF distribution -> one edge.
            yield with_edge_reads(
                {
                    **zone,
                    "alias_cloudfront_domains": list(dict.fromkeys(domains)),
                    "alias_cloudfront_arns": list(dict.fromkeys(arns)),
                    # Bare zone ID (last path segment of Id like "/hostedzone/Z…").
                    # list_tags_for_resource wants ResourceId in this form; Id
                    # itself stays as boto3 returned it so existing identity and
                    # downstream consumers don't shift.
                    "_zone_resource_id": (zone_id or "").rsplit("/", 1)[-1],
                },
                {"alias_cloudfront_arns": routes_read},
            )


def aws_account_singleton(session: Any, *, client_for: Any = None) -> Iterator[dict[str, Any]]:
    """Synthesize the one ``aws_account`` node for the account this run scopes to.

    No AWS API enumerates "the account" as a resource — ``STS
    GetCallerIdentity`` is the canonical way to learn which account the
    run's credentials belong to. The optional IAM account alias
    (``ListAccountAliases``) supplies a friendlier name; absent an alias the
    name falls back to ``AWS Account <id>``.

    Yields exactly one item. The account id sits at ``Account`` — the
    manifest entry's ``natural_key`` — so ``node_entity_id("aws_account",
    "<id>")`` is deterministic. Any node minted elsewhere with the same id
    (e.g. a hand-written GRIFT batch) upserts cleanly onto the collector's.

    STS is reached in the run's region and IAM through its partition-global
    endpoint (``iam.us-gov.amazonaws.com`` in GovCloud) — both via the run's
    ``client_for``, never a literal ``us-east-1``, which is the wrong partition
    for a GovCloud credential. Without one (a unit test driving the function
    directly), ``_run_client`` falls back to the session's own region, then the
    partition's home region — never a bare literal (never reached by
    ``Boto3Collector.run``).
    """
    sts = _run_client(session, client_for, "sts")
    identity = without_response_metadata(sts.get_caller_identity())
    account_id = identity.get("Account") or ""

    aliases: list[str] = []
    try:
        iam = _run_client(session, client_for, "iam")
        alias_resp = without_response_metadata(iam.list_account_aliases())
        aliases = list(alias_resp.get("AccountAliases", []) or [])
    except BotoCoreError, ClientError:
        # The account alias is a nicety, not load-bearing — a denied or
        # failed ListAccountAliases just falls the name back to the id form.
        aliases = []

    yield {
        "Account": account_id,
        "Arn": identity.get("Arn"),
        "UserId": identity.get("UserId"),
        "_account_name": aliases[0] if aliases else f"AWS Account {account_id}",
        "_account_aliases": aliases,
    }


def _origin_access_mode(origin: dict[str, Any]) -> str:
    """How CloudFront authenticates to one origin: ``oac``, ``oai`` or ``none``.

    Read from the ``DistributionSummary`` origin itself, with no extra call:
    a non-empty ``OriginAccessControlId`` is an origin access control, a
    non-empty ``S3OriginConfig.OriginAccessIdentity`` is a legacy origin access
    identity, and neither is ``none``. ``none`` means only that CloudFront uses
    no OAC or OAI for that origin. It does not mean the origin is public: a
    custom origin may still check a shared-secret header
    (``CustomHeaders``), whose presence :func:`_origin_has_custom_headers`
    records separately. OAC wins if both are set.
    """
    if origin.get("OriginAccessControlId"):
        return "oac"
    if ((origin.get("S3OriginConfig") or {}).get("OriginAccessIdentity") or "").strip():
        return "oai"
    return "none"


def _origin_has_custom_headers(origin: dict[str, Any]) -> bool:
    """Whether CloudFront sends any custom header to one origin.

    Presence only: a custom origin header is often a
    shared secret the origin checks, so this reads nothing from the header
    except that it exists. No ``HeaderValue`` and no ``HeaderName`` leaves
    this function. A non-empty ``CustomHeaders.Items`` or a positive
    ``CustomHeaders.Quantity`` is ``True``; an origin whose ``CustomHeaders``
    is absent, empty or has ``Quantity`` 0 is ``False``, an observed absence.
    """
    headers = origin.get("CustomHeaders") or {}
    return bool(headers.get("Items")) or (headers.get("Quantity") or 0) > 0


def cloudfront_distributions_with_oac(session: Any, *, client_for: Any = None) -> Iterator[dict[str, Any]]:
    """Enumerate CloudFront distributions, embedding each origin's OAC config.

    ``ListDistributions`` returns distribution summaries that carry an
    ``Origins.Items[].OriginAccessControlId`` — but the OAC itself (its
    signing protocol/behavior and origin type) lives behind a separate
    ``GetOriginAccessControl`` call. An OAC has no ARN; it is referenced by
    an opaque ``Id``. This ``custom_fn`` resolves every distinct OAC id a
    distribution's origins reference and embeds the results under
    ``_origin_access_controls`` (an ``{oac_id: details}`` map) so they land
    losslessly in the distribution's configuration envelope (not persisted:
    the manifest entry's ``persist_configuration`` is false). The OAC is a
    configuration detail of the distribution, not a separate node — the
    "have it handy" call from the strat-sam-demo discussion (2026-05-21).

    It also derives ``_origin_access``: ``{origin Id: "oac" | "oai" | "none"}``
    (see :func:`_origin_access_mode`), projected to the typed
    ``origin_access`` field so the fact survives with configuration off.

    And ``_origin_custom_headers_present``: ``{origin Id: bool}`` (see
    :func:`_origin_has_custom_headers`), projected to the typed
    ``origin_custom_headers_present`` field. Presence only: the header values
    are a credential and the names are not kept either (a name such as
    ``X-Origin-Verify`` says which secret to steal).

    The yielded item is the unchanged ``DistributionSummary`` plus those three
    extra keys, so the manifest's ``natural_key`` (``ARN``), ``fields``,
    ``tags``, and ``edges`` (``Origins.Items[].DomainName``,
    ``ViewerCertificate.ACMCertificateArn``) all still resolve.

    CloudFront is global; the client is bound to the run's region (the commercial
    partition's global endpoint). CloudFront does not exist in GovCloud — the
    collector records "not available in this partition" for the entry before
    calling this; if called directly there it yields nothing.
    """
    cf = _run_client(session, client_for, "cloudfront")
    if service_unavailable_reason(_client_partition(cf), "cloudfront") is not None:
        return
    # Cache across distributions: two distributions sharing an OAC -> one call.
    oac_cache: dict[str, Any] = {}
    for page in _pages(cf, "list_distributions"):
        for dist in (page.get("DistributionList", {}) or {}).get("Items", []) or []:
            oac_ids: list[str] = []
            origin_access: dict[str, str] = {}
            headers_present: dict[str, bool] = {}
            for origin in (dist.get("Origins") or {}).get("Items", []) or []:
                if origin.get("Id"):
                    origin_access[origin["Id"]] = _origin_access_mode(origin)
                    headers_present[origin["Id"]] = _origin_has_custom_headers(origin)
                oac_id = origin.get("OriginAccessControlId")
                if oac_id and oac_id not in oac_ids:
                    oac_ids.append(oac_id)
            oacs: dict[str, Any] = {}
            for oac_id in oac_ids:
                if oac_id not in oac_cache:
                    try:
                        resp = without_response_metadata(cf.get_origin_access_control(Id=oac_id))
                        oac_cache[oac_id] = resp.get("OriginAccessControl") or resp
                    except BotoCoreError, ClientError:
                        # A per-OAC miss is non-fatal: the distribution still
                        # collects; the slot records None so the gap is visible.
                        oac_cache[oac_id] = None
                oacs[oac_id] = oac_cache[oac_id]
            # Both edge rules read the DistributionSummary itself: the listing's own record, so a
            # distribution that was listed was read whole for them (authority.py).
            yield with_edge_reads(
                {
                    **dist,
                    "_origin_access_controls": oacs,
                    "_origin_access": origin_access,
                    "_origin_custom_headers_present": headers_present,
                },
                {"Origins": COMPLETE, "ViewerCertificate": COMPLETE},
            )


def dynamodb_tables_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate DynamoDB tables (regional) and describe each.

    ``ListTables`` returns table-name strings only — no ARN, no status,
    no billing mode. ``DescribeTable`` per name is the standard fan-out
    to get the full payload. Yields the ``Table`` sub-object from each
    DescribeTable response so the manifest's ``items_path`` and
    ``natural_key`` see a flat dict with ``TableArn`` at the root.

    Regional: the engine binds ``client_for`` to the current region; this
    function runs once per region in the run's scope.
    """
    client = client_for("dynamodb")
    for page in _pages(client, "list_tables"):
        for name in page.get("TableNames", []):
            try:
                desc = without_response_metadata(client.describe_table(TableName=name))
            except BotoCoreError, ClientError:
                # Per-table failures are skipped silently here; the engine's
                # per-entry error path (ENTRY_SKIPPED) is too coarse for a
                # per-item miss. The run's RGTA sweep would still cover tags
                # for any table we missed, and other passes can fill the gap.
                continue
            table = desc.get("Table") or {}
            if table:
                yield table


def eventbridge_rules_with_targets(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate EventBridge rules (regional) with their target ARNs resolved.

    ``ListRules`` returns the rule itself — name, schedule, state, RoleArn —
    but not *what it invokes*. A rule's targets live behind a separate
    ``ListTargetsByRule`` call. This custom_fn fans that call out per rule
    and attaches the target ARNs so the rule → target relationship resolves
    as an edge; without it a scheduled rule and the Lambda it triggers sit
    on the grid as disconnected nodes.

    Two keys are attached:

    - ``_target_arns`` — every target ARN, lossless (→ ``configuration``).
    - ``_lambda_target_arns`` — the Lambda-only subset, which the ``INVOKES_LAMBDA``
      edge rule resolves against. EventBridge targets are polymorphic (SQS,
      SNS, Step Functions, ECS, …) and the v0 edge rule resolves a single
      ``target_type``; filtering to Lambda ARNs here keeps non-Lambda
      targets from producing dangling edges.

    Regional: the engine binds ``client_for`` to the current region. Rules
    are enumerated on the default event bus (parity with the prior
    ``ListRules`` source); custom event buses are future scope.

    A per-rule ``ListTargetsByRule`` failure is non-fatal: the rule still
    collects, without target edges. It is not an empty target list, though:
    ``_edge_reads`` records the ``INVOKES_LAMBDA`` read as ``failed`` (or
    ``partial`` when the listing stopped on a page that said more), so an
    authority claim made from it can never be ``complete``
    (req-aws-collector-edge-authority). ``RoleArn`` is the ``ListRules``
    item's own field.
    """
    client = client_for("events")
    for page in _pages(client, "list_rules"):
        for rule in page.get("Rules", []):
            name = rule.get("Name")
            bus = rule.get("EventBusName") or "default"
            targets = read_sub_listing(client, "list_targets_by_rule", "Targets", Rule=name, EventBusName=bus)
            target_arns = list(dict.fromkeys(t["Arn"] for t in targets.items if t.get("Arn")))
            lambda_arns = [a for a in target_arns if _LAMBDA_ARN_PREFIX_RE.match(a) and ":function:" in a]
            yield with_edge_reads(
                {**rule, "_target_arns": target_arns, "_lambda_target_arns": lambda_arns},
                {"RoleArn": COMPLETE, "_lambda_target_arns": targets.status},
            )


def _iam_client(session: Any, client_for: Any) -> Any:
    """The IAM client for a global listing: the engine's region-bound one, else ``_run_client``'s
    session-region-then-partition-home-region fallback (never a bare ``us-east-1`` literal, which
    is the wrong partition for a GovCloud credential)."""
    return _run_client(session, client_for, "iam")


def _account_summary_count(client: Any, key: str) -> int | None:
    """One count out of IAM ``GetAccountSummary``, the total AWS itself keeps for a relation.

    Read right after a listing ends and compared with the number of items the walk returned: a
    disagreement is a rejection control, so the recorder refuses to call the surface reconcilable
    (``req-grid-reconcile-evidence-3``), and it can only cost a missed retirement, never cause one. Any
    failure (the permission is separate from the list permission), or a response that lacks the key,
    is ``None``: no control, said as such.
    """
    try:
        summary = without_response_metadata(client.get_account_summary()).get("SummaryMap") or {}
    except BotoCoreError, ClientError:
        return None
    value = summary.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _hydrated_slot(envelope: dict[str, Any], key: str) -> Any:
    """The ``data`` of a hydrate slot that answered, else ``None`` (denied, absent and error are all
    'not observed' here; the slot's own status stays in ``_hydrate`` for the run's HYDRATE_GAP warning)."""
    slot = (envelope.get("_hydrate") or {}).get(key) or {}
    return slot.get("data") if slot.get("status") == "ok" else None


def _attached_policy_arns(data: Any) -> list[str] | None:
    """Sorted ARNs from a ``ListAttached*Policies`` answer; ``None`` when it did not answer or was cut short."""
    if not isinstance(data, dict) or page_says_more(data):
        return None
    return sorted(str(p["PolicyArn"]) for p in data.get("AttachedPolicies", []) if p.get("PolicyArn"))


def _attached_policies_read(envelope: dict[str, Any]) -> str:
    """How the ``attached_policies`` hydrate slot was read, for ``ATTACHES_POLICY`` (authority.py).

    ``failed`` when the call did not answer (denied, error, or the entity was gone by the time it was
    asked); ``partial`` when it answered with a page that says more; ``complete`` otherwise. Not the
    same as ``_attached_policy_arns`` being ``None``, which folds the first two together.
    """
    slot = (envelope.get("_hydrate") or {}).get("attached_policies") or {}
    if slot.get("status") != "ok":
        return FAILED
    return PARTIAL if page_says_more(slot.get("data")) else COMPLETE


def _federated_principals_read(document: Any) -> str:
    """How ``FEDERATES_INTO_ROLE``'s path (``AssumeRolePolicyDocument.Statement[].Principal.Federated``)
    can read the trust policy: ``complete`` only for a decoded document whose ``Statement`` is a list.

    A URL-encoded string, or a single-statement document written as an object, is a policy the path
    cannot walk: no edge comes out of it, and that must not read as "trusts no identity provider".
    """
    if isinstance(document, dict) and isinstance(document.get("Statement"), list):
        return COMPLETE
    return PARTIAL


def _boundary_arn(detail: Any) -> str | None:
    """'' when the entity was read and has no permissions boundary; ``None`` when it was not read."""
    if not isinstance(detail, dict):
        return None
    return str((detail.get("PermissionsBoundary") or {}).get("PermissionsBoundaryArn") or "")


def iam_roles_described(
    session: Any, *, client_for: Any = None, walk: ListingWalk | None = None
) -> Iterator[dict[str, Any]]:
    """Enumerate the account's IAM roles (global) and read what ``ListRoles`` leaves out.

    ``ListRoles`` is documented to omit ``PermissionsBoundary``, ``RoleLastUsed`` and ``Tags``, so each
    role is read again with ``GetRole`` and its attached managed policies listed
    (``ListAttachedRolePolicies``); the manifest's ``hydrate`` list names both. The trust policy is
    summarised (:mod:`.iam_trust`) into the cross-account assume-role targets the organization rollout
    is about. Every derived value is a ``_``-prefixed sibling the manifest's ``fields`` map projects;
    ``None`` means the read that would have produced it did not answer, never 'none'.

    The whole listing is read to its end and counted before the first per-role call, so the
    ``GetAccountSummary`` control is taken next to the listing rather than after a long fan-out, and so
    ``walk`` is decided by the listing alone. A role whose name is missing cannot be described: it clears
    ``walk.admitted``.
    """
    walk = walk if walk is not None else ListingWalk()
    client = _iam_client(session, client_for)
    roles = list(iter_listing(client, "list_roles", "Roles[]", walk))
    walk.count_reported = _account_summary_count(client, "Roles")
    hydrate_ops = _hydrate_ops("aws_core__aws_iam_role")
    for role in roles:
        name = role.get("RoleName")
        if not name:
            walk.drop("a listed role carries no RoleName")
            continue
        envelope = hydrate_item(client, role, hydrate_ops, call_kwargs={"RoleName": name})
        detail = (_hydrated_slot(envelope, "role") or {}).get("Role")
        last_used = ((detail or {}).get("RoleLastUsed") or {}).get("LastUsedDate")
        summary = summarize_trust_policy(
            role.get("AssumeRolePolicyDocument"), own_account=account_of_iam_arn(role.get("Arn"))
        )
        trust = summary or {}
        envelope["_permissions_boundary_arn"] = _boundary_arn(detail)
        envelope["_last_used_at"] = None if detail is None else (jsonable(last_used) if last_used else "")
        envelope["_attached_policy_arns"] = _attached_policy_arns(_hydrated_slot(envelope, "attached_policies"))
        envelope["_trusted_account_ids"] = trust.get("trusted_account_ids")
        envelope["_trusted_services"] = trust.get("trusted_services")
        envelope["_trusts_wildcard_principal"] = trust.get("trusts_wildcard_principal")
        # How each edge rule's source was read (authority.py): an unreadable trust policy or an
        # unanswered attached-policy listing is never "trusts nobody" / "has no policies".
        yield with_edge_reads(
            envelope,
            {
                "AssumeRolePolicyDocument": _federated_principals_read(role.get("AssumeRolePolicyDocument")),
                "_trusted_account_ids": COMPLETE if summary is not None else PARTIAL,
                "_attached_policy_arns": _attached_policies_read(envelope),
            },
        )


def iam_users_described(
    session: Any, *, client_for: Any = None, walk: ListingWalk | None = None
) -> Iterator[dict[str, Any]]:
    """Enumerate the account's IAM users (global); read boundary, attached policies and MFA per user.

    The same shape as :func:`iam_roles_described`: list to the end, take the ``GetAccountSummary``
    control, then fan out (``GetUser``, ``ListAttachedUserPolicies``, ``ListMFADevices``). ``mfa_enabled``
    is ``None`` when ``ListMFADevices`` did not answer: an unread device list is not 'no MFA'.
    """
    walk = walk if walk is not None else ListingWalk()
    client = _iam_client(session, client_for)
    users = list(iter_listing(client, "list_users", "Users[]", walk))
    walk.count_reported = _account_summary_count(client, "Users")
    hydrate_ops = _hydrate_ops("aws_core__aws_iam_user")
    for user in users:
        name = user.get("UserName")
        if not name:
            walk.drop("a listed user carries no UserName")
            continue
        envelope = hydrate_item(client, user, hydrate_ops, call_kwargs={"UserName": name})
        detail = (_hydrated_slot(envelope, "user") or {}).get("User")
        devices = _hydrated_slot(envelope, "mfa_devices")
        password_last_used = user.get("PasswordLastUsed")
        envelope["_permissions_boundary_arn"] = _boundary_arn(detail)
        envelope["_password_last_used"] = jsonable(password_last_used) if password_last_used else ""
        envelope["_attached_policy_arns"] = _attached_policy_arns(_hydrated_slot(envelope, "attached_policies"))
        envelope["_mfa_enabled"] = bool(devices.get("MFADevices")) if isinstance(devices, dict) else None
        yield with_edge_reads(envelope, {"_attached_policy_arns": _attached_policies_read(envelope)})


def iam_customer_policies_listed(
    session: Any, *, client_for: Any = None, walk: ListingWalk | None = None
) -> Iterator[dict[str, Any]]:
    """Enumerate the account's customer-managed IAM policies (``ListPolicies(Scope=Local)``).

    ``Scope=Local`` is the account's own policies: AWS-managed ones belong to AWS, are the same in every
    account, and are not this account's to own or to lose. ``ListPolicies`` already returns everything the
    model carries (id, default version, attachment count), so there is no fan-out.
    """
    walk = walk if walk is not None else ListingWalk()
    client = _iam_client(session, client_for)
    policies = list(iter_listing(client, "list_policies", "Policies[]", walk, Scope="Local"))
    walk.count_reported = _account_summary_count(client, "Policies")
    yield from policies


def iam_oidc_providers_described(
    session: Any, *, client_for: Any = None, walk: ListingWalk | None = None
) -> Iterator[dict[str, Any]]:
    """Enumerate IAM OIDC identity providers (global) and describe each.

    ``ListOpenIDConnectProviders`` returns ARNs only; ``GetOpenIDConnectProvider``
    is the per-ARN fan-out for URL, client IDs, thumbprints, and inline tags.
    Each yielded item embeds the source ARN as ``ProviderArn`` so the manifest
    entry can use it as ``natural_key`` (the GetOpenIDConnectProvider response
    doesn't echo the ARN back).

    IAM is global; the client is the run's, bound through the partition's global
    IAM endpoint (``iam.us-gov.amazonaws.com`` in GovCloud). The list call is not
    paginated (AWS returns every provider of the account in one response), so
    ``walk`` ends with that one call unless the response itself reports a continuation. A provider that
    is listed but cannot be described is dropped from the batch, and that clears ``walk.admitted``:
    the listing was complete, but the run did not process all of it, so an absence from the batch is not
    evidence of deletion.
    """
    walk = walk if walk is not None else ListingWalk()
    client = _iam_client(session, client_for)
    listing = without_response_metadata(client.list_open_id_connect_providers())
    entries = listing.get("OpenIDConnectProviderList", [])
    if page_says_more(listing):
        walk.stopped_short(len(entries), "the response reports a continuation")
    else:
        walk.reached_end(len(entries))
    for entry in entries:
        arn = entry.get("Arn")
        if not arn:
            walk.drop("a listed provider carries no Arn")
            continue
        try:
            details = without_response_metadata(client.get_open_id_connect_provider(OpenIDConnectProviderArn=arn))
        except BotoCoreError, ClientError:
            walk.drop(f"{arn} was listed but GetOpenIDConnectProvider did not answer")
            continue
        yield {**details, "ProviderArn": arn}


# An API Gateway v2 Lambda-proxy IntegrationUri embeds the function's invoke
# path: .../functions/<function-arn>/invocations. Capture the embedded ARN.
_LAMBDA_INTEGRATION_URI_RE = re.compile(rf"/functions/(arn:{PARTITION_RE}:lambda:[^/]+)/invocations$")
_LAMBDA_ARN_PREFIX_RE = re.compile(rf"^arn:{PARTITION_RE}:lambda:")

# A Cognito JWT authorizer's Issuer names the pool:
# https://cognito-idp.<region>.amazonaws.com/<pool-id>  (.amazonaws.com.cn in the China partition)
_COGNITO_ISSUER_RE = re.compile(
    r"^https://cognito-idp\.[a-z0-9-]+\.amazonaws\.com(?:\.cn)?/(?P<pool>[a-z0-9-]+_[A-Za-z0-9]+)$",
    re.IGNORECASE,
)


def _client_region(client: Any) -> str:
    """The region a client is bound to, tolerating non-boto3 stand-ins.

    Real boto3 clients carry ``meta.region_name``; test doubles often don't.
    An unknown region degrades to ``""`` (a synthesized ARN then simply has an
    empty region segment) rather than failing enumeration.
    """
    region = getattr(getattr(client, "meta", None), "region_name", None)
    return region if isinstance(region, str) else ""


def _lambda_arn_from_integration_uri(uri: str) -> str | None:
    """Extract the unqualified Lambda ARN from a v2 Lambda-proxy IntegrationUri.

    The embedded ARN may carry an alias/version qualifier
    (``...:function:name:live``); the Lambda node's natural key is the
    *unqualified* ``FunctionArn``, so a trailing qualifier is stripped.
    """
    match = _LAMBDA_INTEGRATION_URI_RE.search(uri or "")
    if not match:
        return None
    arn = match.group(1)
    parts = arn.split(":")
    if len(parts) == 8:  # arn:aws:lambda:region:acct:function:name:qualifier
        arn = ":".join(parts[:7])
    return arn


def apigateway_http_apis_detailed(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate API Gateway v2 HTTP APIs (regional) with sub-resources resolved.

    ``GetApis`` returns the API shell; what it *fronts* lives behind four
    per-API listings — stages, routes, integrations, authorizers. This
    custom_fn fans those out and attaches them lossless (``_stages`` /
    ``_routes`` / ``_integrations`` / ``_authorizers`` → the configuration
    envelope, not persisted: the manifest entry's ``persist_configuration`` is
    false),
    then derives the two edge-resolvable keys:

    - ``_integration_lambda_arns`` — unqualified Lambda ARNs parsed from
      Lambda-proxy IntegrationUris (the ``INVOKES_LAMBDA`` edge).
    - ``_authorizer_user_pool_ids`` — Cognito pool ids parsed from JWT
      authorizer issuers (the ``AUTHENTICATES_VIA_USER_POOL`` edge).

    and one typed-field key:

    - ``_route_authorization_types`` — ``{RouteKey: AuthorizationType}`` from
      ``GetRoutes`` (``NONE``, ``AWS_IAM``, ``JWT``, or ``CUSTOM`` for a Lambda
      authorizer; a route that omits it is ``NONE``, the AWS default). ``None``
      when ``GetRoutes`` failed, so a denied listing never reads as "no open
      routes".

    ``GetApis`` carries no ARN; ``_api_arn`` is synthesized in the documented
    ``arn:aws:apigateway:<region>::/apis/<id>`` form as the natural key.
    """
    client = client_for("apigatewayv2")
    region = _client_region(client)
    for page in _pages(client, "get_apis"):
        for api in page.get("Items", []):
            api_id = api.get("ApiId")
            if not api_id:
                continue
            sub: dict[str, list[dict[str, Any]]] = {}
            reads: dict[str, str] = {}
            for key, method in (
                ("_stages", "get_stages"),
                ("_routes", "get_routes"),
                ("_integrations", "get_integrations"),
                ("_authorizers", "get_authorizers"),
            ):
                # A per-API sub-listing failure is non-fatal: the API still collects, without that
                # facet. Its read status (failed, or partial when it stopped on a page saying more)
                # travels with the edges derived from it (authority.py).
                listing = read_sub_listing(client, method, "Items", ApiId=api_id)
                sub[key] = listing.items
                reads[key] = listing.status
            lambda_arns: list[str] = []
            # A Lambda-proxy integration (AWS_PROXY with no service subtype) whose URI does not parse
            # to a function ARN is a Lambda the API invokes that the edge cannot name: partial.
            unparsed_lambda = False
            for integ in sub["_integrations"]:
                arn = _lambda_arn_from_integration_uri(integ.get("IntegrationUri") or "")
                if arn:
                    lambda_arns.append(arn)
                elif integ.get("IntegrationType") == "AWS_PROXY" and not integ.get("IntegrationSubtype"):
                    unparsed_lambda = True
            pool_ids = []
            # A Cognito issuer the pattern cannot read names a user pool the edge cannot key: partial.
            unparsed_pool = False
            for auth in sub["_authorizers"]:
                issuer = ((auth.get("JwtConfiguration") or {}).get("Issuer") or "").strip()
                match = _COGNITO_ISSUER_RE.match(issuer)
                if match:
                    pool_ids.append(match.group("pool"))
                elif "cognito-idp." in issuer.lower():
                    unparsed_pool = True
            integrations_read = reads["_integrations"]
            if integrations_read == COMPLETE and unparsed_lambda:
                integrations_read = PARTIAL
            authorizers_read = reads["_authorizers"]
            if authorizers_read == COMPLETE and unparsed_pool:
                authorizers_read = PARTIAL
            yield with_edge_reads(
                {
                    **api,
                    **sub,
                    "_api_arn": build_arn(partition_of_region(region), "apigateway", region, "", f"/apis/{api_id}"),
                    "_integration_lambda_arns": list(dict.fromkeys(lambda_arns)),
                    "_authorizer_user_pool_ids": list(dict.fromkeys(pool_ids)),
                    # A routes listing that did not finish is not the whole map: None, never "no open routes".
                    "_route_authorization_types": None
                    if reads["_routes"] != COMPLETE
                    else {
                        route["RouteKey"]: route.get("AuthorizationType") or "NONE"
                        for route in sub["_routes"]
                        if route.get("RouteKey")
                    },
                },
                {
                    "_integration_lambda_arns": integrations_read,
                    "_authorizer_user_pool_ids": authorizers_read,
                },
            )


def cognito_user_pools_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Cognito user pools (regional) and describe each.

    ``ListUserPools`` returns id/name summaries; ``DescribeUserPool`` is the
    per-pool fan-out for the ARN, MFA posture, hosted domain, and inline
    ``UserPoolTags``. Yields the ``UserPool`` sub-object so ``Id`` — the pool
    id JWT issuers embed — sits at the root as the natural key (which is what
    lets an API Gateway authorizer edge resolve by identity).
    """
    client = client_for("cognito-idp")
    for page in _pages(client, "list_user_pools", MaxResults=60):
        for summary in page.get("UserPools", []):
            pool_id = summary.get("Id")
            if not pool_id:
                continue
            try:
                desc = without_response_metadata(client.describe_user_pool(UserPoolId=pool_id))
            except BotoCoreError, ClientError:
                continue
            pool = desc.get("UserPool") or {}
            if pool:
                yield pool


def kms_keys_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate KMS keys (regional) with aliases and tags resolved.

    ``ListKeys`` returns id+ARN only; ``DescribeKey`` supplies state, manager
    (AWS vs CUSTOMER), spec, and description. ``ListAliases`` is fetched once
    and joined by TargetKeyId (``_aliases``); ``ListResourceTags`` fans out
    per key (``_tags``, normalized TagKey/TagValue -> mapping). AWS-managed
    keys commonly deny Describe/ListResourceTags under a read-only principal —
    each fan-out degrades independently so the key still collects from the
    listing shell.

    ``_display_name`` is the first alias (sans ``alias/``) or the key id —
    KMS keys have no name of their own.
    """
    client = client_for("kms")
    aliases_by_key: dict[str, list[str]] = {}
    for page in _pages(client, "list_aliases"):
        for alias in page.get("Aliases", []):
            target = alias.get("TargetKeyId")
            alias_name = alias.get("AliasName")
            if target and alias_name:
                aliases_by_key.setdefault(target, []).append(alias_name)
    for page in _pages(client, "list_keys"):
        for key in page.get("Keys", []):
            key_id = key.get("KeyId")
            if not key_id:
                continue
            try:
                described = without_response_metadata(client.describe_key(KeyId=key_id))
                meta = described.get("KeyMetadata") or {}
            except BotoCoreError, ClientError:
                meta = {"KeyId": key_id, "Arn": key.get("KeyArn")}
            tags: dict[str, str] = {}
            try:
                for tpage in _pages(client, "list_resource_tags", KeyId=key_id):
                    for tag in tpage.get("Tags", []):
                        tag_key = tag.get("TagKey")
                        if tag_key is not None:
                            tags[tag_key] = tag.get("TagValue") or ""
            except BotoCoreError, ClientError:
                tags = {}
            alias_names = aliases_by_key.get(key_id, [])
            display = alias_names[0].removeprefix("alias/") if alias_names else key_id
            yield {**meta, "_aliases": alias_names, "_tags": tags, "_display_name": display}


def sqs_queues_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate SQS queues (regional) with attributes and tags resolved.

    ``ListQueues`` returns URL strings only; ``GetQueueAttributes(All)`` is
    the per-queue fan-out for the ARN, retention, visibility, and encryption
    posture, and ``ListQueueTags`` for tags. The queue name is derived from
    the ARN's last segment (``_queue_name``).
    """
    client = client_for("sqs")
    for page in _pages(client, "list_queues"):
        for url in page.get("QueueUrls", []) or []:
            try:
                attrs = (
                    without_response_metadata(client.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])).get(
                        "Attributes"
                    )
                    or {}
                )
            except BotoCoreError, ClientError:
                continue
            if not attrs.get("QueueArn"):
                continue
            tags: dict[str, str] = {}
            try:
                tags = without_response_metadata(client.list_queue_tags(QueueUrl=url)).get("Tags") or {}
            except BotoCoreError, ClientError:
                tags = {}
            # KmsMasterKeyId is GetQueueAttributes(All)'s own answer; a queue whose attributes did
            # not answer is not yielded at all, so no claim is made for it (authority.py).
            yield with_edge_reads(
                {
                    **attrs,
                    "QueueUrl": url,
                    "_queue_name": attrs["QueueArn"].rsplit(":", 1)[-1],
                    "_tags": tags,
                },
                {"KmsMasterKeyId": COMPLETE},
            )


def cloudtrail_trails_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CloudTrail trails (regional, home-region only) with status + tags.

    ``DescribeTrails(includeShadowTrails=False)`` returns the region's own
    trails; a multi-region trail is additionally filtered to its
    ``HomeRegion`` so one trail yields one node per run, never a
    duplicate-id per region (GRIFT rejects duplicate entity ids in a batch).
    ``GetTrailStatus`` supplies ``_is_logging``; ``ListTags`` normalizes the
    Key/Value TagsList into ``_tags``.
    """
    client = client_for("cloudtrail")
    region = _client_region(client)
    listing = without_response_metadata(client.describe_trails(includeShadowTrails=False))
    for trail in listing.get("trailList", []):
        arn = trail.get("TrailARN")
        if not arn:
            continue
        home = trail.get("HomeRegion")
        if home and home != region:
            continue
        status: dict[str, Any] = {}
        try:
            status = without_response_metadata(client.get_trail_status(Name=arn))
        except BotoCoreError, ClientError:
            status = {}
        tags: dict[str, str] = {}
        try:
            for tpage in _pages(client, "list_tags", ResourceIdList=[arn]):
                for tag_set in tpage.get("ResourceTagList", []):
                    for tag in tag_set.get("TagsList", []) or []:
                        tag_key = tag.get("Key")
                        if tag_key is not None:
                            tags[tag_key] = tag.get("Value") or ""
        except BotoCoreError, ClientError:
            tags = {}
        # The three edge rules read DescribeTrails' own record of the trail (authority.py).
        yield with_edge_reads(
            {
                **trail,
                "_status": status,
                "_is_logging": bool(status.get("IsLogging")),
                "_tags": tags,
            },
            {"S3BucketName": COMPLETE, "CloudWatchLogsLogGroupArn": COMPLETE, "KmsKeyId": COMPLETE},
        )


# Manifest custom_fn name -> callable.
_CUSTOM_FNS = {
    "aws_account_singleton": aws_account_singleton,
    "s3_buckets_hydrated": s3_buckets_hydrated,
    "route53_zones_with_alias_targets": route53_zones_with_alias_targets,
    "cloudfront_distributions_with_oac": cloudfront_distributions_with_oac,
    "dynamodb_tables_described": dynamodb_tables_described,
    "eventbridge_rules_with_targets": eventbridge_rules_with_targets,
    "iam_oidc_providers_described": iam_oidc_providers_described,
    "apigateway_http_apis_detailed": apigateway_http_apis_detailed,
    "cognito_user_pools_described": cognito_user_pools_described,
    "iam_roles_described": iam_roles_described,
    "iam_users_described": iam_users_described,
    "iam_customer_policies_listed": iam_customer_policies_listed,
    "kms_keys_described": kms_keys_described,
    "sqs_queues_described": sqs_queues_described,
    "cloudtrail_trails_described": cloudtrail_trails_described,
}


def build_custom_fn_registry() -> CustomFnRegistry:
    """The populated ``custom_fn`` registry for the collector.

    Every ``custom_fn`` named by the manifest is registered here — the
    registry is the single source. An unregistered ``custom_fn`` still
    classifies-and-skips rather than crashing the run.
    """
    registry = CustomFnRegistry()
    for name, fn in _CUSTOM_FNS.items():
        registry.register(name, fn)
    return registry
