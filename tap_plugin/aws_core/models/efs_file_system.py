"""EFS File System — an Amazon EFS file system."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class EfsFileSystem(BaseModel):
    """An Amazon EFS file system: shared NFS storage. Encryption at rest and the file system policy decide who can read it."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_efs_file_system"
    ENTITY_NAME: ClassVar[str] = "EFS File System"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon EFS file system."
    ENTITY_ICON: ClassVar[str] = "aws-ebs"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The file system's ARN: a file system id is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("file_system_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#D9E4BD", "border": "#7AA116", "label": "#222D06"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "file_system_arn": {"type": "string"},
        "file_system_id": {"type": ["string", "null"]},
        "encrypted": {"type": ["boolean", "null"]},
        "kms_key_id": {"type": ["string", "null"]},
        "performance_mode": {"type": ["string", "null"]},
        "throughput_mode": {"type": ["string", "null"]},
        "life_cycle_state": {"type": ["string", "null"]},
        "number_of_mount_targets": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "file_system_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "file_system_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "encrypted": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "kms_key_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "performance_mode": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "throughput_mode": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "life_cycle_state": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "number_of_mount_targets": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    file_system_arn = models.CharField(max_length=512, blank=True, default="")
    # AWS's id (fs-...). NULL = not observed.
    file_system_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # Whether the file system is encrypted at rest. NULL = not observed.
    encrypted = models.BooleanField(null=True, blank=True, default=None)
    # The key that encrypts the file system. NULL = none, or not observed.
    kms_key_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # generalPurpose or maxIO. NULL = not observed.
    performance_mode = models.CharField(max_length=512, blank=True, null=True, default=None)
    # bursting, provisioned or elastic. NULL = not observed.
    throughput_mode = models.CharField(max_length=512, blank=True, null=True, default=None)
    # AWS's state (available, creating, deleting, ...). NULL = not observed.
    life_cycle_state = models.CharField(max_length=512, blank=True, null=True, default=None)
    # How many mount targets the file system has. NULL = not observed.
    number_of_mount_targets = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_efs_file_system"

    def get_name(self) -> str:
        return self.name or self.file_system_arn

    def __str__(self) -> str:
        return self.get_name()
