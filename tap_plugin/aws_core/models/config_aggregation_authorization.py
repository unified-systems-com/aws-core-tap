"""AWS Config Aggregation Authorization — an authorization for another account to aggregate this account's AWS Config data."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class ConfigAggregationAuthorization(BaseModel):
    """An AWS Config aggregation authorization: it lets another account (and region) collect this account's Config configuration and compliance data, so it is a statement of who may read it."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_config_aggregation_authorization"
    ENTITY_NAME: ClassVar[str] = "AWS Config Aggregation Authorization"
    ENTITY_DESCRIPTION: ClassVar[str] = "An authorization for another account to aggregate this account's AWS Config data."
    ENTITY_ICON: ClassVar[str] = "aws-config"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The authorization's ARN: it is unique per authorized account and region within this account.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("authorization_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "authorization_arn": {"type": "string"},
        "authorized_account_id": {"type": ["string", "null"]},
        "authorized_region": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "authorization_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "authorized_account_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "authorized_region": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    authorization_arn = models.CharField(max_length=512, blank=True, default="")
    # The account allowed to aggregate this account's data. NULL = not observed.
    authorized_account_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The region the authorized aggregator lives in. NULL = not observed.
    authorized_region = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_config_aggregation_authorization"

    def get_name(self) -> str:
        return self.name or self.authorization_arn

    def __str__(self) -> str:
        return self.get_name()
