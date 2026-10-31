"""Registered ``custom_fn`` readers for types whose list call does not carry the object's ARN.

Spec: specs/spec-aws-core-collector-v0.md (``req-aws-collector-source-4``: multi-call assembly of one
logical resource lives only in a ``custom_fn``). Each reader here does one of three things, and nothing
else: list the names and describe each one (the describe answer carries the ARN), build the ARN from a
format the service's own botocore documentation states, or unwrap a record the list call nests.

A reader that lists something it cannot then describe yields the rest and raises
:func:`..customfns._undescribed` once, so the engine reports ``ENTRY_SKIPPED`` and keeps what it has: a
failed description is a loud gap in the run, never a quietly smaller inventory.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from .customfns import _account_id, _client_region, _pages, _undescribed
from .envelope import without_response_metadata
from .partition import build_arn, partition_of_region
from .source import SourceError

# The most repository names one BatchGetRepositories call is asked for (the CodeCommit API accepts 25).
_CODECOMMIT_BATCH = 25

# The ResourceType values rbin ListRules accepts (botocore 1.43.121 rbin ResourceType enum): the call
# requires one, so the reader asks once per type.
_RBIN_RESOURCE_TYPES = ("EBS_SNAPSHOT", "EC2_IMAGE", "EBS_VOLUME")


def _arn_context(client_for: Any, client: Any) -> tuple[str, str, str]:
    """``(partition, region, account)`` for building an ARN of the client's own region.

    An empty account would build an ARN no other node shares, so a run that cannot learn it fails the
    listing (``SourceError``) instead of keying objects by a hole.
    """
    account = _account_id(client_for)
    if not account:
        raise SourceError("the caller's account id could not be read (sts:GetCallerIdentity), so ARNs cannot be built")
    region = _client_region(client)
    return partition_of_region(region), region, account


def _list_then_get(
    client_for: Any,
    service: str,
    list_method: str,
    list_key: str,
    id_key: str | None,
    get_method: str,
    get_param: str,
    kind: str,
    *,
    arn_key: str,
    add: Callable[[str], dict[str, Any]] | None = None,
) -> Iterator[dict[str, Any]]:
    """Each object the list call names, described by the get call that returns its ARN.

    ``id_key`` is the member of a list entry that names the object (``None`` when the entries are bare
    strings). An object whose description fails, or answers without ``arn_key``, has no ARN to key it by:
    it is left out and the reader raises once the rest have been yielded.
    """
    client = client_for(service)
    failed: list[str] = []
    for page in _pages(client, list_method):
        for entry in page.get(list_key) or []:
            ident = entry.get(id_key) if id_key and isinstance(entry, dict) else entry
            if not ident or not isinstance(ident, str):
                continue
            try:
                described = without_response_metadata(getattr(client, get_method)(**{get_param: ident}))
            except BotoCoreError, ClientError:
                failed.append(ident)
                continue
            if isinstance(described, dict) and described.get(arn_key):
                yield {**described, **(add(ident) if add else {})}
            else:
                failed.append(ident)
    if failed:
        raise _undescribed(kind, failed)


def opensearch_domains_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate OpenSearch Service domains (regional): ``ListDomainNames`` (filtered to the OpenSearch
    engine, so Elasticsearch domains stay with ``elasticsearch_domains_described``) names them and
    ``DescribeDomain`` returns each ``DomainStatus``, which carries the ARN.

    A domain that is listed but cannot be described has no ARN to key it by: it is left out of the batch and
    the reader raises once it has yielded the rest (:func:`..customfns._undescribed`).
    """
    client = client_for("opensearch")
    listed = without_response_metadata(client.list_domain_names(EngineType="OpenSearch")).get("DomainNames") or []
    failed: list[str] = []
    for entry in listed:
        name = entry.get("DomainName") if isinstance(entry, dict) else None
        if not name:
            continue
        try:
            status = without_response_metadata(client.describe_domain(DomainName=name)).get("DomainStatus")
        except BotoCoreError, ClientError:
            failed.append(name)
            continue
        if isinstance(status, dict) and status.get("ARN"):
            yield status
        else:
            failed.append(name)
    if failed:
        raise _undescribed("OpenSearch domains", failed)


