"""Credential types carry tap.computing.credential (req-aws-core-credential-dimension).

George ruled on 2026-11-23 (aws-build Q146) that one dimension, computing_core's
``tap.computing.credential``, marks every credential type across all plugins, its value naming the kind.
On 2026-11-24 (Q151) he made the dimension open, its kinds a documented vocabulary rather than a bound,
and added ``mfa_device``.
A type is tagged by what the thing IS: identities, policies, issuers and things that only reference a
credential are not. This pins the exact set, so a type gained or lost is a decision someone made here.
"""

from __future__ import annotations

import pytest

CREDENTIAL = "tap.computing.credential"
# computing_core's documented kinds (Q146b, plus mfa_device from Q151d). The dimension is open (Q151a), so these
# are a vocabulary its seed's description documents, not a bound; aws_core uses only documented kinds.
KINDS = {
    "access_key",
    "password",
    "ssh_key",
    "certificate",
    "api_key",
    "token",
    "crypto_key",
    "secret_store",
    "mfa_device",
}

TAGGED = {
    "aws_core__aws_kms_key": "crypto_key",
    "aws_core__aws_acm_certificate": "certificate",
    "aws_core__aws_iam_server_certificate": "certificate",
    "aws_core__aws_iot_certificate": "certificate",
    "aws_core__aws_iot_ca_certificate": "certificate",
    "aws_core__aws_dms_certificate": "certificate",
    "aws_core__aws_transfer_certificate": "certificate",
    "aws_core__aws_apigateway_client_certificate": "certificate",
    "aws_core__aws_apigateway_api_key": "api_key",
    "aws_core__aws_location_api_key": "api_key",
    "aws_core__aws_secrets_manager_secret": "secret_store",
    "aws_core__aws_codebuild_source_credential": "token",
    "aws_core__aws_transfer_host_key": "ssh_key",
    "aws_core__aws_ec2_key_pair": "ssh_key",
    "aws_core__aws_certificatemanager_acme_external_account_binding": "access_key",
    "aws_core__aws_iam_virtual_mfa_device": "mfa_device",
    # the IAM user credentials (req-aws-core-iam-credentials-9)
    "aws_core__aws_iam_access_key": "access_key",
    "aws_core__aws_iam_ssh_public_key": "ssh_key",
    "aws_core__aws_iam_signing_certificate": "certificate",
    "aws_core__aws_iam_service_specific_credential": "password",
}

# Near misses, decided not to be credentials: each would be wrong to find in a credential filter.
NOT_CREDENTIALS = {
    # identities that hold or use credentials
    "aws_core__aws_iam_user",
    "aws_core__aws_iam_role",
    "aws_core__aws_iam_root_user",
    "aws_core__aws_elasticache_user",
    "aws_core__aws_memorydb_user",
    "aws_core__aws_transfer_user",
    "aws_core__aws_cognito_user_pool_client",
    # policies and configuration
    "aws_core__aws_iam_policy",
    "aws_core__aws_lambda_code_signing_config",
    "aws_core__aws_signer_signing_profile",
    "aws_core__aws_redshift_snapshot_copy_grant",
    # issuers and trust anchors
    "aws_core__aws_acm_private_ca",
    "aws_core__aws_eks_certificate_authority",
    "aws_core__aws_rolesanywhere_trust_anchor",
    "aws_core__aws_elasticloadbalancingv2_trust_store",
    # references to a credential
    "aws_core__aws_kms_alias",
    "aws_core__aws_eventbridge_connection",
    "aws_core__aws_codestarconnections_connection",
    "aws_core__aws_glue_connection",
    "aws_core__aws_iot_role_alias",
    "aws_core__aws_iot_certificate_provider",
    # challenges and endpoints
    "aws_core__aws_certificatemanager_acme_domain_validation",
    "aws_core__aws_certificatemanager_acme_endpoint",
    "aws_core__aws_ec2_ipam_external_resource_verification_token",
    # a database namespace, not a key
    "aws_core__aws_cassandra_keyspace",
    # only a SecureString instance is a credential, so the type carries no default; the collector is to stamp
    # secret_store per SecureString parameter (Q151b)
    "aws_core__aws_ssm_parameter",
}


def _defaults() -> dict[str, dict[str, str]]:
    from django.apps import apps

    return {
        model.ENTITY_TYPE: dict(getattr(model, "DEFAULT_DIMENSIONS", {}) or {})
        for model in apps.get_app_config("aws_core").get_models()
        if getattr(model, "ENTITY_TYPE", "")
    }


@pytest.mark.spec("req-aws-core-credential-dimension-1")
def test_exactly_the_credential_types_are_tagged_with_their_kind() -> None:
    tagged = {slug: dims[CREDENTIAL] for slug, dims in _defaults().items() if CREDENTIAL in dims}
    assert tagged == TAGGED


@pytest.mark.spec("req-aws-core-credential-dimension-1")
def test_every_value_is_a_documented_kind_and_the_cloud_stays() -> None:
    defaults = _defaults()
    for slug, kind in TAGGED.items():
        assert kind in KINDS, slug
        assert defaults[slug] == {"tap.computing.cloud": "aws", CREDENTIAL: kind}, slug


@pytest.mark.spec("req-aws-core-credential-dimension-1")
def test_the_near_misses_exist_and_are_not_tagged() -> None:
    defaults = _defaults()
    assert NOT_CREDENTIALS <= set(defaults), sorted(NOT_CREDENTIALS - set(defaults))
    assert not {slug for slug in NOT_CREDENTIALS if CREDENTIAL in defaults[slug]}


@pytest.mark.spec("req-aws-core-credential-dimension-2")
def test_computing_core_declares_the_dimension_open_with_these_kinds_documented() -> None:
    """The installed computing_core seeds the dimension open (no values) and documents every kind this plugin uses."""
    import json
    from importlib import resources

    seed = json.loads(
        resources.files("tap_plugin.computing_core").joinpath("grift/dimension.grift.json").read_text(encoding="utf-8")
    )
    (node,) = [n["node"] for b in seed["batches"] for n in b["nodes"] if n["node"]["name"] == CREDENTIAL]
    assert "values" not in node
    for kind in KINDS:
        assert f"{kind} (" in node["description"], kind
