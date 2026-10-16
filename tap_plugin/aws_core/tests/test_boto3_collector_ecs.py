"""ECS collection: the walk, the four custom_fns, the container digest and the manifest entries.

Spec: specs/spec-aws-core-collector-v0.md (req-aws-collector-ecs). Faked boto3 clients only; the live
trial is deferred (test_trial_run_live.py, _ECS_DEFERRED).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core import models as models_pkg
from tap_plugin.aws_core.collectors.boto3_collector.authority import EDGE_READS
from tap_plugin.aws_core.collectors.boto3_collector.batch import node_envelope
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    ecs_clusters_described,
    ecs_containers_described,
    ecs_services_described,
    ecs_tasks_described,
)
from tap_plugin.aws_core.collectors.boto3_collector.ecs import _WALKS, walk_ecs
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
from tap_plugin.aws_core.collectors.boto3_collector.source import SourceError

pytestmark = pytest.mark.spec("req-aws-collector-ecs")

_REGION = "us-east-1"
_ACCOUNT = "111122223333"
_CLUSTER = f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:cluster/prod"
_SERVICE = f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:service/prod/web"
_TASK = f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:task/prod/aaaa1111"
_ADHOC_TASK = f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:task/prod/bbbb2222"
_CONTAINER = f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:container/prod/aaaa1111/c1"
_DIGEST = "sha256:" + "ab" * 32
_ENV_CANARY = "ECS-ENV-CANARY-9f3a"
_CMD_CANARY = "ECS-CMD-CANARY-77c1"


def _error(code: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, op)


def _task(arn: str = _TASK, *, group: str = "service:web", digest: str | None = _DIGEST, container_arn: str = _CONTAINER):
    container: dict[str, Any] = {
        "containerArn": container_arn,
        "taskArn": arn,
        "name": "app",
        "image": "registry.example/app:latest",
        "runtimeId": "rt-1",
        "lastStatus": "RUNNING",
    }
    if digest is not None:
        container["imageDigest"] = digest
    return {
        "taskArn": arn,
        "clusterArn": _CLUSTER,
        "taskDefinitionArn": f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:task-definition/app:3",
        "lastStatus": "RUNNING",
        "desiredStatus": "RUNNING",
        "launchType": "FARGATE",
        "platformVersion": "1.4.0",
        "group": group,
        "startedAt": datetime(2026, 10, 15, 12, 0, tzinfo=UTC),
        "tags": [{"key": "team", "value": "core"}],
        "containers": [container],
        "overrides": {
            "containerOverrides": [
                {"name": "app", "environment": [{"name": "TOKEN", "value": _ENV_CANARY}], "command": [_CMD_CANARY]}
            ]
        },
    }


class _Session:
    """A weakly referenceable stand-in for the run's boto3 session (a SimpleNamespace is not)."""