def redshift_clusters_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Redshift clusters (regional). ``DescribeClusters`` carries the tags and no ARN, so each
    cluster gets ``_arn``: ``arn:<partition>:redshift:<region>:<account>:cluster:<identifier>``, the format
    the redshift ``DescribeTags`` ``ResourceName`` documentation gives (``arn:aws:redshift:us-east-2:123456789:cluster:t1``)."""
    client = client_for("redshift")
    partition, region, account = _arn_context(client_for, client)
    for page in _pages(client, "describe_clusters"):
        for cluster in page.get("Clusters") or []:
            identifier = cluster.get("ClusterIdentifier")
            if identifier:
                yield {**cluster, "_arn": build_arn(partition, "redshift", region, account, f"cluster:{identifier}")}


def synthetics_canaries_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CloudWatch Synthetics canaries (regional). ``DescribeCanaries`` carries the tags and no ARN,
    so each canary gets ``_arn``: ``arn:<partition>:synthetics:<region>:<account>:canary:<name>``, the format the
    synthetics ``ListTagsForResource`` documentation states for a canary."""
    client = client_for("synthetics")
    partition, region, account = _arn_context(client_for, client)
    for page in _pages(client, "describe_canaries"):
        for canary in page.get("Canaries") or []:
            name = canary.get("Name")
            if name:
                yield {**canary, "_arn": build_arn(partition, "synthetics", region, account, f"canary:{name}")}


def codecommit_repositories_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate CodeCommit repositories (regional): ``ListRepositories`` names them and ``BatchGetRepositories``
    returns each ``repositoryMetadata`` (the ARN, the clone URLs, the KMS key id). A repository named but not
    returned is a gap (:func:`..customfns._undescribed`)."""
    client = client_for("codecommit")
    names = [
        pair["repositoryName"]
        for page in _pages(client, "list_repositories")
        for pair in page.get("repositories") or []
        if pair.get("repositoryName")
    ]
    failed: list[str] = []
    for start in range(0, len(names), _CODECOMMIT_BATCH):
        batch = names[start : start + _CODECOMMIT_BATCH]
        try:
            answer = without_response_metadata(client.batch_get_repositories(repositoryNames=batch))
        except BotoCoreError, ClientError:
            failed.extend(batch)
            continue
        got = set()
        for repository in answer.get("repositories") or []:
            if isinstance(repository, dict) and repository.get("Arn"):
                got.add(repository.get("repositoryName"))
                yield repository
        failed.extend(name for name in batch if name not in got)
    if failed:
        raise _undescribed("CodeCommit repositories", failed)


def rekognition_collections_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Rekognition collections (regional): ``ListCollections`` returns bare ids and
    ``DescribeCollection`` returns each ``CollectionARN``; ``CollectionId`` is added from the listing."""
    yield from _list_then_get(
        client_for,
        "rekognition",
        "list_collections",
        "CollectionIds",
        None,
        "describe_collection",
        "CollectionId",
        "Rekognition collections",
        arn_key="CollectionARN",
        add=lambda ident: {"CollectionId": ident},
    )


def rekognition_stream_processors_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Rekognition stream processors (regional): ``ListStreamProcessors`` names them and
    ``DescribeStreamProcessor`` returns each ``StreamProcessorArn``."""
    yield from _list_then_get(
        client_for,
        "rekognition",
        "list_stream_processors",
        "StreamProcessors",
        "Name",
        "describe_stream_processor",
        "Name",
        "Rekognition stream processors",
        arn_key="StreamProcessorArn",
    )


def mailmanager_archives_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate SES Mail Manager archives (regional): ``ListArchives`` names them, ``GetArchive`` returns the ARN."""
    yield from _list_then_get(
        client_for, "mailmanager", "list_archives", "Archives", "ArchiveId", "get_archive", "ArchiveId",
        "Mail Manager archives", arn_key="ArchiveArn",
    )


def mailmanager_ingress_points_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate SES Mail Manager ingress points (regional): ``ListIngressPoints`` names them, ``GetIngressPoint`` returns the ARN."""
    yield from _list_then_get(
        client_for, "mailmanager", "list_ingress_points", "IngressPoints", "IngressPointId", "get_ingress_point",
        "IngressPointId", "Mail Manager ingress points", arn_key="IngressPointArn",
    )


def mailmanager_relays_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate SES Mail Manager relays (regional): ``ListRelays`` names them, ``GetRelay`` returns the ARN."""
    yield from _list_then_get(
        client_for, "mailmanager", "list_relays", "Relays", "RelayId", "get_relay", "RelayId",
        "Mail Manager relays", arn_key="RelayArn",
    )


