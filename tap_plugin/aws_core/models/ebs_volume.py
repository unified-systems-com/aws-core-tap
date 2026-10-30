"""EBS Volume — an Amazon Elastic Block Store volume."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class EbsVolume(BaseModel):
    """An Amazon EBS block storage volume."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ebs_volume"
    ENTITY_NAME: ClassVar[str] = "EBS Volume"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon EBS block storage volume."
    ENTITY_ICON: ClassVar[str] = "aws-ebs"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The volume ID (vol-…). AWS assigns it, but does not
    # document it as unique across accounts and regions, so a clash there would surface as
    # AmbiguousIdentity from the generated search, never as a silent merge. The key moves to the ARN
    # if a collector records one.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("volume_id",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#D9E4BD", "border": "#7AA116", "label": "#222D06"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "volume_id": {"type": "string"},
        "volume_type": {"type": "string"},
        "size_gb": {"type": ["integer", "null"]},
        "state": {"type": "string"},
        "encrypted": {"type": "boolean"},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string"}},
        "volume_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "volume_type": {"validation": "jsonschema", "schema": {"type": "string"}},
        "size_gb": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "state": {"validation": "jsonschema", "schema": {"type": "string"}},
        "encrypted": {"validation": "jsonschema", "schema": {"type": "boolean"}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    # Nothing is required at create. A designed volume (dcom=design) exists before AWS mints its
    # volume_id; a collected one can be untagged, so it may have no name. Blank means not observed.
    CREATE_REQUIRED: ClassVar[list[str]] = []

    name = models.CharField(max_length=255, blank=True, default="")
    volume_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    volume_type = models.CharField(max_length=32, blank=True, default="")
    size_gb = models.IntegerField(blank=True, null=True)
    state = models.CharField(max_length=32, blank=True, default="")
    encrypted = models.BooleanField(default=False)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ebs_volume"

    def get_name(self) -> str:
        return self.name or self.volume_id

    def __str__(self) -> str:
        return self.get_name()
