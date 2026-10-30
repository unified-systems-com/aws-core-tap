"""RDS Event Subscription — an Amazon RDS event subscription."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class RdsEventSubscription(BaseModel):
    """An RDS event subscription: it sends database events (failover, maintenance, security group changes) to an SNS topic."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_rds_event_subscription"
    ENTITY_NAME: ClassVar[str] = "RDS Event Subscription"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon RDS event subscription."
    ENTITY_ICON: ClassVar[str] = "aws-rds"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The subscription's ARN: a name is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("event_subscription_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "event_subscription_arn": {"type": "string"},
        "sns_topic_arn": {"type": ["string", "null"]},
        "source_type": {"type": ["string", "null"]},
        "enabled": {"type": ["boolean", "null"]},
        "status": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    event_subscription_arn = models.CharField(max_length=2048, blank=True, default="")
    # The SNS topic events are sent to. NULL = not observed.
    sns_topic_arn = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # db-instance, db-cluster, db-snapshot, ... NULL = all source types, or not observed.
    source_type = models.CharField(max_length=2048, blank=True, null=True, default=None)
    # Whether the subscription is enabled. NULL = not observed.
    enabled = models.BooleanField(null=True, blank=True, default=None)
    # AWS's status. NULL = not observed.
    status = models.CharField(max_length=2048, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_rds_event_subscription"

    def get_name(self) -> str:
        return self.name or self.event_subscription_arn

    def __str__(self) -> str:
        return self.get_name()
