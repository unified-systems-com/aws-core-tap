"""VPC Endpoint — a private connection from a VPC to an AWS service or a PrivateLink endpoint service."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel

# ec2 VpcEndpointType, as DescribeVpcEndpoints reports it.
ENDPOINT_TYPES = ["Interface", "Gateway", "GatewayLoadBalancer", "Resource", "ServiceNetwork"]


class VpcEndpoint(BaseModel):
    """A VPC endpoint (PrivateLink consumer side, for the interface type).

    Sits in a VPC (``RESIDES_IN_VPC``) and, for interface endpoints, in one subnet per AZ
    (``RESIDES_IN_SUBNET``). The endpoint service it connects to is ``CONSUMES_ENDPOINT_SERVICE`` when
    that service is a modelled PrivateLink service; an AWS service endpoint (com.amazonaws.<region>.s3)
    is recorded only in ``service_name``. Design vocabulary: no collector emits it yet. Fields are those
    ``ec2:DescribeVpcEndpoints`` reports.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-privatelink)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_vpc_endpoint"
    ENTITY_NAME: ClassVar[str] = "VPC Endpoint"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An Amazon VPC endpoint: a private connection from a VPC to an AWS service or to a PrivateLink "
        "endpoint service, without traversing the internet."
    )
    ENTITY_ICON: ClassVar[str] = "aws-privatelink"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }

    # AWS's endpoint id (vpce-…).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("vpc_endpoint_id",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "vpc_endpoint_id": {"type": "string", "pattern": "^(vpce-[0-9a-f]{8,17})?$"},
        "endpoint_type": {"type": "string", "enum": ["", *ENDPOINT_TYPES]},
        "service_name": {"type": "string"},
        "private_dns_enabled": {"type": ["boolean", "null"]},
        "region": {"type": "string"},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    vpc_endpoint_id = models.CharField(max_length=32, blank=True, default="", db_index=True)
    # Blank means not observed (the aws_elb.lb_type convention).
    endpoint_type = models.CharField(max_length=32, blank=True, default="")
    # The service it connects to, as AWS names it (an AWS service or a vpce-svc endpoint service).
    service_name = models.CharField(max_length=255, blank=True, default="")
    private_dns_enabled = models.BooleanField(null=True, blank=True, default=None)
    region = models.CharField(max_length=32, blank=True, default="")
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: DescribeVpcEndpoints Tags.
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_vpc_endpoint"

    def get_name(self) -> str:
        return self.name or self.vpc_endpoint_id

    def __str__(self) -> str:
        return self.get_name()
