"""AWS EC2 Network Insights Access Scope Analysis — an AWS EC2 Network Insights Access Scope Analysis."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class Ec2NetworkInsightsAccessScopeAnalysis(BaseModel):
    """An AWS EC2 Network Insights Access Scope Analysis, listed by DescribeNetworkInsightsAccessScopeAnalyses: one run of a Network Access Analyzer scope. Its status, whether it found anything, how many network interfaces it analyzed, when it ran and which scope it ran are typed fields; the whole response is kept in configuration."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ec2_network_insights_access_scope_analysis"
    ENTITY_NAME: ClassVar[str] = "AWS EC2 Network Insights Access Scope Analysis"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS EC2 Network Insights Access Scope Analysis."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (NetworkInsightsAccessScopeAnalysisArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("ec2_network_insights_access_scope_analysis_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "ec2:network-insights-access-scope-analysis"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): the analysis ran from StartDate to EndDate
    # (DescribeNetworkInsightsAccessScopeAnalyses NetworkInsightsAccessScopeAnalyses[], botocore timestamps), read
    # from the typed start_date and end_date the collector fills from them. An interval of kind occurred: a run that
    # happened, not a thing created; a running analysis has no EndDate yet, and holds from its start.
    EVENT_TIME: ClassVar[Interval] = Interval(start="start_date", kind="occurred", end="end_date")

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "ec2_network_insights_access_scope_analysis_arn": {"type": "string"},
        # Null is unobserved (req-aws-core-fields-10). Each is AWS's own value, as sent (req-aws-core-fields-11).
        "status": {"type": ["string", "null"]},
        "findings_found": {"type": ["string", "null"]},
        "analyzed_eni_count": {"type": ["integer", "null"]},
        "start_date": {"type": ["string", "null"]},
        "end_date": {"type": ["string", "null"]},
        "access_scope_id": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    ec2_network_insights_access_scope_analysis_arn = models.CharField(max_length=2048, blank=True, default="")
    # running, succeeded or failed (AWS's enum, as sent).
    status = models.CharField(max_length=64, null=True, blank=True, default=None)
    # FindingsFound: AWS's own three-valued text, "true", "false" or "unknown", kept as text so "unknown" is not lost.
    findings_found = models.CharField(max_length=16, null=True, blank=True, default=None)
    # AnalyzedEniCount: the number of network interfaces the analysis examined (AWS counts only those).
    analyzed_eni_count = models.IntegerField(null=True, blank=True, default=None)
    # StartDate and EndDate as ISO 8601 UTC text, as the envelope renders a botocore timestamp; no EndDate while running.
    start_date = models.CharField(max_length=64, null=True, blank=True, default=None)
    end_date = models.CharField(max_length=64, null=True, blank=True, default=None)
    # NetworkInsightsAccessScopeId: the scope this analysis ran.
    access_scope_id = models.CharField(max_length=255, null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ec2_network_insights_access_scope_analysis"

    def get_name(self) -> str:
        return self.name or self.ec2_network_insights_access_scope_analysis_arn

    def __str__(self) -> str:
        return self.get_name()
