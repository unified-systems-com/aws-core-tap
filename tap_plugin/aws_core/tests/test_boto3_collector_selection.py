"""Collection selection: grammar, matching, account forms, fail-closed checks.

Spec: specs/spec-aws-core-secrets.md (req-aws-core-secret-selection) and
specs/spec-aws-core-collector-v0.md (req-aws-collector-selection). Pure unit tests over the committed manifest;
no DB, no AWS.
"""

from __future__ import annotations

import pytest
from tap_plugin.aws_core.collectors.boto3_collector import selection as sel
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries

ENTRIES = manifest_entries()


def _selected(**keys) -> set[str]:
    selection = sel.parse_selection(keys)
    return {e["entity_type"] for e in sel.apply_type_selection(ENTRIES, selection).selected} - sel.ANCHOR_ENTITIES


def _entities(service: str) -> set[str]:
    return {e["entity_type"] for e in ENTRIES if e["service"] == service}


@pytest.mark.spec("req-aws-collector-selection-1")
def test_include_selects_a_service():
    assert _selected(include_types=["ec2:*"]) == _entities("ec2")


@pytest.mark.spec("req-aws-collector-selection-1")
def test_include_selects_one_entity_of_a_service():
    assert _selected(include_types=["eks:eks_cluster"]) == {"aws_core__aws_eks_cluster"}


@pytest.mark.spec("req-aws-collector-selection-1")
def test_a_wildcard_service_selects_every_entity_with_the_suffix():
    got = _selected(include_types=["*:*_policy"])
    assert got and all(t.endswith("_policy") for t in got)
    assert got == {e["entity_type"] for e in ENTRIES if sel.entity_of(e).endswith("_policy")}


@pytest.mark.spec("req-aws-collector-selection-1")
def test_exclusion_wins_over_an_overlapping_include():
    assert _selected(include_types=["ec2:*"], exclude_types=["ec2:vpc"]) == _entities("ec2") - {"aws_core__aws_vpc"}


@pytest.mark.spec("req-aws-collector-selection-1")
def test_an_exclude_alone_selects_everything_else():
    assert _selected(exclude_types=["ec2:*"]) == {e["entity_type"] for e in ENTRIES} - _entities("ec2") - sel.ANCHOR_ENTITIES


@pytest.mark.spec("req-aws-collector-selection-1")
def test_no_pattern_selects_every_entry():
    everything = {e["entity_type"] for e in ENTRIES} - sel.ANCHOR_ENTITIES
    assert _selected() == everything
    assert _selected(include_types=["*:*"]) == everything


def test_matching_is_case_sensitive_and_a_question_mark_matches_one_character():
    entry = {"service": "ec2", "entity_type": "aws_core__aws_vpc"}
    assert sel.Selection(include_types=("ec2:v?c",)).matches(entry)
    assert not sel.Selection(include_types=("ec2:v?",)).matches(entry)
    assert not sel.Selection(include_types=("EC2:vpc",)).matches(entry)  # matching is case-sensitive; the grammar refuses it earlier


@pytest.mark.spec("req-aws-collector-selection-4")
@pytest.mark.parametrize("key", ["include_types", "exclude_types"])
def test_a_pattern_matching_no_entry_stops_the_run_naming_it(key):
    selection = sel.parse_selection({key: ["ec2:no_such_entity"]})
    with pytest.raises(sel.SelectionError) as raised:
        sel.apply_type_selection(ENTRIES, selection)
    assert raised.value.code == sel.PATTERN_UNMATCHED
    assert "ec2:no_such_entity" in str(raised.value)
    assert key in str(raised.value)


@pytest.mark.spec("req-aws-collector-selection-4")
def test_a_pattern_is_checked_against_the_whole_manifest_not_what_exclusion_left():
    # `ec2:vpc` is excluded by the second pattern but still exists in the manifest, so the include is not a typo.
    selection = sel.parse_selection({"include_types": ["ec2:vpc"], "exclude_types": ["ec2:*"]})
    result = sel.apply_type_selection(ENTRIES, selection)
    assert {e["entity_type"] for e in result.selected} == sel.ANCHOR_ENTITIES


@pytest.mark.spec("req-aws-core-secret-selection-3")
@pytest.mark.parametrize(
    "pattern",
    ["ec2", "ec2:", ":vpc", "EC2:vpc", "ec2:Vpc", "ec2:v[a-z]c", "ec2:vpc:x", "ec2 :vpc", ""],
)
def test_a_pattern_outside_the_grammar_is_refused(pattern):
    with pytest.raises(sel.SelectionError):
        sel.parse_selection({"include_types": [pattern]})


