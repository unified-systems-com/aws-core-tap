"""IAM Signing Certificate — an X.509 signing certificate an AWS IAM user has uploaded."""

from typing import Any, ClassVar

from django.db import models
from tap_plugin.aws_core.times import certificate_not_after

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class IamSigningCertificate(BaseModel):
    """An X.509 signing certificate an IAM user has uploaded (for the SOAP-era APIs that sign with one).

    ListSigningCertificates returns the certificate body (public PEM text) with every row, and it is kept in
    ``configuration`` as AWS sent it (ruling Q150b, 2026-11-24): it holds the certificate's expiry."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_iam_signing_certificate"
    ENTITY_NAME: ClassVar[str] = "IAM Signing Certificate"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An X.509 signing certificate an IAM user has uploaded: id, status, upload time and the public certificate."
    )
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    # The type's dimensions, declared in this one place: aws_core's cloud default and computing_core's standard
    # credential dimension, its value the kind of credential (ruling Q146, 2026-11-23).
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws", "tap.computing.credential": "certificate"}
    # Identity (req-grid-entity-natural-key, req-aws-collector-identity-13).
    # AWS gives a signing certificate no ARN and CloudFormation no type; it is keyed by
    # the id AWS generates, scoped by partition and account (ruling Q142a).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("partition", "account_id", "certificate_id")
    # Event time (req-grid-entity-event-time, req-aws-core-models-5).
    # UploadDate (ListSigningCertificates), when the certificate was uploaded to IAM, until the certificate's notAfter,
    # the end it states (core rule 8). AWS returns the certificate as PEM text, kept in configuration['CertificateBody'],
    # and times.certificate_not_after reads its notAfter (ruling Q150b, 2026-11-24).
    EVENT_TIME: ClassVar[Interval] = Interval(
        start="upload_date",
        kind="created",
        end="configuration",
        end_member=("CertificateBody",),
        end_reader=certificate_not_after,
    )

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
        "certificate_id": {"type": "string"},
        "user_name": {"type": ["string", "null"]},
        "user_arn": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "upload_date": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "partition": {"validation": "jsonschema", "schema": {"type": "string"}},
        "account_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "certificate_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "user_name": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "user_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "upload_date": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    # Key columns: the partition and account the credential lives in, and AWS's own id for it.
    partition = models.CharField(max_length=32, blank=True, default="")
    account_id = models.CharField(max_length=12, blank=True, default="")
    # The certificate id AWS generates.
    certificate_id = models.CharField(max_length=128, blank=True, default="")
    # The user that holds it, as the listing names it; NULL = not observed.
    user_name = models.CharField(max_length=128, null=True, blank=True, default=None)
    user_arn = models.CharField(max_length=512, null=True, blank=True, default=None)
    # Active, Inactive or Expired, as AWS reports it; NULL = not observed.
    status = models.CharField(max_length=32, null=True, blank=True, default=None)
    # ISO 8601 UTC time the certificate was uploaded, as AWS states it; NULL = not observed.
    upload_date = models.CharField(max_length=64, null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    # AWS has no tagging operation for this credential: always {} once collected.
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_iam_signing_certificate"

    def get_name(self) -> str:
        return self.name or self.certificate_id

    def __str__(self) -> str:
        return self.get_name()
