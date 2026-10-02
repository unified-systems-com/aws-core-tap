"""aws-baseline folds Gryphon rows into the security baseline matrix (req-aws-core-panel-baseline).

Pure functions: no grid. The rule under test is that unknown is never off: a null setting, a missing
node, a missing account link and a failed read each stay distinct from an observed off.
"""

from __future__ import annotations

from typing import Any

from tap_plugin.aws_core.panels.baseline import (
    COLUMNS,
    SERVICES,
    control_tower_cell,
    ebs_cell,
    fold_baseline,
    s3_pab_cell,
    service_cell,
)

BY_KEY = {s.key: s for s in SERVICES}
FLAGS = ("block_public_acls", "ignore_public_acls", "block_public_policy", "restrict_public_buckets")


def _fp(fid: str, region: str, ebs: Any = None) -> dict[str, Any]:
    return {"footprint": fid, "account_id": "111111111111", "region": region, "ebs": ebs, "ebs_key": None}


def _acct(fid: str, value: Any) -> dict[str, Any]:
    return {"footprint": fid, "account": "acct-1", "account_name": "prod", **dict.fromkeys(FLAGS, value)}


def _state(matrix: dict[str, Any], row: int, key: str) -> str:
    return next(c["state"] for c in matrix["rows"][row]["cells"] if c["key"] == key)


def test_ebs_reads_true_false_and_null_as_three_states() -> None:
    assert [ebs_cell(v)["state"] for v in (True, False, None)] == ["on", "off", "unknown"]


def test_s3_block_is_on_only_when_all_four_flags_are_on() -> None:
    assert s3_pab_cell(dict.fromkeys(FLAGS, True))["state"] == "on"
    assert s3_pab_cell({**dict.fromkeys(FLAGS, True), "block_public_policy": False})["state"] == "off"
    assert s3_pab_cell({**dict.fromkeys(FLAGS, True), "ignore_public_acls": None})["state"] == "unknown"
    assert s3_pab_cell(None)["state"] == "unknown"


def test_a_missing_service_node_is_unknown_never_off() -> None:
    for service in SERVICES:
        assert service_cell(service, [])["state"] == "unknown", service.key


def test_service_nodes_read_on_and_off_from_what_aws_answered() -> None:
    assert service_cell(BY_KEY["config"], [{"value": True}])["state"] == "on"
    assert service_cell(BY_KEY["config"], [{"value": False}])["state"] == "off"
    assert service_cell(BY_KEY["config"], [{"value": None}])["state"] == "unknown"
    assert service_cell(BY_KEY["guardduty"], [{"value": "DISABLED"}, {"value": "ENABLED"}])["state"] == "on"
    assert service_cell(BY_KEY["guardduty"], [{"value": "DISABLED"}])["state"] == "off"
    assert service_cell(BY_KEY["access_analyzer"], [{"value": "CREATING"}])["state"] == "unknown"
    assert service_cell(BY_KEY["access_analyzer"], [{"value": "FAILED"}])["state"] == "off"
    # A hub exists only when the account is subscribed; there is no "off" hub to observe.
    assert service_cell(BY_KEY["securityhub"], [{"value": "arn:aws-us-gov:securityhub:..."}])["state"] == "on"


def test_control_tower_enrollment_follows_the_ou_tree() -> None:
    parent = {"acct-1": "ou-stage", "ou-stage": "ou-tenants", "ou-tenants": "root"}
    covered = {"ou-tenants": [{"name": "AWSControlTowerBaseline", "status": "SUCCEEDED"}]}
    assert control_tower_cell("acct-1", parent, covered)["state"] == "on"
    assert control_tower_cell("acct-1", parent, {"ou-stage": [{"name": "b", "status": "FAILED"}]})["state"] == "off"
    assert control_tower_cell("acct-1", parent, {})["state"] == "unknown"
    assert control_tower_cell(None, parent, covered)["state"] == "unknown"