@pytest.mark.spec("req-aws-core-secret-selection-3")
@pytest.mark.parametrize("pattern", ["*:*", "*:*_policy", "e*:vpc", "ec2:vpc", "elbv2:*", "sso-admin:*"])
def test_a_pattern_inside_the_grammar_is_accepted(pattern):
    assert sel.parse_selection({"include_types": [pattern]}).include_types == (pattern,)


@pytest.mark.spec("req-aws-core-secret-selection-3")
@pytest.mark.parametrize("key", ["include_types", "exclude_types", "accounts_allowed"])
def test_an_empty_list_is_refused(key):
    with pytest.raises(sel.SelectionError):
        sel.parse_selection({key: []})


@pytest.mark.spec("req-aws-core-secret-selection-3")
def test_duplicate_patterns_collapse():
    assert sel.parse_selection({"include_types": ["ec2:*", "ec2:*"]}).include_types == ("ec2:*",)


@pytest.mark.spec("req-aws-core-secret-selection-1")
def test_a_secret_without_the_keys_selects_everything():
    selection = sel.parse_selection({})
    assert not selection.narrows_types and not selection.narrows_accounts
    assert selection.account_selected("123456789012")
    assert not sel.apply_type_selection(ENTRIES, selection).leaves_unselected


# --- account forms ----------------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-secret-selection-4")
def test_an_id_and_an_arn_naming_the_same_account_normalise_to_the_same_id_and_collapse():
    got = sel.parse_selection(
        {
            "accounts_allowed": [
                "210987654321",
                "arn:aws-us-gov:iam::123456789012:role/Tap",
                "123456789012",
                "arn:aws-us-gov:organizations::111122223333:account/o-abc123/123456789012",
            ]
        },
        partition="aws-us-gov",
    )
    assert got.accounts_allowed == ("123456789012", "210987654321")


@pytest.mark.spec("req-aws-core-secret-selection-4")
def test_an_organizations_arn_names_the_member_not_the_management_account():
    arn = "arn:aws:organizations::111122223333:account/o-abc123/444455556666"
    assert sel.account_id_of(arn, "aws") == "444455556666"


@pytest.mark.spec("req-aws-core-secret-selection-4")
@pytest.mark.parametrize(
    "ref",
    [
        "arn:aws:iam::*:role/x",  # a wildcard
        "arn:aws:iam::123456789012:role/*",  # a wildcard anywhere
        "arn:aws:s3:::a-bucket",  # an empty account field
        "arn:aws-us-gov:iam::123456789012:role/x",  # another partition than the run's
        "not-an-account",
        "12345",
    ],
)
def test_an_account_reference_outside_the_forms_is_refused(ref):
    with pytest.raises(sel.SelectionError):
        sel.parse_selection({"accounts_allowed": [ref]}, partition="aws")


@pytest.mark.spec("req-aws-core-secret-selection-4")
def test_the_partition_is_not_checked_until_it_is_known():
    assert sel.parse_selection({"accounts_allowed": ["arn:aws-us-gov:iam::123456789012:role/x"]}).accounts_allowed == (
        "123456789012",
    )


@pytest.mark.spec("req-aws-core-secret-selection-5")
def test_expected_account_id_must_be_in_accounts_allowed():
    with pytest.raises(sel.SelectionError):
        sel.parse_selection({"accounts_allowed": ["123456789012"], "expected_account_id": "210987654321"})
    ok = sel.parse_selection({"accounts_allowed": ["123456789012"], "expected_account_id": "123456789012"})
    assert ok.accounts_allowed == ("123456789012",)


@pytest.mark.spec("req-aws-collector-selection-6")
def test_a_resolved_account_is_selected_only_when_inside_accounts_allowed():
    selection = sel.parse_selection({"accounts_allowed": ["123456789012"]})
    assert selection.account_selected("123456789012")
    assert not selection.account_selected("210987654321")


# --- the retire flag ----------------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-secret-selection-7")
@pytest.mark.spec("req-aws-collector-selection-13")
@pytest.mark.parametrize("extra", [{}, {"include_types": ["ec2:*"]}, {"accounts_allowed": ["123456789012"]}])
def test_retire_within_selection_true_is_refused_naming_the_blocker(extra):
    with pytest.raises(sel.SelectionError) as raised:
        sel.parse_selection({"retire_within_selection": True, **extra})
    assert "tap#1156" in str(raised.value)


