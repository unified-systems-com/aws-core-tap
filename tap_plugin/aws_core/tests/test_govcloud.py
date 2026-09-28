"""GovCloud (aws-us-gov) readiness (req-aws-collector-partition).

Everything here runs offline, against GovCloud-shaped fixtures (``arn:aws-us-gov:iam::...``,
``us-gov-west-1``). Two kinds of evidence, kept apart on purpose:

- **Real botocore, no network.** Endpoint resolution (``client.meta.endpoint_url`` /
  ``client.meta.partition``) and the exact bytes AssumeRole would put on the wire (captured at
  botocore's ``before-send`` hook and answered with a canned response). These check our code
  against botocore's own bundled endpoint data — not against AWS.
- **Fakes.** Custom fns and the collector's ``run()`` against canned clients.

What none of it proves: that a live GovCloud account accepts the calls. See README
"Deploying to GovCloud" for what is verified and what is assumed.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import boto3
import jsonschema
import pytest
from botocore.awsrequest import AWSResponse
from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred
from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    _COGNITO_ISSUER_RE,
    _client_partition,
    _lambda_arn_from_integration_uri,
    apigateway_http_apis_detailed,
    aws_account_singleton,
    cloudfront_distributions_with_oac,
    eventbridge_rules_with_targets,
    iam_oidc_providers_described,
    route53_zones_with_alias_targets,
    s3_buckets_hydrated,
)
from tap_plugin.aws_core.collectors.boto3_collector.identity import edge_entity_id, node_entity_id
from tap_plugin.aws_core.collectors.boto3_collector.partition import (
    PARTITION_AWS,
    PARTITION_CN,
    PARTITION_US_GOV,
    build_arn,
    home_region,
    known_region,
    parse_arn,
    partition_of_arn,
    partition_of_region,
    service_unavailable_reason,
)
from tap_plugin.aws_core.collectors.boto3_collector.transforms import (
    build_transform_registry,
    kms_key_arn_or_none,
    s3_bucket_arn_from_name,
    s3_bucket_name_from_origin_domain,
)

from tap_cares.collectors.config import CollectorConfig
from tap_cares.secrets.models import Secret, SecretRef

ACCOUNT = "123456789012"
GOV_ROLE_ARN = f"arn:aws-us-gov:iam::{ACCOUNT}:role/x"
GOV_REGION = "us-gov-west-1"
_STATIC = {"access_key_id": "AKIAGOV", "secret_access_key": "shh"}
_ASSUMED = {
    "role_arn": GOV_ROLE_ARN,
    "external_id": "shared-external-id",
    "base": dict(_STATIC),
    "regions_allowed": [GOV_REGION],
}


def _endpoint(session: boto3.session.Session, service: str, region: str) -> str:
    return str(session.client(service, region_name=region).meta.endpoint_url)


def _hostname(url: str) -> str | None:
    """The exact host a URL targets — never a substring/prefix check on the URL string, which
    a URL like ``https://sts.us-gov-west-1.amazonaws.com.evil.example/`` would pass (CodeQL
    py/incomplete-url-substring-sanitization)."""
    return urlsplit(url).hostname


# --- partition helpers ------------------------------------------------------------------------


class TestPartitionHelpers:
    @pytest.mark.parametrize(
        ("region", "expected"),
        [
            ("us-east-1", PARTITION_AWS),
            ("eu-west-1", PARTITION_AWS),
            ("ap-southeast-2", PARTITION_AWS),
            ("us-gov-west-1", PARTITION_US_GOV),
            ("us-gov-east-1", PARTITION_US_GOV),
            ("cn-north-1", PARTITION_CN),
            ("cn-northwest-1", PARTITION_CN),
            ("us-iso-east-1", "aws-iso"),
            ("us-isob-east-1", "aws-iso-b"),
            ("", PARTITION_AWS),
        ],
    )
    def test_region_to_partition_agrees_with_botocore(self, region: str, expected: str) -> None:
        assert partition_of_region(region) == expected
        if region:
            client = boto3.client("sts", region_name=region, aws_access_key_id="x", aws_secret_access_key="y")
            assert client.meta.partition == expected  # botocore's own answer

    def test_home_regions(self) -> None:
        assert home_region(PARTITION_AWS) == "us-east-1"
        assert home_region(PARTITION_US_GOV) == "us-gov-west-1"

    @pytest.mark.parametrize(
        "region",
        ["us-east-1", "us-gov-west-1", "us-gov-east-1", "cn-north-1", "us-iso-east-1", "us-east-97", "eu-west-9"],
    )
    def test_known_region_accepts_every_recognised_shape(self, region: str) -> None:
        assert known_region(region) is True

    @pytest.mark.parametrize("region", ["us-gvo-west-1", "not-a-region-at-all-1", "xx-fake-1", ""])
    def test_known_region_refuses_a_typo_or_nonsense_string(self, region: str) -> None:
        assert known_region(region) is False

    @pytest.mark.parametrize(
        ("arn", "partition", "service", "account", "resource"),
        [
            (GOV_ROLE_ARN, "aws-us-gov", "iam", ACCOUNT, "role/x"),
            ("arn:aws:iam::123456789012:role/x", "aws", "iam", ACCOUNT, "role/x"),
            ("arn:aws-us-gov:iam::aws:policy/SecurityAudit", "aws-us-gov", "iam", "aws", "policy/SecurityAudit"),
            ("arn:aws-us-gov:s3:::my-bucket", "aws-us-gov", "s3", "", "my-bucket"),
            (
                "arn:aws-us-gov:lambda:us-gov-west-1:123456789012:function:f:live",
                "aws-us-gov",
                "lambda",
                ACCOUNT,
                "function:f:live",
            ),
            ("arn:aws-cn:iam::123456789012:role/x", "aws-cn", "iam", ACCOUNT, "role/x"),
        ],
    )
    def test_parse_arn_any_partition(self, arn: str, partition: str, service: str, account: str, resource: str):
        parsed = parse_arn(arn)
        assert parsed is not None
        assert (parsed.partition, parsed.service, parsed.account, parsed.resource) == (
            partition,
            service,
            account,
            resource,
        )
        assert partition_of_arn(arn) == partition

    @pytest.mark.parametrize("junk", ["", "not-an-arn", "arn:gcp:iam::123456789012:role/x", "arn:aws:iam::12:role/x", None, 7])
    def test_parse_arn_rejects_non_arns(self, junk: Any) -> None:
        assert parse_arn(junk) is None

    def test_build_arn(self) -> None:
        assert build_arn("aws-us-gov", "s3", "", "", "b") == "arn:aws-us-gov:s3:::b"

    def test_cloudfront_is_unavailable_in_govcloud_only(self) -> None:
        assert service_unavailable_reason(PARTITION_US_GOV, "cloudfront")
        assert service_unavailable_reason(PARTITION_AWS, "cloudfront") is None
        assert service_unavailable_reason(PARTITION_US_GOV, "iam") is None


# --- the secret: schema + partition resolution --------------------------------------------------


class TestGovCloudSecretShape:
    def test_static_secret_accepts_govcloud_shape(self) -> None:
        jsonschema.validate(
            {
                **_STATIC,
                "regions_allowed": ["us-gov-west-1", "us-gov-east-1"],
                "partition": "aws-us-gov",
                "use_fips_endpoint": True,
                "expected_account_id": ACCOUNT,
            },
            cred.AWS_STATIC_SCHEMA,
        )

    def test_assumed_role_secret_accepts_govcloud_shape(self) -> None:
        jsonschema.validate({**_ASSUMED, "partition": "aws-us-gov", "use_fips_endpoint": True}, cred.AWS_ASSUMED_ROLE_SCHEMA)

    @pytest.mark.parametrize("bad_region", ["gov-west", "US-GOV-WEST-1", "us-gov-west-1-fips", "us_gov_west_1", ""])
    def test_region_names_are_shape_checked(self, bad_region: str) -> None:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**_STATIC, "region": bad_region}, cred.AWS_STATIC_SCHEMA)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**_STATIC, "regions_allowed": [bad_region]}, cred.AWS_STATIC_SCHEMA)

    def test_unknown_partition_and_non_boolean_fips_rejected(self) -> None:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**_STATIC, "region": GOV_REGION, "partition": "aws-mars"}, cred.AWS_STATIC_SCHEMA)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**_STATIC, "region": GOV_REGION, "use_fips_endpoint": "yes"}, cred.AWS_STATIC_SCHEMA)

    def test_role_arn_must_be_an_iam_role_arn(self) -> None:
        for bad in ("x", "arn:aws-us-gov:iam::123456789012:user/u", "arn:aws-us-gov:s3:::b"):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate({**_ASSUMED, "role_arn": bad}, cred.AWS_ASSUMED_ROLE_SCHEMA)

    def test_partition_and_fips_are_shared_by_both_kinds(self) -> None:
        for prop in ("partition", "use_fips_endpoint", "regions_allowed", "region"):
            assert cred.AWS_STATIC_SCHEMA["properties"][prop] == cred.AWS_ASSUMED_ROLE_SCHEMA["properties"][prop]


class TestResolvePartition:
    def test_derived_from_regions(self) -> None:
        assert cred.resolve_partition(_STATIC, ["us-gov-west-1", "us-gov-east-1"]) == "aws-us-gov"
        assert cred.resolve_partition(_STATIC, ["us-east-1", "eu-west-1"]) == "aws"

    def test_declared_partition_must_agree(self) -> None:
        assert cred.resolve_partition({"partition": "aws-us-gov"}, [GOV_REGION]) == "aws-us-gov"
        with pytest.raises(cred.CredentialError, match="belong to partition"):
            cred.resolve_partition({"partition": "aws"}, [GOV_REGION])

    def test_mixed_partitions_refused(self) -> None:
        with pytest.raises(cred.CredentialError, match="spans partitions"):
            cred.resolve_partition(_STATIC, ["us-east-1", GOV_REGION])

    @pytest.mark.parametrize("region", ["cn-north-1", "us-iso-east-1"])
    def test_untested_partitions_refused_by_name(self, region: str) -> None:
        with pytest.raises(cred.CredentialError, match="not supported"):
            cred.resolve_partition(_STATIC, [region])

    def test_role_arn_partition_must_match_regions(self) -> None:
        assert cred.resolve_partition(_ASSUMED, [GOV_REGION]) == "aws-us-gov"
        commercial_role = {**_ASSUMED, "role_arn": f"arn:aws:iam::{ACCOUNT}:role/x"}
        with pytest.raises(cred.CredentialError, match="cannot cross partitions"):
            cred.resolve_partition(commercial_role, [GOV_REGION])
        with pytest.raises(cred.CredentialError, match="cannot cross partitions"):
            cred.resolve_partition(_ASSUMED, ["us-east-1"])

    def test_role_account_must_match_expected_account(self) -> None:
        with pytest.raises(cred.CredentialError, match="expected_account_id"):
            cred.resolve_partition({**_ASSUMED, "expected_account_id": "999988887777"}, [GOV_REGION])
        assert cred.resolve_partition({**_ASSUMED, "expected_account_id": ACCOUNT}, [GOV_REGION]) == "aws-us-gov"

    def test_a_typo_of_a_real_region_is_refused_not_silently_commercial(self) -> None:
        # "us-gvo-west-1" (letters swapped) matches no specific partition pattern; a partition
        # classifier that defaults every unmatched name to commercial would silently accept it
        # rather than failing closed on an unrecognised region.
        with pytest.raises(cred.CredentialError, match="not recognised"):
            cred.resolve_partition(_STATIC, ["us-gvo-west-1"])

    def test_a_region_matching_no_partition_at_all_is_refused(self) -> None:
        with pytest.raises(cred.CredentialError, match="not recognised"):
            cred.resolve_partition(_STATIC, ["not-a-region-at-all-1"])

    def test_a_genuine_but_botocore_unlisted_commercial_region_is_accepted(self) -> None:
        # A region botocore doesn't specifically enumerate but that matches the commercial
        # partition's own regionRegex shape is accepted, not rejected — the gate is "does not
        # match ANY partition's shape", not "is in some fixed list of real region names".
        assert cred.resolve_partition(_STATIC, ["us-east-97"]) == "aws"


# --- endpoints & FIPS (real botocore, no network) ----------------------------------------------


class TestGovCloudEndpoints:
    def test_global_services_resolve_to_govcloud_hosts(self) -> None:
        """The failure mode the old ``region_name="us-east-1"`` produced: a GovCloud credential
        sent to the commercial endpoint. Through a gov region botocore picks the GovCloud one."""
        session = cred.build_session(_STATIC)
        assert _endpoint(session, "iam", GOV_REGION) == "https://iam.us-gov.amazonaws.com"
        assert _endpoint(session, "iam", "us-gov-east-1") == "https://iam.us-gov.amazonaws.com"
        assert _endpoint(session, "organizations", GOV_REGION) == "https://organizations.us-gov-west-1.amazonaws.com"
        assert _endpoint(session, "route53", GOV_REGION) == "https://route53.us-gov.amazonaws.com"
        assert _endpoint(session, "sts", GOV_REGION) == "https://sts.us-gov-west-1.amazonaws.com"
        # ... and the literal the old code used is the WRONG partition for these credentials.
        assert _endpoint(session, "iam", "us-east-1") == "https://iam.amazonaws.com"

    def test_fips_flag_reaches_every_client_of_a_static_session(self) -> None:
        session = cred.build_session({**_STATIC, "use_fips_endpoint": True})
        assert _endpoint(session, "lambda", GOV_REGION) == "https://lambda-fips.us-gov-west-1.amazonaws.com"
        assert _endpoint(session, "kms", GOV_REGION) == "https://kms-fips.us-gov-west-1.amazonaws.com"
        assert _endpoint(session, "s3", GOV_REGION) == "https://s3-fips.us-gov-west-1.amazonaws.com"
        assert _endpoint(session, "iam", GOV_REGION) == "https://iam.us-gov.amazonaws.com"

    def test_fips_flag_in_commercial(self) -> None:
        session = cred.build_session({**_STATIC, "use_fips_endpoint": True})
        assert _endpoint(session, "sts", "us-east-1") == "https://sts-fips.us-east-1.amazonaws.com"

    def test_absent_flag_defers_to_environment_and_explicit_false_overrides_it(self, monkeypatch) -> None:
        monkeypatch.setenv("AWS_USE_FIPS_ENDPOINT", "true")
        assert "lambda-fips" in _endpoint(cred.build_session(_STATIC), "lambda", GOV_REGION)
        assert cred.fips_requested(_STATIC) is True
        off = {**_STATIC, "use_fips_endpoint": False}
        assert "lambda-fips" not in _endpoint(cred.build_session(off), "lambda", GOV_REGION)
        assert cred.fips_requested(off) is False

    def test_no_flag_no_env_is_not_fips(self, monkeypatch) -> None:
        monkeypatch.delenv("AWS_USE_FIPS_ENDPOINT", raising=False)
        # Isolate from whatever ~/.aws/config happens to exist in this environment — this test
        # asserts the "nothing at all requests FIPS" floor, not this machine's ambient config.
        monkeypatch.setenv("AWS_CONFIG_FILE", "/dev/null")
        assert cred.fips_requested(_STATIC) is False

    def test_shared_config_file_is_consulted_when_secret_and_env_are_silent(self, monkeypatch, tmp_path) -> None:
        # A version of fips_requested that reads only the secret and the environment variable
        # would miss ~/.aws/config, so an operator relying on it would see a false "FIPS off" in
        # self_test and the IDENTITY_RESOLVED log while every client was, in fact, using FIPS
        # endpoints (the same resolution chain _botocore_session leaves to botocore itself).
        monkeypatch.delenv("AWS_USE_FIPS_ENDPOINT", raising=False)
        config = tmp_path / "config"
        config.write_text("[default]\nuse_fips_endpoint = true\n")
        monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
        assert cred.fips_requested(_STATIC) is True
        # The explicit secret field still wins over the shared config file either way.
        assert cred.fips_requested({**_STATIC, "use_fips_endpoint": False}) is False


class _Raw:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def stream(self, *_a: Any, **_k: Any):
        yield self._body


_ASSUME_ROLE_XML = (
    b'<AssumeRoleResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/"><AssumeRoleResult><Credentials>'
    b"<AccessKeyId>ASIAGOVTMP</AccessKeyId><SecretAccessKey>tmp</SecretAccessKey>"
    b"<SessionToken>tok</SessionToken><Expiration>2030-01-01T00:00:00Z</Expiration>"
    b"</Credentials></AssumeRoleResult></AssumeRoleResponse>"
)
_CALLER_XML = (
    b'<GetCallerIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/"><GetCallerIdentityResult>'
    b"<Arn>arn:aws-us-gov:sts::123456789012:assumed-role/x/s</Arn><UserId>U</UserId><Account>123456789012</Account>"
    b"</GetCallerIdentityResult></GetCallerIdentityResponse>"
)


def _capture_wire(session: boto3.session.Session, body: bytes) -> list[Any]:
    """Answer every request botocore is about to send with ``body`` and record the request."""
    sent: list[Any] = []

    def _before_send(request: Any, **_kw: Any) -> AWSResponse:
        sent.append(request)
        return AWSResponse(request.url, 200, {"Content-Type": "text/xml"}, _Raw(body))

    session.events.register("before-send", _before_send)
    return sent


class TestAssumeRoleOnTheWire:
    """Cross-account AssumeRole with ExternalId, partition-aware, as botocore would send it."""

    def test_govcloud_assume_role_hits_govcloud_sts_with_gov_arn_and_external_id(self) -> None:
        data = dict(_ASSUMED)
        base = cred.build_session(data["base"])
        sent = _capture_wire(base, _ASSUME_ROLE_XML)

        session = cred.assume_role_session(base, data, GOV_REGION, timeout_seconds=5)

        assert len(sent) == 1
        request = sent[0]
        assert _hostname(request.url) == "sts.us-gov-west-1.amazonaws.com"
        body = request.body if isinstance(request.body, str) else request.body.decode()
        assert "Action=AssumeRole" in body
        assert "RoleArn=arn%3Aaws-us-gov%3Aiam%3A%3A123456789012%3Arole%2Fx" in body
        assert "ExternalId=shared-external-id" in body
        assert session.get_credentials().access_key == "ASIAGOVTMP"

    def test_fips_applies_to_the_assume_role_call_and_the_working_session(self) -> None:
        data = {**_ASSUMED, "use_fips_endpoint": True}
        # base_creds merges the secret's top-level flag into `base` — the base session itself
        # (not only the AssumeRole client built from it) is pinned, since it is a real,
        # client-bearing boto3.session.Session and not merely a throwaway credential holder.
        base = cred.build_session(cred.base_creds(data))
        assert "lambda-fips" in _endpoint(base, "lambda", GOV_REGION)
        sent = _capture_wire(base, _ASSUME_ROLE_XML)

        session = cred.assume_role_session(base, data, GOV_REGION, timeout_seconds=5)

        assert len(sent) == 1  # the AssumeRole call was made
        assert "lambda-fips" in _endpoint(session, "lambda", GOV_REGION)

    def test_base_creds_merges_the_top_level_flag_and_leaves_absence_absent(self) -> None:
        merged = cred.base_creds({**_ASSUMED, "use_fips_endpoint": True})
        assert merged["use_fips_endpoint"] is True
        assert merged["access_key_id"] == _ASSUMED["base"]["access_key_id"]
        # No top-level flag at all -> base_creds carries None, which build_session/
        # _botocore_session treat as "defer to ambient resolution", identically to before.
        silent = cred.base_creds(_ASSUMED)
        assert silent["use_fips_endpoint"] is None

    def test_caller_identity_goes_to_the_govcloud_sts_endpoint(self) -> None:
        session = cred.build_session(_STATIC)
        sent = _capture_wire(session, _CALLER_XML)
        assert cred.caller_account_id(session, GOV_REGION, timeout_seconds=5) == ACCOUNT
        assert _hostname(sent[0].url) == "sts.us-gov-west-1.amazonaws.com"


# --- transforms & ARN handling -----------------------------------------------------------------


class TestPartitionAwareTransforms:
    def test_bare_bucket_name_gets_the_run_partition(self) -> None:
        assert s3_bucket_arn_from_name("audit") == "arn:aws:s3:::audit"  # default unchanged
        assert s3_bucket_arn_from_name("audit", partition="aws-us-gov") == "arn:aws-us-gov:s3:::audit"

    def test_an_arn_of_any_partition_passes_through(self) -> None:
        for arn in ("arn:aws-us-gov:s3:::audit", "arn:aws:s3:::audit"):
            assert s3_bucket_arn_from_name(arn, partition="aws-us-gov") == arn

    def test_cloudfront_origin_bucket_uses_the_run_partition(self) -> None:
        assert (
            s3_bucket_name_from_origin_domain("b.s3.us-gov-west-1.amazonaws.com", partition="aws-us-gov")
            == "arn:aws-us-gov:s3:::b"
        )
        assert s3_bucket_name_from_origin_domain("b.s3.amazonaws.com") == "arn:aws:s3:::b"

    def test_registry_binds_the_partition(self) -> None:
        gov = build_transform_registry("aws-us-gov")
        assert gov.get("s3_bucket_arn_from_name")("audit") == "arn:aws-us-gov:s3:::audit"
        assert build_transform_registry().get("s3_bucket_arn_from_name")("audit") == "arn:aws:s3:::audit"

    def test_kms_key_arn_accepts_govcloud(self) -> None:
        key = "arn:aws-us-gov:kms:us-gov-west-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab"
        assert kms_key_arn_or_none(key) == key
        assert kms_key_arn_or_none("alias/x") is None

    def test_lambda_integration_uri_govcloud(self) -> None:
        fn = "arn:aws-us-gov:lambda:us-gov-west-1:123456789012:function:f"
        uri = f"arn:aws-us-gov:apigateway:us-gov-west-1:lambda:path/2015-03-31/functions/{fn}/invocations"
        assert _lambda_arn_from_integration_uri(uri) == fn
        assert _lambda_arn_from_integration_uri(f"{uri.replace('/invocations', '')}:live/invocations") == fn

    def test_cognito_issuer_govcloud(self) -> None:
        match = _COGNITO_ISSUER_RE.match("https://cognito-idp.us-gov-west-1.amazonaws.com/us-gov-west-1_AbCd1234")
        assert match and match.group("pool") == "us-gov-west-1_AbCd1234"


# --- custom fns: no literal us-east-1, no commercial-only services -----------------------------


class _GovFake:
    """A fake client that reports being bound to GovCloud, answers the named ops, and returns an
    empty response for any other op (like a real client with nothing to list)."""

    meta = SimpleNamespace(partition="aws-us-gov", region_name=GOV_REGION)

    def __init__(self, **ops: Any) -> None:
        self._ops = ops

    def can_paginate(self, _method: str) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._ops.get(name, lambda **_kw: {})


def _gov_client(**ops: Any) -> _GovFake:
    return _GovFake(**ops)


class _NoDirectClientSession:
    """A session that FAILS if a custom fn builds its own client instead of using the run's
    ``client_for`` — the old ``session.client(svc, region_name="us-east-1")`` pattern."""

    events = SimpleNamespace(register=lambda *_a, **_k: None)

    def client(self, service: str, **kw: Any) -> Any:
        raise AssertionError(f"custom fn built session.client({service!r}, {kw}) instead of using client_for")


def _client_for(clients: dict[str, Any], asked: list[str] | None = None):
    def client_for(service: str) -> Any:
        if asked is not None:
            asked.append(service)
        return clients[service]

    return client_for


class TestClientPartitionFallback:
    """``_client_partition`` calls ``_client_region``, defined later in the same module —
    ordinary Python late binding (a function body resolves names when it RUNS, not when it is
    defined), so this is not a NameError risk, but the fallback branch (a client with no
    ``meta.partition`` at all) was otherwise never exercised by any test: every fake client
    built for this test file sets ``meta.partition`` explicitly. This proves the fallback path
    actually runs and returns the right answer, not merely that it fails to raise."""

    def test_reads_meta_partition_when_present(self) -> None:
        client = SimpleNamespace(meta=SimpleNamespace(partition="aws-us-gov", region_name=GOV_REGION))
        assert _client_partition(client) == "aws-us-gov"

    def test_falls_back_to_region_classification_when_meta_partition_is_absent(self) -> None:
        client = SimpleNamespace(meta=SimpleNamespace(region_name=GOV_REGION))  # no .partition
        assert _client_partition(client) == "aws-us-gov"

    def test_falls_back_to_commercial_when_there_is_no_meta_at_all(self) -> None:
        assert _client_partition(SimpleNamespace()) == "aws"


class TestCustomFnsUseTheRunsPartition:
    def test_account_singleton_uses_client_for_for_sts_and_iam(self) -> None:
        asked: list[str] = []
        sts = _gov_client(
            get_caller_identity=lambda: {"Account": ACCOUNT, "Arn": "arn:aws-us-gov:sts::123456789012:assumed-role/r/s"}
        )
        iam = _gov_client(list_account_aliases=lambda: {"AccountAliases": ["govco"]})
        items = list(
            aws_account_singleton(_NoDirectClientSession(), client_for=_client_for({"sts": sts, "iam": iam}, asked))
        )
        assert asked == ["sts", "iam"]
        assert items[0]["Account"] == ACCOUNT and items[0]["_account_name"] == "govco"

    def test_iam_oidc_providers_use_client_for(self) -> None:
        provider = f"arn:aws-us-gov:iam::{ACCOUNT}:oidc-provider/token.example"
        iam = _gov_client(
            list_open_id_connect_providers=lambda: {"OpenIDConnectProviderList": [{"Arn": provider}]},
            get_open_id_connect_provider=lambda **_kw: {"Url": "token.example"},
        )
        items = list(iam_oidc_providers_described(_NoDirectClientSession(), client_for=_client_for({"iam": iam})))
        assert items[0]["ProviderArn"] == provider

    def test_cloudfront_is_never_called_in_govcloud(self) -> None:
        """Route 53 still collects; the CloudFront join is skipped, not attempted."""
        asked: list[str] = []
        r53 = _gov_client(
            list_hosted_zones=lambda: {"HostedZones": [{"Id": "/hostedzone/ZGOV1", "Name": "gov.example."}]},
            list_resource_record_sets=lambda **_kw: {
                "ResourceRecordSets": [
                    {"Name": "gov.example.", "Type": "A", "AliasTarget": {"DNSName": "dabc.cloudfront.net."}}
                ]
            },
        )
        zones = list(
            route53_zones_with_alias_targets(_NoDirectClientSession(), client_for=_client_for({"route53": r53}, asked))
        )
        assert "cloudfront" not in asked
        assert zones[0]["alias_cloudfront_domains"] == ["dabc.cloudfront.net"]  # raw fact kept
        assert zones[0]["alias_cloudfront_arns"] == []  # nothing resolvable without CloudFront

    def test_cloudfront_distribution_fn_yields_nothing_in_govcloud(self) -> None:
        cf = _gov_client(list_distributions=lambda: (_ for _ in ()).throw(AssertionError("must not be called")))
        assert list(cloudfront_distributions_with_oac(_NoDirectClientSession(), client_for=_client_for({"cloudfront": cf}))) == []

    def test_eventbridge_selects_govcloud_lambda_targets(self) -> None:
        fn = f"arn:aws-us-gov:lambda:{GOV_REGION}:{ACCOUNT}:function:f"
        queue = f"arn:aws-us-gov:sqs:{GOV_REGION}:{ACCOUNT}:q"
        events = _gov_client(
            list_rules=lambda **_kw: {"Rules": [{"Name": "r", "Arn": f"arn:aws-us-gov:events:{GOV_REGION}:{ACCOUNT}:rule/r"}]},
            list_targets_by_rule=lambda **_kw: {"Targets": [{"Arn": fn}, {"Arn": queue}]},
        )
        item = next(iter(eventbridge_rules_with_targets(None, client_for=_client_for({"events": events}))))
        assert item["_lambda_target_arns"] == [fn]
        assert item["_target_arns"] == [fn, queue]

    def test_api_arn_is_synthesised_in_the_regions_partition(self) -> None:
        apigw = _gov_client(get_apis=lambda **_kw: {"Items": [{"ApiId": "gov1", "Name": "n"}]})
        item = next(iter(apigateway_http_apis_detailed(None, client_for=_client_for({"apigatewayv2": apigw}))))
        assert item["_api_arn"] == f"arn:aws-us-gov:apigateway:{GOV_REGION}::/apis/gov1"

    def test_s3_bucket_arn_is_synthesised_when_listbuckets_omits_it_and_region_falls_back_in_partition(self) -> None:
        def _boom(**_kw: Any) -> Any:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "GetBucketLocation")

        s3 = _gov_client(
            list_buckets=lambda: {"Buckets": [{"Name": "gov-bucket"}]},
            get_bucket_location=_boom,
        )
        regions_asked: list[str | None] = []
        session = SimpleNamespace(
            client=lambda service, region_name=None, **_kw: (regions_asked.append(region_name), s3)[1]
            if service == "s3"
            else _gov_client(get_metric_data=lambda **_kw: {}),
            events=SimpleNamespace(register=lambda *_a, **_k: None),
        )
        items = list(s3_buckets_hydrated(session, client_for=_client_for({"s3": s3})))
        assert items[0]["BucketArn"] == "arn:aws-us-gov:s3:::gov-bucket"
        assert regions_asked == [GOV_REGION]  # the fallback region is GovCloud's, not us-east-1


# --- falsifiers: account gate is partition-independent; sessions inherit FIPS -------------------


def test_default_falsifier_session_inherits_govcloud_fips(monkeypatch) -> None:
    from tap_plugin.aws_core import falsifiers

    secret = Secret(
        ref=SecretRef(scope="aws_core", key="boto_collector"),
        kind="aws_static_access_key",
        description="t",
        data={**_STATIC, "regions_allowed": [GOV_REGION], "use_fips_endpoint": True},
        metadata={},
        source_path=Path("/dev/null"),
    )
    monkeypatch.setattr(cred, "resolve_secret", lambda _ref: secret)
    monkeypatch.setattr(falsifiers, "caller_account_id", lambda *a, **k: ACCOUNT)
    session, account_id = falsifiers._default_session()
    assert account_id == ACCOUNT
    assert _endpoint(session, "lambda", GOV_REGION) == "https://lambda-fips.us-gov-west-1.amazonaws.com"


def test_default_falsifier_session_fails_closed_on_a_partition_mismatch(monkeypatch) -> None:
    """A falsifier resolves its own credential independently of any collector run, so a secret
    edited to something partition-inconsistent between runs must be refused here too — this is
    the same resolve_partition gate Boto3Collector.run() applies, exercised through the
    falsifier's own session factory rather than through the collector."""
    from tap_plugin.aws_core import falsifiers

    secret = Secret(
        ref=SecretRef(scope="aws_core", key="boto_collector"),
        kind="aws_static_access_key",
        description="t",
        # Mixed-partition regions: one commercial, one GovCloud — resolve_partition must
        # refuse this before any client is built or any AWS call is attempted.
        data={**_STATIC, "regions_allowed": ["us-east-1", GOV_REGION]},
        metadata={},
        source_path=Path("/dev/null"),
    )
    monkeypatch.setattr(cred, "resolve_secret", lambda _ref: secret)
    called: list[str] = []
    monkeypatch.setattr(falsifiers, "build_session", lambda *a, **k: called.append("build_session"))
    monkeypatch.setattr(falsifiers, "caller_account_id", lambda *a, **k: called.append("caller_account_id"))
    with pytest.raises(cred.CredentialError, match="spans partitions"):
        falsifiers._default_session()
    assert called == []  # refused before any session was built or any AWS call attempted


