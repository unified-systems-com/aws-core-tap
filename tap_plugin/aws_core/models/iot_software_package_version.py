"""AWS IoT Software Package Version — an AWS IoT Software Package Version."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class IotSoftwarePackageVersion(BaseModel):
    """An AWS IoT Software Package Version, read by ListPackageVersions. Only its identity, name and tags are collected; the rest of the response is not stored."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iot_software_package_version"
    ENTITY_NAME: ClassVar[str] = "AWS IoT Software Package Version"
    ENTITY_DESCRIPTION: ClassVar[str] = "An AWS IoT Software Package Version."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The package version's ARN, built as arn:{partition}:iot:{region}:{account}:package/{packageName}/version/{versionName} (the AWS Service Authorization Reference iot 'packageversion' resource); the listing carries no ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("iot_software_package_version_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "iot_software_package_version_arn": {"type": "string"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    iot_software_package_version_arn = models.CharField(max_length=2048, blank=True, default="")
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iot_software_package_version"

    def get_name(self) -> str:
        return self.name or self.iot_software_package_version_arn

    def __str__(self) -> str:
        return self.get_name()
