"""CodeBuild Project — an AWS CodeBuild build project."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel

# codebuild SourceType, as BatchGetProjects reports it.
SOURCE_TYPES = [
    "CODECOMMIT",
    "CODEPIPELINE",
    "GITHUB",
    "GITHUB_ENTERPRISE",
    "GITLAB",
    "GITLAB_SELF_MANAGED",
    "BITBUCKET",
    "S3",
    "NO_SOURCE",
]


class CodebuildProject(BaseModel):
    """An AWS CodeBuild project: the build environment and source a build runs with.

    Environment variables, the buildspec and source credentials are deliberately not fields: they can carry
    secrets, and nothing here needs them. What a project touches is carried by edges: ``ASSUMES_ROLE``
    (its service role) and ``RETRIEVES_SECRET_FROM`` (a Secrets Manager secret it reads); a pipeline reaches
    it by ``RUNS_BUILD``. Design vocabulary: no collector emits it yet. Fields are those
    ``codebuild:BatchGetProjects`` reports.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-codebuild)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_codebuild_project"
    ENTITY_NAME: ClassVar[str] = "CodeBuild Project"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS CodeBuild project: a managed build environment (image, compute size, source) that runs "
        "builds such as a Terraform plan or apply."
    )
    ENTITY_ICON: ClassVar[str] = "aws-codebuild"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }

    # The project's ARN (BatchGetProjects arn). A project name is unique only within one account and
    # region, so the ARN, which carries both, is the identity.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("project_arn",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "project_arn": {
            "type": "string",
            "pattern": "^(arn:aws(-us-gov|-cn)?:codebuild:[a-z0-9-]+:[0-9]{12}:project/[A-Za-z0-9][A-Za-z0-9_-]{1,149})?$",
        },
        # environment.image: an ECR image URI, a Docker Hub name or an aws/codebuild/ standard image.
        "environment_image": {"type": "string"},
        # environment.computeType, AWS's string (BUILD_GENERAL1_SMALL, BUILD_LAMBDA_2GB, ...). Not an enum:
        # AWS adds compute types with new environment types.
        "compute_type": {"type": "string"},
        "source_type": {"type": "string", "enum": ["", *SOURCE_TYPES]},
        # True when the project has a vpcConfig with a vpcId; null until observed.
        "vpc_attached": {"type": ["boolean", "null"]},
        # environment.privilegedMode: the build can run a Docker daemon with root on its host. Null until observed.
        "privileged_mode": {"type": ["boolean", "null"]},
        "region": {"type": "string"},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    project_arn = models.CharField(max_length=300, blank=True, default="", db_index=True)
    environment_image = models.CharField(max_length=255, blank=True, default="")
    compute_type = models.CharField(max_length=64, blank=True, default="")
    # Blank means not observed (the aws_elb.lb_type convention).
    source_type = models.CharField(max_length=32, blank=True, default="")
    vpc_attached = models.BooleanField(null=True, blank=True, default=None)
    # environment.privilegedMode: the build can run a Docker daemon with root on its host. Null until observed.
    privileged_mode = models.BooleanField(null=True, blank=True, default=None)
    region = models.CharField(max_length=32, blank=True, default="")
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: BatchGetProjects tags.
    tags = models.JSONField(null=True, blank=True, default=None)
    # The collector's configuration envelope; {} when the manifest entry does not persist it.
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_codebuild_project"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.get_name()
