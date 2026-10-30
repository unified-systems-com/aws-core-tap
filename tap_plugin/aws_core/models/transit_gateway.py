"""Transit Gateway — an AWS Transit Gateway regional network hub."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class TransitGateway(BaseModel):
    """An AWS Transit Gateway.

    VPCs, VPNs and peer transit gateways connect to it through ``aws_transit_gateway_attachment``
    nodes. Design vocabulary: no collector emits it yet. Fields are those
    ``ec2:DescribeTransitGateways`` reports; the three option flags come from its ``Options`` and are
    null until stated.

    ``owner_account_id`` is AWS's ``OwnerId``. A transit gateway is routinely shared through AWS RAM,
    so the account a collector observes it from is not necessarily the one that owns it.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-transit-gateway)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_transit_gateway"
    ENTITY_NAME: ClassVar[str] = "Transit Gateway"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Transit Gateway: a regional hub that routes traffic between the VPCs, VPNs and peer "
        "transit gateways attached to it."
    )
    ENTITY_ICON: ClassVar[str] = "aws-transit-gateway"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }

    # AWS's transit gateway id (tgw-…).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("transit_gateway_id",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "transit_gateway_id": {"type": "string", "pattern": "^(tgw-[0-9a-f]{8,17})?$"},
        "owner_account_id": {"type": "string", "pattern": "^([0-9]{12})?$"},
        "region": {"type": "string"},
        "amazon_side_asn": {
            "anyOf": [
                {"type": "null"},
                {"type": "integer", "minimum": 64512, "maximum": 65534},
                {"type": "integer", "minimum": 4200000000, "maximum": 4294967294},
            ]
        },
        "auto_accept_shared_attachments": {"type": ["boolean", "null"]},
        "default_route_table_association": {"type": ["boolean", "null"]},
        "default_route_table_propagation": {"type": ["boolean", "null"]},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    transit_gateway_id = models.CharField(max_length=32, blank=True, default="", db_index=True)
    owner_account_id = models.CharField(max_length=12, blank=True, default="")
    region = models.CharField(max_length=32, blank=True, default="")
    # Options.AmazonSideAsn: AWS accepts only the private ranges 64512-65534 and 4200000000-4294967294
    # (the second is wider than a 32-bit signed int); the schema allows exactly those, or null.
    amazon_side_asn = models.BigIntegerField(null=True, blank=True, default=None)
    # Options.AutoAcceptSharedAttachments / DefaultRouteTableAssociation / DefaultRouteTablePropagation:
    # AWS reports "enable" / "disable"; true / false here, null when not observed.
    auto_accept_shared_attachments = models.BooleanField(null=True, blank=True, default=None)
    default_route_table_association = models.BooleanField(null=True, blank=True, default=None)
    default_route_table_propagation = models.BooleanField(null=True, blank=True, default=None)
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: DescribeTransitGateways Tags.
    tags = models.JSONField(null=True, blank=True, default=None)
    # The collector's configuration envelope; {} when the manifest entry does not persist it.
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_transit_gateway"

    def get_name(self) -> str:
        return self.name or self.transit_gateway_id

    def __str__(self) -> str:
        return self.get_name()
