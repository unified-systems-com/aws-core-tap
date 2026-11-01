# CodePipeline pipeline and CodeBuild project design vocabulary (req-aws-core-codepipeline, req-aws-core-codebuild).
# Additive only: two CreateModel pairs, nothing touching existing tables. tap_grid is pinned at 0005, the
# floor this migration chain already needs (0017).

import django.db.models.deletion
import simple_history.models
from django.conf import settings
from django.db import migrations, models
from tap_plugin.aws_core.migrations._bulk import BulkCreateModels


class Migration(migrations.Migration):
    dependencies = [
        ("aws_core", "0017_security_findings"),
        ("tap_grid", "0005_entity_natural_key_clear"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        BulkCreateModels([
migrations.CreateModel(
            name="CodebuildProject",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
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
                ("project_arn", models.CharField(blank=True, db_index=True, default="", max_length=300)),
                ("environment_image", models.CharField(blank=True, default="", max_length=255)),
                ("compute_type", models.CharField(blank=True, default="", max_length=64)),
                ("source_type", models.CharField(blank=True, default="", max_length=32)),
                ("vpc_attached", models.BooleanField(blank=True, default=None, null=True)),
                ("region", models.CharField(blank=True, default="", max_length=32)),
                ("tags", models.JSONField(blank=True, default=dict)),
                (
                    "entity",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE, related_name="%(class)s", to="tap_grid.entity"
                    ),
                ),
            ],
            options={
                "db_table": "aws_core__aws_codebuild_project",
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="CodepipelinePipeline",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
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
                ("name", models.CharField(blank=True, default="", max_length=100)),
                ("pipeline_arn", models.CharField(blank=True, db_index=True, default="", max_length=300)),
                ("stage_names", models.JSONField(blank=True, default=list)),
                ("pipeline_type", models.CharField(blank=True, default="", max_length=2)),
                ("execution_mode", models.CharField(blank=True, default="", max_length=16)),
                ("region", models.CharField(blank=True, default="", max_length=32)),
                ("tags", models.JSONField(blank=True, default=dict)),
                (
                    "entity",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE, related_name="%(class)s", to="tap_grid.entity"
                    ),
                ),
            ],
            options={
                "db_table": "aws_core__aws_codepipeline_pipeline",
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="HistoricalCodebuildProject",
            fields=[
                ("id", models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name="ID")),
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
                ("project_arn", models.CharField(blank=True, db_index=True, default="", max_length=300)),
                ("environment_image", models.CharField(blank=True, default="", max_length=255)),
                ("compute_type", models.CharField(blank=True, default="", max_length=64)),
                ("source_type", models.CharField(blank=True, default="", max_length=32)),
                ("vpc_attached", models.BooleanField(blank=True, default=None, null=True)),
                ("region", models.CharField(blank=True, default="", max_length=32)),
                ("tags", models.JSONField(blank=True, default=dict)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")], max_length=1),
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
                "verbose_name": "historical codebuild project",
                "verbose_name_plural": "historical codebuild projects",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="HistoricalCodepipelinePipeline",
            fields=[
                ("id", models.BigIntegerField(auto_created=True, blank=True, db_index=True, verbose_name="ID")),
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
                ("name", models.CharField(blank=True, default="", max_length=100)),
                ("pipeline_arn", models.CharField(blank=True, db_index=True, default="", max_length=300)),
                ("stage_names", models.JSONField(blank=True, default=list)),
                ("pipeline_type", models.CharField(blank=True, default="", max_length=2)),
                ("execution_mode", models.CharField(blank=True, default="", max_length=16)),
                ("region", models.CharField(blank=True, default="", max_length=32)),
                ("tags", models.JSONField(blank=True, default=dict)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")], max_length=1),
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
                "verbose_name": "historical codepipeline pipeline",
                "verbose_name_plural": "historical codepipeline pipelines",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
]),
    ]
