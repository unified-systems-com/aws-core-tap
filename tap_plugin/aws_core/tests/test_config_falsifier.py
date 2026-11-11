"""The AWS Config falsifier prototype (``tap_plugin/aws_core/config_falsifier.py``).

Config can falsify, never confirm: only a deleted configuration item yields a verdict
(``DROPPED_FROM_OBSERVATION``); every other outcome is ``UNDETERMINED`` with a reason. These tests
arrange a fake ``config`` client so each candidate meets one situation, and check the id and region
the falsifier asked about as well as the verdict.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import BotoCoreError
from tap_grid.falsifiers import (
    DROPPED_FROM_OBSERVATION,
    UNDETERMINED,
    Verdict,
    unsupported,
)
from tap_grid.models import Entity

from tap_plugin.aws_core.config_falsifier import (
    TYPES_PATH,
    ConfigHistoryFalsifier,
    ConfigMappingError,
    _validated,
    config_types,
)
from tap_plugin.aws_core.tests.test_falsifiers import (
    ACCOUNT_ID,
    IAM_GROUP,
    IAM_ROLE,
    OTHER_ACCOUNT_ID,
    _client_error,
    _context,
    _dimensioned,
    _iam_candidate,
)

LAMBDA = "aws_core__aws_lambda"
SQS = "aws_core__aws_sqs_queue"
SNS = "aws_core__aws_sns_topic"
DYNAMO = "aws_core__aws_dynamodb_table"
KMS_ALIAS = "aws_core__aws_kms_alias"
SECRETS_MANAGER_TYPE = "aws_core__aws_secrets_manager_secret"
RULE = "aws_core__aws_eventbridge_rule"
S3 = "aws_core__aws_s3_bucket"
GOV = "us-gov-west-1"
CAPTURED = datetime(2026, 11, 1, 19, 52, 17, tzinfo=UTC)
EARLIER = datetime(2026, 11, 1, 19, 30, 7, tzinfo=UTC)

RECORDER_ALL = {
    "name": "default",
    "recordingGroup": {"allSupported": True, "includeGlobalResourceTypes": True},
}
RECORDING = {"name": "default", "recording": True, "lastStatus": "SUCCESS"}


def item(status: str, when: datetime = CAPTURED, **extra: Any) -> dict[str, Any]:
    base = {"configurationItemStatus": status, "configurationItemCaptureTime": when, "configurationStateId": "1"}
    base.update(extra)
    return base


class FakeConfig:
    """A fake ``config`` client: one history answer, one recorder setup, a call log."""

    def __init__(
        self,
        items: list[dict[str, Any]] | None = None,
        *,
        recorders: list[dict[str, Any]] | None = None,
        statuses: list[dict[str, Any]] | None = None,
        history_error: Exception | None = None,
        discovered: list[dict[str, Any]] | None = None,
    ) -> None:
        self.items = items or []
        self.recorders = [RECORDER_ALL] if recorders is None else recorders
        self.statuses = [RECORDING] if statuses is None else statuses
        self.history_error = history_error
        self.discovered = discovered or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def describe_configuration_recorders(self) -> dict[str, Any]:
        return {"ConfigurationRecorders": self.recorders}

    def describe_configuration_recorder_status(self) -> dict[str, Any]:
        return {"ConfigurationRecordersStatus": self.statuses}

    def get_resource_config_history(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("history", kwargs))
        if self.history_error is not None:
            raise self.history_error
        return {"configurationItems": self.items}

    def list_discovered_resources(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list", kwargs))
        return {"resourceIdentifiers": self.discovered}


def session_for(client: FakeConfig | dict[str, FakeConfig]) -> MagicMock:
    """A session handing out ``client``, or the client for the region asked when given a mapping."""
    session = MagicMock()
    session.regions = []

    def client_for(service: str, region_name: str | None = None) -> FakeConfig:
        assert service == "config", f"asked for {service!r}"
        session.regions.append(region_name)
        return client[region_name or ""] if isinstance(client, dict) else client

    session.client.side_effect = client_for
    return session


def judge(
    slug: str,
    payload: dict[str, Any],
    client: FakeConfig | dict[str, FakeConfig],
    *,
    region: str = GOV,
    account: str = ACCOUNT_ID,
    sweep: list[str] | None = None,
    row_created: datetime | None = EARLIER - timedelta(days=1),
) -> tuple[Verdict, MagicMock]:
    entity_id = _dimensioned(slug, payload, region=region)
    # The row's creation time decides whether a deletion record can be about it; pin it so a test says which.
    Entity.objects.filter(id=entity_id).update(created_at=row_created)
    session = session_for(client)
    falsifier = ConfigHistoryFalsifier(
        session=session, account_id=account, region_sweep=(lambda _s: list(sweep)) if sweep is not None else None
    )
    [verdict] = falsifier.batch_falsify([_iam_candidate(entity_id, slug)], _context())
    return verdict, session


FN_ARN = f"arn:aws-us-gov:lambda:{GOV}:{ACCOUNT_ID}:function:seed-fn"
LAMBDA_ROW = {"name": "seed-fn", "function_arn": FN_ARN}


@pytest.mark.django_db
class TestVerdicts:
    def test_deleted_item_is_gone(self) -> None:
        client = FakeConfig([item("ResourceDeleted", arn=FN_ARN, accountId=ACCOUNT_ID, awsRegion=GOV)])
        verdict, session = judge(LAMBDA, LAMBDA_ROW, client)
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        assert unsupported(verdict) is None
        assert session.regions == [GOV]
        [(_, call)] = client.calls
        assert call["resourceType"] == "AWS::Lambda::Function"
        assert call["resourceId"] == "seed-fn"
        assert verdict.probe["status"] == "not_found"
        assert "ResourceDeleted" in verdict.probe["detail"]

    def test_deleted_not_recorded_is_gone(self) -> None:
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, FakeConfig([item("ResourceDeletedNotRecorded")]))
        assert verdict.verdict == DROPPED_FROM_OBSERVATION

    @pytest.mark.parametrize("status", ["OK", "ResourceDiscovered", "ResourceNotRecorded"])
    def test_a_live_looking_item_is_never_present_and_never_retires(self, status: str) -> None:
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, FakeConfig([item(status, arn=FN_ARN)]))
        assert verdict.verdict == UNDETERMINED
        assert verdict.reason == "scope_unknown"
        assert "not a deletion" in verdict.note

    def test_a_deletion_recorded_before_the_grid_row_existed_is_a_later_incarnation_and_not_retired(self) -> None:
        # Config's latest item is a deletion, but it is older than the grid row: the row is a newer object that
        # reuses the name or ARN, and the old record must not retire it.
        client = FakeConfig([item("ResourceDeleted", EARLIER, arn=FN_ARN, accountId=ACCOUNT_ID, awsRegion=GOV)])
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, client, row_created=CAPTURED + timedelta(days=1))
        assert verdict.verdict == UNDETERMINED
        assert "later incarnation" in verdict.note

    def test_a_deletion_after_the_grid_row_was_created_retires(self) -> None:
        client = FakeConfig([item("ResourceDeleted", CAPTURED, arn=FN_ARN, accountId=ACCOUNT_ID, awsRegion=GOV)])
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, client, row_created=CAPTURED - timedelta(minutes=5))
        assert verdict.verdict == DROPPED_FROM_OBSERVATION

    @pytest.mark.parametrize(("captured", "created"), [(None, CAPTURED), (CAPTURED, None), ("2026-11-01", CAPTURED)])
    def test_an_unknown_order_never_retires(self, captured: object, created: object) -> None:
        why, later = ConfigHistoryFalsifier._deletion_not_after_row(captured, created)
        assert "cannot be established" in why and later is False

    def test_deleted_then_recreated_is_not_retired(self) -> None:
        client = FakeConfig([item("OK", CAPTURED), item("ResourceDeleted", EARLIER)])
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, client)
        assert verdict.verdict == UNDETERMINED
        assert "recreated" in verdict.note

    def test_history_is_read_newest_first(self) -> None:
        client = FakeConfig([item("ResourceDeleted")])
        judge(LAMBDA, LAMBDA_ROW, client)
        [(_, call)] = client.calls
        assert call["chronologicalOrder"] == "Reverse"

    def test_never_discovered_id_is_unknown_not_gone(self) -> None:
        client = FakeConfig(history_error=_client_error("ResourceNotDiscoveredException", "GetResourceConfigHistory"))
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, client)
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")

    def test_throttling(self) -> None:
        client = FakeConfig(history_error=_client_error("ThrottlingException", "GetResourceConfigHistory"))
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, client)
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "rate_limited")

    def test_access_denied(self) -> None:
        client = FakeConfig(history_error=_client_error("AccessDeniedException", "GetResourceConfigHistory"))
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, client)
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "forbidden")

    def test_a_not_found_style_error_code_is_not_a_deletion(self) -> None:
        client = FakeConfig(history_error=_client_error("SomethingNotFoundException", "GetResourceConfigHistory"))
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, client)
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "errored")

    def test_a_network_failure_is_errored(self) -> None:
        client = FakeConfig(history_error=BotoCoreError())
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, client)
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "errored")

    def test_no_items(self) -> None:
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, FakeConfig([]))
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")


@pytest.mark.django_db
class TestScope:
    def test_wrong_region_is_refused_without_asking_config(self) -> None:
        verdict, session = judge(LAMBDA, LAMBDA_ROW, FakeConfig([item("ResourceDeleted")]), region="global")
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert session.regions == []

    def test_config_item_for_another_region_is_refused(self) -> None:
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, FakeConfig([item("ResourceDeleted", awsRegion="us-gov-east-1")]))
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")

    def test_config_item_for_another_account_is_refused(self) -> None:
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, FakeConfig([item("ResourceDeleted", accountId=OTHER_ACCOUNT_ID)]))
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")

    def test_config_item_naming_another_arn_is_refused(self) -> None:
        other = FN_ARN.replace("seed-fn", "another")
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, FakeConfig([item("ResourceDeleted", arn=other)]))
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")

    def test_credential_for_another_account_is_refused(self) -> None:
        verdict, session = judge(LAMBDA, LAMBDA_ROW, FakeConfig([item("ResourceDeleted")]), account=OTHER_ACCOUNT_ID)
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert session.regions == []

    def test_a_type_without_a_mapping_is_refused(self) -> None:
        entity_id = _dimensioned("aws_core__aws_vpc_endpoint", {"name": "x"}, region=GOV)
        [verdict] = ConfigHistoryFalsifier(session=session_for(FakeConfig()), account_id=ACCOUNT_ID).batch_falsify(
            [_iam_candidate(entity_id, "aws_core__aws_vpc_endpoint")], _context()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")


@pytest.mark.django_db
class TestGlobalNames:
    """An S3 bucket: the name is global, Config files the item under the bucket's own region, and
    the grid row says 'global'. Every enabled region is asked."""

    ROW = {"name": "seed-bucket", "bucket_arn": "arn:aws-us-gov:s3:::seed-bucket"}
    EAST = "us-gov-east-1"

    def deleted_in_west(self) -> dict[str, FakeConfig]:
        undiscovered = FakeConfig(history_error=_client_error("ResourceNotDiscoveredException", "GetResourceConfigHistory"))
        return {GOV: FakeConfig([item("ResourceDeleted", awsRegion=GOV, arn=self.ROW["bucket_arn"])]), self.EAST: undiscovered}

    def test_deleted_in_one_region_and_unknown_in_the_other_is_gone(self) -> None:
        verdict, session = judge(S3, self.ROW, self.deleted_in_west(), region="global", sweep=[GOV, self.EAST])
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        assert sorted(session.regions) == [self.EAST, GOV]

    def test_alive_in_another_region_is_not_retired(self) -> None:
        clients = self.deleted_in_west()
        clients[self.EAST] = FakeConfig([item("OK", awsRegion=self.EAST)])
        verdict, _ = judge(S3, self.ROW, clients, region="global", sweep=[GOV, self.EAST])
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")

    def test_a_failing_region_does_not_hide_a_deletion_elsewhere(self) -> None:
        clients = self.deleted_in_west()
        clients[self.EAST] = FakeConfig(history_error=_client_error("ThrottlingException", "GetResourceConfigHistory"))
        verdict, _ = judge(S3, self.ROW, clients, region="global", sweep=[GOV, self.EAST])
        assert verdict.verdict == DROPPED_FROM_OBSERVATION

    def test_no_enabled_regions_is_refused(self) -> None:
        verdict, session = judge(S3, self.ROW, FakeConfig([item("ResourceDeleted")]), region="global", sweep=[])
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert session.regions == []

    def test_nothing_known_anywhere_keeps_the_refusal(self) -> None:
        undiscovered = FakeConfig(history_error=_client_error("ResourceNotDiscoveredException", "GetResourceConfigHistory"))
        verdict, _ = judge(S3, self.ROW, {GOV: undiscovered, self.EAST: undiscovered}, region="global", sweep=[GOV, self.EAST])
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")


@pytest.mark.django_db
class TestRecorder:
    def test_no_recorder(self) -> None:
        verdict, session = judge(LAMBDA, LAMBDA_ROW, FakeConfig([item("ResourceDeleted")], recorders=[], statuses=[]))
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "no configuration recorder" in verdict.note

    def test_recorder_stopped(self) -> None:
        stopped = [{"name": "default", "recording": False, "lastStatus": "SUCCESS"}]
        client = FakeConfig([item("ResourceDeleted")], statuses=stopped)
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, client)
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert not [c for c in client.calls if c[0] == "history"], "history is not read when nothing records"

    def test_recorder_whose_last_delivery_failed(self) -> None:
        failed = [{"name": "default", "recording": True, "lastStatus": "FAILURE"}]
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, FakeConfig([item("ResourceDeleted")], statuses=failed))
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")

    def test_type_outside_an_inclusion_list(self) -> None:
        only_sqs = {"name": "default", "recordingGroup": {"allSupported": False, "resourceTypes": ["AWS::SQS::Queue"]}}
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, FakeConfig([item("ResourceDeleted")], recorders=[only_sqs]))
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "does not record AWS::Lambda::Function" in verdict.note

    def test_type_inside_an_inclusion_list(self) -> None:
        listed = {"name": "default", "recordingGroup": {"allSupported": False, "resourceTypes": ["AWS::Lambda::Function"]}}
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, FakeConfig([item("ResourceDeleted")], recorders=[listed]))
        assert verdict.verdict == DROPPED_FROM_OBSERVATION

    def test_type_excluded(self) -> None:
        excluded = {
            "name": "default",
            "recordingGroup": {
                "recordingStrategy": {"useOnly": "EXCLUSION_BY_RESOURCE_TYPES"},
                "exclusionByResourceTypes": {"resourceTypes": ["AWS::Lambda::Function"]},
            },
        }
        verdict, _ = judge(LAMBDA, LAMBDA_ROW, FakeConfig([item("ResourceDeleted")], recorders=[excluded]))
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")

    def test_global_types_need_a_recorder_that_includes_them(self) -> None:
        east = {"name": "default", "recordingGroup": {"allSupported": True, "includeGlobalResourceTypes": False}}
        arn = f"arn:aws-us-gov:iam::{ACCOUNT_ID}:group/g"
        verdict, _ = judge(
            IAM_GROUP, {"name": "g", "group_arn": arn, "group_id": "AGPAX"}, FakeConfig([item("ResourceDeleted")], recorders=[east])
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")

    def test_recorder_is_read_once_per_region_and_type(self) -> None:
        client = FakeConfig([item("ResourceDeleted")])
        client.describe_configuration_recorders = MagicMock(wraps=client.describe_configuration_recorders)  # type: ignore[method-assign]
        session = session_for(client)
        falsifier = ConfigHistoryFalsifier(session=session, account_id=ACCOUNT_ID)
        rows = [
            _iam_candidate(_dimensioned(LAMBDA, {"name": f"f{i}", "function_arn": FN_ARN.replace("seed-fn", f"f{i}")}, region=GOV), LAMBDA)
            for i in range(3)
        ]
        Entity.objects.filter(id__in=[r.entity_id for r in rows]).update(created_at=EARLIER - timedelta(days=1))
        verdicts = falsifier.batch_falsify(rows, _context())
        assert [v.verdict for v in verdicts] == [DROPPED_FROM_OBSERVATION] * 3
        assert client.describe_configuration_recorders.call_count == 1


@pytest.mark.django_db
class TestIdDerivation:
    """The id asked of Config, per type, as read from live Config data on 2026-11-01."""

    def asked(self, slug: str, payload: dict[str, Any]) -> str:
        client = FakeConfig([item("ResourceDeleted")])
        verdict, _ = judge(slug, payload, client)
        assert verdict.verdict == DROPPED_FROM_OBSERVATION, verdict.note
        [(_, call)] = client.calls
        return f"{call['resourceType']}|{call['resourceId']}"

    def test_each_type(self) -> None:
        acct = ACCOUNT_ID
        url = f"https://sqs.{GOV}.amazonaws.com/{acct}/seed-queue"
        topic = f"arn:aws-us-gov:sns:{GOV}:{acct}:seed-topic"
        secret = f"arn:aws-us-gov:secretsmanager:{GOV}:{acct}:secret:seed-secret-pR8vkf"
        assert self.asked(LAMBDA, LAMBDA_ROW) == "AWS::Lambda::Function|seed-fn"
        assert (
            self.asked(SQS, {"name": "seed-queue", "queue_arn": f"arn:aws-us-gov:sqs:{GOV}:{acct}:seed-queue", "queue_url": url})
            == f"AWS::SQS::Queue|{url}"
        )
        assert self.asked(SNS, {"name": "seed-topic", "topic_arn": topic}) == f"AWS::SNS::Topic|{topic}"
        assert (
            self.asked(DYNAMO, {"name": "seed-table", "table_arn": f"arn:aws-us-gov:dynamodb:{GOV}:{acct}:table/seed-table"})
            == "AWS::DynamoDB::Table|seed-table"
        )
        assert (
            self.asked(KMS_ALIAS, {"name": "seed", "alias_arn": f"arn:aws-us-gov:kms:{GOV}:{acct}:alias/seed", "alias_name": "alias/seed"})
            == "AWS::KMS::Alias|alias/seed"
        )
        assert self.asked(SECRETS_MANAGER_TYPE, {"name": "seed-secret", "secret_arn": secret}) == f"AWS::SecretsManager::Secret|{secret}"
        assert (
            self.asked(RULE, {"name": "seed-rule", "rule_arn": f"arn:aws-us-gov:events:{GOV}:{acct}:rule/seed-rule"})
            == "AWS::Events::Rule|seed-rule"
        )
        s3_client = FakeConfig([item("ResourceDeleted")])
        judge(S3, {"name": "seed-bucket", "bucket_arn": "arn:aws-us-gov:s3:::seed-bucket"}, s3_client, region="global", sweep=[GOV])
        [(_, call)] = s3_client.calls
        assert (call["resourceType"], call["resourceId"]) == ("AWS::S3::Bucket", "seed-bucket")

    def test_a_rule_on_a_custom_bus_is_refused(self) -> None:
        arn = f"arn:aws-us-gov:events:{GOV}:{ACCOUNT_ID}:rule/custom-bus/seed-rule"
        verdict, session = judge(RULE, {"name": "seed-rule", "rule_arn": arn}, FakeConfig([item("ResourceDeleted")]))
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert session.regions == []

    def test_a_row_without_the_field_is_refused(self) -> None:
        verdict, _ = judge(SQS, {"name": "q", "queue_arn": "arn:aws-us-gov:sqs:x:y:q"}, FakeConfig([item("ResourceDeleted")]))
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")


@pytest.mark.django_db
class TestIam:
    """IAM ids are opaque. The row's own id is used when it has one, else Config is asked by name."""

    ARN = f"arn:aws-us-gov:iam::{ACCOUNT_ID}:role/seed-role"

    def test_global_region_comes_from_the_arn_partition(self) -> None:
        client = FakeConfig([item("ResourceDeleted")])
        verdict, session = judge(IAM_ROLE, {"name": "seed-role", "role_arn": self.ARN, "role_id": "AROAX"}, client, region="global")
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        assert session.regions == [GOV]
        [(_, call)] = client.calls
        assert call["resourceId"] == "AROAX"

    def test_config_files_iam_items_under_the_region_global(self) -> None:
        client = FakeConfig([item("ResourceDeleted", awsRegion="global", arn=self.ARN)])
        verdict, _ = judge(IAM_ROLE, {"name": "seed-role", "role_arn": self.ARN, "role_id": "AROAX"}, client, region="global")
        assert verdict.verdict == DROPPED_FROM_OBSERVATION

    def test_commercial_arn_asks_us_east_1(self) -> None:
        arn = f"arn:aws:iam::{ACCOUNT_ID}:role/seed-role"
        _, session = judge(IAM_ROLE, {"name": "seed-role", "role_arn": arn, "role_id": "AROAX"}, FakeConfig([item("ResourceDeleted")]), region="global")
        assert session.regions == ["us-east-1"]

    def test_lookup_by_name_uses_the_deleted_id(self) -> None:
        discovered = [{"resourceId": "AROAOLD", "resourceName": "seed-role", "resourceDeletionTime": EARLIER}]
        client = FakeConfig([item("ResourceDeleted")], discovered=discovered)
        verdict, _ = judge(IAM_ROLE, {"name": "seed-role", "role_arn": self.ARN}, client, region="global")
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        assert [c[1]["resourceId"] for c in client.calls if c[0] == "history"] == ["AROAOLD"]
        assert [c[1]["includeDeletedResources"] for c in client.calls if c[0] == "list"] == [True]

    def test_lookup_by_name_takes_the_latest_deletion(self) -> None:
        discovered = [
            {"resourceId": "AROAFIRST", "resourceName": "seed-role", "resourceDeletionTime": EARLIER},
            {"resourceId": "AROASECOND", "resourceName": "seed-role", "resourceDeletionTime": CAPTURED},
        ]
        client = FakeConfig([item("ResourceDeleted")], discovered=discovered)
        judge(IAM_ROLE, {"name": "seed-role", "role_arn": self.ARN}, client, region="global")
        assert [c[1]["resourceId"] for c in client.calls if c[0] == "history"] == ["AROASECOND"]

    def test_a_live_object_of_the_same_name_blocks_retirement(self) -> None:
        discovered = [
            {"resourceId": "AROAOLD", "resourceName": "seed-role", "resourceDeletionTime": EARLIER},
            {"resourceId": "AROANEW", "resourceName": "seed-role"},
        ]
        client = FakeConfig([item("ResourceDeleted")], discovered=discovered)
        verdict, _ = judge(IAM_ROLE, {"name": "seed-role", "role_arn": self.ARN}, client, region="global")
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "in use" in verdict.note
        assert not [c for c in client.calls if c[0] == "history"]

    def test_unknown_name(self) -> None:
        verdict, _ = judge(IAM_ROLE, {"name": "seed-role", "role_arn": self.ARN}, FakeConfig([item("ResourceDeleted")]), region="global")
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")

    def test_a_path_change_is_not_retired(self) -> None:
        other = f"arn:aws-us-gov:iam::{ACCOUNT_ID}:role/elsewhere/seed-role"
        client = FakeConfig([item("ResourceDeleted", arn=other)])
        verdict, _ = judge(IAM_ROLE, {"name": "seed-role", "role_arn": self.ARN, "role_id": "AROAX"}, client, region="global")
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")


