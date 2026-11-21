"""Amazon Inspector v2 network-reachability finding — the middle node of a compound edge from a VPC edge to an ENI."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsInspector2ReachabilityFinding(BaseModel):
    """One Amazon Inspector v2 ``NETWORK_REACHABILITY`` finding: an open port range on an EC2 network interface,
    reachable from a VPC edge along a path. Active, or closed in the last 30 days.

    The first compound edge (``req-grid-edge-compound``; aws-core-tap#261). The finding has an identity of its
    own (its ARN), a sender (the entry gateway), a receiver (the network interface) and the components the traffic
    passes through, so it is the middle node: ``REACHABILITY_SOURCE`` from the gateway, ``REACHABILITY_DESTINATION``
    to the network interface (not the instance: an instance can have several, and it is one ``ATTACHED_TO_INSTANCE``
    away), and ``TRAVERSES_COMPONENT`` to each route table, security group and network ACL on the path. It retires
    with either end. Contained by the account's region footprint (``HOSTS_INSPECTOR2_REACHABILITY_FINDING``).

    The port range and protocol are fields, not port nodes. ``network_path`` is ``networkPath.steps`` verbatim and
    in order. botocore types ``componentType`` as a free string and AWS documents no values, so a step's role is
    read from its id's documented prefix or its ARN, never from a guessed ``componentType``:
    ``component_types_unmatched`` lists every ``componentType`` value whose meaning is not documented, and
    ``unmatched_steps`` every step that matched no tabled type (``req-aws-landing-zone-inspector-reachability``).

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-inspector-reachability)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_inspector2_reachability_finding"
    ENTITY_NAME: ClassVar[str] = "Amazon Inspector Reachability Finding"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An Amazon Inspector v2 network-reachability finding: a TCP or UDP port range open on an EC2 network "
        "interface, reachable from an internet gateway, virtual private gateway, VPC peering connection or load "
        "balancer along a path of route tables, network ACLs and security groups. Drawn as one arrow."
    )
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("finding_arn",)
    # The service reference's inspector2 Finding, shared with aws_inspector2_finding: one ARN form for both types.
    ARN_RESOURCE: ClassVar[str | None] = "inspector2:Finding"

    # The compound edge (req-grid-edge-compound): a dict literal, read statically by tap.edge_declarations.
    COMPOUND_EDGE: ClassVar[dict[str, Any] | None] = {
        "source": "REACHABILITY_SOURCE__aws_core",
        "destination": "REACHABILITY_DESTINATION__aws_core",
        "carrier": None,
        "path": "TRAVERSES_COMPONENT__aws_core",
        "retires_with": ("source", "destination"),
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "finding_arn": {"type": "string"},
        "account_id": {"type": ["string", "null"]},
        "region": {"type": ["string", "null"]},
        # NETWORK_REACHABILITY.
        "finding_type": {"type": ["string", "null"]},
        # ACTIVE, SUPPRESSED or CLOSED, verbatim.
        "status": {"type": ["string", "null"]},
        "severity": {"type": ["string", "null"]},
        "inspector_score": {"type": ["number", "null"]},
        "title": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "remediation": {"type": ["string", "null"]},
        "remediation_url": {"type": ["string", "null"]},
        "first_observed_at": {"type": ["string", "null"]},
        "last_observed_at": {"type": ["string", "null"]},
        "updated_at": {"type": ["string", "null"]},
        "resource_type": {"type": ["string", "null"]},
        "resource_id": {"type": ["string", "null"]},
        # TCP or UDP, verbatim.
        "protocol": {"type": ["string", "null"]},
        "open_port_begin": {"type": ["integer", "null"], "minimum": 0, "maximum": 65535},
        "open_port_end": {"type": ["integer", "null"], "minimum": 0, "maximum": 65535},
        # networkReachabilityDetails.networkPath.steps, verbatim: [{componentId, componentType, componentArn}].
        "network_path": {"type": ["array", "null"], "items": {"type": "object"}},
        # Each componentType value the path carries whose meaning AWS does not document.
        "component_types_unmatched": {"type": ["array", "null"], "items": {"type": "string"}},
        # Each step no tabled type matched: {step, componentId, componentType, reason}.
        "unmatched_steps": {"type": ["array", "null"], "items": {"type": "object"}},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    finding_arn = models.CharField(max_length=2048, blank=True, default="", db_index=True)
    account_id = models.CharField(max_length=12, null=True, blank=True, default=None)
    region = models.CharField(max_length=32, null=True, blank=True, default=None)
    finding_type = models.CharField(max_length=32, null=True, blank=True, default=None)
    status = models.CharField(max_length=16, null=True, blank=True, default=None, db_index=True)
    severity = models.CharField(max_length=16, null=True, blank=True, default=None)
    inspector_score = models.FloatField(null=True, blank=True, default=None)
    title = models.CharField(max_length=1024, null=True, blank=True, default=None)
    description = models.TextField(null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    remediation = models.TextField(null=True, blank=True, default=None)  # noqa: DJ001 — null is "not read"
    remediation_url = models.CharField(max_length=2048, null=True, blank=True, default=None)
    first_observed_at = models.CharField(max_length=40, null=True, blank=True, default=None)
    last_observed_at = models.CharField(max_length=40, null=True, blank=True, default=None)
    updated_at = models.CharField(max_length=40, null=True, blank=True, default=None)
    resource_type = models.CharField(max_length=64, null=True, blank=True, default=None)
    resource_id = models.CharField(max_length=2048, null=True, blank=True, default=None)
    protocol = models.CharField(max_length=8, null=True, blank=True, default=None)
    open_port_begin = models.IntegerField(null=True, blank=True, default=None)
    open_port_end = models.IntegerField(null=True, blank=True, default=None)
    # Source: inspector2:ListFindings findings[].networkReachabilityDetails.networkPath.steps.
    network_path = models.JSONField(null=True, blank=True, default=None)
    # Source: derived from network_path (inspector.py, DOCUMENTED_COMPONENT_TYPES).
    component_types_unmatched = models.JSONField(null=True, blank=True, default=None)
    # Source: derived from network_path (inspector.py, classify_step).
    unmatched_steps = models.JSONField(null=True, blank=True, default=None)
    # AWS cannot tag a finding: always {} (tag_lanes.json, lane `none`).
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_inspector2_reachability_finding"

    def get_name(self) -> str:
        return self.name or self.finding_arn

    def __str__(self) -> str:
        return self.get_name()
