"""AWS Config as a second source of evidence that an object is gone (prototype).

A retirement candidate is a child the grid holds that this run's listing did not name. The
per-type falsifiers in ``falsifiers.py`` each call the one service API that owns the object. Most
types have no such class, and writing ~900 of them is the cost this module sets out to avoid: AWS
Config already records a ``ResourceDeleted`` configuration item for every type it supports, so one
class driven by a data file (``config_falsifier_types.json``) can answer for all of them.

**Config can falsify, never confirm.** Config trails the live account by minutes, and a recorder can
be off or scoped to some types. So the only thing this falsifier ever concludes from Config is
"gone": the latest configuration item of the object is ``ResourceDeleted`` (or
``ResourceDeletedNotRecorded``). Every other outcome is ``UNDETERMINED``: a Config item that is not
deleted is not evidence the object exists, because Config may not have caught up. It never answers
``PRESENT_AT_PROBE``. The reason is ``scope_unknown`` when Config cannot speak to the object (no
recorder, type not recorded, id never discovered, a different account, region or ARN on the item),
and ``forbidden``, ``rate_limited`` or ``errored`` for a failed call.

**Recreated objects.** If the latest item is not deleted but an earlier item in the page is, the
object was deleted and has come back; the verdict names that and nothing is retired.

**Where the region comes from.** From the row's own ``aws_region`` dimension for a regional type
(a name is only unique within a region, so a deletion recorded in another region says nothing). For
a global type (IAM), from the ARN's partition, through ``iam_endpoint_region`` (the lesson of
aws-core-tap#164); the recorder there must include global resource types or the type is refused, and
Config files such an item under the region ``global``. For a globally unique name whose item Config
files under the object's own region (an S3 bucket), every enabled region is asked and the answers
are combined: Config showing it alive in any region means it is not retired.

**Evidence the mapping rests on.** ``config_falsifier_types.json`` records, per type, the Config
resource type and how its id is derived. They were read from the GovCloud test account on
2026-11-01 (``list_discovered_resources`` with deleted resources included, and
``get_resource_config_history`` for the seed resources). ``BatchGetResourceConfig`` returns nothing
for a deleted object, so it cannot be used; the history call is.

Not covered, by design: the object's relationships. Config's VPC item lists ``Contains Subnet`` and
``Contains SecurityGroup``; reading them for cascade is left to a separate piece of work.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from tap_grid.falsifiers import DROPPED_FROM_OBSERVATION, Candidate, Expected, Probe, Verdict
from tap_plugin.aws_core.collectors.boto3_collector.iam_trust import iam_endpoint_region
from tap_plugin.aws_core.falsifiers import (
    ProbeSession,
    _AwsFalsifier,
    _dimensions_of,
    _finish,
    _row_of,
    _undetermined,
    error_code_of,
    probe_status_of,
)

logger = logging.getLogger(__name__)

TYPES_PATH = Path(__file__).with_name("config_falsifier_types.json")

#: The configuration item statuses that say the object is gone.
DELETED_STATUSES = frozenset({"ResourceDeleted", "ResourceDeletedNotRecorded"})

#: How many history items are read: enough to see a deletion that a recreation followed.
HISTORY_LIMIT = 10

_REGION = re.compile(r"^[a-z]{2}(?:-gov|-iso[a-z]?)?-[a-z]+-\d+$")
_CONFIG_TYPE = re.compile(r"^AWS::[A-Za-z0-9]+::[A-Za-z0-9]+$")
_ID_SOURCES = frozenset({"field", "arn_tail", "name_lookup"})
_SCOPES = frozenset({"regional", "global_home", "global_name"})

#: Config error codes that mean "Config cannot speak to this object", not "the call failed".
_CANNOT_SPEAK_CODES = frozenset(
    {
        "ResourceNotDiscoveredException",
        "NoAvailableConfigurationRecorderException",
        "ValidationException",
        "InvalidParameterValueException",
        "InvalidResourceTypeException",
    }
)


class ConfigMappingError(ValueError):
    """The mapping file is malformed; refused at load, never guessed at."""


def _validated(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict) or not isinstance(raw.get("types"), dict) or not raw["types"]:
        raise ConfigMappingError("config_falsifier_types.json needs a non-empty 'types' object")
    for slug, spec in raw["types"].items():
        if not isinstance(spec, dict):
            raise ConfigMappingError(f"{slug}: entry is not an object")
        if not str(spec.get("description", "")).strip():
            raise ConfigMappingError(f"{slug}: every entry carries a description")
        if not _CONFIG_TYPE.match(str(spec.get("config_type", ""))):
            raise ConfigMappingError(f"{slug}: config_type {spec.get('config_type')!r} is not an AWS::Service::Type")
        if spec.get("scope") not in _SCOPES:
            raise ConfigMappingError(f"{slug}: scope must be one of {sorted(_SCOPES)}")
        source = spec.get("id")
        if not isinstance(source, dict) or source.get("from") not in _ID_SOURCES:
            raise ConfigMappingError(f"{slug}: id.from must be one of {sorted(_ID_SOURCES)}")
        if source["from"] in {"field", "name_lookup"} and not source.get("field"):
            raise ConfigMappingError(f"{slug}: id.field is required for {source['from']}")
        if source["from"] == "arn_tail" and not (source.get("marker") and spec.get("arn_field")):
            raise ConfigMappingError(f"{slug}: arn_tail needs id.marker and arn_field")
        if source["from"] == "name_lookup" and not spec.get("arn_field"):
            raise ConfigMappingError(f"{slug}: name_lookup needs arn_field")
        if spec["scope"] == "global_home" and not spec.get("arn_field"):
            raise ConfigMappingError(f"{slug}: a global_home type needs arn_field to find its partition")
    return dict(raw["types"])


@cache
def config_types() -> dict[str, dict[str, Any]]:
    """The validated slug -> mapping table."""
    return _validated(json.loads(TYPES_PATH.read_text(encoding="utf-8")))


def _status_of(exc: Exception) -> str:
    """The probe status for a failed Config call. Never ``not_found``: a Config error does not
    show an object is gone, only that Config could not say."""
    if isinstance(exc, ClientError) and error_code_of(exc) in _CANNOT_SPEAK_CODES:
        return "scope_unknown"
    status = probe_status_of(exc)
    return "errored" if status == "not_found" else status


class ConfigHistoryFalsifier(_AwsFalsifier):
    """``config:GetResourceConfigHistory`` for the object, read as gone only on a deleted item.

    One instance serves one entity type or many: the type comes from the candidate, and the
    mapping from ``config_falsifier_types.json``.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._recorder_cache: dict[tuple[str, str, bool], tuple[str, str] | None] = {}

    def _begin_run(self, batch_id: str) -> None:
        if batch_id != self._batch_id:
            self._recorder_cache = {}
        super()._begin_run(batch_id)

    # -- the row: id, region -------------------------------------------------------------

    @staticmethod
    def _derive_id(spec: dict[str, Any], row: Any) -> tuple[str | None, str]:
        """``(config id, why not)``. For ``name_lookup`` with no stored id the id is ``None`` and
        the reason is empty: the caller asks Config for it by name."""
        source = spec["id"]
        if source["from"] == "field" or source["from"] == "name_lookup":
            value = str(getattr(row, source["field"], "") or "")
            if value:
                return value, ""
            if source["from"] == "name_lookup":
                return None, ""
            return None, f"the grid row holds no {source['field']} to ask Config about"
        arn = str(getattr(row, spec["arn_field"], "") or "")
        marker = source["marker"]
        if marker not in arn:
            return None, f"the ARN {arn!r} does not contain {marker!r}, so no Config id can be derived from it"
        tail = arn.split(marker, 1)[1]
        if not tail or (source.get("single_segment") and "/" in tail):
            return None, (
                f"the ARN tail {tail!r} is empty or has more than one segment; the Config id for that shape "
                "was not established"
            )
        return tail, ""

    def _regions_of_spec(
        self, session: ProbeSession, spec: dict[str, Any], dimensions: dict[str, str], arn: str
    ) -> tuple[list[str], str]:
        """``(regions to ask Config in, why not)``.

        ``regional``: the row's own region only. ``global_home``: the ARN's partition endpoint, where
        the recorder holds global types. ``global_name``: names are unique across regions (an S3
        bucket) but Config files the item under the object's own region, which the row does not
        hold, so every region the account has enabled is asked and the answers are combined.
        """
        if spec["scope"] == "global_home":
            if not arn:
                return [], "the grid holds no ARN, so the partition's Config region cannot be derived"
            return [iam_endpoint_region(arn)], ""
        if spec["scope"] == "global_name":
            regions = self._sweep_regions(session)
            return regions, ("" if regions else "the account's enabled regions could not be listed")
        region = dimensions.get("aws_region") or ""
        if not _REGION.match(region):
            return [], (
                f"the grid records no real region for this object (aws_region={region!r}); a deletion Config "
                "recorded in another region says nothing about this one"
            )
        return [region], ""

    # -- the recorder --------------------------------------------------------------------

    def _recorder_problem(self, client: Any, region: str, config_type: str, is_global: bool) -> tuple[str, str] | None:
        """``(reason, note)`` when Config is not recording ``config_type`` in ``region``, else None."""
        key = (region, config_type, is_global)
        if key not in self._recorder_cache:
            self._recorder_cache[key] = self._read_recorder(client, region, config_type, is_global)
        return self._recorder_cache[key]

    @staticmethod
    def _read_recorder(client: Any, region: str, config_type: str, is_global: bool) -> tuple[str, str] | None:
        recorders = client.describe_configuration_recorders().get("ConfigurationRecorders") or []
        statuses = client.describe_configuration_recorder_status().get("ConfigurationRecordersStatus") or []
        if not recorders:
            return "scope_unknown", f"AWS Config has no configuration recorder in {region}"
        recording = {
            s.get("name") for s in statuses if s.get("recording") and str(s.get("lastStatus") or "") != "FAILURE"
        }
        if not recording:
            return "scope_unknown", f"no AWS Config recorder in {region} is recording (or the last delivery failed)"
        for recorder in recorders:
            if recorder.get("name") not in recording:
                continue
            group = recorder.get("recordingGroup") or {}
            strategy = (group.get("recordingStrategy") or {}).get("useOnly")
            if strategy == "EXCLUSION_BY_RESOURCE_TYPES":
                excluded = (group.get("exclusionByResourceTypes") or {}).get("resourceTypes") or []
                covered = config_type not in excluded
            elif group.get("allSupported") or strategy == "ALL_SUPPORTED_RESOURCE_TYPES":
                # "all supported" leaves global types (IAM) to the recorder in the region that opts in.
                covered = (not is_global) or bool(group.get("includeGlobalResourceTypes"))
            else:
                covered = config_type in (group.get("resourceTypes") or [])
            if covered:
                return None
        return "scope_unknown", f"the AWS Config recorder in {region} does not record {config_type}"

    # -- the verdict ---------------------------------------------------------------------

    def judge(self, session: ProbeSession, account_id: str, candidate: Candidate) -> Verdict:
        spec = config_types().get(candidate.entity_type)
        if spec is None:
            return _undetermined(candidate, "scope_unknown", f"no AWS Config mapping exists for {candidate.entity_type}")
        row = _row_of(candidate.entity_id)
        if row is None:
            return _undetermined(candidate, "errored", "the grid row could not be read")
        dimensions = _dimensions_of(row)
        expected_account = dimensions.get("aws_account") or None
        scoped = self._scope_check(candidate, account_id, expected_account)
        if scoped is not None:
            return scoped
        arn = str(getattr(row, spec["arn_field"], "") or "") if spec.get("arn_field") else ""
        regions, why = self._regions_of_spec(session, spec, dimensions, arn)
        if not regions:
            return _undetermined(candidate, "scope_unknown", why)
        config_id, why = self._derive_id(spec, row)
        name = str(getattr(row, "name", "") or "")
        if config_id is None and not why and not name:
            why = "the grid row holds neither an id nor a name to ask Config about"
        if why:
            return _undetermined(candidate, "scope_unknown", why)
        expected = Expected(source_id=arn or config_id or name, owner=expected_account, name=name or None)
        row_created = _row_created_at(candidate)
        outcomes = [
            self._judge_in_region(
                session, candidate, expected, spec, region, config_id, name, expected_account, arn, row_created
            )
            for region in regions
        ]
        return self._combine(outcomes)

    @staticmethod
    def _combine(outcomes: list[tuple[Verdict, bool]]) -> Verdict:
        """One verdict from the per-region answers. An object Config shows alive (or recreated) in
        any region is not retired; otherwise a deletion in any region retires it; otherwise the
        most informative refusal stands."""
        for verdict, live in outcomes:
            if live:
                return verdict
        for verdict, _ in outcomes:
            if verdict.verdict == DROPPED_FROM_OBSERVATION:
                return verdict
        for verdict, _ in outcomes:
            if verdict.reason != "scope_unknown":
                return verdict
        return outcomes[0][0]

    def _judge_in_region(
        self,
        session: ProbeSession,
        candidate: Candidate,
        expected: Expected,
        spec: dict[str, Any],
        region: str,
        config_id: str | None,
        name: str,
        expected_account: str | None,
        arn: str,
        row_created: Any = None,
    ) -> tuple[Verdict, bool]:
        """``(verdict, config_shows_it_alive)`` for one region."""
        try:
            client = session.client("config", region_name=region)
            problem = self._recorder_problem(client, region, spec["config_type"], bool(spec.get("global")))
            if problem is not None:
                return _undetermined(candidate, problem[0], problem[1]), False
            if config_id is None:
                config_id, why = self._lookup_id_by_name(client, spec, name)
                if config_id is None:
                    return _undetermined(candidate, "scope_unknown", why), "in use" in why
            history = client.get_resource_config_history(
                resourceType=spec["config_type"],
                resourceId=config_id,
                limit=HISTORY_LIMIT,
                chronologicalOrder="Reverse",
            )
        except ClientError as exc:
            return _undetermined(candidate, _status_of(exc), f"AWS Config in {region}: {error_code_of(exc)}"), False
        except BotoCoreError as exc:
            return _undetermined(candidate, "errored", str(exc)), False
        return self._read_history(
            candidate, expected, spec, region, expected_account, arn, history.get("configurationItems") or [], row_created
        )

    @staticmethod
    def _lookup_id_by_name(client: Any, spec: dict[str, Any], name: str) -> tuple[str | None, str]:
        """The Config id for an IAM object whose id the grid does not hold: by name, deleted
        included. A live object of the same name means the name is in use, so nothing is gone."""
        found = client.list_discovered_resources(
            resourceType=spec["config_type"], resourceName=name, includeDeletedResources=True
        ).get("resourceIdentifiers") or []
        same = [i for i in found if i.get("resourceName") == name]
        if not same:
            return None, f"AWS Config holds no record of a {spec['config_type']} named {name!r}"
        if any(not i.get("resourceDeletionTime") for i in same):
            return None, f"AWS Config lists a live {spec['config_type']} named {name!r}: the name is in use"
        latest = max(same, key=lambda i: i["resourceDeletionTime"])
        return str(latest["resourceId"]), ""

    def _read_history(
        self,
        candidate: Candidate,
        expected: Expected,
        spec: dict[str, Any],
        region: str,
        expected_account: str | None,
        arn: str,
        items: Sequence[dict[str, Any]],
        row_created: Any = None,
    ) -> tuple[Verdict, bool]:
        if not items:
            return _undetermined(candidate, "scope_unknown", "AWS Config returned no configuration items for this id"), False
        latest = items[0]
        status = str(latest.get("configurationItemStatus") or "")
        captured = _iso(latest.get("configurationItemCaptureTime"))
        mismatch = self._item_mismatch(latest, region, spec, expected_account, arn)
        if mismatch:
            return _undetermined(candidate, "scope_unknown", mismatch), False
        if status in DELETED_STATUSES:
            stale, later_incarnation = self._deletion_not_after_row(latest.get("configurationItemCaptureTime"), row_created)
            if stale:
                # The grid row was created after Config recorded the deletion, so the row is a later
                # incarnation of the same name or ARN, not the object that was deleted: never retire it on this.
                return _undetermined(candidate, "scope_unknown", stale), later_incarnation
            probe = Probe(
                status="not_found",
                detail=f"AWS Config item {status} captured {captured}; state {latest.get('configurationStateId')}",
            )
            return _finish(candidate, expected, probe, note=f"source: AWS Config {spec['config_type']} in {region}"), False
        earlier = next((i for i in items[1:] if i.get("configurationItemStatus") in DELETED_STATUSES), None)
        if earlier is not None:
            return (
                _undetermined(
                    candidate,
                    "scope_unknown",
                    f"AWS Config recorded a deletion at {_iso(earlier.get('configurationItemCaptureTime'))} and then "
                    f"{status} at {captured}: the object appears to have been recreated; not retired",
                ),
                True,
            )
        return (
            _undetermined(
                candidate,
                "scope_unknown",
                f"AWS Config's latest item is {status} (captured {captured}), not a deletion; Config trails the "
                "live account and cannot show the object exists, so this says nothing",
            ),
            True,
        )

    @staticmethod
    def _deletion_not_after_row(captured: Any, row_created: Any) -> tuple[str, bool]:
        """``(why, later_incarnation)``: why a deletion record cannot be about this grid row, ``""`` when it
        postdates the row's creation; ``later_incarnation`` is True when the row is shown to be a newer object.

        Config's history can end in a deletion that belongs to an EARLIER object of the same name or ARN. A
        grid row created after that deletion is a newer lifetime (a returning object is a new entity), so the
        old record must not retire it. When either time is unknown the order cannot be established, and the
        answer is no retirement.
        """
        if not isinstance(captured, datetime) or not isinstance(row_created, datetime):
            return "the order of AWS Config's deletion record and the grid row's creation cannot be established; not retired", False
        if captured < row_created:
            return (
                f"AWS Config recorded a deletion at {captured.isoformat()}, before the grid row was created "
                f"({row_created.isoformat()}): the row is a later incarnation of the same object, not retired",
                True,
            )
        return "", False

    @staticmethod
    def _item_mismatch(item: dict[str, Any], region: str, spec: dict[str, Any], expected_account: str | None, arn: str) -> str:
        """A reason the item is not about the grid's object, or ``""``."""
        if item.get("accountId") and expected_account and item["accountId"] != expected_account:
            return f"the Config item is for account {item['accountId']}, not {expected_account}"
        # Config files a global type (IAM) under the region "global", whatever endpoint was asked.
        item_region = item.get("awsRegion")
        if item_region and item_region != region and not (spec["scope"] == "global_home" and item_region == "global"):
            return f"the Config item is for region {item_region}, not {region}"
        if item.get("arn") and arn and item["arn"] != arn:
            return f"the Config item names {item['arn']!r}, not the grid's {arn!r}"
        return ""


def _row_created_at(candidate: Candidate) -> datetime | None:
    """When the grid first created this entity: the typed row carries no timestamp, its entity record does. ``None``
    when it cannot be read, which the freshness guard treats as an order it cannot establish."""
    try:
        from tap_grid.models import Entity  # noqa: PLC0415 — only a judging run needs the entity table

        created = Entity.objects.filter(id=candidate.entity_id).values_list("created_at", flat=True).first()
    except Exception:  # noqa: BLE001 — an unreadable timestamp is answered as unknown, never raised
        logger.warning("[c0f1] could not read the creation time of grid entity %s", candidate.entity_id)
        return None
    return created if isinstance(created, datetime) else None


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
