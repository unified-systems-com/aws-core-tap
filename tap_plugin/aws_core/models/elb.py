"""ELB — an Elastic Load Balancer that is not an ALB: classic, network or gateway."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Elb(BaseModel):
    """An Elastic Load Balancer that is not an ALB.

    A Classic, Network or Gateway Load Balancer, told apart by ``lb_type``.
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_elb"
    ENTITY_NAME: ClassVar[str] = "Load Balancer"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An Elastic Load Balancer that is not an ALB: a Classic, Network or Gateway "
        "Load Balancer, told apart by lb_type."
    )
    ENTITY_ICON: ClassVar[str] = "aws-elb"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): the DNS name AWS assigns, which every load balancer
    # type has and which is unique. A Classic Load Balancer has no ARN, and a name is unique only
    # within an account and region, so neither can be the key for all three types.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("dns_name",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "dns_name": {"type": "string"},
        "scheme": {"type": "string"},
        "lb_type": {"type": "string", "enum": ["", "classic", "network", "gateway"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "dns_name": {"validation": "jsonschema", "schema": {"type": "string"}},
        "scheme": {"validation": "jsonschema", "schema": {"type": "string"}},
        "lb_type": {"validation": "jsonschema", "schema": {"type": "string", "enum": ["", "classic", "network", "gateway"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    dns_name = models.CharField(max_length=512, blank=True, default="")
    scheme = models.CharField(max_length=32, blank=True, default="")
    # Which load balancer this is: `classic` (the ELB v1 API), `network` (an NLB) or `gateway` (a GWLB).
    # ALBs are their own type (aws_alb). Blank means not observed.
    lb_type = models.CharField(max_length=16, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_elb"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
