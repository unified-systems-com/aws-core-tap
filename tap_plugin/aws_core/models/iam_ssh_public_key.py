"""IAM SSH Public Key — an SSH public key an AWS IAM user has uploaded."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class IamSshPublicKey(BaseModel):
    """An SSH public key an IAM user has uploaded, for AWS CodeCommit: its id, status, upload time and fingerprint.

    The fingerprint comes from ``GetSSHPublicKey`` (``Encoding="SSH"``); the key body that call returns beside it is
    removed before storage and is never a field (ruling Q150a, 2026-11-24)."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_ssh_public_key"
    ENTITY_NAME: ClassVar[str] = "IAM SSH Public Key"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An SSH public key an IAM user has uploaded (for CodeCommit): id, status, upload time and fingerprint, "
        "never the key body."
    )
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    # The type's dimensions, declared in this one place: aws_core's cloud default and computing_core's standard
    # credential dimension, its value the kind of credential (ruling Q146, 2026-11-23).
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws", "tap.computing.credential": "ssh_key"}
    # Identity (req-grid-entity-natural-key, req-aws-collector-identity-13).
    # AWS gives an SSH public key no ARN and CloudFormation no type; it is keyed by the id AWS
    # generates, scoped by partition and account (ruling Q142a).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("partition", "account_id", "ssh_public_key_id")
    # Event time (req-grid-entity-event-time, req-aws-core-models-5).
    # UploadDate (ListSSHPublicKeys), when the key was uploaded to IAM, which is
    # when it came to exist there. AWS states no end.
    EVENT_TIME: ClassVar[Interval] = Interval(start="upload_date", kind="created")

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "partition": {"type": "string"},
        "account_id": {"type": "string"},
        "ssh_public_key_id": {"type": "string"},
        "user_name": {"type": ["string", "null"]},
        "user_arn": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "upload_date": {"type": ["string", "null"]},
        "fingerprint": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "partition": {"validation": "jsonschema", "schema": {"type": "string"}},
        "account_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "ssh_public_key_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "user_name": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "user_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "upload_date": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "fingerprint": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    # Key columns: the partition and account the credential lives in, and AWS's own id for it.
    partition = models.CharField(max_length=32, blank=True, default="")
    account_id = models.CharField(max_length=12, blank=True, default="")
    # The SSH public key id (APKA...) AWS generates.
    ssh_public_key_id = models.CharField(max_length=128, blank=True, default="")
    # The user that holds it, as the listing names it; NULL = not observed.
    user_name = models.CharField(max_length=128, null=True, blank=True, default=None)
    user_arn = models.CharField(max_length=512, null=True, blank=True, default=None)
    # Active, Inactive or Expired, as AWS reports it; NULL = not observed.
    status = models.CharField(max_length=32, null=True, blank=True, default=None)
    # ISO 8601 UTC time the key was uploaded, as AWS states it; NULL = not observed.
    upload_date = models.CharField(max_length=64, null=True, blank=True, default=None)
    # The key's fingerprint as GetSSHPublicKey states it (the MD5 of the key, colon-separated hex); NULL = not read.
    fingerprint = models.CharField(max_length=128, null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    # AWS has no tagging operation for this credential: always {} once collected.
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iam_ssh_public_key"

    def get_name(self) -> str:
        return self.name or self.ssh_public_key_id

    def __str__(self) -> str:
        return self.get_name()
