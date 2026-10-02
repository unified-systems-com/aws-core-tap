"""AWS Config delivery channel — where Config delivers configuration snapshots and history."""

from typing import Any, ClassVar

from django.db import models

from tap_grid.models import BaseModel


class AwsConfigDeliveryChannel(BaseModel):
    """One AWS Config delivery channel.

    Read with ``config:DescribeDeliveryChannels`` (one call, not paginated). AWS gives a channel no
    ARN, so it is keyed (account, region, channel name). ``WRITES_LOGS`` points at the S3 bucket
    ``s3BucketName`` names, keyed ``arn:<run partition>:s3:::<bucket>``; the key prefix is the typed
    field ``s3_key_prefix``. AWS cannot tag a delivery channel, so ``tags`` is always ``{}``.
    Contained by its footprint (``HOSTS_CONFIG_DELIVERY_CHANNEL``).

    Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-security-services)
    """

    ENTITY_TYPE: ClassVar[str] = "aws_core__aws_config_delivery_channel"
    ENTITY_NAME: ClassVar[str] = "AWS Config Delivery Channel"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "An AWS Config delivery channel: the S3 bucket (and optional SNS topic) Config delivers "
        "configuration snapshots and history to."
    )
    ENTITY_ICON: ClassVar[str] = "aws-config"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap.cloud": "aws"}
    DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {
        "tap_viz": {"shape": "rectangle", "colors": {"fill": "#F8BDDA", "border": "#E7157B", "label": "#400522"}}
    }

    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("account_id", "region", "channel_name")

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "aws_core__aws_s3_bucket"}], "edges": [{"type": "WRITES_LOGS__aws_core"}]}
    ]

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
        "name": {"type": "string", "minLength": 1},
        "account_id": {"type": "string", "pattern": "^([0-9]{12})?$"},
        "region": {"type": "string"},
        "channel_name": {"type": "string"},
        "s3_bucket_name": {"type": "string"},
        "s3_key_prefix": {"type": "string"},
        "s3_kms_key_arn": {"type": "string"},
        "sns_topic_arn": {"type": "string"},
        # configSnapshotDeliveryProperties.deliveryFrequency, verbatim.
        "delivery_frequency": {"type": "string"},
        "tags": {"type": "object", "additionalProperties": {"type": "string"}},
    }

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
        name: {"validation": "jsonschema", "schema": schema} for name, schema in FIELD_CRUD_SCHEMA.items()
    }

    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    name = models.CharField(max_length=255, blank=True, default="")
    account_id = models.CharField(max_length=12, blank=True, default="", db_index=True)
    region = models.CharField(max_length=32, blank=True, default="")
    channel_name = models.CharField(max_length=256, blank=True, default="")
    s3_bucket_name = models.CharField(max_length=256, blank=True, default="")
    s3_key_prefix = models.CharField(max_length=1024, blank=True, default="")
    s3_kms_key_arn = models.CharField(max_length=2048, blank=True, default="")
    sns_topic_arn = models.CharField(max_length=2048, blank=True, default="")
    delivery_frequency = models.CharField(max_length=32, blank=True, default="")
    # Canonical {str: str}. AWS cannot tag a delivery channel: always {}.
    tags = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "aws_core__aws_config_delivery_channel"

    def get_name(self) -> str:
        return self.name or self.channel_name

    def __str__(self) -> str:
        return self.get_name()
