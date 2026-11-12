"""AWS EC2 VPC Endpoint Connection Notification — an AWS EC2 VPC Endpoint Connection Notification."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Ec2VpcEndpointConnectionNotification(BaseModel):
    """An AWS EC2 VPC Endpoint Connection Notification, listed by DescribeVpcEndpointConnectionNotifications. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ec2_vpc_endpoint_connection_notification"
    ENTITY_NAME: ClassVar[str] = "AWS EC2 VPC Endpoint Connection Notification"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS EC2 VPC Endpoint Connection Notification."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's own id (ConnectionNotificationId), assigned by AWS and unique within its type.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("ec2_vpc_endpoint_connection_notification_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "ec2_vpc_endpoint_connection_notification_id": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    ec2_vpc_endpoint_connection_notification_id = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ec2_vpc_endpoint_connection_notification"

    def get_name(self) -> str:
        return self.name or self.ec2_vpc_endpoint_connection_notification_id

    def __str__(self) -> str:
        return self.get_name()
