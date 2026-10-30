"""Direct Connect Gateway — the global hub that joins virtual interfaces to VPCs and transit gateways."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class DxGateway(BaseModel):
    """An AWS Direct Connect gateway.

    A global object (no region). Private and transit virtual interfaces attach to it
    (``ATTACHED_TO_DX_GATEWAY``). Its association with a transit gateway is the transit gateway
    attachment AWS creates for it (resource type ``direct-connect-gateway``), linked here by
    ``ATTACHES_DX_GATEWAY``. Design vocabulary: no collector emits it yet. Fields are those
    ``directconnect:DescribeDirectConnectGateways`` reports. It carries no ``tags``: that call returns
    none.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-direct-connect)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_dx_gateway"
    ENTITY_NAME: ClassVar[str] = "Direct Connect Gateway"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Direct Connect gateway: a global hub joining Direct Connect virtual interfaces to "
        "transit gateways and virtual private gateways."
    )
    ENTITY_ICON: ClassVar[str] = "aws-direct-connect"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }

    # AWS's Direct Connect gateway id, a UUID.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("direct_connect_gateway_id",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "direct_connect_gateway_id": {
            "type": "string",
            "pattern": "^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?$",
        },
        "amazon_side_asn": {
            "anyOf": [
                {"type": "null"},
                {"type": "integer", "minimum": 64512, "maximum": 65534},
                {"type": "integer", "minimum": 4200000000, "maximum": 4294967294},
            ]
        },
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    direct_connect_gateway_id = models.CharField(max_length=36, blank=True, default="", db_index=True)
    # amazonSideAsn: AWS accepts only the private ranges 64512-65534 and 4200000000-4294967294.
    amazon_side_asn = models.BigIntegerField(null=True, blank=True, default=None)
    # The collector's configuration envelope; {} when the manifest entry does not persist it.
    configuration = models.JSONField(default=dict, blank=True)
    # AWS tags, canonical flat {str: str}. NULL = not read; {} = read, untagged.
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_dx_gateway"

    def get_name(self) -> str:
        return self.name or self.direct_connect_gateway_id

    def __str__(self) -> str:
        return self.get_name()
