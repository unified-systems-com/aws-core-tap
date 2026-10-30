"""Direct Connect Connection — a physical or hosted AWS Direct Connect link at a DX location."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class DxConnection(BaseModel):
    """An AWS Direct Connect connection.

    The cross-connect at a Direct Connect location between AWS and the customer's (or a partner's)
    router. Virtual interfaces ride on it (``CARRIED_ON_CONNECTION``). The customer end is outside AWS
    and outside aws_core: ``TERMINATES_AT_CUSTOMER_DEVICE`` has an open target for whatever plugin
    models that device. Design vocabulary: no collector emits it yet. Fields are those
    ``directconnect:DescribeConnections`` reports (``DescribeHostedConnections`` for hosted ones).

    Spec: specs/spec-aws-core-v0.md (req-aws-core-direct-connect)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_dx_connection"
    ENTITY_NAME: ClassVar[str] = "Direct Connect Connection"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Direct Connect connection: a dedicated or hosted network link between AWS and a "
        "customer router at a Direct Connect location."
    )
    ENTITY_ICON: ClassVar[str] = "aws-direct-connect"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }

    # AWS's connection id (dxcon-…).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("connection_id",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "connection_id": {"type": "string", "pattern": "^(dxcon-[a-z0-9]{8,12})?$"},
        "location": {"type": "string"},
        "bandwidth": {"type": "string", "pattern": "^([0-9]+(Mbps|Gbps))?$"},
        "is_hosted": {"type": ["boolean", "null"]},
        "region": {"type": "string"},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    connection_id = models.CharField(max_length=32, blank=True, default="", db_index=True)
    # The Direct Connect location code (e.g. EqDC2), as AWS reports it.
    location = models.CharField(max_length=64, blank=True, default="")
    # AWS's bandwidth string (e.g. 1Gbps, 10Gbps, 500Mbps for a hosted connection).
    bandwidth = models.CharField(max_length=16, blank=True, default="")
    # True for a hosted connection provisioned by a Direct Connect partner; null when not observed.
    is_hosted = models.BooleanField(null=True, blank=True, default=None)
    region = models.CharField(max_length=32, blank=True, default="")
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: DescribeConnections tags.
    tags = models.JSONField(null=True, blank=True, default=None)
    # The collector's configuration envelope; {} when the manifest entry does not persist it.
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_dx_connection"

    def get_name(self) -> str:
        return self.name or self.connection_id

    def __str__(self) -> str:
        return self.get_name()
