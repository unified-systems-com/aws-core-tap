"""The ECS chain past the container: task and service to their task definition, and the definition to the secrets
and parameters it names.

Spec: specs/spec-aws-core-collector-v0.md (req-aws-collector-ecs-24 .. -27).

AWS calls go through a real botocore ECS client under ``botocore.stub.Stubber``, so each request and canned
response is checked against the ECS service model the pinned botocore ships. The grid tests run the whole collector
over the vertical slice's canned AWS and import the batch through core's GRIFT validation.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from tap_plugin.aws_core.collectors.boto3_collector import customfns
from tap_plugin.aws_core.collectors.boto3_collector.authority import EDGE_READS, _path_present, anchor_reads
from tap_plugin.aws_core.collectors.boto3_collector.batch import entry_redact_paths, node_envelope
from tap_plugin.aws_core.collectors.boto3_collector.ecs import (
    _task_definition_item,
    describe_task_definitions,
    referenced_task_definitions,
)
from tap_plugin.aws_core.collectors.boto3_collector.edges import emit_edges
from tap_plugin.aws_core.collectors.boto3_collector.identity import node_ref
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
from tap_plugin.aws_core.collectors.boto3_collector.transforms import (
    build_transform_registry,
    secrets_manager_secret_arn_or_none,
    ssm_parameter_arn,
)
from tap_plugin.aws_core.tests.grid_keys import find_node_id, live_edges, node_id

from tap_cares.collectors.config import CollectorConfig

from . import test_boto3_collector_slice as slice_tests
from .test_ecs_images import _stubbed_walk, _task

_REGION = "us-east-1"
_ACCOUNT = "111122223333"
_TASK_DEF_TYPE = "aws_core__aws_ecs_task_definition"
_TASK_TYPE = "aws_core__aws_ecs_task"
_SERVICE_TYPE = "aws_core__aws_ecs_service"
# Placeholder names avoid "secret"/"token" as a word: a hardcoded-password scan (bandit B105) reads such a
# name bound to a string as a credential, and none of these is one.
_SM_TYPE = "aws_core__aws_secrets_manager_secret"
_PARAMETER_TYPE = "aws_core__aws_ssm_parameter"
USES = "USES_TASK_DEFINITION__aws_core"
REFERENCES_SM = "REFERENCES_SECRET__aws_core"
REF_PARAMETER = "REFERENCES_PARAMETER__aws_core"

_ACTIVE = f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:task-definition/web:8"
_INACTIVE = f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:task-definition/web:7"
_SM_ARN = f"arn:aws:secretsmanager:{_REGION}:{_ACCOUNT}:secret:prod/db-AbC123"
_OTHER_SM_ARN = f"arn:aws:secretsmanager:{_REGION}:{_ACCOUNT}:secret:prod/api-key-XyZ789"
_PARAM_ARN = f"arn:aws:ssm:{_REGION}:{_ACCOUNT}:parameter/prod/db/host"
_PARAM_BY_NAME = f"arn:aws:ssm:{_REGION}:{_ACCOUNT}:parameter/prod/feature-flags"
_PLAIN_ENV_CANARY = "ecs-taskdef-plain-env-4b1e"
_SECRETISH_ENV_CANARY = "ecs-taskdef-secret-env-90cd"


def _definition(arn: str, *, status: str = "ACTIVE", secrets: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """A ``TaskDefinition`` as ``DescribeTaskDefinition`` returns it, every member a real one of the ECS model."""
    family, revision = arn.rsplit("/", 1)[1].split(":")
    app: dict[str, Any] = {
        "name": "web",
        "image": f"{_ACCOUNT}.dkr.ecr.{_REGION}.amazonaws.com/team/web:1.4.2",
        "essential": True,
        "environment": [
            {"name": "LOG_LEVEL", "value": _PLAIN_ENV_CANARY},
            {"name": "DB_PASSWORD", "value": _SECRETISH_ENV_CANARY},
        ],
    }
    if secrets is not None:
        app["secrets"] = secrets
    return {
        "taskDefinitionArn": arn,
        "family": family,
        "revision": int(revision),
        "status": status,
        "networkMode": "awsvpc",
        "requiresCompatibilities": ["FARGATE"],
        "cpu": "256",
        "memory": "512",
        "executionRoleArn": f"arn:aws:iam::{_ACCOUNT}:role/ecs-exec",
        "containerDefinitions": [app, {"name": "log-router", "image": "public.ecr.aws/aws-observability/aws-for-fluent-bit:2.32.0"}],
        "registeredAt": datetime(2026, 10, 1, 8, 0, tzinfo=UTC),
    }


_SECRETS = [
    {"name": "DB_URL", "valueFrom": _SM_ARN},
    {"name": "DB_USER", "valueFrom": f"{_SM_ARN}:username::"},  # a JSON key of the same secret
    {"name": "API_KEY", "valueFrom": f"{_OTHER_SM_ARN}:key:AWSCURRENT:"},
    {"name": "DB_HOST", "valueFrom": _PARAM_ARN},
    {"name": "FLAGS", "valueFrom": "/prod/feature-flags"},  # a parameter by name, in the task's own region
]


def _ecs_client():
    return boto3.client(
        "ecs", region_name=_REGION, aws_access_key_id="test", aws_secret_access_key="test"  # noqa: S106 — offline stub
    )


def _entry(entity_type: str) -> dict[str, Any]:
    return next(e for e in manifest_entries() if e["entity_type"] == entity_type)


def _modeled() -> set[str]:
    return {e["entity_type"] for e in manifest_entries()}


def _emitted(entity_type: str, item: dict[str, Any], edge_type: str) -> list[tuple[str, str]]:
    item = _as_collected(entity_type, item)
    node = project_item(_entry(entity_type), item, {"region": _REGION})
    emission = emit_edges(
        node, _entry(entity_type), modeled_types=_modeled(), transforms=build_transform_registry(), dimensions={}
    )
    return sorted(
        (e["edge"]["from_ref"], e["edge"]["to_ref"]) for e in emission.envelopes if e["edge"]["edge_type"] == edge_type
    )


def _as_collected(entity_type: str, item: dict[str, Any]) -> dict[str, Any]:
    """A task definition as the custom_fn yields it (its reads declared); any other item as given."""
    return _task_definition_item({"taskDefinition": item}) if entity_type == _TASK_DEF_TYPE else item


def _reads(entity_type: str, item: dict[str, Any]) -> dict[tuple[str, str], str]:
    item = _as_collected(entity_type, item)
    node = project_item(_entry(entity_type), item, {"region": _REGION})
    return anchor_reads(node, _entry(entity_type), modeled_types=_modeled(), transforms=build_transform_registry())


# --- (d) USES_TASK_DEFINITION ---------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-collector-ecs-24")
class TestUsesTaskDefinition:
    def test_a_task_and_its_service_point_at_the_revisions_they_name(self):
        walk = _stubbed_walk([_task(slice_tests._ECS_TASK, [])])
        (task,) = walk.tasks
        (service,) = walk.services
        td = node_ref(_TASK_DEF_TYPE, task["taskDefinitionArn"])
        assert _emitted(_TASK_TYPE, task, USES) == [(node_ref(_TASK_TYPE, task["taskArn"]), td)]
        assert _emitted(_SERVICE_TYPE, service, USES) == [(node_ref(_SERVICE_TYPE, service["serviceArn"]), td)]

    def test_both_reads_are_complete_when_described(self):
        walk = _stubbed_walk([_task(slice_tests._ECS_TASK, [])])
        assert walk.tasks[0][EDGE_READS]["taskDefinitionArn"] == "complete"
        assert walk.services[0][EDGE_READS]["taskDefinition"] == "complete"
        assert _reads(_TASK_TYPE, walk.tasks[0])[(USES, "outbound")] == "complete"
        assert _reads(_SERVICE_TYPE, walk.services[0])[(USES, "outbound")] == "complete"

    def test_a_service_that_names_no_revision_is_partial_never_claimed_empty(self):
        """An EXTERNAL-controller service has task sets, not a taskDefinition: AWS leaves the member out, so the
        read is partial and the run claims nothing about the service's edges."""
        walk = _stubbed_walk([_task(slice_tests._ECS_TASK, [])])
        service = {k: v for k, v in walk.services[0].items() if k != "taskDefinition"}
        assert _emitted(_SERVICE_TYPE, service, USES) == []
        assert _reads(_SERVICE_TYPE, service)[(USES, "outbound")] == "partial"

    def test_the_manifest_declares_both_rules(self):
        rules = {
            (e["entity_type"], r["value_path"], r["target_type"], r["direction"])
            for e in manifest_entries()
            for r in e.get("edges", [])
            if r["edge_type"] == USES
        }
        assert rules == {
            (_TASK_TYPE, "taskDefinitionArn", _TASK_DEF_TYPE, "outbound"),
            (_SERVICE_TYPE, "taskDefinition", _TASK_DEF_TYPE, "outbound"),
        }

    def test_the_edge_is_a_reference_not_containment(self):
        from tap_grid.registry import get_model_class

        for entity_type in (_TASK_TYPE, _SERVICE_TYPE):
            assert USES not in tuple(getattr(get_model_class(entity_type), "CONTAINMENT_EDGES", ()) or ())


