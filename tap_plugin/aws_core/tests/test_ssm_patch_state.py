"""SSM managed-instance patch and compliance state (req-aws-core-ssm-patch-state, aws-core-tap#281).

No account with SSM-managed instances was available, so the walk is driven by fakes whose canned responses are
checked against botocore's own ``ssm`` output shapes (:func:`_shape_checked`), so a member name AWS does not define
fails the test. One test drives the real collector run into the grid, so core's GRIFT validation (the tags trap,
``additionalProperties: false``) and the edge endpoints are exercised as an import applies them. No AWS call is made.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import botocore.session
import jsonschema
import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred
from tap_plugin.aws_core.collectors.boto3_collector import ssm_patch
from tap_plugin.aws_core.collectors.boto3_collector.authority import COMPLETE, EDGE_READS, FAILED, PARTIAL
from tap_plugin.aws_core.collectors.boto3_collector.batch import node_envelope
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    build_custom_fn_registry,
    ssm_compliance_items_described,
    ssm_compliance_summaries_described,
    ssm_managed_instances_described,
    ssm_patches_described,
)
from tap_plugin.aws_core.collectors.boto3_collector.edges import TransformRegistry, emit_edges
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
from tap_plugin.aws_core.collectors.boto3_collector.source import iter_source
from tap_plugin.aws_core.tests.grid_keys import edge_between, find_node_id, node_id

ACCOUNT = "111122223333"
REGION = "us-gov-west-1"
PARTITION = "aws-us-gov"
EC2_ID = "i-0abc1234def567890"
EC2_ID_2 = "i-0fedcba9876543210"
HYBRID_ID = "mi-0123456789abcdef0"
OWN_BASELINE = "pb-0123456789abcdef0"
#: An AWS-provided baseline's id is an ARN under AWS's own account; a documentation placeholder stands in for it.
AWS_BASELINE = f"arn:{PARTITION}:ssm:{REGION}:999988887777:patchbaseline/pb-0fedcba9876543210"
OWNER_CANARY = "canary-owner-information-4c1d"
WHEN = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

MI = "aws_core__aws_ssm_managed_instance"
PATCH = "aws_core__aws_ssm_patch"
SUMMARY = "aws_core__aws_ssm_compliance_summary"
ITEM = "aws_core__aws_ssm_compliance_item"

_SSM = botocore.session.get_session().get_service_model("ssm")


def _shape_checked(op: str, page: dict[str, Any]) -> dict[str, Any]:
    """``page`` unchanged, after checking every member it names exists in ``op``'s botocore output shape."""

    def walk(shape: Any, value: Any, where: str) -> None:
        if shape.type_name == "structure":
            assert isinstance(value, dict), where
            unknown = set(value) - set(shape.members)
            assert not unknown, f"{where}: not in botocore's {shape.name}: {sorted(unknown)}"
            for key, member in value.items():
                walk(shape.members[key], member, f"{where}.{key}")
        elif shape.type_name == "list":
            for n, member in enumerate(value):
                walk(shape.member, member, f"{where}[{n}]")
        elif shape.type_name == "map":
            for key, member in value.items():
                walk(shape.value, member, f"{where}.{key}")

    walk(_SSM.operation_model(op).output_shape, page, op)
    return page


def _denied(op: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, op)


def _info(instance_id: str, resource_type: str, **extra: Any) -> dict[str, Any]:
    return {
        "InstanceId": instance_id,
        "PingStatus": "Online",
        "LastPingDateTime": WHEN,
        "AgentVersion": "3.3.1000.0",
        "IsLatestVersion": False,
        "PlatformType": "Linux",
        "PlatformName": "Amazon Linux",
        "PlatformVersion": "2023",
        "ResourceType": resource_type,
        "IPAddress": "10.0.0.5",
        "ComputerName": "ip-10-0-0-5.ec2.internal",
        **extra,
    }


def _state(instance_id: str, baseline: str, **counts: int) -> dict[str, Any]:
    return {
        "InstanceId": instance_id,
        "PatchGroup": "prod",
        "BaselineId": baseline,
        "OwnerInformation": OWNER_CANARY,
        "Operation": "Scan",
        "OperationStartTime": WHEN,
        "OperationEndTime": WHEN,
        "RebootOption": "NoReboot",
        "InstalledCount": counts.get("installed", 40),
        "MissingCount": counts.get("missing", 2),
        "FailedCount": 0,
        "CriticalNonCompliantCount": counts.get("critical", 1),
        "SecurityNonCompliantCount": 2,
        "OtherNonCompliantCount": 0,
    }


def _patch(kb_id: str, state: str, *, installed: datetime = EPOCH, cves: str = "") -> dict[str, Any]:
    return {
        "Title": f"{kb_id} title",
        "KBId": kb_id,
        "Classification": "Security",
        "Severity": "Critical",
        "State": state,
        "InstalledTime": installed,
        **({"CVEIds": cves} if cves else {}),
    }


class _Paginator:
    def __init__(self, client: _FakeSsm, method: str) -> None:
        self.client, self.method = client, method

    def paginate(self, **kwargs: Any):
        self.client.calls.append((self.method, kwargs))
        failure = self.client.fail.get(self.method)
        if failure:
            raise _denied(self.method)
        op = "".join(part.capitalize() for part in self.method.split("_"))
        yield from (_shape_checked(op, page) for page in self.client.pages(self.method, kwargs))


class _Meta:
    def __init__(self, region: str, partition: str) -> None:
        self.region_name, self.partition = region, partition


