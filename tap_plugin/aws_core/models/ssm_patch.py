"""SSM Patch — a vendor patch that is a gap on some managed instance (req-aws-core-ssm-patch-state, rulings B2, Q147)."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import NO_EVENT_TIME, NoEventTime
from tap_grid.models import BaseModel


class SsmPatch(BaseModel):
    """One patch, as DescribeInstancePatches names it, keyed by partition, the SSM operating system of the baseline that evaluated the instance, and the KBId (a Windows KB number, or a Linux package name, epoch, version and release). Made only for a patch that needs action on some instance (MISSING, FAILED, INSTALLED_PENDING_REBOOT, INSTALLED_REJECTED or AVAILABLE_SECURITY_UPDATE; ruling Q147 option 3). One node serves every instance that reports it; each such instance's state, severity and install time are on its REPORTS_PATCH edge. cve_ids is the CVE list AWS gives the patch, split from its comma-separated string. With ssm_compliance_findings on, each CVE also links the patch to compliance_core's vulnerability by RESOLVES_VULNERABILITY."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ssm_patch"
    ENTITY_NAME: ClassVar[str] = "SSM Patch"
    ENTITY_DESCRIPTION: ClassVar[str] = "A patch that needs action on some SSM managed instance, shared by every instance that reports it."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): Partition, SSM operating system and KBId: a patch has no ARN and is not an account's resource.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("partition", "operating_system", "kb_id")
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): no typed field of this model says when
    # the thing happened in the world; EVENT_TIME_REASON says why.
    EVENT_TIME: ClassVar[NoEventTime] = NO_EVENT_TIME
    EVENT_TIME_REASON: ClassVar[str] = (
        "AWS states no time for the patch itself in its own record (DescribeInstancePatches Patches[]): no release or "
        "creation date. InstalledTime there is when one instance installed it, which is that instance's fact and is "
        "held on its REPORTS_PATCH edge, not the patch's."
    )

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "partition": {"type": "string"},
        "operating_system": {"type": "string"},
        "kb_id": {"type": "string"},
        "title": {"type": ["string", "null"]},
        "classification": {"type": ["string", "null"]},
        "cve_ids": {"type": ["array", "null"], "items": {"type": "string"}},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["kb_id"]

    name = models.CharField(max_length=255, blank=True, default="")
    partition = models.CharField(max_length=32, blank=True, default="")
    # The SSM OperatingSystem enum (WINDOWS, AMAZON_LINUX_2023, ...).
    operating_system = models.CharField(max_length=64, blank=True, default="")
    kb_id = models.CharField(max_length=1024, blank=True, default="")
    title = models.TextField(null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    classification = models.CharField(max_length=255, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    cve_ids = models.JSONField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ssm_patch"

    def get_name(self) -> str:
        return self.title or self.kb_id

    def __str__(self) -> str:
        return self.get_name()
