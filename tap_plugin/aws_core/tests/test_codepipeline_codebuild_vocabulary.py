"""Validation tests for the CodePipeline / CodeBuild design vocabulary.

Covers req-aws-core-codepipeline, req-aws-core-codebuild and req-aws-core-deploy-flow-edges
(specs/spec-aws-core-v0.md, aws-core-tap#96): each type creates through the service layer with only a name,
keys on its ARN, refuses a malformed ARN and an unknown enum value, and each edge declares exactly the
endpoints it names. No collector emits these types, so nothing here exercises a collector.
"""

from __future__ import annotations

from typing import Any

import pytest
from tap_plugin.aws_core.models import CodebuildProject, CodepipelinePipeline

from tap_grid.caller_context import CallerContext
from tap_grid.constraints import WILDCARD, get_edge_type_constraints
from tap_grid.models import Edge, Entity
from tap_grid.services import WriteOperation, write_batch

PIPELINE = CodepipelinePipeline.ENTITY_TYPE
PROJECT = CodebuildProject.ENTITY_TYPE

_PIPELINE_ARN = "arn:aws-us-gov:codepipeline:us-gov-east-1:123456789012:highbar-deploy"
_PROJECT_ARN = "arn:aws-us-gov:codebuild:us-gov-east-1:123456789012:project/highbar-plan"

# (model, natural-key field, a well-formed ARN, a malformed one)
TYPES = [
    (CodepipelinePipeline, "pipeline_arn", _PIPELINE_ARN, _PROJECT_ARN),
    (CodebuildProject, "project_arn", _PROJECT_ARN, _PIPELINE_ARN),
]


def t(slug: str) -> str:
    return f"aws_core__aws_{slug}"


def _node(type_slug: str, payload: dict[str, Any]):
    return write_batch(
        [WriteOperation(verb="create_node", type_slug=type_slug, payload=payload)], caller_context=CallerContext()
    ).results[0]


def _entity(type_slug: str, name: str) -> Entity:
    result = _node(type_slug, {"name": name})
    assert result.success, result.errors
    return Entity.objects.get(id=result.entity_id)


def _edge(source: Entity, target: Entity, edge_type: str):
    return write_batch(
        [
            WriteOperation(
                verb="create_edge",
                from_target=str(source.id),
                to_target=str(target.id),
                edge_type=edge_type,
            )
        ],
        caller_context=CallerContext(),
    ).results[0]


def _permits(allowed, entity_type: str) -> bool:
    return allowed is WILDCARD or entity_type in allowed


class TestDeclarations:
    @pytest.mark.parametrize(("model", "key", "_good", "_bad"), TYPES)
    def test_keyed_on_the_arn(self, model, key, _good, _bad) -> None:
        assert model.NATURAL_KEY == (key,)

    @pytest.mark.parametrize(("model", "_key", "_good", "_bad"), TYPES)
    def test_no_blob_and_no_duplicated_owner(self, model, _key, _good, _bad) -> None:
        # The owning account is the BELONGS_TO_ACCOUNT edge, never a second copy in a field; and no
        # source fills a free-form configuration blob (a CodeBuild project's would carry environment
        # variables).
        fields = {f.name for f in model._meta.get_fields()}
        assert "configuration" not in fields
        assert "owner_account_id" not in fields
        assert set(model.FIELD_CRUD_SCHEMA) == set(model.FIELD_VALIDATION_SCHEMA)

    @pytest.mark.parametrize(("model", "_key", "_good", "_bad"), TYPES)
    def test_tags_are_a_flat_string_map(self, model, _key, _good, _bad) -> None:
        assert model.FIELD_CRUD_SCHEMA["tags"] == {
            "type": ["object", "null"],
            "additionalProperties": {"type": "string"},
        }

    def test_no_environment_variable_or_buildspec_field(self) -> None:
        # Environment variables and the buildspec can carry secrets and nothing here needs them.
        names = {f.name for f in CodebuildProject._meta.get_fields()}
        assert not {n for n in names if "env" in n and n != "environment_image"}
        assert "buildspec" not in names

    def test_account_edge_covers_both_types(self) -> None:
        sources = get_edge_type_constraints("BELONGS_TO_ACCOUNT__aws_core").sources
        assert {PIPELINE, PROJECT} <= sources

    def test_role_edge_takes_both_service_roles(self) -> None:
        constraints = get_edge_type_constraints("ASSUMES_ROLE__aws_core")
        assert {PIPELINE, PROJECT, t("lambda")} <= constraints.sources
        assert constraints.targets == {t("iam_role")}

    @pytest.mark.parametrize(
        ("edge_type", "sources", "targets"),
        [
            ("RETRIEVES_SOURCE_FROM__aws_core", {PIPELINE}, {t("s3_bucket")}),
            ("RUNS_BUILD__aws_core", {PIPELINE}, {PROJECT}),
            ("WRITES_OBJECT__aws_core", {t("lambda")}, {t("s3_bucket")}),
            ("RETRIEVES_SECRET_FROM__aws_core", {t("lambda"), PROJECT}, {t("secrets_manager_secret")}),
        ],
    )
    def test_new_edges_declare_exactly_their_endpoints(self, edge_type, sources, targets) -> None:
        constraints = get_edge_type_constraints(edge_type)
        assert constraints is not None
        assert constraints.sources == sources
        assert constraints.targets == targets

    def test_no_new_type_is_a_containment_target(self) -> None:
        # A pipeline or project references a bucket, a role and a secret; none of those retire with it.
        for model in (CodepipelinePipeline, CodebuildProject):
            assert getattr(model, "CONTAINMENT_EDGES", ()) == ()


