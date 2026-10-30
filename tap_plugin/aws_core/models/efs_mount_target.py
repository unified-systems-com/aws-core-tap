"""EFS Mount Target — an Amazon EFS mount target."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class EfsMountTarget(BaseModel):
    """An Amazon EFS mount target: the network endpoint of a file system in one subnet, with its own IP address and security groups."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_efs_mount_target"
    ENTITY_NAME: ClassVar[str] = "EFS Mount Target"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon EFS mount target."
    ENTITY_ICON: ClassVar[str] = "aws-ebs"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): AWS's mount target id (fsmt-...): unique within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("mount_target_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#D9E4BD", "border": "#7AA116", "label": "#222D06"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "mount_target_id": {"type": "string"},
        "file_system_id": {"type": ["string", "null"]},
        "subnet_id": {"type": ["string", "null"]},
        "vpc_id": {"type": ["string", "null"]},
        "ip_address": {"type": ["string", "null"]},
        "life_cycle_state": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "mount_target_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "file_system_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "subnet_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "vpc_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "ip_address": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "life_cycle_state": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    mount_target_id = models.CharField(max_length=512, blank=True, default="")
    # The file system the mount target belongs to. NULL = not observed.
    file_system_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The subnet the mount target is in. NULL = not observed.
    subnet_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The VPC the mount target is in. NULL = not observed.
    vpc_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The mount target's IPv4 address. NULL = not observed.
    ip_address = models.CharField(max_length=512, blank=True, null=True, default=None)
    # AWS's state. NULL = not observed.
    life_cycle_state = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_efs_mount_target"

    def get_name(self) -> str:
        return self.name or self.mount_target_id

    def __str__(self) -> str:
        return self.get_name()