def mailmanager_rule_sets_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate SES Mail Manager rule sets (regional): ``ListRuleSets`` names them, ``GetRuleSet`` returns the ARN."""
    yield from _list_then_get(
        client_for, "mailmanager", "list_rule_sets", "RuleSets", "RuleSetId", "get_rule_set", "RuleSetId",
        "Mail Manager rule sets", arn_key="RuleSetArn",
    )


def mailmanager_traffic_policies_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate SES Mail Manager traffic policies (regional): ``ListTrafficPolicies`` names them, ``GetTrafficPolicy`` returns the ARN."""
    yield from _list_then_get(
        client_for, "mailmanager", "list_traffic_policies", "TrafficPolicies", "TrafficPolicyId", "get_traffic_policy",
        "TrafficPolicyId", "Mail Manager traffic policies", arn_key="TrafficPolicyArn",
    )


def appconfig_extension_associations_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate AppConfig extension associations (regional): ``ListExtensionAssociations`` names them and
    ``GetExtensionAssociation`` returns each ``Arn`` (the summary carries only the id and the two ends)."""
    yield from _list_then_get(
        client_for, "appconfig", "list_extension_associations", "Items", "Id", "get_extension_association",
        "ExtensionAssociationId", "AppConfig extension associations", arn_key="Arn",
    )


def rbin_rules_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate Recycle Bin retention rules (regional). ``ListRules`` requires a ``ResourceType``, so it is asked
    once for each type the service defines; ``ResourceType`` is added to every rule."""
    client = client_for("rbin")
    for resource_type in _RBIN_RESOURCE_TYPES:
        for page in _pages(client, "list_rules", ResourceType=resource_type):
            for rule in page.get("Rules") or []:
                if rule.get("RuleArn"):
                    yield {**rule, "ResourceType": resource_type}


def xray_sampling_rules_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """Enumerate X-Ray sampling rules (regional). ``GetSamplingRules`` nests each rule in a record beside its
    ``CreatedAt`` and ``ModifiedAt``; the rule is yielded with those two beside it."""
    client = client_for("xray")
    for page in _pages(client, "get_sampling_rules"):
        for record in page.get("SamplingRuleRecords") or []:
            rule = record.get("SamplingRule") if isinstance(record, dict) else None
            if isinstance(rule, dict) and rule.get("RuleARN"):
                yield {**rule, "CreatedAt": record.get("CreatedAt"), "ModifiedAt": record.get("ModifiedAt")}


