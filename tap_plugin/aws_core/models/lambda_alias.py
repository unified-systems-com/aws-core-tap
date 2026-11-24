"""AWS Lambda Alias — an AWS Lambda Alias."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import NO_EVENT_TIME, NoEventTime
from tap_grid.models import BaseModel


class LambdaAlias(BaseModel):
    """An AWS Lambda Alias, listed by ListAliases. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_lambda_alias"
    ENTITY_NAME: ClassVar[str] = "AWS Lambda Alias"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS Lambda Alias."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (AliasArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("lambda_alias_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "lambda:function alias"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): no typed field of this model says when
    # the thing happened in the world; EVENT_TIME_REASON says why.
    EVENT_TIME: ClassVar[NoEventTime] = NO_EVENT_TIME
    EVENT_TIME_REASON: ClassVar[str] = "AWS returns no time in its own record (ListAliases Aliases[])."

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "lambda_alias_arn": {"type": "string"},
        "resource_policy_account_ids": {"type": ["array", "null"], "items": {"type": "string", "pattern": "^[0-9]{12}$"}},
        "resource_policy_services": {"type": ["array", "null"], "items": {"type": "string", "minLength": 1}},
        "resource_policy_wildcard_principal": {"type": ["boolean", "null"]},
        "resource_policy_unconditioned": {"type": ["boolean", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    lambda_alias_arn = models.CharField(max_length=2048, blank=True, default="")
    # The alias's own resource-based policy (lambda:GetPolicy, Qualifier), summarised over its Allow
    # statements; the document itself is stored in configuration['_hydrate']['policy'] (aws-core-tap#290). NULL on every
    # field = the policy was not read (denied, errored, unreadable); [] or false = read, and no such grant (a policy that
    # does not exist, ResourceNotFoundException recorded absent, reads [] and false on every field). resource_policy_account_ids are the OTHER accounts
    # (never this one) its principals name: the source of PERMITS_ACCOUNT. resource_policy_services are service
    # principals. resource_policy_wildcard_principal: an Allow names Principal "*", conditioned or not.
    # resource_policy_unconditioned: an Allow grants another account, a service or "*" with no Condition at all.
    resource_policy_account_ids = models.JSONField(null=True, blank=True, default=None)
    resource_policy_services = models.JSONField(null=True, blank=True, default=None)
    resource_policy_wildcard_principal = models.BooleanField(null=True, blank=True, default=None)
    resource_policy_unconditioned = models.BooleanField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_lambda_alias"

    def get_name(self) -> str:
        return self.name or self.lambda_alias_arn

    def __str__(self) -> str:
        return self.get_name()
