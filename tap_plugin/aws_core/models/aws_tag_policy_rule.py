"""AWS Tag Policy Rule — one tag key's rule in an AWS Organizations tag policy."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


def _string_list(description: str) -> dict[str, Any]:
    return {
        "type": ["array", "null"],
        "description": description,
        "items": {"type": "string", "description": "One value, as the policy names it."},
    }


class AwsTagPolicyRule(BaseModel):
    """The rule one ``TAG_POLICY`` document gives one tag key.

    A tag policy is a tree of settings with inheritance operators (``@@assign``, ``@@append``,
    ``@@remove``), not a list of statements; its independently meaningful unit is one tag key's
    rule. Keyed ``(policy_arn, tag_key_lower)`` and contained by its policy (``DECLARES_TAG_RULE``):
    an edit to a key's rule updates the node in place, and removing the key retires it.

    Collecting tag policies is AWS's own tag governance read onto the grid (ruling 2026-10-01),
    not a TAP tag mechanism: nothing here touches ``normalize_tags`` or any node's ``tags``. AWS
    cannot tag a rule, so its own ``tags`` is always ``{}`` and its lane is declared ``none``.

    Spec: specs/spec-aws-core-v0.md (req-aws-core-organizations-completeness-11)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_tag_policy_rule"
    ENTITY_NAME: ClassVar[str] = "AWS Tag Policy Rule"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "The rule an AWS Organizations tag policy gives one tag key: its required capitalization, "
        "allowed values and the resource types it is enforced for."
    )
    ENTITY_ICON: ClassVar[str] = "aws-organizations"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#FBE0ED", "border": "#E7157B", "label": "#400522"},
        }
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("policy_arn", "tag_key_lower")

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "policy_arn": {"type": "string", "maxLength": 512},
        "tag_key_lower": {"type": "string", "maxLength": 128},
        # tag_key.@@assign: the capitalization the rule assigns; the document's key when it assigns none.
        "tag_key": {"type": "string", "maxLength": 128},
        "allowed_values": _string_list(
            "tag_value's @@assign and @@append values, de-duplicated and sorted; null when the rule does not constrain values."
        ),
        "enforced_for": _string_list(
            "enforced_for's @@assign and @@append resource types, de-duplicated and sorted; null when absent."
        ),
        "inheritance_operators": {
            "type": ["array", "null"],
            "description": "Every inheritance operator the rule uses anywhere in its body, sorted.",
            "items": {"type": "string", "pattern": "^@@", "description": "One operator, such as @@assign."},
        },
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    policy_arn = models.CharField(max_length=512, blank=True, default="", db_index=True)
    tag_key_lower = models.CharField(max_length=128, blank=True, default="")
    tag_key = models.CharField(max_length=128, blank=True, default="")
    allowed_values = models.JSONField(null=True, blank=True, default=None)
    enforced_for = models.JSONField(null=True, blank=True, default=None)
    inheritance_operators = models.JSONField(null=True, blank=True, default=None)
    # Canonical {str: str} (req-aws-core-fields-4). A rule is not an AWS resource: always {}.
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_tag_policy_rule"

    def get_name(self) -> str:
        return self.name or self.tag_key or self.tag_key_lower

    def __str__(self) -> str:
        return self.get_name()