def securityhub_hub_v2_described(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
    """The Security Hub V2 service resource of the account and region (at most one): ``DescribeSecurityHubV2``
    returns its ARN. A region where it is not enabled raises, and the engine reports the entry as skipped."""
    client = client_for("securityhub")
    hub = without_response_metadata(client.describe_security_hub_v2())
    if hub.get("HubV2Arn"):
        yield hub


def _arn_listing(
    client_for: Any,
    service: str,
    list_method: str,
    list_key: str,
    resource: str,
    *,
    arn_service: str | None = None,
    key: str | None = None,
    parent: tuple[str, str, str, str] | None = None,
    parent_fields: dict[str, str] | None = None,
    account_key: str | None = None,
    label: str = "objects",
    **kwargs: Any,
) -> Iterator[dict[str, Any]]:
    """The items of a list call that carries an id or name and no ARN; each gets ``_arn``.

    ``resource`` is the resource part of the ARN as the AWS Service Authorization Reference states it for
    the type (``application/{Id}``), filled from the item; the partition and region come from the client, and
    the account from ``sts:GetCallerIdentity`` or, when the item carries its owner (``account_key``), from the
    item. ``key`` wraps a list of bare strings as ``{key: string}``. ``parent`` is ``(list_method, list_key,
    id_member, request_param)``: the list call is asked once per parent, ``parent_fields`` copies parent
    members onto each child (``{item_name: parent_member}``), and a parent whose children cannot be read is
    a gap raised after the rest are yielded (:func:`..customfns._undescribed`).
    """
    client = client_for(service)
    region = _client_region(client)
    partition = partition_of_region(region)
    arn_service = arn_service or service
    account = "" if account_key else _arn_context(client_for, client)[2]
    parents: list[dict[str, Any] | None] = [None]
    if parent:
        parents = [p for page in _pages(client, parent[0]) for p in page.get(parent[1]) or [] if isinstance(p, dict) and p.get(parent[2])]
    failed: list[str] = []
    for owner in parents:
        request = dict(kwargs)
        extra: dict[str, Any] = {}
        if owner is not None and parent:
            request[parent[3]] = owner[parent[2]]
            extra = {name: owner.get(member) for name, member in (parent_fields or {}).items()}
        try:
            entries = [entry for page in _pages(client, list_method, **request) for entry in page.get(list_key) or []]
        except BotoCoreError, ClientError:
            failed.append(str(owner[parent[2]]) if owner is not None and parent else list_method)
            continue
        for entry in entries:
            item = {key: entry} if key and isinstance(entry, str) else dict(entry) if isinstance(entry, dict) else None
            if item is None:
                continue
            item.update(extra)
            holder = str(item.get(account_key) or "") if account_key else account
            try:
                rid = resource.format(**item)
            except KeyError, IndexError:
                continue
            if holder:
                yield {**item, "_arn": build_arn(partition, arn_service, region, holder, rid)}
    if failed:
        raise _undescribed(label, failed)


def _reader(name: str, doc: str, **spec: Any) -> Any:
    """A registered reader over :func:`_arn_listing` with the given arguments."""

    def read(session: Any, *, client_for: Any) -> Iterator[dict[str, Any]]:
        yield from _arn_listing(client_for, **spec)

    read.__name__ = name
    read.__doc__ = doc
    return read


_APPCONFIG_APPS = ("list_applications", "Items", "Id", "ApplicationId")
_LEX_BOTS = ("list_bots", "botSummaries", "botId", "botId")

# The ARN resource part of each type is the one the AWS Service Authorization Reference gives
# (servicereference.us-east-1.amazonaws.com/v1/<service>/<service>.json, read 2026-10-31); the Steampipe
# aws plugin builds the same ARNs the same way (table_aws_appconfig_application.go, table_aws_redshift_subnet_group.go).
_ARN_READERS = (
    _reader("appconfig_applications_described", "AppConfig applications (regional).",
            service="appconfig", list_method="list_applications", list_key="Items", resource="application/{Id}", label="AppConfig applications"),
    _reader("appconfig_deployment_strategies_described", "AppConfig deployment strategies (regional): the account's and the predefined ones the call also returns.",
            service="appconfig", list_method="list_deployment_strategies", list_key="Items", resource="deploymentstrategy/{Id}", label="AppConfig deployment strategies"),
    _reader("appconfig_environments_described", "AppConfig environments (regional), asked once per application.",
            service="appconfig", list_method="list_environments", list_key="Items", parent=_APPCONFIG_APPS,
            resource="application/{ApplicationId}/environment/{Id}", label="AppConfig applications whose environments"),
    _reader("appconfig_configuration_profiles_described", "AppConfig configuration profiles (regional), asked once per application.",
            service="appconfig", list_method="list_configuration_profiles", list_key="Items", parent=_APPCONFIG_APPS,
            resource="application/{ApplicationId}/configurationprofile/{Id}", label="AppConfig applications whose configuration profiles"),
    _reader("appconfig_experiment_definitions_described", "AppConfig experiment definitions (regional).",
            service="appconfig", list_method="list_experiment_definitions", list_key="Items",
            resource="application/{ApplicationId}/experimentdefinition/{Id}", label="AppConfig experiment definitions"),
    _reader("redshift_subnet_groups_described", "Redshift cluster subnet groups (regional).",
            service="redshift", list_method="describe_cluster_subnet_groups", list_key="ClusterSubnetGroups",
            resource="subnetgroup:{ClusterSubnetGroupName}", label="Redshift subnet groups"),
    _reader("redshift_parameter_groups_described", "Redshift cluster parameter groups (regional): the account's and the default ones.",
            service="redshift", list_method="describe_cluster_parameter_groups", list_key="ParameterGroups",
            resource="parametergroup:{ParameterGroupName}", label="Redshift parameter groups"),
    _reader("redshift_event_subscriptions_described", "Redshift event subscriptions (regional).",
            service="redshift", list_method="describe_event_subscriptions", list_key="EventSubscriptionsList",
            resource="eventsubscription:{CustSubscriptionId}", label="Redshift event subscriptions"),
    _reader("redshift_snapshot_schedules_described", "Redshift snapshot schedules (regional).",
            service="redshift", list_method="describe_snapshot_schedules", list_key="SnapshotSchedules",
            resource="snapshotschedule:{ScheduleIdentifier}", label="Redshift snapshot schedules"),
    _reader("redshift_snapshot_copy_grants_described", "Redshift snapshot copy grants (regional).",
            service="redshift", list_method="describe_snapshot_copy_grants", list_key="SnapshotCopyGrants",
            resource="snapshotcopygrant:{SnapshotCopyGrantName}", label="Redshift snapshot copy grants"),
    _reader("redshift_usage_limits_described", "Redshift usage limits (regional).",
            service="redshift", list_method="describe_usage_limits", list_key="UsageLimits",
            resource="usagelimit:{UsageLimitId}", label="Redshift usage limits"),
    _reader("redshift_cluster_snapshots_described", "Redshift cluster snapshots (regional), automated and manual.",
            service="redshift", list_method="describe_cluster_snapshots", list_key="Snapshots",
            resource="snapshot:{ClusterIdentifier}/{SnapshotIdentifier}", label="Redshift snapshots"),
    _reader("ses_configuration_sets_described", "SES configuration sets (regional); the list returns bare names.",
            service="sesv2", arn_service="ses", list_method="list_configuration_sets", list_key="ConfigurationSets", key="ConfigurationSetName",
            resource="configuration-set/{ConfigurationSetName}", label="SES configuration sets"),
    _reader("ses_contact_lists_described", "SES contact lists (regional).",
            service="sesv2", arn_service="ses", list_method="list_contact_lists", list_key="ContactLists",
            resource="contact-list/{ContactListName}", label="SES contact lists"),
    _reader("ses_custom_verification_email_templates_described", "SES custom verification email templates (regional).",
            service="sesv2", arn_service="ses", list_method="list_custom_verification_email_templates", list_key="CustomVerificationEmailTemplates",
            resource="custom-verification-email-template/{TemplateName}", label="SES custom verification email templates"),
    _reader("ses_dedicated_ip_pools_described", "SES dedicated IP pools (regional); the list returns bare names.",
            service="sesv2", arn_service="ses", list_method="list_dedicated_ip_pools", list_key="DedicatedIpPools", key="PoolName",
            resource="dedicated-ip-pool/{PoolName}", label="SES dedicated IP pools"),
    _reader("ses_email_identities_described", "SES email identities (regional): domains and addresses.",
            service="sesv2", arn_service="ses", list_method="list_email_identities", list_key="EmailIdentities",
            resource="identity/{IdentityName}", label="SES email identities"),
    _reader("ses_templates_described", "SES email templates (regional).",
            service="sesv2", arn_service="ses", list_method="list_email_templates", list_key="TemplatesMetadata",
            resource="template/{TemplateName}", label="SES templates"),
    _reader("ses_multi_region_endpoints_described", "SES multi-region endpoints (regional).",
            service="sesv2", arn_service="ses", list_method="list_multi_region_endpoints", list_key="MultiRegionEndpoints",
            resource="multi-region-endpoint/{EndpointName}", label="SES multi-region endpoints"),
    _reader("lex_bots_described", "Lex V2 bots (regional).",
            service="lexv2-models", arn_service="lex", list_method="list_bots", list_key="botSummaries",
            resource="bot/{botId}", label="Lex bots"),
    _reader("lex_bot_aliases_described", "Lex V2 bot aliases (regional), asked once per bot; botId is copied from the bot.",
            service="lexv2-models", arn_service="lex", list_method="list_bot_aliases", list_key="botAliasSummaries", parent=_LEX_BOTS,
            parent_fields={"botId": "botId"}, resource="bot-alias/{botId}/{botAliasId}", label="Lex bots whose aliases"),
    _reader("directconnect_lags_described", "Direct Connect link aggregation groups (regional); the owner account comes from the item.",
            service="directconnect", list_method="describe_lags", list_key="lags", account_key="ownerAccount",
            resource="dxlag/{lagId}", label="Direct Connect LAGs"),
    _reader("cloudwatch_insight_rules_described", "CloudWatch Contributor Insights rules (regional).",
            service="cloudwatch", list_method="describe_insight_rules", list_key="InsightRules",
            resource="insight-rule/{Name}", label="CloudWatch insight rules"),
)


LONGTAIL_FNS: dict[str, Any] = {
    "opensearch_domains_described": opensearch_domains_described,
    "redshift_clusters_described": redshift_clusters_described,
    "synthetics_canaries_described": synthetics_canaries_described,
    "codecommit_repositories_described": codecommit_repositories_described,
    "rekognition_collections_described": rekognition_collections_described,
    "rekognition_stream_processors_described": rekognition_stream_processors_described,
    "mailmanager_archives_described": mailmanager_archives_described,
    "mailmanager_ingress_points_described": mailmanager_ingress_points_described,
    "mailmanager_relays_described": mailmanager_relays_described,
    "mailmanager_rule_sets_described": mailmanager_rule_sets_described,
    "mailmanager_traffic_policies_described": mailmanager_traffic_policies_described,
    "appconfig_extension_associations_described": appconfig_extension_associations_described,
    "rbin_rules_described": rbin_rules_described,
    "xray_sampling_rules_described": xray_sampling_rules_described,
    "securityhub_hub_v2_described": securityhub_hub_v2_described,
}
LONGTAIL_FNS.update({fn.__name__: fn for fn in _ARN_READERS})
