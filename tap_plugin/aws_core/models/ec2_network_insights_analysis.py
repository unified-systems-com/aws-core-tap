"""AWS EC2 Network Insights Analysis — an AWS EC2 Network Insights Analysis."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Moment
from tap_grid.models import BaseModel


class Ec2NetworkInsightsAnalysis(BaseModel):
    """An AWS EC2 Network Insights Analysis, listed by DescribeNetworkInsightsAnalyses: one Reachability Analyzer run of a network insights path. Its status, whether it found a path, when it started and which path it ran are typed fields; the path's source and destination are on the path. The whole response is kept in configuration."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ec2_network_insights_analysis"
    ENTITY_NAME: ClassVar[str] = "AWS EC2 Network Insights Analysis"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS EC2 Network Insights Analysis."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (NetworkInsightsAnalysisArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("ec2_network_insights_analysis_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "ec2:network-insights-analysis"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): the analysis happened at StartDate
    # (DescribeNetworkInsightsAnalyses NetworkInsightsAnalyses[].StartDate, a botocore timestamp), read from the typed
    # start_date the collector fills from it. A moment of kind occurred: AWS states no end for this analysis.
    EVENT_TIME: ClassVar[Moment] = Moment(field="start_date", kind="occurred")

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "ec2_network_insights_analysis_arn": {"type": "string"},
        # Null is unobserved (req-aws-core-fields-10). Each is AWS's own value, as sent (req-aws-core-fields-11).
        "status": {"type": ["string", "null"]},
        "network_path_found": {"type": ["boolean", "null"]},
        "start_date": {"type": ["string", "null"]},
        "network_insights_path_id": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    ec2_network_insights_analysis_arn = models.CharField(max_length=2048, blank=True, default="")
    # running, succeeded or failed (AWS's enum, as sent).
    status = models.CharField(max_length=64, null=True, blank=True, default=None)
    # NetworkPathFound: whether the destination is reachable from the source. AWS omits it until the analysis ends.
    network_path_found = models.BooleanField(null=True, blank=True, default=None)
    # StartDate as ISO 8601 UTC text, as the envelope renders a botocore timestamp.
    start_date = models.CharField(max_length=64, null=True, blank=True, default=None)
    # NetworkInsightsPathId: the path analyzed; its source and destination are typed on the path
    # (aws_core__aws_ec2_network_insights_path), where AWS returns them.
    network_insights_path_id = models.CharField(max_length=255, null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ec2_network_insights_analysis"

    def get_name(self) -> str:
        return self.name or self.ec2_network_insights_analysis_arn

    def __str__(self) -> str:
        return self.get_name()
