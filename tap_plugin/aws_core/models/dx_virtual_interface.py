"""Direct Connect Virtual Interface — a VLAN with its own BGP session on a Direct Connect connection."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel

# directconnect virtualInterfaceType, as DescribeVirtualInterfaces reports it.
VIF_TYPES = ["private", "public", "transit"]


class DxVirtualInterface(BaseModel):
    """An AWS Direct Connect virtual interface (VIF).

    Rides on a connection (``CARRIED_ON_CONNECTION``); a private or transit VIF attaches to a Direct
    Connect gateway (``ATTACHED_TO_DX_GATEWAY``). Design vocabulary: no collector emits it yet.
    Fields are those ``directconnect:DescribeVirtualInterfaces`` reports.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-direct-connect)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_dx_virtual_interface"
    ENTITY_NAME: ClassVar[str] = "Direct Connect Virtual Interface"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Direct Connect virtual interface: a VLAN with its own BGP session on a Direct Connect "
        "connection, reaching a VPC (private), a transit gateway (transit) or AWS public endpoints (public)."
    )
    ENTITY_ICON: ClassVar[str] = "aws-direct-connect"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }

    # AWS's virtual interface id (dxvif-…).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("virtual_interface_id",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "virtual_interface_id": {"type": "string", "pattern": "^(dxvif-[a-z0-9]{8,12})?$"},
        "virtual_interface_type": {"type": "string", "enum": ["", *VIF_TYPES]},
        "vlan": {"type": ["integer", "null"], "minimum": 1, "maximum": 4094},
        "customer_asn": {"type": ["integer", "null"], "minimum": 1, "maximum": 4294967294},
        "region": {"type": "string"},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    virtual_interface_id = models.CharField(max_length=32, blank=True, default="", db_index=True)
    # Blank means not observed (the aws_elb.lb_type convention).
    virtual_interface_type = models.CharField(max_length=16, blank=True, default="")
    vlan = models.IntegerField(null=True, blank=True, default=None)
    # AWS's `asn`: the customer side's BGP ASN (public or private), not Amazon's.
    customer_asn = models.BigIntegerField(null=True, blank=True, default=None)
    region = models.CharField(max_length=32, blank=True, default="")
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: DescribeVirtualInterfaces tags.
    tags = models.JSONField(null=True, blank=True, default=None)
    # The collector's configuration envelope; {} when the manifest entry does not persist it.
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_dx_virtual_interface"

    def get_name(self) -> str:
        return self.name or self.virtual_interface_id

    def __str__(self) -> str:
        return self.get_name()
