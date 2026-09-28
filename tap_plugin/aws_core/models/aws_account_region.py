"""AWS Account Region — one AWS account's footprint in one region."""

from typing import Any, ClassVar

from django.db import models
from tap_grid.models import BaseModel


class AwsAccountRegion(BaseModel):
    """One account's footprint in one region: the parent that regional resources are contained under.

    The region-scoped containment substrate (tap-plugin-aws-core#49). It exists because every
    regional AWS listing is scoped by (credential's account, region) — ``ec2:DescribeVpcs`` in
    ``us-gov-west-1`` says nothing about ``us-gov-east-1`` or about another account — and the
    reconcile machinery needs a grid entity to be the *subject* of that listing.

    * **Not** ``AwsRegion``. ``AwsRegion`` is the region as AWS defines it, one node shared by every
      account; a listing read by account A is not a statement about account B's VPCs, so making the
      shared node the parent would turn A's complete listing into a candidate generator for B's
      resources. The identity here is the pair (account, region).
    * **Not** ``AwsAccount``. ``AwsAccount`` declares no containment on purpose (#46,
      ``BELONGS_TO_ACCOUNT`` is "a reference, not containment"): one account-wide fan-out would
      exceed the cascade cap, and one account holds many regions whose listings succeed or fail
      independently. A footprint per region bounds each fan-out and keeps each completeness claim
      about exactly the listing that made it.

    Retiring a footprint (which nothing does today — it has no falsifier and is a containment
    *source*, never a target) would cascade to every resource it hosts; that is intended, and it
    is why the account -> footprint link is the plain ``BELONGS_TO_ACCOUNT`` reference edge rather
    than a containment edge.
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_account_region"
    ENTITY_NAME: ClassVar[str] = "AWS Account Region"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "One AWS account's footprint in one region: the parent its regional resources are contained under."
    )
    ENTITY_ICON: ClassVar[str] = "aws-region"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): the pair (account id, region code). Neither alone
    # names it: a region code is shared by every account, an account id by every region. Both are
    # AWS's own stable identifiers and both are always known where a collector observes a footprint.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("account_id", "region_code")
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "round-rectangle",
            "colors": {"fill": "#B7E5E6", "border": "#00A4A6", "label": "#002D2E"},
            "label": {"valign": "top", "halign": "center", "position": "outside"},
        }
    }

    # One parent -> child edge type per contained type, each declared BOTH as outbound (a
    # constrained source) and as containment. CONTAINMENT_EDGES is a subset of OUTBOUND_EDGES
    # (import-time check, tap_grid.models.BaseModel.__init_subclass__). BELONGS_TO_ACCOUNT
    # (footprint -> account) is declared on that edge's own sources list and is deliberately NOT
    # containment. Written as LITERALS, not derived from tap_plugin.aws_core.regional's
    # REGIONAL_CHILDREN table: validate_plugin's structure-level "Model edge declarations name
    # defined edge types" check reads these two attributes with an AST literal parser (it runs
    # before Django, and before any model is importable) and refuses a computed expression it
    # cannot verify. tests/test_regional_containment.py is what keeps this list and
    # REGIONAL_CHILDREN from drifting apart instead.
    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "aws_core__aws_vpc"}], "edges": [{"type": "HOSTS_VPC__aws_core"}]},
        {"nodes": [{"type": "aws_core__aws_subnet"}], "edges": [{"type": "HOSTS_SUBNET__aws_core"}]},
        {"nodes": [{"type": "aws_core__aws_ec2_instance"}], "edges": [{"type": "HOSTS_EC2_INSTANCE__aws_core"}]},
        {
            "nodes": [{"type": "aws_core__aws_security_group"}],
            "edges": [{"type": "HOSTS_SECURITY_GROUP__aws_core"}],
        },
    ]
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = (
        "HOSTS_VPC__aws_core",
        "HOSTS_SUBNET__aws_core",
        "HOSTS_EC2_INSTANCE__aws_core",
        "HOSTS_SECURITY_GROUP__aws_core",
    )

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "account_id": {"type": "string"},
        "region_code": {"type": "string"},
        "partition": {"type": "string"},
        "opt_in_status": {"type": "string"},
        "status": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "account_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "region_code": {"validation": "jsonschema", "schema": {"type": "string"}},
        "partition": {"validation": "jsonschema", "schema": {"type": "string"}},
        "opt_in_status": {"validation": "jsonschema", "schema": {"type": "string"}},
        "status": {"validation": "jsonschema", "schema": {"type": "string"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    account_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    region_code = models.CharField(max_length=64, blank=True, default="", db_index=True)
    # The AWS partition the region lives in: "aws", "aws-us-gov" (GovCloud) or "aws-cn". Derived
    # from the region code by the collector (tap_plugin.aws_core.collectors.boto3_collector.regions).
    partition = models.CharField(max_length=32, blank=True, default="")
    # ec2:DescribeRegions OptInStatus, verbatim: "opt-in-not-required", "opted-in" or "not-opted-in".
    # Blank means the collector could not read it (not observed), never "not required".
    opt_in_status = models.CharField(max_length=32, blank=True, default="")
    # What the collector concluded about reading the region: "enabled" (positively known usable),
    # "disabled" (positively known not opted in: nothing was listed from it) or "unknown" (its status
    # could not be established). Only "enabled" — or a listing that returned resources — lets an empty
    # listing count as an observation (see the collector's region gate).
    status = models.CharField(max_length=16, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_account_region"

    def get_name(self) -> str:
        return self.name or f"{self.account_id} / {self.region_code}"

    def __str__(self) -> str:
        return self.get_name()