def test_a_cycle_in_the_tree_terminates() -> None:
    assert control_tower_cell("a", {"a": "b", "b": "a"}, {})["state"] == "unknown"


def test_the_matrix_has_one_row_per_footprint_and_a_column_per_control() -> None:
    m = fold_baseline([_fp("f2", "us-gov-west-1", ebs=False), _fp("f1", "us-gov-east-1", ebs=True)],
                      [_acct("f1", True), _acct("f2", True)],
                      {s.key: [] for s in SERVICES}, [], [])
    assert [r["region"] for r in m["rows"]] == ["us-gov-east-1", "us-gov-west-1"]
    assert [c["key"] for c in m["rows"][0]["cells"]] == [k for k, _ in COLUMNS]
    assert (_state(m, 0, "ebs"), _state(m, 1, "ebs"), _state(m, 0, "s3_pab")) == ("on", "off", "on")
    assert m["cells_total"] == 2 * len(COLUMNS)
    assert (m["cells_on"], m["cells_off"]) == (3, 1)
    assert m["cells_unknown"] == m["cells_total"] - 4


def test_a_failed_read_marks_its_column_failed_not_off() -> None:
    services: dict[str, Any] = {s.key: [] for s in SERVICES}
    services["guardduty"] = None
    m = fold_baseline([_fp("f1", "us-gov-east-1")], [_acct("f1", False)], services, None, [], account_failed=True)
    assert _state(m, 0, "guardduty") == "failed"
    assert _state(m, 0, "s3_pab") == "failed"
    assert _state(m, 0, "control_tower") == "failed"
    assert _state(m, 0, "config") == "unknown"
    assert m["cells_failed"] == 3 and m["cells_unknown"] == m["cells_total"] - m["cells_on"] - m["cells_off"] - 3


def test_service_rows_land_on_their_own_footprint() -> None:
    services: dict[str, Any] = {s.key: [] for s in SERVICES}
    services["guardduty"] = [{"footprint": "f2", "name": "d-1", "value": "ENABLED"}]
    m = fold_baseline([_fp("f1", "us-gov-east-1"), _fp("f2", "us-gov-west-1")], [], services, [], [])
    assert (_state(m, 0, "guardduty"), _state(m, 1, "guardduty")) == ("unknown", "on")


def test_design_nodes_do_not_turn_a_control_on() -> None:
    design = {"value": "ENABLED", "name": "planned", "dims": {"dcom": "design"}}
    assert service_cell(BY_KEY["guardduty"], [design])["state"] == "unknown"
    assert service_cell(BY_KEY["securityhub"], [{**design, "value": "arn"}])["state"] == "unknown"
    assert service_cell(BY_KEY["guardduty"], [design, {"value": "DISABLED"}])["state"] == "off"
    planned = [{"target": "acct-1", "name": "b", "status": "SUCCEEDED", "dims": {"dcom": "design"}}]
    m = fold_baseline([_fp("f1", "us-gov-east-1")], [_acct("f1", True)], {s.key: [] for s in SERVICES}, [], planned)
    assert _state(m, 0, "control_tower") == "unknown"


def test_design_footprints_and_accounts_are_never_observed_off() -> None:
    design = {"dcom": "design"}
    fps = [{**_fp("f-design", "us-gov-east-1", ebs=False), "dims": design, "account_id": "222222222222"},
           _fp("f-real", "us-gov-west-1", ebs=None)]
    accts = [{**_acct("f-design", False), "dims": design},
             {**_acct("f-real", False), "account": "acct-design", "dims": design}]
    m = fold_baseline(fps, accts, {s.key: [] for s in SERVICES}, [], [])
    assert [r["region"] for r in m["rows"]] == ["us-gov-west-1"]
    assert m["accounts"] == 1 and m["cells_off"] == 0
    assert _state(m, 0, "s3_pab") == "unknown"
    assert _state(m, 0, "control_tower") == "unknown"
