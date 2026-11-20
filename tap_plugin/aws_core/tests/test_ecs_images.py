"""The image an ECS container runs: computing_core's image host and tag, and the edges to them.

Spec: specs/spec-aws-core-collector-v0.md (req-aws-collector-ecs-20 .. -23, superseding -14).

The walk is driven through a real botocore ECS client under ``botocore.stub.Stubber``, so every request and
every canned response is checked against the ECS service model the pinned botocore ships. The grid tests run the
whole collector over the vertical slice's canned AWS and import the batch through core's GRIFT validation.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
import jsonschema
import pytest
from botocore.stub import Stubber
from tap_plugin.aws_core.collectors.boto3_collector.ecs import (
    CONTAINER_TYPE,
    HOST_TYPE,
    IMAGE_REALM,
    IMAGE_TAG_TYPE,
    READER,
    RUNS_IMAGE,
    TAGS_IMAGE,
    host_ref,
    image_writes,
    parse_image_tag,
    walk_ecs,
    well_formed_digest,
)
from tap_plugin.aws_core.collectors.boto3_collector.identity import node_ref
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
from tap_plugin.aws_core.tests.grid_keys import find_node_id, live_edges, node_id

from tap_cares.collectors.config import CollectorConfig

from . import test_boto3_collector_slice as slice_tests

_REGION = "us-east-1"
_ACCOUNT = "111122223333"
_CLUSTER = f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:cluster/prod"
_SERVICE = f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:service/prod/web"
_TASK_1 = f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:task/prod/aaaa1111"
_TASK_2 = f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:task/prod/bbbb2222"
_TASK_DEF = f"arn:aws:ecs:{_REGION}:{_ACCOUNT}:task-definition/web:7"
_DIGEST = "sha256:" + "ab" * 32
_OTHER_DIGEST = "sha256:" + "ef" * 32
_ECR_IMAGE = f"{_ACCOUNT}.dkr.ecr.{_REGION}.amazonaws.com/team/web:1.4.2"
_DIMS = {"aws.account": _ACCOUNT, "aws.region": _REGION}


def _container_arn(task: str, name: str) -> str:
    return task.replace(":task/", ":container/") + f"/{name}"


def _container(task: str, name: str, *, image: str = _ECR_IMAGE, digest: str | None = _DIGEST) -> dict[str, Any]:
    """One ``Container`` of a ``DescribeTasks`` response, every member a real one of the ECS model."""
    out: dict[str, Any] = {
        "containerArn": _container_arn(task, name),
        "taskArn": task,
        "name": name,
        "image": image,
        "runtimeId": f"{name}-rt",
        "lastStatus": "RUNNING",
        "healthStatus": "UNKNOWN",
        "cpu": "0",
    }
    if digest is not None:
        out["imageDigest"] = digest
    return out


def _task(arn: str, containers: list[dict[str, Any]], *, started: datetime | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "taskArn": arn,
        "clusterArn": _CLUSTER,
        "taskDefinitionArn": _TASK_DEF,
        "lastStatus": "RUNNING",
        "desiredStatus": "RUNNING",
        "launchType": "FARGATE",
        "platformVersion": "1.4.0",
        "group": "service:web",
        "containers": containers,
        "tags": [],
    }
    if started is not None:
        out["startedAt"] = started
    return out


def _stubbed_walk(tasks: list[dict[str, Any]]):
    """``walk_ecs`` over a real ECS client whose every call is stubbed, in the order the walk makes them."""
    client = boto3.client(
        "ecs", region_name=_REGION, aws_access_key_id="test", aws_secret_access_key="test"  # noqa: S106 — offline stub
    )
    arns = [t["taskArn"] for t in tasks]
    with Stubber(client) as stub:
        stub.add_response("list_clusters", {"clusterArns": [_CLUSTER]}, {})
        stub.add_response(
            "describe_clusters",
            {"clusters": [{"clusterArn": _CLUSTER, "clusterName": "prod", "status": "ACTIVE", "tags": []}], "failures": []},
            {"clusters": [_CLUSTER], "include": ["TAGS"]},
        )
        stub.add_response("list_services", {"serviceArns": [_SERVICE]}, {"cluster": _CLUSTER})
        stub.add_response("list_tasks", {"taskArns": arns}, {"cluster": _CLUSTER, "desiredStatus": "RUNNING"})
        stub.add_response("list_tasks", {"taskArns": []}, {"cluster": _CLUSTER, "desiredStatus": "STOPPED"})
        stub.add_response(
            "describe_services",
            {
                "services": [
                    {
                        "serviceArn": _SERVICE,
                        "serviceName": "web",
                        "clusterArn": _CLUSTER,
                        "status": "ACTIVE",
                        "taskDefinition": _TASK_DEF,
                        "desiredCount": 1,
                        "runningCount": 1,
                        "launchType": "FARGATE",
                        "tags": [],
                    }
                ],
                "failures": [],
            },
            {"services": [_SERVICE], "cluster": _CLUSTER, "include": ["TAGS"]},
        )
        if arns:
            stub.add_response(
                "describe_tasks",
                {"tasks": tasks, "failures": []},
                {"tasks": arns, "cluster": _CLUSTER, "include": ["TAGS"]},
            )
        walk = walk_ecs(client)
        stub.assert_no_pending_responses()
    return walk


def _carried(walk) -> dict[str, dict[str, str]]:
    """Every container of the walk as the batch would carry it."""
    return {node_ref(CONTAINER_TYPE, c["containerArn"]): dict(_DIMS) for c in walk.containers}


def _holding(*digests: str):
    asked: list[str] = []

    def held(digest: str) -> bool:
        asked.append(digest)
        return digest in digests

    held.asked = asked  # type: ignore[attr-defined]
    return held


def _of_type(writes, entity_type: str) -> list[dict[str, Any]]:
    return [n for n in writes.nodes if n["entity"]["entity_type"] == entity_type]


def _edges(writes, edge_type: str) -> list[dict[str, Any]]:
    return [e for e in writes.edges if e["edge"]["edge_type"] == edge_type]


def _create_schema(entity_type: str) -> dict[str, Any]:
    from tap_grid.registry import get_model_class

    model = get_model_class(entity_type)
    return {
        "type": "object",
        "properties": dict(model.FIELD_CRUD_SCHEMA),
        "required": list(model.CREATE_REQUIRED),
        "additionalProperties": False,
    }


def _edge_property_schema(edge_type: str) -> dict[str, Any]:
    from tap_grid.constraints import get_edge_property_schema

    return get_edge_property_schema(edge_type)


# --- (c) RUNS_IMAGE and the image host -------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-collector-ecs-20")
class TestRunsImage:
    def test_a_container_with_a_digest_runs_its_image_host(self):
        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web")])])
        writes = image_writes([walk], _carried(walk), host_held=_holding())
        (host,) = _of_type(writes, HOST_TYPE)
        assert host["node"]["realm"] == IMAGE_REALM == "oci-digest"
        assert host["node"]["stable_id"] == _DIGEST
        assert host["node"]["kind"] == "container"
        (edge,) = _edges(writes, RUNS_IMAGE)
        assert edge["edge"]["from_ref"] == node_ref(CONTAINER_TYPE, _container_arn(_TASK_1, "web"))
        assert edge["edge"]["to_ref"] == host["entity"]["ref"] == host_ref(_DIGEST)
        assert edge["edge"]["properties"] == {}
        assert edge["entity"]["dimensions"] == _DIMS  # the container's own, as its RUNS_CONTAINER edge carries
        assert host["entity"]["dimensions"] == {}  # an image is in no account or region: its type's defaults

    @pytest.mark.parametrize(
        "digest",
        [None, "", "sha256:" + "AB" * 32, "sha256:abc", "sha256:" + "ab" * 33, "sha512:" + "ab" * 32, " " + _DIGEST],
        ids=["absent", "empty", "upper-case", "short", "long", "other-algorithm", "padded"],
    )
    def test_no_well_formed_digest_means_no_host_and_no_edge(self, digest):
        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web", digest=digest)])])
        writes = image_writes([walk], _carried(walk), host_held=_holding())
        assert writes.nodes == [] and writes.edges == []
        assert writes.notices == []  # nothing failed: there is simply no image to name

    def test_a_container_the_batch_does_not_carry_gets_no_image(self):
        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web")])])
        writes = image_writes([walk], {}, host_held=_holding())
        assert writes.nodes == [] and writes.edges == []

    def test_one_digest_is_one_host_whatever_each_container_called_it(self):
        walk = _stubbed_walk(
            [
                _task(_TASK_1, [_container(_TASK_1, "web", image="registry.example/web:2")]),
                _task(_TASK_2, [_container(_TASK_2, "web", image="registry.example/web:latest")]),
            ]
        )
        writes = image_writes([walk], _carried(walk), host_held=_holding())
        (host,) = _of_type(writes, HOST_TYPE)
        assert host["node"]["name"] == host["entity"]["name"] == "registry.example/web:2"  # the first, sorted
        assert sorted(e["edge"]["from_ref"] for e in _edges(writes, RUNS_IMAGE)) == sorted(
            node_ref(CONTAINER_TYPE, _container_arn(t, "web")) for t in (_TASK_1, _TASK_2)
        )

    def test_two_digests_in_one_task_are_two_hosts(self):
        walk = _stubbed_walk(
            [_task(_TASK_1, [_container(_TASK_1, "web"), _container(_TASK_1, "sidecar", digest=_OTHER_DIGEST)])]
        )
        writes = image_writes([walk], _carried(walk), host_held=_holding())
        assert sorted(h["node"]["stable_id"] for h in _of_type(writes, HOST_TYPE)) == [_DIGEST, _OTHER_DIGEST]
        assert len(_edges(writes, RUNS_IMAGE)) == 2

    def test_the_host_payload_passes_computing_core_on_write(self):
        from tap_grid.registry import get_model_class

        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web")])])
        (host,) = _of_type(image_writes([walk], _carried(walk), host_held=_holding()), HOST_TYPE)
        jsonschema.validate(host["node"], _create_schema(HOST_TYPE))
        get_model_class(HOST_TYPE)(**host["node"]).validate()  # the oci-digest stable_id shape (host-4)

    def test_the_container_keeps_its_digest_verbatim_beside_the_host(self):
        """req-aws-collector-ecs-23: the digest stays on the container, and one computing_core refuses stays
        there alone."""
        entry = next(e for e in manifest_entries() if e["entity_type"] == CONTAINER_TYPE)
        odd = "sha256:" + "AB" * 32
        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web"), _container(_TASK_1, "odd", digest=odd)])])
        by_name = {c["name"]: project_item(entry, c).fields["image_digest"] for c in walk.containers}
        assert by_name == {"web": _DIGEST, "odd": odd}
        hosts = _of_type(image_writes([walk], _carried(walk), host_held=_holding()), HOST_TYPE)
        assert [h["node"]["stable_id"] for h in hosts] == [_DIGEST]


@pytest.mark.spec("req-aws-collector-ecs-21")
class TestHostWrittenWithoutOverwriting:
    def test_a_new_host_carries_the_reference_it_was_seen_as(self):
        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web")])])
        held = _holding()
        (host,) = _of_type(image_writes([walk], _carried(walk), host_held=held), HOST_TYPE)
        assert host["node"] == {"realm": "oci-digest", "stable_id": _DIGEST, "kind": "container", "name": _ECR_IMAGE}
        assert host["entity"]["name"] == _ECR_IMAGE
        assert held.asked == [_DIGEST]

    def test_a_held_host_is_sent_its_key_and_kind_only(self):
        """No name in the payload or the envelope: the importer leaves the stored name, and every field the payload
        omits, as another producer wrote them."""
        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web")])])
        (host,) = _of_type(image_writes([walk], _carried(walk), host_held=_holding(_DIGEST)), HOST_TYPE)
        assert host["node"] == {"realm": "oci-digest", "stable_id": _DIGEST, "kind": "container"}
        assert "name" not in host["entity"]

    def test_a_failed_lookup_sends_the_safe_write_and_says_so(self):
        def broken(_digest):
            raise RuntimeError("grid unavailable")

        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web")])])
        writes = image_writes([walk], _carried(walk), host_held=broken)
        (host,) = _of_type(writes, HOST_TYPE)
        assert host["node"] == {"realm": "oci-digest", "stable_id": _DIGEST, "kind": "container"}
        assert [code for code, _ in writes.notices] == ["ECS_IMAGE_HOST_LOOKUP_FAILED"]
        assert _edges(writes, RUNS_IMAGE)  # the edge still names the host

    def test_a_reference_too_long_for_the_name_column_leaves_the_name_out(self):
        long_image = "registry.example/" + "a" * 250 + ":1"
        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web", image=long_image)])])
        (host,) = _of_type(image_writes([walk], _carried(walk), host_held=_holding()), HOST_TYPE)
        assert "name" not in host["node"]
        assert host["entity"]["name"] == _DIGEST

    @pytest.mark.parametrize(
        "block",
        [
            None,
            {"status": "unreviewed"},
            {
                "status": "reviewed_may_contain",
                "basis": "test",
                "locations": [{"path": "name", "category": "credential", "reason": "t", "evidence": "reviewer_judgement"}],
            },
        ],
        ids=["undeclared", "unreviewed", "credential"],
    )
    def test_no_host_is_written_without_a_safe_declaration(self, block):
        from tap_plugin.aws_core.collectors.boto3_collector.organizations import reader_sensitivity

        declared = dict(reader_sensitivity(READER))
        if block is None:
            declared.pop(HOST_TYPE)
        else:
            declared[HOST_TYPE] = block
        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web")])])
        writes = image_writes([walk], _carried(walk), host_held=_holding(), sensitivity=declared)
        assert writes.nodes == [] and writes.edges == []
        assert any(code == "ECS_IMAGE_TYPE_REFUSED" for code, _ in writes.notices)

    def test_both_image_types_are_declared_on_their_own_fields(self):
        from tap_plugin.aws_core.collectors.boto3_collector.organizations import reader_sensitivity, sensitivity_refusal

        declared = reader_sensitivity(READER)
        assert set(declared) == {HOST_TYPE, IMAGE_TAG_TYPE}
        assert all(sensitivity_refusal(t, declared) is None for t in declared)


# --- (f) TAGS_IMAGE and the image tag ---------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-collector-ecs-22")
class TestImageTagParsing:
    @pytest.mark.parametrize(
        ("reference", "parts"),
        [
            ("registry.example/app:latest", ("registry.example", "app", "latest")),
            (_ECR_IMAGE, (f"{_ACCOUNT}.dkr.ecr.{_REGION}.amazonaws.com", "team/web", "1.4.2")),
            ("public.ecr.aws/nginx/nginx:1.27-alpine", ("public.ecr.aws", "nginx/nginx", "1.27-alpine")),
            ("ghcr.io/org/app:v2.0.1", ("ghcr.io", "org/app", "v2.0.1")),
            ("registry.example:5000/org/app:1.0", ("registry.example:5000", "org/app", "1.0")),
            ("localhost:5000/app:dev", ("localhost:5000", "app", "dev")),
            ("localhost/app:1", ("localhost", "app", "1")),
            ("docker.io/library/nginx:1.25", ("docker.io", "library/nginx", "1.25")),
        ],
    )
    def test_a_reference_that_writes_all_three_parts(self, reference, parts):
        assert parse_image_tag(reference) == parts

    @pytest.mark.parametrize(
        "reference",
        [
            "nginx:1.25",  # Docker Hub implied, not written
            "library/nginx:1.25",  # likewise: no '.', ':' or localhost in the first component
            "registry.example/app",  # no tag written (latest is implied)
            "registry.example:5000/app",  # the colon is the port's, not a tag
            "registry.example/app@" + _DIGEST,  # pulled by digest
            "registry.example/app:1.0@" + _DIGEST,  # pulled by digest, whatever tag it also writes
            "registry.example/app:-bad",  # not an OCI tag
            "registry.example/app:" + "t" * 129,  # longer than an OCI tag
            "r" * 256 + ".example/app:1",  # registry longer than the column
            "registry.example/" + "r" * 256 + ":1",  # repository longer than the column
            "registry.example/:1",  # no repository
            " registry.example/app:1",
            "",
            None,
            42,
        ],
    )
    def test_anything_else_makes_no_tag(self, reference):
        assert parse_image_tag(reference) is None

    def test_well_formed_digest(self):
        assert well_formed_digest(_DIGEST) == _DIGEST
        assert well_formed_digest("sha256:" + "AB" * 32) is None
        assert well_formed_digest(None) is None


@pytest.mark.spec("req-aws-collector-ecs-22")
class TestTagsImage:
    def test_the_tag_ecs_resolved_points_at_the_host(self):
        started = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web")], started=started)])
        writes = image_writes([walk], _carried(walk), host_held=_holding())
        (tag,) = _of_type(writes, IMAGE_TAG_TYPE)
        assert tag["node"] == {
            "registry": f"{_ACCOUNT}.dkr.ecr.{_REGION}.amazonaws.com",
            "repository": "team/web",
            "tag": "1.4.2",
        }
        assert tag["entity"]["name"] == _ECR_IMAGE
        assert tag["entity"]["dimensions"] == {}
        (edge,) = _edges(writes, TAGS_IMAGE)
        assert edge["edge"]["from_ref"] == tag["entity"]["ref"]
        assert edge["edge"]["to_ref"] == host_ref(_DIGEST)
        assert edge["edge"]["properties"] == {"detected_at": "2026-11-01T09:30:00Z"}

    def test_detected_at_is_the_latest_start_of_the_tasks_that_ran_the_pair(self):
        early, late = datetime(2026, 11, 1, 9, 0, tzinfo=UTC), datetime(2026, 11, 2, 18, 15, 30, 250000, tzinfo=UTC)
        walk = _stubbed_walk(
            [
                _task(_TASK_1, [_container(_TASK_1, "web")], started=late),
                _task(_TASK_2, [_container(_TASK_2, "web")], started=early),
            ]
        )
        writes = image_writes([walk], _carried(walk), host_held=_holding())
        assert len(_of_type(writes, IMAGE_TAG_TYPE)) == 1
        (edge,) = _edges(writes, TAGS_IMAGE)
        assert edge["edge"]["properties"] == {"detected_at": "2026-11-02T18:15:30.250000Z"}

    def test_a_pending_task_gives_no_detected_at(self):
        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web")])])
        (edge,) = _edges(image_writes([walk], _carried(walk), host_held=_holding()), TAGS_IMAGE)
        assert edge["edge"]["properties"] == {}

    def test_a_moved_tag_points_at_each_image_it_was_seen_on(self):
        walk = _stubbed_walk(
            [
                _task(_TASK_1, [_container(_TASK_1, "web")]),
                _task(_TASK_2, [_container(_TASK_2, "web", digest=_OTHER_DIGEST)]),
            ]
        )
        writes = image_writes([walk], _carried(walk), host_held=_holding())
        assert len(_of_type(writes, IMAGE_TAG_TYPE)) == 1
        assert sorted(e["edge"]["to_ref"] for e in _edges(writes, TAGS_IMAGE)) == sorted(
            [host_ref(_DIGEST), host_ref(_OTHER_DIGEST)]
        )

    @pytest.mark.parametrize("image", ["nginx:1.25", "registry.example/app@" + "sha256:" + "ab" * 32])
    def test_no_tag_where_the_reference_writes_none(self, image):
        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web", image=image)])])
        writes = image_writes([walk], _carried(walk), host_held=_holding())
        assert _of_type(writes, IMAGE_TAG_TYPE) == [] and _edges(writes, TAGS_IMAGE) == []
        assert _of_type(writes, HOST_TYPE)  # the digest still names the image

    def test_no_tag_without_a_digest(self):
        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web", digest=None)])])
        assert image_writes([walk], _carried(walk), host_held=_holding()).nodes == []

    def test_the_tag_and_its_edge_pass_computing_core_on_write(self):
        started = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web")], started=started)])
        writes = image_writes([walk], _carried(walk), host_held=_holding())
        (tag,) = _of_type(writes, IMAGE_TAG_TYPE)
        jsonschema.validate(tag["node"], _create_schema(IMAGE_TAG_TYPE))
        (edge,) = _edges(writes, TAGS_IMAGE)
        jsonschema.validate(edge["edge"]["properties"], _edge_property_schema(TAGS_IMAGE))

    def test_a_refused_tag_type_leaves_the_host_and_runs_image(self):
        from tap_plugin.aws_core.collectors.boto3_collector.organizations import reader_sensitivity

        declared = dict(reader_sensitivity(READER))
        declared.pop(IMAGE_TAG_TYPE)
        walk = _stubbed_walk([_task(_TASK_1, [_container(_TASK_1, "web")])])
        writes = image_writes([walk], _carried(walk), host_held=_holding(), sensitivity=declared)
        assert _of_type(writes, IMAGE_TAG_TYPE) == [] and _edges(writes, TAGS_IMAGE) == []
        assert _of_type(writes, HOST_TYPE) and _edges(writes, RUNS_IMAGE)


# --- the whole run, imported through core ----------------------------------------------------------------------------

_stub_aws = slice_tests._stub_aws
_SLICE_CONTAINER = slice_tests._ECS_CONTAINER
_SLICE_DIGEST = slice_tests._ECS_DIGEST
_SLICE_IMAGE = "registry.example/app:latest"  # the slice's container image
_HOST_KEY = {"realm": "oci-digest", "stable_id": _SLICE_DIGEST}
_TAG_KEY = {"registry": "registry.example", "repository": "app", "tag": "latest"}


def _run():
    from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector

    collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
    collector.run()
    assert collector.results["error"] == []
    return collector


def _live(entity_type: str) -> int:
    from tap_grid.models import Entity

    return Entity.objects.filter(entity_type=entity_type, deleted_at__isnull=True).count()


@pytest.mark.django_db
@pytest.mark.usefixtures("_stub_aws")
@pytest.mark.spec("req-aws-collector-ecs-20", "req-aws-collector-ecs-21", "req-aws-collector-ecs-22")
class TestImportedThroughCore:
    def test_the_host_the_tag_and_both_edges_land(self):
        from tap_grid.services import get_node

        _run()
        host = get_node(node_id(HOST_TYPE, _HOST_KEY))
        assert (host.realm, host.stable_id, host.kind, host.name) == ("oci-digest", _SLICE_DIGEST, "container", _SLICE_IMAGE)
        container = node_id(CONTAINER_TYPE, _SLICE_CONTAINER)
        assert len(live_edges(RUNS_IMAGE, container, host.entity_id)) == 1
        tag = node_id(IMAGE_TAG_TYPE, _TAG_KEY)
        (tags_image,) = live_edges(TAGS_IMAGE, tag, host.entity_id)
        assert tags_image.properties == {}  # the slice's task has no startedAt
        assert get_node(container).image_digest == _SLICE_DIGEST  # kept on the container too (-23)

    def test_a_rerun_adds_nothing(self):
        _run()
        counts = (_live(HOST_TYPE), _live(IMAGE_TAG_TYPE))
        host = node_id(HOST_TYPE, _HOST_KEY)
        _run()
        assert (_live(HOST_TYPE), _live(IMAGE_TAG_TYPE)) == counts == (1, 1)
        assert node_id(HOST_TYPE, _HOST_KEY) == host
        assert len(live_edges(RUNS_IMAGE, node_id(CONTAINER_TYPE, _SLICE_CONTAINER), host)) == 1
        assert len(live_edges(TAGS_IMAGE, node_id(IMAGE_TAG_TYPE, _TAG_KEY), host)) == 1

    def test_a_host_another_producer_wrote_keeps_what_it_wrote(self):
        """An image host Anchore wrote first (its name, operating system and image facts) is joined, not
        rewritten: aws_core sends the key and kind only."""
        from tap_grid.grift import grift_import
        from tap_grid.models import Entity
        from tap_grid.services import get_node

        anchore = {
            "metadata": {"grift_version": "0"},
            "_reserved": {},
            "batches": [
                {
                    "batch_entity": {"entity_id": str(uuid.uuid7()), "entity_type": "batch", "name": "scanner", "dimensions": {}},
                    "batch_node": {"source": "test.scanner", "name": "scanner", "description": "an image scanner's write"},
                    "nodes": [
                        {
                            "entity": {
                                "ref": "image",
                                "entity_type": HOST_TYPE,
                                "name": "ghcr.io/org/app:1.0",
                                "dimensions": {"tap.computing": "host"},
                            },
                            "node": {
                                **_HOST_KEY,
                                "kind": "container",
                                "name": "ghcr.io/org/app:1.0",
                                "os": "alpine 3.20",
                                "architecture": "arm64",
                                "image_layer_count": 7,
                            },
                        }
                    ],
                    "edges": [],
                }
            ],
        }
        imported = grift_import(anchore)
        assert imported.success, [(i.code, i.message) for i in imported.errors]
        before = node_id(HOST_TYPE, _HOST_KEY)

        _run()
        assert _live(HOST_TYPE) == 1
        host = get_node(node_id(HOST_TYPE, _HOST_KEY))
        assert host.entity_id == before
        assert (host.name, host.os, host.architecture, host.image_layer_count, host.kind) == (
            "ghcr.io/org/app:1.0",
            "alpine 3.20",
            "arm64",
            7,
            "container",
        )
        assert Entity.objects.get(pk=before).name == "ghcr.io/org/app:1.0"
        assert len(live_edges(RUNS_IMAGE, node_id(CONTAINER_TYPE, _SLICE_CONTAINER), before)) == 1

    def test_the_batch_sends_no_name_for_a_held_host(self, monkeypatch):
        from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector

        _run()
        submitted: list[dict[str, Any]] = []
        real_submit = Boto3Collector.submit_grift

        def _capture(self, document, **kwargs):
            submitted.append(json.loads(json.dumps(document, default=str)))
            return real_submit(self, document, **kwargs)

        monkeypatch.setattr(Boto3Collector, "submit_grift", _capture)
        _run()
        (batch,) = submitted[0]["batches"]
        (host,) = [n for n in batch["nodes"] if n["entity"]["entity_type"] == HOST_TYPE]
        assert host["node"] == {**_HOST_KEY, "kind": "container"}
        assert "name" not in host["entity"]

    def test_a_failed_image_write_keeps_the_containers_and_is_not_a_clean_run(self, monkeypatch):
        """A defect in image_writes loses only the images, and says so where a run's failures are read: an entry in
        results["error"] and the summary. (Core's job has no partial status, and a warning changes nothing.)"""
        from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
        from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector

        def broken(*_args, **_kwargs):
            raise RuntimeError("defect in image shaping")

        monkeypatch.setattr(collector_mod, "image_writes", broken)
        submitted: list[dict[str, Any]] = []
        real_submit = Boto3Collector.submit_grift

        def _capture(self, document, **kwargs):
            submitted.append(json.loads(json.dumps(document, default=str)))
            return real_submit(self, document, **kwargs)

        monkeypatch.setattr(Boto3Collector, "submit_grift", _capture)
        collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
        collector.run()

        (batch,) = submitted[0]["batches"]
        assert [n for n in batch["nodes"] if n["entity"]["entity_type"] == CONTAINER_TYPE]
        assert [n for n in batch["nodes"] if n["entity"]["entity_type"] in (HOST_TYPE, IMAGE_TAG_TYPE)] == []
        assert [e for e in batch["edges"] if e["edge"]["edge_type"] in (RUNS_IMAGE, TAGS_IMAGE)] == []
        assert find_node_id(CONTAINER_TYPE, _SLICE_CONTAINER) is not None  # imported
        (error,) = collector.results["error"]
        assert error["message_code"] == "ECS_IMAGE_WRITES_FAILED"
        assert error["message_data"] == {"containers": 1, "exception": "RuntimeError"}
        assert "ECS container images NOT staged (RuntimeError)" in collector.summary

    def test_a_container_without_a_digest_lands_without_an_image(self, monkeypatch):
        tasks = json.loads(json.dumps(slice_tests._CANNED["describe_tasks"]))
        del tasks["tasks"][0]["containers"][0]["imageDigest"]
        monkeypatch.setitem(slice_tests._CANNED, "describe_tasks", tasks)
        _run()
        assert find_node_id(CONTAINER_TYPE, _SLICE_CONTAINER) is not None
        assert _live(HOST_TYPE) == 0 and _live(IMAGE_TAG_TYPE) == 0


def test_ecs_names_no_github_core_and_imports_no_other_plugin():
    """req-aws-collector-ecs-20 (superseding -14): computing_core's image types are named by slug, its downward
    dependency (tap-plugin.toml depends_on); nothing of github_core is named and no plugin module is imported."""
    import ast
    from pathlib import Path

    import tap_plugin.aws_core.collectors.boto3_collector.ecs as ecs_module

    source = Path(ecs_module.__file__).read_text()
    assert "github_core" not in source
    imported = [
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    ]
    assert not [m for m in imported if m and m.startswith("tap_plugin.") and not m.startswith("tap_plugin.aws_core")]
