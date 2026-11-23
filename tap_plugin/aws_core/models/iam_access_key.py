"""IAM Access Key — an access key an AWS IAM user holds."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class IamAccessKey(BaseModel):
    """An access key an IAM user holds: its id, status, age and last use.

    Metadata only (ruling Q142a, 2026-11-23): the secret access key is never requested and is never a field."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_access_key"
    ENTITY_NAME: ClassVar[str] = "IAM Access Key"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An access key an IAM user holds: id, status, age and last use, never the secret."
    )
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    # The type's dimensions, declared in this one place: aws_core's cloud default and computing_core's standard
    # credential dimension, its value the kind of credential (ruling Q146, 2026-11-23).
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws", "tap.computing.credential": "access_key"}
    # Identity (req-grid-entity-natural-key, req-aws-collector-identity-13).
    # AWS gives an access key no ARN; it is keyed by its id (CloudFormation's AWS::IAM::AccessKey identifier),
    # scoped by partition and account (ruling Q142a).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("partition", "account_id", "access_key_id")
    # Event time (req-grid-entity-event-time, req-aws-core-models-5).
    # CreateDate (ListAccessKeys), when AWS created the key. AWS states no end:
    # a key lasts until it is deleted, and its last use is another time, kept as last_used_date (core rule 14).
    EVENT_TIME: ClassVar[Interval] = Interval(start="create_date", kind="created")

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
        "access_key_id": {"type": "string"},
        "user_name": {"type": ["string", "null"]},
        "user_arn": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "create_date": {"type": ["string", "null"]},
        "last_used_date": {"type": ["string", "null"]},
        "last_used_service": {"type": ["string", "null"]},
        "last_used_region": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "partition": {"validation": "jsonschema", "schema": {"type": "string"}},
        "account_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "access_key_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "user_name": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "user_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "create_date": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "last_used_date": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "last_used_service": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "last_used_region": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    # Key columns: the partition and account the credential lives in, and AWS's own id for it.
    partition = models.CharField(max_length=32, blank=True, default="")
    account_id = models.CharField(max_length=12, blank=True, default="")
    # The access key id (AKIA...): an identifier, never the secret, which AWS returns only at creation.
    access_key_id = models.CharField(max_length=128, blank=True, default="")
    # The user that holds it, as the listing names it; NULL = not observed.
    user_name = models.CharField(max_length=128, null=True, blank=True, default=None)
    user_arn = models.CharField(max_length=512, null=True, blank=True, default=None)
    # Active, Inactive or Expired, as AWS reports it; NULL = not observed.
    status = models.CharField(max_length=32, null=True, blank=True, default=None)
    # ISO 8601 UTC time the key was created, as AWS states it; NULL = not observed.
    create_date = models.CharField(max_length=64, null=True, blank=True, default=None)
    # When AWS last saw the key used (GetAccessKeyLastUsed); "" = observed, never used; NULL = not read.
    last_used_date = models.CharField(max_length=64, null=True, blank=True, default=None)
    # The service and region of that last use; "" = never used; NULL = not read.
    last_used_service = models.CharField(max_length=128, null=True, blank=True, default=None)
    last_used_region = models.CharField(max_length=64, null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    # AWS has no tagging operation for this credential: always {} once collected.
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iam_access_key"

    def get_name(self) -> str:
        return self.name or self.access_key_id

    def __str__(self) -> str:
        return self.get_name()
