"""SSM Managed Instance — a node AWS Systems Manager manages, and its last patch operation (req-aws-core-ssm-patch-state)."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.event_time import Interval
from tap_grid.models import BaseModel


class SsmManagedInstance(BaseModel):
    """An EC2 instance or hybrid node SSM manages (DescribeInstanceInformation), with the state of its last patch operation (DescribeInstancePatchStates) in typed, nullable fields (ruling A1). Null is not observed: an instance never scanned, or whose patch state could not be read, has null patch fields. OwnerInformation is never read into a field."""

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_ssm_managed_instance"
    ENTITY_NAME: ClassVar[str] = "SSM Managed Instance"
    ENTITY_DESCRIPTION: ClassVar[str] = "A node AWS Systems Manager manages (an EC2 instance or a hybrid mi- node), with its last patch operation."
    ENTITY_ICON: ClassVar[str] = "aws-generic"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.computing.cloud": "aws"}
    # Identity (req-grid-entity-natural-key): The id AWS generates for the node: the EC2 instance id, or SSM's mi- id for a hybrid node. DescribeInstanceInformation returns no ARN.
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("instance_id",)
    ARN_RESOURCE: ClassVar[str | None] = "ssm:managed-instance"
    # Event time (req-grid-entity-event-time, req-aws-core-models-5): RegistrationDate (DescribeInstanceInformation
    # InstanceInformationList[]), when the node was registered with AWS as a managed node, which is when this record
    # came to exist; AWS states it for a hybrid (mi-) node. An EC2 node's record states none (the EC2 instance's
    # LaunchTime is the EC2 instance's own, on that node), so its spine is empty. No end: AWS states none (core rule 8).
    EVENT_TIME: ClassVar[Interval] = Interval(start="registration_date", kind="created")

    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {
            "shape": "rectangle",
            "colors": {"fill": "#C3CFDC", "border": "#2B5783", "label": "#0C1824"},
        }
    }

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string"},
        "instance_id": {"type": "string"},
        "resource_type": {"type": ["string", "null"]},
        "ping_status": {"type": ["string", "null"]},
        "last_ping_at": {"type": ["string", "null"]},
        "agent_version": {"type": ["string", "null"]},
        "is_latest_version": {"type": ["boolean", "null"]},
        "platform_type": {"type": ["string", "null"]},
        "platform_name": {"type": ["string", "null"]},
        "platform_version": {"type": ["string", "null"]},
        "computer_name": {"type": ["string", "null"]},
        "iam_role": {"type": ["string", "null"]},
        "activation_id": {"type": ["string", "null"]},
        "registration_date": {"type": ["string", "null"]},
        "association_status": {"type": ["string", "null"]},
        "last_association_execution_at": {"type": ["string", "null"]},
        "last_successful_association_execution_at": {"type": ["string", "null"]},
        "source_id": {"type": ["string", "null"]},
        "source_type": {"type": ["string", "null"]},
        "patch_group": {"type": ["string", "null"]},
        "patch_baseline_id": {"type": ["string", "null"]},
        "patch_operation": {"type": ["string", "null"]},
        "patch_operation_start_at": {"type": ["string", "null"]},
        "patch_operation_end_at": {"type": ["string", "null"]},
        "patch_last_no_reboot_install_at": {"type": ["string", "null"]},
        "patch_reboot_option": {"type": ["string", "null"]},
        "patch_snapshot_id": {"type": ["string", "null"]},
        "patch_install_override_list": {"type": ["string", "null"]},
        "patch_installed_count": {"type": ["integer", "null"]},
        "patch_installed_other_count": {"type": ["integer", "null"]},
        "patch_installed_pending_reboot_count": {"type": ["integer", "null"]},
        "patch_installed_rejected_count": {"type": ["integer", "null"]},
        "patch_missing_count": {"type": ["integer", "null"]},
        "patch_failed_count": {"type": ["integer", "null"]},
        "patch_unreported_not_applicable_count": {"type": ["integer", "null"]},
        "patch_not_applicable_count": {"type": ["integer", "null"]},
        "patch_available_security_update_count": {"type": ["integer", "null"]},
        "patch_critical_non_compliant_count": {"type": ["integer", "null"]},
        "patch_security_non_compliant_count": {"type": ["integer", "null"]},
        "patch_other_non_compliant_count": {"type": ["integer", "null"]},
        "configuration": {"type": "object"},
        "tags": {"type": ["object", "null"]},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["instance_id"]

    name = models.CharField(max_length=255, blank=True, default="")
    # i-... for an EC2 node, mi-... for a hybrid one.
    instance_id = models.CharField(max_length=64, blank=True, default="")
    # EC2Instance or ManagedInstance.
    resource_type = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    # Online, ConnectionLost or Inactive.
    ping_status = models.CharField(max_length=32, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    # ISO 8601 UTC.
    last_ping_at = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    agent_version = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    is_latest_version = models.BooleanField(null=True, blank=True, default=None)
    # Windows, Linux or MacOS.
    platform_type = models.CharField(max_length=32, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    platform_name = models.CharField(max_length=255, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    platform_version = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    computer_name = models.CharField(max_length=255, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    iam_role = models.CharField(max_length=255, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    activation_id = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    # ISO 8601 UTC.
    registration_date = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    association_status = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    last_association_execution_at = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    last_successful_association_execution_at = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    source_id = models.CharField(max_length=255, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    source_type = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    # The Patch Group tag value the last operation ran under; patch groups are not nodes yet (Fork D unruled).
    patch_group = models.CharField(max_length=256, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    # The baseline the last operation used: pb-... for the account's own, an ARN for an AWS-provided one.
    patch_baseline_id = models.CharField(max_length=2048, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    # Scan or Install.
    patch_operation = models.CharField(max_length=16, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    patch_operation_start_at = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    patch_operation_end_at = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    patch_last_no_reboot_install_at = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    patch_reboot_option = models.CharField(max_length=32, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    patch_snapshot_id = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    patch_install_override_list = models.TextField(null=True, blank=True, default=None)  # noqa: DJ001 — null is "not observed"
    patch_installed_count = models.IntegerField(null=True, blank=True, default=None)
    patch_installed_other_count = models.IntegerField(null=True, blank=True, default=None)
    patch_installed_pending_reboot_count = models.IntegerField(null=True, blank=True, default=None)
    patch_installed_rejected_count = models.IntegerField(null=True, blank=True, default=None)
    patch_missing_count = models.IntegerField(null=True, blank=True, default=None)
    patch_failed_count = models.IntegerField(null=True, blank=True, default=None)
    patch_unreported_not_applicable_count = models.IntegerField(null=True, blank=True, default=None)
    patch_not_applicable_count = models.IntegerField(null=True, blank=True, default=None)
    patch_available_security_update_count = models.IntegerField(null=True, blank=True, default=None)
    patch_critical_non_compliant_count = models.IntegerField(null=True, blank=True, default=None)
    patch_security_non_compliant_count = models.IntegerField(null=True, blank=True, default=None)
    patch_other_non_compliant_count = models.IntegerField(null=True, blank=True, default=None)
    configuration = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_ssm_managed_instance"

    def get_name(self) -> str:
        return self.name or self.instance_id

    def __str__(self) -> str:
        return self.get_name()
