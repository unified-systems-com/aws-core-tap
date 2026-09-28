"""AWS Organizational Unit — a container for accounts inside an AWS Organizations tree."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsOrganizationalUnit(BaseModel):
    """An organizational unit (OU) in an AWS Organizations tree.

    Its place in the tree is the ``NESTED_UNDER_PARENT`` edge to its parent OU or to the organization
    (which stands for the root); the parent's ``PARTITIONED_INTO_OU`` edge to it is the containment.
    Collected by ``Boto3Collector`` (``collectors/boto3_collector/organizations.py``); also design
    vocabulary. Fields are those ``organizations:ListOrganizationalUnitsForParent`` and
    ``ListTagsForResource`` report.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-organizations)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_organizational_unit"
    ENTITY_NAME: ClassVar[str] = "AWS Organizational Unit"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An organizational unit in an AWS Organizations tree: a container for accounts and further OUs "
        "that service control policies attach to."
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

    # AWS's OU id (ou-…). Unique within its organization; AWS mints it with the org's root id
    # embedded, so it does not collide across organizations.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("ou_id",)

    # A nested OU is contained by its parent OU (tap-plugin-aws-core#50): AWS never re-parents an OU
    # and refuses to delete a non-empty one, so PARTITIONED_INTO_OU is safe as containment where the
    # child -> parent NESTED_UNDER_PARENT reference is not. An OU declares NO edge to its accounts as
    # containment: an account is enrolled by the organization (ENROLLS_ACCOUNT), and its OU changes
    # under MoveAccount, which would leave a stale OU -> account edge for a cascade to follow.
    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {
            "nodes": [{"type": "aws_core__aws_organizational_unit"}],
            "edges": [{"type": "PARTITIONED_INTO_OU__aws_core"}],
        },
    ]
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = ("PARTITIONED_INTO_OU__aws_core",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "ou_id": {"type": "string", "pattern": "^(ou-[0-9a-z]{4,32}-[a-z0-9]{8,32})?$"},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    ou_id = models.CharField(max_length=80, blank=True, default="", db_index=True)
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: organizations:ListTagsForResource.
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_organizational_unit"

    def get_name(self) -> str:
        return self.name or self.ou_id

    def __str__(self) -> str:
        return self.get_name()
