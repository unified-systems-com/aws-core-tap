"""Unit tests for :mod:`tap_plugin.aws_core.collectors.boto3_collector.iam_trust` (aws-core-tap#43).

Pure functions, no DB, no boto3 client: the input is exactly what ``ListRoles`` /
``AssumeRolePolicyDocument`` hands the collector.
"""

from __future__ import annotations

from tap_plugin.aws_core.collectors.boto3_collector.iam_trust import (
    account_of_iam_arn,
    iam_endpoint_region,
    summarize_trust_policy,
)


class TestAccountOfIamArn:
    def test_commercial_role_arn(self):
        assert account_of_iam_arn("arn:aws:iam::123456789012:role/foo") == "123456789012"

    def test_govcloud_partition(self):
        assert account_of_iam_arn("arn:aws-us-gov:iam::123456789012:role/foo") == "123456789012"

    def test_china_partition(self):
        assert account_of_iam_arn("arn:aws-cn:iam::123456789012:role/foo") == "123456789012"

    def test_aws_managed_is_not_an_account(self):
        assert account_of_iam_arn("arn:aws:iam::aws:policy/ReadOnlyAccess") is None

    def test_non_iam_arn(self):
        assert account_of_iam_arn("arn:aws:s3:::bucket") is None

    def test_not_a_string(self):
        assert account_of_iam_arn(None) is None
        assert account_of_iam_arn(123) is None

    def test_malformed_string(self):
        assert account_of_iam_arn("not-an-arn") is None


class TestIamEndpointRegion:
    def test_commercial(self):
        assert iam_endpoint_region("arn:aws:iam::123456789012:role/foo") == "us-east-1"

    def test_govcloud(self):
        assert iam_endpoint_region("arn:aws-us-gov:iam::123456789012:role/foo") == "us-gov-west-1"

    def test_china(self):
        assert iam_endpoint_region("arn:aws-cn:iam::123456789012:role/foo") == "cn-north-1"

    def test_unrecognized_partition_falls_back_to_commercial(self):
        assert iam_endpoint_region("arn:aws-iso:iam::123456789012:role/foo") == "us-east-1"

    def test_malformed_or_missing_falls_back_to_commercial(self):
        assert iam_endpoint_region(None) == "us-east-1"
        assert iam_endpoint_region("not-an-arn") == "us-east-1"


class TestSummarizeTrustPolicy:
    def test_cross_account_root_and_service(self):
        doc = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": "arn:aws:iam::999988887777:root"},
                    "Action": "sts:AssumeRole",
                },
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                },
            ],
        }
        result = summarize_trust_policy(doc, own_account="123456789012")
        assert result == {
            "trusted_account_ids": ["999988887777"],
            "trusted_services": ["lambda.amazonaws.com"],
            "trusts_wildcard_principal": False,
        }

    def test_own_account_excluded(self):
        doc = {
            "Statement": [
                {"Effect": "Allow", "Principal": {"AWS": "123456789012"}, "Action": "sts:AssumeRole"},
            ]
        }
        result = summarize_trust_policy(doc, own_account="123456789012")
        assert result["trusted_account_ids"] == []

    def test_wildcard_principal_string(self):
        doc = {"Statement": [{"Effect": "Allow", "Principal": "*", "Action": "sts:AssumeRole"}]}
        result = summarize_trust_policy(doc, own_account=None)
        assert result["trusts_wildcard_principal"] is True
        assert result["trusted_account_ids"] == []

    def test_wildcard_principal_in_aws_list(self):
        doc = {"Statement": [{"Effect": "Allow", "Principal": {"AWS": "*"}, "Action": "sts:AssumeRole"}]}
        result = summarize_trust_policy(doc, own_account=None)
        assert result["trusts_wildcard_principal"] is True

    def test_deny_statement_grants_nothing(self):
        doc = {
            "Statement": [
                {"Effect": "Deny", "Principal": "*", "Action": "sts:AssumeRole"},
            ]
        }
        result = summarize_trust_policy(doc, own_account=None)
        assert result == {"trusted_account_ids": [], "trusted_services": [], "trusts_wildcard_principal": False}

    def test_list_of_principals(self):
        doc = {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["arn:aws:iam::111111111111:root", "arn:aws:iam::222222222222:root"]},
                    "Action": "sts:AssumeRole",
                }
            ]
        }
        result = summarize_trust_policy(doc, own_account=None)
        assert result["trusted_account_ids"] == ["111111111111", "222222222222"]

    def test_opaque_principal_id_is_not_an_account(self):
        # A deleted principal is rendered back as a unique id (AROA...), which names no account.
        doc = {
            "Statement": [
                {"Effect": "Allow", "Principal": {"AWS": "AROAEXAMPLE123456"}, "Action": "sts:AssumeRole"},
            ]
        }
        result = summarize_trust_policy(doc, own_account=None)
        assert result["trusted_account_ids"] == []

    def test_missing_document_is_none(self):
        assert summarize_trust_policy(None, own_account="123456789012") is None
        assert summarize_trust_policy("", own_account="123456789012") is None

    def test_url_encoded_string_document(self):
        import json
        from urllib.parse import quote

        doc = {
            "Statement": [
                {"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::999988887777:root"}, "Action": "sts:AssumeRole"}
            ]
        }
        encoded = quote(json.dumps(doc))
        result = summarize_trust_policy(encoded, own_account=None)
        assert result["trusted_account_ids"] == ["999988887777"]

    def test_unparseable_string_is_none(self):
        assert summarize_trust_policy("{not json", own_account=None) is None

    def test_not_principal_grants_nothing(self):
        # NotPrincipal is a different clause; this module does not evaluate it as a grant.
        doc = {
            "Statement": [
                {
                    "Effect": "Allow",
                    "NotPrincipal": {"AWS": "arn:aws:iam::999988887777:root"},
                    "Action": "sts:AssumeRole",
                }
            ]
        }
        result = summarize_trust_policy(doc, own_account=None)
        assert result == {"trusted_account_ids": [], "trusted_services": [], "trusts_wildcard_principal": False}

    def test_deterministic_and_sorted(self):
        doc = {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["arn:aws:iam::222222222222:root", "arn:aws:iam::111111111111:root"]},
                    "Action": "sts:AssumeRole",
                }
            ]
        }
        r1 = summarize_trust_policy(doc, own_account=None)
        r2 = summarize_trust_policy(doc, own_account=None)
        assert r1 == r2 == {
            "trusted_account_ids": ["111111111111", "222222222222"],
            "trusted_services": [],
            "trusts_wildcard_principal": False,
        }
