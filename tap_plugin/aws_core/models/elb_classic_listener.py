"""ELB Classic Listener — a Classic load balancer listener."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ElbClassicListener(BaseModel):
    """A Classic load balancer listener, one entry of the Classic DescribeLoadBalancers answer's ListenerDescriptions: the protocol and port the load balancer accepts connections on, the instance protocol and port it forwards to, its policies, and the certificate it presents (by ARN, never its body or key). Mapped as a node, as an ELBv2 listener is (aws-core-tap#220)."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_elb_classic_listener"
    ENTITY_NAME: ClassVar[str] = "ELB Classic Listener"
    ENTITY_DESCRIPTION: ClassVar[str] = "A Classic load balancer listener."
    ENTITY_ICON: ClassVar[str] = "aws-elb"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): a Classic listener has no ARN or id, so the key is
    # <partition>:<account>:<region>:<load balancer name>:<protocol>:<load balancer port>. The load balancer's name is
    # unique within its account and region, and the listener by its protocol and port (aws-core-tap#224's convention).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("listener_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "listener_key": {"type": "string"},
        "load_balancer_name": {"type": ["string", "null"]},
        "protocol": {"type": ["string", "null"]},
        "port": {"type": ["integer", "null"]},
        "instance_protocol": {"type": ["string", "null"]},
        "instance_port": {"type": ["integer", "null"]},
        "certificate_id": {"type": ["string", "null"]},
        "policy_names": {"type": ["array", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    listener_key = models.CharField(max_length=2048, blank=True, default="")
    # The Classic load balancer the listener is on. NULL = not observed.
    load_balancer_name = models.CharField(max_length=255, null=True, blank=True, default=None)
    # HTTP, HTTPS, TCP or SSL. NULL = not observed.
    protocol = models.CharField(max_length=64, null=True, blank=True, default=None)
    # The port the load balancer accepts connections on. NULL = not observed.
    port = models.IntegerField(null=True, blank=True, default=None)
    # The protocol the load balancer speaks to the instances. NULL = not observed.
    instance_protocol = models.CharField(max_length=64, null=True, blank=True, default=None)
    # The instance port the listener forwards to. NULL = not observed.
    instance_port = models.IntegerField(null=True, blank=True, default=None)
    # The ARN of the server certificate (IAM or ACM) an HTTPS or SSL listener presents. NULL = none, or not observed.
    certificate_id = models.CharField(max_length=2048, null=True, blank=True, default=None)
    # The policies enabled on the listener (SSL negotiation, stickiness). NULL = not observed.
    policy_names = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_elb_classic_listener"

    def get_name(self) -> str:
        return self.name or self.listener_key

    def __str__(self) -> str:
        return self.get_name()
