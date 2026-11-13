"""AWS Config configuration recorder — what records resource configuration in one account and region."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsConfigRecorder(BaseModel):
    """One AWS Config configuration recorder, customer-managed or service-linked.

    Enumerated with ``config:ListConfigurationRecorders`` (paginated, unfiltered), which lists both
    kinds; ``DescribeConfigurationRecorders`` with no name returns the customer-managed recorder only
    (``req-aws-core-contained-type-triple-6``). Each recorder is then described and its status read
    by ARN. Contained by its footprint (``HOSTS_CONFIG_RECORDER``).

    ``recording`` is null when the status read failed: a denied read is unknown, never "off".

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-security-services)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_config_recorder"
    ENTITY_NAME: ClassVar[str] = "AWS Config Recorder"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Config configuration recorder: whether resource configuration changes are being "
        "recorded in one account and region, and by whom."
    )
    ENTITY_ICON: ClassVar[str] = "aws-config"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("recorder_arn",)
    ARN_RESOURCE: ClassVar[str | None] = "config:ConfigurationRecorder"

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "recorder_arn": {"type": "string"},
        "recorder_name": {"type": ["string", "null"]},
        # ConfigurationRecorderStatus.recording; null when the status read failed.
        "recording": {"type": ["boolean", "null"]},
        "last_status": {"type": ["string", "null"]},
        # The owning service's principal for a service-linked recorder; "" for a customer-managed one.
        "service_principal": {"type": ["string", "null"]},
        # INTERNAL or PAID (recordingScope), verbatim.
        "recording_scope": {"type": ["string", "null"]},
        "role_arn": {"type": ["string", "null"]},
        "all_supported": {"type": ["boolean", "null"]},
        "include_global_resource_types": {"type": ["boolean", "null"]},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    recorder_arn = models.CharField(max_length=2048, blank=True, default="", db_index=True)
    recorder_name = models.CharField(max_length=256, null=True, blank=True, default=None)
    recording = models.BooleanField(null=True, blank=True, default=None)
    last_status = models.CharField(max_length=32, null=True, blank=True, default=None)
    service_principal = models.CharField(max_length=128, null=True, blank=True, default=None)
    recording_scope = models.CharField(max_length=32, null=True, blank=True, default=None)
    role_arn = models.CharField(max_length=2048, null=True, blank=True, default=None)
    all_supported = models.BooleanField(null=True, blank=True, default=None)
    include_global_resource_types = models.BooleanField(null=True, blank=True, default=None)
    # AWS tags, canonical flat {str: str}. Source: config:ListTagsForResource (`Tags`, list_kv).
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_config_recorder"

    def get_name(self) -> str:
        return self.name or self.recorder_name or self.recorder_arn

    def __str__(self) -> str:
        return self.get_name()
