"""The read guard and the committed run records. No AWS and no Django: standard library plus pytest."""

import json
import re
from pathlib import Path

import pytest

import readguard

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "tap_plugin/aws_core/collectors/boto3_collector/aws_resource_manifest.json"
RUNS = Path(__file__).resolve().parents[1] / "runs"


@pytest.mark.parametrize("op", ["DescribeInstances", "ListRoles", "GetBucketPolicy", "BatchGetProjects", "SearchResources", "LookupEvents", "HeadBucket", "QueryTable"])
def test_read_verbs_pass(op):
    readguard.check(op, {})


@pytest.mark.parametrize("op", ["CreateBucket", "DeleteQueue", "PutObject", "RunInstances", "UpdateFunctionCode", "AssumeRole", "Invoke", "StartExecution"])
def test_a_non_read_verb_is_refused(op):
    with pytest.raises(readguard.NonReadCall):
        readguard.check(op, {})


@pytest.mark.parametrize("op", sorted(readguard.SECRET_RETURNING))
def test_a_read_verb_that_returns_credentials_is_refused(op):
    assert readguard.READ_VERB.match(op), "the list is for operations the verb check would let through"
    with pytest.raises(readguard.NonReadCall):
        readguard.check(op, {})


@pytest.mark.parametrize(("op", "param"), [("GetParameter", "WithDecryption"), ("GetParametersByPath", "WithDecryption"), ("GetApiKey", "includeValue"), ("GetApiKeys", "includeValues")])
def test_a_request_that_reveals_a_secret_is_refused_but_the_plain_call_is_not(op, param):
    readguard.check(op, {})
    readguard.check(op, {param: False})
    with pytest.raises(readguard.NonReadCall):
        readguard.check(op, {param: True})


def _manifest_ops():
    ops = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("aws_op", "op") and isinstance(value, str):
                    ops.add(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(MANIFEST.read_text()))
    return ops


def test_no_operation_the_manifest_names_is_on_the_refused_list():
    assert _manifest_ops() & readguard.SECRET_RETURNING == set()


def test_every_manifest_operation_is_a_read_verb():
    assert [o for o in _manifest_ops() if not readguard.READ_VERB.match(o)] == []


@pytest.mark.parametrize("record", sorted(RUNS.glob("*.json")), ids=lambda p: p.name)
def test_committed_run_records_hold_no_account_number_and_no_messages(record):
    text = record.read_text()
    assert not re.search(r"\b\d{12}\b", text), "a 12-digit number (an account id) is in the record"
    assert "error_message" not in text, "error messages can name resources and are not recorded"


def test_by_product_secret_operations_are_ones_the_collector_makes_and_are_not_refused():
    # The guard's stated limit: these are allowed because the collector makes them (in the manifest or a custom
    # function) and the manifest strips the secret field.
    assert readguard.BY_PRODUCT_SECRETS & readguard.SECRET_RETURNING == set()
    source = MANIFEST.read_text() + (MANIFEST.parent / "customfns.py").read_text()
    snake = lambda op: re.sub(r"(?<!^)(?=[A-Z])", "_", op).lower()  # noqa: E731
    for op in readguard.BY_PRODUCT_SECRETS:
        assert op in source or snake(op) in source, op
    assert '"path": "ClientSecret"' in MANIFEST.read_text()
