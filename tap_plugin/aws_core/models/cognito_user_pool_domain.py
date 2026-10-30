"""Cognito User Pool Domain — a domain of an Amazon Cognito user pool."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CognitoUserPoolDomain(BaseModel):
    """A Cognito user pool domain: the hosted sign-in address, either a prefix on amazoncognito.com or a custom domain with its own certificate."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cognito_user_pool_domain"
    ENTITY_NAME: ClassVar[str] = "Cognito User Pool Domain"
    ENTITY_DESCRIPTION: ClassVar[str] = "A domain of an Amazon Cognito user pool."
    ENTITY_ICON: ClassVar[str] = "aws-cognito"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The user pool id and the domain together (pool:domain): a domain is unique across Cognito, and the pool disambiguates a reused prefix.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("domain_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "domain_key": {"type": "string"},
        "user_pool_id": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "certificate_arn": {"type": ["string", "null"]},
        "cloudfront_distribution": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "domain_key": {"validation": "jsonschema", "schema": {"type": "string"}},
        "user_pool_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "status": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "certificate_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "cloudfront_distribution": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    domain_key = models.CharField(max_length=512, blank=True, default="")
    # The user pool the domain belongs to. NULL = not observed.
    user_pool_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # AWS's status (ACTIVE, CREATING, ...). NULL = not observed.
    status = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The ACM certificate of a custom domain. NULL = none (a prefix domain), or not observed.
    certificate_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The CloudFront distribution that serves the domain. NULL = not observed.
    cloudfront_distribution = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cognito_user_pool_domain"

    def get_name(self) -> str:
        return self.name or self.domain_key

    def __str__(self) -> str:
        return self.get_name()
