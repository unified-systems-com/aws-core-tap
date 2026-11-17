# Design vocabulary for the AWS Organizations tree, IAM Identity Center and Transit Gateway
# (req-aws-core-organizations, req-aws-core-identity-center, req-aws-core-transit-gateway).
# Additive only: six CreateModel pairs, nothing touching existing tables. tap_grid is pinned at
# the plugin's floor (0001_initial), as 0001-0003 are, so the plugin keeps migrating against the
# oldest core it supports.

import django.db.models.deletion
import simple_history.models
from django.conf import settings
from django.db import migrations, models
from tap_plugin.aws_core.migrations._bulk import BulkCreateModels


class Migration(migrations.Migration):

    dependencies = [
        ("aws_core", "0008_cloudfront_origin_custom_headers_present"),
        ("tap_grid", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        BulkCreateModels([
migrations.CreateModel(
            name="AwsIdentityCenterInstance",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "batch_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="UUIDv7 of the batch this change was included in.",
                        max_length=36,
                    ),
                ),
                (
                    "flip_map",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="FLIP field-path-to-batch-id map: tracks which batch last set each provenance-tracked field.",
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=255)),
                (
                    "instance_arn",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=1224
                    ),
                ),
                (
                    "identity_store_id",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                (
                    "owner_account_id",
                    models.CharField(blank=True, default="", max_length=12),
                ),
                (
                    "home_region",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                ("tags", models.JSONField(blank=True, default=dict)),
                (
                    "entity",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)s",
                        to="tap_grid.entity",
                    ),
                ),
            ],
            options={
                "db_table": "aws_core__aws_identity_center_instance",
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="AwsOrganization",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "batch_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="UUIDv7 of the batch this change was included in.",
                        max_length=36,
                    ),
                ),
                (
                    "flip_map",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="FLIP field-path-to-batch-id map: tracks which batch last set each provenance-tracked field.",
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=255)),
                (
                    "organization_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=64
                    ),
                ),
                ("root_id", models.CharField(blank=True, default="", max_length=64)),
                (
                    "management_account_id",
                    models.CharField(blank=True, default="", max_length=12),
                ),
                (
                    "feature_set",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                (
                    "partition",
                    models.CharField(blank=True, default="", max_length=16),
                ),
                (
                    "entity",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)s",
                        to="tap_grid.entity",
                    ),
                ),
            ],
            options={
                "db_table": "aws_core__aws_organization",
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="AwsOrganizationalUnit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "batch_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="UUIDv7 of the batch this change was included in.",
                        max_length=36,
                    ),
                ),
                (
                    "flip_map",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="FLIP field-path-to-batch-id map: tracks which batch last set each provenance-tracked field.",
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=255)),
                (
                    "ou_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=80
                    ),
                ),
                ("tags", models.JSONField(blank=True, default=dict)),
                (
                    "entity",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)s",
                        to="tap_grid.entity",
                    ),
                ),
            ],
            options={
                "db_table": "aws_core__aws_organizational_unit",
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="AwsServiceControlPolicy",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "batch_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="UUIDv7 of the batch this change was included in.",
                        max_length=36,
                    ),
                ),
                (
                    "flip_map",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="FLIP field-path-to-batch-id map: tracks which batch last set each provenance-tracked field.",
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=128)),
                (
                    "policy_arn",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=512
                    ),
                ),
                ("policy_id", models.CharField(blank=True, default="", max_length=130)),
                (
                    "description",
                    models.CharField(blank=True, default="", max_length=512),
                ),
                ("aws_managed", models.BooleanField(blank=True, default=None, null=True)),
                ("tags", models.JSONField(blank=True, default=dict)),
                (
                    "entity",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)s",
                        to="tap_grid.entity",
                    ),
                ),
            ],
            options={
                "db_table": "aws_core__aws_service_control_policy",
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="HistoricalAwsIdentityCenterInstance",
            fields=[
                (
                    "id",
                    models.BigIntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                (
                    "batch_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="UUIDv7 of the batch this change was included in.",
                        max_length=36,
                    ),
                ),
                (
                    "flip_map",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="FLIP field-path-to-batch-id map: tracks which batch last set each provenance-tracked field.",
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=255)),
                (
                    "instance_arn",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=1224
                    ),
                ),
                (
                    "identity_store_id",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                (
                    "owner_account_id",
                    models.CharField(blank=True, default="", max_length=12),
                ),
                (
                    "home_region",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                ("tags", models.JSONField(blank=True, default=dict)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "entity",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="tap_grid.entity",
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "historical aws identity center instance",
                "verbose_name_plural": "historical aws identity center instances",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="HistoricalAwsOrganization",
            fields=[
                (
                    "id",
                    models.BigIntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                (
                    "batch_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="UUIDv7 of the batch this change was included in.",
                        max_length=36,
                    ),
                ),
                (
                    "flip_map",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="FLIP field-path-to-batch-id map: tracks which batch last set each provenance-tracked field.",
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=255)),
                (
                    "organization_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=64
                    ),
                ),
                ("root_id", models.CharField(blank=True, default="", max_length=64)),
                (
                    "management_account_id",
                    models.CharField(blank=True, default="", max_length=12),
                ),
                (
                    "feature_set",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                (
                    "partition",
                    models.CharField(blank=True, default="", max_length=16),
                ),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "entity",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="tap_grid.entity",
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "historical aws organization",
                "verbose_name_plural": "historical aws organizations",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="HistoricalAwsOrganizationalUnit",
            fields=[
                (
                    "id",
                    models.BigIntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                (
                    "batch_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="UUIDv7 of the batch this change was included in.",
                        max_length=36,
                    ),
                ),
                (
                    "flip_map",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="FLIP field-path-to-batch-id map: tracks which batch last set each provenance-tracked field.",
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=255)),
                (
                    "ou_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=80
                    ),
                ),
                ("tags", models.JSONField(blank=True, default=dict)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "entity",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="tap_grid.entity",
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "historical aws organizational unit",
                "verbose_name_plural": "historical aws organizational units",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="HistoricalAwsServiceControlPolicy",
            fields=[
                (
                    "id",
                    models.BigIntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                (
                    "batch_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="UUIDv7 of the batch this change was included in.",
                        max_length=36,
                    ),
                ),
                (
                    "flip_map",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="FLIP field-path-to-batch-id map: tracks which batch last set each provenance-tracked field.",
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=128)),
                (
                    "policy_arn",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=512
                    ),
                ),
                ("policy_id", models.CharField(blank=True, default="", max_length=130)),
                (
                    "description",
                    models.CharField(blank=True, default="", max_length=512),
                ),
                ("aws_managed", models.BooleanField(blank=True, default=None, null=True)),
                ("tags", models.JSONField(blank=True, default=dict)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "entity",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="tap_grid.entity",
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "historical aws service control policy",
                "verbose_name_plural": "historical aws service control policys",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="HistoricalTransitGateway",
            fields=[
                (
                    "id",
                    models.BigIntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                (
                    "batch_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="UUIDv7 of the batch this change was included in.",
                        max_length=36,
                    ),
                ),
                (
                    "flip_map",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="FLIP field-path-to-batch-id map: tracks which batch last set each provenance-tracked field.",
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=255)),
                (
                    "transit_gateway_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=32
                    ),
                ),
                (
                    "owner_account_id",
                    models.CharField(blank=True, default="", max_length=12),
                ),
                ("region", models.CharField(blank=True, default="", max_length=32)),
                (
                    "amazon_side_asn",
                    models.BigIntegerField(blank=True, default=None, null=True),
                ),
                (
                    "auto_accept_shared_attachments",
                    models.BooleanField(blank=True, default=None, null=True),
                ),
                (
                    "default_route_table_association",
                    models.BooleanField(blank=True, default=None, null=True),
                ),
                (
                    "default_route_table_propagation",
                    models.BooleanField(blank=True, default=None, null=True),
                ),
                ("tags", models.JSONField(blank=True, default=dict)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "entity",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="tap_grid.entity",
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "historical transit gateway",
                "verbose_name_plural": "historical transit gateways",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="HistoricalTransitGatewayAttachment",
            fields=[
                (
                    "id",
                    models.BigIntegerField(
                        auto_created=True, blank=True, db_index=True, verbose_name="ID"
                    ),
                ),
                (
                    "batch_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="UUIDv7 of the batch this change was included in.",
                        max_length=36,
                    ),
                ),
                (
                    "flip_map",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="FLIP field-path-to-batch-id map: tracks which batch last set each provenance-tracked field.",
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=255)),
                (
                    "attachment_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=40
                    ),
                ),
                (
                    "resource_type",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                (
                    "resource_owner_account_id",
                    models.CharField(blank=True, default="", max_length=12),
                ),
                ("tags", models.JSONField(blank=True, default=dict)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "entity",
                    models.ForeignKey(
                        blank=True,
                        db_constraint=False,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="tap_grid.entity",
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "historical transit gateway attachment",
                "verbose_name_plural": "historical transit gateway attachments",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="TransitGateway",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "batch_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="UUIDv7 of the batch this change was included in.",
                        max_length=36,
                    ),
                ),
                (
                    "flip_map",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="FLIP field-path-to-batch-id map: tracks which batch last set each provenance-tracked field.",
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=255)),
                (
                    "transit_gateway_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=32
                    ),
                ),
                (
                    "owner_account_id",
                    models.CharField(blank=True, default="", max_length=12),
                ),
                ("region", models.CharField(blank=True, default="", max_length=32)),
                (
                    "amazon_side_asn",
                    models.BigIntegerField(blank=True, default=None, null=True),
                ),
                (
                    "auto_accept_shared_attachments",
                    models.BooleanField(blank=True, default=None, null=True),
                ),
                (
                    "default_route_table_association",
                    models.BooleanField(blank=True, default=None, null=True),
                ),
                (
                    "default_route_table_propagation",
                    models.BooleanField(blank=True, default=None, null=True),
                ),
                ("tags", models.JSONField(blank=True, default=dict)),
                (
                    "entity",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)s",
                        to="tap_grid.entity",
                    ),
                ),
            ],
            options={
                "db_table": "aws_core__aws_transit_gateway",
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="TransitGatewayAttachment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "batch_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="UUIDv7 of the batch this change was included in.",
                        max_length=36,
                    ),
                ),
                (
                    "flip_map",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="FLIP field-path-to-batch-id map: tracks which batch last set each provenance-tracked field.",
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=255)),
                (
                    "attachment_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=40
                    ),
                ),
                (
                    "resource_type",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                (
                    "resource_owner_account_id",
                    models.CharField(blank=True, default="", max_length=12),
                ),
                ("tags", models.JSONField(blank=True, default=dict)),
                (
                    "entity",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(class)s",
                        to="tap_grid.entity",
                    ),
                ),
            ],
            options={
                "db_table": "aws_core__aws_transit_gateway_attachment",
                "abstract": False,
            },
        ),
]),
    ]