class TestMappingFile:
    def test_the_shipped_file_loads_and_every_slug_is_a_declared_model(self) -> None:
        import tomllib

        manifest = tomllib.loads((TYPES_PATH.parent / "tap-plugin.toml").read_text())
        models = manifest["models"]
        assert config_types()
        for slug in config_types():
            assert slug in models, f"{slug} is not declared in [models]"

    def test_every_registered_config_type_has_a_mapping(self) -> None:
        import tomllib

        manifest = tomllib.loads((TYPES_PATH.parent / "tap-plugin.toml").read_text())
        for slug, path in manifest["falsifiers"].items():
            if path.endswith("ConfigHistoryFalsifier"):
                assert slug in config_types()

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda t: t.pop("description"),
            lambda t: t.update(config_type="Lambda"),
            lambda t: t.update(scope="everywhere"),
            lambda t: t.update(id={"from": "guess"}),
            lambda t: t.update(id={"from": "arn_tail", "marker": ":x:"}, arn_field=None),
            lambda t: t.update(scope="global_home", arn_field=None),
        ],
    )
    def test_a_malformed_entry_is_refused(self, mutate: Any) -> None:
        raw = json.loads(TYPES_PATH.read_text())
        entry = raw["types"]["aws_core__aws_sns_topic"]
        mutate(entry)
        with pytest.raises(ConfigMappingError):
            _validated(raw)

    def test_an_empty_file_is_refused(self) -> None:
        with pytest.raises(ConfigMappingError):
            _validated({"types": {}})
