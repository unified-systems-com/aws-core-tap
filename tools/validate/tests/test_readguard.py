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


def test_glue_connection_reads_must_hide_the_password():
    for op in ("GetConnection", "GetConnections"):
        with pytest.raises(readguard.NonReadCall):
            readguard.check(op, {})
        with pytest.raises(readguard.NonReadCall):
            readguard.check(op, {"HidePassword": False})
        readguard.check(op, {"HidePassword": True})


@pytest.mark.parametrize("op", ["GetClusterCredentials", "GetRelationalDatabaseMasterUserPassword", "GetInstanceAccessDetails", "GetComputeAccess"])
def test_more_credential_returning_reads_are_refused(op):
    with pytest.raises(readguard.NonReadCall):
        readguard.check(op)


def test_the_manifests_glue_connection_entries_pass_hide_password():
    text = MANIFEST.read_text()
    assert text.count('"HidePassword": true') >= 1


def _session():
    boto3 = pytest.importorskip("boto3")
    return boto3.session.Session(aws_access_key_id="AKIAFAKE", aws_secret_access_key="fake", region_name="us-gov-west-1")


def test_the_botocore_hook_refuses_a_write_before_anything_is_sent():
    session = _session()
    readguard.install(session)
    client = session.client("s3")
    with pytest.raises(readguard.NonReadCall, match="s3.DeleteBucket"):
        client.delete_bucket(Bucket="b")


def test_the_botocore_hook_refuses_a_credential_returning_read_and_a_revealing_request():
    session = _session()
    readguard.install(session)
    with pytest.raises(readguard.NonReadCall, match="GetSessionToken"):
        session.client("sts").get_session_token()
    with pytest.raises(readguard.NonReadCall, match="WithDecryption"):
        session.client("ssm").get_parameter(Name="n", WithDecryption=True)


def test_the_botocore_hook_lets_a_plain_read_through():
    stubber = pytest.importorskip("botocore.stub")
    session = _session()
    readguard.install(session)
    client = session.client("s3")
    with stubber.Stubber(client) as stub:
        stub.add_response("list_buckets", {"Buckets": []})
        assert client.list_buckets()["Buckets"] == []


def test_a_client_built_before_the_guard_is_installed_is_not_covered():
    # The documented limit: install() before building clients. Stub the write so nothing is sent.
    stubber = pytest.importorskip("botocore.stub")
    session = _session()
    early = session.client("s3")
    readguard.install(session)
    with stubber.Stubber(early) as stub:
        stub.add_response("delete_bucket", {})
        early.delete_bucket(Bucket="b")  # not refused: the client copied the handlers before install


def test_the_wheel_ships_only_the_plugin_package():
    text = (Path(__file__).resolve().parents[3] / "pyproject.toml").read_text()
    assert 'only-include = ["tap_plugin/aws_core"]' in text


def test_no_committed_record_calls_an_entry_that_made_no_call_empty():
    records = sorted((Path(__file__).resolve().parents[1] / "runs").glob("*.json"))
    assert records
    for path in records:
        # Only the wave 0 smoke records list per-entry outcomes; the seeded-run records list compared types.
        for result in json.loads(path.read_text()).get("results", []):
            assert not (result.get("outcome") == "empty" and result.get("calls") == 0), (path.name, result["entity_type"])
