"""Landing-zone governance reader for the boto3 collector (aws-core-tap#66).

Spec: specs/spec-aws-core-landing-zone.md (req-aws-landing-zone-availability, -control-tower,
-identity-center, -security-services), with the containment pairs of
``req-aws-core-contained-type-triple`` (specs/spec-aws-core-v0.md).

Like the Organizations tree (``organizations.py``), none of this is a per-account resource list the
manifest engine can drive: Control Tower and Identity Center are read once per run, and their
children come from nested listings whose completeness is one aggregate fact. So it is its own pure
collaborator, called from ``Boto3Collector.run()`` with the run's session, region scope and region
facts, and the organization's member list. It returns what the run folds into its one GRIFT batch.

What it reads, all read-only, every paginated call to its last page (``req-aws-collector-pagination``):

    controltower   ListLandingZones (per region), GetLandingZone, ListEnabledControls(includeChildren),
                   ListEnabledBaselines(includeChildren), ListTagsForResource
    sso-admin      ListInstances (per region), ListPermissionSets, DescribePermissionSet,
                   ListManagedPoliciesInPermissionSet, ListPermissionSetsProvisionedToAccount,
                   ListAccountAssignments, ListTagsForResource
    identitystore  ListGroups
    config         ListConfigurationRecorders, DescribeConfigurationRecorders(Arn),
                   DescribeConfigurationRecorderStatus(Arn), DescribeDeliveryChannels,
                   DescribeConfigurationAggregators, ListTagsForResource
    guardduty      ListDetectors, GetDetector, GetAdministratorAccount
    securityhub    DescribeHub, GetEnabledStandards, GetAdministratorAccount, ListTagsForResource
    accessanalyzer ListAnalyzers(type) once per value of the pinned Type enum
    ec2            GetEbsEncryptionByDefault, GetEbsDefaultKmsKeyId (per region)
    s3control      GetPublicAccessBlock(AccountId), once, in the partition's home region

The security services are read per region for the run's own account. Reaching member accounts is
``req-aws-collector-fanout`` (aws-core-tap#63), out of scope here: until it lands, a run reads the
account its credential resolves to.

Collect-only. Every surface recorded here, and every falsifier registered for these types, is inert
until reconcile authority is armed, which nothing here does.

Failure discipline (the Organizations reader's, unchanged). Nothing raises for an AWS failure. A
denied or failing call degrades to a surface that says so, never to an empty listing. A node whose
tags or describe call could not be read is withheld rather than written with false empty fields
(GRIFT replaces a node whole), and its parent's surface is withdrawn from ``admitted``. A field
whose read failed is ``null``; an off setting is AWS's own answer, stored as returned
(``req-aws-collector-hydrate-6``'s rule).

GovCloud. Region and partition come from the run. Every ARN stored comes from an API response. The
S3 bucket a Config delivery channel names is keyed with the run's partition. A service the partition
does not offer is recorded ``SERVICE_NOT_AVAILABLE_IN_PARTITION`` with no call
(``partition.service_unavailable_reason``). Where availability is not verified (Control Tower's
baseline APIs, Config), a failing call says so (``partition.LANDING_ZONE_AVAILABILITY``). Nothing
here was observed against a live GovCloud account: the response shapes are read from botocore.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

from .containment import Listing as RegionListing
from .containment import footprint_id, footprint_key, surface_of
from .identity import edge_entity_id, node_entity_id
from .organizations import (
    _DENIED_CODES,
    ACCOUNT,
    ORGANIZATIONAL_UNIT,
    Listing,
    Notice,
    _schema_problem,
    error_code,
    reader_sensitivity,
    sensitivity_refusal,
)
from .partition import availability_of, home_region, parse_arn, service_unavailable_reason
from .regions import STATUS_DISABLED, RegionFacts
from .tags import normalize_tags

#: This reader's name in the custom-reader registries (tag_lanes.json, reader_sensitivity.json).
READER = "landing_zone"

FOOTPRINT = "aws_core__aws_account_region"
LANDING_ZONE = "aws_core__aws_controltower_landing_zone"
ENABLED_CONTROL = "aws_core__aws_controltower_enabled_control"
ENABLED_BASELINE = "aws_core__aws_controltower_enabled_baseline"
IDENTITY_CENTER_INSTANCE = "aws_core__aws_identity_center_instance"
PERMISSION_SET = "aws_core__aws_identity_center_permission_set"
IDENTITY_GROUP = "aws_core__aws_identity_center_group"
ACCOUNT_ASSIGNMENT = "aws_core__aws_identity_center_account_assignment"
CONFIG_RECORDER = "aws_core__aws_config_recorder"
CONFIG_DELIVERY_CHANNEL = "aws_core__aws_config_delivery_channel"
CONFIG_AGGREGATOR = "aws_core__aws_config_aggregator"
GUARDDUTY_DETECTOR = "aws_core__aws_guardduty_detector"
SECURITYHUB_HUB = "aws_core__aws_securityhub_hub"
ACCESS_ANALYZER = "aws_core__aws_access_analyzer"
S3_BUCKET = "aws_core__aws_s3_bucket"

HOSTS_LANDING_ZONE = "HOSTS_LANDING_ZONE__aws_core"
HOSTS_IDENTITY_CENTER_INSTANCE = "HOSTS_IDENTITY_CENTER_INSTANCE__aws_core"
HOSTS_CONFIG_RECORDER = "HOSTS_CONFIG_RECORDER__aws_core"
HOSTS_CONFIG_DELIVERY_CHANNEL = "HOSTS_CONFIG_DELIVERY_CHANNEL__aws_core"
HOSTS_CONFIG_AGGREGATOR = "HOSTS_CONFIG_AGGREGATOR__aws_core"
HOSTS_GUARDDUTY_DETECTOR = "HOSTS_GUARDDUTY_DETECTOR__aws_core"
HOSTS_SECURITYHUB_HUB = "HOSTS_SECURITYHUB_HUB__aws_core"
HOSTS_ACCESS_ANALYZER = "HOSTS_ACCESS_ANALYZER__aws_core"
HOLDS_ENABLED_CONTROL = "HOLDS_ENABLED_CONTROL__aws_core"
HOLDS_ENABLED_BASELINE = "HOLDS_ENABLED_BASELINE__aws_core"
APPLIES_TO_TARGET = "APPLIES_TO_TARGET__aws_core"
HOLDS_PERMISSION_SET = "HOLDS_PERMISSION_SET__aws_core"
HOLDS_IDENTITY_GROUP = "HOLDS_IDENTITY_GROUP__aws_core"
HOLDS_ACCOUNT_ASSIGNMENT = "HOLDS_ACCOUNT_ASSIGNMENT__aws_core"
GRANTS_PERMISSION_SET = "GRANTS_PERMISSION_SET__aws_core"
GRANTS_ACCESS_TO_ACCOUNT = "GRANTS_ACCESS_TO_ACCOUNT__aws_core"
GRANTED_TO_GROUP = "GRANTED_TO_GROUP__aws_core"
REPORTS_TO_ADMINISTRATOR = "REPORTS_TO_ADMINISTRATOR__aws_core"
WRITES_LOGS = "WRITES_LOGS__aws_core"

#: The (parent type -> containment edge types) this reader records surfaces for. For the footprint,
#: only the edge types this reader fills (the manifest fills the rest); for the others, exactly the
#: parent model's CONTAINMENT_EDGES (``req-aws-core-contained-type-triple-1``; a test compares them).
CONTAINMENT_SURFACES: dict[str, tuple[str, ...]] = {
    FOOTPRINT: (
        HOSTS_LANDING_ZONE,
        HOSTS_IDENTITY_CENTER_INSTANCE,
        HOSTS_CONFIG_RECORDER,
        HOSTS_CONFIG_DELIVERY_CHANNEL,
        HOSTS_CONFIG_AGGREGATOR,
        HOSTS_GUARDDUTY_DETECTOR,
        HOSTS_SECURITYHUB_HUB,
        HOSTS_ACCESS_ANALYZER,
    ),
    LANDING_ZONE: (HOLDS_ENABLED_CONTROL, HOLDS_ENABLED_BASELINE),
    IDENTITY_CENTER_INSTANCE: (HOLDS_PERMISSION_SET, HOLDS_IDENTITY_GROUP, HOLDS_ACCOUNT_ASSIGNMENT),
}

#: Completeness-surface relation names: ``<parent kind>.<what was listed>`` (the footprint's match
#: ``regional.LANDING_ZONE_CHILDREN``).
RELATION_LANDING_ZONES = "account_region.landing_zones"
RELATION_INSTANCES = "account_region.identity_center_instances"
RELATION_CONFIG_RECORDERS = "account_region.config_recorders"
RELATION_DELIVERY_CHANNELS = "account_region.config_delivery_channels"
RELATION_AGGREGATORS = "account_region.config_aggregators"
RELATION_DETECTORS = "account_region.guardduty_detectors"
RELATION_HUBS = "account_region.securityhub_hubs"
RELATION_ANALYZERS = "account_region.access_analyzers"
RELATION_ENABLED_CONTROLS = "landing_zone.enabled_controls"
RELATION_ENABLED_BASELINES = "landing_zone.enabled_baselines"
RELATION_PERMISSION_SETS = "identity_center_instance.permission_sets"
RELATION_GROUPS = "identity_center_instance.groups"
RELATION_ASSIGNMENTS = "identity_center_instance.account_assignments"

#: IAM Access Analyzer's ``Type`` enum, pinned (read: botocore 1.43.107 ``accessanalyzer``; a test
#: compares it with the installed botocore). ``ListAnalyzers`` is called once per value, because the
#: behaviour with ``type`` absent is not documented (``req-aws-core-contained-type-triple-6``).
ANALYZER_TYPES: tuple[str, ...] = (
    "ACCOUNT",
    "ORGANIZATION",
    "ACCOUNT_UNUSED_ACCESS",
    "ORGANIZATION_UNUSED_ACCESS",
    "ACCOUNT_INTERNAL_ACCESS",
    "ORGANIZATION_INTERNAL_ACCESS",
)

#: Every (service, operation) this reader reads through its page loop, with the continuation token
#: name. Each is paginated in the pinned botocore (``req-aws-collector-pagination-3``; a test walks it).
PAGINATED_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("controltower", "list_landing_zones"),
    ("controltower", "list_enabled_controls"),
    ("controltower", "list_enabled_baselines"),
    ("sso-admin", "list_instances"),
    ("sso-admin", "list_permission_sets"),
    ("sso-admin", "list_managed_policies_in_permission_set"),
    ("sso-admin", "list_permission_sets_provisioned_to_account"),
    ("sso-admin", "list_account_assignments"),
    ("sso-admin", "list_tags_for_resource"),
    ("identitystore", "list_groups"),
    ("config", "list_configuration_recorders"),
    ("config", "describe_configuration_aggregators"),
    ("config", "list_tags_for_resource"),
    ("guardduty", "list_detectors"),
    ("securityhub", "get_enabled_standards"),
    ("accessanalyzer", "list_analyzers"),
)
#: The single calls, not paginated in the pinned botocore (a test checks that too).
SINGLE_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("controltower", "get_landing_zone"),
    ("controltower", "list_tags_for_resource"),
    ("sso-admin", "describe_permission_set"),
    ("config", "describe_configuration_recorders"),
    ("config", "describe_configuration_recorder_status"),
    ("config", "describe_delivery_channels"),
    ("guardduty", "get_detector"),
    ("guardduty", "get_administrator_account"),
    ("securityhub", "describe_hub"),
    ("securityhub", "get_administrator_account"),
    ("securityhub", "list_tags_for_resource"),
    ("ec2", "get_ebs_encryption_by_default"),
    ("ec2", "get_ebs_default_kms_key_id"),
    ("s3control", "get_public_access_block"),
)
#: The lower-camel continuation token Control Tower and Access Analyzer use; every other service
#: here uses ``NextToken``.
_LOWER_TOKEN_SERVICES = frozenset({"controltower", "accessanalyzer"})


def continuation_token(service: str) -> str:
    """The continuation-token member a paginated call of ``service`` takes and returns (a test checks
    every ``PAGINATED_OPERATIONS`` row against botocore's paginator data)."""
    return "nextToken" if service in _LOWER_TOKEN_SERVICES else "NextToken"


#: ``securityhub:DescribeHub``'s answer for an account that has not enabled Security Hub. botocore
#: documents it as "the account doesn't have permission to perform this action", the same code a
#: refused credential gets, so it cannot be read as "no hub" (the spec's error-code rule): the
#: surface stays incomplete and the falsifier stays UNDETERMINED.
SECURITYHUB_NOT_SUBSCRIBED_OR_DENIED = "InvalidAccessException"
#: ``s3control:GetPublicAccessBlock``'s answer for an account with no configuration (botocore).
NO_PUBLIC_ACCESS_BLOCK = "NoSuchPublicAccessBlockConfiguration"
_PAB_FIELDS = (
    ("BlockPublicAcls", "s3_block_public_acls"),
    ("IgnorePublicAcls", "s3_ignore_public_acls"),
    ("BlockPublicPolicy", "s3_block_public_policy"),
    ("RestrictPublicBuckets", "s3_restrict_public_buckets"),
)

_MAX_PAGES = 5000


@dataclass
class LandingZoneRead:
    """Everything one landing-zone read produced."""

    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    #: Footprint surfaces, in ``containment.surface_of``'s form (the collector adds the batch).
    regional_surfaces: list[dict[str, Any]] = field(default_factory=list)
    #: Surfaces of the landing zone's and the instance's children (``organizations.Listing``).
    listings: list[Listing] = field(default_factory=list)
    notices: list[Notice] = field(default_factory=list)
    #: ``{region: {field: value}}`` for the run account's footprint node (EBS default encryption).
    footprint_fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Fields for the run account's own node (the S3 account public-access block).
    account_fields: dict[str, Any] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        value = value if value.tzinfo else value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value or "")


