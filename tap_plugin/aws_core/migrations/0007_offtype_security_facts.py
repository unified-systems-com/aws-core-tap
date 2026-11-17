# Ruling 2026-09-23 Q44: typed fields for the security facts that the
# persist_configuration: false types would otherwise lose. Additive only.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("aws_core", "0006_elb_lb_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="apigatewayhttpapi",
            name="route_authorization_types",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="historicalapigatewayhttpapi",
            name="route_authorization_types",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name="cloudfrontdistribution",
            name="origin_access",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="historicalcloudfrontdistribution",
            name="origin_access",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="lambdafunction",
            name="vpc_security_group_ids",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="historicallambdafunction",
            name="vpc_security_group_ids",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="lambdafunction",
            name="vpc_subnet_ids",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="historicallambdafunction",
            name="vpc_subnet_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
