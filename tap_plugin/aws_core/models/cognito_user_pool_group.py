"""Cognito User Pool Group — a group in an Amazon Cognito user pool."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class CognitoUserPoolGroup(BaseModel):
    """A Cognito user pool group: users in it get its IAM role in the tokens they are issued, so the group is a path to AWS permissions."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_cognito_user_pool_group"
    ENTITY_NAME: ClassVar[str] = "Cognito User Pool Group"
    ENTITY_DESCRIPTION: ClassVar[str] = "A group in an Amazon Cognito user pool."
    ENTITY_ICON: ClassVar[str] = "aws-cognito"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The user pool id and the group name together (pool:group): a group name is unique only within a pool.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("group_key",)

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"},
        }
    }


    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "group_key": {"type": "string"},
        "user_pool_id": {"type": ["string", "null"]},
        "precedence": {"type": ["integer", "null"]},
        "role_arn": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "group_key": {"validation": "jsonschema", "schema": {"type": "string"}},
        "user_pool_id": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "precedence": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "role_arn": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    group_key = models.CharField(max_length=512, blank=True, default="")
    # The user pool the group belongs to. NULL = not observed.
    user_pool_id = models.CharField(max_length=512, blank=True, null=True, default=None)
    # The group's precedence when a user is in several. NULL = not set, or not observed.
    precedence = models.IntegerField(null=True, blank=True, default=None)
    # The IAM role the group's members receive. NULL = none, or not observed.
    role_arn = models.CharField(max_length=512, blank=True, null=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_cognito_user_pool_group"

    def get_name(self) -> str:
        return self.name or self.group_key

    def __str__(self) -> str:
        return self.get_name()