@pytest.mark.django_db
class TestSubnetFalsifierInGovCloud:
    def test_gov_region_and_account_gate(self) -> None:
        from botocore.exceptions import ClientError
        from tap_plugin.aws_core.falsifiers import SubnetFalsifier

        from tap_grid.falsifiers import DROPPED_FROM_OBSERVATION, UNDETERMINED, Candidate, FalsifyContext
        from tap_grid.services import create_node, get_node

        result = create_node("aws_core__aws_subnet", {"subnet_id": "subnet-gov1", "name": "gov"})
        assert result.success
        entity_id = uuid.UUID(str(result.entity_id))
        row = get_node(entity_id)
        row.entity.dimensions = {"cloud": "aws", "aws_account": ACCOUNT, "aws_region": GOV_REGION}
        row.entity.save(update_fields=["dimensions"])

        regions: list[str] = []

        class _Ec2:
            def describe_subnets(self, SubnetIds: list[str]) -> Any:  # noqa: N803
                raise ClientError({"Error": {"Code": "InvalidSubnetID.NotFound", "Message": "gone"}}, "DescribeSubnets")

        class _Session:
            def client(self, service: str, region_name: str | None = None) -> Any:
                regions.append(str(region_name))
                return _Ec2()

        candidate = Candidate(
            entity_id=entity_id,
            entity_type="aws_core__aws_subnet",
            reason="dropped_from_observation",
            surface=0,
            relation="fixture",
            subject=None,
            edge_type=None,
            parent=None,
            interval_first=None,
        )
        ctx = FalsifyContext(batch_id=str(uuid.uuid4()), statement=None)
        # Right account: probed in the GovCloud region the grid recorded, NotFound is a real answer.
        (verdict,) = SubnetFalsifier(session=_Session(), account_id=ACCOUNT).batch_falsify([candidate], ctx)
        assert regions == [GOV_REGION]
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        # Wrong account (e.g. the commercial twin of a GovCloud account): refused, never probed.
        regions.clear()
        (refused,) = SubnetFalsifier(session=_Session(), account_id="999988887777").batch_falsify(
            [candidate], FalsifyContext(batch_id=str(uuid.uuid4()), statement=None)
        )
        assert regions == []
        assert refused.verdict == UNDETERMINED