# --- D4: the revisions running tasks still use ---------------------------------------------------------------------


@pytest.mark.spec("req-aws-collector-ecs-25")
class TestReferencedRevisionsDescribed:
    def test_the_active_list_and_the_inactive_revision_a_task_runs(self):
        client = _ecs_client()
        with Stubber(client) as stub:
            stub.add_response("list_task_definitions", {"taskDefinitionArns": [_ACTIVE]}, {"status": "ACTIVE"})
            stub.add_response("describe_task_definition", {"taskDefinition": _definition(_ACTIVE)}, {"taskDefinition": _ACTIVE})
            stub.add_response(
                "describe_task_definition",
                {"taskDefinition": _definition(_INACTIVE, status="INACTIVE")},
                {"taskDefinition": _INACTIVE},
            )
            items = list(describe_task_definitions(client, [_ACTIVE, _INACTIVE]))
            stub.assert_no_pending_responses()
        assert [(i["taskDefinitionArn"], i["status"]) for i in items] == [(_ACTIVE, "ACTIVE"), (_INACTIVE, "INACTIVE")]
        assert all(i[EDGE_READS] == {"containerDefinitions": "complete"} for i in items)

    def test_an_active_revision_is_described_once_however_often_it_is_named(self):
        client = _ecs_client()
        with Stubber(client) as stub:
            stub.add_response("list_task_definitions", {"taskDefinitionArns": [_ACTIVE]}, {"status": "ACTIVE"})
            stub.add_response("describe_task_definition", {"taskDefinition": _definition(_ACTIVE)}, {"taskDefinition": _ACTIVE})
            assert len(list(describe_task_definitions(client, [_ACTIVE, _ACTIVE]))) == 1
            stub.assert_no_pending_responses()

    def test_a_referenced_revision_that_cannot_be_described_is_left_out(self):
        client = _ecs_client()
        with Stubber(client) as stub:
            stub.add_response("list_task_definitions", {"taskDefinitionArns": []}, {"status": "ACTIVE"})
            stub.add_client_error(
                "describe_task_definition",
                service_error_code="ClientException",
                service_message="Unable to describe task definition.",
                expected_params={"taskDefinition": _INACTIVE},
            )
            assert list(describe_task_definitions(client, [_INACTIVE])) == []

    def test_a_listed_revision_that_fails_to_describe_skips_the_entry(self):
        """As before the references: a short type never reads as complete."""
        client = _ecs_client()
        with Stubber(client) as stub:
            stub.add_response("list_task_definitions", {"taskDefinitionArns": [_ACTIVE]}, {"status": "ACTIVE"})
            stub.add_client_error("describe_task_definition", service_error_code="AccessDeniedException")
            with pytest.raises(ClientError):
                list(describe_task_definitions(client, []))

    def test_every_page_of_the_active_list_is_read(self):
        client = _ecs_client()
        with Stubber(client) as stub:
            stub.add_response(
                "list_task_definitions", {"taskDefinitionArns": [_ACTIVE], "nextToken": "p2"}, {"status": "ACTIVE"}
            )
            stub.add_response(
                "list_task_definitions", {"taskDefinitionArns": [_INACTIVE]}, {"status": "ACTIVE", "nextToken": "p2"}
            )
            for arn in (_ACTIVE, _INACTIVE):
                stub.add_response("describe_task_definition", {"taskDefinition": _definition(arn)}, {"taskDefinition": arn})
            assert [i["taskDefinitionArn"] for i in describe_task_definitions(client)] == [_ACTIVE, _INACTIVE]

    def test_the_walk_names_the_revisions_of_its_tasks_and_services(self):
        walk = _stubbed_walk([_task(slice_tests._ECS_TASK, [])])
        walk.tasks[0]["taskDefinitionArn"] = _INACTIVE
        walk.services[0]["taskDefinition"] = _ACTIVE
        assert referenced_task_definitions(walk) == sorted([_ACTIVE, _INACTIVE])

    def test_a_failed_walk_still_reads_the_active_revisions(self, monkeypatch):
        def denied(_session, _client_for):
            raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "x"}}, "ListClusters")

        monkeypatch.setattr(customfns, "shared_walk", denied)
        client = _ecs_client()
        with Stubber(client) as stub:
            stub.add_response("list_task_definitions", {"taskDefinitionArns": [_ACTIVE]}, {"status": "ACTIVE"})
            stub.add_response("describe_task_definition", {"taskDefinition": _definition(_ACTIVE)}, {"taskDefinition": _ACTIVE})
            items = list(customfns.ecs_task_definitions_described(object(), client_for=lambda _service: client))
        assert [i["taskDefinitionArn"] for i in items] == [_ACTIVE]

    def test_tags_reach_the_node_through_list_tags_for_resource(self):
        """The entry's tags lane is ListTagsForResource on the revision's ARN, as it was for the generic source (which
        passed no include=TAGS and kept only the taskDefinition object): the item needs only its ARN."""
        from tap_plugin.aws_core.collectors.boto3_collector.collector import resolve_node_tags

        client = _ecs_client()
        with Stubber(client) as stub:
            stub.add_response("list_task_definitions", {"taskDefinitionArns": [_ACTIVE]}, {"status": "ACTIVE"})
            stub.add_response("describe_task_definition", {"taskDefinition": _definition(_ACTIVE)}, {"taskDefinition": _ACTIVE})
            stub.add_response(
                "list_tags_for_resource", {"tags": [{"key": "team", "value": "core"}]}, {"resourceArn": _ACTIVE}
            )
            (item,) = describe_task_definitions(client)
            entry = _entry(_TASK_DEF_TYPE)
            tags, slot, _mapping = resolve_node_tags(entry, item, rgta_map={}, client_for=lambda _service: client)
            stub.assert_no_pending_responses()
        assert tags == {"team": "core"} and slot["status"] == "ok"
        node = project_item(entry, item, {"region": _REGION})
        assert node_envelope(node, {}, tags, persist_configuration=False)["node"]["tags"] == {"team": "core"}

    def test_the_entry_is_the_custom_fn(self):
        entry = _entry(_TASK_DEF_TYPE)
        assert entry["source"] == {"custom_fn": "ecs_task_definitions_described"}
        assert "ecs_task_definitions_described" in customfns._CUSTOM_FNS