@pytest.mark.django_db
class TestCreate:
    @pytest.mark.parametrize(("model", "key", "_good", "_bad"), TYPES)
    def test_designed_node_needs_only_a_name(self, model, key, _good, _bad) -> None:
        result = _node(model.ENTITY_TYPE, {"name": "highbar"})
        assert result.success, result.errors
        row = model.all_objects.get(entity_id=result.entity_id)
        assert getattr(row, key) == ""
        assert row.entity.dimensions == {"tap.cloud": "aws"}

    @pytest.mark.parametrize(("model", "key", "good", "_bad"), TYPES)
    def test_well_formed_arn_is_accepted(self, model, key, good, _bad) -> None:
        result = _node(model.ENTITY_TYPE, {"name": "x", key: good})
        assert result.success, result.errors
        assert model.objects.get(**{key: good}).entity_id == result.entity_id

    @pytest.mark.parametrize(("model", "key", "_good", "bad"), TYPES)
    def test_malformed_arn_is_refused(self, model, key, _good, bad) -> None:
        assert not _node(model.ENTITY_TYPE, {"name": "x", key: bad}).success

    @pytest.mark.parametrize(("model", "_key", "_good", "_bad"), TYPES)
    def test_two_arn_less_designs_stay_distinct(self, model, _key, _good, _bad) -> None:
        results = write_batch(
            [
                WriteOperation(verb="create_node", type_slug=model.ENTITY_TYPE, payload={"name": "a"}),
                WriteOperation(verb="create_node", type_slug=model.ENTITY_TYPE, payload={"name": "b"}),
            ],
            caller_context=CallerContext(),
        ).results
        assert all(r.success for r in results)
        assert results[0].entity_id != results[1].entity_id

    def test_pipeline_fields(self) -> None:
        ok = _node(
            PIPELINE,
            {
                "name": "highbar-deploy",
                "pipeline_arn": _PIPELINE_ARN,
                "stage_names": ["Source", "Plan", "Approve", "Apply"],
                "pipeline_type": "V2",
                "execution_mode": "QUEUED",
                "tags": {"env": "demo"},
            },
        )
        assert ok.success, ok.errors
        row = CodepipelinePipeline.objects.get(entity_id=ok.entity_id)
        assert row.stage_names == ["Source", "Plan", "Approve", "Apply"]
        assert not _node(PIPELINE, {"name": "x", "pipeline_type": "V3"}).success
        assert not _node(PIPELINE, {"name": "x", "execution_mode": "queued"}).success
        assert not _node(PIPELINE, {"name": "x", "stage_names": [""]}).success
        assert not _node(PIPELINE, {"name": "x", "stage_names": [{"name": "Source"}]}).success
        assert not _node(PIPELINE, {"name": "x", "tags": {"env": 1}}).success

    @pytest.mark.parametrize(
        ("name", "accepted"),
        [
            ("ab", True),
            ("a" * 150, True),
            ("a-b_c9", True),
            ("a", False),  # botocore ProjectName minimum is 2
            ("a" * 151, False),  # botocore ProjectName maximum is 150
            ("a.b", False),  # no dots in a project name
            ("-ab", False),  # must start alphanumeric
        ],
    )
    def test_project_arn_follows_the_project_name_shape(self, name: str, accepted: bool) -> None:
        arn = f"arn:aws-us-gov:codebuild:us-gov-east-1:123456789012:project/{name}"
        assert _node(PROJECT, {"name": "x", "project_arn": arn}).success is accepted

    def test_longest_valid_project_arn_fits_the_column(self) -> None:
        arn = "arn:aws-us-gov:codebuild:us-gov-east-1:123456789012:project/" + "a" * 150
        assert len(arn) <= CodebuildProject._meta.get_field("project_arn").max_length

    def test_project_fields(self) -> None:
        ok = _node(
            PROJECT,
            {
                "name": "highbar-plan",
                "project_arn": _PROJECT_ARN,
                "environment_image": "aws/codebuild/amazonlinux-x86_64-standard:5.0",
                "compute_type": "BUILD_GENERAL1_SMALL",
                "source_type": "CODEPIPELINE",
                "vpc_attached": True,
                "tags": {"env": "demo"},
            },
        )
        assert ok.success, ok.errors
        assert CodebuildProject.objects.get(entity_id=ok.entity_id).vpc_attached is True
        assert not _node(PROJECT, {"name": "x", "source_type": "SVN"}).success
        assert not _node(PROJECT, {"name": "x", "vpc_attached": "yes"}).success

    def test_vpc_attached_is_null_until_observed(self) -> None:
        # Null means nobody has looked; False means observed, not in a VPC.
        unobserved = _node(PROJECT, {"name": "a"})
        outside = _node(PROJECT, {"name": "b", "vpc_attached": False})
        assert CodebuildProject.objects.get(entity_id=unobserved.entity_id).vpc_attached is None
        assert CodebuildProject.objects.get(entity_id=outside.entity_id).vpc_attached is False


