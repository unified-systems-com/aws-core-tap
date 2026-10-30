"""API Gateway Usage Plan — an Amazon API Gateway usage plan."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ApigatewayUsagePlan(BaseModel):
    """An API Gateway usage plan: throttling and quota limits applied to API keys for chosen stages."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_apigateway_usage_plan"
    ENTITY_NAME: ClassVar[str] = "API Gateway Usage Plan"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon API Gateway usage plan."
    ENTITY_ICON: ClassVar[str] = "aws-apigateway"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The plan's ARN (built from the plan id).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("usage_plan_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EFC1F2", "border": "#C925D1", "label": "#380A3A"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "usage_plan_arn": {"type": "string"},
        "quota_limit": {"type": ["integer", "null"]},
        "quota_period": {"type": ["string", "null"]},
        "throttle_rate_limit": {"type": ["number", "null"]},
        "throttle_burst_limit": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    usage_plan_arn = models.CharField(max_length=2048, blank=True, default="")
    # Requests allowed per quota period. NULL = no quota, or not observed.
    quota_limit = models.IntegerField(null=True, blank=True, default=None)
    # DAY, WEEK or MONTH. NULL = no quota, or not observed.
    quota_period = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # Steady-state requests per second. NULL = not set, or not observed.
    throttle_rate_limit = models.FloatField(null=True, blank=True, default=None)
    # Burst size. NULL = not set, or not observed.
    throttle_burst_limit = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_apigateway_usage_plan"

    def get_name(self) -> str:
        return self.name or self.usage_plan_arn

    def __str__(self) -> str:
        return self.get_name()