@dataclass
class _Walk:
    """One read (a paginated walk or a single call): its items, and the failure that ended it."""

    items: list[Any]
    first: datetime
    last: datetime
    exc: BaseException | None = None
    #: The operation, for the reason text.
    operation: str = ""

    @property
    def complete(self) -> bool:
        return self.exc is None

    @property
    def code(self) -> str:
        if self.exc is None:
            return ""
        return error_code(self.exc) or type(self.exc).__name__

    @property
    def authorized(self) -> bool | None:
        if self.exc is None:
            return True
        return False if error_code(self.exc) in _DENIED_CODES else None

    @property
    def why(self) -> str:
        return f"{self.code}: {self.operation} failed" if self.exc is not None else ""


def _aggregate(walks: list[_Walk], *, why: str = "") -> _Walk:
    """Several listings behind ONE surface: complete only when every one is
    (``req-aws-core-contained-type-triple``, "nested listings aggregate"). ``why`` adds a failure
    that is not a read (a precondition unread)."""
    first = min((w.first for w in walks), default=_now())
    last = max((w.last for w in walks), default=first)
    failed = [w for w in walks if not w.complete]
    if not failed and not why:
        return _Walk([], first, last)
    reasons = [w.why for w in failed] + ([why] if why else [])
    denied = any(w.authorized is False for w in failed)
    code = "AccessDeniedException" if denied else "Incomplete"
    exc = ClientError({"Error": {"Code": code, "Message": "; ".join(reasons)}}, "aggregate")
    return _Walk([], first, last, exc=exc, operation="; ".join(reasons))


def _unidentified(items: list[Any]) -> int:
    """How many listed items carry no identity. Each one is counted as not written, so the surface
    that listed it is withdrawn from ``admitted``: an item the reader could not represent must never
    leave a surface claiming every listed child reached the batch."""
    return sum(1 for item in items if not item)


def region_of_arn(arn: str) -> str:
    """The region segment of an ARN, or ``""``."""
    parsed = parse_arn(arn)
    return parsed.region if parsed else ""


def target_of(target_identifier: str) -> tuple[str, str] | None:
    """``(entity type, natural key)`` for a Control Tower ``targetIdentifier``: an OU ARN
    (``...:ou/o-…/ou-…``) to the OU's ``ou_id``, an account ARN (``...:account/o-…/<id>``) to the
    account's ``account_id`` (spec-aws-core-v0.md, *Target keys*). Anything else is None: no edge,
    and the typed field keeps the value."""
    parsed = parse_arn(target_identifier)
    if parsed is None or parsed.service != "organizations":
        return None
    parts = parsed.resource.split("/")
    if len(parts) == 3 and parts[0] == "ou" and parts[2].startswith("ou-"):
        return ORGANIZATIONAL_UNIT, parts[2]
    if len(parts) == 3 and parts[0] == "account" and parts[2].isdigit() and len(parts[2]) == 12:
        return ACCOUNT, parts[2]
    return None


