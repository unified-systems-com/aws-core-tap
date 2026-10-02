"""aws-scp-rulebook writes SCP statements out as rules (req-aws-core-panel-scp-rulebook). Pure: no grid."""

from __future__ import annotations

from tap_plugin.aws_core.panels.scp_rulebook import fold_rulebook, rule_of

DENY_ROOT = {
    "policy_id": "p2", "policy": "deny-root-user", "description": "Root may do nothing.", "aws_managed": False,
    "sid": "DenyRootUser", "actions": ["*"], "not_actions": [], "resources": ["*"], "not_resources": [],
    "conditions": [{"condition_key": "aws:principalarn", "operator": "stringlike", "values": ["arn:aws:iam::*:root"]}],
    "positions": [0],
}
REGION_DENY = {
    "policy_id": "p1", "policy": "deny-regions", "description": "", "aws_managed": False, "sid": "DenyOtherRegions",
    "actions": [], "not_actions": ["iam:*", "sts:*"], "resources": ["*"], "not_resources": [],
    "conditions": [{"condition_key": "aws:requestedregion", "operator": "forallvalues:stringnotequalsifexists",
                    "values": ["us-gov-west-1", "us-gov-east-1"]}],
    "positions": [1],
}


def test_star_reads_as_every_action_on_any_resource() -> None:
    r = rule_of(DENY_ROOT)
    assert r["actions"] == {"lead": "every action", "items": []}
    assert r["resources"] == {"lead": "any resource", "items": []}
    assert r["conditions"][0]["words"] == "matches" and r["conditions"][0]["values"] == ["arn:aws:iam::*:root"]


def test_not_action_reads_as_every_action_except() -> None:
    r = rule_of(REGION_DENY)
    assert r["actions"] == {"lead": "every action except", "items": ["iam:*", "sts:*"]}
    (c,) = r["conditions"]
    assert c["words"] == "every value is none of" and c["join"] == "," and c["if_exists"] == "if present"


def test_a_negated_operator_with_one_value_stays_plain() -> None:
    row = {**DENY_ROOT, "conditions": [{"condition_key": "k", "operator": "stringnotlike", "values": ["v"]}]}
    (c,) = rule_of(row)["conditions"]
    assert (c["words"], c["join"]) == ("does not match", "or")


def test_an_unknown_operator_is_shown_as_aws_spells_it() -> None:
    row = {**DENY_ROOT, "conditions": [{"condition_key": "k", "operator": "somenewoperator", "values": ["v"]}]}
    assert rule_of(row)["conditions"][0]["words"] == "somenewoperator"


def test_rules_group_by_policy_with_targets_and_number_across_the_book() -> None:
    policies = fold_rulebook([DENY_ROOT, REGION_DENY],
                             [{"policy_id": "p2", "target": "Tenants", "kind": "aws_core__aws_organizational_unit"}])
    assert [p["name"] for p in policies] == ["deny-regions", "deny-root-user"]
    assert [r["number"] for p in policies for r in p["rules"]] == [1, 2]
    assert policies[0]["targets"] == [] and policies[0]["targets_known"] is True
    assert policies[1]["targets"] == [{"name": "Tenants", "kind": "OU"}]


def test_unreadable_attachments_are_not_attached_to_nothing() -> None:
    (policy,) = fold_rulebook([DENY_ROOT], None)
    assert policy["targets_known"] is False
