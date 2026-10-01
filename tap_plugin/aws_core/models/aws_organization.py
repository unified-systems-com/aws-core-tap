"""AWS Organization — an AWS Organizations organization, which is also its own root."""

from typing import Any, ClassVar

from django.db import models
from tap_plugin.aws_core.policy_types import POLICY_TYPES

from tap_grid.models import BaseModel


class AwsOrganization(BaseModel):
    """An AWS Organizations organization.

    The organization node also stands for the organization's root. AWS allows exactly one root per
    organization, the root has no facts of its own beyond its id, and every root-level relationship
    (a top-level OU or account, a policy attached at the root) is the organization's. So there is no
    separate root type: the root's id is carried as ``root_id``, and edges that land on "the root"
    land on this node.

    Collected by ``Boto3Collector`` (``collectors/boto3_collector/organizations.py``) from
    ``organizations:DescribeOrganization``, ``ListRoots`` (with the root's ``PolicyTypes``),
    ``ListAWSServiceAccessForOrganization`` and the root's ``ListTagsForResource``; also design vocabulary, so every id may
    be blank because a designed organization exists before AWS mints one. Blank means not observed,
    for the ids and for the two enums alike (the aws_elb.lb_type convention). The organization is the
    containment parent of its OUs, its member accounts, its delegated administrations and its
    customer-managed policies (see CONTAINMENT_EDGES below). AWS cannot tag an organization but can
    tag its root (``organizations:TagResource`` takes an ``r-…`` id), and this node stands for the
    root, so ``tags`` is the root's.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-organizations, req-aws-core-organizations-completeness)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_organization"
    ENTITY_NAME: ClassVar[str] = "AWS Organization"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Organizations organization and its root: the tree of organizational units and member "
        "accounts that service control policies attach to."
    )
    ENTITY_ICON: ClassVar[str] = "aws-organizations"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "round-rectangle",
            "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"},
            "label": {"valign": "top", "halign": "center", "position": "outside"},
        }
    }

    # AWS's organization id (o-…). Blank ids never converge: identity_lock_key treats "" as a hole.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("organization_id",)

    # Containment (tap-plugin-aws-core#50, req-aws-core-organizations-reconcile). The two existing
    # tree edges point child -> parent (NESTED_UNDER_PARENT) and stay references: an account moves
    # between OUs and nothing ends the old edge, so a cascade through them would tombstone a live
    # account. Cascade and candidate derivation both walk from_entity_id=<parent>
    # (tap_grid/services/_impl.py::_contained_children, tap_grid/candidates.py::_children), so the
    # containment lives on two NEW parent -> child edges, each of a relation that never moves:
    #   PARTITIONED_INTO_OU  organization -> top-level OU. AWS has no operation that re-parents an
    #                        OU and refuses to delete a non-empty one.
    #   ENROLLS_ACCOUNT      organization -> member account, from the organization-wide ListAccounts.
    #                        Organization-level and not OU-level so that MoveAccount does not touch it.
    # An account outliving its REMOVAL FROM THE ORGANIZATION is the ordinary observation-lifetime
    # case (the grid stops observing it under this organization; the AWS account is not deleted), and
    # AwsAccount declares no containment, so retiring one ends its edges and cascades to nothing.
    #
    # FLAGGED FOR HUMAN SIGN-OFF, not something any review has approved (a code comment cannot
    # authorize itself — see tap-plugin-aws-core#50's PR body for the same statement in the one
    # place a verdict actually belongs): retiring or deleting the ORGANIZATION node itself DOES
    # cascade through ENROLLS_ACCOUNT and PARTITIONED_INTO_OU, tombstoning every member account
    # and OU this run holds it enrolled - and, per AwsAccount's own doc, ending every one of those
    # accounts' resources' BELONGS_TO_ACCOUNT edges (req-aws-core-reconcile-falsifiers-4's
    # "reference, not containment" ruling stays: only the EDGE ends, the resources stay live). The
    # author's reasoning for building it this way anyway, for a maintainer to weigh: (1) nothing
    # here ever retires the organization automatically - it has no falsifier
    # (req-aws-core-organizations-collect) - and tap_grid.services.delete_node's own `cascade`
    # argument defaults to "none", so this path needs BOTH a deliberate delete of the org node AND
    # an explicit cascade="contained" opt-in, the same footing as a VPC delete cascading its
    # subnets; (2) TAP_CASCADE_MAX_CLOSURE (tap_grid/services/_impl.py) still bounds the blast
    # radius - an organization whose account count would exceed it refuses the cascade rather than
    # half-applying it; (3) the alternative - leaving ENROLLS_ACCOUNT out of CONTAINMENT_EDGES -
    # would silence AccountFalsifier entirely, since candidate derivation is containment-gated with
    # no separate mechanism (tap_grid/candidates.py::_resolve_parent), which is the actual
    # capability this plugin was asked to deliver. An operator retiring an organization record with
    # cascade="contained" should read this comment before doing it.
    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {
            "nodes": [{"type": "aws_core__aws_organizational_unit"}],
            "edges": [{"type": "PARTITIONED_INTO_OU__aws_core"}],
        },
        {"nodes": [{"type": "aws_core__aws_account"}], "edges": [{"type": "ENROLLS_ACCOUNT__aws_core"}]},
        {
            "nodes": [{"type": "aws_core__aws_delegated_administration"}],
            "edges": [{"type": "HOLDS_DELEGATION__aws_core"}],
        },
        {
            "nodes": [{"type": "aws_core__aws_service_control_policy"}],
            "edges": [{"type": "HOLDS_SERVICE_CONTROL_POLICY__aws_core"}],
        },
        {
            "nodes": [{"type": "aws_core__aws_organizations_policy"}],
            "edges": [{"type": "HOLDS_ORGANIZATIONS_POLICY__aws_core"}],
        },
    ]
    # Organizations completeness (aws-core-tap#65, req-aws-core-organizations-completeness): the
    # organization also contains its delegated administrations and its CUSTOMER-MANAGED policies
    # (an AWS-managed policy has one ARN in every organization, so the collector never emits the
    # containment edge to one). Each has one organization-wide completeness surface, complete only
    # when every listing behind it finished (-13, -14). A deliberate contained delete of the
    # organization therefore also reaches those, and through the policies their statements and
    # tag-policy rules; it reaches no account and no AWS-managed policy.
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = (
        "PARTITIONED_INTO_OU__aws_core",
        "ENROLLS_ACCOUNT__aws_core",
        "HOLDS_DELEGATION__aws_core",
        "HOLDS_SERVICE_CONTROL_POLICY__aws_core",
        "HOLDS_ORGANIZATIONS_POLICY__aws_core",
    )

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "organization_id": {"type": "string", "pattern": "^(o-[a-z0-9]{10,32})?$"},
        "root_id": {"type": "string", "pattern": "^(r-[0-9a-z]{4,32})?$"},
        "management_account_id": {"type": "string", "pattern": "^([0-9]{12})?$"},
        "feature_set": {"type": "string", "enum": ["", "ALL", "CONSOLIDATED_BILLING"]},
        "partition": {"type": "string", "enum": ["", "aws", "aws-us-gov", "aws-cn"]},
        # The root's tags (req-aws-core-organizations-completeness-1). Null means NOT READ: the one
        # case is a credential that can DescribeOrganization but not ListRoots, which keeps the node
        # (req-aws-core-organizations-collect-4) but has no root id to read tags for. A root whose
        # tag read failed withholds the node instead, so null is never written over a read failure.
        "tags": {
            "type": ["object", "null"],
            "description": "The root's AWS Organizations tags as a flat {key: value} map; null when the root could not be listed this run.",
            "additionalProperties": {"type": "string", "description": "One tag value, verbatim."},
        },
        "enabled_policy_types": {
            "type": ["array", "null"],
            "description": "Root.PolicyTypes entries whose Status is ENABLED, sorted; null = not read, [] = observed none.",
            "items": {"type": "string", "enum": list(POLICY_TYPES), "description": "One organizations PolicyType value."},
        },
        "enabled_service_principals": {
            "type": ["array", "null"],
            "description": "ListAWSServiceAccessForOrganization, sorted by service principal; null when the call failed or a page after the first failed.",
            "items": {
                "type": "object",
                "description": "One AWS service with trusted access to the organization.",
                "additionalProperties": False,
                "required": ["service_principal", "enabled_at"],
                "properties": {
                    "service_principal": {"type": "string", "description": "EnabledServicePrincipal.ServicePrincipal, e.g. config.amazonaws.com."},
                    "enabled_at": {"type": "string", "description": "EnabledServicePrincipal.DateEnabled as ISO 8601 UTC; \"\" when AWS reported none."},
                },
            },
        },
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    # An organization has no name in AWS; `name` is the label its author or collector gives it.
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    organization_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    root_id = models.CharField(max_length=64, blank=True, default="")
    management_account_id = models.CharField(max_length=12, blank=True, default="")
    feature_set = models.CharField(max_length=32, blank=True, default="")
    partition = models.CharField(max_length=16, blank=True, default="")
    # The root's tags via the Organizations lane (organizations:ListTagsForResource on r-…).
    tags = models.JSONField(null=True, blank=True, default=dict)
    # Structured facts default to null, "not observed" (req-aws-core-fields-8).
    enabled_policy_types = models.JSONField(null=True, blank=True, default=None)
    enabled_service_principals = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_organization"

    def get_name(self) -> str:
        return self.name or self.organization_id

    def __str__(self) -> str:
        return self.get_name()
