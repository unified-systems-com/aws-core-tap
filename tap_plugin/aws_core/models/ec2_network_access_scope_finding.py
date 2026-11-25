"""VPC Network Access Analyzer finding — the middle node of a compound edge from a path's first component to its last."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class Ec2NetworkAccessScopeFinding(BaseModel):
    """One finding of a VPC Network Access Analyzer access scope analysis: a network path the scope flags, read from
    ``GetNetworkInsightsAccessScopeAnalysisFindings`` for an analysis that succeeded.

    A finding is its own node (ruled 2026-11-09 on aws-core-tap#212) and the middle node of a compound edge
    (``req-grid-edge-compound``), following the Inspector reachability finding: ``ACCESS_SCOPE_FINDING_SOURCE`` from
    the path's first component, ``ACCESS_SCOPE_FINDING_DESTINATION`` to its last, and ``TRAVERSES_COMPONENT`` (with
    ``step``) to each component between them, each typed from its resource id or ARN and only where the Network
    Access Analyzer guide lists the type for that role. It retires with either end. Its analysis has
    ``REPORTS_ACCESS_SCOPE_FINDING`` to it.

    AWS gives a finding no ARN and no time of its own. It is keyed by its analysis's ARN and its ``FindingId``, and
    dated by the analysis that found it: ``analysis_start_date`` and ``analysis_end_date`` are that analysis's
    ``StartDate`` and ``EndDate``. The whole finding is kept in ``configuration``, its ``FindingComponents`` verbatim
    and in AWS's order; the typed fields name the first and last components as AWS sent them, whether or not a node
    matches, and ``unmatched_components`` lists every component that got no edge and why.

    Spec: specs/spec-aws-core-collector-v0.md (req-aws-collector-network-analyzer)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ec2_network_access_scope_finding"
    ENTITY_NAME: ClassVar[str] = "AWS EC2 Network Access Scope Finding"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "A VPC Network Access Analyzer finding: a network path an access scope analysis flagged, from where it "
        "starts (an internet gateway, network interface, endpoint, peering connection, transit gateway attachment "
        "or virtual private gateway) through route tables, security groups, network ACLs and gateways to where it "
        "ends. Drawn as one arrow."
    )
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }

    # Identity (req-grid-entity-natural-key, req-aws-collector-identity-8, -13): AWS gives a finding no ARN and
    # addresses it only through its analysis, so it is keyed by the analysis's ARN (which carries partition, account
    # and region) and the FindingId, both as AWS returns them. The manifest's `_key` is the batch ref only.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("analysis_arn", "finding_id")
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): the finding is what one analysis run observed,
    # and AWS dates only the run: StartDate to EndDate of the analysis (DescribeNetworkInsightsAccessScopeAnalyses
    # NetworkInsightsAccessScopeAnalyses[], botocore timestamps), copied to analysis_start_date and analysis_end_date.
    # The finding itself (botocore AccessScopeAnalysisFinding) carries no time. An interval of kind occurred, as its
    # analysis declares.
    EVENT_TIME: ClassVar[Interval] = Interval(start="analysis_start_date", kind="occurred", end="analysis_end_date")

    # The compound edge (req-grid-edge-compound): a dict literal, read statically by tap.edge_declarations.
    COMPOUND_EDGE: ClassVar[dict[str, Any] | None] = {
        "source": "ACCESS_SCOPE_FINDING_SOURCE__aws_core",
        "destination": "ACCESS_SCOPE_FINDING_DESTINATION__aws_core",
        "carrier": None,
        "path": "TRAVERSES_COMPONENT__aws_core",
        "retires_with": ("source", "destination"),
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "analysis_arn": {"type": "string"},
        "finding_id": {"type": "string"},
        # Null is unobserved (req-aws-core-fields-10). Each is AWS's own value, as sent (req-aws-core-fields-11).
        "analysis_id": {"type": ["string", "null"]},
        "access_scope_id": {"type": ["string", "null"]},
        "analysis_start_date": {"type": ["string", "null"]},
        "analysis_end_date": {"type": ["string", "null"]},
        "component_count": {"type": ["integer", "null"], "minimum": 0},
        "source_component_id": {"type": ["string", "null"]},
        "source_component_arn": {"type": ["string", "null"]},
        "destination_component_id": {"type": ["string", "null"]},
        "destination_component_arn": {"type": ["string", "null"]},
        # Each component that got no edge: {step, id, arn, reason}.
        "unmatched_components": {"type": ["array", "null"], "items": {"type": "object"}},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    # Source: the analysis's NetworkInsightsAccessScopeAnalysisArn (DescribeNetworkInsightsAccessScopeAnalyses).
    analysis_arn = models.CharField(max_length=2048, blank=True, default="", db_index=True)
    # Source: GetNetworkInsightsAccessScopeAnalysisFindings AnalysisFindings[].FindingId.
    finding_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    # Source: AnalysisFindings[].NetworkInsightsAccessScopeAnalysisId.
    analysis_id = models.CharField(max_length=255, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    # Source: AnalysisFindings[].NetworkInsightsAccessScopeId.
    access_scope_id = models.CharField(max_length=255, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    # Source: the analysis's StartDate and EndDate, as ISO 8601 UTC text.
    analysis_start_date = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    analysis_end_date = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    # Source: the number of FindingComponents.
    component_count = models.IntegerField(null=True, blank=True, default=None)
    # Source: Component.Id and Component.Arn of the first and last FindingComponents in SequenceNumber order.
    source_component_id = models.CharField(max_length=2048, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    source_component_arn = models.CharField(max_length=2048, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    destination_component_id = models.CharField(max_length=2048, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    destination_component_arn = models.CharField(max_length=2048, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    # Source: derived from FindingComponents (network_insights.read_path).
    unmatched_components = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    # AWS cannot tag a finding: always {} (the manifest entry's tag lane is `none`).
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ec2_network_access_scope_finding"

    def get_name(self) -> str:
        return self.name or self.finding_id

    def __str__(self) -> str:
        return self.get_name()