@pytest.mark.spec("req-aws-core-secret-selection-7")
def test_retire_within_selection_false_or_absent_is_the_default_and_a_non_boolean_is_refused():
    assert sel.parse_selection({"retire_within_selection": False}).retire_within_selection is False
    assert sel.parse_selection({}).retire_within_selection is False
    with pytest.raises(sel.SelectionError):
        sel.parse_selection({"retire_within_selection": "yes"})


# --- the echo -------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-collector-selection-9")
def test_the_echo_carries_patterns_accounts_counts_and_the_parent_reads():
    selection = sel.parse_selection({"include_types": ["ec2:vpc"], "accounts_allowed": ["123456789012"]})
    result = sel.apply_type_selection(ENTRIES, selection)
    got = sel.echo(selection, entries_total=len(ENTRIES), type_selection=result)
    assert got["include_types"] == ["ec2:vpc"] and got["accounts_allowed"] == ["123456789012"]
    assert got["entries_total"] == len(ENTRIES)
    assert got["entries_selected"] == len(result.selected) == 2  # the entry and the account anchor
    assert got["entries_skipped"] == len(ENTRIES) - 2
    assert isinstance(got["parent_reads"], list)


@pytest.mark.spec("req-aws-collector-selection-2")
def test_a_selected_child_names_the_parent_list_call_it_needs():
    child = {"service": "eks", "entity_type": "aws_core__aws_x", "source": {"aws_op": "Describe", "per": {"aws_op": "ListClusters"}}}
    assert sel.parent_reads([child]) == ["eks:ListClusters"]
    assert sel.parent_reads([{"service": "ec2", "entity_type": "aws_core__aws_y", "source": {"aws_op": "DescribeVpcs"}}]) == []


@pytest.mark.spec("req-aws-collector-selection-5")
def test_only_a_selection_that_leaves_something_out_is_a_selected_run():
    everything = sel.apply_type_selection(ENTRIES, sel.parse_selection({"include_types": ["*:*"]}))
    some = sel.apply_type_selection(ENTRIES, sel.parse_selection({"exclude_types": ["ec2:vpc"]}))
    assert not everything.leaves_unselected
    assert some.leaves_unselected


@pytest.mark.spec("req-aws-collector-selection-3")
def test_the_account_anchor_is_selected_whatever_the_patterns_say_and_is_never_counted_skipped():
    result = sel.apply_type_selection(ENTRIES, sel.parse_selection({"include_types": ["ec2:vpc"]}))
    chosen = {e["entity_type"] for e in result.selected}
    assert chosen == {"aws_core__aws_vpc"} | sel.ANCHOR_ENTITIES
    assert not (sel.ANCHOR_ENTITIES & {e["entity_type"] for e in result.skipped})
    only_anchor_excluded = sel.apply_type_selection(ENTRIES, sel.parse_selection({"exclude_types": ["sts:*"]}))
    assert sel.ANCHOR_ENTITIES <= {e["entity_type"] for e in only_anchor_excluded.selected}
    assert not only_anchor_excluded.leaves_unselected


@pytest.mark.spec("req-aws-collector-selection-2")
def test_parent_reads_walks_a_nested_chain_a_per_level_service_and_skips_fixed_values():
    nested = {
        "service": "eks",
        "entity_type": "aws_core__aws_x",
        "source": {"aws_op": "Describe", "per": {"aws_op": "ListNodegroups", "per": {"aws_op": "ListClusters"}}},
    }
    other_service = {
        "service": "ec2",
        "entity_type": "aws_core__aws_y",
        "source": {"aws_op": "Describe", "per": {"service": "organizations", "aws_op": "ListAccounts"}},
    }
    fixed = {"service": "ec2", "entity_type": "aws_core__aws_z", "source": {"aws_op": "Describe", "per": {"values": ["a", "b"]}}}
    assert sel.parent_reads([nested]) == ["eks:ListClusters", "eks:ListNodegroups"]
    assert sel.parent_reads([other_service]) == ["organizations:ListAccounts"]
    assert sel.parent_reads([fixed]) == []


@pytest.mark.spec("req-aws-collector-selection-2")
def test_every_per_entry_of_the_committed_manifest_names_at_least_one_parent_read_unless_its_parents_are_fixed():
    for entry in ENTRIES:
        per = (entry.get("source") or {}).get("per")
        if not isinstance(per, dict):
            continue
        chain = []
        while isinstance(per, dict):
            chain.append(per)
            per = per.get("per")
        if all("values" in level for level in chain):
            assert sel.parent_reads([entry]) == [], entry["entity_type"]
        else:
            assert sel.parent_reads([entry]), entry["entity_type"]
