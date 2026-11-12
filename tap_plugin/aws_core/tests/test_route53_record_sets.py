"""Route 53 record sets as nodes (aws-core-tap#220): the run's one walk of every zone, the per-zone surfaces it
records, containment, and the record set falsifier (``req-aws-collector-lb-topology-5``).

Surfaces are checked on the walk with a faked Route 53 client; the falsifier runs core's four proof cases
(``req-grid-reconcile-falsifier-6``) against real grid rows and a faked ``ListResourceRecordSets``.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector.listing import surface_statement
from tap_plugin.aws_core.collectors.boto3_collector.route53_records import (
    CONTAINMENT_SURFACES,
    HOLDS_RECORD_SET,
    RECORD_SET_TYPE,
    REPLACED_ZONE_SCOPE,
    ZONE_TYPE,
    record_set_key,
    shared_walk,
    walk_of,
    walk_zones,
    withhold_unreplaced_zone_routes,
)
from tap_plugin.aws_core.falsifiers import Route53RecordSetFalsifier

from tap_grid.falsifier_testing import CASE_DROPPED, CASE_FORBIDDEN, CASE_PRESENT, CASE_REIDENTIFIED, run_four_cases
from tap_grid.falsifiers import DROPPED_FROM_OBSERVATION, PRESENT_AT_PROBE, UNDETERMINED, Candidate, FalsifyContext
from tap_grid.services import create_node, get_node

ACCOUNT_ID = "111122223333"
REGION = "us-east-1"


class _FakeRoute53:
    """Zones ``a`` and ``b`` by default; ``records`` per zone id, a ``ClientError`` code to fail a zone's listing, or
    ``"short"`` for a listing whose last page still says more."""

    def __init__(self, records: dict[str, Any] | None = None, zones: list[str] | None = None) -> None:
        self.zones = zones if zones is not None else ["/hostedzone/ZA", "/hostedzone/ZB"]
        self.records = records or {}
        self.calls = 0

    def can_paginate(self, _m: str) -> bool:
        return False

    def list_hosted_zones(self, **_kw: Any) -> Any:
        self.calls += 1
        return {"HostedZones": [{"Id": z, "Name": f"{z[-2:].lower()}.example.com."} for z in self.zones]}

    def list_resource_record_sets(self, HostedZoneId: str, **_kw: Any) -> Any:
        answer = self.records.get(HostedZoneId, [])
        if answer == "short":
            return {"ResourceRecordSets": [{"Name": "x.", "Type": "A"}], "IsTruncated": True, "NextRecordName": "y."}
        if isinstance(answer, str):
            raise ClientError({"Error": {"Code": answer, "Message": "no"}}, "ListResourceRecordSets")
        return {"ResourceRecordSets": answer}


def _surfaces(walk: Any) -> dict[str, dict[str, Any]]:
    return {
        listing.zone_id: surface_statement(listing.walk, relation=listing.relation, edge_type=listing.edge_type, subject="s", applied_batches=[])
        for listing in walk.listings
    }


class TestContainment:
    @pytest.mark.spec("req-aws-core-contained-type-triple-1", "req-aws-collector-lb-topology-5")
    def test_reader_surfaces_mirror_model_containment(self) -> None:
        from tap_grid.registry import get_model_class

        for entity_type, edges in CONTAINMENT_SURFACES.items():
            assert tuple(get_model_class(entity_type).CONTAINMENT_EDGES) == edges, entity_type
        assert CONTAINMENT_SURFACES == {ZONE_TYPE: (HOLDS_RECORD_SET,)}


@pytest.mark.spec("req-aws-collector-lb-topology-5")
class TestWalk:
    def test_every_zone_has_a_surface_and_a_complete_listing_counts_its_records(self) -> None:
        r53 = _FakeRoute53({"/hostedzone/ZA": [{"Name": "a.", "Type": "A"}, {"Name": "b.", "Type": "TXT"}]})
        walk = walk_zones(r53)
        surfaces = _surfaces(walk)
        assert set(surfaces) == {"/hostedzone/ZA", "/hostedzone/ZB"}
        assert surfaces["/hostedzone/ZA"]["enumeration_complete"] is True and surfaces["/hostedzone/ZA"]["count_observed"] == 2
        assert surfaces["/hostedzone/ZB"]["enumeration_complete"] is True and surfaces["/hostedzone/ZB"]["count_observed"] == 0
        assert {listing.relation for listing in walk.listings} == {"route53_zone.record_sets"}
        assert [record["Name"] for _zone, record in walk.records] == ["a.", "b."]

    def test_a_denied_listing_is_recorded_incomplete_and_contributes_no_records(self) -> None:
        r53 = _FakeRoute53({"/hostedzone/ZA": "AccessDenied", "/hostedzone/ZB": [{"Name": "b.", "Type": "A"}]})
        walk = walk_zones(r53)
        surface = _surfaces(walk)["/hostedzone/ZA"]
        assert surface["enumeration_complete"] is False and surface["scope_authorized"] is False
        assert [zone["Id"] for zone, _record in walk.records] == ["/hostedzone/ZB"]

    def test_a_short_listing_is_incomplete_and_contributes_no_records(self) -> None:
        walk = walk_zones(_FakeRoute53({"/hostedzone/ZA": "short"}))
        surface = _surfaces(walk)["/hostedzone/ZA"]
        assert surface["enumeration_complete"] is False and surface["admitted"] is False
        assert [zone["Id"] for zone, _record in walk.records] == []

    def test_the_walk_is_made_once_per_session(self) -> None:
        class _Session:
            pass

        session, r53 = _Session(), _FakeRoute53()
        assert shared_walk(session, r53) is shared_walk(session, r53)
        assert r53.calls == 1 and walk_of(session) is not None

    def test_an_unprojected_walk_licenses_no_retirement(self) -> None:
        walk = walk_zones(_FakeRoute53({"/hostedzone/ZA": [{"Name": "a.", "Type": "A"}]}))
        surfaces = {
            listing.zone_id: surface_statement(listing.walk, relation=listing.relation, edge_type=listing.edge_type, subject="s", applied_batches=[])
            for listing in walk.surface_listings()
        }
        assert all(surface["admitted"] is False for surface in surfaces.values())
        assert surfaces["/hostedzone/ZA"]["reasons"]["admitted"].startswith("collection_partial")

    def test_a_projected_walk_keeps_its_complete_surfaces(self) -> None:
        walk = walk_zones(_FakeRoute53({"/hostedzone/ZA": [{"Name": "a.", "Type": "A"}]}))
        walk.projected = True
        assert all(listing.walk.admitted for listing in walk.surface_listings())

    def test_a_zone_whose_records_did_not_all_resolve_or_reach_the_batch_keeps_its_old_routes(self) -> None:
        walk = walk_zones(_FakeRoute53({"/hostedzone/ZA": [{"Name": "a.", "Type": "A"}], "/hostedzone/ZB": [{"Name": "b.", "Type": "A"}]}))

        def judged() -> list[Any]:
            return [
                ({"entity": {"entity_type": ZONE_TYPE}, "node": {"hosted_zone_id": zone}}, {REPLACED_ZONE_SCOPE: "complete"})
                for zone in ("/hostedzone/ZA", "/hostedzone/ZB")
            ]

        def reads(rows: list[Any]) -> list[str]:
            return [r[REPLACED_ZONE_SCOPE] for _envelope, r in rows]

        # The reader did not finish: no zone's old routes are claimed.
        rows = judged()
        assert withhold_unreplaced_zone_routes(rows, walk) == 2 and reads(rows) == ["failed", "failed"]
        # The reader finished, but a record set in ZA resolved only partly: ZA keeps its old routes, ZB is claimed.
        walk.projected, walk.unresolved = True, {"/hostedzone/ZA"}
        rows = judged()
        assert withhold_unreplaced_zone_routes(rows, walk) == 1 and reads(rows) == ["failed", "complete"]
        # No walk at all: nothing is claimed.
        rows = judged()
        withhold_unreplaced_zone_routes(rows, None)
        assert reads(rows) == ["failed", "failed"]

    def test_a_walk_that_raised_is_kept_and_has_no_listings(self) -> None:
        class _Denied(_FakeRoute53):
            def list_hosted_zones(self, **_kw: Any) -> Any:
                self.calls += 1
                raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "ListHostedZones")

        class _Session:
            pass

        session, r53 = _Session(), _Denied()
        for _ in range(2):
            with pytest.raises(ClientError):
                shared_walk(session, r53)
        assert r53.calls == 1 and walk_of(session) is None


# --- the falsifier ----------------------------------------------------------------------------------------------


class _Probe:
    """A faked ``route53`` client: ``list_resource_record_sets`` answers with the zone's records from the start
    name, type and identifier on, sorted as Route 53 sorts them; ``denied`` and ``gone`` zones raise."""

    def __init__(self) -> None:
        self.records: dict[str, list[dict[str, Any]]] = {}
        self.denied: set[str] = set()
        self.gone: set[str] = set()

    def list_resource_record_sets(self, HostedZoneId: str, StartRecordName: str, StartRecordType: str, MaxItems: str, StartRecordIdentifier: str = "") -> Any:
        if HostedZoneId in self.denied:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "ListResourceRecordSets")
        if HostedZoneId in self.gone:
            raise ClientError({"Error": {"Code": "NoSuchHostedZone", "Message": "no"}}, "ListResourceRecordSets")
        start = (StartRecordName.lower(), StartRecordType, StartRecordIdentifier)
        rows = sorted(self.records.get(HostedZoneId, []), key=lambda r: (r["Name"].lower(), r["Type"], r.get("SetIdentifier", "")))
        after = [r for r in rows if (r["Name"].lower(), r["Type"], r.get("SetIdentifier", "")) >= start]
        return {"ResourceRecordSets": after[: int(MaxItems)]}


class _Session:
    def __init__(self, r53: _Probe) -> None:
        self._r53 = r53

    def client(self, service: str, region_name: str | None = None) -> Any:
        assert service == "route53" and region_name == REGION, (service, region_name)
        return self._r53


def _record_row(zone: str, name: str, record_type: str = "A", set_identifier: str | None = None, *, key_name: str | None = None) -> uuid.UUID:
    record = {"Name": key_name or name, "Type": record_type, "SetIdentifier": set_identifier}
    fields = {
        "name": name,
        "record_set_key": record_set_key(f"/hostedzone/{zone}", record),
        "hosted_zone_id": f"/hostedzone/{zone}",
        "record_name": name,
        "record_type": record_type,
        "set_identifier": set_identifier,
    }
    result = create_node(RECORD_SET_TYPE, fields)
    assert result.success, result.errors
    entity_id = uuid.UUID(str(result.entity_id))
    row = get_node(entity_id)
    row.entity.dimensions = {"aws.account": ACCOUNT_ID, "aws.region": REGION}
    row.entity.save(update_fields=["dimensions"])
    return entity_id


def _candidate(entity_id: uuid.UUID) -> Candidate:
    return Candidate(
        entity_id=entity_id, entity_type=RECORD_SET_TYPE, reason="dropped_from_observation", surface=0, relation="fixture",
        subject=None, edge_type=None, parent=None, interval_first=None,
    )


def _judge(probe: _Probe, entity_id: uuid.UUID) -> Any:
    falsifier = Route53RecordSetFalsifier(session=_Session(probe), account_id=ACCOUNT_ID)
    (verdict,) = falsifier.batch_falsify([_candidate(entity_id)], FalsifyContext(batch_id=str(uuid.uuid4()), statement=None))
    return verdict


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-lb-topology-5")
class TestRecordSetFalsifier:
    @pytest.mark.spec("req-grid-reconcile-falsifier-6")
    def test_four_cases(self) -> None:
        probe = _Probe()
        probe.records["/hostedzone/ZA"] = [{"Name": "present.example.com.", "Type": "A"}, {"Name": "reborn.example.com.", "Type": "A"}]
        probe.denied.add("/hostedzone/ZLOCKED")
        cases = {
            CASE_PRESENT: _candidate(_record_row("ZA", "present.example.com.")),
            CASE_DROPPED: _candidate(_record_row("ZA", "dropped.example.com.")),
            CASE_FORBIDDEN: _candidate(_record_row("ZLOCKED", "x.example.com.")),
            # The same record set written under another spelling of its name: Route 53 keys it by the name it
            # returns, so the probe finds it under another key.
            CASE_REIDENTIFIED: _candidate(_record_row("ZA", "reborn.example.com.", key_name="Reborn.Example.com.")),
        }
        run_four_cases(Route53RecordSetFalsifier(session=_Session(probe), account_id=ACCOUNT_ID), cases, FalsifyContext(batch_id=str(uuid.uuid4()), statement=None))

    def test_a_weighted_record_is_found_by_its_set_identifier(self) -> None:
        probe = _Probe()
        probe.records["/hostedzone/ZA"] = [{"Name": "w.example.com.", "Type": "A", "SetIdentifier": "blue"}, {"Name": "w.example.com.", "Type": "A", "SetIdentifier": "green"}]
        assert _judge(probe, _record_row("ZA", "w.example.com.", set_identifier="green")).verdict == PRESENT_AT_PROBE
        assert _judge(probe, _record_row("ZA", "w.example.com.", set_identifier="red")).verdict == DROPPED_FROM_OBSERVATION

    def test_a_zone_that_is_gone_is_undetermined_not_absence(self) -> None:
        probe = _Probe()
        probe.gone.add("/hostedzone/ZGONE")
        assert _judge(probe, _record_row("ZGONE", "a.example.com.")).verdict == UNDETERMINED