# --- (e) REFERENCES_SECRET and REFERENCES_PARAMETER -----------------------------------------------------------------


@pytest.mark.spec("req-aws-collector-ecs-26")
class TestReferencesSecret:
    @pytest.mark.parametrize(
        ("value", "secret"),
        [
            (_SM_ARN, _SM_ARN),
            (f"{_SM_ARN}:username::", _SM_ARN),
            (f"{_SM_ARN}::AWSPREVIOUS:", _SM_ARN),
            (f"{_SM_ARN}:::0f1e2d3c-aaaa-bbbb-cccc-111122223333", _SM_ARN),
            (f"arn:aws-us-gov:secretsmanager:us-gov-west-1:{_ACCOUNT}:secret:db-AbC123", f"arn:aws-us-gov:secretsmanager:us-gov-west-1:{_ACCOUNT}:secret:db-AbC123"),
            (f"arn:aws:secretsmanager:{_REGION}:{_ACCOUNT}:secret:prod/db", None),  # partial ARN: not the key
            (f"{_SM_ARN}:username", None),  # a suffix must write all three parts
            (_PARAM_ARN, None),
            ("/prod/feature-flags", None),
            ("", None),
            (None, None),
        ],
    )
    def test_value_from_maps_to_the_secret_arn(self, value, secret):
        assert secrets_manager_secret_arn_or_none(value) == secret

    def test_one_edge_per_secret_with_no_properties(self):
        item = _definition(_ACTIVE, secrets=_SECRETS)
        td = node_ref(_TASK_DEF_TYPE, _ACTIVE)
        assert sorted(set(_emitted(_TASK_DEF_TYPE, item, REFERENCES_SM))) == sorted(
            [(td, node_ref(_SM_TYPE, _SM_ARN)), (td, node_ref(_SM_TYPE, _OTHER_SM_ARN))]
        )
        node = project_item(_entry(_TASK_DEF_TYPE), item, {"region": _REGION})
        emission = emit_edges(
            node, _entry(_TASK_DEF_TYPE), modeled_types=_modeled(), transforms=build_transform_registry(), dimensions={}
        )
        assert all(e["edge"]["properties"] == {} for e in emission.envelopes)

    def test_the_read_is_complete_when_every_secret_reference_maps(self):
        assert _reads(_TASK_DEF_TYPE, _definition(_ACTIVE, secrets=_SECRETS))[(REFERENCES_SM, "outbound")] == "complete"

    def test_a_partial_secret_arn_makes_the_read_partial(self):
        secrets = [*_SECRETS, {"name": "X", "valueFrom": f"arn:aws:secretsmanager:{_REGION}:{_ACCOUNT}:secret:prod/db"}]
        assert _reads(_TASK_DEF_TYPE, _definition(_ACTIVE, secrets=secrets))[(REFERENCES_SM, "outbound")] == "partial"

    def test_a_definition_whose_containers_name_no_secret_reads_complete_and_empty(self):
        """A container definition with no ``secrets`` is that element's answer, not a member AWS left unread."""
        item = _definition(_ACTIVE)
        assert _emitted(_TASK_DEF_TYPE, item, REFERENCES_SM) == []
        reads = _reads(_TASK_DEF_TYPE, item)
        assert reads[(REFERENCES_SM, "outbound")] == reads[(REF_PARAMETER, "outbound")] == "complete"

    def test_only_the_two_secret_rules_read_a_path_through_two_lists(self):
        """_path_present stops at the first list for every rule; today only these two rules have a second list. A new
        one must be checked for fail-open before it joins this set."""
        multi = sorted(
            (e["entity_type"], r["edge_type"], r["value_path"])
            for e in manifest_entries()
            for r in e.get("edges", [])
            if r["value_path"].count("[]") >= 2 or "[]" in str(r.get("key_path", ""))
        )
        path = "containerDefinitions[].secrets[].valueFrom"
        assert multi == [(_TASK_DEF_TYPE, REF_PARAMETER, path), (_TASK_DEF_TYPE, REFERENCES_SM, path)]

    def test_a_path_with_two_lists_is_present_once_its_first_list_is(self):
        assert _path_present({"containerDefinitions": [{"name": "a"}]}, "containerDefinitions[].secrets[].valueFrom")
        assert not _path_present({}, "containerDefinitions[].secrets[].valueFrom")
        assert _path_present({"Statement": [{}]}, "Statement[].Principal.Federated")  # one list: unchanged

    def test_the_secret_value_is_never_read(self):
        """The edge comes from the definition's text; no Secrets Manager call is named by the ECS code."""
        from pathlib import Path

        import tap_plugin.aws_core.collectors.boto3_collector.ecs as ecs_module

        source = Path(ecs_module.__file__).read_text()
        assert "get_secret_value" not in source and "GetSecretValue" not in source


