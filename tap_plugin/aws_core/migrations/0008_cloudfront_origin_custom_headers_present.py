# Ruling 2026-09-24 Q46: whether each CloudFront origin is sent a custom
# header, presence only. Additive only; NULL until the distribution is next
# collected.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("aws_core", "0007_offtype_security_facts"),
    ]

    operations = [
        migrations.AddField(
            model_name="cloudfrontdistribution",
            name="origin_custom_headers_present",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="historicalcloudfrontdistribution",
            name="origin_custom_headers_present",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
