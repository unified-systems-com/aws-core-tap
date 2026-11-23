"""Every aws_core model declares its event time (req-aws-core-models-5; tap req-grid-entity-event-time).

Core copies the field a model declares into ``Entity.event_start``/``event_end``/``event_precision`` and stamps the
kind as the row's ``time`` dimension. Every model is in exactly one of three states, and these tests hold them:

- declared: exactly the types below, each saying what it declares;
- ``NO_EVENT_TIME``: AWS states no time for the thing itself, and ``EVENT_TIME_REASON`` says why;
- undeclared, on purpose: AWS states a time, but in a place (inside ``configuration``) or a form (Lambda's
  ``+0000``) core cannot read yet, so it waits for a reader function (unified-systems-com/tap#1284), and
  ``EVENT_TIME_PENDING`` says where. Plugin validation reports exactly these, and nothing else;
- a time read from AWS reaches the spine as AWS stated it: a botocore datetime at second precision, and an Inspector
  finding as an interval from its first observation with no end.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from botocore.utils import parse_timestamp
from django.apps import apps

import tap_plugin.aws_core.models  # noqa: F401 — registers the models
from tap.plugin_testing import find_plugin_source_root
from tap_grid import event_time
from tap_grid.caller_context import CallerContext
from tap_grid.dimension_names import view
from tap_grid.event_time import NO_EVENT_TIME, Interval, declaration_problems
from tap_grid.models import Entity
from tap_grid.services import create_node
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    iam_saml_providers_described,
    lambda_layer_versions_described,
)
from tap_plugin.aws_core.collectors.boto3_collector.listing import ListingWalk
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
from tap_plugins.validate.service import validate_plugin

PLUGIN_ROOT = find_plugin_source_root(__file__)
# Not an account number: the ARNs below only need to be well formed for the field they fill.
ACCOUNT = "0000"

#: The types that declare an event time, and what each declares. Every other aws_core type states NO_EVENT_TIME.
DECLARED: dict[str, Interval] = {
    "aws_core__aws_access_analyzer": Interval(start="created_at", kind="created"),
    "aws_core__aws_access_analyzer_finding": Interval(start="created_at", kind="created"),
    "aws_core__aws_delegated_administration": Interval(start="delegation_enabled_at", kind="created"),
    "aws_core__aws_ecs_task": Interval(start="started_at", kind="occurred", end="stopped_at"),
    "aws_core__aws_guardduty_finding": Interval(start="created_at", kind="created"),
    "aws_core__aws_iam_access_key": Interval(start="create_date", kind="created"),
    "aws_core__aws_iam_root_user": Interval(start="created_at", kind="created"),
    "aws_core__aws_iam_saml_provider": Interval(start="created_at", kind="created", end="valid_until"),
    "aws_core__aws_iam_service_specific_credential": Interval(start="create_date", kind="created", end="expiration_date"),
    "aws_core__aws_iam_signing_certificate": Interval(start="upload_date", kind="created"),
    "aws_core__aws_iam_ssh_public_key": Interval(start="upload_date", kind="created"),
    "aws_core__aws_iam_server_certificate": Interval(start="upload_date", kind="created", end="expiration"),
    "aws_core__aws_identity_center_permission_set": Interval(start="created_at", kind="created"),
    "aws_core__aws_inspector2_finding": Interval(start="first_observed_at", kind="first_seen"),
    "aws_core__aws_inspector2_reachability_finding": Interval(start="first_observed_at", kind="first_seen"),
    "aws_core__aws_rds_db_cluster_snapshot": Interval(start="created_at", kind="created"),
    "aws_core__aws_rds_db_snapshot": Interval(start="created_at", kind="created"),
    "aws_core__aws_securityhub_finding": Interval(start="created_at", kind="created"),
    "aws_core__aws_securityhub_hub": Interval(start="subscribed_at", kind="created"),
}


#: A typed field left undeclared over its form (unified-systems-com/tap#1284): the field, and the form AWS sends it in,
#: which is not a FHIR dateTime and is stored as sent (core rule 22).
FORM_PENDING: dict[str, tuple[str, str]] = {
    "aws_core__aws_lambda_layer_version": ("created_date", "2018-11-27T15:10:45.123+0000"),
}


def _aws_models() -> list[type]:
    return [
        m
        for m in apps.get_app_config("aws_core").get_models()
        if getattr(m, "ENTITY_TYPE", "").startswith("aws_core__") and not m.__name__.startswith("Historical")
    ]


def _entry(entity_type: str) -> dict[str, Any]:
    return next(e for e in manifest_entries() if e["entity_type"] == entity_type)


def _create(entity_type: str, payload: dict[str, Any]) -> Entity:
    result = create_node(entity_type, payload, caller_context=CallerContext(batch_id=str(uuid.uuid7())))
    assert result.success, result.errors
    assert result.warnings == [], result.warnings
    return Entity.objects.get(pk=result.entity_id)


def _kind(row: Entity) -> Any:
    return view(row.dimensions).get(event_time.TIME_DIMENSION)


class _Client:
    """A fake boto3 client: each method answers with its canned value; a method nobody canned fails the test."""

    def __init__(self, **canned: Any) -> None:
        self._canned = canned

    def can_paginate(self, method: str) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        def call(**kwargs: Any) -> Any:
            if name not in self._canned:
                raise AssertionError(f"{name} was not expected")
            return self._canned[name]

        return call


# --- declarations -------------------------------------------------------------------------------------------------


def _pending() -> set[str]:
    return {m.ENTITY_TYPE for m in _aws_models() if "EVENT_TIME_PENDING" in m.__dict__}


@pytest.mark.django_db
def test_validation_reports_exactly_the_pending_types(monkeypatch: pytest.MonkeyPatch) -> None:
    """req-grid-entity-event-time-3: undeclared is a note, not a failure, until the switch is on."""
    monkeypatch.delenv(event_time.REQUIRE_DECLARATION_ENV, raising=False)
    result = validate_plugin(PLUGIN_ROOT, level="loads")
    check = next(c for c in result.checks if c.id == "event-time-declarations")
    undeclared = check.details["undeclared"]
    assert (set(undeclared), len(undeclared), check.details["required"]) == (_pending(), len(_pending()), False)
    assert check.status == "pass", check.messages


def test_every_type_is_declared_timeless_or_pending_and_only_one() -> None:
    models = _aws_models()
    assert len(models) == len({m.ENTITY_TYPE for m in models})
    declared = {
        m.ENTITY_TYPE: m.EVENT_TIME for m in models if m.__dict__.get("EVENT_TIME") not in (NO_EVENT_TIME, None)
    }
    assert declared == DECLARED
    for model in models:
        declaration = model.__dict__.get("EVENT_TIME")
        reason = model.__dict__.get("EVENT_TIME_REASON")
        pending = model.__dict__.get("EVENT_TIME_PENDING")
        assert declaration_problems(model) == [], model.ENTITY_TYPE
        if declaration is NO_EVENT_TIME:
            # A reason cites where it was read: the AWS call, the policy document, or the reference data.
            assert isinstance(reason, str) and len(reason) > 40 and ("(" in reason or "derives" in reason), (
                model.ENTITY_TYPE
            )
            assert pending is None, model.ENTITY_TYPE
        elif declaration is None:
            # Not decided, on purpose: the note names the AWS member and the core issue it waits on.
            assert isinstance(pending, str) and "(" in pending and "unified-systems-com/tap#1284" in pending, (
                model.ENTITY_TYPE
            )
            assert reason is None, model.ENTITY_TYPE
        else:
            assert reason is None and pending is None, model.ENTITY_TYPE


def test_a_typed_field_left_pending_over_its_form_is_one_the_reader_refuses() -> None:
    for entity_type, (field, example) in FORM_PENDING.items():
        model = next(m for m in _aws_models() if m.ENTITY_TYPE == entity_type)
        assert entity_type in _pending(), entity_type
        model._meta.get_field(field)
        with pytest.raises(event_time.Unreadable):
            event_time.read_value(example)


def test_no_pending_type_has_a_typed_field_that_would_serve_today() -> None:
    """A pending note says the time is in configuration, stored nowhere, or in a refused form; never on a typed field
    that could be declared now."""
    for model in _aws_models():
        pending = model.__dict__.get("EVENT_TIME_PENDING")
        if pending is not None and model.ENTITY_TYPE not in FORM_PENDING:
            assert "configuration" in pending or "no field of this model" in pending, model.ENTITY_TYPE


def test_no_declared_field_is_a_time_the_grid_or_the_collector_made() -> None:
    """Core rule 9 and 13: never a collection time, a last-seen time or a last-change time."""
    for entity_type, declaration in DECLARED.items():
        for name in event_time.declared_fields(declaration):
            assert not name.startswith(("last_", "updated", "collected", "observed")), (entity_type, name)


# --- the stored value keeps the source's form --------------------------------------------------------------------


def test_a_layer_versions_created_date_is_stored_as_lambda_sent_it() -> None:
    """Core rule 22: no conversion in the collector; the declaration waits for a declared source form instead."""
    arn = f"arn:aws:lambda:us-east-1:{ACCOUNT}:layer:deps"
    client = _Client(
        list_layers={"Layers": [{"LayerName": "deps", "LayerArn": arn}]},
        list_layer_versions={
            "LayerVersions": [{"LayerVersionArn": f"{arn}:3", "Version": 3, "CreatedDate": "2026-10-01T00:00:00.000+0000"}]
        },
    )
    (item,) = list(lambda_layer_versions_described(None, client_for=lambda service: client))
    node = project_item(_entry("aws_core__aws_lambda_layer_version"), item)
    assert node.fields["created_date"] == "2026-10-01T00:00:00.000+0000"


# --- on the spine -------------------------------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_creation_time_botocore_parsed_lands_in_event_start_at_second_precision() -> None:
    """GetSAMLProvider's CreateDate, as botocore parses it (an aware datetime), through the collector to the spine."""
    created = parse_timestamp("2026-03-04T05:06:07Z")
    expires = parse_timestamp("2027-03-04T05:06:07Z")
    assert created.tzinfo is not None
    provider = f"arn:aws:iam::{ACCOUNT}:saml-provider/Okta"
    iam = _Client(
        list_saml_providers={"SAMLProviderList": [{"Arn": provider, "CreateDate": created}]},
        get_saml_provider={"SAMLProviderUUID": "u-1", "CreateDate": created, "ValidUntil": expires},
    )
    (item,) = list(iam_saml_providers_described(None, client_for=lambda service: iam, walk=ListingWalk()))
    node = project_item(_entry("aws_core__aws_iam_saml_provider"), item)
    row = _create("aws_core__aws_iam_saml_provider", node.fields)
    assert row.event_start == datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
    assert row.event_precision == "second"
    # Rule 8: it holds from its creation until the expiration AWS states.
    assert row.event_end == datetime(2027, 3, 4, 5, 6, 7, tzinfo=UTC)
    assert _kind(row) == "created"