@pytest.mark.spec("req-aws-collector-ecs-27")
class TestReferencesParameter:
    @pytest.mark.parametrize(
        ("value", "parameter"),
        [
            (_PARAM_ARN, _PARAM_ARN),
            ("/prod/feature-flags", _PARAM_BY_NAME),
            ("plain-name", f"arn:aws:ssm:{_REGION}:{_ACCOUNT}:parameter/plain-name"),
            (f"arn:aws:ssm:{_REGION}:{_ACCOUNT}:document/x", None),
            (_SM_ARN, None),
            ("bad name", None),
            ("/", None),
            ("", None),
        ],
    )
    def test_value_from_maps_to_the_parameter_arn(self, value, parameter):
        assert ssm_parameter_arn(value, source_key=_ACTIVE) == parameter

    def test_a_name_takes_the_definitions_own_partition_region_and_account(self):
        gov = f"arn:aws-us-gov:ecs:us-gov-west-1:{_ACCOUNT}:task-definition/web:1"
        assert ssm_parameter_arn("/a/b", source_key=gov) == f"arn:aws-us-gov:ssm:us-gov-west-1:{_ACCOUNT}:parameter/a/b"
        assert ssm_parameter_arn("/a/b", source_key="not-an-arn") is None

    def test_one_edge_per_parameter(self):
        td = node_ref(_TASK_DEF_TYPE, _ACTIVE)
        assert _emitted(_TASK_DEF_TYPE, _definition(_ACTIVE, secrets=_SECRETS), REF_PARAMETER) == sorted(
            [(td, node_ref(_PARAMETER_TYPE, _PARAM_ARN)), (td, node_ref(_PARAMETER_TYPE, _PARAM_BY_NAME))]
        )
        assert _reads(_TASK_DEF_TYPE, _definition(_ACTIVE, secrets=_SECRETS))[(REF_PARAMETER, "outbound")] == "complete"


