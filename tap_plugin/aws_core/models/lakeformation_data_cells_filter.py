"""AWS LakeFormation Data Cells Filter — an AWS LakeFormation Data Cells Filter."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class LakeformationDataCellsFilter(BaseModel):
    """An AWS LakeFormation Data Cells Filter, listed by ListDataCellsFilter. Only its identity, name and tags are collected; the rest of the response has not been reviewed for sensitive values, so none of it is stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_lakeformation_data_cells_filter"
    ENTITY_NAME: ClassVar[str] = "AWS LakeFormation Data Cells Filter"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS LakeFormation Data Cells Filter."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): Table catalog id, database, table and filter name joined with slashes: the CloudFormation primary identifier of the type is that quadruple, and the item carries no ARN. Unique within the account and region. The key leads with <partition>:<account>:<region>: (req-aws-collector-identity-8), because these names repeat in other regions and accounts (issue 224).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("lakeformation_data_cells_filter_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "lakeformation_data_cells_filter_key": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    lakeformation_data_cells_filter_key = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_lakeformation_data_cells_filter"

    def get_name(self) -> str:
        return self.name or self.lakeformation_data_cells_filter_key

    def __str__(self) -> str:
        return self.get_name()
