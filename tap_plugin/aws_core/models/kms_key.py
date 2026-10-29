"""KMS Key — an AWS Key Management Service key."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class KmsKey(BaseModel):
    """An AWS KMS key."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_kms_key"
    ENTITY_NAME: ClassVar[str] = "KMS Key"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Key Management Service key — the encryption-at-rest anchor that "
        "buckets, log groups, queues, trails, and secrets resolve to via "
        "ENCRYPTED_WITH_KEY edges."
    )
    ENTITY_ICON: ClassVar[str] = "aws-kms"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The key's ARN, the boto3 collector's identity for it;
    # the key ID alone is unique only within an account and region.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("key_arn",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "key_arn": {"type": "string"},
        "key_id": {"type": "string"},
        "key_state": {"type": "string"},
        "key_manager": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": ["object", "null"]},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "key_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "key_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "key_state": {"validation": "jsonschema", "schema": {"type": "string"}},
        "key_manager": {"validation": "jsonschema", "schema": {"type": "string"}},
        "description": {"validation": "jsonschema", "schema": {"type": "string"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    key_arn = models.CharField(max_length=512, blank=True, default="")
    key_id = models.CharField(max_length=128, blank=True, default="")
    key_state = models.CharField(max_length=64, blank=True, default="")
    key_manager = models.CharField(max_length=32, blank=True, default="")
    description = models.TextField(blank=True, default="")
    tags = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_kms_key"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
