"""The ECS retirement path (aws-core-tap#211): containment, the per-parent surfaces the walk records, and the
task and container falsifiers (``req-aws-collector-ecs-17`` .. ``-19``, ``req-aws-core-contained-type-triple``).

Surfaces are checked on the walk with a faked ECS client; the falsifiers run core's four proof cases
(``req-grid-reconcile-falsifier-6``) against real grid rows and a faked ``DescribeTasks``.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import tomllib
from botocore.exceptions import ClientError
from django.utils.module_loading import import_string
from tap_plugin.aws_core.collectors.boto3_collector.ecs import (
    CLUSTER_TYPE,
    CONTAINMENT_SURFACES,
    RUNS_CONTAINER,
    RUNS_TASK,
    TASK_TYPE,
    walk_ecs,
)
from tap_plugin.aws_core.collectors.boto3_collector.listing import surface_statement
from tap_plugin.aws_core.falsifiers import (
    EcsContainerFalsifier,
    EcsTaskFalsifier,
    _ecs_cluster_of_task,
    _ecs_task_of_container,
)
from tap_plugin.aws_core.tests.test_boto3_collector_ecs import _CLUSTER, _FakeEcs, _task

from tap.plugin_testing import find_plugin_source_root
from tap_grid.falsifier_testing import CASE_DROPPED, CASE_FORBIDDEN, CASE_PRESENT, CASE_REIDENTIFIED, run_four_cases
from tap_grid.falsifiers import (
    DROPPED_FROM_OBSERVATION,
    PRESENT_AT_PROBE,
    UNDETERMINED,
    Candidate,
    FalsifyContext,
    unsupported,
)
from tap_grid.services import create_node, get_node

REGION = "us-east-1"
ACCOUNT_ID = "111122223333"
OTHER_ACCOUNT_ID = "999988887777"
TASK = "aws_core__aws_ecs_task"
CONTAINER = "aws_core__aws_ecs_container"


def _task_arn(task_id: str, cluster: str = "prod") -> str:
    return f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:task/{cluster}/{task_id}"


def _container_arn(task_id: str, container_id: str, cluster: str = "prod") -> str:
    return f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:container/{cluster}/{task_id}/{container_id}"


def _surfaces(walk) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {
        (listing.parent_type, listing.parent_key, listing.edge_type): surface_statement(
            listing.walk, relation=listing.relation, edge_type=listing.edge_type, subject="s", applied_batches=[]
        )
        for listing in walk.listings
    }


# --- containment and surfaces ----------------------------------------------------------------------------------


class TestContainmentDeclarations:
    @pytest.mark.spec("req-aws-core-contained-type-triple-1", "req-aws-collector-ecs-17")
    def test_reader_surfaces_mirror_model_containment(self) -> None:
        from tap_grid.registry import get_model_class

        for entity_type, edges in CONTAINMENT_SURFACES.items():
            assert tuple(get_model_class(entity_type).CONTAINMENT_EDGES) == edges, entity_type

    @pytest.mark.spec("req-aws-collector-ecs-17")
    def test_a_service_does_not_contain_tasks(self) -> None:
        """RUNS_TASK from a service is a reference: only the cluster's listing decides a task's candidacy."""
        from tap_grid.registry import get_model_class

        assert tuple(getattr(get_model_class("aws_core__aws_ecs_service"), "CONTAINMENT_EDGES", ()) or ()) == ()


@pytest.mark.spec("req-aws-core-contained-type-triple-1", "req-aws-collector-ecs-18")
class TestEveryParentHasASurface:
    def test_every_observed_parent_has_a_surface_for_every_containment_edge(self) -> None:
        walk = walk_ecs(_FakeEcs())
        recorded = set(_surfaces(walk))
        checked = 0
        for cluster in walk.clusters:
            assert (CLUSTER_TYPE, cluster["clusterArn"], RUNS_TASK) in recorded
            checked += 1
        for task in walk.tasks:
            assert (TASK_TYPE, task["taskArn"], RUNS_CONTAINER) in recorded
            checked += 1
        assert checked == 2

    def test_relations_are_named(self) -> None:
        walk = walk_ecs(_FakeEcs())
        assert {(listing.edge_type, listing.relation) for listing in walk.listings} == {
            (RUNS_TASK, "ecs_cluster.tasks"),
            (RUNS_CONTAINER, "ecs_task.containers"),
        }


@pytest.mark.spec("req-aws-collector-ecs-18")
class TestClusterTaskSurface:
    def test_a_read_listing_is_complete_and_counts_the_running_tasks(self) -> None:
        surface = _surfaces(walk_ecs(_FakeEcs()))[(CLUSTER_TYPE, _CLUSTER, RUNS_TASK)]
        assert surface["enumeration_complete"] is True
        assert surface["scope_authorized"] is True
        assert surface["admitted"] is True
        assert surface["count_observed"] == 1

    @pytest.mark.spec("req-aws-core-contained-type-triple-2")
    def test_a_cluster_with_no_running_task_is_complete_empty(self) -> None:
        surface = _surfaces(walk_ecs(_FakeEcs(tasks={})))[(CLUSTER_TYPE, _CLUSTER, RUNS_TASK)]
        assert surface["enumeration_complete"] is True
        assert surface["count_observed"] == 0

    @pytest.mark.spec("req-aws-core-contained-type-triple-3")
    def test_a_denied_listing_is_recorded_incomplete_never_omitted(self) -> None:
        surface = _surfaces(walk_ecs(_FakeEcs(deny={"list_tasks"})))[(CLUSTER_TYPE, _CLUSTER, RUNS_TASK)]
        assert surface["enumeration_complete"] is False
        assert surface["scope_authorized"] is False
        assert surface["reasons"]["enumeration_complete"].startswith("access_denied")

    @pytest.mark.spec("req-aws-core-contained-type-triple-3")
    def test_a_short_listing_is_incomplete(self) -> None:
        class _Short(_FakeEcs):
            def get_paginator(self, method):
                inner = super().get_paginator(method)

                class _P:
                    def paginate(self, **kwargs):
                        if method == "list_tasks" and kwargs.get("desiredStatus") == "RUNNING":
                            return iter([{"taskArns": [], "nextToken": "more"}])
                        return inner.paginate(**kwargs)

                return _P()

        walk = walk_ecs(_Short())
        surface = _surfaces(walk)[(CLUSTER_TYPE, _CLUSTER, RUNS_TASK)]
        assert surface["enumeration_complete"] is False
        assert surface["admitted"] is False
        assert walk.tasks == []

    def test_the_stopped_listing_records_no_surface(self) -> None:
        """Only the running listing decides containment; the stopped one only records state (``-15``)."""
        walk = walk_ecs(_FakeEcs(stopped={_task_arn("gone"): {**_task(_task_arn("gone")), "lastStatus": "STOPPED"}}))
        assert [key for key in _surfaces(walk) if key[0] == CLUSTER_TYPE] == [(CLUSTER_TYPE, _CLUSTER, RUNS_TASK)]


@pytest.mark.spec("req-aws-collector-ecs-18")
class TestTaskContainerSurface:
    def test_a_described_task_lists_its_containers_completely(self) -> None:
        walk = walk_ecs(_FakeEcs())
        surface = _surfaces(walk)[(TASK_TYPE, walk.tasks[0]["taskArn"], RUNS_CONTAINER)]
        assert surface["enumeration_complete"] is True
        assert surface["count_observed"] == 1

    @pytest.mark.spec("req-aws-core-contained-type-triple-3")
    def test_a_task_that_was_not_described_has_an_incomplete_container_surface(self) -> None:
        walk = walk_ecs(_FakeEcs(deny={"describe_tasks"}))
        surface = _surfaces(walk)[(TASK_TYPE, walk.tasks[0]["taskArn"], RUNS_CONTAINER)]
        assert surface["enumeration_complete"] is False
        assert surface["scope_authorized"] is False
        assert surface["reasons"]["enumeration_complete"].startswith("describe_failed")

    def test_a_container_without_an_arn_is_complete_but_not_admitted(self) -> None:
        task = _task()
        task["containers"].append({"name": "sidecar", "image": "x"})
        walk = walk_ecs(_FakeEcs(tasks={task["taskArn"]: task}))
        surface = _surfaces(walk)[(TASK_TYPE, task["taskArn"], RUNS_CONTAINER)]
        assert surface["enumeration_complete"] is True
        assert surface["admitted"] is False


# --- falsifiers ------------------------------------------------------------------------------------------------


class FakeEcsProbe:
    """A faked ``ecs`` client: ``describe_tasks(cluster, tasks)`` answered per task ARN from ``answers`` (a task,
    or a failure reason string), with ``renamed`` returning a task under another ARN and ``denied`` clusters
    refusing the whole call."""

    def __init__(self) -> None:
        self.answers: dict[str, dict[str, Any] | str] = {}
        self.renamed: dict[str, dict[str, Any]] = {}
        self.denied: set[str] = set()
        self.calls: list[tuple[str, list[str]]] = []

    def describe_tasks(self, cluster: str, tasks: list[str]) -> dict[str, Any]:
        self.calls.append((cluster, list(tasks)))
        if cluster in self.denied:
            raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "DescribeTasks")
        found: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for arn in tasks:
            if arn in self.renamed:
                found.append(self.renamed[arn])
                continue
            answer = self.answers.get(arn, "MISSING")
            if isinstance(answer, str):
                failures.append({"arn": arn, "reason": answer})
            else:
                found.append(answer)
        return {"tasks": found, "failures": failures}


class FakeSession:
    def __init__(self, ecs: FakeEcsProbe) -> None:
        self._ecs = ecs

    def client(self, service: str, region_name: str | None = None) -> Any:
        assert service == "ecs" and region_name == REGION, (service, region_name)
        return self._ecs


def _described(task_arn: str, *, status: str = "RUNNING", containers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"taskArn": task_arn, "lastStatus": status, "containers": containers or []}


def _row(entity_type: str, fields: dict[str, Any], *, account_id: str = ACCOUNT_ID) -> uuid.UUID:
    result = create_node(entity_type, fields)
    assert result.success, result.errors
    entity_id = uuid.UUID(str(result.entity_id))
    row = get_node(entity_id)
    row.entity.dimensions = {"cloud": "aws", "aws_account": account_id, "aws_region": REGION}
    row.entity.save(update_fields=["dimensions"])
    return entity_id


def _task_row(task_arn: str, **kw: Any) -> uuid.UUID:
    return _row(TASK, {"task_arn": task_arn, "name": task_arn.rsplit("/", 1)[-1]}, **kw)


def _container_row(container_arn: str, name: str = "app", **kw: Any) -> uuid.UUID:
    return _row(CONTAINER, {"container_arn": container_arn, "name": name}, **kw)


def _candidate(entity_id: uuid.UUID, entity_type: str) -> Candidate:
    return Candidate(
        entity_id=entity_id,
        entity_type=entity_type,
        reason="dropped_from_observation",
        surface=0,
        relation="fixture",
        subject=None,
        edge_type=None,
        parent=None,
        interval_first=None,
    )


def _context() -> FalsifyContext:
    return FalsifyContext(batch_id=str(uuid.uuid4()), statement=None)


def _supported(verdicts: dict[str, Any]) -> None:
    for case, verdict in verdicts.items():
        assert unsupported(verdict) is None, f"{case}: {unsupported(verdict)}"


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-ecs-19")
class TestEcsTaskFalsifier:
    @pytest.mark.spec("req-grid-reconcile-falsifier-6")
    def test_four_cases(self) -> None:
        ecs = FakeEcsProbe()
        present, dropped = _task_arn("present"), _task_arn("dropped")
        forbidden, reborn = _task_arn("forbidden", "locked"), _task_arn("reborn", "moved")
        ecs.answers[present] = _described(present)
        ecs.answers[dropped] = "MISSING"
        ecs.denied.add("locked")
        ecs.renamed[reborn] = _described(_task_arn("reborn-long-form", "moved"))
        cases = {
            CASE_PRESENT: _candidate(_task_row(present), TASK),
            CASE_DROPPED: _candidate(_task_row(dropped), TASK),
            CASE_FORBIDDEN: _candidate(_task_row(forbidden), TASK),
            CASE_REIDENTIFIED: _candidate(_task_row(reborn), TASK),
        }
        verdicts = run_four_cases(EcsTaskFalsifier(session=FakeSession(ecs), account_id=ACCOUNT_ID), cases, _context())
        _supported(verdicts)

    def test_a_stopped_task_is_gone(self) -> None:
        ecs = FakeEcsProbe()
        arn = _task_arn("stopped")
        ecs.answers[arn] = _described(arn, status="STOPPED")
        [verdict] = EcsTaskFalsifier(session=FakeSession(ecs), account_id=ACCOUNT_ID).batch_falsify(
            [_candidate(_task_row(arn), TASK)], _context()
        )
        assert verdict.verdict == DROPPED_FROM_OBSERVATION

    def test_an_unexplained_failure_is_undetermined_never_absence(self) -> None:
        ecs = FakeEcsProbe()
        arn = _task_arn("odd")
        ecs.answers[arn] = "SomethingElse"
        [verdict] = EcsTaskFalsifier(session=FakeSession(ecs), account_id=ACCOUNT_ID).batch_falsify(
            [_candidate(_task_row(arn), TASK)], _context()
        )
        assert verdict.verdict == UNDETERMINED

    def test_candidates_are_probed_100_per_call_per_cluster(self) -> None:
        """A deploy can replace every task at once: the probe budget is one call per 100, not one per task."""
        ecs = FakeEcsProbe()
        candidates = []
        for i in range(103):
            arn = _task_arn(f"t{i:03d}")
            ecs.answers[arn] = "MISSING"
            candidates.append(_candidate(_task_row(arn), TASK))
        other = _task_arn("elsewhere", "staging")
        ecs.answers[other] = "MISSING"
        candidates.append(_candidate(_task_row(other), TASK))
        verdicts = EcsTaskFalsifier(session=FakeSession(ecs), account_id=ACCOUNT_ID).batch_falsify(candidates, _context())
        assert all(v.verdict == DROPPED_FROM_OBSERVATION for v in verdicts)
        assert sorted((cluster, len(arns)) for cluster, arns in ecs.calls) == [("prod", 3), ("prod", 100), ("staging", 1)]

    def test_an_arn_that_names_no_cluster_is_not_probed(self) -> None:
        ecs = FakeEcsProbe()
        arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:task/0123456789abcdef"  # the older short form
        [verdict] = EcsTaskFalsifier(session=FakeSession(ecs), account_id=ACCOUNT_ID).batch_falsify(
            [_candidate(_task_row(arn), TASK)], _context()
        )
        assert verdict.verdict == UNDETERMINED and verdict.reason == "scope_unknown"
        assert ecs.calls == []

    def test_another_accounts_task_is_not_probed(self) -> None:
        ecs = FakeEcsProbe()
        arn = _task_arn("theirs")
        [verdict] = EcsTaskFalsifier(session=FakeSession(ecs), account_id=ACCOUNT_ID).batch_falsify(
            [_candidate(_task_row(arn, account_id=OTHER_ACCOUNT_ID), TASK)], _context()
        )
        assert verdict.verdict == UNDETERMINED and verdict.reason == "scope_unknown"
        assert ecs.calls == []


@pytest.mark.django_db
@pytest.mark.spec("req-aws-collector-ecs-19")
class TestEcsContainerFalsifier:
    @pytest.mark.spec("req-grid-reconcile-falsifier-6")
    def test_four_cases(self) -> None:
        ecs = FakeEcsProbe()
        live, done = _task_arn("live"), _task_arn("done")
        locked = _task_arn("locked-task", "locked")
        present, dropped = _container_arn("live", "c1"), _container_arn("done", "c1")
        forbidden = _container_arn("locked-task", "c1", "locked")
        reborn = _container_arn("live", "c-old")
        ecs.answers[live] = _described(
            live,
            containers=[
                {"containerArn": present, "name": "app"},
                {"containerArn": _container_arn("live", "c-new"), "name": "sidecar"},
            ],
        )
        ecs.answers[done] = _described(done, status="STOPPED", containers=[{"containerArn": dropped, "name": "app"}])
        ecs.denied.add("locked")
        cases = {
            CASE_PRESENT: _candidate(_container_row(present, "app"), CONTAINER),
            CASE_DROPPED: _candidate(_container_row(dropped, "app"), CONTAINER),
            CASE_FORBIDDEN: _candidate(_container_row(forbidden, "app"), CONTAINER),
            CASE_REIDENTIFIED: _candidate(_container_row(reborn, "sidecar"), CONTAINER),
        }
        verdicts = run_four_cases(
            EcsContainerFalsifier(session=FakeSession(ecs), account_id=ACCOUNT_ID), cases, _context()
        )
        _supported(verdicts)
        assert ("locked", [locked]) in ecs.calls  # the refused call covered only its own cluster's task

    def test_a_container_its_running_task_no_longer_lists_is_gone(self) -> None:
        ecs = FakeEcsProbe()
        task = _task_arn("live")
        ecs.answers[task] = _described(task, containers=[{"containerArn": _container_arn("live", "other"), "name": "x"}])
        [verdict] = EcsContainerFalsifier(session=FakeSession(ecs), account_id=ACCOUNT_ID).batch_falsify(
            [_candidate(_container_row(_container_arn("live", "c1"), "app"), CONTAINER)], _context()
        )
        assert verdict.verdict == DROPPED_FROM_OBSERVATION

    def test_containers_of_one_task_share_one_call(self) -> None:
        ecs = FakeEcsProbe()
        task = _task_arn("multi")
        arns = [_container_arn("multi", f"c{i}") for i in range(3)]
        ecs.answers[task] = _described(task, containers=[{"containerArn": a, "name": f"n{i}"} for i, a in enumerate(arns)])
        verdicts = EcsContainerFalsifier(session=FakeSession(ecs), account_id=ACCOUNT_ID).batch_falsify(
            [_candidate(_container_row(a, f"n{i}"), CONTAINER) for i, a in enumerate(arns)], _context()
        )
        assert [v.verdict for v in verdicts] == [PRESENT_AT_PROBE] * 3
        assert ecs.calls == [("prod", [task])]

    def test_an_older_container_arn_is_not_probed(self) -> None:
        ecs = FakeEcsProbe()
        arn = f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:container/0123456789abcdef"
        [verdict] = EcsContainerFalsifier(session=FakeSession(ecs), account_id=ACCOUNT_ID).batch_falsify(
            [_candidate(_container_row(arn), CONTAINER)], _context()
        )
        assert verdict.verdict == UNDETERMINED and verdict.reason == "scope_unknown"


class TestArnParsing:
    def test_container_arn_names_its_task(self) -> None:
        assert _ecs_task_of_container(_container_arn("t1", "c1")) == _task_arn("t1")
        assert _ecs_task_of_container(f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:container/abc") is None

    def test_task_arn_names_its_cluster(self) -> None:
        assert _ecs_cluster_of_task(_task_arn("t1", "blue")) == "blue"
        assert _ecs_cluster_of_task(f"arn:aws:ecs:{REGION}:{ACCOUNT_ID}:task/abc") is None


@pytest.mark.spec("req-aws-collector-ecs-19")
def test_both_falsifiers_are_registered() -> None:
    root = find_plugin_source_root(__file__)
    assert root is not None, "plugin source tree not found"
    manifest = tomllib.loads(next((root / "tap_plugin").glob("*/tap-plugin.toml")).read_text())
    falsifiers = manifest["falsifiers"]
    assert import_string(falsifiers[TASK]) is EcsTaskFalsifier
    assert import_string(falsifiers[CONTAINER]) is EcsContainerFalsifier
