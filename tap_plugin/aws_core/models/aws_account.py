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

    # Containment: the account-EXCLUSIVE resources, and only those (aws-core-tap#43, which deliberately
    # supersedes the empty declaration tap-plugin-aws-core#42 made here).
    #
    # #42 left this empty for a sound reason that still stands for the general case: BELONGS_TO_ACCOUNT is
    # the one edge naming every account-owned type, it points resource -> account (this model is its TARGET,
    # and cascade / candidate fan-out both walk from_entity_id=<parent>), and its own description says it is
    # "a reference, not containment: a resource shared through AWS RAM is used from other accounts, and an
    # account's subtree can exceed the cascade cap". So BELONGS_TO_ACCOUNT stays a reference, unreversed.
    #
    # The five types below are different in kind: an IAM role, IAM user, customer-managed IAM policy, IAM
    # OIDC provider and S3 bucket each exist in exactly ONE account. None can be shared through RAM, none
    # is visible from another account's listing, and the account's own listing of each is the complete
    # inventory of them (IAM is global per account and partition; S3 ListBuckets is account-wide). Each gets
    # its own NEW parent -> child edge type, one per listing, because candidate derivation fans out through
    # an edge type and a run must be able to say "roles were read to the end" without saying anything about
    # users. The edge types are not BELONGS_TO_ACCOUNT under another name: they are emitted by the collector
    # only from a listing it read, and a completeness surface is recorded only when that listing was
    # paginated to the end (collectors/boto3_collector/listing.py).
    #
    # Everything else an account owns stays a reference (EC2, VPCs, ...): those are regional, shareable, or
    # fan out past TAP_CASCADE_MAX_CLOSURE, and each has its own regional listing to earn containment
    # from. An account with more than the cascade cap of these five combined will refuse a contained
    # cascade and a >5000-child surface is recorded fan_out_exceeds_cap rather than derived: the failure is
    # loud and safe, never a silent partial retirement.
    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "aws_core__aws_iam_role"}], "edges": [{"type": "OWNS_IAM_ROLE__aws_core"}]},
        {"nodes": [{"type": "aws_core__aws_iam_user"}], "edges": [{"type": "OWNS_IAM_USER__aws_core"}]},
        {"nodes": [{"type": "aws_core__aws_iam_policy"}], "edges": [{"type": "OWNS_IAM_POLICY__aws_core"}]},
        {"nodes": [{"type": "aws_core__aws_iam_oidc_provider"}], "edges": [{"type": "OWNS_OIDC_PROVIDER__aws_core"}]},
        {"nodes": [{"type": "aws_core__aws_s3_bucket"}], "edges": [{"type": "OWNS_BUCKET__aws_core"}]},
    ]
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = (
        "OWNS_IAM_ROLE__aws_core",
        "OWNS_IAM_USER__aws_core",
        "OWNS_IAM_POLICY__aws_core",
        "OWNS_OIDC_PROVIDER__aws_core",
        "OWNS_BUCKET__aws_core",
    )

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
