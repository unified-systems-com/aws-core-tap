"""Route 53 Record Set — one record set in an Amazon Route 53 hosted zone."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class Route53RecordSet(BaseModel):
    """One record set in a Route 53 hosted zone: a name, a type and, for a routing policy, a set identifier."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_route53_record_set"
    ENTITY_NAME: ClassVar[str] = "Route 53 Record Set"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "One record set in a Route 53 hosted zone: the hostname, its type and what it answers with."
    )
    ENTITY_ICON: ClassVar[str] = "aws-route53"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): a record set is unique within its zone by name, type and set
    # identifier (Route 53's ChangeResourceRecordSets addresses it by exactly those). The key is the four in one
    # string, "<zone id>/<name>/<type>/<set identifier>", the set identifier empty for a simple record, because the
    # collector names a node by one key value (aws-core-tap#220).
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("record_set_key",)
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#EDE7F3", "border": "#7B5EA7", "label": "#221A2E"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "record_set_key": {"type": "string"},
        "hosted_zone_id": {"type": "string"},
        "record_name": {"type": "string"},
        "record_type": {"type": "string"},
        "set_identifier": {"type": ["string", "null"]},
        "ttl": {"type": ["integer", "null"]},
        "alias_dns_name": {"type": ["string", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "record_set_key": {"validation": "jsonschema", "schema": {"type": "string"}},
        "hosted_zone_id": {"validation": "jsonschema", "schema": {"type": "string"}},
        "record_name": {"validation": "jsonschema", "schema": {"type": "string"}},
        "record_type": {"validation": "jsonschema", "schema": {"type": "string"}},
        "set_identifier": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "ttl": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
        "alias_dns_name": {"validation": "jsonschema", "schema": {"type": ["string", "null"]}},
        "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
        "tags": {"validation": "jsonschema", "schema": {"type": ["object", "null"]}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=1024, blank=True, default="")
    record_set_key = models.CharField(max_length=1200, blank=True, default="", db_index=True)
    hosted_zone_id = models.CharField(max_length=64, blank=True, default="")
    record_name = models.CharField(max_length=1024, blank=True, default="")
    record_type = models.CharField(max_length=16, blank=True, default="")
    set_identifier = models.CharField(max_length=128, null=True, blank=True, default=None)
    ttl = models.BigIntegerField(null=True, blank=True, default=None)
    alias_dns_name = models.CharField(max_length=1024, null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    # Route 53 record sets cannot be tagged; the column exists because every collected type carries one, and it
    # stays null (unobserved).
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_route53_record_set"

    def get_name(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name
