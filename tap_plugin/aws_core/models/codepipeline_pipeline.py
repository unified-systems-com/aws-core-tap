"""CodePipeline Pipeline — an AWS CodePipeline release pipeline."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel

# codepipeline PipelineType and ExecutionMode, as GetPipeline reports them.
PIPELINE_TYPES = ["V1", "V2"]
EXECUTION_MODES = ["QUEUED", "SUPERSEDED", "PARALLEL"]


class CodepipelinePipeline(BaseModel):
    """An AWS CodePipeline pipeline: ordered stages of actions that move a change from source to deploy.

    The stages are recorded by name only; the actions inside them are not nodes. What a pipeline touches is
    carried by edges: ``RETRIEVES_SOURCE_FROM`` (its S3 source bucket), ``RUNS_BUILD`` (the CodeBuild projects
    its build actions start) and ``ASSUMES_ROLE`` (its service role). Design vocabulary: no collector emits
    it yet. Fields are those ``codepipeline:GetPipeline`` reports.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-codepipeline)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_codepipeline_pipeline"
    ENTITY_NAME: ClassVar[str] = "CodePipeline Pipeline"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS CodePipeline pipeline: a sequence of stages (source, build, approval, deploy) that moves "
        "a change from its source to a deployment."
    )
    ENTITY_ICON: ClassVar[str] = "aws-codepipeline"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }

    # The pipeline's ARN (GetPipeline metadata.pipelineArn). A pipeline name is unique only within one
    # account and region, so the ARN, which carries both, is the identity.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("pipeline_arn",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "pipeline_arn": {
            "type": "string",
            "pattern": "^(arn:aws(-us-gov|-cn)?:codepipeline:[a-z0-9-]+:[0-9]{12}:[A-Za-z0-9.@_-]+)?$",
        },
        # Source: GetPipeline pipeline.stages[].name, in pipeline order.
        "stage_names": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "pipeline_type": {"type": "string", "enum": ["", *PIPELINE_TYPES]},
        "execution_mode": {"type": "string", "enum": ["", *EXECUTION_MODES]},
        "region": {"type": "string"},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=100, blank=True, default="")
    pipeline_arn = models.CharField(max_length=300, blank=True, default="", db_index=True)
    # Empty list means a pipeline observed with no stages; GetPipeline requires at least two, so in
    # practice it means the design is not yet drawn.
    stage_names = models.JSONField(default=list, blank=True)
    # Blank means not observed (the aws_elb.lb_type convention).
    pipeline_type = models.CharField(max_length=2, blank=True, default="")
    execution_mode = models.CharField(max_length=16, blank=True, default="")
    region = models.CharField(max_length=32, blank=True, default="")
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: ListTagsForResource.
    tags = models.JSONField(null=True, blank=True, default=None)
    # The collector's configuration envelope; {} when the manifest entry does not persist it.
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_codepipeline_pipeline"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.get_name()
