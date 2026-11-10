"""Re-key, in place, the types whose natural key could repeat across regions or accounts (issue 224).

Their keys were a bare name (``default.dax1.0``, which AWS creates in every region) or a composite of names
(``<log group>:<filter>``), so the same names in two regions were one identity: the batch kept the first and
dropped the rest as duplicates, and across runs the regions overwrote one another's row. The collector now keys
them ``<partition>:<account>:<region>:<rest>`` (req-aws-collector-identity-8).

A row already on the grid is re-keyed from its own ``aws_account`` and ``aws_region`` dimensions, so it keeps its
entity id, its edges and its history, and the next collection matches it instead of creating a new row and
retiring the old. A row without both dimensions, or whose old key does not have the shape expected for its type,
is left as it is and named in a warning: a key built from a guessed account or region would be worse than a row
the next run replaces. History rows are not rewritten; they record the key each version actually had.
"""

import logging
import re

from django.db import migrations

log = logging.getLogger(__name__)

#: model -> (key column, the shape the old key had). "plain": the old key is the rest as it was (a name or a
#: composite of names). "account_region": the old key led with ``<account>/<region>/``, which the prefix replaces.
REKEYED: dict[str, tuple[str, str]] = {
    "daxparametergroup": ("dax_parameter_group_id", "plain"),
    "daxsubnetgroup": ("dax_subnet_group_id", "plain"),
    "redshiftclustersecuritygroup": ("redshift_cluster_security_group_id", "plain"),
    "redshiftendpointaccess": ("redshift_endpoint_access_id", "plain"),
    "redshiftscheduledaction": ("redshift_scheduled_action_id", "plain"),
    "gluesecurityconfiguration": ("glue_security_configuration_name", "plain"),
    "lakeformationtag": ("lakeformation_tag_key", "plain"),
    "logsmetricfilter": ("filter_key", "plain"),
    "logssubscriptionfilter": ("filter_key", "plain"),
    "backuprestoretestingselection": ("backup_restore_testing_selection_key", "plain"),
    "ec2networkperformancemetricsubscription": ("ec2_network_performance_metric_subscription_key", "plain"),
    "lakeformationdatacellsfilter": ("lakeformation_data_cells_filter_key", "plain"),
    "autoscalingplansscalingplan": ("autoscalingplans_scaling_plan_id", "plain"),
    "appstreamdirectoryconfig": ("appstream_directory_config_key", "account_region"),
    "appstreamentitlement": ("appstream_entitlement_key", "account_region"),
    "autoscalinglifecyclehook": ("autoscaling_lifecycle_hook_key", "account_region"),
    "emrsecurityconfiguration": ("emr_security_configuration_key", "account_region"),
    "ecrrepositorycreationtemplate": ("ecr_repository_creation_template_key", "account_region"),
    "ekscertificateauthority": ("eks_certificate_authority_key", "account_region"),
    "fsxs3accesspointattachment": ("fsx_s3_access_point_attachment_key", "account_region"),
    "logsintegration": ("logs_integration_key", "account_region"),
    "opensearchserverlessaccesspolicy": ("opensearchserverless_access_policy_key", "account_region"),
    "opensearchserverlesslifecyclepolicy": ("opensearchserverless_lifecycle_policy_key", "account_region"),
    "opensearchserverlesssecuritypolicy": ("opensearchserverless_security_policy_key", "account_region"),
    "opensearchserverlesssecurityconfig": ("opensearchserverless_security_config_key", "account_region"),
    "sesreceiptfilter": ("ses_receipt_filter_key", "account_region"),
    "sesreceiptruleset": ("ses_receipt_rule_set_key", "account_region"),
    "cassandratype": ("cassandra_type_key", "account_region"),
}

# Frozen from collectors/boto3_collector/partition.py at this migration (botocore's regionRegex per partition), so
# a later change there cannot change what this migration did.
_REGION = re.compile(r"^[a-z]{2,3}(-[a-z]+)+-[0-9]+$")
_ACCOUNT = re.compile(r"^[0-9]{12}$")
_REGION_PARTITIONS = (
    ("aws-us-gov", re.compile(r"^us-gov-\w+-\d+$")),
    ("aws-cn", re.compile(r"^cn-\w+-\d+$")),
    ("aws-iso-b", re.compile(r"^us-isob-\w+-\d+$")),
    ("aws-iso-e", re.compile(r"^eu-isoe-\w+-\d+$")),
    ("aws-iso-f", re.compile(r"^us-isof-\w+-\d+$")),
    ("aws-iso", re.compile(r"^us-iso-\w+-\d+$")),
)


def _partition(region: str) -> str:
    return next((name for name, pattern in _REGION_PARTITIONS if pattern.match(region)), "aws")


def _scope(row) -> tuple[str, str, str] | None:
    """(partition, account, region) from the row's own dimensions, or None when they do not name both."""
    dims = row.entity.dimensions or {}
    account, region = dims.get("aws_account"), dims.get("aws_region")
    if not (isinstance(account, str) and _ACCOUNT.match(account) and isinstance(region, str) and _REGION.match(region)):
        return None
    return _partition(region), account, region


def new_key(old: str, shape: str, partition: str, account: str, region: str) -> str | None:
    """The scoped key for an old one, the old one when it is already scoped, None when its shape is unexpected."""
    prefix = f"{partition}:{account}:{region}:"
    if old.startswith(prefix):
        return old
    if shape == "account_region":
        lead = f"{account}/{region}/"
        return prefix + old[len(lead):] if old.startswith(lead) and len(old) > len(lead) else None
    return prefix + old if old else None


def old_key(new: str, shape: str, partition: str, account: str, region: str) -> str | None:
    """The inverse of :func:`new_key`, for the reverse migration."""
    prefix = f"{partition}:{account}:{region}:"
    if not new.startswith(prefix):
        return new
    rest = new[len(prefix):]
    return f"{account}/{region}/{rest}" if shape == "account_region" else rest


def _rewrite(apps, convert, direction: str) -> None:
    for model_name, (column, shape) in REKEYED.items():
        model = apps.get_model("aws_core", model_name)
        left: list[str] = []
        for row in model._default_manager.select_related("entity").iterator():
            old = getattr(row, column) or ""
            scope = _scope(row)
            key = convert(old, shape, *scope) if scope else None
            if key is None:
                left.append(str(row.pk))
            elif key != old:
                model._default_manager.filter(pk=row.pk).update(**{column: key})
        if left:
            log.warning(
                "aws_core 0053 (%s): %d %s row(s) kept their key, no account and region dimensions or an unexpected "
                "key shape: %s",
                direction,
                len(left),
                model_name,
                ", ".join(left),
            )


def scope_keys(apps, schema_editor):
    _rewrite(apps, new_key, "forward")


def unscope_keys(apps, schema_editor):
    _rewrite(apps, old_key, "reverse")


class Migration(migrations.Migration):

    dependencies = [
        ("aws_core", "0052_route53_record_set"),
    ]

    operations = [
        migrations.RunPython(scope_keys, unscope_keys),
    ]