# --- the collector end to end, GovCloud-shaped -------------------------------------------------

_GOV_FN = f"arn:aws-us-gov:lambda:{GOV_REGION}:{ACCOUNT}:function:gov-handler"
_GOV_RULE = f"arn:aws-us-gov:events:{GOV_REGION}:{ACCOUNT}:rule/gov-rule"
_GOV_BUCKET = "gov-bucket"
_GOV_BUCKET_ARN = f"arn:aws-us-gov:s3:::{_GOV_BUCKET}"

_GOV_CANNED: dict[str, Any] = {
    "list_functions": {
        "Functions": [
            {
                "FunctionName": "gov-handler",
                "FunctionArn": _GOV_FN,
                "Runtime": "python3.13",
                "Role": GOV_ROLE_ARN,
                "VpcConfig": {"SubnetIds": [], "SecurityGroupIds": [], "VpcId": ""},
            }
        ]
    },
    "list_roles": {"Roles": [{"RoleName": "x", "Arn": GOV_ROLE_ARN, "Path": "/", "MaxSessionDuration": 3600}]},
    "list_rules": {"Rules": [{"Name": "gov-rule", "Arn": _GOV_RULE, "State": "ENABLED"}]},
    "list_targets_by_rule": {"Targets": [{"Arn": _GOV_FN}]},
    "list_buckets": {"Buckets": [{"Name": _GOV_BUCKET}]},  # no BucketArn: exercised on purpose
    "get_bucket_location": {"LocationConstraint": GOV_REGION},
    "list_role_tags": {"Tags": []},
}


