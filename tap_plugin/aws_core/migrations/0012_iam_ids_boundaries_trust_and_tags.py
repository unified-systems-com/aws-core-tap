# Generated for aws-core-tap#43: IamRole/IamUser/IamPolicy identity + posture fields, plus the
# canonical tags field on IamUser/IamPolicy (req-aws-core-fields-4; both were manifest-collected
# but had not carried it).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aws_core', '0011_natural_keys_and_null_defaults'),
    ]

    operations = [
        migrations.AddField(
            model_name='iamrole',
            name='role_id',
            field=models.CharField(blank=True, db_index=True, default=None, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='historicaliamrole',
            name='role_id',
            field=models.CharField(blank=True, db_index=True, default=None, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='iamrole',
            name='permissions_boundary_arn',
            field=models.CharField(blank=True, default=None, max_length=512, null=True),
        ),
        migrations.AddField(
            model_name='historicaliamrole',
            name='permissions_boundary_arn',
            field=models.CharField(blank=True, default=None, max_length=512, null=True),
        ),
        migrations.AddField(
            model_name='iamrole',
            name='last_used_at',
            field=models.CharField(blank=True, default=None, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name='historicaliamrole',
            name='last_used_at',
            field=models.CharField(blank=True, default=None, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name='iamrole',
            name='attached_policy_arns',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='historicaliamrole',
            name='attached_policy_arns',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='iamrole',
            name='trusted_account_ids',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='historicaliamrole',
            name='trusted_account_ids',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='iamrole',
            name='trusted_services',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='historicaliamrole',
            name='trusted_services',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='iamrole',
            name='trusts_wildcard_principal',
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='historicaliamrole',
            name='trusts_wildcard_principal',
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
        migrations.AlterField(
            model_name='iamuser',
            name='mfa_enabled',
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
        migrations.AlterField(
            model_name='historicaliamuser',
            name='mfa_enabled',
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='iamuser',
            name='user_id',
            field=models.CharField(blank=True, db_index=True, default=None, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='historicaliamuser',
            name='user_id',
            field=models.CharField(blank=True, db_index=True, default=None, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='iamuser',
            name='permissions_boundary_arn',
            field=models.CharField(blank=True, default=None, max_length=512, null=True),
        ),
        migrations.AddField(
            model_name='historicaliamuser',
            name='permissions_boundary_arn',
            field=models.CharField(blank=True, default=None, max_length=512, null=True),
        ),
        migrations.AddField(
            model_name='iamuser',
            name='password_last_used',
            field=models.CharField(blank=True, default=None, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name='historicaliamuser',
            name='password_last_used',
            field=models.CharField(blank=True, default=None, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name='iamuser',
            name='attached_policy_arns',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='historicaliamuser',
            name='attached_policy_arns',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='iamuser',
            name='tags',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='historicaliamuser',
            name='tags',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='iampolicy',
            name='policy_id',
            field=models.CharField(blank=True, db_index=True, default=None, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='historicaliampolicy',
            name='policy_id',
            field=models.CharField(blank=True, db_index=True, default=None, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='iampolicy',
            name='default_version_id',
            field=models.CharField(blank=True, default=None, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name='historicaliampolicy',
            name='default_version_id',
            field=models.CharField(blank=True, default=None, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name='iampolicy',
            name='attachment_count',
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='historicaliampolicy',
            name='attachment_count',
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='iampolicy',
            name='is_attachable',
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='historicaliampolicy',
            name='is_attachable',
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
        migrations.AddField(
            model_name='iampolicy',
            name='tags',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='historicaliampolicy',
            name='tags',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
