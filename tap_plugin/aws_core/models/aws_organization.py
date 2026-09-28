"""AWS Organization — an AWS Organizations organization, which is also its own root."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsOrganization(BaseModel):
    """An AWS Organizations organization.

    The organization node also stands for the organization's root. AWS allows exactly one root per
    organization, the root has no facts of its own beyond its id, and every root-level relationship
    (a top-level OU or account, a policy attached at the root) is the organization's. So there is no
    separate root type: the root's id is carried as ``root_id``, and edges that land on "the root"
    land on this node.

    Design vocabulary: no collector emits it yet. Every field is one AWS reports
    (``organizations:DescribeOrganization`` and ``ListRoots``), and every id may be blank because a
    designed organization exists before AWS mints one. Blank means not observed, for the ids and
    for the two enums alike (the aws_elb.lb_type convention).

    Spec: specs/spec-aws-core-v0.md (req-aws-core-organizations)
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

    # No containment declared (tap-plugin-aws-core#42, req-aws-core-reconcile-foundation) — this
    # is already the documented ruling in req-aws-core-organizations above, restated here as a
    # CLASS-LEVEL declaration rather than leaving it implicit via BaseModel's default: "No
    # containment is declared. Both edges point child -> parent (and policy -> target), and
    # CONTAINMENT_EDGES can only name outbound edges; an account also outlives its organization."
    # NESTED_UNDER_PARENT (OU/account -> OU/organization) is the ONE tree edge and it points
    # child -> parent, so this model is never its source; cascade
    # (tap_grid/services/_impl.py::_contained_children) walks from_entity_id=<parent> and cannot
    # follow an inbound edge. Splitting NESTED_UNDER_PARENT into a separate parent -> child
    # containment edge (an org "owns" its OU tree the way a VPC owns its subnets, even though an
    # account merely sits IN the tree and outlives it) is a real, larger design question — a new
    # edge type shared with AwsOrganizationalUnit — deliberately left to a follow-up rather than
    # decided unilaterally here.
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = ()

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "organization_id": {"type": "string", "pattern": "^(o-[a-z0-9]{10,32})?$"},
        "root_id": {"type": "string", "pattern": "^(r-[0-9a-z]{4,32})?$"},
        "management_account_id": {"type": "string", "pattern": "^([0-9]{12})?$"},
        "feature_set": {"type": "string", "enum": ["", "ALL", "CONSOLIDATED_BILLING"]},
        "partition": {"type": "string", "enum": ["", "aws", "aws-us-gov", "aws-cn"]},
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

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_organization"

    def get_name(self) -> str:
        return self.name or self.organization_id

    def __str__(self) -> str:
        return self.get_name()