class _GovPaginator:
    def paginate(self, **_kw: Any):
        yield {"ResourceTagMappingList": [{"ResourceARN": _GOV_FN, "Tags": [{"Key": "Owner", "Value": "gov"}]}]}


class _GovCannedClient:
    meta = SimpleNamespace(partition="aws-us-gov", region_name=GOV_REGION)

    def can_paginate(self, _method: str) -> bool:
        return False

    def get_paginator(self, _name: str) -> _GovPaginator:
        return _GovPaginator()

    def __getattr__(self, name: str):
        return lambda **_kw: _GOV_CANNED.get(name, {})


class _GovSession:
    events = SimpleNamespace(register=lambda *_a, **_k: None)

    def client(self, _service: str, **_kw: Any) -> _GovCannedClient:
        return _GovCannedClient()


def _stub_gov(monkeypatch, *, regions: list[str], extra: dict[str, Any] | None = None) -> None:
    secret = Secret(
        ref=SecretRef(scope="aws_core", key="boto_collector"),
        kind="aws_static_access_key",
        description="test",
        data={**_STATIC, "regions_allowed": regions, "use_fips_endpoint": True, **(extra or {})},
        metadata={},
        source_path=Path("/dev/null"),
    )
    monkeypatch.setattr(cred, "resolve_secret", lambda _ref: secret)
    monkeypatch.setattr(collector_mod, "build_session", lambda _data: _GovSession())
    monkeypatch.setattr(collector_mod, "client_factory", lambda _s, _r: (lambda _svc: _GovCannedClient()))
    monkeypatch.setattr(collector_mod, "caller_account_id", lambda *a, **k: ACCOUNT)


