"""Landing-zone governance, collect-only (aws-core-tap#66, spec-aws-core-landing-zone.md).

Three layers, as in ``test_organizations_completeness.py``: the reader against a canned, PAGINATING
fake of every service it calls (no grid); one run of the real ``Boto3Collector`` over the same fake,
whose batch the grid must accept; and the thirteen new falsifiers against real grid rows and a fake
client. The fixture is shaped on a GovCloud management account (partition ``aws-us-gov``, regions
``us-gov-west-1`` and ``us-gov-east-1``); every response is canned and no AWS call is made.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector import partition as partition_mod
from tap_plugin.aws_core.collectors.boto3_collector.containment import footprint_ref
from tap_plugin.aws_core.collectors.boto3_collector.identity import node_ref
from tap_plugin.aws_core.collectors.boto3_collector.landing_zone import (
    ACCESS_ANALYZER,
    ACCOUNT_ASSIGNMENT,
    ANALYZER_TYPES,
    APPLIES_TO_TARGET,
    CONFIG_AGGREGATOR,
    CONFIG_DELIVERY_CHANNEL,
    CONFIG_RECORDER,
    CONTAINMENT_SURFACES,
    ENABLED_BASELINE,
    ENABLED_CONTROL,
    FOOTPRINT,
    GRANTED_TO_GROUP,
    GRANTS_ACCESS_TO_ACCOUNT,
    GRANTS_PERMISSION_SET,
    GUARDDUTY_DETECTOR,
    HOLDS_ACCOUNT_ASSIGNMENT,
    HOLDS_ENABLED_BASELINE,
    HOLDS_ENABLED_CONTROL,
    HOLDS_IDENTITY_GROUP,
    HOLDS_PERMISSION_SET,
    HOSTS_ACCESS_ANALYZER,
    HOSTS_CONFIG_RECORDER,
    HOSTS_GUARDDUTY_DETECTOR,
    HOSTS_IDENTITY_CENTER_INSTANCE,
    HOSTS_LANDING_ZONE,
    HOSTS_SECURITYHUB_HUB,
    IDENTITY_CENTER_INSTANCE,
    IDENTITY_GROUP,
    LANDING_ZONE,
    PAGINATED_OPERATIONS,
    PERMISSION_SET,
    READER,
    REPORTS_TO_ADMINISTRATOR,
    SECURITYHUB_HUB,
    SINGLE_OPERATIONS,
    WRITES_LOGS,
    LandingZoneRead,
    assignment_key,
    collect_landing_zone,
    continuation_token,
    group_key,
    regional_key,
    target_of,
)
from tap_plugin.aws_core.collectors.boto3_collector.regions import STATUS_DISABLED, STATUS_ENABLED, RegionFacts
from tap_plugin.aws_core.falsifiers import (
    AccessAnalyzerFalsifier,
    AccountAssignmentFalsifier,
    ConfigAggregatorFalsifier,
    ConfigDeliveryChannelFalsifier,
    ConfigRecorderFalsifier,
    EnabledBaselineFalsifier,
    EnabledControlFalsifier,
    GuardDutyDetectorFalsifier,
    IdentityCenterInstanceFalsifier,
    IdentityGroupFalsifier,
    LandingZoneFalsifier,
    PermissionSetFalsifier,
    SecurityHubHubFalsifier,
)
from tap_plugin.aws_core.regional import LANDING_ZONE_CHILDREN
from tap_plugin.aws_core.tests.grid_keys import node_id

from tap_grid.falsifier_testing import CASE_DROPPED, CASE_FORBIDDEN, CASE_PRESENT, CASE_REIDENTIFIED, run_four_cases
from tap_grid.falsifiers import (
    DROPPED_FROM_OBSERVATION,
    PRESENT_AT_PROBE,
    UNDETERMINED,
    Candidate,
    FalsifyContext,
    unsupported,
)
from tap_grid.services import create_node, get_node

PARTITION = "aws-us-gov"
WEST = "us-gov-west-1"
EAST = "us-gov-east-1"
REGIONS = [WEST, EAST]
MGMT = "111111111111"
SECURITY = "222222222222"
WORKLOAD = "333333333333"
ORG_ID = "o-02tvy5y4l7"
OU_ID = "ou-0vv8-level3aa"

LZ_ARN = f"arn:{PARTITION}:controltower:{WEST}:{MGMT}:landingzone/1A2B3C4D5E6F7G8H"
CONTROL_OU = f"arn:{PARTITION}:controltower:{WEST}:{MGMT}:enabledcontrol/OUCONTROL1"
CONTROL_ACCOUNT = f"arn:{PARTITION}:controltower:{WEST}:{MGMT}:enabledcontrol/ACCTCONTROL1"
CONTROL_PAGE2 = f"arn:{PARTITION}:controltower:{WEST}:{MGMT}:enabledcontrol/PAGETWO1"
BASELINE_PARENT = f"arn:{PARTITION}:controltower:{WEST}:{MGMT}:enabledbaseline/PARENTBASELINE"
BASELINE_CHILD = f"arn:{PARTITION}:controltower:{WEST}:{MGMT}:enabledbaseline/CHILDBASELINE"
OU_TARGET = f"arn:{PARTITION}:organizations::{MGMT}:ou/{ORG_ID}/{OU_ID}"
ACCOUNT_TARGET = f"arn:{PARTITION}:organizations::{MGMT}:account/{ORG_ID}/{WORKLOAD}"

INSTANCE_ARN = f"arn:{PARTITION}:sso:::instance/ssoins-7907a1b2c3d4e5f6"
STORE_ID = "d-9067abcdef"
PS_ADMIN = f"arn:{PARTITION}:sso:::permissionSet/ssoins-7907a1b2c3d4e5f6/ps-1111111111111111"
PS_READ = f"arn:{PARTITION}:sso:::permissionSet/ssoins-7907a1b2c3d4e5f6/ps-2222222222222222"
GROUP_ADMINS = "9067abcd-1111-2222-3333-444455556666"
USER_ID = "9067abcd-aaaa-bbbb-cccc-ddddeeeeffff"

RECORDER_ARN = f"arn:{PARTITION}:config:{WEST}:{MGMT}:configuration-recorder/default/aaaa1111"
LINKED_RECORDER_ARN = (
    f"arn:{PARTITION}:config:{WEST}:{MGMT}:configuration-recorder/AWSConfigurationRecorderForSecurityHub/bbbb2222"
)
AGGREGATOR_ARN = f"arn:{PARTITION}:config:{WEST}:{MGMT}:config-aggregator/config-aggregator-abc12345"
DETECTOR_ID = "12abc34d567e8fa901bc2d34e56789f0"
HUB_ARN = f"arn:{PARTITION}:securityhub:{WEST}:{MGMT}:hub/default"
ANALYZER_ARN = f"arn:{PARTITION}:access-analyzer:{WEST}:{MGMT}:analyzer/OrgAnalyzer"
UNUSED_ANALYZER_ARN = f"arn:{PARTITION}:access-analyzer:{WEST}:{MGMT}:analyzer/UnusedAccess"
BUCKET = "aws-controltower-logs-111111111111-us-gov-west-1"


def _err(code: str, op: str = "Op") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, op)


def _facts(status: str = STATUS_ENABLED) -> dict[str, RegionFacts]:
    return {r: RegionFacts(r, PARTITION, "opt-in-not-required", status, "test") for r in REGIONS}


class FakeAws:
    """Every client the reader asks for. A handler is registered per (service, operation), optionally
    per region; it is called with the call's kwargs. ``paged`` builds one that PAGINATES, so a test
    can fail page two of any listing. An unregistered operation answers ``{}``."""

    def __init__(self) -> None:
        self.handlers: dict[tuple[str, str, str | None], Callable[[str, dict[str, Any]], Any]] = {}
        self.calls: list[tuple[str, str, str, dict[str, Any]]] = []

    def on(self, service: str, operation: str, answer: Any, *, region: str | None = None) -> None:
        """``answer`` is a handler, an exception to raise, or a response to return."""

        def constant(_region: str, _kw: dict[str, Any]) -> Any:
            if isinstance(answer, Exception):
                raise answer
            return answer

        self.handlers[(service, operation, region)] = answer if callable(answer) else constant

    def client_for(self, service: str, region: str) -> Any:
        return _FakeClient(self, service, region)

    def ops(self, service: str | None = None) -> list[str]:
        return [op for svc, _r, op, _kw in self.calls if service in (None, svc)]


class _NoPages:
    def paginate(self, **_kw: Any) -> Any:
        return iter(())


class _FakeClient:
    def __init__(self, aws: FakeAws, service: str, region: str) -> None:
        self._aws, self._service, self._region = aws, service, region

    def can_paginate(self, _operation: str) -> bool:
        return False

    def get_paginator(self, _operation: str) -> _NoPages:
        return _NoPages()

    def __getattr__(self, operation: str) -> Any:
        def call(**kwargs: Any) -> Any:
            self._aws.calls.append((self._service, self._region, operation, dict(kwargs)))
            handler = self._aws.handlers.get((self._service, operation, self._region)) or self._aws.handlers.get(
                (self._service, operation, None)
            )
            return {} if handler is None else handler(self._region, kwargs)

        return call


def paged(result_key: str, *pages: Any, token: str = "NextToken") -> Callable[[str, dict[str, Any]], Any]:
    def handler(_region: str, kwargs: dict[str, Any]) -> Any:
        index = int(kwargs.get(token) or 0)
        page = pages[index]
        if isinstance(page, Exception):
            raise page
        response: dict[str, Any] = {result_key: page}
        if index + 1 < len(pages):
            response[token] = str(index + 1)
        return response

    return handler


def by(key: Callable[[dict[str, Any]], Any], table: dict[Any, Any]) -> Callable[[str, dict[str, Any]], Any]:
    def handler(region: str, kwargs: dict[str, Any]) -> Any:
        found = table.get(key(kwargs))
        if found is None:
            return {}
        if isinstance(found, Exception):
            raise found
        return found(region, kwargs) if callable(found) else found

    return handler


def govcloud() -> FakeAws:
    """A GovCloud management account with Control Tower, Identity Center and the security services
    turned on in us-gov-west-1."""
    aws = FakeAws()
    # Control Tower: the landing zone lives in us-gov-west-1; us-gov-east-1's endpoint lists it too.
    aws.on("controltower", "list_landing_zones", paged("landingZones", [{"arn": LZ_ARN}], token="nextToken"))
    aws.on(
        "controltower",
        "get_landing_zone",
        {
            "landingZone": {
                "arn": LZ_ARN,
                "version": "3.3",
                "latestAvailableVersion": "4.0",
                "status": "ACTIVE",
                "driftStatus": {"status": "IN_SYNC"},
                "manifest": {"governedRegions": [EAST, WEST], "securityRoles": {"accountId": SECURITY}},
            }
        },
    )
    aws.on(
        "controltower",
        "list_enabled_controls",
        paged(
            "enabledControls",
            [
                {
                    "arn": CONTROL_OU,
                    "controlIdentifier": f"arn:{PARTITION}:controlcatalog:::control/denyroot",
                    "targetIdentifier": OU_TARGET,
                    "statusSummary": {"status": "SUCCEEDED"},
                    "driftStatusSummary": {"driftStatus": "IN_SYNC"},
                },
                {
                    "arn": CONTROL_ACCOUNT,
                    "controlIdentifier": f"arn:{PARTITION}:controlcatalog:::control/s3block",
                    "targetIdentifier": ACCOUNT_TARGET,
                    "statusSummary": {"status": "SUCCEEDED"},
                },
            ],
            [{"arn": CONTROL_PAGE2, "controlIdentifier": "c3", "targetIdentifier": OU_TARGET}],
            token="nextToken",
        ),
    )
    aws.on(
        "controltower",
        "list_enabled_baselines",
        paged(
            "enabledBaselines",
            [
                {
                    "arn": BASELINE_PARENT,
                    "baselineIdentifier": f"arn:{PARTITION}:controltower:{WEST}::baseline/AWSControlTowerBaseline",
                    "baselineVersion": "4.0",
                    "targetIdentifier": OU_TARGET,
                    "statusSummary": {"status": "SUCCEEDED"},
                    "driftStatusSummary": {"types": {"inheritance": {"status": "IN_SYNC"}}},
                },
                {
                    "arn": BASELINE_CHILD,
                    "baselineIdentifier": f"arn:{PARTITION}:controltower:{WEST}::baseline/AWSControlTowerBaseline",
                    "baselineVersion": "4.0",
                    "targetIdentifier": ACCOUNT_TARGET,
                    "parentIdentifier": BASELINE_PARENT,
                    "statusSummary": {"status": "SUCCEEDED"},
                },
            ],
            token="nextToken",
        ),
    )
    aws.on(
        "controltower",
        "list_tags_for_resource",
        lambda _r, kw: (
            {"tags": {"aws-control-tower": "managed-by-control-tower"}} if kw["resourceArn"] == LZ_ARN else {"tags": {}}
        ),
    )
    # Identity Center: one instance, primary in us-gov-west-1 (GovCloud has no multi-region, so the
    # response names no Regions).
    instance = {
        "InstanceArn": INSTANCE_ARN,
        "IdentityStoreId": STORE_ID,
        "OwnerAccountId": MGMT,
        "Name": "gov-sso",
        "Status": "ACTIVE",
        "PrimaryRegion": WEST,
    }
    aws.on("sso-admin", "list_instances", paged("Instances", [instance]), region=WEST)
    aws.on(
        "sso-admin",
        "list_tags_for_resource",
        lambda _r, kw: (
            {"Tags": [{"Key": "owner", "Value": "platform"}]} if kw["ResourceArn"] == INSTANCE_ARN else {"Tags": []}
        ),
    )
    aws.on("sso-admin", "list_permission_sets", paged("PermissionSets", [PS_ADMIN], [PS_READ]))
    aws.on(
        "sso-admin",
        "describe_permission_set",
        by(
            lambda kw: kw["PermissionSetArn"],
            {
                PS_ADMIN: {
                    "PermissionSet": {
                        "Name": "AWSAdministratorAccess",
                        "PermissionSetArn": PS_ADMIN,
                        "SessionDuration": "PT1H",
                    }
                },
                PS_READ: {"PermissionSet": {"Name": "GWReadOnly", "PermissionSetArn": PS_READ, "Description": "read"}},
            },
        ),
    )
    aws.on(
        "sso-admin",
        "list_managed_policies_in_permission_set",
        by(
            lambda kw: kw["PermissionSetArn"],
            {
                PS_ADMIN: paged(
                    "AttachedManagedPolicies",
                    [{"Name": "AdministratorAccess", "Arn": f"arn:{PARTITION}:iam::aws:policy/AdministratorAccess"}],
                    [{"Name": "Billing", "Arn": f"arn:{PARTITION}:iam::aws:policy/job-function/Billing"}],
                ),
                PS_READ: paged(
                    "AttachedManagedPolicies",
                    [{"Name": "ReadOnlyAccess", "Arn": f"arn:{PARTITION}:iam::aws:policy/ReadOnlyAccess"}],
                ),
            },
        ),
    )
    aws.on(
        "identitystore",
        "list_groups",
        paged(
            "Groups",
            [
                {
                    "GroupId": GROUP_ADMINS,
                    "IdentityStoreId": STORE_ID,
                    "DisplayName": "AWSControlTowerAdmins",
                    "ExternalIds": [{"Issuer": "https://scim.example", "Id": "okta-00g1"}],
                }
            ],
        ),
    )
    aws.on(
        "sso-admin",
        "list_permission_sets_provisioned_to_account",
        by(
            lambda kw: kw["AccountId"],
            {MGMT: paged("PermissionSets", [PS_ADMIN]), WORKLOAD: paged("PermissionSets", [PS_ADMIN, PS_READ])},
        ),
    )
    aws.on(
        "sso-admin",
        "list_account_assignments",
        by(
            lambda kw: (kw["AccountId"], kw["PermissionSetArn"]),
            {
                (MGMT, PS_ADMIN): paged("AccountAssignments", [_assignment(MGMT, PS_ADMIN, "GROUP", GROUP_ADMINS)]),
                (WORKLOAD, PS_ADMIN): paged(
                    "AccountAssignments", [_assignment(WORKLOAD, PS_ADMIN, "GROUP", GROUP_ADMINS)]
                ),
                (WORKLOAD, PS_READ): paged("AccountAssignments", [], [_assignment(WORKLOAD, PS_READ, "USER", USER_ID)]),
            },
        ),
    )
    # Security services, us-gov-west-1 only; us-gov-east-1 answers empty listings.
    aws.on(
        "config",
        "list_configuration_recorders",
        paged(
            "ConfigurationRecorderSummaries",
            [{"arn": RECORDER_ARN, "name": "default", "recordingScope": "PAID"}],
            [
                {
                    "arn": LINKED_RECORDER_ARN,
                    "name": "AWSConfigurationRecorderForSecurityHub",
                    "servicePrincipal": "securityhub.amazonaws.com",
                    "recordingScope": "INTERNAL",
                }
            ],
        ),
        region=WEST,
    )
    aws.on(
        "config",
        "describe_configuration_recorders",
        lambda _r, kw: {
            "ConfigurationRecorders": [
                {
                    "arn": kw["Arn"],
                    "name": kw["Arn"].split("/")[1],
                    "roleARN": f"arn:{PARTITION}:iam::{MGMT}:role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig",
                    "recordingGroup": {"allSupported": True, "includeGlobalResourceTypes": True},
                    "servicePrincipal": "securityhub.amazonaws.com" if kw["Arn"] == LINKED_RECORDER_ARN else "",
                }
            ]
        },
    )
    aws.on(
        "config",
        "describe_configuration_recorder_status",
        lambda _r, kw: {
            "ConfigurationRecordersStatus": [{"arn": kw["Arn"], "recording": True, "lastStatus": "Success"}]
        },
    )
    aws.on(
        "config",
        "list_tags_for_resource",
        paged("Tags", [{"Key": "aws-control-tower", "Value": "managed-by-control-tower"}]),
    )
    aws.on(
        "config",
        "describe_delivery_channels",
        {
            "DeliveryChannels": [
                {
                    "name": "aws-controltower-BaselineConfigDeliveryChannel",
                    "s3BucketName": BUCKET,
                    "s3KeyPrefix": f"{ORG_ID}",
                }
            ]
        },
        region=WEST,
    )
    aws.on(
        "config",
        "describe_configuration_aggregators",
        paged(
            "ConfigurationAggregators",
            [
                {
                    "ConfigurationAggregatorName": "aws-controltower-GuardrailsComplianceAggregator",
                    "ConfigurationAggregatorArn": AGGREGATOR_ARN,
                    "OrganizationAggregationSource": {
                        "RoleArn": f"arn:{PARTITION}:iam::{MGMT}:role/agg",
                        "AllAwsRegions": True,
                    },
                }
            ],
        ),
        region=WEST,
    )
    aws.on("guardduty", "list_detectors", paged("DetectorIds", [DETECTOR_ID]), region=WEST)
    aws.on(
        "guardduty",
        "get_detector",
        {"Status": "ENABLED", "FindingPublishingFrequency": "SIX_HOURS", "Tags": {"team": "sec"}},
    )
    aws.on(
        "guardduty",
        "get_administrator_account",
        {"Administrator": {"AccountId": SECURITY, "RelationshipStatus": "Enabled"}},
    )
    aws.on(
        "securityhub",
        "describe_hub",
        {
            "HubArn": HUB_ARN,
            "SubscribedAt": "2026-09-01T00:00:00Z",
            "AutoEnableControls": True,
            "ControlFindingGenerator": "SECURITY_CONTROL",
        },
        region=WEST,
    )
    aws.on("securityhub", "describe_hub", _err("InvalidAccessException", "DescribeHub"), region=EAST)
    aws.on(
        "securityhub",
        "get_enabled_standards",
        paged(
            "StandardsSubscriptions",
            [
                {
                    "StandardsArn": f"arn:{PARTITION}:securityhub:{WEST}::standards/aws-foundational-security-best-practices/v/1.0.0",
                    "StandardsStatus": "READY",
                }
            ],
            [
                {
                    "StandardsArn": f"arn:{PARTITION}:securityhub:{WEST}::standards/nist-800-53/v/5.0.0",
                    "StandardsStatus": "READY",
                }
            ],
        ),
    )
    aws.on(
        "securityhub",
        "get_administrator_account",
        {"Administrator": {"AccountId": SECURITY, "MemberStatus": "Enabled"}},
    )
    aws.on("securityhub", "list_tags_for_resource", {"Tags": {}})
    aws.on(
        "accessanalyzer",
        "list_analyzers",
        by(
            lambda kw: kw.get("type"),
            {
                "ORGANIZATION": paged(
                    "analyzers",
                    [
                        {
                            "arn": ANALYZER_ARN,
                            "name": "OrgAnalyzer",
                            "type": "ORGANIZATION",
                            "status": "ACTIVE",
                            "tags": {"k": "v"},
                        }
                    ],
                    token="nextToken",
                ),
                "ORGANIZATION_UNUSED_ACCESS": paged(
                    "analyzers",
                    [
                        {
                            "arn": UNUSED_ANALYZER_ARN,
                            "name": "UnusedAccess",
                            "type": "ORGANIZATION_UNUSED_ACCESS",
                            "status": "ACTIVE",
                        }
                    ],
                    token="nextToken",
                ),
            },
        ),
        region=WEST,
    )
    aws.on("ec2", "get_ebs_encryption_by_default", {"EbsEncryptionByDefault": True}, region=WEST)
    aws.on("ec2", "get_ebs_encryption_by_default", {"EbsEncryptionByDefault": False}, region=EAST)
    aws.on("ec2", "get_ebs_default_kms_key_id", {"KmsKeyId": "alias/aws/ebs"})
    aws.on(
        "s3control",
        "get_public_access_block",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": False,
            }
        },
    )
    return aws


def _assignment(account: str, permission_set: str, principal_type: str, principal_id: str) -> dict[str, str]:
    return {
        "AccountId": account,
        "PermissionSetArn": permission_set,
        "PrincipalType": principal_type,
        "PrincipalId": principal_id,
    }


def collect(
    aws: FakeAws, *, members: list[str] | None = None, facts: dict[str, RegionFacts] | None = None, **kw: Any
) -> LandingZoneRead:
    return collect_landing_zone(
        aws.client_for,
        account_id=MGMT,
        partition=PARTITION,
        regions=kw.pop("regions", REGIONS),
        facts=facts or _facts(),
        member_accounts=[MGMT, WORKLOAD] if members is None else members,
        **kw,
    )


def _nodes(read: LandingZoneRead, entity_type: str) -> list[dict[str, Any]]:
    return [n for n in read.nodes if n["entity"]["entity_type"] == entity_type]


def _one(read: LandingZoneRead, entity_type: str) -> dict[str, Any]:
    [node] = _nodes(read, entity_type)
    return node["node"]


def _edges(read: LandingZoneRead, edge_type: str) -> list[tuple[str, str]]:
    return [
        (e["edge"]["from_ref"], e["edge"]["to_ref"])
        for e in read.edges
        if e["edge"]["edge_type"] == edge_type
    ]


def _id(entity_type: str, key: str) -> str:
    return node_ref(entity_type, key)


def _fp(region: str) -> str:
    return footprint_ref(MGMT, region)


def _regional(read: LandingZoneRead, edge_type: str, region: str) -> dict[str, Any]:
    [surface] = [s for s in read.regional_surfaces if s["edge_type"] == edge_type and s["subject"] == _fp(region)]
    return surface


def _parent(read: LandingZoneRead, edge_type: str, subject: str) -> Any:
    [listing] = [s for s in read.listings if s.edge_type == edge_type and s.subject == subject]
    return listing


def _codes(read: LandingZoneRead) -> list[str]:
    return [n.code for n in read.notices]


# ---------------------------------------------------------------------------
# Control Tower
# ---------------------------------------------------------------------------


class TestControlTower:
    @pytest.mark.spec("req-aws-landing-zone-control-tower-1", "req-aws-landing-zone-control-tower-4")
    def test_landing_zone_is_one_node_under_its_home_footprint(self) -> None:
        read = collect(govcloud())
        lz = _one(read, LANDING_ZONE)
        assert (lz["version"], lz["status"], lz["drift_status"], lz["home_region"]) == (
            "3.3",
            "ACTIVE",
            "IN_SYNC",
            WEST,
        )
        assert lz["governed_regions"] == [EAST, WEST]
        assert lz["tags"] == {"aws-control-tower": "managed-by-control-tower"}
        assert _edges(read, HOSTS_LANDING_ZONE) == [(_fp(WEST), _id(LANDING_ZONE, LZ_ARN))]
        # Both regional endpoints listed it: west hosts it, east observed it without hosting it.
        assert _regional(read, HOSTS_LANDING_ZONE, WEST)["enumeration_complete"] is True
        east = _regional(read, HOSTS_LANDING_ZONE, EAST)
        assert east["enumeration_complete"] is True and "includes_shared" in east["reasons"]["count_observed"]

    @pytest.mark.spec("req-aws-landing-zone-control-tower-1")
    def test_no_landing_zone_writes_none_and_says_so(self) -> None:
        aws = govcloud()
        aws.on("controltower", "list_landing_zones", paged("landingZones", [], token="nextToken"))
        read = collect(aws)
        assert _nodes(read, LANDING_ZONE) == []
        surface = _regional(read, HOSTS_LANDING_ZONE, WEST)
        assert (surface["enumeration_complete"], surface["count_observed"]) == (True, 0)
        assert "list_enabled_controls" not in aws.ops("controltower")

    @pytest.mark.spec(
        "req-aws-landing-zone-control-tower-2", "req-aws-core-contained-type-triple-6", "req-aws-collector-pagination-1"
    )
    def test_controls_and_baselines_read_their_full_set(self) -> None:
        aws = govcloud()
        read = collect(aws)
        for op in ("list_enabled_controls", "list_enabled_baselines"):
            kwargs = [kw for svc, _r, o, kw in aws.calls if o == op]
            assert kwargs and all(kw.get("includeChildren") is True for kw in kwargs), op
            assert all("targetIdentifier" not in kw and "filter" not in kw for kw in kwargs), op
        # A control on a nested OU, one on an account, and one on the listing's second page.
        controls = {n["node"]["enabled_control_arn"] for n in _nodes(read, ENABLED_CONTROL)}
        assert controls == {CONTROL_OU, CONTROL_ACCOUNT, CONTROL_PAGE2}
        targets = set(_edges(read, APPLIES_TO_TARGET))
        assert (_id(ENABLED_CONTROL, CONTROL_OU), _id("aws_core__aws_organizational_unit", OU_ID)) in targets
        assert (_id(ENABLED_CONTROL, CONTROL_ACCOUNT), _id("aws_core__aws_account", WORKLOAD)) in targets
        child = next(
            n["node"] for n in _nodes(read, ENABLED_BASELINE) if n["node"]["enabled_baseline_arn"] == BASELINE_CHILD
        )
        assert child["parent_identifier"] == BASELINE_PARENT
        assert (_id(ENABLED_BASELINE, BASELINE_CHILD), _id("aws_core__aws_account", WORKLOAD)) in targets
        assert len(_edges(read, HOLDS_ENABLED_CONTROL)) == 3 and len(_edges(read, HOLDS_ENABLED_BASELINE)) == 2
        for edge in (HOLDS_ENABLED_CONTROL, HOLDS_ENABLED_BASELINE):
            listing = _parent(read, edge, _id(LANDING_ZONE, LZ_ARN))
            assert listing.complete is True and listing.admitted is True

    @pytest.mark.spec("req-aws-collector-pagination-2", "req-aws-core-contained-type-triple-3")
    def test_failed_second_page_keeps_page_one_and_is_incomplete(self) -> None:
        aws = govcloud()
        aws.on(
            "controltower",
            "list_enabled_controls",
            paged(
                "enabledControls",
                [{"arn": CONTROL_OU, "targetIdentifier": OU_TARGET}],
                _err("ThrottlingException"),
                token="nextToken",
            ),
        )
        read = collect(aws)
        assert [n["node"]["enabled_control_arn"] for n in _nodes(read, ENABLED_CONTROL)] == [CONTROL_OU]
        listing = _parent(read, HOLDS_ENABLED_CONTROL, _id(LANDING_ZONE, LZ_ARN))
        assert listing.complete is False and listing.count is None

    @pytest.mark.spec("req-aws-landing-zone-availability-2")
    def test_unverified_baseline_api_failure_is_failed_with_the_partition_hint(self) -> None:
        aws = govcloud()
        aws.on("controltower", "list_enabled_baselines", _err("ValidationException", "ListEnabledBaselines"))
        read = collect(aws)
        listing = _parent(read, HOLDS_ENABLED_BASELINE, _id(LANDING_ZONE, LZ_ARN))
        assert listing.complete is False
        failed = [
            n
            for n in read.notices
            if n.code == "LANDING_ZONE_READ_FAILED" and n.data.get("operation") == "list_enabled_baselines"
        ]
        assert failed and "not verified" in failed[0].message

    @pytest.mark.spec("req-aws-landing-zone-control-tower-3", "req-aws-collector-tags-15")
    def test_denied_tag_read_withholds_the_landing_zone_and_withdraws_admitted(self) -> None:
        aws = govcloud()
        aws.on("controltower", "list_tags_for_resource", _err("AccessDeniedException"))
        read = collect(aws)
        assert _nodes(read, LANDING_ZONE) == []
        surface = _regional(read, HOSTS_LANDING_ZONE, WEST)
        assert surface["enumeration_complete"] is True and surface["admitted"] is False
        assert "LANDING_ZONE_TAGS_DENIED" in _codes(read)

    @pytest.mark.spec("req-aws-core-contained-type-triple-3")
    def test_two_listed_landing_zones_leave_the_survivor_incomplete(self) -> None:
        """Ambiguity is decided by what was LISTED, not by what could be written: a second landing
        zone whose GetLandingZone fails still makes the unscoped child listings unattributable."""
        aws = govcloud()
        other = f"arn:{PARTITION}:controltower:{WEST}:{MGMT}:landingzone/SECONDLZ00000000"
        aws.on(
            "controltower",
            "list_landing_zones",
            paged("landingZones", [{"arn": LZ_ARN}, {"arn": other}], token="nextToken"),
        )
        good = govcloud().handlers[("controltower", "get_landing_zone", None)]
        aws.on(
            "controltower",
            "get_landing_zone",
            by(lambda kw: kw["landingZoneIdentifier"], {LZ_ARN: good, other: _err("InternalServerException")}),
        )
        read = collect(aws)
        assert [n["node"]["landing_zone_arn"] for n in _nodes(read, LANDING_ZONE)] == [LZ_ARN]
        for edge in (HOLDS_ENABLED_CONTROL, HOLDS_ENABLED_BASELINE):
            listing = _parent(read, edge, _id(LANDING_ZONE, LZ_ARN))
            assert listing.complete is False and listing.admitted is False
        assert _nodes(read, ENABLED_CONTROL) == [] and "list_enabled_controls" not in aws.ops("controltower")
        assert "LANDING_ZONE_AMBIGUOUS" in _codes(read)

    @pytest.mark.spec("req-aws-core-contained-type-triple-3")
    def test_a_listed_item_with_no_identity_withdraws_admitted(self) -> None:
        aws = govcloud()
        aws.on(
            "controltower",
            "list_enabled_controls",
            paged(
                "enabledControls",
                [{"arn": CONTROL_OU, "targetIdentifier": OU_TARGET}, {"controlIdentifier": "no-arn"}],
                token="nextToken",
            ),
        )
        aws.on("guardduty", "list_detectors", paged("DetectorIds", [DETECTOR_ID, ""]), region=WEST)
        read = collect(aws)
        controls = _parent(read, HOLDS_ENABLED_CONTROL, _id(LANDING_ZONE, LZ_ARN))
        assert controls.complete is True and controls.admitted is False
        detectors = _regional(read, HOSTS_GUARDDUTY_DETECTOR, WEST)
        assert detectors["enumeration_complete"] is True and detectors["admitted"] is False

    def test_home_region_out_of_scope_is_written_without_containment(self) -> None:
        read = collect(govcloud(), regions=[EAST], facts={EAST: RegionFacts(EAST, PARTITION, "", STATUS_ENABLED, "t")})
        assert _one(read, LANDING_ZONE)["home_region"] == WEST
        assert _edges(read, HOSTS_LANDING_ZONE) == []
        assert "LANDING_ZONE_HOME_REGION_OUT_OF_SCOPE" in _codes(read)

    @pytest.mark.spec("req-aws-core-reference-derivation-3")
    @pytest.mark.parametrize(
        ("target", "expected"),
        [
            (OU_TARGET, ("aws_core__aws_organizational_unit", OU_ID)),
            (ACCOUNT_TARGET, ("aws_core__aws_account", WORKLOAD)),
            (
                f"arn:aws:organizations::{MGMT}:ou/{ORG_ID}/ou-abcd-12345678",
                ("aws_core__aws_organizational_unit", "ou-abcd-12345678"),
            ),
            (f"arn:{PARTITION}:organizations::{MGMT}:root/{ORG_ID}/r-0vv8", None),
            ("not-an-arn", None),
        ],
    )
    def test_target_identifier_normalizes_to_the_target_key(self, target: str, expected: Any) -> None:
        assert target_of(target) == expected


# ---------------------------------------------------------------------------
# Identity Center
# ---------------------------------------------------------------------------


class TestIdentityCenter:
    @pytest.mark.spec("req-aws-landing-zone-identity-center-1")
    def test_instance_collected_with_its_primary_region(self) -> None:
        read = collect(govcloud())
        instance = _one(read, IDENTITY_CENTER_INSTANCE)
        assert (instance["home_region"], instance["identity_store_id"], instance["owner_account_id"]) == (
            WEST,
            STORE_ID,
            MGMT,
        )
        assert instance["regions"] is None, "GovCloud reports no Regions: not read, never an empty list"
        assert instance["tags"] == {"owner": "platform"}
        assert _edges(read, HOSTS_IDENTITY_CENTER_INSTANCE) == [
            (_fp(WEST), _id(IDENTITY_CENTER_INSTANCE, INSTANCE_ARN))
        ]

    @pytest.mark.spec("req-aws-landing-zone-identity-center-1")
    def test_multi_region_instance_is_one_node_from_its_primary_footprint(self) -> None:
        aws = govcloud()
        replicated = {
            "InstanceArn": INSTANCE_ARN,
            "IdentityStoreId": STORE_ID,
            "OwnerAccountId": MGMT,
            "PrimaryRegion": EAST,
            "Regions": [{"RegionName": WEST, "IsPrimaryRegion": False}, {"RegionName": EAST, "IsPrimaryRegion": True}],
        }
        aws.on("sso-admin", "list_instances", paged("Instances", [replicated]), region=WEST)
        aws.on("sso-admin", "list_instances", paged("Instances", [replicated]), region=EAST)
        read = collect(aws)
        instance = _one(read, IDENTITY_CENTER_INSTANCE)
        assert (instance["home_region"], instance["regions"]) == (EAST, [EAST, WEST])
        assert _edges(read, HOSTS_IDENTITY_CENTER_INSTANCE) == [
            (_fp(EAST), _id(IDENTITY_CENTER_INSTANCE, INSTANCE_ARN))
        ]
        assert "not_hosted" not in json.dumps(_regional(read, HOSTS_IDENTITY_CENTER_INSTANCE, EAST)["reasons"])
        assert "includes_shared" in _regional(read, HOSTS_IDENTITY_CENTER_INSTANCE, WEST)["reasons"]["count_observed"]
        # Children are read once, through the primary region.
        assert {r for svc, r, op, _ in aws.calls if op == "list_permission_sets"} == {EAST}

    @pytest.mark.spec("req-aws-landing-zone-identity-center-7")
    def test_primary_region_outside_the_scope_is_written_without_containment(self) -> None:
        """The case aws-core-tap#66 settles: ListInstances in an allowed secondary region returns
        an instance whose PrimaryRegion has no footprint this run."""
        aws = govcloud()
        aws.on(
            "sso-admin",
            "list_instances",
            paged(
                "Instances",
                [
                    {
                        "InstanceArn": INSTANCE_ARN,
                        "IdentityStoreId": STORE_ID,
                        "OwnerAccountId": MGMT,
                        "PrimaryRegion": "us-east-1",
                    }
                ],
            ),
            region=WEST,
        )
        read = collect(aws)
        assert _one(read, IDENTITY_CENTER_INSTANCE)["home_region"] == "us-east-1"
        [node] = _nodes(read, IDENTITY_CENTER_INSTANCE)
        assert node["entity"]["dimensions"]["aws_region"] == WEST, "stamped with the region it was read through"
        assert _edges(read, HOSTS_IDENTITY_CENTER_INSTANCE) == []
        warning = next(n for n in read.notices if n.code == "IDENTITY_CENTER_PRIMARY_REGION_OUT_OF_SCOPE")
        assert warning.level == "warn" and warning.data == {"primary_region": "us-east-1", "read_region": WEST}
        west = _regional(read, HOSTS_IDENTITY_CENTER_INSTANCE, WEST)
        assert west["enumeration_complete"] is True and "includes_shared" in west["reasons"]["count_observed"]
        # Its children are still read, through the region that returned it, under the instance.
        assert {r for svc, r, op, _ in aws.calls if op == "list_permission_sets"} == {WEST}
        assert _parent(read, HOLDS_PERMISSION_SET, _id(IDENTITY_CENTER_INSTANCE, INSTANCE_ARN)).complete is True

    @pytest.mark.spec("req-aws-collector-pagination-1", "req-aws-collector-pagination-2")
    def test_managed_policies_read_both_pages_and_a_failed_page_is_null(self) -> None:
        read = collect(govcloud())
        admin = next(n["node"] for n in _nodes(read, PERMISSION_SET) if n["node"]["permission_set_arn"] == PS_ADMIN)
        assert admin["managed_policy_arns"] == [
            f"arn:{PARTITION}:iam::aws:policy/AdministratorAccess",
            f"arn:{PARTITION}:iam::aws:policy/job-function/Billing",
        ]
        aws = govcloud()
        aws.on(
            "sso-admin",
            "list_managed_policies_in_permission_set",
            paged(
                "AttachedManagedPolicies",
                [{"Arn": f"arn:{PARTITION}:iam::aws:policy/AdministratorAccess"}],
                _err("ThrottlingException"),
            ),
        )
        read = collect(aws)
        assert {n["node"]["managed_policy_arns"] is None for n in _nodes(read, PERMISSION_SET)} == {True}

    def test_permission_sets_across_pages_are_contained(self) -> None:
        read = collect(govcloud())
        assert {n["node"]["permission_set_arn"] for n in _nodes(read, PERMISSION_SET)} == {PS_ADMIN, PS_READ}
        assert len(_edges(read, HOLDS_PERMISSION_SET)) == 2

    def test_groups_are_nodes_with_their_external_ids(self) -> None:
        read = collect(govcloud())
        group = _one(read, IDENTITY_GROUP)
        assert group["external_ids"] == [{"issuer": "https://scim.example", "id": "okta-00g1"}]
        assert group["tags"] == {}
        assert _edges(read, HOLDS_IDENTITY_GROUP) == [
            (_id(IDENTITY_CENTER_INSTANCE, INSTANCE_ARN), _id(IDENTITY_GROUP, group_key(STORE_ID, GROUP_ADMINS)))
        ]

    @pytest.mark.spec(
        "req-aws-landing-zone-identity-center-2",
        "req-aws-landing-zone-identity-center-3",
        "req-aws-core-contained-type-triple-6",
    )
    def test_assignments_answer_which_group_reaches_which_account(self) -> None:
        aws = govcloud()
        read = collect(aws)
        assignments = [n["node"] for n in _nodes(read, ACCOUNT_ASSIGNMENT)]
        assert len(assignments) == 3
        # No identity-store user is read or written: a USER assignment is its principal id only.
        assert "list_users" not in aws.ops("identitystore") and "describe_user" not in aws.ops("identitystore")
        user = next(a for a in assignments if a["principal_type"] == "USER")
        user_key = assignment_key(INSTANCE_ARN, WORKLOAD, PS_READ, "USER", USER_ID)
        assert user["principal_id"] == USER_ID
        assert not [e for e in _edges(read, GRANTED_TO_GROUP) if e[0] == _id(ACCOUNT_ASSIGNMENT, user_key)]
        # Walk the edges: from the group to the accounts it reaches, with the permission set.
        group = _id(IDENTITY_GROUP, group_key(STORE_ID, GROUP_ADMINS))
        via = [a for a, g in _edges(read, GRANTED_TO_GROUP) if g == group]
        reached = {
            (acct, ps)
            for a in via
            for a2, acct in _edges(read, GRANTS_ACCESS_TO_ACCOUNT)
            if a2 == a
            for a3, ps in _edges(read, GRANTS_PERMISSION_SET)
            if a3 == a
        }
        admin_ps = _id(PERMISSION_SET, PS_ADMIN)
        assert reached == {
            (_id("aws_core__aws_account", MGMT), admin_ps),
            (_id("aws_core__aws_account", WORKLOAD), admin_ps),
        }
        # ProvisioningStatus is a filter and is never set.
        provisioned = [kw for _s, _r, op, kw in aws.calls if op == "list_permission_sets_provisioned_to_account"]
        assert provisioned and all("ProvisioningStatus" not in kw for kw in provisioned)

    @pytest.mark.spec("req-aws-landing-zone-identity-center-5")
    def test_one_assignment_surface_per_instance_and_one_failed_nested_listing_spoils_it(self) -> None:
        read = collect(govcloud())
        instance = _id(IDENTITY_CENTER_INSTANCE, INSTANCE_ARN)
        surfaces = [s for s in read.listings if s.edge_type == HOLDS_ACCOUNT_ASSIGNMENT]
        assert [s.subject for s in surfaces] == [instance]
        assert surfaces[0].complete is True and surfaces[0].count == 3
        aws = govcloud()
        aws.on(
            "sso-admin",
            "list_account_assignments",
            by(
                lambda kw: (kw["AccountId"], kw["PermissionSetArn"]),
                {
                    (MGMT, PS_ADMIN): paged("AccountAssignments", [_assignment(MGMT, PS_ADMIN, "GROUP", GROUP_ADMINS)]),
                    (WORKLOAD, PS_ADMIN): _err("ThrottlingException"),
                    (WORKLOAD, PS_READ): paged("AccountAssignments", [_assignment(WORKLOAD, PS_READ, "USER", USER_ID)]),
                },
            ),
        )
        read = collect(aws)
        [surface] = [s for s in read.listings if s.edge_type == HOLDS_ACCOUNT_ASSIGNMENT]
        assert surface.complete is False and surface.admitted is False
        assert "ThrottlingException" in surface.reasons["enumeration_complete"]

    @pytest.mark.spec("req-aws-landing-zone-identity-center-5")
    def test_unknown_account_set_is_incomplete(self) -> None:
        read = collect_landing_zone(
            govcloud().client_for,
            account_id=MGMT,
            partition=PARTITION,
            regions=REGIONS,
            facts=_facts(),
            member_accounts=None,
        )
        surface = _parent(read, HOLDS_ACCOUNT_ASSIGNMENT, _id(IDENTITY_CENTER_INSTANCE, INSTANCE_ARN))
        assert surface.complete is False and "ListAccounts" in surface.reasons["enumeration_complete"]
        assert _nodes(read, ACCOUNT_ASSIGNMENT) == []


# ---------------------------------------------------------------------------
# Security services and account settings
# ---------------------------------------------------------------------------


class TestSecurityServices:
    @pytest.mark.spec("req-aws-core-contained-type-triple-6", "req-aws-landing-zone-security-services-1")
    def test_customer_managed_and_service_linked_recorders_appear(self) -> None:
        aws = govcloud()
        read = collect(aws)
        recorders = {n["node"]["recorder_arn"]: n["node"] for n in _nodes(read, CONFIG_RECORDER)}
        assert set(recorders) == {RECORDER_ARN, LINKED_RECORDER_ARN}
        assert recorders[LINKED_RECORDER_ARN]["service_principal"] == "securityhub.amazonaws.com"
        assert recorders[RECORDER_ARN]["recording"] is True
        assert recorders[RECORDER_ARN]["tags"] == {"aws-control-tower": "managed-by-control-tower"}
        # Described by ARN, never by DescribeConfigurationRecorders with no name.
        described = [kw for _s, _r, op, kw in aws.calls if op == "describe_configuration_recorders"]
        assert described and all("Arn" in kw for kw in described)
        assert _regional(read, HOSTS_CONFIG_RECORDER, WEST)["enumeration_complete"] is True

    @pytest.mark.spec("req-aws-landing-zone-security-services-1")
    def test_denied_recorder_status_is_unknown_never_off(self) -> None:
        aws = govcloud()
        aws.on("config", "describe_configuration_recorder_status", _err("AccessDeniedException"))
        read = collect(aws)
        assert {n["node"]["recording"] for n in _nodes(read, CONFIG_RECORDER)} == {None}

    @pytest.mark.spec("req-aws-core-reference-derivation-3")
    def test_delivery_channel_writes_to_the_bucket_keyed_in_the_run_partition(self) -> None:
        read = collect(govcloud())
        key = regional_key(MGMT, WEST, "aws-controltower-BaselineConfigDeliveryChannel")
        assert _one(read, CONFIG_DELIVERY_CHANNEL)["s3_key_prefix"] == ORG_ID
        assert _edges(read, WRITES_LOGS) == [
            (_id(CONFIG_DELIVERY_CHANNEL, key), _id("aws_core__aws_s3_bucket", f"arn:{PARTITION}:s3:::{BUCKET}"))
        ]

    def test_organization_wide_aggregator(self) -> None:
        aggregator = _one(collect(govcloud()), CONFIG_AGGREGATOR)
        assert (aggregator["organization_wide"], aggregator["all_aws_regions"]) == (True, True)

    @pytest.mark.spec("req-aws-landing-zone-security-services-2")
    def test_detector_and_hub_report_to_their_administrator(self) -> None:
        read = collect(govcloud())
        detector = _one(read, GUARDDUTY_DETECTOR)
        assert (detector["status"], detector["administrator_account_id"], detector["tags"]) == (
            "ENABLED",
            SECURITY,
            {"team": "sec"},
        )
        hub = _one(read, SECURITYHUB_HUB)
        assert hub["administrator_account_id"] == SECURITY
        assert len(hub["enabled_standards"]) == 2, "GetEnabledStandards is read to its last page"
        security = _id("aws_core__aws_account", SECURITY)
        assert {to for _f, to in _edges(read, REPORTS_TO_ADMINISTRATOR)} == {security}
        assert len(_edges(read, REPORTS_TO_ADMINISTRATOR)) == 2

    def test_own_administrator_and_failed_administrator_read_have_no_edge(self) -> None:
        aws = govcloud()
        aws.on("guardduty", "get_administrator_account", _err("BadRequestException"))
        aws.on("securityhub", "get_administrator_account", {"Administrator": {}})
        read = collect(aws)
        assert _one(read, GUARDDUTY_DETECTOR)["administrator_account_id"] is None
        assert _one(read, SECURITYHUB_HUB)["administrator_account_id"] == ""
        assert _edges(read, REPORTS_TO_ADMINISTRATOR) == []

    @pytest.mark.spec("req-aws-landing-zone-security-services-1")
    def test_not_subscribed_or_denied_hub_is_unknown_never_off(self) -> None:
        read = collect(govcloud())
        east = _regional(read, HOSTS_SECURITYHUB_HUB, EAST)
        assert east["enumeration_complete"] is False and east["scope_authorized"] is None
        assert "SECURITYHUB_NOT_SUBSCRIBED_OR_DENIED" in _codes(read)
        assert [n["entity"]["dimensions"]["aws_region"] for n in _nodes(read, SECURITYHUB_HUB)] == [WEST]

    @pytest.mark.spec("req-aws-core-contained-type-triple-6")
    def test_one_analyzer_listing_per_type_behind_one_surface(self) -> None:
        aws = govcloud()
        read = collect(aws)
        types = [kw["type"] for _s, r, op, kw in aws.calls if op == "list_analyzers" and r == WEST]
        assert types == list(ANALYZER_TYPES)
        assert {n["node"]["analyzer_type"] for n in _nodes(read, ACCESS_ANALYZER)} == {
            "ORGANIZATION",
            "ORGANIZATION_UNUSED_ACCESS",
        }
        assert _regional(read, HOSTS_ACCESS_ANALYZER, WEST)["enumeration_complete"] is True
        aws.on(
            "accessanalyzer",
            "list_analyzers",
            by(lambda kw: kw.get("type"), {"ACCOUNT_INTERNAL_ACCESS": _err("AccessDeniedException")}),
            region=WEST,
        )
        read = collect(aws)
        surface = _regional(read, HOSTS_ACCESS_ANALYZER, WEST)
        assert surface["enumeration_complete"] is False and surface["scope_authorized"] is False

    def test_analyzer_type_outside_the_pinned_enum_is_kept_and_warned(self) -> None:
        aws = govcloud()
        aws.on(
            "accessanalyzer",
            "list_analyzers",
            by(
                lambda kw: kw.get("type"),
                {
                    "ACCOUNT": paged(
                        "analyzers",
                        [{"arn": ANALYZER_ARN, "name": "OrgAnalyzer", "type": "ACCOUNT_FUTURE"}],
                        token="nextToken",
                    )
                },
            ),
            region=WEST,
        )
        read = collect(aws)
        assert _one(read, ACCESS_ANALYZER)["analyzer_type"] == "ACCOUNT_FUTURE"
        assert "UNKNOWN_ENUM_VALUE" in _codes(read)

    @pytest.mark.spec("req-aws-landing-zone-security-services-1")
    def test_ebs_default_encryption_once_per_footprint_false_is_stored(self) -> None:
        aws = govcloud()
        aws.on("ec2", "get_ebs_default_kms_key_id", _err("UnauthorizedOperation"), region=EAST)
        read = collect(aws)
        assert read.footprint_fields[WEST] == {
            "ebs_encryption_by_default": True,
            "ebs_default_kms_key_id": "alias/aws/ebs",
        }
        assert read.footprint_fields[EAST] == {"ebs_encryption_by_default": False, "ebs_default_kms_key_id": None}
        assert sorted(r for _s, r, op, _ in aws.calls if op == "get_ebs_encryption_by_default") == sorted(REGIONS)

    @pytest.mark.spec("req-aws-landing-zone-security-services-1")
    @pytest.mark.parametrize(
        ("answer", "expected"),
        [
            (None, [True, True, True, False]),
            (_err("NoSuchPublicAccessBlockConfiguration"), [False, False, False, False]),
            (_err("AccessDenied"), [None, None, None, None]),
        ],
        ids=["configured", "no-configuration-is-off", "denied-is-unknown"],
    )
    def test_s3_public_access_block_read_once_in_the_home_region(self, answer: Any, expected: list[Any]) -> None:
        aws = govcloud()
        if answer is not None:
            aws.on("s3control", "get_public_access_block", answer)
        read = collect(aws)
        calls = [(r, kw) for s, r, op, kw in aws.calls if op == "get_public_access_block"]
        assert calls == [(WEST, {"AccountId": MGMT})], "exactly once, in the partition's home region"
        assert [
            read.account_fields[f]
            for f in (
                "s3_block_public_acls",
                "s3_ignore_public_acls",
                "s3_block_public_policy",
                "s3_restrict_public_buckets",
            )
        ] == expected


# ---------------------------------------------------------------------------
# Partition availability and region gates
# ---------------------------------------------------------------------------


class TestAvailability:
    @pytest.mark.spec("req-aws-landing-zone-availability-1")
    def test_every_service_the_reader_calls_has_an_availability_row(self) -> None:
        services = {svc for svc, _ in PAGINATED_OPERATIONS + SINGLE_OPERATIONS}
        for service in services:
            for partition in partition_mod.SUPPORTED_PARTITIONS:
                row = partition_mod.availability_of(partition, service)
                assert row is not None and row.evidence and row.method in ("web", "read", "inferred"), (
                    service,
                    partition,
                )
        assert partition_mod.availability_of(PARTITION, "macie2").available is False
        assert partition_mod.service_unavailable_reason(PARTITION, "macie2")
        unverified = {s for s in services if not partition_mod.availability_of(PARTITION, s).verified}
        assert unverified == {"controltower", "config"}

    @pytest.mark.spec("req-aws-landing-zone-availability-1")
    def test_a_service_the_partition_does_not_offer_is_skipped_with_no_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        unavailable = {PARTITION: {**partition_mod._UNAVAILABLE_SERVICES[PARTITION], "guardduty": "not offered (test)"}}
        monkeypatch.setattr(partition_mod, "_UNAVAILABLE_SERVICES", unavailable)
        aws = govcloud()
        read = collect(aws)
        assert aws.ops("guardduty") == []
        assert _nodes(read, GUARDDUTY_DETECTOR) == []
        notice = next(n for n in read.notices if n.code == "SERVICE_NOT_AVAILABLE_IN_PARTITION")
        assert notice.data == {"service": "guardduty", "partition": PARTITION}
        for region in REGIONS:
            surface = _regional(read, HOSTS_GUARDDUTY_DETECTOR, region)
            assert surface["enumeration_complete"] is False and surface["scope_authorized"] is False
            assert surface["reasons"]["enumeration_complete"].startswith("service_not_available_in_partition")
        assert _nodes(read, SECURITYHUB_HUB), "only the unavailable service is skipped"

    def test_a_disabled_region_is_not_read(self) -> None:
        facts = _facts()
        facts[EAST] = RegionFacts(EAST, PARTITION, "not-opted-in", STATUS_DISABLED, "not opted in")
        aws = govcloud()
        read = collect(aws, facts=facts)
        assert not [c for c in aws.calls if c[1] == EAST]
        for edge in CONTAINMENT_SURFACES[FOOTPRINT]:
            assert _regional(read, edge, EAST)["reasons"]["enumeration_complete"].startswith("region_disabled")


# ---------------------------------------------------------------------------
# The containment triple, tag lanes, sensitivity and the botocore walk
# ---------------------------------------------------------------------------


class TestTripleAndDeclarations:
    @pytest.mark.spec("req-aws-core-contained-type-triple-1")
    def test_reader_surfaces_mirror_model_containment(self) -> None:
        from tap_grid.registry import get_model_class

        for entity_type, edges in CONTAINMENT_SURFACES.items():
            declared = tuple(get_model_class(entity_type).CONTAINMENT_EDGES)
            if entity_type == FOOTPRINT:
                assert set(edges) <= set(declared)
                assert set(edges) == {c.edge_type for c in LANDING_ZONE_CHILDREN}
            else:
                assert declared == edges, entity_type

    @pytest.mark.spec("req-aws-core-contained-type-triple-1", "req-aws-core-contained-type-triple-2")
    def test_every_observed_parent_has_a_surface_for_every_containment_edge(self) -> None:
        read = collect(govcloud())
        recorded = {(s.subject, s.edge_type) for s in read.listings} | {
            (s["subject"], s["edge_type"]) for s in read.regional_surfaces
        }
        checked = 0
        for node in read.nodes:
            for edge in CONTAINMENT_SURFACES.get(node["entity"]["entity_type"], ()):
                assert (node["entity"]["ref"], edge) in recorded, (node["entity"]["entity_type"], edge)
                checked += 1
        for region in REGIONS:
            for edge in CONTAINMENT_SURFACES[FOOTPRINT]:
                assert (_fp(region), edge) in recorded, (region, edge)
                checked += 1
        assert checked >= 21
        # A parent with no children records a complete, empty surface.
        empty = _regional(read, HOSTS_GUARDDUTY_DETECTOR, EAST)
        assert (empty["enumeration_complete"], empty["count_observed"]) == (True, 0)

    @pytest.mark.spec("req-aws-collector-tags-13", "req-aws-collector-tags-14")
    def test_every_type_the_reader_emits_declares_one_lane(self) -> None:
        import jsonschema

        here = Path(__file__).resolve().parents[1] / "collectors" / "boto3_collector"
        schema = json.loads((here / "aws_resource_manifest.schema.json").read_text())
        block = {**schema["$defs"]["tags_block"], "$defs": schema["$defs"]}
        rows = [r for r in json.loads((here / "tag_lanes.json").read_text())["lanes"] if r["reader"] == READER]
        lanes: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            jsonschema.validate(row["tags"], block)
            lanes.setdefault(row["entity_type"], []).append(row)
        read = collect(govcloud())
        emitted = {n["entity"]["entity_type"] for n in read.nodes}
        assert len(emitted) == 13
        for entity_type in emitted:
            assert len(lanes.get(entity_type, [])) == 1, entity_type
        for node in read.nodes:
            if lanes[node["entity"]["entity_type"]][0]["tags"]["source"] == "none":
                assert node["node"]["tags"] == {}

    @pytest.mark.spec(
        "req-aws-collector-tags-13", "req-aws-landing-zone-security-services-4", "req-aws-landing-zone-control-tower-4"
    )
    def test_declared_tag_paths_and_shapes_match_botocore(self) -> None:
        import botocore.session

        session = botocore.session.get_session()
        services = {
            "aws_core__aws_controltower_landing_zone": ("controltower", "ListLandingZones"),
            "aws_core__aws_controltower_enabled_control": ("controltower", "ListEnabledControls"),
            "aws_core__aws_controltower_enabled_baseline": ("controltower", "ListEnabledBaselines"),
            "aws_core__aws_identity_center_instance": ("sso-admin", "ListInstances"),
            "aws_core__aws_identity_center_permission_set": ("sso-admin", "ListPermissionSets"),
            "aws_core__aws_config_recorder": ("config", "ListConfigurationRecorders"),
            "aws_core__aws_config_aggregator": ("config", "DescribeConfigurationAggregators"),
            "aws_core__aws_guardduty_detector": ("guardduty", "GetDetector"),
            "aws_core__aws_securityhub_hub": ("securityhub", "DescribeHub"),
            "aws_core__aws_access_analyzer": ("accessanalyzer", "ListAnalyzers"),
        }
        here = Path(__file__).resolve().parents[1] / "collectors" / "boto3_collector"
        rows = {
            r["entity_type"]: r["tags"]
            for r in json.loads((here / "tag_lanes.json").read_text())["lanes"]
            if r["reader"] == READER
        }
        for entity_type, (service, source_op) in services.items():
            lane = rows[entity_type]
            model = session.get_service_model(service)
            if lane["source"] == "service":
                shape = model.operation_model(lane["op"]).output_shape.members[lane["path"]]
            else:
                output = model.operation_model(source_op).output_shape
                if lane["from"] not in output.members:
                    output = next(m for m in output.members.values() if m.type_name == "list").member
                shape = output.members[lane["from"]]
            assert shape.type_name == {"map": "map", "list_kv": "list"}[lane["shape"]], entity_type

    @pytest.mark.spec("req-aws-collector-manifest-6")
    def test_every_emitted_type_declares_sensitivity_on_its_own_fields(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.organizations import reader_sensitivity

        from tap_grid.registry import get_model_class

        declared = reader_sensitivity(READER)
        read = collect(govcloud())
        emitted = {n["entity"]["entity_type"] for n in read.nodes}
        assert emitted <= set(declared), emitted - set(declared)
        for entity_type, block in declared.items():
            fields = set(get_model_class(entity_type).FIELD_CRUD_SCHEMA)
            for location in block.get("locations", []):
                assert location["path"].split("[]")[0].split(".")[0] in fields, (entity_type, location["path"])
        assert {loc["evidence"] for loc in declared[IDENTITY_GROUP]["locations"] if loc["path"] != "name"} == {
            "botocore_sensitive"
        }

    @pytest.mark.spec("req-aws-collector-manifest-7")
    def test_a_type_without_a_safe_declaration_is_not_written(self) -> None:
        from tap_plugin.aws_core.collectors.boto3_collector.organizations import reader_sensitivity

        declared = dict(reader_sensitivity(READER))
        declared[IDENTITY_GROUP] = {"status": "unreviewed"}
        read = collect(govcloud(), sensitivity=declared)
        assert _nodes(read, IDENTITY_GROUP) == []
        listing = _parent(read, HOLDS_IDENTITY_GROUP, _id(IDENTITY_CENTER_INSTANCE, INSTANCE_ARN))
        assert listing.admitted is False
        assert _nodes(read, PERMISSION_SET), "only the refused type is withheld"

    @pytest.mark.spec("req-aws-collector-pagination-3")
    def test_every_call_is_walked_against_botocore(self) -> None:
        import boto3

        # Dummy credentials: a metadata-only client must never walk the ambient provider chain (IMDS).
        session = boto3.session.Session(aws_access_key_id="x", aws_secret_access_key="x")
        clients = {svc: session.client(svc, region_name=WEST) for svc, _ in PAGINATED_OPERATIONS + SINGLE_OPERATIONS}
        for service, op in PAGINATED_OPERATIONS:
            assert clients[service].can_paginate(op), (service, op)
        for service, op in SINGLE_OPERATIONS:
            assert not clients[service].can_paginate(op), (service, op)
            assert hasattr(clients[service], op), (service, op)
        # The continuation token the page loop sends and reads is botocore's own, per operation.
        loader = boto3.session.Session()._session
        for service, op in PAGINATED_OPERATIONS:
            pascal = clients[service].meta.method_to_api_mapping[op]
            config = loader.get_paginator_model(service).get_paginator(pascal)
            assert (config["input_token"], config["output_token"]) == (continuation_token(service),) * 2, (service, op)
        aws = govcloud()
        collect(aws)
        used = {(svc, op) for svc, _r, op, _kw in aws.calls}
        assert used <= set(PAGINATED_OPERATIONS) | set(SINGLE_OPERATIONS), (
            used - set(PAGINATED_OPERATIONS) - set(SINGLE_OPERATIONS)
        )
        analyzer_type = (
            clients["accessanalyzer"].meta.service_model.operation_model("ListAnalyzers").input_shape.members["type"]
        )
        assert tuple(analyzer_type.enum) == ANALYZER_TYPES

    def test_govcloud_arns_are_stored_as_returned(self) -> None:
        read = collect(govcloud())
        arns = [v for n in read.nodes for k, v in n["node"].items() if k.endswith("_arn") and v]
        assert arns and all(a.startswith(f"arn:{PARTITION}:") for a in arns)


# ---------------------------------------------------------------------------
# One real collector run: the grid accepts the batch
# ---------------------------------------------------------------------------


class _Events:
    def register(self, _name: str, _handler: object) -> None:
        return None


class _Session:
    events = _Events()

    def __init__(self, aws: FakeAws) -> None:
        self._aws = aws

    def client(self, service: str, region_name: str | None = None, **_kw: Any) -> Any:
        return self._aws.client_for(service, region_name or WEST)


@pytest.mark.django_db
def test_collector_run_lands_every_type_and_both_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
    from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred
    from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector

    from tap_cares.collectors.config import CollectorConfig
    from tap_cares.secrets.models import Secret, SecretRef

    aws = govcloud()
    aws.on(
        "ec2",
        "describe_regions",
        {"Regions": [{"RegionName": r, "OptInStatus": "opt-in-not-required"} for r in REGIONS]},
    )
    aws.on("organizations", "describe_organization", _err("AWSOrganizationsNotInUseException"))
    secret = Secret(
        ref=SecretRef(scope="aws_core", key="boto_collector"),
        kind="aws_static_access_key",
        description="test",
        data={"access_key_id": "AKIA", "secret_access_key": "shh", "regions_allowed": REGIONS},
        metadata={},
        source_path=Path("/dev/null"),
    )
    monkeypatch.setattr(cred, "resolve_secret", lambda _ref: secret)
    monkeypatch.setattr(collector_mod, "build_session", lambda _data: _Session(aws))
    aws.on("sts", "get_caller_identity", {"Account": MGMT})
    monkeypatch.setattr(
        collector_mod, "client_factory", lambda _s, region: lambda service: aws.client_for(service, region)
    )
    monkeypatch.setattr(collector_mod, "caller_account_id", lambda *a, **k: MGMT)
    collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
    collector.run()
    assert collector.results["error"] == []
    assert not [w for w in collector.results["warn"] if w["message_code"] == "LANDING_ZONE_READ_FAILED"]
    for entity_type, key in (
        (LANDING_ZONE, LZ_ARN),
        (ENABLED_CONTROL, CONTROL_OU),
        (ENABLED_BASELINE, BASELINE_CHILD),
        (IDENTITY_CENTER_INSTANCE, INSTANCE_ARN),
        (PERMISSION_SET, PS_ADMIN),
        (IDENTITY_GROUP, {"identity_store_id": STORE_ID, "group_id": GROUP_ADMINS}),
        (CONFIG_RECORDER, LINKED_RECORDER_ARN),
        (
            CONFIG_DELIVERY_CHANNEL,
            {"account_id": MGMT, "region": WEST, "channel_name": "aws-controltower-BaselineConfigDeliveryChannel"},
        ),
        (CONFIG_AGGREGATOR, AGGREGATOR_ARN),
        (GUARDDUTY_DETECTOR, {"account_id": MGMT, "region": WEST, "detector_id": DETECTOR_ID}),
        (SECURITYHUB_HUB, HUB_ARN),
        (ACCESS_ANALYZER, ANALYZER_ARN),
    ):
        assert get_node(node_id(entity_type, key)) is not None, entity_type
    footprint = get_node(node_id("aws_core__aws_account_region", {"account_id": MGMT, "region_code": EAST}))
    assert footprint.ebs_encryption_by_default is False
    account = get_node(node_id("aws_core__aws_account", MGMT))
    assert (account.s3_block_public_acls, account.s3_restrict_public_buckets) == (True, False)
    # Not in an organization: the account set is unknown, so no assignment is written.
    assert "IDENTITY_CENTER_ASSIGNMENTS_INCOMPLETE" in [w["message_code"] for w in collector.results["warn"]]


# ---------------------------------------------------------------------------
# The falsifiers — real grid rows, fake client
# ---------------------------------------------------------------------------


class ProbeSession:
    def __init__(self, aws: FakeAws) -> None:
        self.aws = aws

    def client(self, service: str, region_name: str | None = None) -> Any:
        return self.aws.client_for(service, region_name or "")


def _row(entity_type: str, payload: dict[str, Any], *, region: str = WEST) -> uuid.UUID:
    result = create_node(entity_type, payload)
    assert result.success, result.errors
    entity_id = uuid.UUID(str(result.entity_id))
    row = get_node(entity_id)
    row.entity.dimensions = {"cloud": "aws", "aws_account": MGMT, "aws_region": region}
    row.entity.save(update_fields=["dimensions"])
    return entity_id


def _cand(entity_id: uuid.UUID, entity_type: str, parent: uuid.UUID | None = None) -> Candidate:
    return Candidate(
        entity_id=entity_id,
        entity_type=entity_type,
        reason="dropped_from_observation",
        surface=0,
        relation="fixture",
        subject=None,
        edge_type=None,
        parent=parent,
        interval_first=None,
    )


def _ctx() -> FalsifyContext:
    return FalsifyContext(batch_id=str(uuid.uuid4()), statement=None)


def _supported(verdicts: dict[str, Any]) -> None:
    for case, verdict in verdicts.items():
        assert unsupported(verdict) is None, (case, unsupported(verdict))


def _arn(service: str, resource: str, region: str = WEST) -> str:
    return f"arn:{PARTITION}:{service}:{region}:{MGMT}:{resource}"


#: (falsifier, entity type, arn field, row extras, ARN builder, the fake's (service, operation), the
#: response for a found ARN, the operation's not-found error)
_GET_BY_ARN: list[
    tuple[
        Any,
        str,
        str,
        Callable[[str], dict[str, Any]],
        Callable[[str], str],
        tuple[str, str],
        Callable[[str], dict[str, Any]],
        str,
    ]
] = [
    (
        LandingZoneFalsifier,
        LANDING_ZONE,
        "landing_zone_arn",
        lambda arn: {},
        lambda i: _arn("controltower", f"landingzone/LZ{i}"),
        ("controltower", "get_landing_zone"),
        lambda arn: {"landingZone": {"arn": arn}},
        "ResourceNotFoundException",
    ),
    (
        EnabledControlFalsifier,
        ENABLED_CONTROL,
        "enabled_control_arn",
        lambda arn: {},
        lambda i: _arn("controltower", f"enabledcontrol/C{i}"),
        ("controltower", "get_enabled_control"),
        lambda arn: {"enabledControlDetails": {"arn": arn}},
        "ResourceNotFoundException",
    ),
    (
        EnabledBaselineFalsifier,
        ENABLED_BASELINE,
        "enabled_baseline_arn",
        lambda arn: {},
        lambda i: _arn("controltower", f"enabledbaseline/B{i}"),
        ("controltower", "get_enabled_baseline"),
        lambda arn: {"enabledBaselineDetails": {"arn": arn}},
        "ResourceNotFoundException",
    ),
    (
        ConfigAggregatorFalsifier,
        CONFIG_AGGREGATOR,
        "aggregator_arn",
        lambda arn: {"aggregator_name": arn.rsplit("/", 1)[-1]},
        lambda i: _arn("config", f"config-aggregator/agg-{i}"),
        ("config", "describe_configuration_aggregators"),
        lambda arn: {"ConfigurationAggregators": [{"ConfigurationAggregatorArn": arn}]},
        "NoSuchConfigurationAggregatorException",
    ),
    (
        SecurityHubHubFalsifier,
        SECURITYHUB_HUB,
        "hub_arn",
        lambda arn: {},
        lambda i: _arn("securityhub", f"hub/h{i}"),
        ("securityhub", "describe_hub"),
        lambda arn: {"HubArn": arn},
        "ResourceNotFoundException",
    ),
    (
        AccessAnalyzerFalsifier,
        ACCESS_ANALYZER,
        "analyzer_arn",
        lambda arn: {"analyzer_name": arn.rsplit("/", 1)[-1]},
        lambda i: _arn("access-analyzer", f"analyzer/a{i}"),
        ("accessanalyzer", "get_analyzer"),
        lambda arn: {"analyzer": {"arn": arn}},
        "ResourceNotFoundException",
    ),
]


def _request_key(kw: dict[str, Any]) -> str:
    for name in (
        "landingZoneIdentifier",
        "enabledControlIdentifier",
        "enabledBaselineIdentifier",
        "HubArn",
        "analyzerName",
    ):
        if name in kw:
            return str(kw[name]).rsplit("/", 1)[-1]
    return str(kw["ConfigurationAggregatorNames"][0])


@pytest.mark.django_db
class TestGetByArnFalsifiers:
    @pytest.mark.spec(
        "req-aws-landing-zone-control-tower-3",
        "req-aws-landing-zone-security-services-3",
        "req-grid-reconcile-falsifier-6",
    )
    @pytest.mark.parametrize("spec", _GET_BY_ARN, ids=lambda s: s[1])
    def test_four_cases(self, spec: Any) -> None:
        falsifier_cls, entity_type, field, extras, make_arn, (service, op), found, gone = spec
        arns = {
            case: make_arn(index)
            for index, case in enumerate((CASE_PRESENT, CASE_DROPPED, CASE_FORBIDDEN, CASE_REIDENTIFIED))
        }
        cases = {
            case: _cand(_row(entity_type, {"name": "n", field: arn, **extras(arn)}), entity_type)
            for case, arn in arns.items()
        }
        forbidden = "InvalidAccessException" if entity_type == SECURITYHUB_HUB else "AccessDeniedException"
        table = {
            arns[CASE_PRESENT].rsplit("/", 1)[-1]: found(arns[CASE_PRESENT]),
            arns[CASE_DROPPED].rsplit("/", 1)[-1]: _err(gone),
            arns[CASE_FORBIDDEN].rsplit("/", 1)[-1]: _err(forbidden),
            arns[CASE_REIDENTIFIED].rsplit("/", 1)[-1]: found(make_arn(99)),
        }
        aws = FakeAws()
        aws.on(service, op, by(_request_key, table))
        falsifier = falsifier_cls(session=ProbeSession(aws), allowed_regions=REGIONS, account_id=MGMT)
        _supported(run_four_cases(falsifier, cases, _ctx()))
        assert {r for _s, r, _o, _k in aws.calls} == {WEST}, "probed in the ARN's own region"

    def test_other_account_is_scope_unknown_without_a_probe(self) -> None:
        aws = FakeAws()
        entity_id = _row(LANDING_ZONE, {"name": "n", "landing_zone_arn": LZ_ARN})
        [v] = LandingZoneFalsifier(
            session=ProbeSession(aws), allowed_regions=REGIONS, account_id=SECURITY
        ).batch_falsify([_cand(entity_id, LANDING_ZONE)], _ctx())
        assert (v.verdict, v.reason) == (UNDETERMINED, "scope_unknown")
        assert aws.calls == []


def _listing_case(falsifier: Any, entity_type: str, payload: dict[str, Any], aws: FakeAws, **kw: Any) -> Any:
    [verdict] = falsifier(session=ProbeSession(aws), allowed_regions=REGIONS, account_id=MGMT, **kw).batch_falsify(
        [_cand(_row(entity_type, payload), entity_type)], _ctx()
    )
    return verdict


#: (falsifier, entity type, row payload, the fake's (service, operation), a handler naming it, one
#: not naming it). A key looked up in a listing by that same key cannot come back under another, so
#: REIDENTIFIED is structurally impossible; the cases are proven one by one.
_LISTING: list[tuple[Any, str, dict[str, Any], tuple[str, str], Any, Any]] = [
    (
        IdentityCenterInstanceFalsifier,
        IDENTITY_CENTER_INSTANCE,
        {"name": "i", "instance_arn": INSTANCE_ARN, "owner_account_id": MGMT, "home_region": WEST},
        ("sso-admin", "list_instances"),
        paged("Instances", [], [{"InstanceArn": INSTANCE_ARN, "OwnerAccountId": MGMT}]),
        paged(
            "Instances",
            [{"InstanceArn": f"arn:{PARTITION}:sso:::instance/ssoins-0000000000000000", "OwnerAccountId": MGMT}],
        ),
    ),
    (
        ConfigRecorderFalsifier,
        CONFIG_RECORDER,
        {"name": "r", "recorder_arn": RECORDER_ARN},
        ("config", "list_configuration_recorders"),
        paged("ConfigurationRecorderSummaries", [], [{"arn": RECORDER_ARN}]),
        paged("ConfigurationRecorderSummaries", [{"arn": LINKED_RECORDER_ARN}]),
    ),
    (
        ConfigDeliveryChannelFalsifier,
        CONFIG_DELIVERY_CHANNEL,
        {"name": "c", "account_id": MGMT, "region": WEST, "channel_name": "default"},
        ("config", "describe_delivery_channels"),
        {"DeliveryChannels": [{"name": "default"}]},
        {"DeliveryChannels": []},
    ),
    (
        GuardDutyDetectorFalsifier,
        GUARDDUTY_DETECTOR,
        {"name": "d", "account_id": MGMT, "region": WEST, "detector_id": DETECTOR_ID},
        ("guardduty", "list_detectors"),
        paged("DetectorIds", ["other"], [DETECTOR_ID]),
        paged("DetectorIds", ["other"]),
    ),
]


@pytest.mark.django_db
class TestListingFalsifiers:
    @pytest.mark.spec(
        "req-aws-landing-zone-identity-center-4",
        "req-aws-landing-zone-security-services-3",
        "req-aws-collector-pagination-1",
        "req-aws-collector-pagination-2",
    )
    @pytest.mark.parametrize("spec", _LISTING, ids=lambda s: s[1])
    def test_present_dropped_forbidden_and_failed_page(self, spec: Any) -> None:
        falsifier, entity_type, payload, (service, op), naming, not_naming = spec
        for handler, expected in (
            (naming, PRESENT_AT_PROBE),
            (not_naming, DROPPED_FROM_OBSERVATION),
            (_err("AccessDeniedException"), UNDETERMINED),
        ):
            aws = FakeAws()
            aws.on(service, op, handler)
            verdict = _listing_case(falsifier, entity_type, payload, aws)
            assert verdict.verdict == expected, (handler, verdict.note)
            assert unsupported(verdict) is None
        if op != "describe_delivery_channels":
            key = {
                "list_instances": "Instances",
                "list_configuration_recorders": "ConfigurationRecorderSummaries",
                "list_detectors": "DetectorIds",
            }[op]
            aws = FakeAws()
            aws.on(service, op, paged(key, [], _err("ThrottlingException")))
            assert _listing_case(falsifier, entity_type, payload, aws).verdict == UNDETERMINED


@pytest.mark.django_db
class TestIdentityFalsifiers:
    @pytest.mark.spec("req-aws-landing-zone-identity-center-4", "req-grid-reconcile-falsifier-6")
    def test_permission_set_four_cases(self) -> None:
        arns = {
            case: f"{PS_ADMIN[:-4]}{index:04d}"
            for index, case in enumerate((CASE_PRESENT, CASE_DROPPED, CASE_FORBIDDEN, CASE_REIDENTIFIED))
        }
        cases = {
            case: _cand(
                _row(PERMISSION_SET, {"name": "p", "permission_set_arn": arn, "instance_arn": INSTANCE_ARN}),
                PERMISSION_SET,
            )
            for case, arn in arns.items()
        }
        aws = FakeAws()
        aws.on(
            "sso-admin",
            "describe_permission_set",
            by(
                lambda kw: kw["PermissionSetArn"],
                {
                    arns[CASE_PRESENT]: {"PermissionSet": {"PermissionSetArn": arns[CASE_PRESENT]}},
                    arns[CASE_DROPPED]: _err("ResourceNotFoundException"),
                    arns[CASE_FORBIDDEN]: _err("AccessDeniedException"),
                    arns[CASE_REIDENTIFIED]: {"PermissionSet": {"PermissionSetArn": PS_READ}},
                },
            ),
        )
        _supported(
            run_four_cases(
                PermissionSetFalsifier(session=ProbeSession(aws), allowed_regions=REGIONS, account_id=MGMT),
                cases,
                _ctx(),
            )
        )

    @pytest.mark.spec("req-aws-landing-zone-identity-center-4", "req-grid-reconcile-falsifier-6")
    def test_group_four_cases(self) -> None:
        ids = {
            case: f"g-{index}"
            for index, case in enumerate((CASE_PRESENT, CASE_DROPPED, CASE_FORBIDDEN, CASE_REIDENTIFIED))
        }
        cases = {
            case: _cand(
                _row(
                    IDENTITY_GROUP,
                    {"name": "g", "identity_store_id": STORE_ID, "group_id": gid, "display_name": "Admins"},
                ),
                IDENTITY_GROUP,
            )
            for case, gid in ids.items()
        }
        aws = FakeAws()
        aws.on(
            "identitystore",
            "describe_group",
            by(
                lambda kw: kw["GroupId"],
                {
                    ids[CASE_PRESENT]: {"GroupId": ids[CASE_PRESENT], "DisplayName": "Admins"},
                    ids[CASE_DROPPED]: _err("ResourceNotFoundException"),
                    ids[CASE_FORBIDDEN]: _err("AccessDeniedException"),
                    ids[CASE_REIDENTIFIED]: {"GroupId": "g-new", "DisplayName": "Admins"},
                },
            ),
        )
        _supported(
            run_four_cases(
                IdentityGroupFalsifier(session=ProbeSession(aws), allowed_regions=REGIONS, account_id=MGMT),
                cases,
                _ctx(),
            )
        )


def _assignment_rows() -> tuple[uuid.UUID, uuid.UUID]:
    instance = _row(
        IDENTITY_CENTER_INSTANCE,
        {"name": "i", "instance_arn": INSTANCE_ARN, "owner_account_id": MGMT, "home_region": WEST},
    )
    assignment = _row(
        ACCOUNT_ASSIGNMENT,
        {
            "name": "a",
            "instance_arn": INSTANCE_ARN,
            "account_id": WORKLOAD,
            "permission_set_arn": PS_ADMIN,
            "principal_type": "GROUP",
            "principal_id": GROUP_ADMINS,
        },
    )
    return instance, assignment


def _org(aws: FakeAws, *, account: Any) -> None:
    aws.on("organizations", "describe_organization", {"Organization": {"Id": ORG_ID}})
    aws.on("organizations", "list_roots", {"Roots": [{"Id": "r-0vv8"}]})
    aws.on("organizations", "describe_account", account)


@pytest.mark.django_db
class TestAccountAssignmentFalsifier:
    def _verdict(self, aws: FakeAws, *, account_id: str = MGMT) -> Any:
        instance, assignment = _assignment_rows()
        falsifier = AccountAssignmentFalsifier(
            session=ProbeSession(aws), allowed_regions=REGIONS, account_id=account_id, org_region=WEST
        )
        [verdict] = falsifier.batch_falsify([_cand(assignment, ACCOUNT_ASSIGNMENT, parent=instance)], _ctx())
        return verdict

    @pytest.mark.spec("req-aws-landing-zone-identity-center-4", "req-aws-collector-pagination-1")
    def test_named_on_a_later_page_is_present_and_unnamed_is_dropped(self) -> None:
        aws = FakeAws()
        aws.on(
            "sso-admin",
            "list_account_assignments",
            paged("AccountAssignments", [], [_assignment(WORKLOAD, PS_ADMIN, "GROUP", GROUP_ADMINS)]),
        )
        assert self._verdict(aws).verdict == PRESENT_AT_PROBE
        aws = FakeAws()
        aws.on(
            "sso-admin",
            "list_account_assignments",
            paged("AccountAssignments", [_assignment(WORKLOAD, PS_ADMIN, "USER", USER_ID)]),
        )
        assert self._verdict(aws).verdict == DROPPED_FROM_OBSERVATION

    @pytest.mark.spec("req-aws-landing-zone-identity-center-6")
    def test_permission_set_deleted_is_dropped(self) -> None:
        aws = FakeAws()
        aws.on("sso-admin", "list_account_assignments", _err("ResourceNotFoundException"))
        aws.on("sso-admin", "describe_permission_set", _err("ResourceNotFoundException"))
        verdict = self._verdict(aws)
        assert verdict.verdict == DROPPED_FROM_OBSERVATION and "permission set" in verdict.probe["detail"]
        assert aws.ops("organizations") == []

    @pytest.mark.spec("req-aws-landing-zone-identity-center-6")
    def test_account_removed_from_the_organization_is_dropped(self) -> None:
        aws = FakeAws()
        aws.on("sso-admin", "list_account_assignments", _err("ResourceNotFoundException"))
        aws.on("sso-admin", "describe_permission_set", {"PermissionSet": {"PermissionSetArn": PS_ADMIN}})
        _org(aws, account=_err("AccountNotFoundException"))
        verdict = self._verdict(aws)
        assert verdict.verdict == DROPPED_FROM_OBSERVATION and "organization" in verdict.probe["detail"]

    @pytest.mark.spec("req-aws-landing-zone-identity-center-6")
    @pytest.mark.parametrize(
        ("account", "reach"),
        [
            ({"Account": {"Id": WORKLOAD}}, True),
            (_err("AccessDeniedException"), True),
            (_err("AccountNotFoundException"), False),
        ],
        ids=["account-still-a-member", "account-probe-refused", "reach-unproven"],
    )
    def test_neither_confirmed_is_undetermined(self, account: Any, reach: bool) -> None:
        aws = FakeAws()
        aws.on("sso-admin", "list_account_assignments", _err("ResourceNotFoundException"))
        aws.on("sso-admin", "describe_permission_set", {"PermissionSet": {"PermissionSetArn": PS_ADMIN}})
        _org(aws, account=account)
        if not reach:
            aws.on("organizations", "describe_organization", _err("AWSOrganizationsNotInUseException"))
        assert self._verdict(aws).verdict == UNDETERMINED

    @pytest.mark.spec("req-aws-landing-zone-identity-center-6")
    def test_a_credential_that_does_not_own_the_instance_never_drops_on_the_account_probe(self) -> None:
        aws = FakeAws()
        aws.on("sso-admin", "list_account_assignments", _err("ResourceNotFoundException"))
        aws.on("sso-admin", "describe_permission_set", {"PermissionSet": {"PermissionSetArn": PS_ADMIN}})
        _org(aws, account=_err("AccountNotFoundException"))
        instance = _row(
            IDENTITY_CENTER_INSTANCE,
            {"name": "i", "instance_arn": INSTANCE_ARN, "owner_account_id": SECURITY, "home_region": WEST},
        )
        _i, assignment = _assignment_rows()
        falsifier = AccountAssignmentFalsifier(
            session=ProbeSession(aws), allowed_regions=REGIONS, account_id=MGMT, org_region=WEST
        )
        [verdict] = falsifier.batch_falsify([_cand(assignment, ACCOUNT_ASSIGNMENT, parent=instance)], _ctx())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "describe_account" not in aws.ops("organizations")

    def test_refused_listing_is_undetermined(self) -> None:
        aws = FakeAws()
        aws.on("sso-admin", "list_account_assignments", _err("AccessDeniedException"))
        assert self._verdict(aws).verdict == UNDETERMINED


@pytest.mark.django_db
class TestProbesStayInScope:
    """A falsifier never probes outside the collector's configured region scope (regions_allowed)."""

    def test_out_of_scope_primary_region_is_probed_where_it_was_read(self) -> None:
        aws = FakeAws()
        aws.on(
            "sso-admin", "list_instances", paged("Instances", [{"InstanceArn": INSTANCE_ARN, "OwnerAccountId": MGMT}])
        )
        entity_id = _row(
            IDENTITY_CENTER_INSTANCE,
            {"name": "i", "instance_arn": INSTANCE_ARN, "owner_account_id": MGMT, "home_region": "us-east-1"},
            region=WEST,
        )
        falsifier = IdentityCenterInstanceFalsifier(session=ProbeSession(aws), allowed_regions=[WEST], account_id=MGMT)
        [verdict] = falsifier.batch_falsify([_cand(entity_id, IDENTITY_CENTER_INSTANCE)], _ctx())
        assert verdict.verdict == PRESENT_AT_PROBE
        assert {r for _s, r, _o, _k in aws.calls} == {WEST}

    def test_no_region_in_scope_is_refused_without_a_call(self) -> None:
        aws = FakeAws()
        arn = f"arn:{PARTITION}:controltower:{EAST}:{MGMT}:landingzone/EASTLZ"
        entity_id = _row(LANDING_ZONE, {"name": "n", "landing_zone_arn": arn}, region=EAST)
        falsifier = LandingZoneFalsifier(session=ProbeSession(aws), allowed_regions=[WEST], account_id=MGMT)
        [verdict] = falsifier.batch_falsify([_cand(entity_id, LANDING_ZONE)], _ctx())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert aws.calls == []

    def test_an_unreadable_scope_refuses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_plugin.aws_core import falsifiers as falsifiers_mod

        def unreadable() -> Any:
            raise RuntimeError("no secret")

        monkeypatch.setattr(falsifiers_mod, "resolve_aws_secret", unreadable)
        aws = FakeAws()
        entity_id = _row(LANDING_ZONE, {"name": "n", "landing_zone_arn": LZ_ARN})
        [verdict] = LandingZoneFalsifier(session=ProbeSession(aws), account_id=MGMT).batch_falsify(
            [_cand(entity_id, LANDING_ZONE)], _ctx()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert aws.calls == []


@pytest.mark.django_db
def test_hub_invalid_access_is_never_a_drop() -> None:
    aws = FakeAws()
    aws.on("securityhub", "describe_hub", _err("InvalidAccessException"))
    entity_id = _row(SECURITYHUB_HUB, {"name": "h", "hub_arn": HUB_ARN})
    [verdict] = SecurityHubHubFalsifier(
        session=ProbeSession(aws), allowed_regions=REGIONS, account_id=MGMT
    ).batch_falsify([_cand(entity_id, SECURITYHUB_HUB)], _ctx())
    assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "forbidden")


class TestFalsifierWiring:
    def test_class_paths_resolve_and_construct_with_no_arguments(self) -> None:
        import tomllib

        from django.utils.module_loading import import_string

        from tap_grid.falsifiers import Falsifier

        manifest = tomllib.loads((Path(__file__).resolve().parents[1] / "tap-plugin.toml").read_text())
        reconcilable = {
            LANDING_ZONE,
            ENABLED_CONTROL,
            ENABLED_BASELINE,
            IDENTITY_CENTER_INSTANCE,
            PERMISSION_SET,
            IDENTITY_GROUP,
            ACCOUNT_ASSIGNMENT,
            CONFIG_RECORDER,
            CONFIG_DELIVERY_CHANNEL,
            CONFIG_AGGREGATOR,
            GUARDDUTY_DETECTOR,
            SECURITYHUB_HUB,
            ACCESS_ANALYZER,
        }
        for entity_type in reconcilable:
            cls = import_string(manifest["falsifiers"][entity_type])
            assert issubclass(cls, Falsifier)
            assert cls()
