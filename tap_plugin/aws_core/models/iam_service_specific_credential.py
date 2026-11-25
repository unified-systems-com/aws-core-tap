"""IAM Service-Specific Credential — a credential an AWS IAM user holds for one AWS service."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class IamServiceSpecificCredential(BaseModel):
    """A service-specific credential an IAM user holds: a user name and password, or an API key, for one AWS service.

    Metadata only (ruling Q142a, 2026-11-23): AWS returns the password only when the credential is created or reset,
    which aws_core never does; it is never a field."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_service_specific_credential"
    ENTITY_NAME: ClassVar[str] = "IAM Service-Specific Credential"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "A credential an IAM user holds for one AWS service: id, service, status and age, never the password."
    )
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    # The type's dimensions, declared in this one place: aws_core's cloud default and computing_core's standard
    # credential dimension, its value the kind of credential (a generated user name and password, or an API key) (ruling Q146, 2026-11-23).
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws", "tap.computing.credential": "password"}
    # Identity (req-grid-entity-natural-key, req-aws-collector-identity-13).
    # AWS gives a service-specific credential no ARN and CloudFormation no type; it
    # is keyed by the id AWS generates, scoped by partition and account (ruling Q142a).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("partition", "account_id", "service_specific_credential_id")
    # Event time (req-grid-entity-event-time, req-aws-core-models-5).
    # CreateDate (ListServiceSpecificCredentials), when AWS created it, until
    # ExpirationDate, the end AWS states for a credential created with one (a Bedrock API key). An interval that ends
    # where AWS states an end (core rule 8); a credential with no expiry has none.
    EVENT_TIME: ClassVar[Interval] = Interval(start="create_date", kind="created", end="expiration_date")

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
        "service_specific_credential_id": {"type": "string"},
        "user_name": {"type": ["string", "null"]},
        "user_arn": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "service_name": {"type": ["string", "null"]},
        "service_user_name": {"type": ["string", "null"]},
        "service_credential_alias": {"type": ["string", "null"]},
        "create_date": {"type": ["string", "null"]},
        "expiration_date": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "partition": {"validation": "jsonschema", "schema": {"type": "string"}},
        "account_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "service_specific_credential_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "user_name": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "user_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "service_name": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "service_user_name": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "service_credential_alias": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "create_date": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "expiration_date": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    # Key columns: the partition and account the credential lives in, and AWS's own id for it.
    partition = models.CharField(max_length=32, blank=True, default="")
    account_id = models.CharField(max_length=12, blank=True, default="")
    # The credential id (ACCA...) AWS generates.
    service_specific_credential_id = models.CharField(max_length=128, blank=True, default="")
    # The user that holds it, as the listing names it; NULL = not observed.
    user_name = models.CharField(max_length=128, null=True, blank=True, default=None)
    user_arn = models.CharField(max_length=512, null=True, blank=True, default=None)
    # Active, Inactive or Expired, as AWS reports it; NULL = not observed.
    status = models.CharField(max_length=32, null=True, blank=True, default=None)
    # The service the credential is for (codecommit.amazonaws.com, cassandra.amazonaws.com, ...).
    service_name = models.CharField(max_length=255, null=True, blank=True, default=None)
    # The user name the service takes with the password (the IAM user name and the account id).
    service_user_name = models.CharField(max_length=255, null=True, blank=True, default=None)
    # The alias AWS gives an API-key credential; "" when it has none; NULL = not observed.
    service_credential_alias = models.CharField(max_length=255, null=True, blank=True, default=None)
    # ISO 8601 UTC time the credential was created, as AWS states it; NULL = not observed.
    create_date = models.CharField(max_length=64, null=True, blank=True, default=None)
    # ISO 8601 UTC time the credential expires; "" = AWS states no expiry; NULL = not observed.
    expiration_date = models.CharField(max_length=64, null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    # AWS has no tagging operation for this credential: always {} once collected.
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iam_service_specific_credential"

    def get_name(self) -> str:
        return self.name or self.service_specific_credential_id

    def __str__(self) -> str:
        return self.get_name()
