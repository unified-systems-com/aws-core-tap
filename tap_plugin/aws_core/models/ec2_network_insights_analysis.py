"""AWS EC2 Network Insights Analysis — an AWS EC2 Network Insights Analysis."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import NO_EVENT_TIME, NoEventTime
from tap_grid.models import BaseModel


class Ec2NetworkInsightsAnalysis(BaseModel):
    """An AWS EC2 Network Insights Analysis, listed by DescribeNetworkInsightsAnalyses. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ec2_network_insights_analysis"
    ENTITY_NAME: ClassVar[str] = "AWS EC2 Network Insights Analysis"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS EC2 Network Insights Analysis."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (NetworkInsightsAnalysisArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("ec2_network_insights_analysis_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "ec2:network-insights-analysis"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): no typed field of this model says when
    # the thing happened in the world; EVENT_TIME_REASON says why.
    EVENT_TIME: ClassVar[NoEventTime] = NO_EVENT_TIME
    EVENT_TIME_REASON: ClassVar[str] = (
        "AWS returns no creation time in its own record (DescribeNetworkInsightsAnalyses NetworkInsightsAnalyses[]); "
        "the times it does return there (StartDate) are held only inside configuration."
    )

    # The compound edge (req-grid-edge-compound, req-aws-collector-network-analyzer): the analysis is itself the middle
    # node, as the Inspector reachability finding is: it has its own identity (its ARN) and time (StartDate), and when
    # AWS found a path (NetworkPathFound) a sender, a receiver and the hops between them (ForwardPathComponents).
    # REACHABILITY_ANALYSIS_SOURCE runs from the forward path's first component, REACHABILITY_ANALYSIS_DESTINATION to its
    # last, TRAVERSES_COMPONENT to each one between (collectors/boto3_collector/network_insights.py). It retires with
    # either end. An analysis that found no path has no role edges.
    COMPOUND_EDGE: ClassVar[dict[str, Any] | None] = {
        "source": "REACHABILITY_ANALYSIS_SOURCE__aws_core",
        "destination": "REACHABILITY_ANALYSIS_DESTINATION__aws_core",
        "carrier": None,
        "path": "TRAVERSES_COMPONENT__aws_core",
        "retires_with": ("source", "destination"),
    }

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "ec2_network_insights_analysis_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    ec2_network_insights_analysis_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ec2_network_insights_analysis"

    def get_name(self) -> str:
        return self.name or self.ec2_network_insights_analysis_arn

    def __str__(self) -> str:
        return self.get_name()