@pytest.mark.django_db
def test_an_inspector_finding_is_an_interval_from_its_first_observation() -> None:
    """The first observation starts it; the last is a last-seen time, which stays a typed field (core rule 14)."""
    row = _create(
        "aws_core__aws_inspector2_finding",
        {
            "name": "CVE-2026-0001 - openssl",
            "finding_arn": f"arn:aws:inspector2:us-east-1:{ACCOUNT}:finding/abc",
            "first_observed_at": "2026-01-02T03:04:05Z",
            "last_observed_at": "2026-02-03T04:05:06Z",
        },
    )
    assert (row.event_start, row.event_end, row.event_precision) == (
        datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        None,
        "second",
    )
    assert _kind(row) == "first_seen"


@pytest.mark.django_db
def test_a_stopped_ecs_task_is_the_interval_it_ran() -> None:
    row = _create(
        "aws_core__aws_ecs_task",
        {
            "name": "task",
            "task_arn": f"arn:aws:ecs:us-east-1:{ACCOUNT}:task/c/abc",
            "started_at": "2026-01-02T03:04:05Z",
            "stopped_at": "2026-01-02T04:00:00Z",
        },
    )
    assert (row.event_start, row.event_end, _kind(row)) == (
        datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        datetime(2026, 1, 2, 4, 0, 0, tzinfo=UTC),
        "occurred",
    )


@pytest.mark.django_db
def test_a_type_with_no_event_time_has_none_on_the_spine() -> None:
    row = _create("aws_core__aws_vpc", {"name": "main", "vpc_id": "vpc-1"})
    assert (row.event_start, row.event_end, row.event_precision, _kind(row)) == (None, None, None, None)
