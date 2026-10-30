"""ACM Private CA — an AWS Private Certificate Authority."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel

# acm-pca enums, as DescribeCertificateAuthority reports them.
CA_TYPES = ["ROOT", "SUBORDINATE"]
KEY_ALGORITHMS = ["RSA_2048", "RSA_3072", "RSA_4096", "EC_prime256v1", "EC_secp384r1", "EC_secp521r1", "SM2"]
STATUSES = ["CREATING", "PENDING_CERTIFICATE", "ACTIVE", "DELETED", "DISABLED", "EXPIRED", "FAILED"]
USAGE_MODES = ["GENERAL_PURPOSE", "SHORT_LIVED_CERTIFICATE"]


class AcmPrivateCa(BaseModel):
    """An AWS Private Certificate Authority.

    A subordinate CA's issuer, and an ACM certificate's issuing private CA, are ``ISSUED_BY_CA``
    edges. Design vocabulary: no collector emits it yet. Fields are those
    ``acm-pca:DescribeCertificateAuthority`` reports; ``subject_common_name`` is
    ``CertificateAuthorityConfiguration.Subject.CommonName``.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-private-ca)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_acm_private_ca"
    ENTITY_NAME: ClassVar[str] = "ACM Private CA"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Private Certificate Authority: a root or subordinate CA that issues private certificates."
    )
    ENTITY_ICON: ClassVar[str] = "aws-private-ca"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }

    # AWS's CA ARN; there is no shorter id.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("ca_arn",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "ca_arn": {
            "type": "string",
            "pattern": "^(arn:aws(-us-gov|-cn)?:acm-pca:[a-z0-9-]+:[0-9]{12}:certificate-authority/[0-9a-f-]{36})?$",
        },
        "ca_type": {"type": "string", "enum": ["", *CA_TYPES]},
        "key_algorithm": {"type": "string", "enum": ["", *KEY_ALGORITHMS]},
        "status": {"type": "string", "enum": ["", *STATUSES]},
        "usage_mode": {"type": "string", "enum": ["", *USAGE_MODES]},
        "subject_common_name": {"type": "string"},
        "tags": {"type": ["object", "null"], "additionalProperties": {"type": "string"}},
        "configuration": {"type": "object"},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    ca_arn = models.CharField(max_length=200, blank=True, default="", db_index=True)
    # Blank means not observed for each enum (the aws_elb.lb_type convention).
    ca_type = models.CharField(max_length=16, blank=True, default="")
    key_algorithm = models.CharField(max_length=16, blank=True, default="")
    status = models.CharField(max_length=24, blank=True, default="")
    usage_mode = models.CharField(max_length=32, blank=True, default="")
    subject_common_name = models.CharField(max_length=64, blank=True, default="")
    # AWS tags, canonical flat {str: str} (req-aws-core-fields-4). Source: acm-pca:ListTags.
    tags = models.JSONField(null=True, blank=True, default=None)
    # The collector's configuration envelope; {} when the manifest entry does not persist it.
    configuration = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_acm_private_ca"

    def get_name(self) -> str:
        return self.name or self.subject_common_name or self.ca_arn

    def __str__(self) -> str:
        return self.get_name()
