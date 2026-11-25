"""IAM Root User — the AWS account's root user, as the account's credential report describes it."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class IamRootUser(BaseModel):
    """The AWS account's root user: its password, MFA, access key and certificate use (ruling Q143b, 2026-11-23).

    The credential report (``GetCredentialReport``) is the only source of these facts: no other IAM call describes
    the root user. Every value is the report's, as of ``report_generated_at``. Metadata only: the report holds no
    password, key or secret, and none is a field."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_root_user"
    ENTITY_NAME: ClassVar[str] = "IAM Root User"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "The AWS account's root user, as the credential report describes it: password, MFA, key and certificate use."
    )
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    # The type's dimensions, declared in this one place (aws_core's normal default; see IamAccessKey).
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): the root user's ARN, read from the report's arn column, never built
    # (req-aws-collector-identity-12). The Service Authorization Reference names no resource type for it.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("root_arn",)
    ARN_RESOURCE: ClassVar[str | None] = None
    # Event time (req-grid-entity-event-time, req-aws-core-models-5).
    # The report's user_creation_time, when the root user (and with it the account) was created. AWS states no end.
    EVENT_TIME: ClassVar[Interval] = Interval(start="created_at", kind="created")

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "root_arn": {"type": "string"},
        "report_generated_at": {"type": ["string", "null"]},
        "created_at": {"type": ["string", "null"]},
        "password_enabled": {"type": ["boolean", "null"]},
        "password_last_used": {"type": ["string", "null"]},
        "mfa_active": {"type": ["boolean", "null"]},
        "access_key_1_active": {"type": ["boolean", "null"]},
        "access_key_1_last_rotated": {"type": ["string", "null"]},
        "access_key_1_last_used_date": {"type": ["string", "null"]},
        "access_key_1_last_used_region": {"type": ["string", "null"]},
        "access_key_1_last_used_service": {"type": ["string", "null"]},
        "access_key_2_active": {"type": ["boolean", "null"]},
        "access_key_2_last_rotated": {"type": ["string", "null"]},
        "access_key_2_last_used_date": {"type": ["string", "null"]},
        "access_key_2_last_used_region": {"type": ["string", "null"]},
        "access_key_2_last_used_service": {"type": ["string", "null"]},
        "cert_1_active": {"type": ["boolean", "null"]},
        "cert_1_last_rotated": {"type": ["string", "null"]},
        "cert_2_active": {"type": ["boolean", "null"]},
        "cert_2_last_rotated": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "root_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "report_generated_at": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "created_at": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "password_enabled": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "password_last_used": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "mfa_active": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "access_key_1_active": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "access_key_1_last_rotated": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "access_key_1_last_used_date": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "access_key_1_last_used_region": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "access_key_1_last_used_service": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "access_key_2_active": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "access_key_2_last_rotated": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "access_key_2_last_used_date": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "access_key_2_last_used_region": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "access_key_2_last_used_service": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "cert_1_active": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "cert_1_last_rotated": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "cert_2_active": {"validation": "jsonschema", "schema": {"type": ["boolean", "null"]}},
        "cert_2_last_rotated": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    # The root user's ARN as the report's arn column states it (arn:<partition>:iam::<account>:root).
    root_arn = models.CharField(max_length=512, blank=True, default="")
    # When AWS built the report these facts come from (GetCredentialReport GeneratedTime): their as-of time.
    report_generated_at = models.CharField(max_length=64, null=True, blank=True, default=None)
    # The report's user_creation_time for the root user, as the report states it; NULL = not observed.
    created_at = models.CharField(max_length=64, null=True, blank=True, default=None)
    # The report's true/false; NULL when it says not_supported (the root row usually does) or was not read.
    password_enabled = models.BooleanField(null=True, blank=True, default=None)
    # Report times as the report states them; "" when it says N/A, no_information or not_supported (configuration
    # keeps which); NULL = not observed.
    password_last_used = models.CharField(max_length=64, null=True, blank=True, default=None)
    mfa_active = models.BooleanField(null=True, blank=True, default=None)
    # The root user's access key 1, as the report describes it (root keys have no listing of their own).
    access_key_1_active = models.BooleanField(null=True, blank=True, default=None)
    access_key_1_last_rotated = models.CharField(max_length=64, null=True, blank=True, default=None)
    access_key_1_last_used_date = models.CharField(max_length=64, null=True, blank=True, default=None)
    access_key_1_last_used_region = models.CharField(max_length=64, null=True, blank=True, default=None)
    access_key_1_last_used_service = models.CharField(max_length=128, null=True, blank=True, default=None)
    access_key_2_active = models.BooleanField(null=True, blank=True, default=None)
    access_key_2_last_rotated = models.CharField(max_length=64, null=True, blank=True, default=None)
    access_key_2_last_used_date = models.CharField(max_length=64, null=True, blank=True, default=None)
    access_key_2_last_used_region = models.CharField(max_length=64, null=True, blank=True, default=None)
    access_key_2_last_used_service = models.CharField(max_length=128, null=True, blank=True, default=None)
    # The root user's signing certificate 1, as the report describes it.
    cert_1_active = models.BooleanField(null=True, blank=True, default=None)
    cert_1_last_rotated = models.CharField(max_length=64, null=True, blank=True, default=None)
    cert_2_active = models.BooleanField(null=True, blank=True, default=None)
    cert_2_last_rotated = models.CharField(max_length=64, null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    # The root user has no tags: always {} once collected.
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iam_root_user"

    def get_name(self) -> str:
        return self.name or self.root_arn

    def __str__(self) -> str:
        return self.get_name()
