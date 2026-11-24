"""A Lambda function's, alias's and published version's own resource-based policy (aws-core-tap#290).

Spec: specs/spec-aws-core-v0.md (req-aws-core-lambda-policy), specs/spec-aws-core-collector-v0.md
(req-aws-collector-outcome-7). The policy is read with ``lambda:GetPolicy`` (unqualified for the function,
``Qualifier`` for an alias or version), stored raw in the ``policy`` hydrate slot, summarised into the
``resource_policy_*`` fields and the ``PERMITS_ACCOUNT`` edge source. "No policy" (``ResourceNotFoundException``,
recorded absent by a reviewed outcome row) and "not read" (denied, errored, unreadable) stay distinct on every
summary field. Fake Lambda clients, no network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import botocore.session
import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector import iam_policy as iam
from tap_plugin.aws_core.collectors.boto3_collector.authority import COMPLETE, EDGE_READS, FAILED, PARTIAL, anchor_reads
from tap_plugin.aws_core.collectors.boto3_collector.batch import node_envelope
from tap_plugin.aws_core.collectors.boto3_collector.collector import HYDRATE_GAP_STATUSES
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    LAMBDA_ALIAS,
    LAMBDA_FUNCTION,
    LAMBDA_FUNCTION_VERSION,
    lambda_aliases_described,
    lambda_function_versions_described,
    lambda_functions_described,
)
from tap_plugin.aws_core.collectors.boto3_collector.edges import emit_edges
from tap_plugin.aws_core.collectors.boto3_collector.iam_trust import account_of_arn, summarize_resource_policy
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.outcomes import ABSENT, classify, classify_hydrate_read
from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
from tap_plugin.aws_core.collectors.boto3_collector.source import UndescribedError
from tap_plugin.aws_core.collectors.boto3_collector.transforms import build_transform_registry
from tap_plugin.aws_core.tests.test_trial_run_live import _create_verb_schema, _prepare_null_payload

# AWS documentation placeholder accounts only.
OWN = "111122223333"
OTHER = "444455556666"
THIRD = "777788889999"
REGION = "us-east-1"
FUNCTION_ARN = f"arn:aws:lambda:{REGION}:{OWN}:function:worker"
ALIAS_ARN = f"{FUNCTION_ARN}:live"
VERSION_ARN = f"{FUNCTION_ARN}:3"
LATEST_ARN = f"{FUNCTION_ARN}:$LATEST"
PERMITS = ("PERMITS_ACCOUNT__aws_core", "outbound")
NO_POLICY = {
    "resource_policy_account_ids": [],
    "resource_policy_services": [],
    "resource_policy_wildcard_principal": False,
    "resource_policy_unconditioned": False,
}
NOT_READ = dict.fromkeys(NO_POLICY)
_ENTRIES = manifest_entries()
_MODELED = {e["entity_type"] for e in _ENTRIES}
_TRANSFORMS = build_transform_registry()


def _entry(entity_type: str) -> dict[str, Any]:
    return next(e for e in _ENTRIES if e["entity_type"] == entity_type)


def _statement(principal: Any, *, condition: dict[str, Any] | None = None, effect: str = "Allow", **extra: Any) -> dict[str, Any]:
    statement: dict[str, Any] = {"Sid": "s", "Effect": effect, "Principal": principal, "Action": "lambda:InvokeFunction"}
    statement["Resource"] = FUNCTION_ARN
    if condition is not None:
        statement["Condition"] = condition
    statement.update(extra)
    return statement


def _policy(*statements: dict[str, Any]) -> str:
    """The policy as ``GetPolicy`` returns it: a JSON string."""
    return json.dumps({"Version": "2012-10-17", "Id": "default", "Statement": list(statements)})


def _error(code: str, op: str = "GetPolicy") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "The resource you requested does not exist."}}, op)


class _Lambda:
    """A fake Lambda client. ``get_policy`` is a callable of the call's kwargs, or a fixed answer or exception;
    ``list_aliases`` maps a function name to its aliases or to an exception. Every call is recorded."""

    def __init__(
        self,
        functions: list[dict[str, Any]],
        *,
        get_policy: Any = None,
        aliases: dict[str, Any] | None = None,
    ) -> None:
        self._functions = functions
        self._get_policy = get_policy
        self._aliases = aliases or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.meta = type("Meta", (), {"region_name": REGION, "partition": "aws"})()

    def can_paginate(self, _method: str) -> bool:
        return False

    def list_functions(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_functions", kwargs))
        return {"Functions": self._functions}

    def list_aliases(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_aliases", kwargs))
        answer = self._aliases.get(kwargs["FunctionName"], [])
        if isinstance(answer, Exception):
            raise answer
        return {"Aliases": answer}

    def get_policy(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_policy", kwargs))
        answer = self._get_policy(**kwargs) if callable(self._get_policy) else self._get_policy
        if isinstance(answer, Exception):
            raise answer
        return {"Policy": answer, "RevisionId": "rev-1", "ResponseMetadata": {"HTTPStatusCode": 200}}

    def policy_calls(self) -> list[dict[str, Any]]:
        return [kwargs for name, kwargs in self.calls if name == "get_policy"]


def _function(name: str = "worker", **extra: Any) -> dict[str, Any]:
    return {
        "FunctionName": name,
        "FunctionArn": f"arn:aws:lambda:{REGION}:{OWN}:function:{name}",
        "Role": f"arn:aws:iam::{OWN}:role/{name}",
        "Runtime": "python3.13",
        **extra,
    }


def _fields(item: dict[str, Any]) -> dict[str, Any]:
    return {key.removeprefix("_"): item[key] for key in item if key.startswith("_resource_policy_")}


def _functions(client: _Lambda) -> list[dict[str, Any]]:
    return list(lambda_functions_described(None, client_for=lambda _service: client))


CROSS_ACCOUNT = _policy(_statement({"AWS": f"arn:aws:iam::{OTHER}:root"}))


# ---------------------------------------------------------------------------
# The summary (pure)
# ---------------------------------------------------------------------------


class TestSummary:
    def test_other_accounts_by_root_arn_bare_id_and_role_arn_and_never_the_own_account(self) -> None:
        summary = summarize_resource_policy(
            _policy(
                _statement({"AWS": f"arn:aws:iam::{OTHER}:root"}, condition={"StringEquals": {"aws:x": "y"}}),
                _statement({"AWS": [THIRD, f"arn:aws:iam::{OWN}:role/self"]}, condition={"Bool": {"aws:y": "true"}}),
                _statement({"AWS": f"arn:aws:iam::{OTHER}:role/caller"}, condition={"Bool": {"aws:y": "true"}}),
            ),
            own_account=OWN,
        )
        assert summary == {"account_ids": [OTHER, THIRD], "services": [], "wildcard_principal": False, "unconditioned": False}

    def test_a_cross_account_grant_with_no_condition_is_unconditioned(self) -> None:
        summary = summarize_resource_policy(CROSS_ACCOUNT, own_account=OWN)
        assert summary is not None
        assert (summary["account_ids"], summary["unconditioned"]) == ([OTHER], True)

    def test_a_service_principal_without_a_source_condition_is_unconditioned(self) -> None:
        summary = summarize_resource_policy(_policy(_statement({"Service": "s3.amazonaws.com"})), own_account=OWN)
        assert summary == {"account_ids": [], "services": ["s3.amazonaws.com"], "wildcard_principal": False, "unconditioned": True}

    def test_a_service_principal_with_a_source_arn_is_conditioned(self) -> None:
        condition = {"ArnLike": {"AWS:SourceArn": f"arn:aws:s3:::bucket-{OWN}"}}
        summary = summarize_resource_policy(_policy(_statement({"Service": "s3.amazonaws.com"}, condition=condition)), own_account=OWN)
        assert summary is not None
        assert (summary["services"], summary["unconditioned"]) == (["s3.amazonaws.com"], False)

    @pytest.mark.parametrize("principal", ["*", {"AWS": "*"}, {"AWS": ["*"]}])
    def test_a_wildcard_without_a_condition_is_both_flags(self, principal: Any) -> None:
        summary = summarize_resource_policy(_policy(_statement(principal)), own_account=OWN)
        assert summary == {"account_ids": [], "services": [], "wildcard_principal": True, "unconditioned": True}

    def test_any_condition_makes_a_wildcard_conditioned_and_the_wildcard_flag_stays(self) -> None:
        # A function URL with AuthType NONE is written exactly so: "*" with a FunctionUrlAuthType condition. The flag
        # says the door is unnamed; unconditioned only says no outside grant lacks a condition.
        condition = {"StringEquals": {"lambda:FunctionUrlAuthType": "NONE"}}
        summary = summarize_resource_policy(_policy(_statement("*", condition=condition)), own_account=OWN)
        assert summary == {"account_ids": [], "services": [], "wildcard_principal": True, "unconditioned": False}

    def test_an_organization_condition_is_a_condition(self) -> None:
        condition = {"StringEquals": {"aws:PrincipalOrgID": "o-exampleorgid"}}
        summary = summarize_resource_policy(_policy(_statement("*", condition=condition)), own_account=OWN)
        assert summary is not None and summary["unconditioned"] is False

    def test_an_empty_condition_conditions_nothing(self) -> None:
        summary = summarize_resource_policy(_policy(_statement({"AWS": OTHER}, condition={})), own_account=OWN)
        assert summary is not None and summary["unconditioned"] is True

    def test_the_own_account_unconditioned_is_not_an_outside_grant(self) -> None:
        summary = summarize_resource_policy(_policy(_statement({"AWS": f"arn:aws:iam::{OWN}:root"})), own_account=OWN)
        assert summary == {"account_ids": [], "services": [], "wildcard_principal": False, "unconditioned": False}

    def test_a_deny_grants_nothing(self) -> None:
        summary = summarize_resource_policy(_policy(_statement("*", effect="Deny")), own_account=OWN)
        assert summary == {"account_ids": [], "services": [], "wildcard_principal": False, "unconditioned": False}

    @pytest.mark.parametrize("partition", ["aws-us-gov", "aws-cn"])
    def test_principal_arns_are_read_whatever_their_partition(self, partition: str) -> None:
        summary = summarize_resource_policy(_policy(_statement({"AWS": f"arn:{partition}:iam::{OTHER}:root"})), own_account=OWN)
        assert summary is not None and summary["account_ids"] == [OTHER]

    def test_the_policy_string_is_json_and_never_url_decoded(self) -> None:
        # A trust policy can arrive URL-encoded; a GetPolicy document never does, and a '%' in it is literal.
        condition = {"StringLike": {"AWS:SourceArn": "arn:aws:execute-api:*:*:abc%2F*"}}
        summary = summarize_resource_policy(_policy(_statement({"Service": "apigateway.amazonaws.com"}, condition=condition)), own_account=OWN)
        assert summary is not None and summary["unconditioned"] is False

    def test_a_single_statement_object_is_read(self) -> None:
        document = {"Version": "2012-10-17", "Statement": _statement({"AWS": OTHER})}
        summary = summarize_resource_policy(document, own_account=OWN)
        assert summary is not None and summary["account_ids"] == [OTHER]

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "{not json",
            json.dumps({"Version": "2012-10-17"}),
            _policy(_statement(None, NotPrincipal={"AWS": OTHER})),
            _policy(_statement({"Federated": "cognito-identity.amazonaws.com"})),
            _policy(_statement({"AWS": 12})),
            _policy(_statement(["*"])),
            _policy(_statement({"AWS": "AROAEXAMPLEDELETEDROLE"})),
            _policy(_statement({"AWS": [OTHER, "AIDAEXAMPLEDELETEDUSER"]}, condition={"Bool": {"aws:x": "true"}})),
        ],
        ids=[
            "none", "empty", "unparseable", "no-statement", "not-principal", "federated", "non-string", "list-principal",
            "opaque-id", "opaque-id-beside-an-account",
        ],
    )
    def test_a_document_that_cannot_be_read_with_certainty_is_none(self, raw: Any) -> None:
        assert summarize_resource_policy(raw, own_account=OWN) is None

    def test_the_output_is_sorted_and_the_same_every_time(self) -> None:
        raw = _policy(_statement({"AWS": [THIRD, OTHER], "Service": ["sns.amazonaws.com", "events.amazonaws.com"]}))
        assert summarize_resource_policy(raw, own_account=OWN) == summarize_resource_policy(raw, own_account=OWN) == {
            "account_ids": [OTHER, THIRD],
            "services": ["events.amazonaws.com", "sns.amazonaws.com"],
            "wildcard_principal": False,
            "unconditioned": True,
        }

    @pytest.mark.parametrize(
        ("arn", "account"),
        [
            (FUNCTION_ARN, OWN),
            (f"arn:aws-us-gov:lambda:us-gov-west-1:{OWN}:function:f:live", OWN),
            ("arn:aws:s3:::bucket", None),
            ("not-an-arn", None),
            (None, None),
        ],
    )
    def test_the_own_account_comes_from_any_arn(self, arn: Any, account: str | None) -> None:
        assert account_of_arn(arn) == account


# ---------------------------------------------------------------------------
# The outcome row: no policy is absent, never an error; denied stays denied
# ---------------------------------------------------------------------------


class TestOutcomeRow:
    def test_get_policy_not_found_is_absent(self) -> None:
        outcome = classify_hydrate_read(_entry(LAMBDA_FUNCTION), _error("ResourceNotFoundException"))
        assert outcome is not None and outcome.kind == ABSENT
        assert "deleted between the listing and this read" in outcome.why

    @pytest.mark.parametrize("entity_type", [LAMBDA_FUNCTION, LAMBDA_ALIAS, LAMBDA_FUNCTION_VERSION])
    def test_the_row_covers_all_three_types(self, entity_type: str) -> None:
        assert classify_hydrate_read(_entry(entity_type), _error("ResourceNotFoundException")) is not None

    def test_denied_and_other_errors_are_not_matched(self) -> None:
        entry = _entry(LAMBDA_FUNCTION)
        assert classify_hydrate_read(entry, _error("AccessDeniedException")) is None
        assert classify_hydrate_read(entry, _error("ServiceException")) is None

    def test_the_same_code_on_another_lambda_operation_is_not_matched(self) -> None:
        assert classify_hydrate_read(_entry(LAMBDA_FUNCTION), _error("ResourceNotFoundException", "GetFunctionUrlConfig")) is None

    def test_an_absent_row_never_names_a_listing_result(self) -> None:
        # A listing that raised the same code is a failed call, not an empty listing.
        assert classify(_entry(LAMBDA_FUNCTION), _error("ResourceNotFoundException"), "aws") is None


# ---------------------------------------------------------------------------
# The function reader
# ---------------------------------------------------------------------------


class TestFunctionReader:
    def test_the_function_policy_is_read_unqualified_stored_raw_and_summarised(self) -> None:
        client = _Lambda([_function()], get_policy=CROSS_ACCOUNT)
        [item] = _functions(client)
        assert client.policy_calls() == [{"FunctionName": "worker"}]
        slot = item["_hydrate"]["policy"]
        assert (slot["status"], slot["op"]) == ("ok", "GetPolicy")
        assert slot["data"] == {"Policy": CROSS_ACCOUNT, "RevisionId": "rev-1"}
        assert item["_hydrate_mapping"]["policy"]["op"] == "GetPolicy"
        assert _fields(item) == {
            "resource_policy_account_ids": [OTHER],
            "resource_policy_services": [],
            "resource_policy_wildcard_principal": False,
            "resource_policy_unconditioned": True,
        }
        assert item[EDGE_READS]["_resource_policy_account_ids"] == COMPLETE

    def test_no_policy_is_recorded_absent_and_reads_as_no_grant(self) -> None:
        [item] = _functions(_Lambda([_function()], get_policy=_error("ResourceNotFoundException")))
        assert item["_hydrate"]["policy"] == {"status": "absent", "op": "GetPolicy", "error_code": "ResourceNotFoundException"}
        assert item["_hydrate"]["policy"]["status"] not in HYDRATE_GAP_STATUSES
        assert _fields(item) == NO_POLICY
        assert item[EDGE_READS]["_resource_policy_account_ids"] == COMPLETE

    def test_a_denied_read_stays_denied_and_every_field_is_unread(self) -> None:
        [item] = _functions(_Lambda([_function()], get_policy=_error("AccessDeniedException")))
        assert item["_hydrate"]["policy"]["status"] == "denied"
        assert _fields(item) == NOT_READ
        assert item[EDGE_READS]["_resource_policy_account_ids"] == FAILED

    def test_an_unexpected_error_is_an_error_and_every_field_is_unread(self) -> None:
        [item] = _functions(_Lambda([_function()], get_policy=_error("ServiceException")))
        assert item["_hydrate"]["policy"]["status"] == "error"
        assert _fields(item) == NOT_READ
        assert item[EDGE_READS]["_resource_policy_account_ids"] == FAILED

    def test_a_policy_that_cannot_be_read_with_certainty_is_unread_and_partial(self) -> None:
        raw = _policy(_statement(None, NotPrincipal={"AWS": OTHER}))
        [item] = _functions(_Lambda([_function()], get_policy=raw))
        assert item["_hydrate"]["policy"]["status"] == "ok"
        assert _fields(item) == NOT_READ
        assert item[EDGE_READS]["_resource_policy_account_ids"] == PARTIAL

    def test_a_principal_that_names_no_account_never_reads_as_a_complete_grant_set(self) -> None:
        # An opaque unique id (a deleted principal) names someone in an unknown account: the account list cannot be
        # called complete, so PERMITS_ACCOUNT edges are never retired on it (PR #299 review, Codex seat).
        raw = _policy(_statement({"AWS": "AROAEXAMPLEDELETEDROLE"}))
        [item] = _functions(_Lambda([_function()], get_policy=raw))
        assert _fields(item) == NOT_READ
        assert item[EDGE_READS]["_resource_policy_account_ids"] == PARTIAL

    def test_the_listed_item_is_kept_and_its_own_edge_sources_read_as_an_aws_op_item_would(self) -> None:
        [item] = _functions(_Lambda([_function(LoggingConfig={"LogGroup": "/aws/lambda/worker"})], get_policy=CROSS_ACCOUNT))
        assert item["Runtime"] == "python3.13"
        assert item[EDGE_READS] == {"Role": COMPLETE, "LoggingConfig": COMPLETE, "_resource_policy_account_ids": COMPLETE}
        node = project_item(_entry(LAMBDA_FUNCTION), item, {"region": REGION})
        reads = anchor_reads(node, _entry(LAMBDA_FUNCTION), modeled_types=_MODELED, transforms=_TRANSFORMS)
        assert reads[("ASSUMES_ROLE__aws_core", "outbound")] == COMPLETE
        assert reads[PERMITS] == COMPLETE

    def test_an_unread_policy_never_claims_the_edge_scope_complete(self) -> None:
        [item] = _functions(_Lambda([_function()], get_policy=_error("AccessDeniedException")))
        node = project_item(_entry(LAMBDA_FUNCTION), item, {"region": REGION})
        reads = anchor_reads(node, _entry(LAMBDA_FUNCTION), modeled_types=_MODELED, transforms=_TRANSFORMS)
        assert reads[PERMITS] == FAILED

    def test_the_manifest_projects_the_summary_onto_the_function(self) -> None:
        [item] = _functions(_Lambda([_function()], get_policy=CROSS_ACCOUNT))
        node = project_item(_entry(LAMBDA_FUNCTION), item, {"region": REGION})
        assert node.natural_key == FUNCTION_ARN
        assert node.fields["resource_policy_account_ids"] == [OTHER]
        assert node.fields["resource_policy_unconditioned"] is True

    def test_the_stored_configuration_keeps_the_raw_policy(self) -> None:
        entry = _entry(LAMBDA_FUNCTION)
        [item] = _functions(_Lambda([_function()], get_policy=CROSS_ACCOUNT))
        node = project_item(entry, item, {"region": REGION})
        envelope = node_envelope(node, {}, {}, persist_configuration=entry["persist_configuration"])
        assert envelope["node"]["configuration"]["_hydrate"]["policy"]["data"]["Policy"] == CROSS_ACCOUNT


# ---------------------------------------------------------------------------
# Aliases and published versions carry their own policy
# ---------------------------------------------------------------------------


def _alias(name: str = "live") -> dict[str, Any]:
    return {"AliasArn": f"{FUNCTION_ARN}:{name}", "Name": name, "FunctionVersion": "3", "RevisionId": "a"}


class TestAliasReader:
    def test_each_alias_policy_is_read_with_its_name_as_qualifier(self) -> None:
        def answer(**kwargs: Any) -> Any:
            return CROSS_ACCOUNT if kwargs.get("Qualifier") == "live" else _error("ResourceNotFoundException")

        client = _Lambda([_function()], get_policy=answer, aliases={"worker": [_alias("live"), _alias("canary")]})
        items = list(lambda_aliases_described(None, client_for=lambda _service: client))
        assert client.policy_calls() == [
            {"FunctionName": "worker", "Qualifier": "live"},
            {"FunctionName": "worker", "Qualifier": "canary"},
        ]
        live, canary = items
        assert _fields(live)["resource_policy_account_ids"] == [OTHER]
        assert _fields(canary) == NO_POLICY
        assert "_parent" not in live

    def test_an_alias_grant_is_invisible_on_the_function_and_visible_on_the_alias(self) -> None:
        def answer(**kwargs: Any) -> Any:
            return CROSS_ACCOUNT if kwargs.get("Qualifier") else _error("ResourceNotFoundException")

        client = _Lambda([_function()], get_policy=answer, aliases={"worker": [_alias()]})
        [function] = _functions(client)
        [alias] = list(lambda_aliases_described(None, client_for=lambda _service: client))
        assert _fields(function) == NO_POLICY
        assert _fields(alias)["resource_policy_account_ids"] == [OTHER]

    def test_a_function_whose_aliases_cannot_be_listed_is_a_gap_and_the_rest_are_kept(self) -> None:
        client = _Lambda(
            [_function("broken"), _function("worker")],
            get_policy=CROSS_ACCOUNT,
            aliases={"broken": _error("AccessDeniedException", "ListAliases"), "worker": [_alias()]},
        )
        items: list[dict[str, Any]] = []
        with pytest.raises(UndescribedError, match="broken"):
            for item in lambda_aliases_described(None, client_for=lambda _service: client):
                items.append(item)  # noqa: PERF402 - the items yielded before the raise are the point
        assert [i["AliasArn"] for i in items] == [ALIAS_ARN]

    def test_the_alias_edge_and_fields_project(self) -> None:
        client = _Lambda([_function()], get_policy=CROSS_ACCOUNT, aliases={"worker": [_alias()]})
        [item] = list(lambda_aliases_described(None, client_for=lambda _service: client))
        entry = _entry(LAMBDA_ALIAS)
        node = project_item(entry, item, {"region": REGION})
        assert node.natural_key == ALIAS_ARN
        assert node.fields["name"] == "live"
        emission = emit_edges(node, entry, modeled_types=_MODELED, transforms=_TRANSFORMS, dimensions={})
        assert _edges(emission) == [("PERMITS_ACCOUNT__aws_core", _account_ref(OTHER))]
        assert item[EDGE_READS] == {"_resource_policy_account_ids": COMPLETE}


class TestVersionReader:
    def _versions(self, client: _Lambda) -> list[dict[str, Any]]:
        return list(lambda_function_versions_described(None, client_for=lambda _service: client))

    def test_each_published_version_policy_is_read_with_its_version_as_qualifier(self) -> None:
        published = _function(FunctionArn=VERSION_ARN, Version="3")
        client = _Lambda([published], get_policy=CROSS_ACCOUNT)
        [item] = self._versions(client)
        assert ("list_functions", {"FunctionVersion": "ALL"}) in client.calls
        assert client.policy_calls() == [{"FunctionName": "worker", "Qualifier": "3"}]
        assert _fields(item)["resource_policy_account_ids"] == [OTHER]
        node = project_item(_entry(LAMBDA_FUNCTION_VERSION), item, {"region": REGION})
        assert node.natural_key == VERSION_ARN

    def test_latest_is_listed_but_no_policy_is_read_for_it(self) -> None:
        latest = _function(FunctionArn=LATEST_ARN, Version="$LATEST")
        client = _Lambda([latest], get_policy=CROSS_ACCOUNT)
        [item] = self._versions(client)
        assert client.policy_calls() == []
        assert "_hydrate" not in item
        assert _fields(item) == NOT_READ
        assert item[EDGE_READS]["_resource_policy_account_ids"] == PARTIAL

    def test_a_denied_version_read_stays_denied(self) -> None:
        published = _function(FunctionArn=VERSION_ARN, Version="3")
        [item] = self._versions(_Lambda([published], get_policy=_error("AccessDeniedException")))
        assert item["_hydrate"]["policy"]["status"] == "denied"
        assert _fields(item) == NOT_READ


def _edges(emission: Any) -> list[tuple[str, str]]:
    """``(edge_type, to_ref)`` of each edge an emission carries."""
    return [(envelope["edge"]["edge_type"], envelope["edge"]["to_ref"]) for envelope in emission.envelopes]


def _account_ref(account_id: str) -> str:
    return f"aws_core__aws_account:{account_id}"


class TestPermitsAccountEdge:
    def test_the_function_points_at_each_other_account_its_policy_names(self) -> None:
        raw = _policy(_statement({"AWS": [OTHER, f"arn:aws:iam::{THIRD}:root", OWN]}), _statement({"Service": "sns.amazonaws.com"}))
        [item] = _functions(_Lambda([_function()], get_policy=raw))
        entry = _entry(LAMBDA_FUNCTION)
        node = project_item(entry, item, {"region": REGION})
        emission = emit_edges(node, entry, modeled_types=_MODELED, transforms=_TRANSFORMS, dimensions={})
        permits = [to for edge_type, to in _edges(emission) if edge_type == "PERMITS_ACCOUNT__aws_core"]
        assert permits == [_account_ref(OTHER), _account_ref(THIRD)]

    def test_no_policy_and_an_unread_policy_both_emit_no_edge_but_claim_differently(self) -> None:
        entry = _entry(LAMBDA_FUNCTION)
        for answer, read in ((_error("ResourceNotFoundException"), COMPLETE), (_error("AccessDeniedException"), FAILED)):
            [item] = _functions(_Lambda([_function()], get_policy=answer))
            node = project_item(entry, item, {"region": REGION})
            emission = emit_edges(node, entry, modeled_types=_MODELED, transforms=_TRANSFORMS, dimensions={})
            assert not [to for edge_type, to in _edges(emission) if edge_type == "PERMITS_ACCOUNT__aws_core"]
            assert anchor_reads(node, entry, modeled_types=_MODELED, transforms=_TRANSFORMS)[PERMITS] == read

    def test_the_edge_type_allows_each_rule_pair(self) -> None:
        edge = json.loads((Path(__file__).resolve().parent.parent / "edges" / "PERMITS_ACCOUNT.edge.json").read_text())
        for entity_type in (LAMBDA_FUNCTION, LAMBDA_ALIAS, LAMBDA_FUNCTION_VERSION):
            rules = [r for r in _entry(entity_type)["edges"] if r["edge_type"] == "PERMITS_ACCOUNT__aws_core"]
            assert len(rules) == 1, entity_type
            assert entity_type in edge["sources"] and rules[0]["target_type"] in edge["targets"]
            # The same account-node resolution as TRUSTS_ACCOUNT's: the account id, by identity.
            assert (rules[0]["key_kind"], rules[0]["target_type"]) == ("id", "aws_core__aws_account")


# ---------------------------------------------------------------------------
# Declarations: manifest, sensitivity, IAM grant, model schemas
# ---------------------------------------------------------------------------


class TestDeclarations:
    TYPES = (LAMBDA_FUNCTION, LAMBDA_ALIAS, LAMBDA_FUNCTION_VERSION)

    @pytest.mark.parametrize("entity_type", TYPES)
    def test_each_entry_hydrates_get_policy_and_declares_the_document_an_access_policy(self, entity_type: str) -> None:
        entry = _entry(entity_type)
        assert [h["op"] for h in entry["hydrate"]] == ["GetPolicy"]
        assert entry["persist_configuration"] is True
        locations = {loc["path"]: loc for loc in entry["sensitivity"]["locations"]}
        assert locations["_hydrate.policy.data.Policy"]["category"] == "access_policy"
        assert not locations["_hydrate.policy.data.Policy"].get("redact")

    @pytest.mark.parametrize(("entity_type", "op", "items"), [
        (LAMBDA_FUNCTION, "ListFunctions", "Functions"),
        (LAMBDA_FUNCTION_VERSION, "ListFunctions", "Functions"),
        (LAMBDA_ALIAS, "ListAliases", "Aliases"),
    ])
    def test_the_listed_item_shape_is_still_covered(self, entity_type: str, op: str, items: str) -> None:
        # The entries moved from aws_op to custom_fn, which the shape ratchet in test_boto3_collector_sensitivity does
        # not walk: every botocore-sensitive member of the listed item is still declared here.
        from tap_plugin.aws_core.tests.test_boto3_collector_sensitivity import _covered, _sensitive_member_paths

        model = botocore.session.get_session().get_service_model("lambda")
        shape = model.operation_model(op).output_shape.members[items].member
        declared = {loc["path"] for loc in _entry(entity_type)["sensitivity"]["locations"]}
        assert [p for p in _sensitive_member_paths(shape) if not _covered(p, declared)] == []
        get_policy = model.operation_model("GetPolicy").output_shape
        assert _sensitive_member_paths(get_policy) == []

    def test_get_policy_is_in_the_generated_read_policy(self) -> None:
        assert ("lambda", "GetPolicy") in iam.inventory()
        assert iam.iam_actions("lambda", "GetPolicy", iam.overrides(), iam.catalog()) == ["lambda:GetPolicy"]
        allowed = {a for t in iam.render().values() for s in json.loads(t)["Statement"] if s["Effect"] == "Allow" for a in s["Action"]}
        assert "lambda:GetPolicy" in allowed

    @pytest.mark.parametrize(
        ("entity_type", "answer"),
        [
            (LAMBDA_FUNCTION, CROSS_ACCOUNT),
            (LAMBDA_FUNCTION, _error("ResourceNotFoundException")),
            (LAMBDA_FUNCTION, _error("AccessDeniedException")),
            (LAMBDA_ALIAS, CROSS_ACCOUNT),
            (LAMBDA_FUNCTION_VERSION, CROSS_ACCOUNT),
            (LAMBDA_FUNCTION_VERSION, None),
        ],
        ids=["function-ok", "function-absent", "function-denied", "alias-ok", "version-ok", "version-latest"],
    )
    def test_the_payload_imports_under_the_model_create_schema(self, entity_type: str, answer: Any) -> None:
        import jsonschema
        from django.apps import apps

        model = next(m for m in apps.get_app_config("aws_core").get_models() if getattr(m, "ENTITY_TYPE", "") == entity_type)
        if entity_type == LAMBDA_ALIAS:
            client = _Lambda([_function()], get_policy=answer, aliases={"worker": [_alias()]})
            items = list(lambda_aliases_described(None, client_for=lambda _service: client))
        elif entity_type == LAMBDA_FUNCTION_VERSION:
            version = "$LATEST" if answer is None else "3"
            client = _Lambda([_function(FunctionArn=f"{FUNCTION_ARN}:{version}", Version=version)], get_policy=answer)
            items = list(lambda_function_versions_described(None, client_for=lambda _service: client))
        else:
            items = _functions(_Lambda([_function()], get_policy=answer))
        entry = _entry(entity_type)
        schema = _create_verb_schema(model)
        for item in items:
            payload = node_envelope(project_item(entry, item, {"region": REGION}), {}, {}, persist_configuration=True)["node"]
            jsonschema.validate(_prepare_null_payload(payload, schema), schema)
