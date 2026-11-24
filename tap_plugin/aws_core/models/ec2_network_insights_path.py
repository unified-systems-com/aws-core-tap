"""AWS EC2 Network Insights Path — an AWS EC2 Network Insights Path."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class Ec2NetworkInsightsPath(BaseModel):
    """An AWS EC2 Network Insights Path, listed by DescribeNetworkInsightsPaths: the source and destination a Reachability Analyzer analysis checks. Its source and destination are typed fields, as AWS returns them; the whole response is kept in configuration."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ec2_network_insights_path"
    ENTITY_NAME: ClassVar[str] = "AWS EC2 Network Insights Path"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS EC2 Network Insights Path."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The object's ARN (NetworkInsightsPathArn): unique across accounts and regions.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("network_insights_path_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "ec2:network-insights-path"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): when AWS created it (DescribeNetworkInsightsPaths
    # NetworkInsightsPaths[].CreatedDate, a botocore timestamp), read from configuration['CreatedDate'], where the
    # collector stores it as AWS sent it. AWS states no end for it.
    EVENT_TIME: ClassVar[Interval] = Interval(start="configuration", kind="created", member="CreatedDate")

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "network_insights_path_arn": {"type": "string"},
        # Null is unobserved (req-aws-core-fields-10). Each is AWS's own value, as sent (req-aws-core-fields-11).
        "source": {"type": ["string", "null"]},
        "source_arn": {"type": ["string", "null"]},
        "destination": {"type": ["string", "null"]},
        "destination_arn": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    network_insights_path_arn = models.CharField(max_length=2048, blank=True, default="")
    # Source and Destination as AWS returns them (documented on the path as the ID; CreateNetworkInsightsPath takes
    # an ID or an ARN); SourceArn and DestinationArn are the ARNs. Source is required on create; Destination is not,
    # so a path created with only a destination address or filter has none.
    source = models.CharField(max_length=2048, null=True, blank=True, default=None)
    source_arn = models.CharField(max_length=2048, null=True, blank=True, default=None)
    destination = models.CharField(max_length=2048, null=True, blank=True, default=None)
    destination_arn = models.CharField(max_length=2048, null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ec2_network_insights_path"

    def get_name(self) -> str:
        return self.name or self.network_insights_path_arn

    def __str__(self) -> str:
        return self.get_name()
