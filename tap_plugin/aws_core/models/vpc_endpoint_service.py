"""VPC Endpoint Service — the provider side of AWS PrivateLink."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class VpcEndpointService(BaseModel):
    """A VPC endpoint service (PrivateLink provider side).

    Consumers reach it through interface VPC endpoints (``CONSUMES_ENDPOINT_SERVICE``); it forwards
    that traffic to the Network or Gateway Load Balancer behind it (``ROUTES_TRAFFIC``). Design
    vocabulary: no collector emits it yet. Fields are those ``ec2:DescribeVpcEndpointServiceConfigurations``
    reports.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-privatelink)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_vpc_endpoint_service"
    ENTITY_NAME: ClassVar[str] = "VPC Endpoint Service"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS PrivateLink endpoint service: a service a provider exposes from behind a load balancer, "
        "reachable privately from other VPCs and accounts through interface endpoints."
    )
    ENTITY_ICON: ClassVar[str] = "aws-privatelink"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }

    # AWS's service id (vpce-svc-…).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("service_id",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "service_id": {"type": "string", "pattern": "^(vpce-svc-[0-9a-f]{8,17})?$"},
        "service_name": {"type": "string"},
        "acceptance_required": {"type": ["boolean", "null"]},
        "private_dns_name": {"type": "string"},
        "region": {"type": "string"},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    service_id = models.CharField(max_length=32, blank=True, default="", db_index=True)
    # The name consumers connect to (com.amazonaws.vpce.<region>.vpce-svc-…).
    service_name = models.CharField(max_length=255, blank=True, default="")
    # AcceptanceRequired: whether the provider must accept each endpoint connection. Null when not observed.
    acceptance_required = models.BooleanField(null=True, blank=True, default=None)
    private_dns_name = models.CharField(max_length=255, blank=True, default="")
    region = models.CharField(max_length=32, blank=True, default="")
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: the configuration's Tags.
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_vpc_endpoint_service"

    def get_name(self) -> str:
        return self.name or self.service_id

    def __str__(self) -> str:
        return self.get_name()
