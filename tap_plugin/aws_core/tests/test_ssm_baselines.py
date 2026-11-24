"""SSM patch baselines, each account's default baseline per operating system, and patch groups
(req-aws-core-ssm-baselines, aws-core-tap#281, rulings Q139a option 2 and Q139b).

Driven by the SSM fakes of ``test_ssm_patch_state``, whose canned pages are checked against botocore's own ``ssm``
output shapes. One test drives the real collector run into the grid. No AWS call is made.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import jsonschema
import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector import ssm_baselines
from tap_plugin.aws_core.collectors.boto3_collector.authority import COMPLETE, EDGE_READS, FAILED, PARTIAL
from tap_plugin.aws_core.collectors.boto3_collector.batch import node_envelope
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    build_custom_fn_registry,
    ssm_default_patch_baselines_described,
    ssm_patch_baselines_described,
    ssm_patch_groups_described,
)
from tap_plugin.aws_core.tests.grid_keys import edge_between, node_id
from tap_plugin.aws_core.tests.test_ssm_patch_state import (  # noqa: F401 — _stub_ssm is a fixture
    ACCOUNT,
    AWS_BASELINE,
    EC2_ID,
    EC2_ID_2,
    HYBRID_ID,
    MI,
    OWN_BASELINE,
    PARTITION,
    REGION,
    _clients,
    _denied,
    _edges,
    _entry,
    _FakeSsm,
    _items,
    _Session,
    _shape_checked,
    _state,
    _stub_ssm,
)

BASELINE = "aws_core__aws_ssm_patch_baseline"
DEFAULT = "aws_core__aws_ssm_default_patch_baseline"
GROUP = "aws_core__aws_ssm_patch_group"
#: The account segment of the AWS-owned baseline's ARN (a documentation placeholder stands in for AWS's account).
AWS_ACCOUNT = AWS_BASELINE.split(":")[4]


class _Ssm(_FakeSsm):
    """The SSM fake, with patch groups and an own baseline's tags."""

    def __init__(self, *, groups: list[dict[str, Any]] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.groups = groups if groups is not None else [
            {"PatchGroup": "prod", "BaselineIdentity": {"BaselineId": AWS_BASELINE, "BaselineName": "AWS-AmazonLinux2023DefaultPatchBaseline",
                                                        "OperatingSystem": "AMAZON_LINUX_2023", "DefaultBaseline": True}},
            {"PatchGroup": "prod", "BaselineIdentity": {"BaselineId": OWN_BASELINE, "BaselineName": "lab-windows",
                                                        "OperatingSystem": "WINDOWS", "DefaultBaseline": False}},
        ]

    def pages(self, method: str, kwargs: dict[str, Any]) -> list[dict[str, Any]]:
        if method == "describe_patch_groups":
            return [{"Mappings": self.groups[:1]}, {"Mappings": self.groups[1:]}]
        return super().pages(method, kwargs)

    def list_tags_for_resource(self, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("ResourceType") != "PatchBaseline":
            return super().list_tags_for_resource(**kwargs)
        self.calls.append(("list_tags_for_resource", kwargs))
        assert kwargs["ResourceId"] == OWN_BASELINE, "an AWS-owned baseline's tags are never read"
        if self.fail.get("list_tags_for_resource"):
            raise _denied("ListTagsForResource")
        return _shape_checked("ListTagsForResource", {"TagList": [{"Key": "team", "Value": "lab"}]})


def _by(items: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(i[key]): i for i in items}


# --- baselines (Q139a option 2) ----------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-ssm-baselines-1")
def test_every_baseline_is_listed_and_an_aws_owned_one_is_shared_and_untagged() -> None:
    ssm = _Ssm()
    baselines = _by(list(ssm_patch_baselines_described(None, client_for=_clients(ssm))), "BaselineId")
    assert set(baselines) == {AWS_BASELINE, OWN_BASELINE}
    assert not any("Filters" in kw for m, kw in ssm.calls if m == "describe_patch_baselines")
    aws = baselines[AWS_BASELINE]
    assert aws["_aws_owned"] is True and aws["_tags_unread"] is True and "DefaultBaseline" not in aws
    own = baselines[OWN_BASELINE]
    assert own["_aws_owned"] is False and own["_tags"] == [{"Key": "team", "Value": "lab"}] and "_tags_unread" not in own
    assert own["DefaultBaseline"] is False  # the account's own: its flag is its own fact
    nodes = {i["BaselineId"]: i for i in _items(BASELINE, ssm)}
    assert set(nodes) == {AWS_BASELINE, OWN_BASELINE}


@pytest.mark.spec("req-aws-core-ssm-baselines-1")
def test_the_aws_owned_baseline_is_keyed_by_its_arn_and_owned_by_aws_s_account() -> None:
    from tap_plugin.aws_core.collectors.boto3_collector.containment import resource_owner
    from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item

    entry = _entry(BASELINE)
    for item in _items(BASELINE, _Ssm()):
        node = project_item(entry, item, {"region": REGION})
        owner = resource_owner(entry, node, ACCOUNT)
        if item["_aws_owned"]:
            assert node.natural_key == AWS_BASELINE and owner == AWS_ACCOUNT != ACCOUNT
            assert node.fields["aws_owned"] is True and node.fields["operating_system"] == "AMAZON_LINUX_2023"
        else:
            assert node.natural_key == OWN_BASELINE and owner == ACCOUNT


@pytest.mark.spec("req-aws-core-ssm-baselines-5")
def test_a_denied_own_tag_read_is_a_gap_and_a_denied_listing_raises() -> None:
    ssm = _Ssm(fail={"list_tags_for_resource": True})
    own = _by(list(ssm_patch_baselines_described(None, client_for=_clients(ssm))), "BaselineId")[OWN_BASELINE]
    assert own["_tags_unread"] is True and own["_hydrate"]["tags"]["status"] == "denied"
    failing = _Ssm(fail={"describe_patch_baselines": True})
    with pytest.raises(ClientError):
        list(ssm_patch_baselines_described(None, client_for=_clients(failing)))
    with pytest.raises(ClientError):
        list(ssm_default_patch_baselines_described(None, client_for=_clients(failing)))


# --- defaults (Q139a) --------------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-ssm-baselines-2")
def test_each_default_is_a_node_per_operating_system_naming_its_baseline() -> None:
    ssm = _Ssm()
    [default] = _items(DEFAULT, ssm)
    assert default["_key"] == f"{PARTITION}:{ACCOUNT}:{REGION}:AMAZON_LINUX_2023"
    assert (default["BaselineId"], default["_aws_owned"]) == (AWS_BASELINE, True)
    assert default[EDGE_READS]["BaselineId"] == COMPLETE
    from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item

    node = project_item(_entry(DEFAULT), default, {"region": REGION})
    assert (node.fields["partition"], node.fields["account_id"], node.fields["region"], node.fields["operating_system"]) == (
        PARTITION, ACCOUNT, REGION, "AMAZON_LINUX_2023")
    assert {(e["edge_type"], e["to_ref"]) for e in _edges(node)} == {
        ("DEFAULTS_TO_PATCH_BASELINE__aws_core", f"{BASELINE}:{AWS_BASELINE}")
    }
    assert not any(m in ("get_default_patch_baseline", "get_patch_baseline_for_patch_group") for m, _ in ssm.calls)


# --- patch groups (Q139b) ----------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-ssm-baselines-3", "req-aws-core-ssm-baselines-4")
def test_a_patch_group_names_its_baselines_and_its_instances() -> None:
    from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item

    ssm = _Ssm(states=[_state(EC2_ID, AWS_BASELINE), _state(EC2_ID_2, AWS_BASELINE), {**_state(HYBRID_ID, OWN_BASELINE), "PatchGroup": "lab"}])
    session = _Session()
    [group] = _items(GROUP, ssm, session)  # "lab" is no registered group: no node
    assert group["_key"] == f"{PARTITION}:{ACCOUNT}:{REGION}:prod"
    assert group["_baseline_ids"] == sorted([AWS_BASELINE, OWN_BASELINE]) and group["_members"] == [EC2_ID, EC2_ID_2]
    assert group[EDGE_READS] == {"_baseline_ids": COMPLETE, "_members": COMPLETE}
    node = project_item(_entry(GROUP), group, {"region": REGION})
    assert node.fields["patch_group"] == "prod" and node.fields["baseline_ids"] == group["_baseline_ids"]
    edges = {(e["edge_type"], e["from_ref"], e["to_ref"]) for e in _edges(node)}
    ref = node.ref
    assert edges == {
        ("REGISTERED_TO_PATCH_BASELINE__aws_core", ref, f"{BASELINE}:{AWS_BASELINE}"),
        ("REGISTERED_TO_PATCH_BASELINE__aws_core", ref, f"{BASELINE}:{OWN_BASELINE}"),
        ("IN_PATCH_GROUP__aws_core", f"{MI}:{EC2_ID}", ref),
        ("IN_PATCH_GROUP__aws_core", f"{MI}:{EC2_ID_2}", ref),
    }


@pytest.mark.spec("req-aws-core-ssm-baselines-4")
def test_members_the_run_could_not_see_are_never_read_as_none() -> None:
    partial = _Ssm(fail={"describe_instance_patch_states": True})
    [group] = list(ssm_patch_groups_described(_Session(), client_for=_clients(partial)))
    assert group["_members"] == [] and group[EDGE_READS]["_members"] == PARTIAL
    failed = _Ssm(fail={"describe_instance_information": True})
    [group] = list(ssm_patch_groups_described(_Session(), client_for=_clients(failed)))
    assert group[EDGE_READS]["_members"] == FAILED and group["_hydrate"]["members"]["status"] == "denied"
    assert group[EDGE_READS]["_baseline_ids"] == COMPLETE


@pytest.mark.spec("req-aws-core-ssm-baselines-5")
def test_a_denied_group_listing_skips_the_groups_only() -> None:
    ssm = _Ssm(fail={"describe_patch_groups": True})
    session = _Session()
    with pytest.raises(ClientError):
        list(ssm_patch_groups_described(session, client_for=_clients(ssm)))
    assert len(list(ssm_patch_baselines_described(session, client_for=_clients(ssm)))) == 2
    assert len(list(ssm_default_patch_baselines_described(session, client_for=_clients(ssm)))) == 1


def test_a_region_with_no_group_never_walks_the_instances_for_members() -> None:
    ssm = _Ssm(groups=[])
    assert list(ssm_patch_groups_described(_Session(), client_for=_clients(ssm))) == []
    assert not any(m == "describe_instance_information" for m, _ in ssm.calls)


# --- declarations ------------------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-ssm-baselines-6")
def test_the_three_entries_are_registered_stored_and_their_reads_granted() -> None:
    from tap_plugin.aws_core.collectors.boto3_collector import iam_policy

    registry = build_custom_fn_registry()
    for entity_type, fn in ((BASELINE, "ssm_patch_baselines_described"), (DEFAULT, "ssm_default_patch_baselines_described"),
                            (GROUP, "ssm_patch_groups_described")):
        entry = _entry(entity_type)
        assert entry["source"] == {"custom_fn": fn} and registry.get(fn)
        assert entry["persist_configuration"] is True
        assert entry["sensitivity"]["status"] == "reviewed_may_contain"
    assert iam_policy.catalog()["operations"]["ssm:describe_patch_groups"]["actions"] == ["ssm:DescribePatchGroups"]
    assert ("ssm", "DescribePatchGroups") in iam_policy.inventory()
    assert "ssm:DescribePatchGroups" in iam_policy.actions()
    assert ("ssm", "DescribePatchGroups") not in iam_policy.unverified()
    for op in ("DescribePatchBaselines", "DescribePatchGroups"):
        assert not any(shape.metadata.get("sensitive") for shape in _members_of(op))


def _members_of(op: str) -> list[Any]:
    import botocore.session

    model = botocore.session.get_session().get_service_model("ssm").operation_model(op).output_shape
    listed = next(iter(m for m in model.members.values() if m.type_name == "list"))
    out = list(listed.member.members.values())
    for shape in list(out):
        if shape.type_name == "structure":
            out.extend(shape.members.values())
    return out


@pytest.mark.spec("req-aws-core-ssm-baselines-6")
def test_every_projected_payload_passes_the_create_schema() -> None:
    from tap_grid.registry import get_model_class
    from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
    from tap_plugin.aws_core.tests.test_trial_run_live import _create_verb_schema, _prepare_null_payload

    ssm = _Ssm()
    session = _Session()
    for entity_type in (BASELINE, DEFAULT, GROUP):
        schema = _create_verb_schema(get_model_class(entity_type))
        for item in _items(entity_type, ssm, session):
            payload = node_envelope(project_item(_entry(entity_type), item, {"region": REGION}), {}, {}, persist_configuration=True)["node"]
            jsonschema.validate(_prepare_null_payload(payload, schema), schema)


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-ssm-baselines-6", "req-aws-core-ssm-baselines-1", "req-aws-core-ssm-baselines-4")
def test_a_collector_run_lands_the_baselines_defaults_and_groups(_stub_ssm, monkeypatch) -> None:
    from tap_cares.collectors.config import CollectorConfig
    from tap_grid.services import get_node
    from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector

    groups, canned = _Ssm().groups, _stub_ssm.pages
    monkeypatch.setattr(_stub_ssm, "pages", lambda method, kwargs: (
        [{"Mappings": groups}] if method == "describe_patch_groups" else canned(method, kwargs)))
    collector = Boto3Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
    collector.run()
    assert collector.results["error"] == []

    from tap_grid.dimension_names import containment
    from tap_plugin.aws_core.models.ssm_patch_baseline import SsmPatchBaseline

    aws = get_node(node_id(BASELINE, AWS_BASELINE))
    assert aws.aws_owned is True and aws.tags is None and "DefaultBaseline" not in json.dumps(aws.configuration)
    own = get_node(node_id(BASELINE, OWN_BASELINE))
    assert own.aws_owned is False

    def owned_by(account: str) -> set[str]:
        rows = SsmPatchBaseline.objects.filter(entity__dimensions__contains=containment("aws.account", account))
        return set(rows.values_list("ssm_patch_baseline_id", flat=True))

    # AWS's baseline carries AWS's account, never the collecting account's (Q139a option 2).
    assert owned_by(AWS_ACCOUNT) == {AWS_BASELINE} and owned_by(ACCOUNT) == {OWN_BASELINE}
    # The instance's last operation used AWS's baseline: since Q139a that edge lands.
    edge_between("USES_PATCH_BASELINE__aws_core", MI, EC2_ID, BASELINE, AWS_BASELINE)
    default = {"partition": PARTITION, "account_id": ACCOUNT, "region": REGION, "operating_system": "AMAZON_LINUX_2023"}
    edge_between("DEFAULTS_TO_PATCH_BASELINE__aws_core", DEFAULT, default, BASELINE, AWS_BASELINE)
    group = {"partition": PARTITION, "account_id": ACCOUNT, "region": REGION, "patch_group": "prod"}
    edge_between("REGISTERED_TO_PATCH_BASELINE__aws_core", GROUP, group, BASELINE, OWN_BASELINE)
    for instance in (EC2_ID, EC2_ID_2, HYBRID_ID):
        edge_between("IN_PATCH_GROUP__aws_core", MI, instance, GROUP, group)


def test_aws_owned_is_an_arn_and_an_own_id_is_not() -> None:
    assert ssm_baselines.aws_owned(AWS_BASELINE) and not ssm_baselines.aws_owned(OWN_BASELINE)
