"""AWS IAM Identity Center instance — the workforce sign-in service for an organization or account."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsIdentityCenterInstance(BaseModel):
    """An IAM Identity Center instance.

    Its external identity provider is the ``TRUSTS_IDENTITY_SOURCE`` edge, whose target is open
    because the provider lives in another plugin (an Okta application, for example) and aws_core
    declares no dependency on one. Fields are those ``sso-admin:ListInstances`` reports.

    Collected by ``Boto3Collector`` (``collectors/boto3_collector/landing_zone.py``). ``home_region``
    is the instance's ``PrimaryRegion`` (the instance ARN carries no region), or the region the call
    was made in when the response names none. A multi-region instance is returned by several
    regional endpoints and is one node, contained by its primary region's footprint
    (``HOSTS_IDENTITY_CENTER_INSTANCE``); ``regions`` holds every region it is replicated to. An
    instance whose primary region is outside the run's region scope is written with no footprint
    containment (``req-aws-landing-zone-identity-center-7``). It contains its permission sets,
    groups and account assignments.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-identity-center),
    specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-identity-center)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_identity_center_instance"
    ENTITY_NAME: ClassVar[str] = "AWS IAM Identity Center Instance"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An IAM Identity Center instance: where workforce users sign in to AWS accounts, with its "
        "users either held in its own identity store or taken from an external identity provider."
    )
    ENTITY_ICON: ClassVar[str] = "aws-identity-center"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    # AWS's instance ARN (arn:<partition>:sso:::instance/ssoins-…); partition-qualified, so unique.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("instance_arn",)

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {
            "nodes": [{"type": "aws_core__aws_identity_center_permission_set"}],
            "edges": [{"type": "HOLDS_PERMISSION_SET__aws_core"}],
        },
        {
            "nodes": [{"type": "aws_core__aws_identity_center_group"}],
            "edges": [{"type": "HOLDS_IDENTITY_GROUP__aws_core"}],
        },
        {
            "nodes": [{"type": "aws_core__aws_identity_center_account_assignment"}],
            "edges": [{"type": "HOLDS_ACCOUNT_ASSIGNMENT__aws_core"}],
        },
    ]
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = (
        "HOLDS_PERMISSION_SET__aws_core",
        "HOLDS_IDENTITY_GROUP__aws_core",
        "HOLDS_ACCOUNT_ASSIGNMENT__aws_core",
    )

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "instance_arn": {
            "type": "string",
            "pattern": "^(arn:(aws|aws-us-gov|aws-cn|aws-iso|aws-iso-b):sso:::instance/(sso)?ins-[a-zA-Z0-9-.]{16})?$",
        },
        "identity_store_id": {"type": "string"},
        "owner_account_id": {"type": "string", "pattern": "^([0-9]{12})?$"},
        "home_region": {"type": "string"},
        # Every region the instance is replicated to (InstanceMetadata.Regions); null when not reported.
        "regions": {"type": ["array", "null"], "items": {"type": "string"}},
        "status": {"type": "string"},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    instance_arn = models.CharField(max_length=1224, blank=True, default="", db_index=True)
    identity_store_id = models.CharField(max_length=64, blank=True, default="")
    # AWS's OwnerAccountId: the account the instance lives in (the management account or a delegated
    # administrator for an organization instance).
    owner_account_id = models.CharField(max_length=12, blank=True, default="")
    home_region = models.CharField(max_length=32, blank=True, default="")
    regions = models.JSONField(null=True, blank=True, default=None)
    status = models.CharField(max_length=32, blank=True, default="")
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: sso-admin:ListTagsForResource.
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_identity_center_instance"

    def get_name(self) -> str:
        return self.name or self.instance_arn

    def __str__(self) -> str:
        return self.get_name()
