"""CloudFront Distribution — an Amazon CloudFront content delivery distribution."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CloudfrontDistribution(BaseModel):
    """An Amazon CloudFront distribution.

    Spec: plugins/aws_core/specs/spec-aws-core-v0.md (req-aws-core-models),
    plugins/aws_core/specs/spec-aws-core-collector-v0.md
    (req-aws-collector-model-deps).

    `domain_name` is indexed because the Route 53 alias → CloudFront edge
    resolves by matching an alias record's target against this value.
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cloudfront_distribution"
    ENTITY_NAME: ClassVar[str] = "CloudFront Distribution"
    ENTITY_DESCRIPTION: ClassVar[str] = "An Amazon CloudFront content delivery distribution."
    ENTITY_ICON: ClassVar[str] = "aws-cloudfront"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The distribution's ARN, the boto3 collector's identity
    # for it.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("distribution_arn",)
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#DECDFF", "border": "#8C4FFF", "label": "#271647"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "distribution_arn": {"type": "string"},
        "domain_name": {"type": "string"},
        "status": {"type": "string"},
        "enabled": {"type": "boolean"},
        "origin_access": {"type": ["object", "null"], "additionalProperties": {"type": "string", "enum": ["oac", "oai", "none"]}},
        "origin_custom_headers_present": {"type": ["object", "null"], "additionalProperties": {"type": "boolean"}},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "distribution_arn": {"validation": "jsonschema", "schema": {"type": "string"}},
        "domain_name": {"validation": "jsonschema", "schema": {"type": "string"}},
        "status": {"validation": "jsonschema", "schema": {"type": "string"}},
        "enabled": {"validation": "jsonschema", "schema": {"type": "boolean"}},
        "origin_access": {"validation": "jsonschema", "schema": {"type": ["object", "null"], "additionalProperties": {"type": "string", "enum": ["oac", "oai", "none"]}}},
        "origin_custom_headers_present": {"validation": "jsonschema", "schema": {"type": ["object", "null"], "additionalProperties": {"type": "boolean"}}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    distribution_arn = models.CharField(max_length=512, blank=True, default="")
    domain_name = models.CharField(max_length=255, blank=True, default="", db_index=True)
    status = models.CharField(max_length=64, blank=True, default="")
    enabled = models.BooleanField(default=False)
    # {origin Id: "oac" | "oai" | "none"}: how CloudFront authenticates to each
    # origin, derived from the ListDistributions origin by the custom_fn. A typed
    # field because this type's configuration is not stored (origins can carry
    # shared-secret headers), and without it whether the origin is locked to
    # CloudFront would be lost. "none" means no OAC or OAI for that origin; it
    # does not mean public, since a custom origin may check a shared-secret
    # header (CustomHeaders), which origin_custom_headers_present records.
    # Null means not observed; {} means observed with no origins.
    origin_access = models.JSONField(null=True, blank=True, default=None)
    # {origin Id: bool}: whether CloudFront sends any custom header to that
    # origin (CustomHeaders), derived from the ListDistributions origin by the
    # custom_fn. Presence only: a custom origin header
    # is often a shared secret the origin checks, so neither its value nor its
    # name is stored. False is an observed absence; null means the
    # distribution has not been collected since this field was added.
    origin_custom_headers_present = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cloudfront_distribution"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
