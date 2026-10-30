"""Transit Gateway Attachment — one connection between a transit gateway and a VPC, VPN or peer."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel

# ec2 TransitGatewayAttachmentResourceType, as DescribeTransitGatewayAttachments reports it.
RESOURCE_TYPES = [
    "vpc",
    "vpn",
    "vpn-concentrator",
    "direct-connect-gateway",
    "connect",
    "peering",
    "tgw-peering",
    "network-function",
]


class TransitGatewayAttachment(BaseModel):
    """An AWS Transit Gateway attachment.

    Its transit gateway is the ``ATTACHED_TO_TRANSIT_GATEWAY`` edge. What it connects is
    ``ATTACHES_VPC`` for a VPC attachment and ``PEERS_WITH_TRANSIT_GATEWAY`` for a peering attachment;
    VPN, Direct Connect and Connect attachments have no far-side node type in aws_core yet. Design
    vocabulary: no collector emits it yet. Fields are those ``ec2:DescribeTransitGatewayAttachments``
    reports.

    ``resource_owner_account_id`` is AWS's ``ResourceOwnerId``: the account that owns the attached
    VPC or peer, which differs from the transit gateway's owner whenever the attachment crosses
    accounts. The transit gateway's owner is not repeated here; it is on the transit gateway node.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-transit-gateway)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_transit_gateway_attachment"
    ENTITY_NAME: ClassVar[str] = "Transit Gateway Attachment"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Transit Gateway attachment: one connection between a transit gateway and a VPC, VPN, "
        "Direct Connect gateway, Connect peer or a peer transit gateway."
    )
    ENTITY_ICON: ClassVar[str] = "aws-transit-gateway"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }

    # AWS's attachment id (tgw-attach-…). A peering attachment is one object with one id, reported
    # from both sides.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("attachment_id",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "attachment_id": {"type": "string", "pattern": "^(tgw-attach-[0-9a-f]{8,17})?$"},
        "resource_type": {"type": "string", "enum": ["", *RESOURCE_TYPES]},
        "resource_owner_account_id": {"type": "string", "pattern": "^([0-9]{12})?$"},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    attachment_id = models.CharField(max_length=40, blank=True, default="", db_index=True)
    # Blank means not observed (the aws_elb.lb_type convention).
    resource_type = models.CharField(max_length=32, blank=True, default="")
    resource_owner_account_id = models.CharField(max_length=12, blank=True, default="")
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: DescribeTransitGatewayAttachments Tags.
    tags = models.JSONField(null=True, blank=True, default=None)
    # The collector's configuration envelope; {} when the manifest entry does not persist it.
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_transit_gateway_attachment"

    def get_name(self) -> str:
        return self.name or self.attachment_id

    def __str__(self) -> str:
        return self.get_name()
