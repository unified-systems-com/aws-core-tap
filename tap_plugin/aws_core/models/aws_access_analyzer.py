"""AWS IAM Access Analyzer analyzer — one analyzer in one account and region."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsAccessAnalyzer(BaseModel):
    """One IAM Access Analyzer analyzer.

    Read with ``accessanalyzer:ListAnalyzers(type=…)`` once per value of the pinned ``Type`` enum,
    each read to its last page, behind one surface complete only when every per-type listing
    finished (``req-aws-core-contained-type-triple-6``). ``analyzer_type`` holds the API's ``type``
    verbatim, including a value newer than the pinned enum. Tags come from the item's own
    lowercase ``tags`` map. Contained by its footprint (``HOSTS_ACCESS_ANALYZER``).

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-security-services)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_access_analyzer"
    ENTITY_NAME: ClassVar[str] = "AWS IAM Access Analyzer"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An IAM Access Analyzer analyzer: finds external, internal or unused access across one "
        "account or a whole organization."
    )
    ENTITY_ICON: ClassVar[str] = "aws-iam"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F5C6CC", "border": "#DD344C", "label": "#3D0E15"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("analyzer_arn",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "analyzer_arn": {"type": "string"},
        "analyzer_name": {"type": "string"},
        # The API's `type`, verbatim (ACCOUNT, ORGANIZATION, ..._UNUSED_ACCESS, ..._INTERNAL_ACCESS).
        "analyzer_type": {"type": "string"},
        "status": {"type": "string"},
        "created_at": {"type": "string"},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    analyzer_arn = models.CharField(max_length=2048, blank=True, default="", db_index=True)
    analyzer_name = models.CharField(max_length=255, blank=True, default="")
    analyzer_type = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=32, blank=True, default="")
    created_at = models.CharField(max_length=40, blank=True, default="")
    # AWS tags, canonical flat {str: str}. Source: the analyzer's own `tags` map.
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_access_analyzer"

    def get_name(self) -> str:
        return self.name or self.analyzer_name or self.analyzer_arn

    def __str__(self) -> str:
        return self.get_name()
