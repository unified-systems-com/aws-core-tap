"""Route 53 record sets: one walk of every hosted zone's record sets, shared by the run (aws-core-tap#220).

Every record set ``ListResourceRecordSets`` returns becomes an ``aws_route53_record_set`` node contained by its
zone (``HOLDS_RECORD_SET``). A zone's listing is walked to its end once per run; the walk is what the record-set
reader projects and what the collector turns into one completeness surface per zone after import, so a record set
a complete listing of its zone no longer names is a retirement candidate.

Spec: ``specs/spec-aws-core-collector-v0.md`` (``req-aws-collector-lb-topology-5``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from weakref import WeakKeyDictionary

from botocore.exceptions import BotoCoreError, ClientError

from .envelope import without_response_metadata
from .listing import ListingWalk, page_says_more

ZONE_TYPE = "aws_core__aws_route53_zone"
RECORD_SET_TYPE = "aws_core__aws_route53_record_set"
HOLDS_RECORD_SET = "HOLDS_RECORD_SET__aws_core"

#: The parent type -> the containment edges it records a surface for (``req-aws-core-contained-type-triple``).
CONTAINMENT_SURFACES: dict[str, tuple[str, ...]] = {ZONE_TYPE: (HOLDS_RECORD_SET,)}
RELATION = "route53_zone.record_sets"


def bare_zone_id(zone_id: str) -> str:
    """The zone id without its ``/hostedzone/`` prefix, as ``ListTagsForResource`` and the record set key use it."""
    return zone_id.rsplit("/", 1)[-1]


def record_set_key(zone_id: str, record: dict[str, Any]) -> str:
    """A record set's natural key: ``<zone id>/<name>/<type>/<set identifier>``, the set identifier empty for a
    simple record. Route 53 addresses a record set by exactly these four (``ChangeResourceRecordSets``)."""
    return f"{bare_zone_id(zone_id)}/{record.get('Name', '')}/{record.get('Type', '')}/{record.get('SetIdentifier') or ''}"


@dataclass
class ZoneListing:
    """One zone's record set listing: what the collector turns into the zone's completeness surface."""

    zone_id: str
    walk: ListingWalk
    parent_type: str = ZONE_TYPE
    edge_type: str = HOLDS_RECORD_SET
    relation: str = RELATION

    @property
    def parent_key(self) -> str:
        return self.zone_id


@dataclass
class RecordWalk:
    """Every hosted zone and the record sets each listed, for the run's one Route 53 read."""

    zones: list[dict[str, Any]] = field(default_factory=list)
    #: ``(zone, record set)`` for every record set of a zone whose listing reached its end.
    records: list[tuple[dict[str, Any], dict[str, Any]]] = field(default_factory=list)
    listings: list[ZoneListing] = field(default_factory=list)
    #: The record set reader yielded every record set to the end. Until it has, no zone's surface may say its
    #: record sets reached the batch: a reader that raised partway imported none of the ones it missed.
    projected: bool = False

    def surface_listings(self) -> list[ZoneListing]:
        """The listings to record as the zones' surfaces. When the reader did not finish, every listing says its
        record sets were not all carried to the batch, so none of them licenses retiring a record set the batch
        is missing (aws-core-tap PR 223 review)."""
        if not self.projected:
            for listing in self.listings:
                listing.walk.drop("the record set reader did not finish; its record sets were not all carried")
        return self.listings


def _pages(client: Any, method: str, **kwargs: Any) -> list[dict[str, Any]]:
    if client.can_paginate(method):
        return [without_response_metadata(p) for p in client.get_paginator(method).paginate(**kwargs)]
    return [without_response_metadata(getattr(client, method)(**kwargs))]


def walk_zones(client: Any) -> RecordWalk:
    """List every hosted zone, then every zone's record sets to the end.

    A zone whose record listing fails or stops short keeps its walk (so its surface says why it is not an answer)
    and contributes no record sets: a partial listing would make the ones it missed look absent. The zone listing
    itself failing raises, as every other source does.
    """
    walk = RecordWalk()
    walk.zones = [zone for page in _pages(client, "list_hosted_zones") for zone in page.get("HostedZones", [])]
    for zone in walk.zones:
        zone_id = str(zone.get("Id") or "")
        if not zone_id:
            continue
        listing = ListingWalk()
        try:
            pages = _pages(client, "list_resource_record_sets", HostedZoneId=zone_id)
        except (BotoCoreError, ClientError) as exc:
            listing.fail(exc)
        else:
            records = [r for page in pages for r in page.get("ResourceRecordSets", [])]
            if pages and page_says_more(pages[-1]):
                listing.stopped_short(len(records), "ListResourceRecordSets: the final page still reports more")
                listing.admitted = False
                listing.reasons["admitted"] = "walk_capped: the listing stopped short, so none of it was processed"
            else:
                listing.reached_end(len(records))
                walk.records.extend((zone, record) for record in records)
        walk.listings.append(ZoneListing(zone_id=zone_id, walk=listing))
    return walk


#: One walk per session: the zone reader and the record set reader share one set of Route 53 calls. A walk that
#: raised is kept too, so a denied ``ListHostedZones`` is not retried by the second reader.
_WALKS: WeakKeyDictionary[Any, RecordWalk | BaseException] = WeakKeyDictionary()


def walk_of(session: Any) -> RecordWalk | None:
    """The run's completed walk, or None when none was made or it raised (a zone that was not observed has no
    surface to record)."""
    try:
        cached = _WALKS.get(session)
    except TypeError:
        return None
    return cached if isinstance(cached, RecordWalk) else None


def shared_walk(session: Any, client: Any) -> RecordWalk:
    """The run's :class:`RecordWalk`, made once per session (a session is the run's own and never reused)."""
    try:
        cached = _WALKS.get(session) if session is not None else None
    except TypeError:  # a session that cannot be weakly referenced: no sharing, still correct
        session = None
        cached = None
    if isinstance(cached, BaseException):
        raise cached
    if cached is not None:
        return cached
    try:
        walk = walk_zones(client)
    except (BotoCoreError, ClientError) as exc:
        if session is not None:
            _WALKS[session] = exc
        raise
    if session is not None:
        _WALKS[session] = walk
    return walk