def _run() -> Boto3Collector:
    collector = Boto3Collector(
        CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7())
    )
    collector.run()
    return collector


@pytest.mark.django_db
class TestCollectorRunInGovCloud:
    def test_run_lands_govcloud_shaped_nodes_and_says_cloudfront_is_not_offered(self, monkeypatch) -> None:
        from tap_grid.services import get_edge, get_node

        _stub_gov(monkeypatch, regions=[GOV_REGION])
        collector = _run()

        assert collector.results["error"] == []
        # The run names its partition.
        identity = next(e for e in collector.results["info"] if e["message_code"] == "IDENTITY_RESOLVED")
        assert identity["message_data"]["partition"] == "aws-us-gov"
        assert identity["message_data"]["use_fips_endpoint"] is True
        assert "aws-us-gov" in collector.summary
        # us-gov-west-1 is the partition's anchor region: in scope, so no invariant warning.
        assert not [w for w in collector.results["warn"] if w["message_code"] == "REGION_INVARIANT"]

        # CloudFront: a clear "not available in this partition" result — not a skipped-with-error warn.
        info = [e for e in collector.results["info"] if e["message_code"] == "SERVICE_NOT_AVAILABLE_IN_PARTITION"]
        assert [e["message_data"]["service"] for e in info] == ["cloudfront"]
        assert "not available in partition aws-us-gov" in info[0]["message"]
        assert not [
            w for w in collector.results["warn"] if w["message_code"] == "ENTRY_SKIPPED" and "cloudfront" in w["message"]
        ]

        # GovCloud ARNs land as natural keys, unchanged.
        role = get_node(node_entity_id("aws_core__aws_iam_role", GOV_ROLE_ARN))
        assert role.role_arn == GOV_ROLE_ARN
        fn = get_node(node_entity_id("aws_core__aws_lambda", _GOV_FN))
        assert fn.function_arn == _GOV_FN and fn.tags == {"Owner": "gov"}
        # The EventBridge rule -> Lambda edge resolves: the Lambda-ARN filter accepts aws-us-gov.
        edge = get_edge(edge_entity_id("INVOKES_LAMBDA__aws_core", _GOV_RULE, _GOV_FN))
        assert str(edge.to_entity_id) == str(node_entity_id("aws_core__aws_lambda", _GOV_FN))
        # The S3 bucket's ARN was minted in the run's partition.
        bucket = get_node(node_entity_id("aws_core__aws_s3_bucket", _GOV_BUCKET_ARN))
        assert bucket.bucket_arn == _GOV_BUCKET_ARN

    def test_anchor_region_invariant_names_the_govcloud_anchor(self, monkeypatch) -> None:
        _stub_gov(monkeypatch, regions=["us-gov-east-1"])
        collector = _run()
        warn = [w for w in collector.results["warn"] if w["message_code"] == "REGION_INVARIANT"]
        assert len(warn) == 1 and "us-gov-west-1" in warn[0]["message"]
        assert "us-east-1" not in warn[0]["message"]

    def test_partition_mismatch_aborts_by_name_before_any_aws_call(self, monkeypatch) -> None:
        _stub_gov(monkeypatch, regions=[GOV_REGION], extra={"partition": "aws"})
        called: list[str] = []
        monkeypatch.setattr(collector_mod, "caller_account_id", lambda *a, **k: called.append("sts") or ACCOUNT)
        collector = Boto3Collector(
            CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7())
        )
        with pytest.raises(collector_mod.Boto3CollectorError, match="belong to partition"):
            collector.run()
        assert called == []
        assert [e["message_code"] for e in collector.results["error"]] == ["PARTITION_UNUSABLE"]


