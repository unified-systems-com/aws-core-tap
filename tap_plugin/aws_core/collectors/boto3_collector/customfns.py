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
from urllib.parse import urlsplit, urlunsplit

from botocore.exceptions import BotoCoreError, ClientError

from .authority import COMPLETE, FAILED, PARTIAL, with_edge_reads
from .ecs import shared_walk
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
from .source import CustomFnRegistry, SourceError, iter_listing


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
    names its target by natural key with no transform (the make-it-work
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
            # fan-out emits the same relationship twice, which GRIFT
            # rejects the whole batch over. One CF distribution -> one edge.
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
    manifest entry's ``natural_key`` — and the account node is found by it:
    an ``aws_account`` row with that ``account_id`` already on the grid (a
    hand-written GRIFT batch, say) is the collector's row, not a second one.

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


def iam_groups_listed(
    session: Any, *, client_for: Any = None, walk: ListingWalk | None = None
) -> Iterator[dict[str, Any]]:
    """Enumerate the account's IAM groups (global) and list the managed policies attached to each.

    The same shape as :func:`iam_users_described`: list to the end, take the ``GetAccountSummary``
    control, then fan out (``ListAttachedGroupPolicies``). A group's members are users and are read
    from the user side, not here. IAM has no group tag operation, so there is no tag read.
    """
    walk = walk if walk is not None else ListingWalk()
    client = _iam_client(session, client_for)
    groups = list(iter_listing(client, "list_groups", "Groups[]", walk))
    walk.count_reported = _account_summary_count(client, "Groups")
    hydrate_ops = _hydrate_ops("aws_core__aws_iam_group")
    for group in groups:
        name = group.get("GroupName")
        if not name:
            walk.drop("a listed group carries no GroupName")
            continue
        envelope = hydrate_item(client, group, hydrate_ops, call_kwargs={"GroupName": name})
        envelope["_attached_policy_arns"] = _attached_policy_arns(_hydrated_slot(envelope, "attached_policies"))
        yield with_edge_reads(envelope, {"_attached_policy_arns": _attached_policies_read(envelope)})


def iam_instance_profiles_listed(
    session: Any, *, client_for: Any = None, walk: ListingWalk | None = None
) -> Iterator[dict[str, Any]]:
    """Enumerate the account's IAM instance profiles (global), each with the roles it holds.

    ``ListInstanceProfiles`` embeds every role of a profile, so there is no fan-out for them. The embedded
    role is cut to its name and ARN: the rest of it (the trust policy above all) is the role's own node's
    to carry, not this profile's. ``_role_arns`` is the profile's own answer, and is ``None`` only when the
    response carries no ``Roles`` list at all.
    """
    walk = walk if walk is not None else ListingWalk()
    client = _iam_client(session, client_for)
    profiles = list(iter_listing(client, "list_instance_profiles", "InstanceProfiles[]", walk))
    walk.count_reported = _account_summary_count(client, "InstanceProfiles")
    for profile in profiles:
        if not profile.get("InstanceProfileName"):
            walk.drop("a listed instance profile carries no InstanceProfileName")
            continue
        roles = profile.get("Roles")
        known = isinstance(roles, list)
        slim = [{"RoleName": r.get("RoleName"), "Arn": r.get("Arn")} for r in roles or []]
        yield with_edge_reads(
            {
                **profile,
                "Roles": slim,
                "_role_arns": sorted(str(r["Arn"]) for r in slim if r["Arn"]) if known else None,
            },
            {"_role_arns": COMPLETE if known else PARTIAL},
        )


def iam_saml_providers_described(
    session: Any, *, client_for: Any = None, walk: ListingWalk | None = None
) -> Iterator[dict[str, Any]]:
    """Enumerate IAM SAML identity providers (global) and describe each.

    The same shape as :func:`iam_oidc_providers_described`: ``ListSAMLProviders`` is one unpaginated
    call, and ``GetSAMLProvider`` supplies the dates and the inline tags. The metadata document the
    response carries is the identity provider's own configuration, large and not a field of the node, so
    it is dropped here rather than stored. A provider that is listed but cannot be described is dropped
    from the batch, and that clears ``walk.admitted``.
    """
    walk = walk if walk is not None else ListingWalk()
    client = _iam_client(session, client_for)
    listing = without_response_metadata(client.list_saml_providers())
    entries = listing.get("SAMLProviderList", [])
    if page_says_more(listing):
        walk.stopped_short(len(entries), "the response reports a continuation")
    else:
        walk.reached_end(len(entries))
    for entry in entries:
        arn = entry.get("Arn")
        if not arn:
            walk.drop("a listed SAML provider carries no Arn")
            continue
        try:
            details = without_response_metadata(client.get_saml_provider(SAMLProviderArn=arn))
        except BotoCoreError, ClientError:
            walk.drop(f"{arn} was listed but GetSAMLProvider did not answer")
            continue
        details.pop("SAMLMetadataDocument", None)
        valid_until = details.get("ValidUntil")
        created = details.get("CreateDate")
        yield {
            **details,
            "ProviderArn": arn,
            "_name": arn.rsplit("/", 1)[-1],
            "_valid_until": jsonable(valid_until) if valid_until else "",
            "_created_at": jsonable(created) if created else "",
        }


def iam_server_certificates_listed(
    session: Any, *, client_for: Any = None, walk: ListingWalk | None = None
) -> Iterator[dict[str, Any]]:
    """Enumerate the account's IAM server certificates (global), metadata only.

    ``ListServerCertificates`` returns the name, path, id, ARN and the upload and expiry dates. The
    certificate body and chain come from ``GetServerCertificate``, which is never called.
    """
    walk = walk if walk is not None else ListingWalk()
    client = _iam_client(session, client_for)
    certificates = list(iter_listing(client, "list_server_certificates", "ServerCertificateMetadataList[]", walk))
    walk.count_reported = _account_summary_count(client, "ServerCertificates")
    for certificate in certificates:
        if not certificate.get("ServerCertificateName"):
            walk.drop("a listed server certificate carries no ServerCertificateName")
            continue
        expiration = certificate.get("Expiration")
        uploaded = certificate.get("UploadDate")
        yield {
            **certificate,
            "_expiration": jsonable(expiration) if expiration else "",
            "_upload_date": jsonable(uploaded) if uploaded else "",
        }


def iam_virtual_mfa_devices_listed(
    session: Any, *, client_for: Any = None, walk: ListingWalk | None = None
) -> Iterator[dict[str, Any]]:
    """Enumerate the account's virtual MFA devices (global), assigned or not.

    The seed and the QR code that enrol a device are the device's credentials: AWS returns them only when
    the device is created, and this reader removes them from every item whether or not a response carries
    them. ``_user_arn`` is ``""`` for a device nobody has enabled. Hardware tokens are not virtual devices
    and are not listed by this call, so ``GetAccountSummary``'s ``MFADevices`` is not a control for this
    listing and none is taken.
    """
    walk = walk if walk is not None else ListingWalk()
    client = _iam_client(session, client_for)
    for device in iter_listing(client, "list_virtual_mfa_devices", "VirtualMFADevices[]", walk):
        serial = device.get("SerialNumber")
        if not serial:
            walk.drop("a listed virtual MFA device carries no SerialNumber")
            continue
        safe = {k: v for k, v in device.items() if k not in ("Base32StringSeed", "QRCodePNG")}
        enabled = device.get("EnableDate")
        yield with_edge_reads(
            {
                **safe,
                "_name": str(serial).rsplit("/", 1)[-1],
                "_user_arn": str((device.get("User") or {}).get("Arn") or ""),
                "_enable_date": jsonable(enabled) if enabled else "",
            },
            {"_user_arn": COMPLETE},
        )


# DescribeTags on the load balancer APIs and on Direct Connect takes at most this many ids per call.
_TAG_BATCH = 20


def _batched_tags(
    client: Any,
    id_param: str,
    id_key: str,
    ids: list[str],
    *,
    method: str = "describe_tags",
    list_key: str = "TagDescriptions",
    tags_key: str = "Tags",
    tag_key: str = "Key",
    tag_value: str = "Value",
) -> dict[str, dict[str, str]]:
    """Tags per resource, read 20 ids to a ``describe_tags`` call.

    ``id_param``/``id_key`` are the request parameter and the response key that carry the id
    (``ResourceArns``/``ResourceArn`` for ELBv2, ``LoadBalancerNames``/``LoadBalancerName`` for Classic,
    ``resourceArns``/``resourceArn`` for Direct Connect, ``ResourceIdList``/``ResourceId`` for CloudTrail with
    ``method="list_tags"``), ``list_key`` the response list, ``tags_key`` the
    list of tags inside each entry, and ``tag_key``/``tag_value`` the spelling of the tag struct. An id is in the result only when an answer named
    it: absent is 'not read', and ``{}`` is 'read, untagged'. A batch that failed, and an id a successful
    answer left out (a resource deleted mid-run), are both 'not read', so neither clears the stored tags.
    """
    tags: dict[str, dict[str, str]] = {}
    for start in range(0, len(ids), _TAG_BATCH):
        batch = ids[start : start + _TAG_BATCH]
        try:
            answer = without_response_metadata(getattr(client, method)(**{id_param: batch}))
        except BotoCoreError, ClientError:
            continue
        for description in answer.get(list_key, []):
            ident = description.get(id_key)
            if ident in batch:
                tags[ident] = {
                    t[tag_key]: t.get(tag_value) or "" for t in description.get(tags_key, []) if tag_key in t
                }
    return tags


def _lb_item(lb: dict[str, Any], tags: dict[str, dict[str, str]], tag_id: str, subnet_ids: list[str]) -> dict[str, Any]:
    """A load balancer as the manifest projects it: the listing, plus the derived ``_`` siblings."""
    return with_edge_reads(
        {
            **lb,
            "_state": (lb.get("State") or {}).get("Code"),
            "_subnet_ids": subnet_ids,
            "_tags": tags.get(tag_id, {}),
            "_tags_unread": tag_id not in tags,
        },
        {"_subnet_ids": COMPLETE},
    )


def _elbv2_load_balancers(client: Any) -> list[dict[str, Any]]:
    return [lb for page in _pages(client, "describe_load_balancers") for lb in page.get("LoadBalancers", [])]


def _az_subnet_ids(lb: dict[str, Any]) -> list[str]:
    return sorted({str(az["SubnetId"]) for az in lb.get("AvailabilityZones", []) if az.get("SubnetId")})


def elbv2_albs_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Application Load Balancers (regional) with their tags.

    ``DescribeLoadBalancers`` returns Application, Network and Gateway load balancers together; the
    application ones are these, the others are :func:`elb_family_described`'s. Tags come from
    ``DescribeTags``, 20 ARNs to a call, so a denial costs the tags of a batch and not the load balancers.
    """
    client = client_for("elbv2")
    albs = [lb for lb in _elbv2_load_balancers(client) if lb.get("Type") == "application"]
    tags = _batched_tags(client, "ResourceArns", "ResourceArn", [str(lb["LoadBalancerArn"]) for lb in albs])
    for lb in albs:
        yield _lb_item(lb, tags, str(lb["LoadBalancerArn"]), _az_subnet_ids(lb))


def elb_family_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Network, Gateway and Classic Load Balancers (regional) with their tags.

    The network and gateway ones come from the ELBv2 listing (the application ones are
    :func:`elbv2_albs_described`'s) and are keyed by their DNS name, as the Classic ones are, which have no
    ARN. ``_lb_type`` tells them apart. A Classic load balancer's tags are read by name from the ELB API.
    """
    v2 = client_for("elbv2")
    others = [lb for lb in _elbv2_load_balancers(v2) if lb.get("Type") in ("network", "gateway")]
    v2_tags = _batched_tags(v2, "ResourceArns", "ResourceArn", [str(lb["LoadBalancerArn"]) for lb in others])
    for lb in others:
        item = _lb_item(lb, v2_tags, str(lb["LoadBalancerArn"]), _az_subnet_ids(lb))
        yield {**item, "_lb_type": lb["Type"]}
    classic = client_for("elb")
    described = [
        lb for page in _pages(classic, "describe_load_balancers") for lb in page.get("LoadBalancerDescriptions", [])
    ]
    classic_tags = _batched_tags(
        classic, "LoadBalancerNames", "LoadBalancerName", [str(lb["LoadBalancerName"]) for lb in described]
    )
    for lb in described:
        item = _lb_item(lb, classic_tags, str(lb["LoadBalancerName"]), sorted(str(i) for i in lb.get("Subnets", [])))
        yield {**item, "_lb_type": "classic"}


def elbv2_target_groups_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate ELBv2 target groups (regional) with their tags (``DescribeTags``, 20 ARNs to a call)."""
    client = client_for("elbv2")
    groups = [tg for page in _pages(client, "describe_target_groups") for tg in page.get("TargetGroups", [])]
    tags = _batched_tags(client, "ResourceArns", "ResourceArn", [str(tg["TargetGroupArn"]) for tg in groups])
    for group in groups:
        arn = str(group["TargetGroupArn"])
        yield {**group, "_tags": tags.get(arn, {}), "_tags_unread": arn not in tags}


def dx_gateways_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Direct Connect gateways (global) with their tags.

    ``DescribeDirectConnectGateways`` returns no ARN and the tag API is keyed by ARN, so the ARN is built
    from the partition, the owning account and the gateway id (``arn:<partition>:directconnect::<account>:
    dx-gateway/<id>``, as CloudFormation's ``DirectConnectGatewayArn`` is). Tags are read 20 ARNs to a call;
    a batch that fails leaves its gateways' tags unread. A gateway with no owner account or id has no ARN and
    is left out of the batch, and the reader raises once it has yielded the rest.
    """
    client = client_for("directconnect")
    partition = _client_partition(client)
    gateways = [
        g for page in _pages(client, "describe_direct_connect_gateways") for g in page.get("directConnectGateways", [])
    ]
    arns: dict[str, str] = {}
    failed: list[str] = []
    for gateway in gateways:
        gateway_id, owner = gateway.get("directConnectGatewayId"), gateway.get("ownerAccount")
        if gateway_id and owner:
            arns[gateway_id] = build_arn(partition, "directconnect", "", owner, f"dx-gateway/{gateway_id}")
        else:
            failed.append(str(gateway_id or gateway.get("directConnectGatewayName") or "<unnamed>"))
    tags = _batched_tags(
        client,
        "resourceArns",
        "resourceArn",
        list(arns.values()),
        list_key="resourceTags",
        tags_key="tags",
        tag_key="key",
        tag_value="value",
    )
    for gateway in gateways:
        arn = arns.get(str(gateway.get("directConnectGatewayId")))
        if arn:
            yield {**gateway, "_arn": arn, "_tags": tags.get(arn, {}), "_tags_unread": arn not in tags}
    if failed:
        raise _undescribed("Direct Connect gateways without an owner account", failed)


def transit_gateways_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate transit gateways (regional). EC2 reports an option as ``enable``/``disable``; the model holds
    a boolean, ``None`` when the option is absent from the answer (the three ``_`` flags below)."""
    client = client_for("ec2")

    def flag(options: dict[str, Any], key: str) -> bool | None:
        value = options.get(key)
        return None if value is None else value == "enable"

    for page in _pages(client, "describe_transit_gateways"):
        for gateway in page.get("TransitGateways", []):
            options = gateway.get("Options") or {}
            yield {
                **gateway,
                "_auto_accept_shared_attachments": flag(options, "AutoAcceptSharedAttachments"),
                "_default_route_table_association": flag(options, "DefaultRouteTableAssociation"),
                "_default_route_table_propagation": flag(options, "DefaultRouteTablePropagation"),
            }


def transit_gateway_attachments_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate transit gateway attachments (regional).

    An attachment's ``ResourceId`` names a different kind of thing by ``ResourceType``: a VPC, a Direct
    Connect gateway or the peer transit gateway of a peering attachment. The three ``_`` ids carry it for the
    type it is and ``None`` otherwise, so each edge is written from the one id that is true. They come from the
    same record as the type, so the edge read is ``complete``.
    """
    client = client_for("ec2")
    for page in _pages(client, "describe_transit_gateway_attachments"):
        for attachment in page.get("TransitGatewayAttachments", []):
            kind, target = attachment.get("ResourceType"), attachment.get("ResourceId")
            yield with_edge_reads(
                {
                    **attachment,
                    "_vpc_id": target if kind == "vpc" else None,
                    "_dx_gateway_id": target if kind == "direct-connect-gateway" else None,
                    "_peer_transit_gateway_id": target if kind == "peering" else None,
                },
                {
                    "TransitGatewayId": COMPLETE,
                    "_vpc_id": COMPLETE,
                    "_dx_gateway_id": COMPLETE,
                    "_peer_transit_gateway_id": COMPLETE,
                },
            )


_CODEBUILD_BATCH = 100


def codebuild_projects_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CodeBuild projects (regional): ``ListProjects`` names them and ``BatchGetProjects``
    (100 names to a call) describes them, tags included.

    ``_vpc_attached`` is whether the project runs inside a VPC (``vpcConfig.vpcId`` is set). A name that
    ``BatchGetProjects`` does not return, or a batch that fails, is a gap: the reader yields what it did
    describe and then raises (:func:`_undescribed`).
    """
    client = client_for("codebuild")
    names = [n for page in _pages(client, "list_projects") for n in page.get("projects", [])]
    failed: list[str] = []
    for start in range(0, len(names), _CODEBUILD_BATCH):
        batch = names[start : start + _CODEBUILD_BATCH]
        try:
            answer = without_response_metadata(client.batch_get_projects(names=batch))
        except BotoCoreError, ClientError:
            failed.extend(batch)
            continue
        got = {p.get("name"): p for p in answer.get("projects", []) if p.get("arn")}
        failed.extend(n for n in batch if n not in got)
        for project in got.values():
            yield {**project, "_vpc_attached": bool((project.get("vpcConfig") or {}).get("vpcId"))}
    if failed:
        raise _undescribed("CodeBuild projects", failed)


def codepipeline_pipelines_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CodePipeline pipelines (regional): ``ListPipelines`` names them, ``GetPipeline`` describes
    each, and ``ListTagsForResource`` reads its tags by ARN.

    Derived siblings: ``_arn`` (``metadata.pipelineArn``), ``_stage_names`` in order, ``_codebuild_project_arns``
    (the CodeBuild projects its build and test actions run, named by project name and built into an ARN with
    the pipeline's own partition, region and account) and ``_s3_source_bucket_arns`` (its S3 source actions'
    buckets). All come from the one ``GetPipeline`` answer, so the edge reads are ``complete``. A failed tag
    read leaves the tags unread; a pipeline that cannot be described is a gap (:func:`_undescribed`).
    """
    client = client_for("codepipeline")
    names = [p["name"] for page in _pages(client, "list_pipelines") for p in page.get("pipelines", []) if p.get("name")]
    failed: list[str] = []
    for name in names:
        try:
            answer = without_response_metadata(client.get_pipeline(name=name))
        except BotoCoreError, ClientError:
            failed.append(name)
            continue
        pipeline = answer.get("pipeline") or {}
        arn = (answer.get("metadata") or {}).get("pipelineArn")
        if not arn:
            failed.append(name)
            continue
        partition, _, region, account = (arn.split(":") + [""] * 5)[1:5]
        actions = [a for stage in pipeline.get("stages", []) for a in stage.get("actions", [])]
        builds = sorted(
            {
                build_arn(partition, "codebuild", region, account, f"project/{a['configuration']['ProjectName']}")
                for a in actions
                if (a.get("actionTypeId") or {}).get("provider") == "CodeBuild"
                and (a.get("configuration") or {}).get("ProjectName")
            }
        )
        buckets = sorted(
            {
                build_arn(partition, "s3", "", "", a["configuration"]["S3Bucket"])
                for a in actions
                if (a.get("actionTypeId") or {}).get("category") == "Source"
                and (a.get("actionTypeId") or {}).get("provider") == "S3"
                and (a.get("configuration") or {}).get("S3Bucket")
            }
        )
        tags: dict[str, str] = {}
        tags_unread = False
        try:
            for page in _pages(client, "list_tags_for_resource", resourceArn=arn):
                tags.update({t["key"]: t.get("value") or "" for t in page.get("tags", []) if "key" in t})
        except BotoCoreError, ClientError:
            tags, tags_unread = {}, True
        yield with_edge_reads(
            {
                **pipeline,
                "_arn": arn,
                "_stage_names": [s.get("name") for s in pipeline.get("stages", []) if s.get("name")],
                "_codebuild_project_arns": builds,
                "_s3_source_bucket_arns": buckets,
                "_tags": tags,
                "_tags_unread": tags_unread,
            },
            {
                "roleArn": COMPLETE,
                "_codebuild_project_arns": COMPLETE,
                "_s3_source_bucket_arns": COMPLETE,
            },
        )
    if failed:
        raise _undescribed("CodePipeline pipelines", failed)


def kms_aliases_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate KMS aliases (regional). ``_target_key_arn`` is the ARN of the key an alias points at, built
    from the alias's own ARN (same partition, region and account) and its ``TargetKeyId``; it is ``None`` for
    an alias with no target. AWS-managed aliases (``alias/aws/...``) are listed like any other."""
    client = client_for("kms")
    for page in _pages(client, "list_aliases"):
        for alias in page.get("Aliases", []):
            arn, key_id = alias.get("AliasArn"), alias.get("TargetKeyId")
            if not arn:
                continue
            prefix = arn.rsplit(":", 1)[0] + ":"
            yield with_edge_reads(
                {**alias, "_target_key_arn": f"{prefix}key/{key_id}" if key_id else None},
                {"_target_key_arn": COMPLETE},
            )


def _cloudtrail_lake_items(client_for: Any, method: str, list_key: str, id_key: str) -> Iterator[dict[str, Any]]:
    """A CloudTrail Lake listing with each item's tags (``ListTags``, 20 ARNs to a call) in ``_tags``."""
    client = client_for("cloudtrail")
    items = [i for page in _pages(client, method) for i in page.get(list_key, []) if i.get(id_key)]
    tags = _batched_tags(
        client,
        "ResourceIdList",
        "ResourceId",
        [str(i[id_key]) for i in items],
        method="list_tags",
        list_key="ResourceTagList",
        tags_key="TagsList",
    )
    for item in items:
        arn = str(item[id_key])
        yield {
            **item,
            "_name": item.get("Name") or arn.rsplit("/", 1)[-1],
            "_tags": tags.get(arn, {}),
            "_tags_unread": arn not in tags,
        }


def cloudtrail_event_data_stores_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CloudTrail Lake event data stores (regional) with their tags."""
    yield from _cloudtrail_lake_items(client_for, "list_event_data_stores", "EventDataStores", "EventDataStoreArn")


def cloudtrail_channels_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CloudTrail Lake channels (regional) with their tags."""
    yield from _cloudtrail_lake_items(client_for, "list_channels", "Channels", "ChannelArn")


def cloudtrail_dashboards_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CloudTrail Lake dashboards (regional) with their tags."""
    yield from _cloudtrail_lake_items(client_for, "list_dashboards", "Dashboards", "DashboardArn")


# Config's organization calls fail this way in an account that is not the organization's management or
# delegated administrator account (or has no organization): there is nothing to list, which is not an error.
_NOT_AN_ORGANIZATION_ADMIN = frozenset(
    {"OrganizationAccessDeniedException", "NoSuchOrganizationException", "OrganizationNotInAllFeaturesModeException"}
)


def _config_organization_items(client_for: Any, method: str, list_key: str) -> Iterator[dict[str, Any]]:
    client = client_for("config")
    yielded = False
    try:
        for page in _pages(client, method):
            for item in page.get(list_key, []):
                last = item.get("LastUpdateTime")
                yielded = True
                yield {**item, "_last_update_time": jsonable(last) if last else None}
    except ClientError as exc:
        # 'Not the organization admin' is an answer to the first call. After a page has been yielded the same
        # code means the listing was cut short, which must not read as a complete one.
        if yielded or error_code(exc) not in _NOT_AN_ORGANIZATION_ADMIN:
            raise


def config_organization_rules_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate AWS Config organization rules (regional). Empty, without error, outside the organization's
    management or delegated administrator account."""
    yield from _config_organization_items(client_for, "describe_organization_config_rules", "OrganizationConfigRules")


def config_organization_conformance_packs_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate AWS Config organization conformance packs (regional). Empty, without error, outside the
    organization's management or delegated administrator account."""
    yield from _config_organization_items(
        client_for, "describe_organization_conformance_packs", "OrganizationConformancePacks"
    )


def _identity_center_instances(client_for: Any) -> list[dict[str, Any]]:
    """The Identity Center instances visible in this region (``ListInstances``). A denial is raised: an
    unreadable instance list must not read as 'no instances'."""
    client = client_for("sso-admin")
    return [i for page in _pages(client, "list_instances") for i in page.get("Instances", []) if i.get("InstanceArn")]


def identity_center_users_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate the users of each Identity Center instance's identity store (regional).

    ``ListUsers`` returns a full personal profile (emails, phone numbers, addresses, ...) and botocore marks
    every member of it sensitive. Only the identifying names are kept: the item holds the ids, ``UserName``
    and ``DisplayName``, and nothing else leaves the reader. ``_key`` is ``identity_store_id:user_id``, the
    form the group node uses. An identity store that cannot be listed is a gap (:func:`_undescribed`).
    """
    client = client_for("identitystore")
    failed: list[str] = []
    seen: set[str] = set()
    for instance in _identity_center_instances(client_for):
        store = instance.get("IdentityStoreId")
        if not store or store in seen:
            continue
        seen.add(store)
        try:
            for page in _pages(client, "list_users", IdentityStoreId=store):
                for user in page.get("Users", []):
                    user_id = user.get("UserId")
                    if user_id:
                        yield {
                            "IdentityStoreId": store,
                            "UserId": user_id,
                            "UserName": user.get("UserName"),
                            "DisplayName": user.get("DisplayName"),
                            "_key": f"{store}:{user_id}",
                        }
        except BotoCoreError, ClientError:
            failed.append(str(store))
    if failed:
        raise _undescribed("identity stores", failed)


def _identity_center_applications(client_for: Any) -> Iterator[dict[str, Any]]:
    client = client_for("sso-admin")
    seen: set[str] = set()
    for instance in _identity_center_instances(client_for):
        for page in _pages(client, "list_applications", InstanceArn=instance["InstanceArn"]):
            for application in page.get("Applications", []):
                arn = application.get("ApplicationArn")
                if arn and arn not in seen:
                    seen.add(arn)
                    yield application


def identity_center_applications_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Identity Center applications of each instance (regional); tags are read by the manifest's
    tag lane (``ListTagsForResource`` takes the instance and the application)."""
    yield from _identity_center_applications(client_for)


def identity_center_application_assignments_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate the users and groups assigned to each Identity Center application (regional).

    An assignment has no ARN, so ``_key`` is ``application_arn|principal_type|principal_id``. An application
    whose assignments cannot be listed is a gap (:func:`_undescribed`).
    """
    client = client_for("sso-admin")
    failed: list[str] = []
    for application in _identity_center_applications(client_for):
        arn = str(application["ApplicationArn"])
        try:
            for page in _pages(client, "list_application_assignments", ApplicationArn=arn):
                for assignment in page.get("ApplicationAssignments", []):
                    kind, principal = assignment.get("PrincipalType"), assignment.get("PrincipalId")
                    if kind and principal:
                        yield {**assignment, "_key": f"{arn}|{kind}|{principal}"}
        except BotoCoreError, ClientError:
            failed.append(arn)
    if failed:
        raise _undescribed("applications whose assignments", failed)


def access_analyzer_archive_rules_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate the archive rules of each IAM Access Analyzer analyzer (regional).

    A rule has no ARN in the API, so ``_arn`` is the analyzer's ARN plus ``/archive-rule/`` and the rule name
    (the form the Service Authorization Reference gives). An analyzer whose rules cannot be listed is a gap
    (:func:`_undescribed`).
    """
    client = client_for("accessanalyzer")
    failed: list[str] = []
    for analyzers in _pages(client, "list_analyzers"):
        for analyzer in analyzers.get("analyzers", []):
            name, analyzer_arn = analyzer.get("name"), analyzer.get("arn")
            if not name or not analyzer_arn:
                continue
            try:
                for page in _pages(client, "list_archive_rules", analyzerName=name):
                    for rule in page.get("archiveRules", []):
                        if rule.get("ruleName"):
                            updated = rule.get("updatedAt")
                            yield {
                                **rule,
                                "_analyzer_arn": analyzer_arn,
                                "_arn": f"{analyzer_arn}/archive-rule/{rule['ruleName']}",
                                "_updated_at": jsonable(updated) if updated else None,
                            }
            except BotoCoreError, ClientError:
                failed.append(str(analyzer_arn))
    if failed:
        raise _undescribed("analyzers whose archive rules", failed)


# The continuation key of EventBridge's list calls, which return one and have no paginator.
_CONTINUATION = "NextToken"


def _token_pages(client: Any, method: str, continue_on: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
    """Pages of a list call that has a continuation key (``continue_on``) but no botocore paginator
    (EventBridge's and WAFv2's list calls): call, then call again with what the answer returned under that
    key, until it returns none."""
    if client.can_paginate(method):
        yield from _pages(client, method, **kwargs)
        return
    after: str | None = None
    while True:
        page = without_response_metadata(getattr(client, method)(**kwargs, **({continue_on: after} if after else {})))
        yield page
        after = page.get(continue_on)
        if not after:
            return


def sns_topics_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate SNS topics (regional): ``GetTopicAttributes`` for the attributes and ``ListTagsForResource``
    for the tags, one call each per topic. ``_attributes`` is the attribute map (all strings, as SNS returns
    them); the ``_`` siblings are the typed readings of it. A topic whose attributes cannot be read is a gap
    (:func:`_undescribed`); a failed tag read leaves its tags unread."""
    client = client_for("sns")
    failed: list[str] = []
    for page in _pages(client, "list_topics"):
        for entry in page.get("Topics", []):
            arn = entry.get("TopicArn")
            if not arn:
                continue
            try:
                attributes = without_response_metadata(client.get_topic_attributes(TopicArn=arn)).get("Attributes") or {}
            except BotoCoreError, ClientError:
                failed.append(str(arn))
                continue
            tags: dict[str, str] = {}
            tags_unread = False
            try:
                answer = without_response_metadata(client.list_tags_for_resource(ResourceArn=arn))
                tags = {t["Key"]: t.get("Value") or "" for t in answer.get("Tags", []) if "Key" in t}
            except BotoCoreError, ClientError:
                tags_unread = True

            def count(key: str, attrs: dict[str, str] = attributes) -> int | None:
                value = attrs.get(key)
                return int(value) if isinstance(value, str) and value.isdigit() else None

            yield {
                "TopicArn": arn,
                "_name": str(arn).rsplit(":", 1)[-1],
                "Attributes": attributes,
                "_kms_master_key_id": attributes.get("KmsMasterKeyId") or None,
                "_fifo_topic": None if "FifoTopic" not in attributes else attributes["FifoTopic"] == "true",
                "_subscriptions_confirmed": count("SubscriptionsConfirmed"),
                "_subscriptions_pending": count("SubscriptionsPending"),
                "_tags": tags,
                "_tags_unread": tags_unread,
            }
    if failed:
        raise _undescribed("SNS topics", failed)


def sns_subscriptions_listed(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate SNS subscriptions (regional). A subscription still awaiting confirmation (or deleted) is
    reported with the literal ``PendingConfirmation``/``Deleted`` in place of its ARN, which is not an
    identity, so it is not collected. The endpoint (an email address, a phone number, or a URL that can carry
    credentials) is dropped here and never leaves the reader."""
    client = client_for("sns")
    for page in _pages(client, "list_subscriptions"):
        for sub in page.get("Subscriptions", []):
            arn = sub.get("SubscriptionArn")
            if arn and arn.startswith("arn:"):
                yield {k: v for k, v in sub.items() if k != "Endpoint"}


def _eventbridge_items(client_for: Any, method: str, list_key: str) -> Iterator[dict[str, Any]]:
    client = client_for("events")
    for page in _token_pages(client, method, _CONTINUATION):
        yield from page.get(list_key, [])


def eventbridge_event_buses_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate EventBridge event buses (regional), the default bus included."""
    yield from _eventbridge_items(client_for, "list_event_buses", "EventBuses")


def eventbridge_archives_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate EventBridge archives (regional). ``ListArchives`` carries no ARN, so ``_arn`` is built from
    the source event bus's ARN (same partition, region and account): ``arn:...:archive/<name>``."""
    for archive in _eventbridge_items(client_for, "list_archives", "Archives"):
        source, name = str(archive.get("EventSourceArn") or ""), archive.get("ArchiveName")
        if name and source.count(":") >= 5:
            yield {**archive, "_arn": f"{source.rsplit(':', 1)[0]}:archive/{name}"}


def eventbridge_connections_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate EventBridge connections (regional): the stored credentials an API destination calls with.
    ``ListConnections`` returns their state and authorization type and never the credentials."""
    yield from _eventbridge_items(client_for, "list_connections", "Connections")


def _without_credentials(url: str) -> str:
    """``url`` as scheme, host and path only: the user info, query string and fragment are where a token or a
    password goes in a URL, and none of them is needed to know which endpoint is called."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def eventbridge_api_destinations_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate EventBridge API destinations (regional). The endpoint URL is reduced to scheme, host and path
    (:func:`_without_credentials`): a token in a query string or user info never leaves the reader."""
    for destination in _eventbridge_items(client_for, "list_api_destinations", "ApiDestinations"):
        endpoint = destination.get("InvocationEndpoint")
        yield {**destination, "InvocationEndpoint": _without_credentials(endpoint) if endpoint else endpoint}


def lambda_function_urls_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Lambda function URLs (regional): ``ListFunctionUrlConfigs`` for each function. A URL with
    ``AuthType: NONE`` is open to the internet. A function whose URLs cannot be listed is a gap
    (:func:`_undescribed`)."""
    client = client_for("lambda")
    failed: list[str] = []
    for page in _pages(client, "list_functions"):
        for function in page.get("Functions", []):
            name = function.get("FunctionName")
            if not name:
                continue
            try:
                for urls in _pages(client, "list_function_url_configs", FunctionName=name):
                    for config in urls.get("FunctionUrlConfigs", []):
                        if config.get("FunctionUrl"):
                            yield {**config, "_allow_origins": (config.get("Cors") or {}).get("AllowOrigins")}
            except BotoCoreError, ClientError:
                failed.append(str(name))
    if failed:
        raise _undescribed("Lambda functions whose URLs", failed)


def lambda_layer_versions_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate the account's Lambda layer versions (regional): every version of each layer, not only the
    latest. A layer whose versions cannot be listed is a gap (:func:`_undescribed`)."""
    client = client_for("lambda")
    failed: list[str] = []
    for page in _pages(client, "list_layers"):
        for layer in page.get("Layers", []):
            arn = layer.get("LayerArn")
            if not arn:
                continue
            try:
                for versions in _pages(client, "list_layer_versions", LayerName=arn):
                    for version in versions.get("LayerVersions", []):
                        if version.get("LayerVersionArn"):
                            yield {**version, "_layer_arn": arn, "_layer_name": layer.get("LayerName")}
            except BotoCoreError, ClientError:
                failed.append(str(arn))
    if failed:
        raise _undescribed("Lambda layers whose versions", failed)


def lambda_code_signing_configs_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Lambda code signing configurations (regional)."""
    client = client_for("lambda")
    for page in _pages(client, "list_code_signing_configs"):
        yield from page.get("CodeSigningConfigs", [])


def lambda_event_source_mappings_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Lambda event source mappings (regional). ``_arn`` is the mapping's ARN, built from the
    function's ARN and the mapping UUID when the answer carries none."""
    client = client_for("lambda")
    for page in _pages(client, "list_event_source_mappings"):
        for mapping in page.get("EventSourceMappings", []):
            uuid_, function = mapping.get("UUID"), str(mapping.get("FunctionArn") or "")
            arn = mapping.get("EventSourceMappingArn")
            if not arn and uuid_ and function.count(":") >= 6:
                arn = f"{':'.join(function.split(':')[:5])}:event-source-mapping:{uuid_}"
            if arn:
                yield {**mapping, "_arn": arn}


def _account_id(client_for: Any) -> str:
    """The calling account's id (``sts:GetCallerIdentity``), for ARNs and keys the service does not return."""
    return str(without_response_metadata(client_for("sts").get_caller_identity()).get("Account") or "")


def _guardduty_detector_ids(client: Any) -> list[str]:
    return [str(d) for page in _pages(client, "list_detectors") for d in page.get("DetectorIds", []) if d]


def _guardduty_children(
    client_for: Any, list_method: str, list_key: str, get_method: str, id_param: str, kind: str, *, ident: str
) -> Iterator[dict[str, Any]]:
    """The detector-scoped objects of each GuardDuty detector: the list call names them (by id or name), the
    get call describes each, and every item carries ``_key`` (``<detector>/<kind>/<id>``) and
    ``_detector_key`` (the detector node's key, ``<account>:<region>:<detector>``). Something listed but not
    described is a gap (:func:`_undescribed`)."""
    client = client_for("guardduty")
    account, region = _account_id(client_for), _client_region(client)
    failed: list[str] = []
    for detector in _guardduty_detector_ids(client):
        for page in _pages(client, list_method, DetectorId=detector):
            for name in page.get(list_key, []):
                try:
                    described = without_response_metadata(getattr(client, get_method)(DetectorId=detector, **{id_param: name}))
                except BotoCoreError, ClientError:
                    failed.append(f"{detector}/{kind}/{name}")
                    continue
                yield with_edge_reads(
                    {
                        **described,
                        "DetectorId": detector,
                        ident: name,
                        "_key": f"{detector}/{kind}/{name}",
                        "_detector_key": f"{account}:{region}:{detector}",
                    },
                    {"_detector_key": COMPLETE},
                )
    if failed:
        raise _undescribed(f"GuardDuty {kind}s", failed)


def guardduty_filters_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate GuardDuty filters (regional): suppression rules that archive matching findings."""
    yield from _guardduty_children(client_for, "list_filters", "FilterNames", "get_filter", "FilterName", "filter", ident="FilterName")


def guardduty_ip_sets_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate GuardDuty trusted IP lists (regional): addresses GuardDuty will not report on."""
    yield from _guardduty_children(client_for, "list_ip_sets", "IpSetIds", "get_ip_set", "IpSetId", "ipset", ident="IpSetId")


def guardduty_threat_intel_sets_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate GuardDuty threat intelligence sets (regional): addresses GuardDuty reports on."""
    yield from _guardduty_children(client_for, "list_threat_intel_sets", "ThreatIntelSetIds", "get_threat_intel_set", "ThreatIntelSetId", "threatintelset", ident="ThreatIntelSetId")


def guardduty_publishing_destinations_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate GuardDuty publishing destinations (regional): where findings are exported to (S3, with a key)."""
    client = client_for("guardduty")
    account, region = _account_id(client_for), _client_region(client)
    failed: list[str] = []
    for detector in _guardduty_detector_ids(client):
        for page in _token_pages(client, "list_publishing_destinations", "NextToken", DetectorId=detector):
            for entry in page.get("Destinations", []):
                dest_id = entry.get("DestinationId")
                if not dest_id:
                    continue
                try:
                    described = without_response_metadata(client.describe_publishing_destination(DetectorId=detector, DestinationId=dest_id))
                except BotoCoreError, ClientError:
                    failed.append(f"{detector}/destination/{dest_id}")
                    continue
                yield with_edge_reads(
                    {
                        **described,
                        "DetectorId": detector,
                        "_key": f"{detector}/destination/{dest_id}",
                        "_detector_key": f"{account}:{region}:{detector}",
                    },
                    {"_detector_key": COMPLETE, "DestinationProperties": COMPLETE},
                )
    if failed:
        raise _undescribed("GuardDuty publishing destinations", failed)


def guardduty_members_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate the member accounts of each GuardDuty detector (regional). ``ListMembers`` returns the member's
    email address, which botocore marks sensitive; the reader drops it."""
    client = client_for("guardduty")
    account, region = _account_id(client_for), _client_region(client)
    for detector in _guardduty_detector_ids(client):
        for page in _pages(client, "list_members", DetectorId=detector, OnlyAssociated="false"):
            for member in page.get("Members", []):
                member_account = member.get("AccountId")
                if member_account:
                    yield with_edge_reads(
                        {
                            **{k: v for k, v in member.items() if k != "Email"},
                            "ParentDetectorId": detector,
                            "_key": f"{detector}/member/{member_account}",
                            "_detector_key": f"{account}:{region}:{detector}",
                        },
                        {"_detector_key": COMPLETE},
                    )


# WAFv2's list calls have a marker and no paginator, and a scope: REGIONAL in every region, CLOUDFRONT only
# through the partition's home region (us-east-1) and only where CloudFront exists.
def _wafv2_scopes(client: Any) -> list[str]:
    region = _client_region(client)
    partition = partition_of_region(region)
    scopes = ["REGIONAL"]
    if partition == PARTITION_AWS and region == home_region(partition):
        scopes.append("CLOUDFRONT")
    return scopes


def _wafv2_objects(client_for: Any, list_method: str, list_key: str, get_method: str, get_key: str) -> Iterator[dict[str, Any]]:
    """The WAFv2 objects of each scope: the list call names them, the get call describes each, and
    ``ListTagsForResource`` reads its tags. The item is the description with ``Scope``, ``_arn`` and the tags
    added. Something listed but not described is a gap (:func:`_undescribed`); a failed tag read leaves the
    tags unread."""
    client = client_for("wafv2")
    failed: list[str] = []
    for scope in _wafv2_scopes(client):
        for page in _token_pages(client, list_method, "NextMarker", Scope=scope):
            for entry in page.get(list_key, []):
                name, ident, arn = entry.get("Name"), entry.get("Id"), entry.get("ARN")
                if not (name and ident and arn):
                    continue
                try:
                    described = without_response_metadata(getattr(client, get_method)(Name=name, Scope=scope, Id=ident))
                except BotoCoreError, ClientError:
                    failed.append(str(arn))
                    continue
                tags: dict[str, str] = {}
                tags_unread = False
                try:
                    for tag_page in _token_pages(client, "list_tags_for_resource", "NextMarker", ResourceARN=arn):
                        tag_list = (tag_page.get("TagInfoForResource") or {}).get("TagList", [])
                        tags.update({t["Key"]: t.get("Value") or "" for t in tag_list if "Key" in t})
                except BotoCoreError, ClientError:
                    tags, tags_unread = {}, True
                yield {**(described.get(get_key) or {}), "Scope": scope, "_arn": arn, "_tags": tags, "_tags_unread": tags_unread}
    if failed:
        raise _undescribed(f"WAFv2 {get_key} objects", failed)


def wafv2_web_acls_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate WAFv2 web ACLs. ``_default_action`` is ``ALLOW`` or ``BLOCK`` and ``_rule_count`` the number
    of rules (``None`` when the description names no rules list)."""
    for acl in _wafv2_objects(client_for, "list_web_acls", "WebACLs", "get_web_acl", "WebACL"):
        action = acl.get("DefaultAction") or {}
        rules = acl.get("Rules")
        yield {**acl, "_default_action": "ALLOW" if "Allow" in action else "BLOCK" if "Block" in action else None, "_rule_count": len(rules) if isinstance(rules, list) else None}


def wafv2_rule_groups_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate WAFv2 rule groups."""
    for group in _wafv2_objects(client_for, "list_rule_groups", "RuleGroups", "get_rule_group", "RuleGroup"):
        rules = group.get("Rules")
        yield {**group, "_rule_count": len(rules) if isinstance(rules, list) else None}


def wafv2_ip_sets_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate WAFv2 IP sets. ``_address_count`` is how many addresses the set holds."""
    for ip_set in _wafv2_objects(client_for, "list_ip_sets", "IPSets", "get_ip_set", "IPSet"):
        addresses = ip_set.get("Addresses")
        yield {**ip_set, "_address_count": len(addresses) if isinstance(addresses, list) else None}


def wafv2_regex_pattern_sets_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate WAFv2 regex pattern sets. ``_pattern_count`` is how many patterns the set holds."""
    for pattern_set in _wafv2_objects(client_for, "list_regex_pattern_sets", "RegexPatternSets", "get_regex_pattern_set", "RegexPatternSet"):
        patterns = pattern_set.get("RegularExpressionList")
        yield {**pattern_set, "_pattern_count": len(patterns) if isinstance(patterns, list) else None}


def s3_access_points_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate S3 access points (regional): ``ListAccessPoints`` (S3 Control, by account id) and
    ``GetAccessPointPolicyStatus`` for whether each is public. ``_account_id`` rides with the item for the tag
    read, which S3 Control takes by account and ARN. A status that cannot be read leaves ``_is_public`` ``None``."""
    client = client_for("s3control")
    account = _account_id(client_for)
    for page in _token_pages(client, "list_access_points", "NextToken", AccountId=account):
        for access_point in page.get("AccessPointList", []):
            name = access_point.get("Name")
            if not name:
                continue
            is_public: bool | None = None
            try:
                status = without_response_metadata(client.get_access_point_policy_status(AccountId=account, Name=name))
                public = (status.get("PolicyStatus") or {}).get("IsPublic")
                is_public = public if isinstance(public, bool) else None
            except BotoCoreError, ClientError:
                is_public = None
            bucket = access_point.get("Bucket")
            yield with_edge_reads(
                {
                    **access_point,
                    "_account_id": account,
                    "_is_public": is_public,
                    "_vpc_id": (access_point.get("VpcConfiguration") or {}).get("VpcId"),
                    "_bucket_arn": build_arn(partition_of_region(_client_region(client)), "s3", "", "", bucket) if bucket else None,
                },
                {"_bucket_arn": COMPLETE},
            )


def efs_access_points_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate EFS access points (regional). ``_file_system_arn`` is the file system's ARN, built from the
    access point's own (same partition, region and account) and its ``FileSystemId``."""
    client = client_for("efs")
    for page in _pages(client, "describe_access_points"):
        for access_point in page.get("AccessPoints", []):
            arn, file_system = str(access_point.get("AccessPointArn") or ""), access_point.get("FileSystemId")
            prefix = arn.rsplit(":", 1)[0] if arn.count(":") >= 5 else ""
            yield with_edge_reads(
                {**access_point, "_file_system_arn": f"{prefix}:file-system/{file_system}" if prefix and file_system else None},
                {"_file_system_arn": COMPLETE},
            )


def efs_mount_targets_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate EFS mount targets (regional): ``DescribeMountTargets`` takes a file system, so each file
    system is asked in turn. ``_file_system_arn`` is built from the file system's own ARN. A file system whose
    mount targets cannot be listed is a gap (:func:`_undescribed`)."""
    client = client_for("efs")
    failed: list[str] = []
    for page in _pages(client, "describe_file_systems"):
        for file_system in page.get("FileSystems", []):
            fs_id = file_system.get("FileSystemId")
            if not fs_id:
                continue
            try:
                for targets in _pages(client, "describe_mount_targets", FileSystemId=fs_id):
                    for target in targets.get("MountTargets", []):
                        yield with_edge_reads(
                            {**target, "_file_system_arn": file_system.get("FileSystemArn")}, {"_file_system_arn": COMPLETE, "SubnetId": COMPLETE}
                        )
            except BotoCoreError, ClientError:
                failed.append(str(fs_id))
    if failed:
        raise _undescribed("EFS file systems whose mount targets", failed)


def elbv2_listeners_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate ELBv2 listeners (regional): ``DescribeListeners`` for each load balancer, tags 20 ARNs to a
    call. The listener is the TLS fact (protocol, policy, certificates) and carries the authentication action
    (an OIDC action holds a client secret). ``_certificate_arns`` and ``_action_types`` are derived; ``_alb_arn``
    is the load balancer's ARN for an Application Load Balancer only, the one kind whose node is keyed by it.
    A load balancer whose listeners cannot be listed is a gap (:func:`_undescribed`)."""
    client = client_for("elbv2")
    listeners: list[dict[str, Any]] = []
    failed: list[str] = []
    for lb in _elbv2_load_balancers(client):
        lb_arn = lb.get("LoadBalancerArn")
        if not lb_arn:
            continue
        try:
            for page in _pages(client, "describe_listeners", LoadBalancerArn=lb_arn):
                listeners.extend({**listener, "_lb_type": lb.get("Type")} for listener in page.get("Listeners", []) if listener.get("ListenerArn"))
        except BotoCoreError, ClientError:
            failed.append(str(lb_arn))
    tags = _batched_tags(client, "ResourceArns", "ResourceArn", [str(x["ListenerArn"]) for x in listeners])
    for listener in listeners:
        arn = str(listener["ListenerArn"])
        actions = listener.get("DefaultActions") or []
        # DescribeListeners names the default certificate only; the others (SNI) are DescribeListenerCertificates'.
        certificates = {str(c["CertificateArn"]) for c in listener.get("Certificates", []) if c.get("CertificateArn")}
        certificates_read = COMPLETE
        if listener.get("Protocol") in ("HTTPS", "TLS"):
            try:
                for cert_page in _pages(client, "describe_listener_certificates", ListenerArn=arn):
                    certificates.update(str(c["CertificateArn"]) for c in cert_page.get("Certificates", []) if c.get("CertificateArn"))
            except BotoCoreError, ClientError:
                certificates_read = PARTIAL
        yield with_edge_reads(
            {
                **listener,
                "_certificate_arns": sorted(certificates),
                "_action_types": [a.get("Type") for a in actions if a.get("Type")],
                "_alb_arn": listener.get("LoadBalancerArn") if listener.get("_lb_type") == "application" else None,
                "_tags": tags.get(arn, {}),
                "_tags_unread": arn not in tags,
            },
            {"_certificate_arns": certificates_read, "_alb_arn": COMPLETE},
        )
    if failed:
        raise _undescribed("load balancers whose listeners", failed)


def _backup_tags(client: Any, arn: str) -> tuple[dict[str, str], bool]:
    """``(tags, unread)`` for one AWS Backup resource: ``ListTags`` returns a plain map."""
    try:
        return dict(without_response_metadata(client.list_tags(ResourceArn=arn)).get("Tags") or {}), False
    except BotoCoreError, ClientError:
        return {}, True


def backup_vaults_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate AWS Backup vaults (regional) with tags (botocore marks the tag map sensitive; the values go to
    the canonical ``tags`` field only)."""
    client = client_for("backup")
    for page in _pages(client, "list_backup_vaults"):
        for vault in page.get("BackupVaultList", []):
            arn = vault.get("BackupVaultArn")
            if arn:
                tags, unread = _backup_tags(client, arn)
                yield {**vault, "_tags": tags, "_tags_unread": unread}


def backup_plans_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate AWS Backup plans (regional): ``ListBackupPlans`` names them, ``GetBackupPlan`` reads the rules.
    ``BackupPlan`` is the plan's detail (rules, schedules, lifecycle), ``_rule_count`` the number of rules and
    ``_target_vault_arns`` the vaults the rules write to, built from the plan's own ARN (same partition, region and account). A plan that cannot be read is a gap
    (:func:`_undescribed`)."""
    client = client_for("backup")
    failed: list[str] = []
    for page in _pages(client, "list_backup_plans"):
        for plan in page.get("BackupPlansList", []):
            arn, plan_id = plan.get("BackupPlanArn"), plan.get("BackupPlanId")
            if not (arn and plan_id):
                continue
            try:
                detail = without_response_metadata(client.get_backup_plan(BackupPlanId=plan_id)).get("BackupPlan") or {}
            except BotoCoreError, ClientError:
                failed.append(str(arn))
                continue
            rules = detail.get("Rules")
            prefix = ":".join(str(arn).split(":")[:5])
            vaults = sorted({f"{prefix}:backup-vault:{r['TargetBackupVaultName']}" for r in rules or [] if r.get("TargetBackupVaultName")})
            tags, unread = _backup_tags(client, arn)
            yield with_edge_reads(
                {**plan, "BackupPlan": detail, "_rule_count": len(rules) if isinstance(rules, list) else None, "_target_vault_arns": vaults, "_tags": tags, "_tags_unread": unread},
                {"_target_vault_arns": COMPLETE if isinstance(rules, list) else PARTIAL},
            )
    if failed:
        raise _undescribed("Backup plans", failed)


def backup_frameworks_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate AWS Backup audit frameworks (regional) with tags."""
    client = client_for("backup")
    for page in _token_pages(client, "list_frameworks", _CONTINUATION):
        for framework in page.get("Frameworks", []):
            arn = framework.get("FrameworkArn")
            if arn:
                tags, unread = _backup_tags(client, arn)
                yield {**framework, "_tags": tags, "_tags_unread": unread}


def backup_legal_holds_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate AWS Backup legal holds (regional) with tags."""
    client = client_for("backup")
    for page in _pages(client, "list_legal_holds"):
        for hold in page.get("LegalHolds", []):
            arn = hold.get("LegalHoldArn")
            if arn:
                tags, unread = _backup_tags(client, arn)
                yield {**hold, "_tags": tags, "_tags_unread": unread}


def cognito_identity_pools_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Cognito identity pools (regional): ``ListIdentityPools`` and ``DescribeIdentityPool`` (which
    carries ``IdentityPoolTags``). ``AllowUnauthenticatedIdentities`` is the exposure fact: anyone can get
    credentials. A pool that cannot be described is a gap (:func:`_undescribed`)."""
    client = client_for("cognito-identity")
    failed: list[str] = []
    for page in _pages(client, "list_identity_pools", MaxResults=60):
        for entry in page.get("IdentityPools", []):
            pool_id = entry.get("IdentityPoolId")
            if not pool_id:
                continue
            try:
                yield without_response_metadata(client.describe_identity_pool(IdentityPoolId=pool_id))
            except BotoCoreError, ClientError:
                failed.append(str(pool_id))
    if failed:
        raise _undescribed("Cognito identity pools", failed)


def _cognito_user_pool_ids(client: Any) -> list[str]:
    return [p["Id"] for page in _pages(client, "list_user_pools", MaxResults=60) for p in page.get("UserPools", []) if p.get("Id")]


def cognito_user_pool_clients_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate the app clients of each Cognito user pool (regional): ``ListUserPoolClients`` then
    ``DescribeUserPoolClient``. ``_key`` is ``<pool id>:<client id>`` and ``_has_secret`` whether the client
    has a secret (the secret itself is in the answer and is why the entry stores nothing). A pool whose clients
    cannot be read is a gap (:func:`_undescribed`)."""
    client = client_for("cognito-idp")
    failed: list[str] = []
    for pool in _cognito_user_pool_ids(client):
        try:
            for page in _pages(client, "list_user_pool_clients", UserPoolId=pool, MaxResults=60):
                for entry in page.get("UserPoolClients", []):
                    client_id = entry.get("ClientId")
                    if not client_id:
                        continue
                    detail = without_response_metadata(client.describe_user_pool_client(UserPoolId=pool, ClientId=client_id)).get("UserPoolClient") or {}
                    yield {**detail, "UserPoolId": pool, "_key": f"{pool}:{client_id}", "_has_secret": bool(detail.get("ClientSecret"))}
        except BotoCoreError, ClientError:
            failed.append(str(pool))
    if failed:
        raise _undescribed("Cognito user pools whose clients", failed)


def cognito_identity_providers_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate the identity providers of each Cognito user pool (regional): ``ListIdentityProviders`` then
    ``DescribeIdentityProvider`` (whose provider details hold the OAuth client secret). ``_key`` is
    ``<pool id>:<provider name>``. A pool whose providers cannot be read is a gap (:func:`_undescribed`)."""
    client = client_for("cognito-idp")
    failed: list[str] = []
    for pool in _cognito_user_pool_ids(client):
        try:
            for page in _pages(client, "list_identity_providers", UserPoolId=pool, MaxResults=60):
                for entry in page.get("Providers", []):
                    name = entry.get("ProviderName")
                    if not name:
                        continue
                    detail = without_response_metadata(client.describe_identity_provider(UserPoolId=pool, ProviderName=name)).get("IdentityProvider") or {}
                    yield {**detail, "UserPoolId": pool, "_key": f"{pool}:{name}"}
        except BotoCoreError, ClientError:
            failed.append(str(pool))
    if failed:
        raise _undescribed("Cognito user pools whose identity providers", failed)


def cognito_user_pool_groups_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate the groups of each Cognito user pool (regional). ``_key`` is ``<pool id>:<group name>``. A group
    can carry an IAM role its members assume. A pool whose groups cannot be read is a gap
    (:func:`_undescribed`)."""
    client = client_for("cognito-idp")
    failed: list[str] = []
    for pool in _cognito_user_pool_ids(client):
        try:
            for page in _pages(client, "list_groups", UserPoolId=pool, Limit=60):
                for group in page.get("Groups", []):
                    if group.get("GroupName"):
                        yield with_edge_reads({**group, "UserPoolId": pool, "_key": f"{pool}:{group['GroupName']}"}, {"RoleArn": COMPLETE})
        except BotoCoreError, ClientError:
            failed.append(str(pool))
    if failed:
        raise _undescribed("Cognito user pools whose groups", failed)


def cognito_user_pool_resource_servers_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate the OAuth resource servers of each Cognito user pool (regional). ``_key`` is
    ``<pool id>:<identifier>``. A pool whose resource servers cannot be read is a gap (:func:`_undescribed`)."""
    client = client_for("cognito-idp")
    failed: list[str] = []
    for pool in _cognito_user_pool_ids(client):
        try:
            for page in _pages(client, "list_resource_servers", UserPoolId=pool, MaxResults=50):
                for server in page.get("ResourceServers", []):
                    if server.get("Identifier"):
                        yield {**server, "UserPoolId": pool, "_key": f"{pool}:{server['Identifier']}"}
        except BotoCoreError, ClientError:
            failed.append(str(pool))
    if failed:
        raise _undescribed("Cognito user pools whose resource servers", failed)


def cognito_user_pool_domains_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate the domains of each Cognito user pool (regional): the prefix domain and the custom domain
    ``DescribeUserPool`` names, each described by ``DescribeUserPoolDomain``. A pool or domain that cannot be
    read is a gap (:func:`_undescribed`)."""
    client = client_for("cognito-idp")
    failed: list[str] = []
    for pool in _cognito_user_pool_ids(client):
        try:
            described = without_response_metadata(client.describe_user_pool(UserPoolId=pool)).get("UserPool") or {}
        except BotoCoreError, ClientError:
            failed.append(str(pool))
            continue
        for domain in sorted({d for d in (described.get("Domain"), described.get("CustomDomain")) if d}):
            try:
                detail = without_response_metadata(client.describe_user_pool_domain(Domain=domain)).get("DomainDescription") or {}
            except BotoCoreError, ClientError:
                failed.append(f"{pool}:{domain}")
                continue
            if detail.get("Domain"):
                yield {**detail, "UserPoolId": detail.get("UserPoolId") or pool, "_key": f"{pool}:{detail['Domain']}"}
    if failed:
        raise _undescribed("Cognito user pool domains", failed)


def _sns_topic_arns(*action_lists: Any) -> list[str]:
    """The SNS topic ARNs among CloudWatch alarm actions (which can also be Lambda, Auto Scaling and SSM ARNs)."""
    return sorted({a for actions in action_lists for a in actions or [] if re.match(rf"^arn:{PARTITION_RE}:sns:", str(a))})


def cloudwatch_alarms_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CloudWatch metric alarms (regional). ``_sns_topic_arns`` are the SNS topics in the alarm's
    actions: where the alarm sends people to look."""
    client = client_for("cloudwatch")
    for page in _pages(client, "describe_alarms", AlarmTypes=["MetricAlarm"]):
        for alarm in page.get("MetricAlarms", []):
            if alarm.get("AlarmArn"):
                topics = _sns_topic_arns(alarm.get("AlarmActions"), alarm.get("OKActions"), alarm.get("InsufficientDataActions"))
                yield with_edge_reads({**alarm, "_sns_topic_arns": topics}, {"_sns_topic_arns": COMPLETE})


def cloudwatch_composite_alarms_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CloudWatch composite alarms (regional), with the SNS topics in their actions."""
    client = client_for("cloudwatch")
    for page in _pages(client, "describe_alarms", AlarmTypes=["CompositeAlarm"]):
        for alarm in page.get("CompositeAlarms", []):
            if alarm.get("AlarmArn"):
                topics = _sns_topic_arns(alarm.get("AlarmActions"), alarm.get("OKActions"), alarm.get("InsufficientDataActions"))
                yield with_edge_reads({**alarm, "_sns_topic_arns": topics}, {"_sns_topic_arns": COMPLETE})


def cloudwatch_dashboards_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CloudWatch dashboards (regional). The dashboard body (GetDashboard) is not requested."""
    client = client_for("cloudwatch")
    for page in _pages(client, "list_dashboards"):
        yield from (d for d in page.get("DashboardEntries", []) if d.get("DashboardArn"))


def cloudwatch_metric_streams_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CloudWatch metric streams (regional): the Firehose delivery of metrics to a destination."""
    client = client_for("cloudwatch")
    for page in _token_pages(client, "list_metric_streams", _CONTINUATION):
        yield from (e for e in page.get("Entries", []) if e.get("Arn"))


def _log_group_arn(partition: str, region: str, account: str, name: str) -> str:
    return build_arn(partition, "logs", region, account, f"log-group:{name}")


def logs_metric_filters_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CloudWatch Logs metric filters (regional), every log group's at once. ``_key`` is
    ``<log group>:<filter>`` and ``_log_group_arn`` the log group's ARN (the form the log group node is keyed
    by). The first metric transformation's name and namespace are ``_metric_name`` and ``_metric_namespace``."""
    client = client_for("logs")
    region = _client_region(client)
    partition, account = partition_of_region(region), _account_id(client_for)
    for page in _pages(client, "describe_metric_filters"):
        for item in page.get("metricFilters", []):
            group, name = item.get("logGroupName"), item.get("filterName")
            if not (group and name):
                continue
            first = (item.get("metricTransformations") or [{}])[0]
            yield with_edge_reads(
                {
                    **item,
                    "_key": f"{group}:{name}",
                    "_log_group_arn": _log_group_arn(partition, region, account, group),
                    "_metric_name": first.get("metricName"),
                    "_metric_namespace": first.get("metricNamespace"),
                },
                {"_log_group_arn": COMPLETE},
            )


def logs_subscription_filters_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CloudWatch Logs subscription filters (regional): ``DescribeSubscriptionFilters`` takes a log
    group, so each group is asked in turn. A subscription filter sends a log group's events to a destination
    (a Kinesis stream, a Lambda function, another account's destination). A group whose filters cannot be
    listed is a gap (:func:`_undescribed`)."""
    client = client_for("logs")
    region = _client_region(client)
    partition, account = partition_of_region(region), _account_id(client_for)
    failed: list[str] = []
    for groups in _pages(client, "describe_log_groups"):
        for group in groups.get("logGroups", []):
            name = group.get("logGroupName")
            if not name:
                continue
            try:
                for page in _pages(client, "describe_subscription_filters", logGroupName=name):
                    for item in page.get("subscriptionFilters", []):
                        if item.get("filterName"):
                            yield with_edge_reads(
                                {**item, "_key": f"{name}:{item['filterName']}", "_log_group_arn": _log_group_arn(partition, region, account, name)},
                                {"_log_group_arn": COMPLETE, "roleArn": COMPLETE},
                            )
            except BotoCoreError, ClientError:
                failed.append(str(name))
    if failed:
        raise _undescribed("log groups whose subscription filters", failed)


def logs_destinations_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CloudWatch Logs destinations (regional): the cross-account receivers of subscription filters,
    each with an access policy naming who may send to it. Tags are read by ARN (``ListTagsForResource``)."""
    client = client_for("logs")
    for page in _pages(client, "describe_destinations"):
        for destination in page.get("destinations", []):
            arn = destination.get("arn")
            if not arn:
                continue
            tags: dict[str, str] = {}
            unread = False
            try:
                tags = dict(without_response_metadata(client.list_tags_for_resource(resourceArn=arn)).get("tags") or {})
            except BotoCoreError, ClientError:
                unread = True
            yield {**destination, "_tags": tags, "_tags_unread": unread}


# SecurityHub answers InvalidAccessException when the account has not enabled it in the region: there is
# nothing to list, which is not an error.
_SECURITYHUB_NOT_ENABLED = frozenset({"InvalidAccessException"})


def _securityhub_items(client_for: Any, method: str, list_key: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
    client = client_for("securityhub")
    answered = False
    try:
        for page in _token_pages(client, method, _CONTINUATION, **kwargs):
            answered = True
            yield from page.get(list_key, [])
    except ClientError as exc:
        # 'Not enabled' is an answer to the first call; after any page has come back the same code means the
        # listing was cut short, which must not read as a complete one.
        if answered or error_code(exc) not in _SECURITYHUB_NOT_ENABLED:
            raise


def _securityhub_tags(client: Any, arn: str) -> tuple[dict[str, str], bool]:
    try:
        return dict(without_response_metadata(client.list_tags_for_resource(ResourceArn=arn)).get("Tags") or {}), False
    except BotoCoreError, ClientError:
        return {}, True


def securityhub_action_targets_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Security Hub custom action targets (regional). Empty, without error, where Security Hub is not enabled."""
    yield from (t for t in _securityhub_items(client_for, "describe_action_targets", "ActionTargets") if t.get("ActionTargetArn"))


def securityhub_automation_rules_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Security Hub automation rules (regional): rules that rewrite or suppress findings as they
    arrive. ``ListAutomationRules`` names them; ``BatchGetAutomationRules`` (100 ARNs to a call) adds the
    criteria and actions as ``Criteria`` and ``Actions``. A rule the batch read did not return (a denied batch,
    or a rule left unprocessed) is still yielded, and then the reader raises (:func:`_undescribed`), so a rule
    whose suppression logic was not read is a loud gap. Tags are read by ARN. Empty, without error, where
    Security Hub is not enabled."""
    client = client_for("securityhub")
    rules = [r for r in _securityhub_items(client_for, "list_automation_rules", "AutomationRulesMetadata") if r.get("RuleArn")]
    detail: dict[str, dict[str, Any]] = {}
    for start in range(0, len(rules), 100):
        batch = [str(r["RuleArn"]) for r in rules[start : start + 100]]
        try:
            answer = without_response_metadata(client.batch_get_automation_rules(AutomationRulesArns=batch))
            detail.update({r["RuleArn"]: r for r in answer.get("Rules", []) if r.get("RuleArn")})
        except BotoCoreError, ClientError:
            continue
    missing: list[str] = []
    for rule in rules:
        arn = str(rule["RuleArn"])
        tags, unread = _securityhub_tags(client, arn)
        extra = detail.get(arn)
        if extra is None:
            missing.append(arn)
            extra = {}
        yield {**rule, "Criteria": extra.get("Criteria"), "Actions": extra.get("Actions"), "_tags": tags, "_tags_unread": unread}
    if missing:
        raise _undescribed("Security Hub automation rules whose criteria and actions", missing)


def securityhub_finding_aggregators_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Security Hub finding aggregators (regional): the cross-region aggregation of findings.
    ``GetFindingAggregator`` adds the linking mode and regions. An aggregator that cannot be described is a
    gap (:func:`_undescribed`). Empty, without error, where Security Hub is not enabled."""
    client = client_for("securityhub")
    failed: list[str] = []
    for entry in _securityhub_items(client_for, "list_finding_aggregators", "FindingAggregators"):
        arn = entry.get("FindingAggregatorArn")
        if not arn:
            continue
        try:
            yield without_response_metadata(client.get_finding_aggregator(FindingAggregatorArn=arn))
        except BotoCoreError, ClientError:
            failed.append(str(arn))
    if failed:
        raise _undescribed("Security Hub finding aggregators", failed)


def securityhub_insights_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Security Hub insights (regional): saved finding queries. Empty, without error, where Security
    Hub is not enabled."""
    yield from (i for i in _securityhub_items(client_for, "get_insights", "Insights") if i.get("InsightArn"))


def _undescribed(kind: str, names: list[str]) -> SourceError:
    """The error a reader raises, after yielding what it could describe, when some listed ``kind`` could not
    be described. The engine reports it as ``ENTRY_SKIPPED`` and keeps the items already yielded, so a
    description that failed is a loud gap in the run and never a quietly smaller inventory."""
    return SourceError(f"{len(names)} {kind} could not be described and are missing from this run: {', '.join(names)}")


def eks_clusters_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate EKS clusters (regional): ``ListClusters`` names them and ``DescribeCluster`` describes each.

    ``DescribeCluster`` carries the tags (a plain map) and the VPC configuration, including whether the API
    endpoint is public. A cluster that is listed but cannot be described has no ARN to key it by, so it is
    left out of the batch, and the reader raises once it has yielded the rest (:func:`_undescribed`).
    """
    client = client_for("eks")
    failed: list[str] = []
    for page in _pages(client, "list_clusters"):
        for name in page.get("clusters", []):
            try:
                cluster = without_response_metadata(client.describe_cluster(name=name)).get("cluster")
            except BotoCoreError, ClientError:
                failed.append(name)
                continue
            if isinstance(cluster, dict) and cluster.get("arn"):
                # The description answered, so the subnet list in it is the whole list.
                yield with_edge_reads(cluster, {"resourcesVpcConfig": COMPLETE})
            else:
                failed.append(name)
    if failed:
        raise _undescribed("EKS clusters", failed)


def elasticsearch_domains_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Elasticsearch Service domains (regional): ``ListDomainNames`` names them and
    ``DescribeElasticsearchDomain`` returns each ``DomainStatus``.

    A domain that is listed but cannot be described is left out of the batch (it has no ARN to key it by).
    The domain's tags are read by the Resource Groups Tagging API sweep.
    """
    client = client_for("es")
    names = [d["DomainName"] for d in without_response_metadata(client.list_domain_names()).get("DomainNames", [])]
    failed: list[str] = []
    for name in names:
        try:
            status = without_response_metadata(client.describe_elasticsearch_domain(DomainName=name)).get("DomainStatus")
        except BotoCoreError, ClientError:
            failed.append(name)
            continue
        if isinstance(status, dict) and status.get("ARN"):
            yield with_edge_reads(status, {"VPCOptions": COMPLETE})
        else:
            failed.append(name)
    if failed:
        raise _undescribed("Elasticsearch domains", failed)


def network_firewalls_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Network Firewall firewalls (regional): ``ListFirewalls`` names them and ``DescribeFirewall``
    describes each. The firewall's tags ride inline in the description; its status is
    ``FirewallStatus.Status`` (``_status``). A firewall that is listed but cannot be described is left out.
    """
    client = client_for("network-firewall")
    failed: list[str] = []
    for page in _pages(client, "list_firewalls"):
        for entry in page.get("Firewalls", []):
            arn = entry.get("FirewallArn")
            if not arn:
                continue
            try:
                described = without_response_metadata(client.describe_firewall(FirewallArn=arn))
            except BotoCoreError, ClientError:
                failed.append(arn)
                continue
            firewall = described.get("Firewall")
            if isinstance(firewall, dict) and firewall.get("FirewallArn"):
                yield with_edge_reads(
                    {**firewall, "_status": (described.get("FirewallStatus") or {}).get("Status")},
                    {"SubnetMappings": COMPLETE},
                )
            else:
                failed.append(arn)
    if failed:
        raise _undescribed("Network Firewall firewalls", failed)


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
            tags_unread = False
            try:
                for tpage in _pages(client, "list_resource_tags", KeyId=key_id):
                    for tag in tpage.get("Tags", []):
                        tag_key = tag.get("TagKey")
                        if tag_key is not None:
                            tags[tag_key] = tag.get("TagValue") or ""
            except BotoCoreError, ClientError:
                tags, tags_unread = {}, True
            alias_names = aliases_by_key.get(key_id, [])
            display = alias_names[0].removeprefix("alias/") if alias_names else key_id
            yield {
                **meta,
                "_aliases": alias_names,
                "_tags": tags,
                "_tags_unread": tags_unread,
                "_display_name": display,
            }


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
            tags_unread = False
            try:
                tags = without_response_metadata(client.list_queue_tags(QueueUrl=url)).get("Tags") or {}
            except BotoCoreError, ClientError:
                tags_unread = True
            # KmsMasterKeyId is GetQueueAttributes(All)'s own answer; a queue whose attributes did
            # not answer is not yielded at all, so no claim is made for it (authority.py).
            yield with_edge_reads(
                {
                    **attrs,
                    "QueueUrl": url,
                    "_queue_name": attrs["QueueArn"].rsplit(":", 1)[-1],
                    "_tags": tags,
                    "_tags_unread": tags_unread,
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
        tags_unread = False
        try:
            for tpage in _pages(client, "list_tags", ResourceIdList=[arn]):
                for tag_set in tpage.get("ResourceTagList", []):
                    for tag in tag_set.get("TagsList", []) or []:
                        tag_key = tag.get("Key")
                        if tag_key is not None:
                            tags[tag_key] = tag.get("Value") or ""
        except BotoCoreError, ClientError:
            tags, tags_unread = {}, True
        # The three edge rules read DescribeTrails' own record of the trail (authority.py).
        yield with_edge_reads(
            {
                **trail,
                "_status": status,
                "_is_logging": bool(status.get("IsLogging")),
                "_tags": tags,
                "_tags_unread": tags_unread,
            },
            {"S3BucketName": COMPLETE, "CloudWatchLogsLogGroupArn": COMPLETE, "KmsKeyId": COMPLETE},
        )


def ecs_clusters_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """ECS clusters (regional), from the region's shared ECS walk (see :mod:`.ecs`)."""
    yield from shared_walk(session, client_for).clusters


def ecs_services_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """ECS services of every cluster in the region, from the shared ECS walk."""
    yield from shared_walk(session, client_for).services


def ecs_tasks_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Running and pending ECS tasks of every cluster in the region, from the shared ECS walk.

    The walk is the fan-out req-aws-collector-ecs names: ListClusters/DescribeClusters, then per cluster
    ListServices/DescribeServices and ListTasks/DescribeTasks with tags, each read to its end.
    """
    yield from shared_walk(session, client_for).tasks


def ecs_containers_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """The containers of those tasks, with the image and the digest ECS reports, from the shared ECS walk."""
    yield from shared_walk(session, client_for).containers


# Manifest custom_fn name -> callable.
_CUSTOM_FNS = {
    "aws_account_singleton": aws_account_singleton,
    "s3_buckets_hydrated": s3_buckets_hydrated,
    "route53_zones_with_alias_targets": route53_zones_with_alias_targets,
    "cloudfront_distributions_with_oac": cloudfront_distributions_with_oac,
    "dynamodb_tables_described": dynamodb_tables_described,
    "eventbridge_rules_with_targets": eventbridge_rules_with_targets,
    "iam_oidc_providers_described": iam_oidc_providers_described,
    "eks_clusters_described": eks_clusters_described,
    "dx_gateways_described": dx_gateways_described,
    "kms_aliases_described": kms_aliases_described,
    "cloudwatch_alarms_described": cloudwatch_alarms_described,
    "cloudwatch_composite_alarms_described": cloudwatch_composite_alarms_described,
    "cloudwatch_dashboards_described": cloudwatch_dashboards_described,
    "cloudwatch_metric_streams_described": cloudwatch_metric_streams_described,
    "logs_metric_filters_described": logs_metric_filters_described,
    "logs_subscription_filters_described": logs_subscription_filters_described,
    "logs_destinations_described": logs_destinations_described,
    "securityhub_action_targets_described": securityhub_action_targets_described,
    "securityhub_automation_rules_described": securityhub_automation_rules_described,
    "securityhub_finding_aggregators_described": securityhub_finding_aggregators_described,
    "securityhub_insights_described": securityhub_insights_described,
    "efs_access_points_described": efs_access_points_described,
    "efs_mount_targets_described": efs_mount_targets_described,
    "elbv2_listeners_described": elbv2_listeners_described,
    "backup_vaults_described": backup_vaults_described,
    "backup_plans_described": backup_plans_described,
    "backup_frameworks_described": backup_frameworks_described,
    "backup_legal_holds_described": backup_legal_holds_described,
    "cognito_identity_pools_described": cognito_identity_pools_described,
    "cognito_user_pool_clients_described": cognito_user_pool_clients_described,
    "cognito_identity_providers_described": cognito_identity_providers_described,
    "cognito_user_pool_groups_described": cognito_user_pool_groups_described,
    "cognito_user_pool_resource_servers_described": cognito_user_pool_resource_servers_described,
    "cognito_user_pool_domains_described": cognito_user_pool_domains_described,
    "guardduty_filters_described": guardduty_filters_described,
    "guardduty_ip_sets_described": guardduty_ip_sets_described,
    "guardduty_threat_intel_sets_described": guardduty_threat_intel_sets_described,
    "guardduty_publishing_destinations_described": guardduty_publishing_destinations_described,
    "guardduty_members_described": guardduty_members_described,
    "wafv2_web_acls_described": wafv2_web_acls_described,
    "wafv2_rule_groups_described": wafv2_rule_groups_described,
    "wafv2_ip_sets_described": wafv2_ip_sets_described,
    "wafv2_regex_pattern_sets_described": wafv2_regex_pattern_sets_described,
    "s3_access_points_described": s3_access_points_described,
    "sns_topics_described": sns_topics_described,
    "sns_subscriptions_listed": sns_subscriptions_listed,
    "eventbridge_event_buses_described": eventbridge_event_buses_described,
    "eventbridge_archives_described": eventbridge_archives_described,
    "eventbridge_connections_described": eventbridge_connections_described,
    "eventbridge_api_destinations_described": eventbridge_api_destinations_described,
    "lambda_function_urls_described": lambda_function_urls_described,
    "lambda_layer_versions_described": lambda_layer_versions_described,
    "lambda_code_signing_configs_described": lambda_code_signing_configs_described,
    "lambda_event_source_mappings_described": lambda_event_source_mappings_described,
    "identity_center_users_described": identity_center_users_described,
    "identity_center_applications_described": identity_center_applications_described,
    "identity_center_application_assignments_described": identity_center_application_assignments_described,
    "access_analyzer_archive_rules_described": access_analyzer_archive_rules_described,
    "cloudtrail_event_data_stores_described": cloudtrail_event_data_stores_described,
    "cloudtrail_channels_described": cloudtrail_channels_described,
    "cloudtrail_dashboards_described": cloudtrail_dashboards_described,
    "config_organization_rules_described": config_organization_rules_described,
    "config_organization_conformance_packs_described": config_organization_conformance_packs_described,
    "transit_gateways_described": transit_gateways_described,
    "codebuild_projects_described": codebuild_projects_described,
    "codepipeline_pipelines_described": codepipeline_pipelines_described,
    "transit_gateway_attachments_described": transit_gateway_attachments_described,
    "elasticsearch_domains_described": elasticsearch_domains_described,
    "network_firewalls_described": network_firewalls_described,
    "elbv2_albs_described": elbv2_albs_described,
    "elb_family_described": elb_family_described,
    "elbv2_target_groups_described": elbv2_target_groups_described,
    "iam_groups_listed": iam_groups_listed,
    "iam_instance_profiles_listed": iam_instance_profiles_listed,
    "iam_saml_providers_described": iam_saml_providers_described,
    "iam_server_certificates_listed": iam_server_certificates_listed,
    "iam_virtual_mfa_devices_listed": iam_virtual_mfa_devices_listed,
    "apigateway_http_apis_detailed": apigateway_http_apis_detailed,
    "cognito_user_pools_described": cognito_user_pools_described,
    "iam_roles_described": iam_roles_described,
    "iam_users_described": iam_users_described,
    "iam_customer_policies_listed": iam_customer_policies_listed,
    "kms_keys_described": kms_keys_described,
    "sqs_queues_described": sqs_queues_described,
    "cloudtrail_trails_described": cloudtrail_trails_described,
    "ecs_clusters_described": ecs_clusters_described,
    "ecs_services_described": ecs_services_described,
    "ecs_tasks_described": ecs_tasks_described,
    "ecs_containers_described": ecs_containers_described,
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