class _FakeSsm:
    """An ``ssm`` client stand-in: canned pages per call, and any call can be made to fail."""

    def __init__(self, *, region: str = REGION, partition: str = PARTITION, fail: dict[str, bool] | None = None,
                 instances: list[dict[str, Any]] | None = None, states: list[dict[str, Any]] | None = None,
                 patches: dict[str, list[dict[str, Any]]] | None = None, summaries: list[dict[str, Any]] | None = None,
                 items: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.meta = _Meta(region, partition)
        self.unfiltered_baseline_reads = 0
        self.fail = fail or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.instances = instances if instances is not None else [
            _info(EC2_ID, "EC2Instance"),
            _info(EC2_ID_2, "EC2Instance"),
            _info(HYBRID_ID, "ManagedInstance", Name="lab-box", ActivationId="a1b2c3d4-0000-1111-2222-abcdefabcdef"),
        ]
        self.states = states if states is not None else [
            _state(EC2_ID, AWS_BASELINE),
            _state(EC2_ID_2, AWS_BASELINE, missing=0, critical=0),
            _state(HYBRID_ID, OWN_BASELINE),
        ]
        shared = _patch("openssl-libs.x86_64:1:3.0.8-1.amzn2023", "MISSING", cves="CVE-2026-0001, CVE-2026-0002,CVE-2026-0001")
        self.patches = patches if patches is not None else {
            EC2_ID: [shared, _patch("kernel.x86_64:0:6.1.100-1.amzn2023", "INSTALLED", installed=WHEN)],
            EC2_ID_2: [{**shared, "State": "INSTALLED_PENDING_REBOOT", "InstalledTime": WHEN}],
            HYBRID_ID: [_patch("KB5034441", "FAILED")],
        }
        self.summaries = summaries if summaries is not None else [
            {
                "ComplianceType": "Patch", "ResourceType": "ManagedInstance", "ResourceId": EC2_ID, "Status": "NON_COMPLIANT",
                "OverallSeverity": "CRITICAL", "ExecutionSummary": {"ExecutionTime": WHEN, "ExecutionId": "exec-1", "ExecutionType": "Command"},
                "CompliantSummary": {"CompliantCount": 40, "SeveritySummary": {"CriticalCount": 3}},
                "NonCompliantSummary": {"NonCompliantCount": 2, "SeveritySummary": {"CriticalCount": 1, "HighCount": 1}},
            },
            {
                "ComplianceType": "Association", "ResourceType": "ManagedInstance", "ResourceId": EC2_ID, "Status": "COMPLIANT",
                "OverallSeverity": "UNSPECIFIED", "ExecutionSummary": {"ExecutionTime": WHEN},
                "CompliantSummary": {"CompliantCount": 1}, "NonCompliantSummary": {"NonCompliantCount": 0},
            },
        ]
        self.items = items if items is not None else {
            EC2_ID: [
                {"ComplianceType": "Association", "ResourceType": "ManagedInstance", "ResourceId": EC2_ID,
                 "Id": "8dfe3659-4309-493a-8755-0123456789ab", "Title": "", "Status": "COMPLIANT", "Severity": "UNSPECIFIED",
                 "ExecutionSummary": {"ExecutionTime": WHEN, "ExecutionId": "exec-2", "ExecutionType": "Command"},
                 "Details": {"DocumentName": "AWS-GatherSoftwareInventory", "DocumentVersion": "1"}},
                {"ComplianceType": "Custom:CIS", "ResourceType": "ManagedInstance", "ResourceId": EC2_ID,
                 "Title": "1.1.1 Ensure mounting of cramfs is disabled", "Status": "NON_COMPLIANT", "Severity": "HIGH",
                 "ExecutionSummary": {"ExecutionTime": WHEN}},
            ],
        }

    def get_paginator(self, method: str) -> _Paginator:
        return _Paginator(self, method)

    def can_paginate(self, _method: str) -> bool:
        return True

    def pages(self, method: str, kwargs: dict[str, Any]) -> list[dict[str, Any]]:
        if method == "describe_instance_information":
            return [{"InstanceInformationList": self.instances[:1]}, {"InstanceInformationList": self.instances[1:]}]
        if method == "describe_instance_patch_states":
            wanted = set(kwargs["InstanceIds"])
            assert len(wanted) <= ssm_patch.PATCH_STATES_PER_CALL
            return [{"InstancePatchStates": [s for s in self.states if s["InstanceId"] in wanted]}]
        if method == "describe_patch_baselines":
            baselines = [
                {"BaselineId": AWS_BASELINE, "BaselineName": "AWS-AmazonLinux2023DefaultPatchBaseline", "OperatingSystem": "AMAZON_LINUX_2023", "DefaultBaseline": True},
                {"BaselineId": OWN_BASELINE, "BaselineName": "lab-windows", "OperatingSystem": "WINDOWS", "DefaultBaseline": False},
            ]
            if kwargs.get("Filters") == [{"Key": "OWNER", "Values": ["Self"]}]:  # the baseline entry, unchanged
                return [{"BaselineIdentities": [b for b in baselines if not b["BaselineId"].startswith("arn:")]}]
            assert "Filters" not in kwargs  # the walk: every baseline, AWS's included, for the operating system lookup
            self.unfiltered_baseline_reads += 1
            return [{"BaselineIdentities": baselines}]
        if method == "describe_instance_patches":
            return [{"Patches": self.patches.get(kwargs["InstanceId"], [])}]
        if method == "list_resource_compliance_summaries":
            return [{"ResourceComplianceSummaryItems": self.summaries}]
        if method == "list_compliance_items":
            assert kwargs["ResourceTypes"] == ["ManagedInstance"]
            assert kwargs["Filters"] == [{"Key": "ComplianceType", "Values": ["Patch"], "Type": "NOT_EQUAL"}]
            [resource] = kwargs["ResourceIds"]
            return [{"ComplianceItems": self.items.get(resource, [])}]
        return [{}]  # another SSM entry's listing (parameters, documents...): nothing

    def list_tags_for_resource(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_tags_for_resource", kwargs))
        if kwargs.get("ResourceType") != "ManagedInstance":  # another SSM entry's tag lane
            return {"TagList": []}
        assert kwargs == {"ResourceType": "ManagedInstance", "ResourceId": HYBRID_ID}
        if self.fail.get("list_tags_for_resource"):
            raise _denied("ListTagsForResource")
        return _shape_checked("ListTagsForResource", {"TagList": [{"Key": "team", "Value": "lab"}]})


class _Sts:
    def __init__(self) -> None:
        self.calls = 0

    def get_caller_identity(self) -> dict[str, Any]:
        self.calls += 1
        return {"Account": ACCOUNT}


def _clients(ssm: _FakeSsm, sts: _Sts | None = None):
    clients = {"ssm": ssm, "sts": sts or _Sts()}
    return clients.__getitem__


def _entry(entity_type: str) -> dict[str, Any]:
    return next(e for e in manifest_entries() if e["entity_type"] == entity_type)


_REGISTRY = build_custom_fn_registry()


def _items(entity_type: str, ssm: _FakeSsm, session: Any = None) -> list[dict[str, Any]]:
    """The entry's items as a run reads them: its custom_fn, then its ``derive`` keys under the run's scope."""
    region = ssm.meta.region_name
    return list(iter_source(_entry(entity_type), client_for=_clients(ssm), custom_fns=_REGISTRY, fn_context=session,
                            account_id=ACCOUNT, scope={"partition": PARTITION, "region": region, "account": ACCOUNT}))


def _nodes(entity_type: str, _fn: Any, ssm: _FakeSsm, session: Any = None) -> list[Any]:
    return [project_item(_entry(entity_type), item, {"region": ssm.meta.region_name}) for item in _items(entity_type, ssm, session)]


def _edges(node: Any) -> list[dict[str, Any]]:
    modeled = {e["entity_type"] for e in manifest_entries()}
    emission = emit_edges(node, _entry(node.entity_type), modeled_types=modeled, transforms=TransformRegistry(), dimensions={})
    return [env["edge"] for env in emission.envelopes]


def _by_key(nodes: list[Any]) -> dict[str, Any]:
    return {n.natural_key: n for n in nodes}


class _Session:
    """A weakly referenceable stand-in for the run's boto3 session, so the walk is shared as in a run."""


# --- the managed instance and its patch state (ruling A1) ----------------------------------------------------------


@pytest.mark.spec("req-aws-core-ssm-patch-state-1", "req-aws-core-ssm-patch-state-2")
def test_each_managed_instance_holds_its_last_patch_operation_in_typed_fields() -> None:
    nodes = _by_key(_nodes(MI, ssm_managed_instances_described, _FakeSsm()))
    assert set(nodes) == {EC2_ID, EC2_ID_2, HYBRID_ID}  # both pages, keyed by the id AWS generates
    ec2 = nodes[EC2_ID].fields
    assert ec2["instance_id"] == EC2_ID and ec2["resource_type"] == "EC2Instance" and ec2["ping_status"] == "Online"
    assert ec2["last_ping_at"] == "2026-11-20T03:00:00Z"
    assert (ec2["patch_operation"], ec2["patch_group"], ec2["patch_baseline_id"]) == ("Scan", "prod", AWS_BASELINE)
    assert (ec2["patch_installed_count"], ec2["patch_missing_count"], ec2["patch_critical_non_compliant_count"]) == (40, 2, 1)
    assert ec2["patch_operation_end_at"] == "2026-11-20T03:00:00Z"
    assert ec2["patch_installed_other_count"] is None  # AWS did not report it: unobserved, not zero
    assert nodes[HYBRID_ID].fields["name"] == "lab-box"
    assert nodes[EC2_ID].fields["name"] == "ip-10-0-0-5.ec2.internal"


@pytest.mark.spec("req-aws-core-ssm-patch-state-2")
def test_owner_information_reaches_nothing_and_the_ip_address_no_field() -> None:
    nodes = _nodes(MI, ssm_managed_instances_described, _FakeSsm())
    for node in nodes:
        assert OWNER_CANARY not in json.dumps(node.raw_item, default=str)  # dropped as the response was read
        payload = node_envelope(node, {}, {}, persist_configuration=_entry(MI)["persist_configuration"])["node"]
        assert OWNER_CANARY not in json.dumps(payload, default=str)
        assert "10.0.0.5" not in json.dumps({k: v for k, v in payload.items() if k != "configuration"}, default=str)
        assert payload["configuration"]["_source"]  # stored, per req-aws-collector-redaction-1
    assert _entry(MI)["persist_configuration"] is True


@pytest.mark.spec("req-aws-core-ssm-patch-state-3")
def test_a_managed_instance_links_to_its_ec2_instance_and_the_baseline_its_last_operation_used() -> None:
    nodes = _by_key(_nodes(MI, ssm_managed_instances_described, _FakeSsm()))
    ec2_edges = {(e["edge_type"], e["to_ref"]) for e in _edges(nodes[EC2_ID])}
    assert ("REPRESENTS_EC2_INSTANCE__aws_core", f"aws_core__aws_ec2_instance:{EC2_ID}") in ec2_edges
    # An AWS-provided baseline is named by the ARN AWS returns: the edge is sent, and core skips it while the
    # baseline listing reads OWNER=Self only (the instance keeps patch_baseline_id).
    assert ("USES_PATCH_BASELINE__aws_core", f"aws_core__aws_ssm_patch_baseline:{AWS_BASELINE}") in ec2_edges
    hybrid_edges = {(e["edge_type"], e["to_ref"]) for e in _edges(nodes[HYBRID_ID])}
    assert not any(t == "REPRESENTS_EC2_INSTANCE__aws_core" for t, _ in hybrid_edges)  # a hybrid node is no EC2 instance
    assert ("USES_PATCH_BASELINE__aws_core", f"aws_core__aws_ssm_patch_baseline:{OWN_BASELINE}") in hybrid_edges


@pytest.mark.spec("req-aws-core-ssm-patch-state-4")
def test_a_hybrid_node_reads_its_own_tags_and_an_ec2_node_leaves_them_to_the_ec2_instance() -> None:
    ssm = _FakeSsm()
    items = {i["InstanceId"]: i for i in ssm_managed_instances_described(None, client_for=_clients(ssm))}
    assert items[HYBRID_ID]["_tags"] == [{"Key": "team", "Value": "lab"}]
    assert items[EC2_ID]["_tags_unread"] is True and "_tags" not in items[EC2_ID]
    assert [c for c in ssm.calls if c[0] == "list_tags_for_resource"] == [  # once, for the hybrid node
        ("list_tags_for_resource", {"ResourceType": "ManagedInstance", "ResourceId": HYBRID_ID})
    ]


# --- patches: shared nodes, per-instance edges (ruling B2) ----------------------------------------------------------


@pytest.mark.spec("req-aws-core-ssm-patch-state-5")
def test_a_patch_two_instances_report_is_one_node_with_an_edge_from_each() -> None:
    ssm = _FakeSsm()
    session = _Session()
    patches = _by_key(_nodes(PATCH, ssm_patches_described, ssm, session))
    shared = f"{PARTITION}:AMAZON_LINUX_2023:openssl-libs.x86_64:1:3.0.8-1.amzn2023"
    # The kernel patch is INSTALLED wherever it is reported: no node (Q147 option 3).
    assert set(patches) == {shared, f"{PARTITION}:WINDOWS:KB5034441"}
    fields = patches[shared].fields
    assert (fields["partition"], fields["operating_system"], fields["kb_id"]) == (PARTITION, "AMAZON_LINUX_2023", "openssl-libs.x86_64:1:3.0.8-1.amzn2023")
    assert fields["cve_ids"] == ["CVE-2026-0001", "CVE-2026-0002"]  # split, order kept, the repeat dropped
    instances = _by_key(_nodes(MI, ssm_managed_instances_described, ssm, session))
    reports = {
        iid: {e["to_ref"]: e["properties"] for e in _edges(instances[iid]) if e["edge_type"] == "REPORTS_PATCH__aws_core"}
        for iid in (EC2_ID, EC2_ID_2)
    }
    ref = f"{PATCH}:{shared}"
    assert reports[EC2_ID][ref] == {"state": "MISSING", "severity": "Critical", "installed_time": None}  # epoch: never
    assert reports[EC2_ID_2][ref] == {"state": "INSTALLED_PENDING_REBOOT", "severity": "Critical", "installed_time": "2026-11-20T03:00:00Z"}
    assert len(reports[EC2_ID]) == 1  # the INSTALLED kernel row is no edge
    # The walk was made once and shared by both entries.
    assert sum(1 for c in ssm.calls if c[0] == "describe_instance_information") == 1


@pytest.mark.spec("req-aws-core-ssm-patch-state-5")
def test_a_patch_is_sent_once_per_run_however_many_regions_report_it() -> None:
    session = _Session()
    east = _FakeSsm(region="us-gov-east-1")
    west = _FakeSsm(region=REGION)
    first = [p["_key"] for p in _items(PATCH, west, session)]
    second = [p["_key"] for p in _items(PATCH, east, session)]
    assert len(first) == 2 and second == []
    east_instances = {i["InstanceId"]: i for i in ssm_managed_instances_described(session, client_for=_clients(east))}
    assert next(e["key"] for e in east_instances[EC2_ID]["_patches"]) in first  # still named from the second region


@pytest.mark.spec("req-aws-core-ssm-patch-state-6")
def test_the_patch_node_keeps_cve_ids_in_the_shape_the_inspector_projection_reads() -> None:
    """The walk emits no CVE link; the optional projection (ssm_compliance.py, req-aws-core-ssm-compliance) reads
    ``cve_ids`` as compliance.py reads a finding's CVE: a list of strings, each the CVE id as AWS gives it."""
    from tap_plugin.aws_core.collectors.boto3_collector.compliance import _CVE
    from tap_plugin.aws_core.models.ssm_patch import SsmPatch

    patches = _nodes(PATCH, ssm_patches_described, _FakeSsm())
    with_cves = [p for p in patches if p.fields["cve_ids"]]
    assert with_cves and all(_CVE.match(c) for p in with_cves for c in p.fields["cve_ids"])
    assert SsmPatch.FIELD_CRUD_SCHEMA["cve_ids"] == {"type": ["array", "null"], "items": {"type": "string"}}
    assert not any(r.get("target_type", "").startswith("compliance_core") for r in _entry(MI).get("edges", []))


# --- compliance summaries and items -------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-ssm-patch-state-7")
def test_each_compliance_type_is_a_summary_node_held_by_its_instance() -> None:
    ssm = _FakeSsm()
    summaries = _by_key(_nodes(SUMMARY, ssm_compliance_summaries_described, ssm))
    patch_key = f"{PARTITION}:{ACCOUNT}:{REGION}:ManagedInstance/{EC2_ID}/Patch"
    assert set(summaries) == {patch_key, f"{PARTITION}:{ACCOUNT}:{REGION}:ManagedInstance/{EC2_ID}/Association"}
    fields = summaries[patch_key].fields
    assert (fields["account_id"], fields["region"], fields["resource_id"], fields["compliance_type"]) == (ACCOUNT, REGION, EC2_ID, "Patch")
    assert (fields["status"], fields["overall_severity"], fields["non_compliant_count"], fields["non_compliant_critical_count"]) == ("NON_COMPLIANT", "CRITICAL", 2, 1)
    assert fields["compliant_critical_count"] == 3 and fields["execution_time"] == "2026-11-20T03:00:00Z"
    for key, node in summaries.items():  # the summary names its holder by ResourceId (an inbound rule)
        assert [(e["edge_type"], e["from_ref"], e["to_ref"]) for e in _edges(node)] == [
            ("HOLDS_COMPLIANCE_SUMMARY__aws_core", f"{MI}:{EC2_ID}", f"{SUMMARY}:{key}")
        ]
    assert fields["name"] == f"{EC2_ID} Patch"


@pytest.mark.spec("req-aws-core-ssm-patch-state-8")
def test_association_and_custom_items_are_nodes_and_patch_items_are_not_read_twice() -> None:
    ssm = _FakeSsm()
    items = _by_key(_nodes(ITEM, ssm_compliance_items_described, ssm))
    association = f"{PARTITION}:{ACCOUNT}:{REGION}:ManagedInstance/{EC2_ID}/Association/8dfe3659-4309-493a-8755-0123456789ab"
    custom = f"{PARTITION}:{ACCOUNT}:{REGION}:ManagedInstance/{EC2_ID}/Custom:CIS/1.1.1 Ensure mounting of cramfs is disabled"
    assert set(items) == {association, custom}
    assert items[association].fields["details"] == {"DocumentName": "AWS-GatherSoftwareInventory", "DocumentVersion": "1"}
    assert items[custom].fields["item_id"] == "1.1.1 Ensure mounting of cramfs is disabled"  # no Id: the title names it
    held = ("HOLDS_COMPLIANCE_ITEM__aws_core", f"{MI}:{EC2_ID}")
    assert {(e["edge_type"], e["from_ref"], e["to_ref"]) for e in _edges(items[association])} == {
        (*held, f"{ITEM}:{association}"),
        ("CONCERNS_ASSOCIATION__aws_core", f"{ITEM}:{association}", "aws_core__aws_ssm_association:8dfe3659-4309-493a-8755-0123456789ab"),
    }
    assert [(e["edge_type"], e["from_ref"], e["to_ref"]) for e in _edges(items[custom])] == [(*held, f"{ITEM}:{custom}")]


# --- no cap, degradation, and the empty region ------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-ssm-patch-state-9")
def test_every_instance_is_read_with_no_cap_in_chunks_the_api_accepts() -> None:
    many = [_info(f"i-{n:017x}", "EC2Instance") for n in range(120)]
    ssm = _FakeSsm(instances=many, states=[_state(i["InstanceId"], AWS_BASELINE) for i in many],
                   patches={i["InstanceId"]: [_patch(f"pkg-{k}", "MISSING") for k in range(30)] for i in many}, summaries=[], items={})
    instances = list(ssm_managed_instances_described(None, client_for=_clients(ssm)))
    assert len(instances) == 120 and all(len(i["_patches"]) == 30 for i in instances)
    chunks = [len(kw["InstanceIds"]) for method, kw in ssm.calls if method == "describe_instance_patch_states"]
    assert chunks == [50, 50, 20]


@pytest.mark.spec("req-aws-core-ssm-patch-state-10")
def test_a_denied_per_instance_read_is_a_gap_and_a_failed_edge_read_never_an_empty_answer() -> None:
    ssm = _FakeSsm(fail={"describe_instance_patches": True, "list_compliance_items": True})
    item = next(i for i in ssm_managed_instances_described(None, client_for=_clients(ssm)) if i["InstanceId"] == EC2_ID)
    assert item["_hydrate"]["patches"]["status"] == "denied" and item["_hydrate"]["compliance_items"]["status"] == "denied"
    assert item[EDGE_READS]["_patches"] == FAILED
    assert list(ssm_compliance_items_described(None, client_for=_clients(ssm))) == []  # none read, none sent
    assert item[EDGE_READS]["_patch_baseline_id"] == COMPLETE and item["_patch_baseline_id"] == AWS_BASELINE


@pytest.mark.spec("req-aws-core-ssm-patch-state-10")
def test_a_denied_patch_state_read_leaves_the_patch_fields_unobserved() -> None:
    ssm = _FakeSsm(fail={"describe_instance_patch_states": True})
    nodes = _by_key(_nodes(MI, ssm_managed_instances_described, ssm))
    fields = nodes[EC2_ID].fields
    assert fields["patch_missing_count"] is None and fields["patch_baseline_id"] is None
    assert nodes[EC2_ID].raw_item[EDGE_READS]["_patch_baseline_id"] == FAILED
    assert nodes[EC2_ID].raw_item[EDGE_READS]["_patches"] == FAILED
    assert not any(c[0] == "describe_instance_patches" for c in ssm.calls)  # nothing to read patches against


@pytest.mark.spec("req-aws-core-ssm-patch-state-10")
def test_patches_that_cannot_be_keyed_make_the_read_partial_and_no_node() -> None:
    ssm = _FakeSsm(fail={"describe_patch_baselines": True})
    session = _Session()
    assert list(ssm_patches_described(session, client_for=_clients(ssm))) == []
    item = next(i for i in ssm_managed_instances_described(session, client_for=_clients(ssm)) if i["InstanceId"] == EC2_ID)
    assert item["_patches"] == [] and item[EDGE_READS]["_patches"] == PARTIAL
    assert item["_hydrate"]["baseline_systems"]["status"] == "denied"


@pytest.mark.spec("req-aws-core-ssm-patch-state-10")
def test_a_failed_instance_listing_raises_rather_than_read_as_nothing_managed() -> None:
    ssm = _FakeSsm(fail={"describe_instance_information": True})
    with pytest.raises(ClientError):
        list(ssm_managed_instances_described(None, client_for=_clients(ssm)))


@pytest.mark.spec("req-aws-core-ssm-patch-state-9")
def test_a_region_with_nothing_managed_makes_two_listings_and_the_walk_never_calls_sts() -> None:
    ssm, sts = _FakeSsm(instances=[], states=[], patches={}, summaries=[], items={}), _Sts()
    assert list(ssm_managed_instances_described(None, client_for=_clients(ssm, sts))) == []
    assert [c[0] for c in ssm.calls] == ["describe_instance_information", "list_resource_compliance_summaries"]
    assert sts.calls == 0
    list(ssm_managed_instances_described(None, client_for=_clients(_FakeSsm(), sts)))
    assert sts.calls == 0  # keys are built by the entries' derive from the run's scope


@pytest.mark.spec("req-aws-core-ssm-patch-state-5")
def test_the_walk_names_a_patch_exactly_as_the_patch_entry_derives_it() -> None:
    assert _entry(PATCH)["derive"]["_key"] == ssm_patch.PATCH_KEY_TEMPLATE
    session = _Session()
    ssm = _FakeSsm()
    keys = {p["_key"] for p in _items(PATCH, ssm, session)}
    named = {e["key"] for i in _items(MI, ssm, session) for e in i["_patches"]}
    assert named == keys


# --- only the rows that need action are edges (Q147 option 3) ----------------------------------------------------


@pytest.mark.spec("req-aws-core-ssm-patch-state-5")
@pytest.mark.parametrize("state", sorted(ssm_patch.GAP_STATES))
def test_a_row_that_needs_action_is_an_edge_and_its_patch_a_node(state: str) -> None:
    ssm = _FakeSsm(patches={EC2_ID: [_patch("pkg-gap", state)]})
    session = _Session()
    [patch] = _items(PATCH, ssm, session)
    item = next(i for i in _items(MI, ssm, session) if i["InstanceId"] == EC2_ID)
    assert [e["key"] for e in item["_patches"]] == [patch["_key"]]
    assert item["_patches"][0]["properties"]["state"] == state


@pytest.mark.spec("req-aws-core-ssm-patch-state-5")
@pytest.mark.parametrize("state", ["INSTALLED", "INSTALLED_OTHER", "NOT_APPLICABLE"])
def test_a_row_that_needs_no_action_is_neither_edge_nor_node_and_never_partial(state: str) -> None:
    # No KBId either: a row that is no gap is never keyed, so it cannot make the read partial.
    row = {k: v for k, v in _patch("pkg-done", state).items() if k != "KBId"}
    ssm = _FakeSsm(patches={EC2_ID: [row, _patch("pkg-done-2", state)]})
    session = _Session()
    assert list(ssm_patches_described(session, client_for=_clients(ssm))) == []
    item = next(i for i in _items(MI, ssm, session) if i["InstanceId"] == EC2_ID)
    assert item["_patches"] == [] and item[EDGE_READS]["_patches"] == COMPLETE


def test_the_gap_states_are_the_ruled_five_and_cover_every_exposed_state() -> None:
    from tap_plugin.aws_core.collectors.boto3_collector.ssm_compliance import EXPOSED_STATES

    assert ssm_patch.GAP_STATES == {
        "MISSING", "FAILED", "INSTALLED_PENDING_REBOOT", "INSTALLED_REJECTED", "AVAILABLE_SECURITY_UPDATE"
    }
    assert EXPOSED_STATES <= ssm_patch.GAP_STATES  # a finding is only ever read from an edge the walk keeps
    states = set(_SSM.shape_for("PatchComplianceDataState").enum)
    assert ssm_patch.GAP_STATES <= states  # every ruled state is one AWS defines


@pytest.mark.spec("req-aws-core-ssm-patch-state-2", "req-aws-core-ssm-patch-state-5")
def test_the_patch_list_is_not_stored_and_a_note_names_where_aws_lists_it() -> None:
    entry = _entry(MI)
    assert entry["edge_only"]["keys"] == ["_patches"]
    assert any(r["value_path"] == "_patches" and r["edge_type"] == "REPORTS_PATCH__aws_core" for r in entry["edges"])
    nodes = _by_key(_nodes(MI, ssm_managed_instances_described, _FakeSsm()))
    node = nodes[EC2_ID]
    assert node.raw_item["_patches"]  # the edge pass still reads it
    stored = node_envelope(node, {}, {}, persist_configuration=entry["persist_configuration"])["node"]["configuration"]
    assert "_patches" not in stored and "openssl-libs" not in json.dumps(stored)
    assert stored["_patch_list"]["op"] == "DescribeInstancePatches"
    assert {e["edge_type"] for e in _edges(node)} >= {"REPORTS_PATCH__aws_core"}


@pytest.mark.spec("req-aws-core-ssm-patch-state-5")
def test_an_instance_with_no_patch_state_has_no_note_and_an_empty_complete_read() -> None:
    ssm = _FakeSsm(states=[_state(EC2_ID, AWS_BASELINE)])
    item = next(i for i in _items(MI, ssm) if i["InstanceId"] == HYBRID_ID)
    assert "_patch_list" not in item and item["_patches"] == [] and item[EDGE_READS]["_patches"] == COMPLETE


# --- declarations ------------------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-ssm-patch-state-11")
def test_the_four_types_are_registered_and_declare_the_sensitive_members() -> None:
    registry = build_custom_fn_registry()
    for entity_type, fn in ((MI, "ssm_managed_instances_described"), (PATCH, "ssm_patches_described"),
                            (SUMMARY, "ssm_compliance_summaries_described"), (ITEM, "ssm_compliance_items_described")):
        entry = _entry(entity_type)
        assert entry["source"] == {"custom_fn": fn} and registry.get(fn)
        assert entry["persist_configuration"] is True  # req-aws-collector-redaction-1: every entry stores
        assert entry["sensitivity"]["status"] in ("reviewed_may_contain", "reviewed_none_known")
    located = {(loc["path"], loc["evidence"]) for loc in _entry(MI)["sensitivity"]["locations"]}
    assert ("IPAddress", "botocore_sensitive") in located
    # OwnerInformation is botocore-sensitive too, and never reaches an item: the basis says so.
    assert "OwnerInformation" in _entry(MI)["sensitivity"]["basis"]
    sensitive = {
        name
        for op in ("DescribeInstanceInformation", "DescribeInstancePatchStates")
        for name, shape in _SSM.operation_model(op).output_shape.members[
            "InstanceInformationList" if op == "DescribeInstanceInformation" else "InstancePatchStates"
        ].member.members.items()
        if shape.metadata.get("sensitive")
    }
    assert sensitive == {"IPAddress", "OwnerInformation"}


@pytest.mark.spec("req-aws-core-ssm-patch-state-11")
def test_every_projected_payload_passes_the_create_schema_as_grift_import_applies_it() -> None:
    from tap_grid.registry import get_model_class
    from tap_plugin.aws_core.tests.test_trial_run_live import _create_verb_schema, _prepare_null_payload

    ssm = _FakeSsm()
    session = _Session()
    for entity_type, fn in ((MI, ssm_managed_instances_described), (PATCH, ssm_patches_described),
                            (SUMMARY, ssm_compliance_summaries_described), (ITEM, ssm_compliance_items_described)):
        schema = _create_verb_schema(get_model_class(entity_type))
        for node in _nodes(entity_type, fn, ssm, session):
            payload = node_envelope(node, {}, {}, persist_configuration=True)["node"]
            jsonschema.validate(_prepare_null_payload(payload, schema), schema)


# --- through the real collector run, into the grid -------------------------------------------------------------


class _Empty:
    """Every other service: an empty answer to everything."""

    meta = _Meta(REGION, PARTITION)

    def can_paginate(self, _method: str) -> bool:
        return False

    def get_paginator(self, _name: str) -> Any:
        class _P:
            def paginate(self, **_kw: Any):
                yield {}

        return _P()

    def __getattr__(self, name: str):
        return lambda **_kw: {}


@pytest.fixture
def _stub_ssm(monkeypatch):
    from tap_cares.secrets.models import Secret, SecretRef

    secret = Secret(
        ref=SecretRef(scope="aws_core", key="boto_collector"),
        kind="aws_static_access_key",
        description="test",
        data={"access_key_id": "AKIA", "secret_access_key": "shh", "regions_allowed": [REGION]},
        metadata={},
        source_path=__import__("pathlib").Path("/dev/null"),
    )
    ssm, sts = _FakeSsm(), _Sts()

    class _FakeSession:
        class events:  # noqa: N801 — mirrors boto3's attribute
            @staticmethod
            def register(_name: str, _handler: object) -> None:
                return None

        def client(self, service: str, **_kwargs: object) -> Any:
            return {"ssm": ssm, "sts": sts}.get(service, _Empty())

    monkeypatch.setattr(cred, "resolve_secret", lambda _ref: secret)
    # A new session per run, as a real run builds one: the SSM walk is shared within a run, never across two.
    monkeypatch.setattr(collector_mod, "build_session", lambda _data: _FakeSession())
    monkeypatch.setattr(
        collector_mod, "client_factory", lambda _s, _r: (lambda svc: {"ssm": ssm, "sts": sts}.get(svc, _Empty()))
    )
    monkeypatch.setattr(collector_mod, "caller_account_id", lambda *a, **k: ACCOUNT)
    return ssm


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-ssm-patch-state-11", "req-aws-core-ssm-patch-state-3", "req-aws-core-ssm-patch-state-5")
def test_a_collector_run_lands_the_instances_patches_and_compliance_on_the_grid(_stub_ssm) -> None:
    from tap_cares.collectors.config import CollectorConfig
    from tap_grid.services import get_node
    from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector

    collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
    collector.run()
    assert collector.results["error"] == []

    instance = get_node(node_id(MI, EC2_ID))
    assert (instance.patch_missing_count, instance.patch_baseline_id) == (2, AWS_BASELINE)
    assert OWNER_CANARY not in json.dumps(instance.configuration)
    assert "_patches" not in instance.configuration and instance.configuration["_patch_list"]["op"] == "DescribeInstancePatches"
    assert instance.tags is None  # an EC2 node's tags are the EC2 instance's
    assert get_node(node_id(MI, HYBRID_ID)).tags == {"team": "lab"}
    patch = {"partition": PARTITION, "operating_system": "AMAZON_LINUX_2023", "kb_id": "openssl-libs.x86_64:1:3.0.8-1.amzn2023"}
    assert get_node(node_id(PATCH, patch)).cve_ids == ["CVE-2026-0001", "CVE-2026-0002"]
    edge = edge_between("REPORTS_PATCH__aws_core", MI, EC2_ID, PATCH, patch)
    assert edge.properties == {"state": "MISSING", "severity": "Critical", "installed_time": None}
    edge_between("REPORTS_PATCH__aws_core", MI, EC2_ID_2, PATCH, patch)
    kernel = {"partition": PARTITION, "operating_system": "AMAZON_LINUX_2023", "kb_id": "kernel.x86_64:0:6.1.100-1.amzn2023"}
    assert find_node_id(PATCH, kernel) is None  # installed wherever reported: no node, no edge (Q147 option 3)
    summary = {"account_id": ACCOUNT, "region": REGION, "resource_type": "ManagedInstance", "resource_id": EC2_ID, "compliance_type": "Patch"}
    edge_between("HOLDS_COMPLIANCE_SUMMARY__aws_core", MI, EC2_ID, SUMMARY, summary)
    item = {"account_id": ACCOUNT, "region": REGION, "resource_type": "ManagedInstance", "resource_id": EC2_ID,
            "compliance_type": "Custom:CIS", "item_id": "1.1.1 Ensure mounting of cramfs is disabled"}
    edge_between("HOLDS_COMPLIANCE_ITEM__aws_core", MI, EC2_ID, ITEM, item)
    # The account's own baseline is collected by its entry (OWNER=Self, unchanged), so the hybrid node's edge lands.
    edge_between("USES_PATCH_BASELINE__aws_core", MI, HYBRID_ID, "aws_core__aws_ssm_patch_baseline", OWN_BASELINE)
    # No EC2 instance, association or AWS-provided baseline was collected: those edges were skipped, never minted.
    assert find_node_id("aws_core__aws_ec2_instance", EC2_ID) is None
    assert find_node_id("aws_core__aws_ssm_patch_baseline", AWS_BASELINE) is None
    assert _stub_ssm.unfiltered_baseline_reads == 1  # the walk's lookup, once for the region
    assert OWNER_CANARY not in json.dumps([get_node(node_id(MI, i)).__dict__ for i in (EC2_ID, EC2_ID_2, HYBRID_ID)], default=str)


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-ssm-patch-state-5")
def test_a_closed_gap_is_a_complete_surface_absence_and_its_edge_is_proposed_for_removal(_stub_ssm) -> None:
    """The instance installs the patch: the next run sends no edge for it and claims the instance's REPORTS_PATCH
    scope complete, so core records the stale edge as a removal proposal (tap req-grid-reconcile-edge-authority);
    the instance's other gap keeps its edge. Applying the proposal is reconcile's, under armed authority."""
    from tap_cares.collectors.config import CollectorConfig
    from tap_grid.batch import create_batch
    from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
    from tap_grid.models import BatchEvent, BatchEventType
    from tap_grid.reconcile import RUN_CONFIG_KEY, run_config
    from tap_plugin.aws_core.collectors.boto3_collector import authority
    from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector

    if not authority.importer_accepts_edge_cases():
        pytest.skip("this tap's importer predates edge_cases")
    _stub_ssm.patches[EC2_ID] = [*_stub_ssm.patches[EC2_ID], _patch("glibc.x86_64:0:2.34-1.amzn2023", "MISSING")]

    def _run() -> None:
        collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
        collector.run()
        assert collector.results["error"] == []

    _run()
    openssl = {"partition": PARTITION, "operating_system": "AMAZON_LINUX_2023", "kb_id": "openssl-libs.x86_64:1:3.0.8-1.amzn2023"}
    glibc = {**openssl, "kb_id": "glibc.x86_64:0:2.34-1.amzn2023"}
    closed = edge_between("REPORTS_PATCH__aws_core", MI, EC2_ID, PATCH, openssl)
    edge_between("REPORTS_PATCH__aws_core", MI, EC2_ID, PATCH, glibc)

    _stub_ssm.patches[EC2_ID][0] = {**_stub_ssm.patches[EC2_ID][0], "State": "INSTALLED", "InstalledTime": WHEN}
    # A claim is weighed only inside a collection run, whose lifecycle batch is its read boundary (tap
    # req-grid-reconcile-edge-authority-8); bind one as run_collection does, with authority off.
    run = create_batch(
        source="t:ssm-second-run", name="second run", description="the run after the patch was installed",
        metadata={RUN_CONFIG_KEY: run_config(authority=False, budget=None, collector="test")},
    )
    ambient = get_caller_context()
    set_caller_context(CallerContext(user=ambient.user if ambient else None, batch_id=str(run.entity_id)))
    try:
        _run()
    finally:
        set_caller_context(ambient)
    proposals = BatchEvent.objects.filter(
        event_type=BatchEventType.AUTHORITY_PROPOSED, metadata__record="proposal", entity_id=closed.entity_id
    )
    [proposal] = list(proposals)
    assert proposal.metadata["outcome"] == "proposed" and proposal.metadata["claim"]["read"] == COMPLETE
    assert proposal.metadata["identity"]["edge_type"] == "REPORTS_PATCH__aws_core"
    still = edge_between("REPORTS_PATCH__aws_core", MI, EC2_ID, PATCH, glibc)
    assert not BatchEvent.objects.filter(
        event_type=BatchEventType.AUTHORITY_PROPOSED, metadata__record="proposal", entity_id=still.entity_id
    ).exists()