class _FakeEcs:
    """A faked ECS client. ``deny`` names methods that raise AccessDenied; ``calls`` records every call."""

    meta = SimpleNamespace(region_name=_REGION)

    def __init__(self, *, tasks=None, deny=(), task_pages=1, failures=None):
        self.tasks = tasks if tasks is not None else {_TASK: _task()}
        self.deny = set(deny)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.task_pages = task_pages
        self.failures = failures or {}

    def can_paginate(self, method: str) -> bool:
        return method in {"list_clusters", "list_services", "list_tasks"}

    def get_paginator(self, method: str):
        outer = self

        class _Paginator:
            def paginate(self, **kwargs):
                outer._record(method, kwargs)
                key, arns = {
                    "list_clusters": ("clusterArns", [_CLUSTER]),
                    "list_services": ("serviceArns", [_SERVICE]),
                    "list_tasks": ("taskArns", list(outer.tasks)),
                }[method]
                if method == "list_tasks" and outer.task_pages > 1:
                    half = max(1, len(arns) // outer.task_pages)
                    return iter([{key: arns[i : i + half]} for i in range(0, len(arns), half)])
                return iter([{key: arns}])

        return _Paginator()

    def _record(self, method: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((method, kwargs))
        if method in self.deny:
            raise _error("AccessDeniedException", method)

    def describe_clusters(self, **kwargs):
        self._record("describe_clusters", kwargs)
        return {"clusters": [{"clusterArn": _CLUSTER, "clusterName": "prod", "status": "ACTIVE", "tags": []}]}

    def describe_services(self, **kwargs):
        self._record("describe_services", kwargs)
        return {
            "services": [
                {
                    "serviceArn": _SERVICE,
                    "serviceName": "web",
                    "clusterArn": _CLUSTER,
                    "status": "ACTIVE",
                    "desiredCount": 1,
                    "runningCount": 1,
                    "launchType": "FARGATE",
                    "tags": [],
                }
            ]
        }

    def describe_tasks(self, **kwargs):
        self._record("describe_tasks", kwargs)
        found = [self.tasks[a] for a in kwargs["tasks"] if a in self.tasks and a not in self.failures]
        failures = [{"arn": a, "reason": r} for a, r in self.failures.items() if a in kwargs["tasks"]]
        return {"tasks": found, "failures": failures}


def _walk(fake: _FakeEcs | None = None):
    fake = fake or _FakeEcs()
    return fake, walk_ecs(fake)


def _calls(fake: _FakeEcs, method: str) -> list[dict[str, Any]]:
    return [kw for name, kw in fake.calls if name == method]


class TestCallShape:
    def test_calls_and_include_tags(self):
        """req-aws-collector-ecs-2"""
        fake, _ = _walk()
        assert _calls(fake, "list_clusters") == [{}]
        assert _calls(fake, "describe_clusters")[0]["include"] == ["TAGS"]
        assert _calls(fake, "list_services") == [{"cluster": _CLUSTER}]
        assert _calls(fake, "describe_services")[0] == {"services": [_SERVICE], "cluster": _CLUSTER, "include": ["TAGS"]}
        assert _calls(fake, "list_tasks") == [{"cluster": _CLUSTER, "desiredStatus": "RUNNING"}]
        assert _calls(fake, "describe_tasks")[0]["include"] == ["TAGS"]

    def test_describe_batches_respect_aws_maximums(self):
        """req-aws-collector-ecs-2: 100 tasks and 10 services per call."""
        many = {f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:task/prod/{i:04d}": _task() for i in range(250)}
        for arn, task in many.items():
            many[arn] = {**task, "taskArn": arn, "containers": []}
        fake, walk = _walk(_FakeEcs(tasks=many))
        sizes = [len(kw["tasks"]) for kw in _calls(fake, "describe_tasks")]
        assert sizes == [100, 100, 50]
        assert len(walk.tasks) == 250

    def test_every_page_of_a_listing_is_read(self):
        """req-aws-collector-ecs-2: a paginated ListTasks is read to its end."""
        many = {f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:task/prod/{i}": {**_task(), "containers": []} for i in range(6)}
        for arn in many:
            many[arn]["taskArn"] = arn
        _, walk = _walk(_FakeEcs(tasks=many, task_pages=3))
        assert len(walk.tasks) == 6


class TestContainerNode:
    def test_container_carries_image_and_digest_verbatim(self):
        """req-aws-collector-ecs-3, -4"""
        _, walk = _walk()
        (container,) = walk.containers
        assert container["containerArn"] == _CONTAINER
        assert container["image"] == "registry.example/app:latest"
        assert container["imageDigest"] == _DIGEST
        assert container["_task_arn"] == _TASK

    @pytest.mark.parametrize("digest", [None, ""])
    def test_unreported_digest_is_null_never_empty(self, digest):
        """req-aws-collector-ecs-5"""
        _, walk = _walk(_FakeEcs(tasks={_TASK: _task(digest=digest)}))
        (container,) = walk.containers
        entry = _entry("aws_core__aws_ecs_container")
        node = project_item(entry, container)
        assert node.fields["image_digest"] is None
        assert node.fields["image"] == "registry.example/app:latest"  # the tag is not copied into the digest

    def test_no_registry_call_is_made(self):
        """req-aws-collector-ecs-4: the only client the walk touches is ECS."""
        fake, _ = _walk()
        assert {name for name, _ in fake.calls} <= {
            "list_clusters",
            "describe_clusters",
            "list_services",
            "describe_services",
            "list_tasks",
            "describe_tasks",
        }

    def test_container_item_carries_no_overrides(self):
        _, walk = _walk()
        assert "overrides" not in json.dumps(walk.containers)


class TestTaskFields:
    def test_task_projection(self):
        """req-aws-collector-ecs-6"""
        _, walk = _walk()
        node = project_item(_entry("aws_core__aws_ecs_task"), walk.tasks[0])
        assert node.fields["cluster_arn"] == _CLUSTER
        assert node.fields["last_status"] == "RUNNING"
        assert node.fields["desired_status"] == "RUNNING"
        assert node.fields["platform_version"] == "1.4.0"
        assert node.fields["group"] == "service:web"
        assert node.fields["started_at"] == "2026-10-15T12:00:00Z"
        assert node.fields["name"] == "aaaa1111"

    def test_unstarted_task_has_null_started_at(self):
        task = _task()
        del task["startedAt"]
        _, walk = _walk(_FakeEcs(tasks={_TASK: task}))
        assert project_item(_entry("aws_core__aws_ecs_task"), walk.tasks[0]).fields["started_at"] is None


class TestEdges:
    def test_service_launched_task_resolves_its_service(self):
        """req-aws-collector-ecs-8"""
        _, walk = _walk()
        task = walk.tasks[0]
        assert task["_service_arn"] == _SERVICE
        assert task[EDGE_READS] == {"clusterArn": "complete", "_service_arn": "complete"}

    def test_task_without_service_group_attaches_to_cluster_only(self):
        """req-aws-collector-ecs-8"""
        _, walk = _walk(_FakeEcs(tasks={_ADHOC_TASK: _task(_ADHOC_TASK, group="family:app")}))
        task = walk.tasks[0]
        assert task["_service_arn"] is None
        assert task[EDGE_READS]["_service_arn"] == "complete"

    def test_unresolved_service_is_a_partial_read_not_a_claim_of_none(self):
        _, walk = _walk(_FakeEcs(tasks={_TASK: _task(group="service:gone")}))
        assert walk.tasks[0]["_service_arn"] is None
        assert walk.tasks[0][EDGE_READS]["_service_arn"] == "partial"

    def test_manifest_declares_the_edge_rules(self):
        task_rules = {(r["edge_type"], r["value_path"], r["direction"]) for r in _entry("aws_core__aws_ecs_task")["edges"]}
        assert ("RUNS_TASK__aws_core", "clusterArn", "inbound") in task_rules
        assert ("RUNS_TASK__aws_core", "_service_arn", "inbound") in task_rules
        container_rules = _entry("aws_core__aws_ecs_container")["edges"]
        assert [(r["edge_type"], r["target_type"]) for r in container_rules] == [
            ("RUNS_CONTAINER__aws_core", "aws_core__aws_ecs_task")
        ]
        service_rules = _entry("aws_core__aws_ecs_service")["edges"]
        assert [r["edge_type"] for r in service_rules] == ["RUNS_SERVICE__aws_core"]


class TestDenialDegrades:
    def test_list_clusters_denied_skips_the_entry_rather_than_reading_clean(self):
        """req-aws-collector-ecs-10: the engine records a raised call as ENTRY_SKIPPED."""
        with pytest.raises(ClientError):
            walk_ecs(_FakeEcs(deny={"list_clusters"}))

    def test_describe_tasks_denied_keeps_the_task_with_a_gap(self):
        """req-aws-collector-ecs-10"""
        _, walk = _walk(_FakeEcs(deny={"describe_tasks"}))
        (task,) = walk.tasks
        assert task["taskArn"] == _TASK
        assert task["_hydrate"]["describe"]["status"] == "denied"
        assert task[EDGE_READS]["_service_arn"] == "partial"
        assert walk.containers == []  # no containerArn without a describe: nothing invented
        node = project_item(_entry("aws_core__aws_ecs_task"), task)
        assert node.fields["last_status"] is None and node.fields["group"] is None

    def test_list_tasks_denied_is_distinguishable_from_no_tasks(self):
        """req-aws-collector-ecs-10"""
        _, walk = _walk(_FakeEcs(deny={"list_tasks"}))
        assert walk.tasks == []
        assert walk.clusters[0]["_hydrate"]["tasks"]["status"] == "denied"
        _, empty = _walk(_FakeEcs(tasks={}))
        assert empty.clusters[0]["_hydrate"]["tasks"]["status"] == "ok"

    def test_describe_services_denied_keeps_services_and_tasks(self):
        _, walk = _walk(_FakeEcs(deny={"describe_services"}))
        (service,) = walk.services
        assert service["serviceArn"] == _SERVICE and service["_hydrate"]["describe"]["status"] == "denied"
        assert walk.tasks[0]["_service_arn"] == _SERVICE  # resolved from the listing, not the describe

    def test_list_services_denied_leaves_the_service_edge_partial(self):
        _, walk = _walk(_FakeEcs(deny={"list_services"}))
        assert walk.services == []
        assert walk.clusters[0]["_hydrate"]["services"]["status"] == "denied"
        assert walk.tasks[0][EDGE_READS]["_service_arn"] == "partial"

    def test_describe_failure_reason_other_than_missing_is_a_gap(self):
        _, walk = _walk(_FakeEcs(failures={_TASK: "BOOM"}))
        assert walk.tasks[0]["_hydrate"]["describe"] == {"status": "error", "op": "DescribeTasks", "error_code": "BOOM"}

    def test_missing_task_is_dropped_not_an_error(self):
        _, walk = _walk(_FakeEcs(failures={_TASK: "MISSING"}))
        assert walk.tasks == []


class TestSharedWalk:
    def test_four_custom_fns_share_one_set_of_calls(self):
        """The fan-out is made once per (session, region), not once per node type."""
        session = _Session()
        fake = _FakeEcs()
        client_for = lambda _service: fake  # noqa: E731
        try:
            assert [c["clusterArn"] for c in ecs_clusters_described(session, client_for=client_for)] == [_CLUSTER]
            assert [s["serviceArn"] for s in ecs_services_described(session, client_for=client_for)] == [_SERVICE]
            assert [t["taskArn"] for t in ecs_tasks_described(session, client_for=client_for)] == [_TASK]
            assert [c["containerArn"] for c in ecs_containers_described(session, client_for=client_for)] == [_CONTAINER]
            assert len(_calls(fake, "list_clusters")) == 1
            assert len(_calls(fake, "describe_tasks")) == 1
        finally:
            _WALKS.pop(session, None)

    def test_a_denied_walk_is_not_retried_by_each_entry(self):
        session = _Session()
        fake = _FakeEcs(deny={"list_clusters"})
        client_for = lambda _service: fake  # noqa: E731
        for fn in (ecs_clusters_described, ecs_services_described, ecs_tasks_described, ecs_containers_described):
            with pytest.raises(ClientError):
                list(fn(session, client_for=client_for))
        assert len(_calls(fake, "list_clusters")) == 1

    def test_incomplete_cluster_listing_is_a_skip_not_an_empty_region(self):
        class _Short(_FakeEcs):
            def get_paginator(self, method):
                class _P:
                    def paginate(self, **_kw):
                        return iter([{"clusterArns": [], "nextToken": "more"}])

                return _P()

        with pytest.raises(SourceError):
            walk_ecs(_Short())


class TestSensitivityAndConfiguration:
    def test_all_four_entries_keep_configuration_off(self):
        """req-aws-collector-ecs-9 (George, 2026-10-16: off)."""
        for entity_type in _ECS_TYPES:
            assert _entry(entity_type)["persist_configuration"] is False

    def test_task_declares_override_environment_and_command_as_credentials(self):
        """req-aws-collector-ecs-9"""
        locations = {
            loc["path"]: loc["category"] for loc in _entry("aws_core__aws_ecs_task")["sensitivity"]["locations"]
        }
        assert locations["overrides.containerOverrides[].environment"] == "credential"
        assert locations["overrides.containerOverrides[].command"] == "credential"

    def test_canary_never_reaches_the_node_envelope(self):
        """req-aws-collector-ecs-9: the planted canary is in the in-memory item and in no emitted payload."""
        _, walk = _walk()
        entry = _entry("aws_core__aws_ecs_task")
        node = project_item(entry, walk.tasks[0])
        assert _ENV_CANARY in json.dumps(node.raw_item, default=str) and _CMD_CANARY in json.dumps(node.raw_item, default=str)
        emitted = json.dumps(node_envelope(node, {}, {}, persist_configuration=entry["persist_configuration"]))
        assert _ENV_CANARY not in emitted and _CMD_CANARY not in emitted


_ECS_TYPES = [
    "aws_core__aws_ecs_cluster",
    "aws_core__aws_ecs_service",
    "aws_core__aws_ecs_task",
    "aws_core__aws_ecs_container",
]


def _entry(entity_type: str) -> dict[str, Any]:
    (entry,) = [e for e in manifest_entries() if e["entity_type"] == entity_type]
    return entry


_MODELS = {cls.ENTITY_TYPE: cls for cls in vars(models_pkg).values() if isinstance(cls, type) and hasattr(cls, "ENTITY_TYPE")}


def _schema(model) -> dict[str, Any]:
    properties = dict(model.FIELD_CRUD_SCHEMA)
    return {
        "type": "object",
        "properties": properties,
        "required": list(model.CREATE_REQUIRED),
        "additionalProperties": False,
    }


@pytest.mark.parametrize("entity_type", _ECS_TYPES)
def test_emitted_payload_satisfies_the_model_create_schema(entity_type):
    """req-aws-collector-ecs-7: the v0.4.0 trap, offline. `tags` and every projected field are declared."""
    _, walk = _walk()
    items = {
        "aws_core__aws_ecs_cluster": walk.clusters,
        "aws_core__aws_ecs_service": walk.services,
        "aws_core__aws_ecs_task": walk.tasks,
        "aws_core__aws_ecs_container": walk.containers,
    }[entity_type]
    entry = _entry(entity_type)
    node = project_item(entry, items[0])
    payload = node_envelope(node, {}, {"team": "core"}, persist_configuration=False)["node"]
    jsonschema.validate(payload, _schema(_MODELS[entity_type]))
    assert payload["configuration"] == {}


@pytest.mark.parametrize("entity_type", _ECS_TYPES)
def test_models_declare_tags_in_both_schemas(entity_type):
    """req-aws-collector-ecs-7 (the always-on guard in test_aws_core_tags_field.py derives from the manifest)."""
    model = _MODELS[entity_type]
    assert model.FIELD_CRUD_SCHEMA["tags"] == {"type": "object"}
    assert model.FIELD_VALIDATION_SCHEMA["tags"]["schema"] == {"type": "object"}


def test_ecs_tags_normalize_from_the_lowercase_wire_shape():
    from tap_plugin.aws_core.collectors.boto3_collector.tags import normalize_tags

    assert normalize_tags([{"key": "team", "value": "core"}, {"key": "empty"}], "list_kv_lower") == {
        "team": "core",
        "empty": "",
    }
    assert normalize_tags(None, "list_kv_lower") == {}


def test_no_cross_plugin_import():
    """req-aws-collector-ecs-14: no github_core or computing_core import and no digest matching here."""
    from pathlib import Path

    import tap_plugin.aws_core.collectors.boto3_collector.ecs as ecs_module

    source = Path(ecs_module.__file__).read_text()
    assert "github_core" not in source and "computing_core" not in source
