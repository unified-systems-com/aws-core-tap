"""AWS Organizations Policy — an organization policy of any type other than SCP."""

from typing import Any, ClassVar

from django.db import models
from tap_plugin.aws_core.policy_types import OTHER_POLICY_TYPES

from tap_grid.models import BaseModel


class AwsOrganizationsPolicy(BaseModel):
    """An AWS Organizations policy whose type is not ``SERVICE_CONTROL_POLICY``.

    Resource control policies, tag policies, declarative policies and the rest of the
    ``PolicyType`` enum. SCPs keep their own model (``AwsServiceControlPolicy``,
    ``req-aws-core-organizations``), so this type never holds an SCP. Read with
    ``organizations:ListPolicies(Filter=<type>)`` only for the types the root has ``ENABLED``, so
    a type the partition does not offer is never called (GovCloud allows SCP, RCP, tag and the
    declarative EC2 and S3 policies).

    Where it applies is the ``ATTACHED_TO_TARGET`` edge, as for SCPs. A customer-managed policy is
    contained by its organization (``HOLDS_ORGANIZATIONS_POLICY``); an AWS-managed one (one ARN
    in every organization) is not. Its body is read by type: an RCP's statements are
    ``aws_policy_statement`` nodes (``DECLARES_STATEMENT``), a tag policy's keys are
    ``aws_tag_policy_rule`` nodes (``DECLARES_TAG_RULE``), and the body of every other type is not
    read until an amendment names its typed fields (``req-aws-core-organizations-completeness-12``).
    No document blob is stored (``req-aws-core-organizations-7``).

    Spec: specs/spec-aws-core-v0.md (req-aws-core-organizations-completeness-5, -6)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_organizations_policy"
    ENTITY_NAME: ClassVar[str] = "AWS Organizations Policy"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Organizations policy other than a service control policy: a resource control policy, "
        "tag policy, declarative policy or another type the organization's root has enabled."
    )
    ENTITY_ICON: ClassVar[str] = "aws-organizations"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"},
        }
    }

    # Keyed on the ARN, as SCPs are: the p-… id has no documented global uniqueness, and an
    # AWS-managed policy's ARN is one AWS-owned object across every organization.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("policy_arn",)

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "aws_core__aws_policy_statement"}], "edges": [{"type": "DECLARES_STATEMENT__aws_core"}]},
        {"nodes": [{"type": "aws_core__aws_tag_policy_rule"}], "edges": [{"type": "DECLARES_TAG_RULE__aws_core"}]},
    ]
    # Statements (RCP) and tag rules (tag policy) are contained by their policy: a removed
    # statement or key becomes a candidate, and retiring the policy retires them. The collector
    # records a surface for both edge types on every policy it observes; the edge type a policy's
    # type cannot carry is recorded complete and empty.
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = ("DECLARES_STATEMENT__aws_core", "DECLARES_TAG_RULE__aws_core")

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "policy_arn": {
            "type": "string",
            "pattern": (
                "^(arn:aws(-us-gov|-cn)?:organizations::([0-9]{12}|aws):policy/(o-[a-z0-9]{10,32}/)?"
                "[a-z0-9_]+/p-[0-9a-zA-Z_]{8,128})?$"
            ),
        },
        "policy_id": {"type": "string", "pattern": "^(p-[0-9a-zA-Z_]{8,128})?$"},
        # PolicySummary.Type; "" when not observed. Never SERVICE_CONTROL_POLICY (own model).
        "policy_type": {"type": "string", "enum": ["", *OTHER_POLICY_TYPES]},
        "description": {"type": "string"},
        "aws_managed": {"type": ["boolean", "null"]},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=128, blank=True, default="")
    policy_arn = models.CharField(max_length=512, blank=True, default="", db_index=True)
    policy_id = models.CharField(max_length=130, blank=True, default="")
    policy_type = models.CharField(max_length=64, blank=True, default="")
    description = models.CharField(max_length=512, blank=True, default="")
    # PolicySummary.AwsManaged; null when not observed.
    aws_managed = models.BooleanField(null=True, blank=True, default=None)
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: organizations:ListTagsForResource
    # (the Organizations lane), for customer-managed policies; an AWS-managed policy cannot be tagged.
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_organizations_policy"

    def get_name(self) -> str:
        return self.name or self.policy_id

    def __str__(self) -> str:
        return self.get_name()
