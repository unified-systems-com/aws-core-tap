"""EFS Access Point — an Amazon EFS access point."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class EfsAccessPoint(BaseModel):
    """An Amazon EFS access point: an application entry into a file system that fixes the POSIX identity and root directory its clients use."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_efs_access_point"
    ENTITY_NAME: ClassVar[str] = "EFS Access Point"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon EFS access point."
    ENTITY_ICON: ClassVar[str] = "aws-ebs"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The access point's ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("access_point_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#D9E4BD", "border": "#7AA116", "label": "#222D06"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "access_point_arn": {"type": "string"},
        "file_system_id": {"type": ["string", "null"]},
        "posix_uid": {"type": ["integer", "null"]},
        "root_directory_path": {"type": ["string", "null"]},
        "life_cycle_state": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "access_point_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "file_system_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "posix_uid": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "root_directory_path": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "life_cycle_state": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    access_point_arn = models.CharField(max_length=512, blank=True, default="")
    # The file system the access point is on. NULL = not observed.
    file_system_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The POSIX user id forced on clients. NULL = none enforced, or not observed.
    posix_uid = models.IntegerField(null=True, blank=True, default=None)
    # The directory clients see as the root. NULL = not observed.
    root_directory_path = models.CharField(max_length=512, blank=True, null=True, default=None)
    # AWS's state. NULL = not observed.
    life_cycle_state = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_efs_access_point"

    def get_name(self) -> str:
        return self.name or self.access_point_arn

    def __str__(self) -> str:
        return self.get_name()
