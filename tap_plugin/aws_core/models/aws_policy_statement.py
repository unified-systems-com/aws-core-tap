"""AWS Policy Statement — one statement of an SCP or RCP document."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel

_STRING_LIST = {"type": "string"}


def _string_list(description: str) -> dict[str, Any]:
    return {
        "type": ["array", "null"],
        "description": description,
        "items": {**_STRING_LIST, "description": "One value, as the canonical form stores it."},
    }


_PRINCIPALS = {
    "type": ["array", "null"],
    "description": (
        "RCP principals, one entry per value, sorted by (type, value); [] on an SCP, whose grammar has "
        "no principal. A bare \"*\" is stored as {type: \"*\", value: \"*\"}, never folded into AWS."
    ),
    "items": {
        "type": "object",
        "description": "One principal value under one principal type.",
        "additionalProperties": False,
        "required": ["type", "value"],
        "properties": {
            "type": {"type": "string", "description": "The principal type key (AWS, Service, Federated, CanonicalUser, or *)."},
            "value": {"type": "string", "description": "One principal value, case kept."},
        },
    },
}


class AwsPolicyStatement(BaseModel):
    """One statement of a service control policy or resource control policy document.

    The 2026-10-01 rule, as ``specs/spec-aws-core-v0.md`` *Policy Statements* reads it: a statement
    is independently meaningful (it has a ``Sid``, and the questions asked of policies are
    statement questions), so it is a node contained by its policy (``DECLARES_STATEMENT``). Effect,
    actions, resources and conditions only make sense together, so they are typed fields. No
    action is a node, and no policy document is stored (``req-aws-core-organizations-7``).

    Identity is ``(policy_arn, statement_key)``: ``sid:<Sid>`` for a unique ``Sid``,
    ``content:<content_sha256>`` for a statement without one, ``dupsid:<sha256>`` for a repeated
    ``Sid``. ``content_sha256`` is the SHA-256 of the canonical form built from the stored typed
    fields (``collectors/boto3_collector/policy_documents.py``). Statement content is access-control
    configuration: ``collectors/boto3_collector/reader_sensitivity.json`` declares ``conditions``,
    ``principals``, ``not_principals``, ``resources`` and ``not_resources`` as ``access_policy``
    locations, and the reader refuses to write the type without that declaration. AWS cannot tag a
    statement: ``tags`` is always ``{}`` and its lane is declared ``none``.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-organizations-completeness-7, -8, -9, -10)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_policy_statement"
    ENTITY_NAME: ClassVar[str] = "AWS Policy Statement"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "One statement of an AWS Organizations service control policy or resource control policy: "
        "its effect, actions, resources, principals and conditions."
    )
    ENTITY_ICON: ClassVar[str] = "aws-organizations"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#FBE0ED", "border": "#E7157B", "label": "#400522"},
        }
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("policy_arn", "statement_key")

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "policy_arn": {"type": "string", "maxLength": 512},
        "statement_key": {"type": "string", "pattern": "^((sid|content|dupsid):.+)?$", "maxLength": 512},
        "sid": {"type": "string"},
        "effect": {"type": "string", "enum": ["", "Allow", "Deny"]},
        "actions": _string_list("Action, lowercased (IAM matches action names case-insensitively), de-duplicated, sorted."),
        "not_actions": _string_list("NotAction, lowercased, de-duplicated, sorted."),
        "resources": _string_list("Resource ARN patterns, case kept, de-duplicated, sorted."),
        "not_resources": _string_list("NotResource ARN patterns, case kept, de-duplicated, sorted."),
        "principals": _PRINCIPALS,
        "not_principals": {**_PRINCIPALS, "description": "RCP NotPrincipal entries, in the same form as principals."},
        "conditions": {
            "type": ["array", "null"],
            "description": "The Condition block, one entry per key under each operator, sorted by (operator, condition_key); [] when there is none.",
            "items": {
                "type": "object",
                "description": "One condition key under one condition operator.",
                "additionalProperties": False,
                "required": ["operator", "condition_key", "values"],
                "properties": {
                    "operator": {"type": "string", "description": "The condition operator, lowercased (for example stringequals)."},
                    "condition_key": {"type": "string", "description": "The condition key, lowercased (for example aws:requestedregion)."},
                    "values": {
                        "type": "array",
                        "description": "The condition values as strings, case kept, de-duplicated, sorted.",
                        "items": {"type": "string", "description": "One condition value."},
                    },
                },
            },
        },
        "positions": {
            "type": ["array", "null"],
            "description": "The sorted 0-based indices at which this statement appears in the document as last read. Informational, never identity.",
            "items": {"type": "integer", "minimum": 0, "description": "One position in the Statement array."},
        },
        "occurrences": {"type": ["integer", "null"], "minimum": 1},
        "content_sha256": {"type": "string", "pattern": "^([0-9a-f]{64})?$"},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    policy_arn = models.CharField(max_length=512, blank=True, default="", db_index=True)
    statement_key = models.CharField(max_length=512, blank=True, default="")
    sid = models.CharField(max_length=255, blank=True, default="")
    effect = models.CharField(max_length=8, blank=True, default="")
    # Structured facts default to null, "not observed" (req-aws-core-fields-8); the collector
    # always writes a list, [] being an observed empty.
    actions = models.JSONField(null=True, blank=True, default=None)
    not_actions = models.JSONField(null=True, blank=True, default=None)
    resources = models.JSONField(null=True, blank=True, default=None)
    not_resources = models.JSONField(null=True, blank=True, default=None)
    principals = models.JSONField(null=True, blank=True, default=None)
    not_principals = models.JSONField(null=True, blank=True, default=None)
    conditions = models.JSONField(null=True, blank=True, default=None)
    positions = models.JSONField(null=True, blank=True, default=None)
    occurrences = models.IntegerField(null=True, blank=True, default=None)
    content_sha256 = models.CharField(max_length=64, blank=True, default="")
    # Canonical {str: str} (req-aws-core-fields-4). A statement is not an AWS resource: always {}.
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_policy_statement"

    def get_name(self) -> str:
        return self.name or self.statement_key

    def __str__(self) -> str:
        return self.get_name()