@pytest.mark.django_db
class TestEdges:
    @pytest.mark.parametrize(
        ("edge_type", "source", "target"),
        [
            ("BELONGS_TO_ACCOUNT__aws_core", PIPELINE, t("account")),
            ("BELONGS_TO_ACCOUNT__aws_core", PROJECT, t("account")),
            ("ASSUMES_ROLE__aws_core", PIPELINE, t("iam_role")),
            ("ASSUMES_ROLE__aws_core", PROJECT, t("iam_role")),
            ("RETRIEVES_SOURCE_FROM__aws_core", PIPELINE, t("s3_bucket")),
            ("RUNS_BUILD__aws_core", PIPELINE, PROJECT),
            ("WRITES_OBJECT__aws_core", t("lambda"), t("s3_bucket")),
            ("RETRIEVES_SECRET_FROM__aws_core", t("lambda"), t("secrets_manager_secret")),
            ("RETRIEVES_SECRET_FROM__aws_core", PROJECT, t("secrets_manager_secret")),
        ],
    )
    def test_declared_endpoints_are_accepted(self, edge_type: str, source: str, target: str) -> None:
        result = _edge(_entity(source, "s"), _entity(target, "t"), edge_type)
        assert result.success, result.errors
        edge = Edge.objects.select_related("entity").get(entity_id=result.entity_id)
        assert edge.entity.dimensions == {"tap.cloud": "aws"}

    @pytest.mark.parametrize(
        ("edge_type", "source", "target"),
        [
            ("RETRIEVES_SOURCE_FROM__aws_core", t("s3_bucket"), PIPELINE),  # reversed
            ("RETRIEVES_SOURCE_FROM__aws_core", PROJECT, t("s3_bucket")),  # only a pipeline's source stage
            ("RETRIEVES_SOURCE_FROM__aws_core", PIPELINE, t("secrets_manager_secret")),
            ("RUNS_BUILD__aws_core", PROJECT, PIPELINE),
            ("RUNS_BUILD__aws_core", PIPELINE, t("lambda")),
            ("WRITES_OBJECT__aws_core", t("s3_bucket"), t("lambda")),
            ("WRITES_OBJECT__aws_core", PROJECT, t("s3_bucket")),
            ("WRITES_OBJECT__aws_core", t("lambda"), t("secrets_manager_secret")),
            ("RETRIEVES_SECRET_FROM__aws_core", PIPELINE, t("secrets_manager_secret")),
            ("RETRIEVES_SECRET_FROM__aws_core", t("lambda"), t("ssm_parameter")),
            ("RETRIEVES_SECRET_FROM__aws_core", t("secrets_manager_secret"), t("lambda")),
            ("ASSUMES_ROLE__aws_core", PIPELINE, PROJECT),
        ],
    )
    def test_other_pairs_fall_outside_the_declaration(self, edge_type: str, source: str, target: str) -> None:
        # The declaration, not the write path: tap_grid checks edges by permission union and aws_core
        # nodes mostly declare no node-side constraints, so such a write can succeed
        # (unified-systems-com/tap#794).
        constraints = get_edge_type_constraints(edge_type)
        assert constraints is not None
        assert not (_permits(constraints.sources, source) and _permits(constraints.targets, target))
