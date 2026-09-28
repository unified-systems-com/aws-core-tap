"""AWS Account — an AWS account within an organization."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsAccount(BaseModel):
    """An AWS account."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_account"
    ENTITY_NAME: ClassVar[str] = "AWS Account"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS account within an organization."
    ENTITY_ICON: ClassVar[str] = "aws-account"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The 12-digit account ID, the boto3 collector's identity
    # for it.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("account_id",)

    # No containment declared (tap-plugin-aws-core#42, req-aws-core-reconcile-foundation). The
    # account is itself a containment TARGET of AwsOrganization (ENROLLS_ACCOUNT, #50); that does not
    # change anything below: it declares no containment of its own.
    # CONTAINMENT_EDGES can only name an edge type where THIS model is the source
    # (req-grid-service-delete-cascade-12; tap_grid.models.BaseModel.__init_subclass__ checks
    # CONTAINMENT_EDGES ⊆ OUTBOUND_EDGES, and cascade itself walks from_entity_id=<parent>,
    # tap_grid/services/_impl.py::_contained_children). BELONGS_TO_ACCOUNT — the one edge that
    # names every account-owned resource type — points resource -> account (this model is the
    # TARGET, never a source), and its own manifest description says why that direction is
    # deliberate, not an oversight: "A reference, not containment: a resource shared through AWS
    # RAM is used from other accounts, and an account's subtree can exceed the cascade cap"
    # (edges/BELONGS_TO_ACCOUNT.edge.json). Retiring an account therefore ends its resources'
    # BELONGS_TO_ACCOUNT edges (the tombstone endpoint rule) and leaves the resources themselves
    # live — each one's own truth is a question for that TYPE's falsifier, never a blanket
    # account-level cascade. Do not "fix" this by reversing BELONGS_TO_ACCOUNT's direction for
    # this model alone; that would contradict the edge's documented design and blow past
    # TAP_CASCADE_MAX_CLOSURE for any account with real fan-out.
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = ()

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "round-rectangle",
            "colors": {"fill": "#EBE1D5", "border": "#B89669", "label": "#332A1D"},
            "label": {"valign": "top", "halign": "center", "position": "outside"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "account_id": {"type": "string"},
        "email": {"type": "string"},
        "status": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "account_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "email": {"validation": "jsonschema", "schema": {"type": "string"}},
        "status": {"validation": "jsonschema", "schema": {"type": "string"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    # account_id is NOT required at create: a designed account (dcom=design) exists on the grid
    # before AWS has minted it, so its id is not observed yet. Blank (the field default) means
    # not observed, never "has no id"; the record validates whole, so it cannot carry a minLength.
    # A collected account always carries the id.
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    account_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    email = models.EmailField(blank=True, default="")
    status = models.CharField(max_length=64, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_account"

    def get_name(self) -> str:
        return self.name or self.account_id

    def __str__(self) -> str:
        return self.get_name()
