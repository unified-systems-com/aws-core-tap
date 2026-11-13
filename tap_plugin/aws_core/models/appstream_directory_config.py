"""AWS AppStream Directory Config — an AWS AppStream Directory Config."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AppstreamDirectoryConfig(BaseModel):
    """An AWS AppStream Directory Config, read by DescribeDirectoryConfigs. Only its identity, name and tags are collected; the rest of the response is not stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_appstream_directory_config"
    ENTITY_NAME: ClassVar[str] = "AWS AppStream Directory Config"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS AppStream Directory Config."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The account, the region and the directory name (DirectoryName, the CloudFormation primary identifier): AWS gives it no ARN, and a bare name repeats across accounts and regions, so the key is the account, the region and the name. The key leads with <partition>:<account>:<region>: (req-aws-collector-identity-8), because these names repeat in other regions and accounts (issue 224).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("appstream_directory_config_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "appstream_directory_config_key": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    appstream_directory_config_key = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_appstream_directory_config"

    def get_name(self) -> str:
        return self.name or self.appstream_directory_config_key

    def __str__(self) -> str:
        return self.get_name()
