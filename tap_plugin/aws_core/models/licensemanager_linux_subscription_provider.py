"""AWS License Manager Linux Subscription Provider — an AWS License Manager Linux Subscription Provider."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import NO_EVENT_TIME, NoEventTime
from tap_grid.models import BaseModel


class LicensemanagerLinuxSubscriptionProvider(BaseModel):
    """An AWS License Manager Linux Subscription Provider, listed by ListRegisteredSubscriptionProviders. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_licensemanager_linux_subscription_provider"
    ENTITY_NAME: ClassVar[str] = "AWS License Manager Linux Subscription Provider"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS License Manager Linux Subscription Provider."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (SubscriptionProviderArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("licensemanager_linux_subscription_provider_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "license-manager-linux-subscriptions:subscription-provider"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): no typed field of this model says when
    # the thing happened in the world; EVENT_TIME_REASON says why.
    EVENT_TIME: ClassVar[NoEventTime] = NO_EVENT_TIME
    EVENT_TIME_REASON: ClassVar[str] = (
        "AWS returns no creation time in its own record (ListRegisteredSubscriptionProviders "
        "RegisteredSubscriptionProviders[]); the times it does return there (LastSuccessfulDataRetrievalTime) are held "
        "only inside configuration."
    )

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "licensemanager_linux_subscription_provider_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    licensemanager_linux_subscription_provider_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_licensemanager_linux_subscription_provider"

    def get_name(self) -> str:
        return self.name or self.licensemanager_linux_subscription_provider_arn

    def __str__(self) -> str:
        return self.get_name()