def group_key(identity_store_id: str, group_id: str) -> str:
    """The group's natural key, ``(identity_store_id, group_id)``, in one string."""
    return f"{identity_store_id}:{group_id}"


def assignment_key(
    instance_arn: str, account_id: str, permission_set_arn: str, principal_type: str, principal_id: str
) -> str:
    """The assignment's natural key, all five members, in one string."""
    return f"{instance_arn}|{account_id}|{permission_set_arn}|{principal_type}|{principal_id}"


def regional_key(account_id: str, region: str, name: str) -> str:
    """The key of a regional object AWS gives no ARN (a delivery channel, a detector)."""
    return f"{account_id}:{region}:{name}"


def bucket_arn(partition: str, bucket: str) -> str:
    """An S3 bucket's natural key from a bare bucket name, in the run's partition."""
    return f"arn:{partition}:s3:::{bucket}"


class _Reader:
    """One landing-zone read. Holds the client factory, the accumulators and the tag latches."""

    def __init__(
        self,
        client_for: Callable[[str, str], Any],
        *,
        account_id: str,
        partition: str,
        regions: list[str],
        facts: dict[str, RegionFacts],
        member_accounts: list[str] | None,
        sensitivity: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._client_for = client_for
        self._clients: dict[tuple[str, str], Any] = {}
        self.account_id = account_id
        self.partition = partition
        self.regions = list(regions)
        self.facts = facts
        self.member_accounts = member_accounts
        self.sensitivity = reader_sensitivity(READER) if sensitivity is None else sensitivity
        self.result = LandingZoneRead()
        self._node_ids: set[str] = set()
        self._edge_ids: set[str] = set()
        #: Services whose tag read was denied: the permission is per action, not per resource.
        self._tags_denied: set[str] = set()
        self._tags_missing = 0
        self._unavailable_said: set[str] = set()

    # -- plumbing ---------------------------------------------------------

    def notice(self, level: str, code: str, message: str, **data: Any) -> None:
        self.result.notices.append(Notice(level, code, message, data))

    def client(self, service: str, region: str) -> Any:
        key = (service, region)
        if key not in self._clients:
            self._clients[key] = self._client_for(service, region)
        return self._clients[key]

    def unavailable(self, service: str) -> str | None:
        """Why ``service`` is not offered in the run's partition, said once, or None."""
        reason = service_unavailable_reason(self.partition, service)
        if reason and service not in self._unavailable_said:
            self._unavailable_said.add(service)
            self.notice(
                "info",
                "SERVICE_NOT_AVAILABLE_IN_PARTITION",
                f"{service}: not available in partition {self.partition} — {reason}",
                service=service,
                partition=self.partition,
            )
        return reason

    def _failed(self, service: str, operation: str, exc: BaseException) -> None:
        code = error_code(exc) or type(exc).__name__
        denied = code in _DENIED_CODES
        message = f"{service}:{operation} failed: {code}"
        known = availability_of(self.partition, service)
        if known is not None and not known.verified:
            message += f" (availability of {service} in {self.partition} is not verified: {known.evidence})"
        elif isinstance(exc, EndpointConnectionError):
            message += f" (no reachable {service} endpoint in partition {self.partition})"
        self.notice(
            "info" if denied else "warn",
            "LANDING_ZONE_READ_FAILED",
            message,
            service=service,
            operation=operation,
            error_code=code,
        )

    def _pages(self, client: Any, operation: str, result_key: str, token: str, params: dict[str, Any]) -> Iterator[Any]:
        fn: Callable[..., dict[str, Any]] = getattr(client, operation)
        next_token: str | None = None
        for _ in range(_MAX_PAGES):
            kwargs = dict(params)
            if next_token:
                kwargs[token] = next_token
            response = fn(**kwargs)
            yield from response.get(result_key) or []
            next_token = response.get(token)
            if not next_token:
                return
        raise EndpointConnectionError(endpoint_url=f"{operation}: continuation chain exceeded {_MAX_PAGES} pages")

    def walk(self, service: str, region: str, operation: str, result_key: str, **params: Any) -> _Walk:
        """Read one paginated call to its end. A failure keeps the items it did get but marks the
        read incomplete, so nothing is inferred from what it did not name."""
        token = continuation_token(service)
        result = _Walk([], _now(), _now(), operation=operation)
        try:
            client = self.client(service, region)
            for item in self._pages(client, operation, result_key, token, params):
                result.items.append(item)
        except (ClientError, BotoCoreError) as exc:
            result.exc = exc
            self._failed(service, operation, exc)
        result.last = _now()
        return result

    def call(
        self, service: str, region: str, operation: str, *, quiet: tuple[str, ...] = (), **params: Any
    ) -> tuple[dict[str, Any] | None, _Walk]:
        """One unpaginated call: ``(response or None, the read)``. ``quiet`` codes are expected
        answers the caller interprets, not failures to report."""
        read = _Walk([], _now(), _now(), operation=operation)
        try:
            response = getattr(self.client(service, region), operation)(**params)
        except (ClientError, BotoCoreError) as exc:
            read.exc = exc
            read.last = _now()
            if error_code(exc) not in quiet:
                self._failed(service, operation, exc)
            return None, read
        read.last = _now()
        return dict(response or {}), read

    def tags(
        self, service: str, region: str, operation: str, shape: str, result_key: str, **params: Any
    ) -> dict[str, str] | None:
        """A resource's tags through its service lane, normalized; None when unreadable (never
        ``{}``: see ``organizations._Reader.tags_of`` for why an unread tag set withholds the node).
        A paginated tag operation is read to its last page (``req-aws-collector-tags-15``)."""
        if service in self._tags_denied:
            return None
        if (service, operation) in PAGINATED_OPERATIONS:
            read = self.walk(service, region, operation, result_key, **params)
            raw: Any = read.items
        else:
            response, read = self.call(service, region, operation, **params)
            raw = (response or {}).get(result_key)
        if not read.complete:
            if read.authorized is False:
                self._tags_denied.add(service)
            else:
                self._tags_missing += 1
            return None
        return normalize_tags(raw if raw is not None else ({} if shape == "map" else []), shape)

    def dimensions(self, region: str) -> dict[str, str]:
        return {"cloud": "aws", "aws_account": self.account_id, "aws_region": region}

    def add_node(self, entity_type: str, natural_key: str, name: str, fields: dict[str, Any], region: str) -> bool:
        """Append one node envelope unless it must be withheld; True when kept (or already kept)."""
        entity_id = str(node_entity_id(entity_type, natural_key))
        if entity_id in self._node_ids:
            return True
        if fields.get("tags", {}) is None:
            self.notice(
                "warn",
                "LANDING_ZONE_NODE_SKIPPED",
                f"{entity_type} {natural_key}: skipped, tags could not be read this run",
                entity_type=entity_type,
            )
            return False
        refused = sensitivity_refusal(entity_type, self.sensitivity)
        if refused is None:
            refused = _schema_problem(entity_type, fields)
        if refused is not None:
            self.notice(
                "warn",
                "LANDING_ZONE_NODE_SKIPPED",
                f"{entity_type} {natural_key}: skipped, {refused}",
                entity_type=entity_type,
            )
            return False
        self._node_ids.add(entity_id)
        self.result.nodes.append(
            {
                "entity": {
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "name": name[:255] or natural_key[:255],
                    "dimensions": self.dimensions(region),
                },
                "node": fields,
            }
        )
        return True

    def add_edge(self, edge_type: str, from_type: str, from_key: str, to_type: str, to_key: str, region: str) -> None:
        entity_id = str(edge_entity_id(edge_type, from_key, to_key))
        if entity_id in self._edge_ids:
            return
        self._edge_ids.add(entity_id)
        self.result.edges.append(
            {
                "entity": {
                    "entity_id": entity_id,
                    "entity_type": "edge",
                    "name": f"{from_key} {edge_type} {to_key}",
                    "dimensions": self.dimensions(region),
                },
                "edge": {
                    "from_entity_id": str(node_entity_id(from_type, from_key)),
                    "to_entity_id": str(node_entity_id(to_type, to_key)),
                    "edge_type": edge_type,
                    "properties": {},
                },
            }
        )

    def hosts(self, edge_type: str, region: str, child_type: str, child_key: str) -> None:
        self.add_edge(edge_type, FOOTPRINT, footprint_key(self.account_id, region), child_type, child_key, region)

    # -- surfaces ---------------------------------------------------------

    def footprint_surface(
        self,
        region: str,
        edge_type: str,
        relation: str,
        read: _Walk,
        *,
        count: int,
        not_hosted: int = 0,
        skipped: int = 0,
    ) -> None:
        """A footprint's surface for one of this reader's listings, under the per-region rules."""
        listing = RegionListing(first=read.first, last=read.last, count=count, error=read.exc, not_hosted=not_hosted)
        if skipped:
            listing.processing.append(f"child_skipped: {skipped} listed item(s) were not written this run")
        self.result.regional_surfaces.append(
            surface_of(
                relation=relation,
                edge_type=edge_type,
                subject=str(footprint_id(self.account_id, region)),
                facts=self.facts[region],
                listing=listing,
            )
        )

    def disabled_surface(self, region: str, edge_type: str, relation: str) -> None:
        self.result.regional_surfaces.append(
            surface_of(
                relation=relation,
                edge_type=edge_type,
                subject=str(footprint_id(self.account_id, region)),
                facts=self.facts[region],
                listing=None,
            )
        )

    def not_offered_surface(self, region: str, edge_type: str, relation: str, why: str) -> None:
        """No call was made because the partition does not offer the service. Recorded incomplete,
        never complete-empty: the availability table could be wrong, and a complete empty answer
        would nominate whatever the grid still holds."""
        now = _now().isoformat()
        reason = f"service_not_available_in_partition: {why}"
        self.result.regional_surfaces.append(
            {
                "relation": relation,
                "edge_type": edge_type,
                "subject": str(footprint_id(self.account_id, region)),
                "interval": {"first": now, "last": now},
                "scope_authorized": False,
                "enumeration_complete": False,
                "source_consistent": "unknown",
                "admitted": False,
                "count_observed": None,
                "reasons": {
                    "scope_authorized": reason,
                    "enumeration_complete": reason,
                    "admitted": reason,
                    "source_consistent": "no_promise: no listing was made",
                },
            }
        )

    def parent_surface(
        self,
        read: _Walk,
        relation: str,
        edge_type: str,
        subject_type: str,
        subject_key: str,
        *,
        count: int,
        skipped: int = 0,
    ) -> Listing:
        """A non-footprint parent's surface (``organizations.Listing``), kept for the run."""
        subject = str(node_entity_id(subject_type, subject_key))
        if read.complete:
            listing = Listing(relation, edge_type, subject, read.first, read.last, True, True, count)
            if skipped:
                listing.admitted = False
                listing.reasons["admitted"] = f"child_skipped: {skipped} listed item(s) were not written this run"
        else:
            denied = read.authorized is False
            listing = Listing(
                relation,
                edge_type,
                subject,
                read.first,
                read.last,
                authorized=read.authorized,
                complete=False,
                count=None,
                admitted=False,
                reasons={
                    "scope_authorized": f"{'denied' if denied else 'not_determinable'}: {read.why}",
                    "enumeration_complete": f"nothing_established: {read.why}",
                    "admitted": f"nothing_to_process: {read.why}",
                },
            )
        listing.reasons.setdefault(
            "source_consistent", "no_promise: the AWS listing makes no snapshot promise across pages"
        )
        self.result.listings.append(listing)
        return listing

    def readable_regions(self, edge_types: tuple[tuple[str, str], ...], service: str) -> list[str]:
        """The regions to read for one service: every in-scope region not positively disabled. A
        disabled region and an unavailable service each record their surfaces here, with no call."""
        why = self.unavailable(service)
        regions = []
        for region in self.regions:
            for edge_type, relation in edge_types:
                if why:
                    self.not_offered_surface(region, edge_type, relation, why)
                elif self.facts[region].status == STATUS_DISABLED:
                    self.disabled_surface(region, edge_type, relation)
            if not why and self.facts[region].status != STATUS_DISABLED:
                regions.append(region)
        return regions

    # -- the read ---------------------------------------------------------

    def collect(self) -> LandingZoneRead:
        self._control_tower()
        self._identity_center()
        for region in self.readable_regions(
            (
                (HOSTS_CONFIG_RECORDER, RELATION_CONFIG_RECORDERS),
                (HOSTS_CONFIG_DELIVERY_CHANNEL, RELATION_DELIVERY_CHANNELS),
                (HOSTS_CONFIG_AGGREGATOR, RELATION_AGGREGATORS),
            ),
            "config",
        ):
            self._config(region)
        for region in self.readable_regions(((HOSTS_GUARDDUTY_DETECTOR, RELATION_DETECTORS),), "guardduty"):
            self._guardduty(region)
        for region in self.readable_regions(((HOSTS_SECURITYHUB_HUB, RELATION_HUBS),), "securityhub"):
            self._securityhub(region)
        for region in self.readable_regions(((HOSTS_ACCESS_ANALYZER, RELATION_ANALYZERS),), "accessanalyzer"):
            self._access_analyzers(region)
        for region in self.readable_regions((), "ec2"):
            self._ebs_defaults(region)
        self._public_access_block()
        if self._tags_missing:
            self.notice(
                "warn",
                "LANDING_ZONE_TAGS_INCOMPLETE",
                f"{self._tags_missing} tag read(s) failed; those nodes are not written this run.",
                count=self._tags_missing,
            )
        for service in sorted(self._tags_denied):
            self.notice(
                "info",
                "LANDING_ZONE_TAGS_DENIED",
                f"{service}:ListTagsForResource is denied: its nodes are not written this run rather than overwrite their tags with a false empty observation.",
                service=service,
            )
        return self.result

    # Control Tower --------------------------------------------------------

    def _control_tower(self) -> None:
        regions = self.readable_regions(((HOSTS_LANDING_ZONE, RELATION_LANDING_ZONES),), "controltower")
        reads: dict[str, _Walk] = {}
        found: dict[str, str] = {}  # landing zone ARN -> the first region whose listing returned it
        skipped: dict[str, int] = {}
        for region in regions:
            reads[region] = self.walk("controltower", region, "list_landing_zones", "landingZones")
            for item in reads[region].items:
                arn = str((item or {}).get("arn") or "")
                if arn:
                    found.setdefault(arn, region)
                else:
                    skipped[region] = skipped.get(region, 0) + 1
        written: list[tuple[str, str]] = []
        for arn in sorted(found):
            home = region_of_arn(arn) or found[arn]
            if self._landing_zone(arn, home, found[arn]):
                written.append((arn, home if home in self.regions else found[arn]))
            elif home in reads:
                skipped[home] = skipped.get(home, 0) + 1
        for region, read in reads.items():
            own = sum(
                1 for item in read.items if (region_of_arn(str((item or {}).get("arn") or "")) or region) == region
            )
            self.footprint_surface(
                region,
                HOSTS_LANDING_ZONE,
                RELATION_LANDING_ZONES,
                read,
                count=len(read.items),
                not_hosted=len(read.items) - own,
                skipped=skipped.get(region, 0),
            )
        if len(found) > 1:
            # ListEnabledControls and ListEnabledBaselines are not scoped to a landing zone: with two
            # LISTED (whether or not each was written this run), neither listing can be said to be
            # one's children, so every written one records both child surfaces incomplete.
            now = _now()
            why = f"{len(found)} landing zones listed; the enabled-control and enabled-baseline listings are not scoped to one"
            self.notice("warn", "LANDING_ZONE_AMBIGUOUS", why, landing_zones=sorted(found))
            unread = _Walk(
                [],
                now,
                now,
                exc=ClientError({"Error": {"Code": "Ambiguous", "Message": why}}, "list"),
                operation="ListEnabledControls/ListEnabledBaselines",
            )
            for arn, _region in written:
                self.parent_surface(
                    unread, RELATION_ENABLED_CONTROLS, HOLDS_ENABLED_CONTROL, LANDING_ZONE, arn, count=0
                )
                self.parent_surface(
                    unread, RELATION_ENABLED_BASELINES, HOLDS_ENABLED_BASELINE, LANDING_ZONE, arn, count=0
                )
            return
        for arn, region in written:
            self._enabled_controls(arn, region)
            self._enabled_baselines(arn, region)

    def _landing_zone(self, arn: str, home: str, returned_in: str) -> bool:
        in_scope = home in self.regions
        region = home if in_scope else returned_in
        response, read = self.call("controltower", region, "get_landing_zone", landingZoneIdentifier=arn)
        if response is None:
            self.notice(
                "warn",
                "LANDING_ZONE_NODE_SKIPPED",
                f"{arn}: GetLandingZone failed ({read.code}); the landing zone is not written this run",
                entity_type=LANDING_ZONE,
            )
            return False
        detail = response.get("landingZone") or {}
        manifest = detail.get("manifest")
        governed = manifest.get("governedRegions") if isinstance(manifest, dict) else None
        name = f"Landing zone {detail.get('version') or ''} ({home})".replace("  ", " ")
        fields: dict[str, Any] = {
            "name": name,
            "landing_zone_arn": arn,
            "home_region": home,
            "version": str(detail.get("version") or ""),
            "latest_available_version": str(detail.get("latestAvailableVersion") or ""),
            "status": str(detail.get("status") or ""),
            "drift_status": str((detail.get("driftStatus") or {}).get("status") or ""),
            "governed_regions": sorted(str(r) for r in governed) if isinstance(governed, list) else None,
            "tags": self.tags("controltower", region, "list_tags_for_resource", "map", "tags", resourceArn=arn),
        }
        if not self.add_node(LANDING_ZONE, arn, name, fields, region):
            return False
        if in_scope:
            self.hosts(HOSTS_LANDING_ZONE, home, LANDING_ZONE, arn)
        else:
            self.notice(
                "warn",
                "LANDING_ZONE_HOME_REGION_OUT_OF_SCOPE",
                f"{arn}: its home region {home} is outside the run's region scope; it is written with no footprint containment.",
                home_region=home,
            )
        return True

    def _control_children(self, kind: str, lz_arn: str, region: str) -> None:
        if kind == "control":
            operation, key, child_type, edge, relation = (
                "list_enabled_controls",
                "enabledControls",
                ENABLED_CONTROL,
                HOLDS_ENABLED_CONTROL,
                RELATION_ENABLED_CONTROLS,
            )
        else:
            operation, key, child_type, edge, relation = (
                "list_enabled_baselines",
                "enabledBaselines",
                ENABLED_BASELINE,
                HOLDS_ENABLED_BASELINE,
                RELATION_ENABLED_BASELINES,
            )
        # includeChildren: true, never the default (req-aws-core-contained-type-triple-6).
        read = self.walk("controltower", region, operation, key, includeChildren=True)
        skipped = 0
        untargeted = 0
        for item in read.items:
            arn = str((item or {}).get("arn") or "")
            if not arn:
                skipped += 1
                continue
            target = str(item.get("targetIdentifier") or "")
            if kind == "control":
                identifier = str(item.get("controlIdentifier") or "")
                drift = str((item.get("driftStatusSummary") or {}).get("driftStatus") or "")
                fields: dict[str, Any] = {"enabled_control_arn": arn, "control_identifier": identifier}
            else:
                identifier = str(item.get("baselineIdentifier") or "")
                inheritance = ((item.get("driftStatusSummary") or {}).get("types") or {}).get("inheritance") or {}
                drift = str(inheritance.get("status") or "")
                fields = {
                    "enabled_baseline_arn": arn,
                    "baseline_identifier": identifier,
                    "baseline_version": str(item.get("baselineVersion") or ""),
                }
            name = f"{identifier.rsplit('/', 1)[-1] or arn} -> {target.rsplit('/', 1)[-1] or '?'}"
            fields.update(
                {
                    "name": name[:255],
                    "target_identifier": target,
                    "parent_identifier": str(item.get("parentIdentifier") or ""),
                    "status": str((item.get("statusSummary") or {}).get("status") or ""),
                    "drift_status": drift,
                    "tags": self.tags("controltower", region, "list_tags_for_resource", "map", "tags", resourceArn=arn),
                }
            )
            if not self.add_node(child_type, arn, name, fields, region):
                skipped += 1
                continue
            self.add_edge(edge, LANDING_ZONE, lz_arn, child_type, arn, region)
            resolved = target_of(target)
            if resolved is None:
                untargeted += 1
            else:
                self.add_edge(APPLIES_TO_TARGET, child_type, arn, resolved[0], resolved[1], region)
        if untargeted:
            self.notice(
                "warn",
                "LANDING_ZONE_TARGET_UNRESOLVED",
                f"{untargeted} enabled {kind}(s) name a target that is not an OU or account ARN; their target is kept as a field, with no edge.",
                count=untargeted,
            )
        self.parent_surface(read, relation, edge, LANDING_ZONE, lz_arn, count=len(read.items), skipped=skipped)

    def _enabled_controls(self, lz_arn: str, region: str) -> None:
        self._control_children("control", lz_arn, region)

    def _enabled_baselines(self, lz_arn: str, region: str) -> None:
        self._control_children("baseline", lz_arn, region)

    # Identity Center ------------------------------------------------------

    def _identity_center(self) -> None:
        regions = self.readable_regions(((HOSTS_IDENTITY_CENTER_INSTANCE, RELATION_INSTANCES),), "sso-admin")
        reads: dict[str, _Walk] = {}
        found: dict[str, tuple[dict[str, Any], str]] = {}
        skipped: dict[str, int] = {}
        for region in regions:
            reads[region] = self.walk("sso-admin", region, "list_instances", "Instances")
            for item in reads[region].items:
                arn = str((item or {}).get("InstanceArn") or "")
                if arn:
                    found.setdefault(arn, (item, region))
                else:
                    skipped[region] = skipped.get(region, 0) + 1
        for arn in sorted(found):
            item, returned_in = found[arn]
            home = str(item.get("PrimaryRegion") or "") or returned_in
            if not self._instance(arn, item, home, returned_in) and home in reads:
                skipped[home] = skipped.get(home, 0) + 1
        for region, read in reads.items():
            own = sum(1 for item in read.items if (str((item or {}).get("PrimaryRegion") or "") or region) == region)
            self.footprint_surface(
                region,
                HOSTS_IDENTITY_CENTER_INSTANCE,
                RELATION_INSTANCES,
                read,
                count=len(read.items),
                not_hosted=len(read.items) - own,
                skipped=skipped.get(region, 0),
            )

    def _instance(self, arn: str, item: dict[str, Any], home: str, returned_in: str) -> bool:
        """One instance, emitted once from its primary region's footprint
        (``req-aws-landing-zone-identity-center-1``). Its primary region outside the run's scope is
        the case aws-core-tap#66 settles (``-7``): the instance is written, with no footprint
        containment and a warning, and its children are read through the region that returned it.
        Its ``aws_region`` dimension is that read region, so a falsifier never has to leave the scope."""
        in_scope = home in self.regions
        region = home if in_scope else returned_in
        reported = item.get("Regions")
        regions = (
            sorted({str(r.get("RegionName") or "") for r in reported if isinstance(r, dict)} - {""})
            if isinstance(reported, list)
            else None
        )
        name = str(item.get("Name") or "") or arn.rsplit("/", 1)[-1]
        fields: dict[str, Any] = {
            "name": name,
            "instance_arn": arn,
            "identity_store_id": str(item.get("IdentityStoreId") or ""),
            "owner_account_id": str(item.get("OwnerAccountId") or ""),
            "home_region": home,
            "regions": regions,
            "status": str(item.get("Status") or ""),
            "tags": self.tags(
                "sso-admin", region, "list_tags_for_resource", "list_kv", "Tags", InstanceArn=arn, ResourceArn=arn
            ),
        }
        if not self.add_node(IDENTITY_CENTER_INSTANCE, arn, name, fields, region):
            return False
        if in_scope:
            self.hosts(HOSTS_IDENTITY_CENTER_INSTANCE, home, IDENTITY_CENTER_INSTANCE, arn)
        else:
            self.notice(
                "warn",
                "IDENTITY_CENTER_PRIMARY_REGION_OUT_OF_SCOPE",
                f"{arn}: its primary region {home} is outside the run's region scope ({', '.join(self.regions)}); it is "
                f"written with no footprint containment and read through {returned_in}.",
                primary_region=home,
                read_region=returned_in,
            )
        self._permission_sets(arn, region)
        self._groups(arn, fields["identity_store_id"], region)
        self._assignments(arn, fields["identity_store_id"], region)
        return True

    def _permission_sets(self, instance_arn: str, region: str) -> None:
        read = self.walk("sso-admin", region, "list_permission_sets", "PermissionSets", InstanceArn=instance_arn)
        skipped = _unidentified(read.items)
        for ps_arn in sorted({str(a) for a in read.items if a}):
            response, described = self.call(
                "sso-admin", region, "describe_permission_set", InstanceArn=instance_arn, PermissionSetArn=ps_arn
            )
            if response is None:
                skipped += 1
                self.notice(
                    "warn",
                    "LANDING_ZONE_NODE_SKIPPED",
                    f"{ps_arn}: DescribePermissionSet failed ({described.code}); not written this run",
                    entity_type=PERMISSION_SET,
                )
                continue
            detail = response.get("PermissionSet") or {}
            managed = self.walk(
                "sso-admin",
                region,
                "list_managed_policies_in_permission_set",
                "AttachedManagedPolicies",
                InstanceArn=instance_arn,
                PermissionSetArn=ps_arn,
            )
            name = str(detail.get("Name") or "") or ps_arn.rsplit("/", 1)[-1]
            fields = {
                "name": name,
                "permission_set_arn": ps_arn,
                "instance_arn": instance_arn,
                "description": str(detail.get("Description") or "")[:700],
                "session_duration": str(detail.get("SessionDuration") or ""),
                "relay_state": str(detail.get("RelayState") or ""),
                "created_at": _iso(detail.get("CreatedDate")),
                # A later page that failed leaves the list unknown, never partial (req-aws-collector-pagination-2).
                "managed_policy_arns": sorted({str(p.get("Arn") or "") for p in managed.items} - {""})
                if managed.complete
                else None,
                "tags": self.tags(
                    "sso-admin",
                    region,
                    "list_tags_for_resource",
                    "list_kv",
                    "Tags",
                    InstanceArn=instance_arn,
                    ResourceArn=ps_arn,
                ),
            }
            if not self.add_node(PERMISSION_SET, ps_arn, name, fields, region):
                skipped += 1
                continue
            self.add_edge(HOLDS_PERMISSION_SET, IDENTITY_CENTER_INSTANCE, instance_arn, PERMISSION_SET, ps_arn, region)
        self.parent_surface(
            read,
            RELATION_PERMISSION_SETS,
            HOLDS_PERMISSION_SET,
            IDENTITY_CENTER_INSTANCE,
            instance_arn,
            count=len(read.items),
            skipped=skipped,
        )

    def _groups(self, instance_arn: str, identity_store_id: str, region: str) -> None:
        if self.unavailable("identitystore"):
            now = _now()
            read = _Walk(
                [],
                now,
                now,
                exc=ClientError({"Error": {"Code": "ServiceNotAvailable", "Message": "identitystore"}}, "ListGroups"),
                operation="ListGroups",
            )
        elif not identity_store_id:
            now = _now()
            read = _Walk(
                [],
                now,
                now,
                exc=ClientError(
                    {"Error": {"Code": "NoIdentityStore", "Message": "ListInstances named no IdentityStoreId"}},
                    "ListGroups",
                ),
                operation="ListGroups",
            )
        else:
            # No Filters: the full set (req-aws-core-contained-type-triple-6).
            read = self.walk("identitystore", region, "list_groups", "Groups", IdentityStoreId=identity_store_id)
        skipped = 0
        for group in read.items:
            group_id = str((group or {}).get("GroupId") or "")
            if not group_id:
                skipped += 1
                continue
            display = str(group.get("DisplayName") or "")
            key = group_key(identity_store_id, group_id)
            fields = {
                "name": (display or group_id)[:255],
                "identity_store_id": identity_store_id,
                "group_id": group_id,
                "display_name": display[:1024],
                "description": str(group.get("Description") or "")[:1024],
                "external_ids": [
                    {"issuer": str(e.get("Issuer") or ""), "id": str(e.get("Id") or "")}
                    for e in (group.get("ExternalIds") or [])
                    if isinstance(e, dict)
                ],
                # AWS cannot tag an identity-store group (lane `none`, tag_lanes.json).
                "tags": {},
            }
            if not self.add_node(IDENTITY_GROUP, key, str(fields["name"]), fields, region):
                skipped += 1
                continue
            self.add_edge(HOLDS_IDENTITY_GROUP, IDENTITY_CENTER_INSTANCE, instance_arn, IDENTITY_GROUP, key, region)
        self.parent_surface(
            read,
            RELATION_GROUPS,
            HOLDS_IDENTITY_GROUP,
            IDENTITY_CENTER_INSTANCE,
            instance_arn,
            count=len(read.items),
            skipped=skipped,
        )

    def _assignments(self, instance_arn: str, identity_store_id: str, region: str) -> None:
        """Account assignments behind ONE surface per instance (``req-aws-landing-zone-identity-center-5``):
        complete only when the organization's account listing, every
        ``ListPermissionSetsProvisionedToAccount`` and every ``ListAccountAssignments`` read to the end."""
        reads: list[_Walk] = []
        why = ""
        accounts = self.member_accounts
        if accounts is None:
            why = "the organization's account listing (ListAccounts) did not read to its end, so the account set is unknown"
            accounts = []
        emitted = skipped = 0
        for account in accounts:
            # ProvisioningStatus is never set: it is a filter (req-aws-core-contained-type-triple-6).
            provisioned = self.walk(
                "sso-admin",
                region,
                "list_permission_sets_provisioned_to_account",
                "PermissionSets",
                InstanceArn=instance_arn,
                AccountId=account,
            )
            reads.append(provisioned)
            skipped += _unidentified(provisioned.items)
            for ps_arn in sorted({str(a) for a in provisioned.items if a}):
                listed = self.walk(
                    "sso-admin",
                    region,
                    "list_account_assignments",
                    "AccountAssignments",
                    InstanceArn=instance_arn,
                    AccountId=account,
                    PermissionSetArn=ps_arn,
                )
                reads.append(listed)
                for assignment in listed.items:
                    principal_type = str((assignment or {}).get("PrincipalType") or "")
                    principal_id = str(assignment.get("PrincipalId") or "")
                    account_id = str(assignment.get("AccountId") or account)
                    permission_set = str(assignment.get("PermissionSetArn") or ps_arn)
                    if not principal_type or not principal_id:
                        skipped += 1
                        continue
                    key = assignment_key(instance_arn, account_id, permission_set, principal_type, principal_id)
                    name = f"{principal_type} {principal_id} -> {account_id} ({permission_set.rsplit('/', 1)[-1]})"
                    fields = {
                        "name": name[:255],
                        "instance_arn": instance_arn,
                        "account_id": account_id,
                        "permission_set_arn": permission_set,
                        "principal_type": principal_type,
                        "principal_id": principal_id,
                        # AWS cannot tag an assignment (lane `none`, tag_lanes.json).
                        "tags": {},
                    }
                    if not self.add_node(ACCOUNT_ASSIGNMENT, key, name, fields, region):
                        skipped += 1
                        continue
                    emitted += 1
                    self.add_edge(
                        HOLDS_ACCOUNT_ASSIGNMENT,
                        IDENTITY_CENTER_INSTANCE,
                        instance_arn,
                        ACCOUNT_ASSIGNMENT,
                        key,
                        region,
                    )
                    self.add_edge(
                        GRANTS_PERMISSION_SET, ACCOUNT_ASSIGNMENT, key, PERMISSION_SET, permission_set, region
                    )
                    self.add_edge(GRANTS_ACCESS_TO_ACCOUNT, ACCOUNT_ASSIGNMENT, key, ACCOUNT, account_id, region)
                    if principal_type == "GROUP" and identity_store_id:
                        # Users are not nodes (ruling 2026-10-01): only a group principal has an edge.
                        self.add_edge(
                            GRANTED_TO_GROUP,
                            ACCOUNT_ASSIGNMENT,
                            key,
                            IDENTITY_GROUP,
                            group_key(identity_store_id, principal_id),
                            region,
                        )
        if why:
            self.notice(
                "warn", "IDENTITY_CENTER_ASSIGNMENTS_INCOMPLETE", f"{instance_arn}: {why}", instance_arn=instance_arn
            )
        self.parent_surface(
            _aggregate(reads, why=why),
            RELATION_ASSIGNMENTS,
            HOLDS_ACCOUNT_ASSIGNMENT,
            IDENTITY_CENTER_INSTANCE,
            instance_arn,
            count=emitted + skipped,
            skipped=skipped,
        )

    # Security services ----------------------------------------------------

    def _config(self, region: str) -> None:
        # Recorders: ListConfigurationRecorders, unfiltered, lists customer-managed and service-linked
        # alike; DescribeConfigurationRecorders with no name would not (req-aws-core-contained-type-triple-6).
        read = self.walk("config", region, "list_configuration_recorders", "ConfigurationRecorderSummaries")
        skipped = 0
        for summary in read.items:
            arn = str((summary or {}).get("arn") or "")
            if not arn:
                skipped += 1
                continue
            response, described = self.call("config", region, "describe_configuration_recorders", Arn=arn)
            recorder = next(iter((response or {}).get("ConfigurationRecorders") or []), None)
            if recorder is None:
                skipped += 1
                self.notice(
                    "warn",
                    "LANDING_ZONE_NODE_SKIPPED",
                    f"{arn}: DescribeConfigurationRecorders returned no recorder ({described.code or 'empty'}); not written this run",
                    entity_type=CONFIG_RECORDER,
                )
                continue
            status_response, _ = self.call("config", region, "describe_configuration_recorder_status", Arn=arn)
            status = next(iter((status_response or {}).get("ConfigurationRecordersStatus") or []), None)
            group = recorder.get("recordingGroup") or {}
            name = str(recorder.get("name") or summary.get("name") or arn)
            fields = {
                "name": name[:255],
                "recorder_arn": arn,
                "recorder_name": name[:256],
                "recording": status.get("recording")
                if isinstance(status, dict) and isinstance(status.get("recording"), bool)
                else None,
                "last_status": str(status.get("lastStatus") or "") if isinstance(status, dict) else "",
                "service_principal": str(recorder.get("servicePrincipal") or summary.get("servicePrincipal") or ""),
                "recording_scope": str(recorder.get("recordingScope") or summary.get("recordingScope") or ""),
                "role_arn": str(recorder.get("roleARN") or ""),
                "all_supported": group.get("allSupported") if isinstance(group.get("allSupported"), bool) else None,
                "include_global_resource_types": group.get("includeGlobalResourceTypes")
                if isinstance(group.get("includeGlobalResourceTypes"), bool)
                else None,
                "tags": self.tags("config", region, "list_tags_for_resource", "list_kv", "Tags", ResourceArn=arn),
            }
            if not self.add_node(CONFIG_RECORDER, arn, name, fields, region):
                skipped += 1
                continue
            self.hosts(HOSTS_CONFIG_RECORDER, region, CONFIG_RECORDER, arn)
        self.footprint_surface(
            region, HOSTS_CONFIG_RECORDER, RELATION_CONFIG_RECORDERS, read, count=len(read.items), skipped=skipped
        )

        response, channels_read = self.call("config", region, "describe_delivery_channels")
        channels = list((response or {}).get("DeliveryChannels") or [])
        channels_read.items = channels
        skipped = 0
        for channel in channels:
            channel_name = str((channel or {}).get("name") or "")
            if not channel_name:
                skipped += 1
                continue
            key = regional_key(self.account_id, region, channel_name)
            bucket = str(channel.get("s3BucketName") or "")
            fields = {
                "name": channel_name[:255],
                "account_id": self.account_id,
                "region": region,
                "channel_name": channel_name[:256],
                "s3_bucket_name": bucket,
                "s3_key_prefix": str(channel.get("s3KeyPrefix") or ""),
                "s3_kms_key_arn": str(channel.get("s3KmsKeyArn") or ""),
                "sns_topic_arn": str(channel.get("snsTopicARN") or ""),
                "delivery_frequency": str(
                    (channel.get("configSnapshotDeliveryProperties") or {}).get("deliveryFrequency") or ""
                ),
                # AWS cannot tag a delivery channel (lane `none`, tag_lanes.json).
                "tags": {},
            }
            if not self.add_node(CONFIG_DELIVERY_CHANNEL, key, channel_name, fields, region):
                skipped += 1
                continue
            self.hosts(HOSTS_CONFIG_DELIVERY_CHANNEL, region, CONFIG_DELIVERY_CHANNEL, key)
            if bucket:
                # Target keys: a bare bucket name, keyed in the run's partition.
                self.add_edge(
                    WRITES_LOGS, CONFIG_DELIVERY_CHANNEL, key, S3_BUCKET, bucket_arn(self.partition, bucket), region
                )
        self.footprint_surface(
            region,
            HOSTS_CONFIG_DELIVERY_CHANNEL,
            RELATION_DELIVERY_CHANNELS,
            channels_read,
            count=len(channels),
            skipped=skipped,
        )

        read = self.walk("config", region, "describe_configuration_aggregators", "ConfigurationAggregators")
        skipped = 0
        for aggregator in read.items:
            arn = str((aggregator or {}).get("ConfigurationAggregatorArn") or "")
            if not arn:
                skipped += 1
                continue
            organization = aggregator.get("OrganizationAggregationSource")
            account_sources = [s for s in (aggregator.get("AccountAggregationSources") or []) if isinstance(s, dict)]
            sources = [organization] if isinstance(organization, dict) else account_sources
            all_regions = [s.get("AllAwsRegions") for s in sources if isinstance(s.get("AllAwsRegions"), bool)]
            name = str(aggregator.get("ConfigurationAggregatorName") or arn)
            fields = {
                "name": name[:255],
                "aggregator_arn": arn,
                "aggregator_name": name[:256],
                "organization_wide": isinstance(organization, dict),
                "source_account_ids": sorted({str(a) for s in account_sources for a in (s.get("AccountIds") or [])}),
                "all_aws_regions": any(all_regions) if all_regions else None,
                "aws_regions": sorted({str(r) for s in sources for r in (s.get("AwsRegions") or [])}),
                "role_arn": str(organization.get("RoleArn") or "") if isinstance(organization, dict) else "",
                "tags": self.tags("config", region, "list_tags_for_resource", "list_kv", "Tags", ResourceArn=arn),
            }
            if not self.add_node(CONFIG_AGGREGATOR, arn, name, fields, region):
                skipped += 1
                continue
            self.hosts(HOSTS_CONFIG_AGGREGATOR, region, CONFIG_AGGREGATOR, arn)
        self.footprint_surface(
            region, HOSTS_CONFIG_AGGREGATOR, RELATION_AGGREGATORS, read, count=len(read.items), skipped=skipped
        )

    def _guardduty(self, region: str) -> None:
        read = self.walk("guardduty", region, "list_detectors", "DetectorIds")
        skipped = _unidentified(read.items)
        for detector_id in sorted({str(d) for d in read.items if d}):
            response, described = self.call("guardduty", region, "get_detector", DetectorId=detector_id)
            if response is None:
                skipped += 1
                self.notice(
                    "warn",
                    "LANDING_ZONE_NODE_SKIPPED",
                    f"GuardDuty detector {detector_id} in {region}: GetDetector failed ({described.code}); not written this run",
                    entity_type=GUARDDUTY_DETECTOR,
                )
                continue
            administrator, relationship = self._administrator("guardduty", region, DetectorId=detector_id)
            key = regional_key(self.account_id, region, detector_id)
            fields = {
                "name": f"GuardDuty {region}",
                "account_id": self.account_id,
                "region": region,
                "detector_id": detector_id,
                "status": str(response.get("Status") or ""),
                "finding_publishing_frequency": str(response.get("FindingPublishingFrequency") or ""),
                "administrator_account_id": administrator,
                "relationship_status": relationship,
                # Field lane: GetDetector carries the detector's own Tags map.
                "tags": normalize_tags(response.get("Tags") or {}, "map"),
            }
            if not self.add_node(GUARDDUTY_DETECTOR, key, str(fields["name"]), fields, region):
                skipped += 1
                continue
            self.hosts(HOSTS_GUARDDUTY_DETECTOR, region, GUARDDUTY_DETECTOR, key)
            if administrator and administrator != self.account_id:
                self.add_edge(REPORTS_TO_ADMINISTRATOR, GUARDDUTY_DETECTOR, key, ACCOUNT, administrator, region)
        self.footprint_surface(
            region, HOSTS_GUARDDUTY_DETECTOR, RELATION_DETECTORS, read, count=len(read.items), skipped=skipped
        )

    def _administrator(self, service: str, region: str, **params: Any) -> tuple[str | None, str]:
        """``(administrator account id, relationship)``: ``""`` when there is none, None when unread."""
        response, _ = self.call(service, region, "get_administrator_account", **params)
        if response is None:
            return None, ""
        administrator = response.get("Administrator") or {}
        account = str(administrator.get("AccountId") or "")
        relationship = str(administrator.get("RelationshipStatus") or administrator.get("MemberStatus") or "")
        return account, relationship

    def _securityhub(self, region: str) -> None:
        response, read = self.call("securityhub", region, "describe_hub", quiet=(SECURITYHUB_NOT_SUBSCRIBED_OR_DENIED,))
        if response is None:
            if read.code == SECURITYHUB_NOT_SUBSCRIBED_OR_DENIED:
                self.notice(
                    "info",
                    "SECURITYHUB_NOT_SUBSCRIBED_OR_DENIED",
                    f"securityhub:DescribeHub in {region} answered {SECURITYHUB_NOT_SUBSCRIBED_OR_DENIED}, which AWS uses both for an "
                    "account without Security Hub and for a refused credential: recorded as unknown, not as off.",
                    region=region,
                )
            self.footprint_surface(region, HOSTS_SECURITYHUB_HUB, RELATION_HUBS, read, count=0)
            return
        arn = str(response.get("HubArn") or "")
        if not arn:
            now = _now()
            empty = _Walk(
                [],
                read.first,
                now,
                exc=ClientError(
                    {"Error": {"Code": "NoHubArn", "Message": "DescribeHub returned no HubArn"}}, "DescribeHub"
                ),
                operation="describe_hub",
            )
            self.footprint_surface(region, HOSTS_SECURITYHUB_HUB, RELATION_HUBS, empty, count=0)
            return
        read.items = [response]
        standards = self.walk("securityhub", region, "get_enabled_standards", "StandardsSubscriptions")
        administrator, _ = self._administrator("securityhub", region)
        fields = {
            "name": f"Security Hub {region}",
            "hub_arn": arn,
            "subscribed_at": str(response.get("SubscribedAt") or ""),
            "auto_enable_controls": response.get("AutoEnableControls")
            if isinstance(response.get("AutoEnableControls"), bool)
            else None,
            "control_finding_generator": str(response.get("ControlFindingGenerator") or ""),
            "enabled_standards": (
                [
                    {"standards_arn": str(s.get("StandardsArn") or ""), "status": str(s.get("StandardsStatus") or "")}
                    for s in standards.items
                    if isinstance(s, dict)
                ]
                if standards.complete
                else None
            ),
            "administrator_account_id": administrator,
            "tags": self.tags("securityhub", region, "list_tags_for_resource", "map", "Tags", ResourceArn=arn),
        }
        skipped = 0
        if self.add_node(SECURITYHUB_HUB, arn, str(fields["name"]), fields, region):
            self.hosts(HOSTS_SECURITYHUB_HUB, region, SECURITYHUB_HUB, arn)
            if administrator and administrator != self.account_id:
                self.add_edge(REPORTS_TO_ADMINISTRATOR, SECURITYHUB_HUB, arn, ACCOUNT, administrator, region)
        else:
            skipped = 1
        self.footprint_surface(region, HOSTS_SECURITYHUB_HUB, RELATION_HUBS, read, count=1, skipped=skipped)

    def _access_analyzers(self, region: str) -> None:
        reads: list[_Walk] = []
        analyzers: dict[str, dict[str, Any]] = {}
        unidentified = 0
        for analyzer_type in ANALYZER_TYPES:
            read = self.walk("accessanalyzer", region, "list_analyzers", "analyzers", type=analyzer_type)
            reads.append(read)
            for item in read.items:
                arn = str((item or {}).get("arn") or "")
                if arn:
                    analyzers.setdefault(arn, item)
                else:
                    unidentified += 1
        skipped = unidentified
        for arn in sorted(analyzers):
            item = analyzers[arn]
            kind = str(item.get("type") or "")
            if kind and kind not in ANALYZER_TYPES:
                self.notice(
                    "warn",
                    "UNKNOWN_ENUM_VALUE",
                    f"{arn}: analyzer type {kind!r} is not in the pinned enum; kept verbatim.",
                    value=kind,
                )
            name = str(item.get("name") or arn.rsplit("/", 1)[-1])
            fields = {
                "name": name[:255],
                "analyzer_arn": arn,
                "analyzer_name": name[:255],
                "analyzer_type": kind,
                "status": str(item.get("status") or ""),
                "created_at": _iso(item.get("createdAt")),
                # Field lane: the analyzer's own lowercase `tags` map.
                "tags": normalize_tags(item.get("tags") or {}, "map"),
            }
            if not self.add_node(ACCESS_ANALYZER, arn, name, fields, region):
                skipped += 1
                continue
            self.hosts(HOSTS_ACCESS_ANALYZER, region, ACCESS_ANALYZER, arn)
        combined = _aggregate(reads)
        self.footprint_surface(
            region,
            HOSTS_ACCESS_ANALYZER,
            RELATION_ANALYZERS,
            combined,
            count=sum(len(r.items) for r in reads),
            skipped=skipped,
        )

    # Account settings -----------------------------------------------------

    def _ebs_defaults(self, region: str) -> None:
        """EBS default encryption, once per footprint. ``EbsEncryptionByDefault: false`` is AWS's own
        answer and stored as returned; a failed read is null."""
        enabled, _ = self.call("ec2", region, "get_ebs_encryption_by_default")
        key, _ = self.call("ec2", region, "get_ebs_default_kms_key_id")
        value = (enabled or {}).get("EbsEncryptionByDefault")
        kms = (key or {}).get("KmsKeyId")
        self.result.footprint_fields[region] = {
            "ebs_encryption_by_default": value if isinstance(value, bool) else None,
            "ebs_default_kms_key_id": str(kms) if key is not None and kms is not None else None,
        }

    def _public_access_block(self) -> None:
        """The account-level S3 public-access block, read exactly once per account through
        ``s3control`` in the partition's home region, never per region."""
        if self.unavailable("s3control"):
            self.result.account_fields = {field: None for _, field in _PAB_FIELDS}
            return
        response, read = self.call(
            "s3control",
            home_region(self.partition),
            "get_public_access_block",
            quiet=(NO_PUBLIC_ACCESS_BLOCK,),
            AccountId=self.account_id,
        )
        if response is None:
            if read.code == NO_PUBLIC_ACCESS_BLOCK:
                # No configuration: AWS's own "off", an observed false on all four flags.
                self.result.account_fields = {field: False for _, field in _PAB_FIELDS}
            else:
                self.result.account_fields = {field: None for _, field in _PAB_FIELDS}
            return
        configuration = response.get("PublicAccessBlockConfiguration") or {}
        self.result.account_fields = {
            field: configuration.get(key) if isinstance(configuration.get(key), bool) else None
            for key, field in _PAB_FIELDS
        }


def collect_landing_zone(
    client_for: Callable[[str, str], Any],
    *,
    account_id: str,
    partition: str,
    regions: list[str],
    facts: dict[str, RegionFacts],
    member_accounts: list[str] | None,
    sensitivity: dict[str, dict[str, Any]] | None = None,
) -> LandingZoneRead:
    """Read the landing zone's governance surface; never raises for an AWS failure.

    ``client_for(service, region)`` builds a client. ``member_accounts`` is the organization's
    complete account list (``OrganizationTree.member_accounts``), or None when it was not read to
    the end. ``sensitivity`` replaces ``reader_sensitivity(READER)`` (tests only).
    """
    return _Reader(
        client_for,
        account_id=account_id,
        partition=partition,
        regions=regions,
        facts=facts,
        member_accounts=member_accounts,
        sensitivity=sensitivity,
    ).collect()


__all__ = [
    "ANALYZER_TYPES",
    "CONTAINMENT_SURFACES",
    "PAGINATED_OPERATIONS",
    "READER",
    "SINGLE_OPERATIONS",
    "LandingZoneRead",
    "assignment_key",
    "bucket_arn",
    "collect_landing_zone",
    "continuation_token",
    "group_key",
    "region_of_arn",
    "regional_key",
    "target_of",
]
