"""AWS Service Control Policy — an AWS Organizations SCP."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsServiceControlPolicy(BaseModel):
    """A service control policy (SCP) in AWS Organizations.

    Where it applies is the ``ATTACHED_TO_TARGET`` edge to an OU, an account or the organization (the
    root). The policy document is not stored: no source fills a typed summary of it yet, and a raw
    document blob is exactly the unsourced JSON the model contract forbids. ``description`` carries
    the author's statement of intent, which is AWS's own field. Collected by ``Boto3Collector``
    (``collectors/boto3_collector/organizations.py``). Fields are those ``organizations:ListPolicies``
    (``PolicySummary``) and ``ListTagsForResource`` report. Its statements are
    ``aws_policy_statement`` nodes it contains (``DECLARES_STATEMENT``), read from
    ``DescribePolicy``; a customer-managed SCP is itself contained by its organization
    (``HOLDS_SERVICE_CONTROL_POLICY``), an AWS-managed one by none.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-organizations, req-aws-core-organizations-completeness)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_service_control_policy"
    ENTITY_NAME: ClassVar[str] = "AWS Service Control Policy"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Organizations service control policy: the maximum permissions available to the "
        "accounts under the OU, account or root it is attached to."
    )
    ENTITY_ICON: ClassVar[str] = "aws-organizations"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"},
        }
    }

    # Keyed on the policy ARN, not the bare id. AWS documents no global uniqueness for a customer
    # policy's p-… id; its ARN is scoped by the management account and organization
    # (arn:aws:organizations::<account>:policy/o-…/service_control_policy/p-…), so it is unique. An
    # AWS-managed policy such as FullAWSAccess has one ARN in every organization
    # (arn:aws:organizations::aws:policy/service_control_policy/p-FullAWSAccess), because it is one
    # AWS-owned object: one node, with each organization's use of it its own ATTACHED_TO_TARGET edge.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("policy_arn",)

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "aws_core__aws_policy_statement"}], "edges": [{"type": "DECLARES_STATEMENT__aws_core"}]},
    ]
    # A statement removed from the document becomes a candidate; retiring the SCP retires its
    # statements (req-aws-core-organizations-completeness-9, -10). This holds for AWS-managed SCPs
    # too: FullAWSAccess is contained by no organization, but its statements are contained by it.
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = ("DECLARES_STATEMENT__aws_core",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "policy_arn": {
            "type": "string",
            "pattern": (
                "^(arn:aws(-us-gov|-cn)?:organizations::([0-9]{12}|aws):policy/(o-[a-z0-9]{10,32}/)?"
                "service_control_policy/p-[0-9a-zA-Z_]{8,128})?$"
            ),
        },
        "policy_id": {"type": "string", "pattern": "^(p-[0-9a-zA-Z_]{8,128})?$"},
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
    # The id AttachPolicy takes; also the last segment of policy_arn, kept because it is what AWS's
    # policy APIs and the console show.
    policy_id = models.CharField(max_length=130, blank=True, default="")
    description = models.CharField(max_length=512, blank=True, default="")
    # PolicySummary.AwsManaged; null when not observed, so a designed policy is not asserted customer-managed.
    aws_managed = models.BooleanField(null=True, blank=True, default=None)
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: organizations:ListTagsForResource.
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_service_control_policy"

    def get_name(self) -> str:
        return self.name or self.policy_id

    def __str__(self) -> str:
        return self.get_name()
