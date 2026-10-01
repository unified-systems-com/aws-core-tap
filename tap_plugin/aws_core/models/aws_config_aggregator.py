"""AWS Config configuration aggregator — collects Config data from many accounts and regions."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsConfigAggregator(BaseModel):
    """One AWS Config configuration aggregator.

    Read with ``config:DescribeConfigurationAggregators``, read to its last page. Whether it
    aggregates the whole organization or named accounts, and which regions, are typed fields.
    Contained by its footprint (``HOSTS_CONFIG_AGGREGATOR``).

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-security-services)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_config_aggregator"
    ENTITY_NAME: ClassVar[str] = "AWS Config Aggregator"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Config configuration aggregator: gathers Config data from an organization or from "
        "named accounts, across regions, into one account."
    )
    ENTITY_ICON: ClassVar[str] = "aws-config"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("aggregator_arn",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "aggregator_arn": {"type": "string"},
        "aggregator_name": {"type": "string"},
        # True when OrganizationAggregationSource is set.
        "organization_wide": {"type": "boolean"},
        "source_account_ids": {"type": "array", "items": {"type": "string"}},
        "all_aws_regions": {"type": ["boolean", "null"]},
        "aws_regions": {"type": "array", "items": {"type": "string"}},
        "role_arn": {"type": "string"},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    aggregator_arn = models.CharField(max_length=2048, blank=True, default="", db_index=True)
    aggregator_name = models.CharField(max_length=256, blank=True, default="")
    organization_wide = models.BooleanField(default=False)
    source_account_ids = models.JSONField(default=list, blank=True)
    all_aws_regions = models.BooleanField(null=True, blank=True, default=None)
    aws_regions = models.JSONField(default=list, blank=True)
    role_arn = models.CharField(max_length=2048, blank=True, default="")
    # AWS tags, canonical flat {str: str}. Source: config:ListTagsForResource (`Tags`, list_kv).
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_config_aggregator"

    def get_name(self) -> str:
        return self.name or self.aggregator_name or self.aggregator_arn

    def __str__(self) -> str:
        return self.get_name()