@pytest.mark.spec("req-aws-collector-ecs-28")
class TestStoredAsBefore:
    def test_environment_values_are_kept_and_the_redaction_is_unchanged(self):
        """Ruled on #95: environment values stay stored; the only redaction is the existing one."""
        entry = _entry(_TASK_DEF_TYPE)
        node = project_item(entry, _definition(_ACTIVE, secrets=_SECRETS), {"region": _REGION})
        stored = json.dumps(
            node_envelope(node, {}, {}, persist_configuration=entry["persist_configuration"], redact_paths=entry_redact_paths(entry))
        )
        assert _PLAIN_ENV_CANARY in stored
        assert _SECRETISH_ENV_CANARY not in stored  # secret-named variable: the existing key-name rule
        assert _SM_ARN in stored and _PARAM_ARN in stored  # secrets[].valueFrom is a reference, kept
        assert entry_redact_paths(entry) == ["containerDefinitions[].repositoryCredentials"]

    def test_the_docstring_and_the_basis_say_what_is_stored(self):
        from tap_grid.registry import get_model_class

        doc = get_model_class(_TASK_DEF_TYPE).__doc__ or ""
        basis = _entry(_TASK_DEF_TYPE)["sensitivity"]["basis"]
        assert "not stored" not in doc and "Nothing beyond identity" not in basis
        assert "configuration" in doc and "environment" in doc
        assert "stored as configuration" in basis


