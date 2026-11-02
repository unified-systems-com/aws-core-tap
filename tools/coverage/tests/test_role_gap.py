import json

import pytest

import role_gap


def test_the_committed_list_has_not_drifted_from_the_manifest():
    assert role_gap.problems_of(role_gap.load(), *role_gap.manifest_calls()) == []


def test_a_follow_up_operation_counts_as_called():
    calls, _ = role_gap.manifest_calls()
    assert ("glue", "ListBlueprints") in calls


def test_policy_leaves_out_the_opt_in_and_unfixable_sections():
    doc = role_gap.load()
    actions = role_gap.actions_of(doc)
    assert "glue:GetConnections" not in actions
    assert "securityhub:GetConfigurationPolicy" not in actions
    assert "bedrock:GetFlow" not in actions and "geo:ListTrackers" in actions
    assert "glue:GetConnections" in role_gap.actions_of(doc, include_opt_in=True)
    assert "bedrock:GetFlow" in role_gap.actions_of(doc, include_opt_in=True)
    assert "securityhub:GetConfigurationPolicy" not in role_gap.actions_of(doc, include_opt_in=True)


def test_policy_allows_only_read_verbs():
    policy = role_gap.policy_of(role_gap.load(), include_opt_in=True)
    statement = policy["Statement"][0]
    assert statement["Effect"] == "Allow"
    assert all(a.partition(":")[2].startswith(role_gap.READ_VERBS) for a in statement["Action"])


@pytest.mark.parametrize(
    ("section", "item", "expected"),
    [
        ("collection-gaps", {"action": "ec2:DeleteVpc"}, "ec2:DeleteVpc: not a read verb"),
        ("collection-gaps", {"action": "geo:ListTrackers"}, "geo:ListTrackers: in collection-gaps and collection-gaps"),
        ("collection-gaps", {"action": "geo:ListNotCalledAnywhere"}, "geo:ListNotCalledAnywhere: no manifest entry calls ListNotCalledAnywhere under service geo"),
        ("collection-gaps", {"action": "iam:ListTrackers"}, "iam:ListTrackers: no manifest entry calls ListTrackers under service iam"),
        ("collection-gaps", {"action": "sso:ListThings", "custom_fn": "rekognition_stream_processors_described"}, "sso:ListThings: no manifest entry read by rekognition_stream_processors_described is under service sso"),
        ("collection-gaps", {"action": "sso:ListNothingReal", "custom_fn": "identity_center_applications_described"}, "sso:ListNothingReal: identity_center_applications_described does not call list_nothing_real"),
        ("opt-in-probe-reads", {"action": "sts:GetFederationToken"}, "sts:GetFederationToken: the operation name suggests it returns a credential or secret"),
        ("opt-in-probe-reads", {"action": "ecr:GetAuthorizationToken"}, "ecr:GetAuthorizationToken: the operation name suggests it returns a credential or secret"),
        ("opt-in-probe-reads", {"action": "*:Get*"}, "*:Get*: not service:Operation (one operation, no wildcard)"),
        ("opt-in-probe-reads", {"action": "iam:Get*"}, "iam:Get*: not service:Operation (one operation, no wildcard)"),
        ("opt-in-probe-reads", {"action": "iam:List*"}, "iam:List*: not service:Operation (one operation, no wildcard)"),
        ("collection-gaps", {"action": "nocolon"}, "nocolon: not service:Operation (one operation, no wildcard)"),
        ("opt-in-credential-bearing", {"action": "glue:GetSomething"}, "glue:GetSomething: left out of the policy with no reason"),
    ],
)
def test_the_check_names_each_kind_of_drift(section, item, expected):
    doc = role_gap.load()
    for s in doc["sections"]:
        if s["id"] == section:
            s["actions"].append(item)
    assert expected in role_gap.problems_of(doc, *role_gap.manifest_calls())


def test_every_section_says_why_it_is_there():
    doc = role_gap.load()
    assert doc["description"] and doc["provenance"]["not_established"]
    assert all(s["description"] for s in doc["sections"])


def test_check_exits_zero_on_the_committed_list(capsys):
    assert role_gap.main(["--check"]) == 0


def test_printed_policy_is_json(capsys):
    assert role_gap.main([]) == 0
    assert json.loads(capsys.readouterr().out)["Statement"][0]["Action"]


def test_snake_case_and_the_custom_function_closure():
    assert role_gap.snake_case("ListApplications") == "list_applications"
    assert "list_applications" in role_gap.custom_fn_calls("identity_center_applications_described")
    assert role_gap.custom_fn_calls("no_such_function") == set()


def test_only_calls_on_a_client_count(tmp_path):
    source = tmp_path / "customfns.py"
    source.write_text(
        "def f(session, *, client_for):\n"
        "    \"\"\"Uses list_comment_only.\"\"\"\n"
        "    client = client_for('x')\n"
        "    unused = 'list_unused'\n"
        "    logger.list_logged()\n"
        "    print('list_printed')\n"
        "    _pages(logger, 'list_wrong_receiver')\n"
        "    client.list_attr(x=1)\n"
        "    return _pages(client, 'list_arg')\n"
        "def _pages(client, name):\n"
        "    return name\n"
    )
    assert role_gap.custom_fn_calls("f", source) == {"list_attr", "list_arg"}
