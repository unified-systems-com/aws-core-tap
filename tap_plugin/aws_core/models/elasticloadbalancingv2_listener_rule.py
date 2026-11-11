"""AWS ElasticLoadBalancingV2 Listener Rule — an AWS ElasticLoadBalancingV2 Listener Rule."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Elasticloadbalancingv2ListenerRule(BaseModel):
    """An Application Load Balancer listener rule, listed by DescribeLoadBalancers, DescribeListeners and DescribeRules, the listener's default rule among them: the hop between a listener and the target groups it forwards to (load balancer -> listener -> rule -> target group). It holds what decides the route: its priority, its conditions exactly as AWS returns them, and its actions. The whole response is stored, with an OIDC action's client secret removed."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_elasticloadbalancingv2_listener_rule"
    ENTITY_NAME: ClassVar[str] = "AWS ElasticLoadBalancingV2 Listener Rule"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS ElasticLoadBalancingV2 Listener Rule."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (RuleArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("elasticloadbalancingv2_listener_rule_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "elasticloadbalancingv2_listener_rule_arn": {"type": "string"},
        "listener_arn": {"type": ["string", "null"]},
        "load_balancer_arn": {"type": ["string", "null"]},
        "priority": {"type": ["string", "null"]},
        "is_default": {"type": ["boolean", "null"]},
        "conditions": {"type": ["array", "null"]},
        "action_types": {"type": ["array", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    elasticloadbalancingv2_listener_rule_arn = models.CharField(max_length=2048, blank=True, default="")
    # The listener whose rule this is. NULL = not observed.
    listener_arn = models.CharField(max_length=2048, null=True, blank=True, default=None)
    # The Application Load Balancer the listener is on. NULL = not observed.
    load_balancer_arn = models.CharField(max_length=2048, null=True, blank=True, default=None)
    # The priority as AWS returns it: a number as text, or 'default' for the default rule. NULL = not observed.
    priority = models.CharField(max_length=64, null=True, blank=True, default=None)
    # Whether this is the listener's default rule, which applies when no other rule matches. NULL = not observed.
    is_default = models.BooleanField(null=True, blank=True, default=None)
    # The conditions exactly as DescribeRules returns them (host header, path, HTTP header, method, query string,
    # source IP). NULL = not observed.
    conditions = models.JSONField(null=True, blank=True, default=None)
    # The types of the rule's actions (forward, redirect, fixed-response, authenticate-oidc, ...). NULL = not observed.
    action_types = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_elasticloadbalancingv2_listener_rule"

    def get_name(self) -> str:
        return self.name or self.elasticloadbalancingv2_listener_rule_arn

    def __str__(self) -> str:
        return self.get_name()