# --- the whole run, imported through core ----------------------------------------------------------------------------

_stub_aws = slice_tests._stub_aws


@pytest.fixture
def _ecs_chain(monkeypatch):
    """The slice's task names a deregistered revision, its service the ACTIVE one; the ACTIVE one names a secret and
    a parameter the run also lists."""
    canned = slice_tests._CANNED
    tasks = json.loads(json.dumps(canned["describe_tasks"]))
    tasks["tasks"][0]["taskDefinitionArn"] = _INACTIVE
    services = json.loads(json.dumps(canned["describe_services"]))
    services["services"][0]["taskDefinition"] = _ACTIVE
    monkeypatch.setitem(canned, "describe_tasks", tasks)
    monkeypatch.setitem(canned, "describe_services", services)
    monkeypatch.setitem(canned, "list_task_definitions", {"taskDefinitionArns": [_ACTIVE]})
    monkeypatch.setitem(
        canned, "list_secrets", {"SecretList": [{"ARN": _SM_ARN, "Name": "prod/db"}, {"ARN": _OTHER_SM_ARN, "Name": "prod/api-key"}]}
    )
    monkeypatch.setitem(
        canned,
        "describe_parameters",
        {
            "Parameters": [
                {"ARN": _PARAM_ARN, "Name": "/prod/db/host", "Type": "String", "Tier": "Standard"},
                {"ARN": _PARAM_BY_NAME, "Name": "/prod/feature-flags", "Type": "String", "Tier": "Standard"},
            ]
        },
    )
    definitions = {
        _ACTIVE: _definition(_ACTIVE, secrets=_SECRETS),
        _INACTIVE: _definition(_INACTIVE, status="INACTIVE"),
    }

    def describe_task_definition(self, **kwargs):
        return {"taskDefinition": definitions[kwargs["taskDefinition"]], "tags": []}

    monkeypatch.setattr(slice_tests._CannedClient, "describe_task_definition", describe_task_definition, raising=False)


