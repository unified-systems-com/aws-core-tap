"""IAM Virtual MFA Device — a virtual multi-factor authentication device registered in AWS IAM."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class IamVirtualMfaDevice(BaseModel):
    """An AWS IAM virtual MFA device.

    The seed and QR code that enrol a device are credentials: they are never fields here."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_virtual_mfa_device"
    ENTITY_NAME: ClassVar[str] = "IAM Virtual MFA Device"
    ENTITY_DESCRIPTION: ClassVar[str] = "A virtual multi-factor authentication device registered in AWS IAM."
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The device's serial number, an ARN that embeds the user name for a virtual device.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("serial_number",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "serial_number": {"type": "string"},
        "user_arn": {"type": ["string", "null"]},
        "enable_date": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "serial_number": {"validation": "jsonschema", "schema": {"type": "string"}},
        "user_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "enable_date": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": "object"}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    serial_number = models.CharField(max_length=512, blank=True, default="")
    # ARN of the user the device is enabled for. NULL = not observed; "" = observed, not assigned.
    user_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # ISO 8601 UTC time the device was enabled; NULL = not observed.
    enable_date = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iam_virtual_mfa_device"

    def get_name(self) -> str:
        return self.name or self.serial_number

    def __str__(self) -> str:
        return self.get_name()
