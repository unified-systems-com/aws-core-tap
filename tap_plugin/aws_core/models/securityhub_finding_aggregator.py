"""Security Hub Finding Aggregator — a Security Hub cross-region finding aggregator."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class SecurityhubFindingAggregator(BaseModel):
    """A Security Hub finding aggregator: it copies findings from linked regions into one aggregation region. Its linking mode decides which regions are in view."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_securityhub_finding_aggregator"
    ENTITY_NAME: ClassVar[str] = "Security Hub Finding Aggregator"
    ENTITY_DESCRIPTION: ClassVar[str] = "A Security Hub cross-region finding aggregator."
    ENTITY_ICON: ClassVar[str] = "aws-security-hub"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The aggregator's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("aggregator_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "aggregator_arn": {"type": "string"},
        "region_linking_mode": {"type": ["string", "null"]},
        "regions": {"type": ["array", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "aggregator_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "region_linking_mode": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "regions": {"validation": "jsonschema", "schema": {"type": ["array", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    aggregator_arn = models.CharField(max_length=512, blank=True, default="")
    # ALL_REGIONS, ALL_REGIONS_EXCEPT_SPECIFIED, SPECIFIED_REGIONS or NO_REGIONS. NULL = not observed.
    region_linking_mode = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The regions named by the linking mode. NULL = not observed.
    regions = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_securityhub_finding_aggregator"

    def get_name(self) -> str:
        return self.name or self.aggregator_arn

    def __str__(self) -> str:
        return self.get_name()
