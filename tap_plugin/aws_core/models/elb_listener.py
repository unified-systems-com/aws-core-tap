"""ELB Listener — an Elastic Load Balancing (v2) listener."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ElbListener(BaseModel):
    """An Elastic Load Balancing listener: the port and protocol a load balancer accepts connections on, with the TLS policy and certificates it presents and the action it takes. The TLS policy decides which protocol versions and ciphers clients may use."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_elb_listener"
    ENTITY_NAME: ClassVar[str] = "ELB Listener"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Elastic Load Balancing (v2) listener."
    ENTITY_ICON: ClassVar[str] = "aws-elb"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The listener's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("listener_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "listener_arn": {"type": "string"},
        "load_balancer_arn": {"type": ["string", "null"]},
        "port": {"type": ["integer", "null"]},
        "protocol": {"type": ["string", "null"]},
        "ssl_policy": {"type": ["string", "null"]},
        "certificate_arns": {"type": ["array", "null"]},
        "action_types": {"type": ["array", "null"]},
        "mutual_authentication_mode": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "listener_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "load_balancer_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "port": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "protocol": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "ssl_policy": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "certificate_arns": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "action_types": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "mutual_authentication_mode": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    listener_arn = models.CharField(max_length=512, blank=True, default="")
    # The load balancer the listener is on. NULL = not observed.
    load_balancer_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The port. NULL = not observed.
    port = models.IntegerField(null=True, blank=True, default=None)
    # HTTP, HTTPS, TCP, TLS, UDP, ... NULL = not observed.
    protocol = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The TLS security policy (HTTPS and TLS listeners). NULL = none, or not observed.
    ssl_policy = models.CharField(max_length=512, blank=True, null=True, default=None)
    # ARNs of the certificates the listener presents. NULL = not observed.
    certificate_arns = models.JSONField(null=True, blank=True, default=None)
    # The types of the default actions (forward, redirect, authenticate-oidc, ...). NULL = not observed.
    action_types = models.JSONField(null=True, blank=True, default=None)
    # off, passthrough or verify. NULL = none, or not observed.
    mutual_authentication_mode = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_elb_listener"

    def get_name(self) -> str:
        return self.name or self.listener_arn

    def __str__(self) -> str:
        return self.get_name()
