# Network-plane design vocabulary: Direct Connect, PrivateLink, Route 53 Resolver DNS Firewall and
# ACM Private CA (req-aws-core-direct-connect, -privatelink, -dns-firewall, -private-ca).
# Additive only: seven CreateModel pairs, nothing touching existing tables. tap_grid is pinned at
# the plugin's floor (0001_initial), as 0001-0003 and 0009 are.

import django.db.models.deletion
import simple_history.models
from django.conf import settings
from django.db import migrations, models
from tap_plugin.aws_core.migrations._bulk import BulkCreateModels


class Migration(migrations.Migration):

    dependencies = [
        ("aws_core", "0009_org_and_transit_gateway_vocabulary"),
        ("tap_grid", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        BulkCreateModels([
migrations.CreateModel(
            name="AcmPrivateCa",
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
                    "ca_arn",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=200
                    ),
                ),
                ("ca_type", models.CharField(blank=True, default="", max_length=16)),
                (
                    "key_algorithm",
                    models.CharField(blank=True, default="", max_length=16),
                ),
                ("status", models.CharField(blank=True, default="", max_length=24)),
                ("usage_mode", models.CharField(blank=True, default="", max_length=32)),
                (
                    "subject_common_name",
                    models.CharField(blank=True, default="", max_length=64),
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
                "db_table": "aws_core__aws_acm_private_ca",
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="DxConnection",
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
                    "connection_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=32
                    ),
                ),
                ("location", models.CharField(blank=True, default="", max_length=64)),
                ("bandwidth", models.CharField(blank=True, default="", max_length=16)),
                ("is_hosted", models.BooleanField(blank=True, default=None, null=True)),
                ("region", models.CharField(blank=True, default="", max_length=32)),
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
                "db_table": "aws_core__aws_dx_connection",
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="DxGateway",
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
                    "direct_connect_gateway_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=36
                    ),
                ),
                (
                    "amazon_side_asn",
                    models.BigIntegerField(blank=True, default=None, null=True),
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
                "db_table": "aws_core__aws_dx_gateway",
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="DxVirtualInterface",
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
                    "virtual_interface_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=32
                    ),
                ),
                (
                    "virtual_interface_type",
                    models.CharField(blank=True, default="", max_length=16),
                ),
                ("vlan", models.IntegerField(blank=True, default=None, null=True)),
                (
                    "customer_asn",
                    models.BigIntegerField(blank=True, default=None, null=True),
                ),
                ("region", models.CharField(blank=True, default="", max_length=32)),
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
                "db_table": "aws_core__aws_dx_virtual_interface",
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="HistoricalAcmPrivateCa",
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
                    "ca_arn",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=200
                    ),
                ),
                ("ca_type", models.CharField(blank=True, default="", max_length=16)),
                (
                    "key_algorithm",
                    models.CharField(blank=True, default="", max_length=16),
                ),
                ("status", models.CharField(blank=True, default="", max_length=24)),
                ("usage_mode", models.CharField(blank=True, default="", max_length=32)),
                (
                    "subject_common_name",
                    models.CharField(blank=True, default="", max_length=64),
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
                "verbose_name": "historical acm private ca",
                "verbose_name_plural": "historical acm private cas",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="HistoricalDxConnection",
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
                    "connection_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=32
                    ),
                ),
                ("location", models.CharField(blank=True, default="", max_length=64)),
                ("bandwidth", models.CharField(blank=True, default="", max_length=16)),
                ("is_hosted", models.BooleanField(blank=True, default=None, null=True)),
                ("region", models.CharField(blank=True, default="", max_length=32)),
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
                "verbose_name": "historical dx connection",
                "verbose_name_plural": "historical dx connections",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="HistoricalDxGateway",
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
                    "direct_connect_gateway_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=36
                    ),
                ),
                (
                    "amazon_side_asn",
                    models.BigIntegerField(blank=True, default=None, null=True),
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
                "verbose_name": "historical dx gateway",
                "verbose_name_plural": "historical dx gateways",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="HistoricalDxVirtualInterface",
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
                    "virtual_interface_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=32
                    ),
                ),
                (
                    "virtual_interface_type",
                    models.CharField(blank=True, default="", max_length=16),
                ),
                ("vlan", models.IntegerField(blank=True, default=None, null=True)),
                (
                    "customer_asn",
                    models.BigIntegerField(blank=True, default=None, null=True),
                ),
                ("region", models.CharField(blank=True, default="", max_length=32)),
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
                "verbose_name": "historical dx virtual interface",
                "verbose_name_plural": "historical dx virtual interfaces",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="HistoricalRoute53ResolverFirewallRuleGroup",
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
                ("name", models.CharField(blank=True, default="", max_length=64)),
                (
                    "rule_group_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=64
                    ),
                ),
                (
                    "rule_count",
                    models.IntegerField(blank=True, default=None, null=True),
                ),
                ("block_domain_lists", models.JSONField(blank=True, default=list)),
                ("allow_domain_lists", models.JSONField(blank=True, default=list)),
                ("alert_domain_lists", models.JSONField(blank=True, default=list)),
                ("region", models.CharField(blank=True, default="", max_length=32)),
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
                "verbose_name": "historical route53 resolver firewall rule group",
                "verbose_name_plural": "historical route53 resolver firewall rule groups",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="HistoricalVpcEndpoint",
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
                    "vpc_endpoint_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=32
                    ),
                ),
                (
                    "endpoint_type",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                (
                    "service_name",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "private_dns_enabled",
                    models.BooleanField(blank=True, default=None, null=True),
                ),
                ("region", models.CharField(blank=True, default="", max_length=32)),
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
                "verbose_name": "historical vpc endpoint",
                "verbose_name_plural": "historical vpc endpoints",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="HistoricalVpcEndpointService",
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
                    "service_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=32
                    ),
                ),
                (
                    "service_name",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "acceptance_required",
                    models.BooleanField(blank=True, default=None, null=True),
                ),
                (
                    "private_dns_name",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("region", models.CharField(blank=True, default="", max_length=32)),
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
                "verbose_name": "historical vpc endpoint service",
                "verbose_name_plural": "historical vpc endpoint services",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="Route53ResolverFirewallRuleGroup",
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
                ("name", models.CharField(blank=True, default="", max_length=64)),
                (
                    "rule_group_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=64
                    ),
                ),
                (
                    "rule_count",
                    models.IntegerField(blank=True, default=None, null=True),
                ),
                ("block_domain_lists", models.JSONField(blank=True, default=list)),
                ("allow_domain_lists", models.JSONField(blank=True, default=list)),
                ("alert_domain_lists", models.JSONField(blank=True, default=list)),
                ("region", models.CharField(blank=True, default="", max_length=32)),
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
                "db_table": "aws_core__aws_route53_resolver_firewall_rule_group",
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="VpcEndpoint",
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
                    "vpc_endpoint_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=32
                    ),
                ),
                (
                    "endpoint_type",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                (
                    "service_name",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "private_dns_enabled",
                    models.BooleanField(blank=True, default=None, null=True),
                ),
                ("region", models.CharField(blank=True, default="", max_length=32)),
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
                "db_table": "aws_core__aws_vpc_endpoint",
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="VpcEndpointService",
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
                    "service_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=32
                    ),
                ),
                (
                    "service_name",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "acceptance_required",
                    models.BooleanField(blank=True, default=None, null=True),
                ),
                (
                    "private_dns_name",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("region", models.CharField(blank=True, default="", max_length=32)),
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
                "db_table": "aws_core__aws_vpc_endpoint_service",
                "abstract": False,
            },
        ),
]),
    ]