def _run():
    from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector

    collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
    collector.run()
    assert collector.results["error"] == []
    return collector


@pytest.mark.django_db
@pytest.mark.usefixtures("_stub_aws", "_ecs_chain")
@pytest.mark.spec("req-aws-collector-ecs-24", "req-aws-collector-ecs-25", "req-aws-collector-ecs-26", "req-aws-collector-ecs-27")
class TestImportedThroughCore:
    def test_the_chain_from_service_to_secret_lands(self):
        from tap_grid.services import get_node

        _run()
        active, inactive = node_id(_TASK_DEF_TYPE, _ACTIVE), node_id(_TASK_DEF_TYPE, _INACTIVE)
        assert get_node(inactive).configuration["status"] == "INACTIVE"  # described although not listed
        task = node_id(_TASK_TYPE, slice_tests._ECS_TASK)
        service = node_id(_SERVICE_TYPE, slice_tests._ECS_SERVICE)
        assert len(live_edges(USES, task, inactive)) == 1
        assert len(live_edges(USES, service, active)) == 1
        for secret in (_SM_ARN, _OTHER_SM_ARN):
            (edge,) = live_edges(REFERENCES_SM, active, node_id(_SM_TYPE, secret))
            assert edge.properties == {}
        for parameter in (_PARAM_ARN, _PARAM_BY_NAME):
            assert len(live_edges(REF_PARAMETER, active, node_id(_PARAMETER_TYPE, parameter))) == 1
        assert live_edges(REFERENCES_SM, inactive, node_id(_SM_TYPE, _SM_ARN)) == []

    def test_a_rerun_adds_no_edge(self):
        from tap_grid.models import Edge

        _run()
        count = Edge.objects.filter(edge_type__in=[USES, REFERENCES_SM, REF_PARAMETER], entity__deleted_at__isnull=True).count()
        _run()
        assert count == 6
        assert Edge.objects.filter(edge_type__in=[USES, REFERENCES_SM, REF_PARAMETER], entity__deleted_at__isnull=True).count() == count

    def test_the_stored_definition_keeps_plain_environment_values(self):
        from tap_grid.services import get_node

        _run()
        stored = json.dumps(get_node(node_id(_TASK_DEF_TYPE, _ACTIVE)).configuration)
        assert _PLAIN_ENV_CANARY in stored and _SECRETISH_ENV_CANARY not in stored

    def test_a_secret_the_run_did_not_list_is_skipped_not_minted(self, monkeypatch):
        monkeypatch.setitem(slice_tests._CANNED, "list_secrets", {"SecretList": [{"ARN": _SM_ARN, "Name": "prod/db"}]})
        _run()
        assert find_node_id(_SM_TYPE, _OTHER_SM_ARN) is None
        assert len(live_edges(REFERENCES_SM, node_id(_TASK_DEF_TYPE, _ACTIVE), node_id(_SM_TYPE, _SM_ARN))) == 1