class TestSelfTestReportsPartition:
    def test_ready_and_partition_check_named(self, monkeypatch) -> None:
        from tap_cares.collectors import CollectorReadinessStatus

        _stub_gov(monkeypatch, regions=[GOV_REGION])
        result = Boto3Collector.self_test()
        assert result.status == CollectorReadinessStatus.READY
        names = {c.code: c for c in result.checks}
        assert "AWS_PARTITION" in names
        assert "aws-us-gov" in names["AWS_PARTITION"].message

    def test_role_arn_in_the_wrong_partition_is_misconfigured(self, monkeypatch) -> None:
        from tap_cares.collectors import CollectorReadinessStatus

        secret = Secret(
            ref=SecretRef(scope="aws_core", key="boto_collector"),
            kind="aws_assumed_role",
            description="t",
            data={**_ASSUMED, "role_arn": f"arn:aws:iam::{ACCOUNT}:role/x"},
            metadata={},
            source_path=Path("/dev/null"),
        )
        monkeypatch.setattr(cred, "resolve_secret", lambda _ref: secret)
        result = Boto3Collector.self_test()
        assert result.status == CollectorReadinessStatus.MISCONFIGURED
        assert not result.runnable


# Shape guard: nothing executable in the collector package may hardcode the commercial partition
# or a commercial client region again. AST-based, so docstrings and comments that DESCRIBE the old
# form (``arn:aws:...``) do not trip it.
def _executable_offenders(path: Path) -> list[str]:
    import ast

    tree = ast.parse(path.read_text())
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "region_name":
            if isinstance(node.value, ast.Constant) and node.value.value == "us-east-1":
                found.append(f"{path.name}:{node.value.lineno}: region_name='us-east-1'")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if "arn:aws:" in node.value:
                found.append(f"{path.name}:{node.lineno}: literal {node.value!r}")
    return found


def test_no_hardcoded_commercial_partition_or_region_in_collector_code() -> None:
    root = Path(cred.__file__).parent
    offenders = [o for path in sorted(root.glob("*.py")) for o in _executable_offenders(path)]
    assert not offenders, "commercial-only literals in executable collector code:\n" + "\n".join(offenders)
