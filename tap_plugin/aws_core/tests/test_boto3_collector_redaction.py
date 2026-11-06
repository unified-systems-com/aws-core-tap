"""What is removed from a stored configuration (req-aws-collector-redaction): secret material, nothing else."""

from __future__ import annotations

import copy

import pytest
from tap_plugin.aws_core.collectors.boto3_collector.envelope import redact_configuration


class TestDeclaredPaths:
    @pytest.mark.spec("req-aws-collector-redaction")
    def test_a_declared_path_is_removed_and_listed(self):
        config = {"FunctionName": "f", "Environment": {"Variables": {"DB_PASSWORD": "hunter2"}}, "Runtime": "python3.13"}
        out = redact_configuration(config, ["Environment.Variables"])
        assert out["Environment"] == {} and out["FunctionName"] == "f" and out["Runtime"] == "python3.13"
        assert out["_redacted"] == ["Environment.Variables"]

    @pytest.mark.spec("req-aws-collector-redaction")
    def test_a_path_through_a_list_removes_it_from_every_element(self):
        config = {"Origins": {"Items": [{"Id": "a", "CustomHeaders": {"Items": [{"HeaderName": "h", "HeaderValue": "s1"}]}}, {"Id": "b"}]}}
        out = redact_configuration(config, ["Origins.Items[].CustomHeaders.Items[].HeaderValue"])
        assert out["Origins"]["Items"][0]["CustomHeaders"]["Items"] == [{"HeaderName": "h"}]
        assert out["Origins"]["Items"][1] == {"Id": "b"}

    @pytest.mark.spec("req-aws-collector-redaction")
    def test_a_path_that_is_not_there_changes_nothing_and_lists_nothing(self):
        config = {"a": 1}
        assert redact_configuration(config, ["Environment.Variables"]) == {"a": 1}

    @pytest.mark.spec("req-aws-collector-redaction")
    def test_the_input_is_not_changed_and_the_output_is_deterministic(self):
        config = {"Environment": {"Variables": {"K": "v"}}, "x": {"password": "p"}}
        before = copy.deepcopy(config)
        first = redact_configuration(config, ["Environment.Variables"])
        assert config == before
        assert first == redact_configuration(config, ["Environment.Variables"])
        assert first["_redacted"] == sorted(first["_redacted"])


class TestKeyNameScrub:
    @pytest.mark.spec("req-aws-collector-redaction")
    @pytest.mark.parametrize("key", ["Password", "MasterUserPassword", "client_secret", "SecretAccessKey", "ApiKey", "PrivateKey", "HECToken", "AuthToken", "PreSharedKey"])
    def test_a_string_under_a_key_that_names_a_secret_is_removed_wherever_it_is(self, key):
        out = redact_configuration({"Outer": [{"Inner": {key: "s3cr3t", "Keep": "x"}}]}, [])
        assert out["Outer"][0]["Inner"] == {"Keep": "x"}
        assert out["_redacted"] == [f"Outer[].Inner.{key}"]

    @pytest.mark.spec("req-aws-collector-redaction")
    @pytest.mark.parametrize(
        "key",
        ["SecretArn", "SecretId", "SecretName", "PasswordLastUsed", "PasswordPolicy", "MinimumPasswordLength", "TokenUrl", "AccessKeyId", "KmsKeyId", "ApiKeyRequired", "RotationEnabled", "PasswordResetRequired", "IdentityTokenSource"],
    )
    def test_a_reference_a_flag_a_date_or_a_url_is_kept(self, key):
        out = redact_configuration({key: "kept"}, [])
        assert out == {key: "kept"}

    @pytest.mark.spec("req-aws-collector-redaction")
    def test_only_strings_are_scrubbed(self):
        out = redact_configuration({"PasswordReusePrevention": 24, "HasPassword": True, "Password": None, "Passwords": ["a"]}, [])
        assert "PasswordReusePrevention" in out and "HasPassword" in out and "Password" in out


class TestNameValuePairs:
    @pytest.mark.spec("req-aws-collector-redaction")
    def test_the_value_of_a_pair_named_like_a_secret_is_removed(self):
        config = {"environment": [{"name": "DB_PASSWORD", "value": "hunter2"}, {"name": "STAGE", "value": "prod"}]}
        out = redact_configuration(config, [])
        assert out["environment"] == [{"name": "DB_PASSWORD"}, {"name": "STAGE", "value": "prod"}]
        assert out["_redacted"] == ["environment[].value"]

    @pytest.mark.spec("req-aws-collector-redaction")
    def test_a_tag_is_kept_whatever_it_is_called(self):
        config = {"Tags": [{"Key": "password-owner", "Value": "net-team"}]}
        assert redact_configuration(config, []) == config


class TestWhatIsKept:
    @pytest.mark.spec("req-aws-collector-redaction")
    def test_operator_authored_content_is_kept(self):
        config = {
            "Tags": [{"Key": "owner", "Value": "net-team"}],
            "Description": "uses the db at db.internal; password is in the vault",
            "Policy": '{"Statement": []}',
            "UserName": "alice",
            "Comment": "see ticket 4411",
        }
        assert redact_configuration(config, []) == config
