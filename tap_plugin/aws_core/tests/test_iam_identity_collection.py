"""Collection of the five IAM identity types: group, instance profile, SAML provider, server
certificate and virtual MFA device (the readers in ``customfns.py``, their manifest entries and the
edges they declare). Fake IAM clients, no network."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector.authority import COMPLETE, EDGE_READS, FAILED, PARTIAL
from tap_plugin.aws_core.collectors.boto3_collector.batch import node_envelope
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    iam_groups_listed,
    iam_instance_profiles_listed,
    iam_saml_providers_described,
    iam_server_certificates_listed,
    iam_virtual_mfa_devices_listed,
)
from tap_plugin.aws_core.collectors.boto3_collector.listing import ListingWalk
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
from tap_plugin.aws_core.tests.test_trial_run_live import _create_verb_schema, _prepare_null_payload

ACCOUNT = "123456789012"
WHEN = datetime(2026, 10, 1, 12, 30, tzinfo=UTC)
WHEN_TEXT = "2026-10-01T12:30:00Z"
SEED_CANARY = "TAPCANARYBASE32SEEDXYZ"
QR_CANARY = b"TAPCANARYQRPNGBYTES"


def _denied(op: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, op)


class _Iam:
    """A fake IAM client: a method answers with its canned value, raises it if it is an exception, and
    calls it if it is callable. A method nobody canned fails the test that called it."""

    def __init__(self, **canned: Any) -> None:
        self._canned = canned
        self.calls: list[str] = []

    def can_paginate(self, method: str) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        def call(**kwargs: Any) -> Any:
            self.calls.append(name)
            if name not in self._canned:
                raise AssertionError(f"{name} was not expected")
            value = self._canned[name]
            if isinstance(value, Exception):
                raise value
            return value(**kwargs) if callable(value) else value

        return call


def _run(fn: Any, iam: _Iam) -> tuple[list[dict[str, Any]], ListingWalk]:
    walk = ListingWalk()
    items = list(fn(None, client_for=lambda service: iam, walk=walk))
    return items, walk


def _entry(entity_type: str) -> dict[str, Any]:
    return next(e for e in manifest_entries() if e["entity_type"] == entity_type)


GROUP = "aws_core__aws_iam_group"
PROFILE = "aws_core__aws_iam_instance_profile"
SAML = "aws_core__aws_iam_saml_provider"
CERT = "aws_core__aws_iam_server_certificate"
MFA = "aws_core__aws_iam_virtual_mfa_device"

POLICY_ARN = f"arn:aws:iam::{ACCOUNT}:policy/app"
AWS_POLICY_ARN = "arn:aws:iam::aws:policy/ReadOnlyAccess"


class TestGroups:
    def _iam(self, **over: Any) -> _Iam:
        canned: dict[str, Any] = {
            "list_groups": {
                "Groups": [
                    {"GroupName": "admins", "Path": "/", "GroupId": "AGPA1", "Arn": f"arn:aws:iam::{ACCOUNT}:group/admins"},
                    {"GroupName": "devs", "Path": "/eng/", "GroupId": "AGPA2", "Arn": f"arn:aws:iam::{ACCOUNT}:group/eng/devs"},
                ],
                "IsTruncated": False,
            },
            "get_account_summary": {"SummaryMap": {"Groups": 2}},
            "list_attached_group_policies": {
                "AttachedPolicies": [
                    {"PolicyName": "ro", "PolicyArn": AWS_POLICY_ARN},
                    {"PolicyName": "app", "PolicyArn": POLICY_ARN},
                ]
            },
        }
        canned.update(over)
        return _Iam(**canned)

    def test_lists_to_the_end_takes_the_control_and_reads_attached_policies(self) -> None:
        items, walk = _run(iam_groups_listed, self._iam())
        assert [i["GroupName"] for i in items] == ["admins", "devs"]
        assert (walk.complete, walk.count, walk.count_reported, walk.admitted) == (True, 2, 2, True)
        assert items[0]["_attached_policy_arns"] == sorted([AWS_POLICY_ARN, POLICY_ARN])
        assert items[0][EDGE_READS] == {"_attached_policy_arns": COMPLETE}

    def test_an_unreadable_attachment_list_is_not_an_empty_one(self) -> None:
        items, _ = _run(iam_groups_listed, self._iam(list_attached_group_policies=_denied("ListAttachedGroupPolicies")))
        assert items[0]["_attached_policy_arns"] is None
        assert items[0][EDGE_READS] == {"_attached_policy_arns": FAILED}

    def test_a_group_with_no_attachments_reads_as_an_empty_list(self) -> None:
        items, _ = _run(iam_groups_listed, self._iam(list_attached_group_policies={"AttachedPolicies": []}))
        assert items[0]["_attached_policy_arns"] == []

    def test_a_truncated_listing_is_not_complete(self) -> None:
        listing = {"Groups": [{"GroupName": "a", "Arn": f"arn:aws:iam::{ACCOUNT}:group/a"}], "IsTruncated": True}
        _, walk = _run(iam_groups_listed, self._iam(list_groups=listing))
        assert walk.complete is False

    def test_a_group_without_a_name_is_dropped_and_clears_admitted(self) -> None:
        listing = {"Groups": [{"Arn": f"arn:aws:iam::{ACCOUNT}:group/x"}], "IsTruncated": False}
        items, walk = _run(iam_groups_listed, self._iam(list_groups=listing))
        assert items == []
        assert walk.admitted is False

    def test_the_manifest_entry_projects_the_group(self) -> None:
        items, _ = _run(iam_groups_listed, self._iam())
        node = project_item(_entry(GROUP), items[1])
        assert node.natural_key == f"arn:aws:iam::{ACCOUNT}:group/eng/devs"
        assert node.fields["name"] == "devs"
        assert node.fields["path"] == "/eng/"
        assert node.fields["group_id"] == "AGPA2"
        assert node.fields["attached_policy_arns"] == sorted([AWS_POLICY_ARN, POLICY_ARN])

    def test_a_group_declares_no_tag_lane(self) -> None:
        assert _entry(GROUP)["tags"]["source"] == "none"


class TestInstanceProfiles:
    ARN = f"arn:aws:iam::{ACCOUNT}:instance-profile/web"
    ROLE = f"arn:aws:iam::{ACCOUNT}:role/web-role"

    def _iam(self, profile: dict[str, Any] | None = None) -> _Iam:
        return _Iam(
            list_instance_profiles={
                "InstanceProfiles": [
                    profile
                    or {
                        "InstanceProfileName": "web",
                        "Path": "/",
                        "InstanceProfileId": "AIPA1",
                        "Arn": self.ARN,
                        "CreateDate": WHEN,
                        "Roles": [
                            {
                                "RoleName": "web-role",
                                "Arn": self.ROLE,
                                "AssumeRolePolicyDocument": {"Statement": "TRUST-POLICY-CANARY"},
                            }
                        ],
                    }
                ],
                "IsTruncated": False,
            },
            get_account_summary={"SummaryMap": {"InstanceProfiles": 1}},
        )

    def test_the_embedded_role_is_cut_to_its_name_and_arn(self) -> None:
        items, walk = _run(iam_instance_profiles_listed, self._iam())
        assert items[0]["_role_arns"] == [self.ROLE]
        assert items[0][EDGE_READS] == {"_role_arns": COMPLETE}
        assert items[0]["Roles"] == [{"RoleName": "web-role", "Arn": self.ROLE}]
        assert "TRUST-POLICY-CANARY" not in json.dumps(items, default=str)
        assert (walk.complete, walk.count_reported) == (True, 1)

    def test_a_profile_with_no_role_has_an_empty_list_not_an_unknown_one(self) -> None:
        profile = {"InstanceProfileName": "bare", "Arn": f"{self.ARN}-2", "Roles": []}
        items, _ = _run(iam_instance_profiles_listed, self._iam(profile))
        assert items[0]["_role_arns"] == []
        assert items[0][EDGE_READS] == {"_role_arns": COMPLETE}

    def test_a_response_with_no_roles_list_is_not_read_as_no_role(self) -> None:
        profile = {"InstanceProfileName": "odd", "Arn": f"{self.ARN}-3"}
        items, _ = _run(iam_instance_profiles_listed, self._iam(profile))
        assert items[0]["_role_arns"] is None
        assert items[0][EDGE_READS] == {"_role_arns": PARTIAL}

    def test_the_manifest_entry_projects_the_profile(self) -> None:
        items, _ = _run(iam_instance_profiles_listed, self._iam())
        node = project_item(_entry(PROFILE), items[0])
        assert node.natural_key == self.ARN
        assert node.fields["instance_profile_id"] == "AIPA1"
        assert node.fields["role_arns"] == [self.ROLE]

    def test_the_tag_lane_is_the_service_read(self) -> None:
        tags = _entry(PROFILE)["tags"]
        assert (tags["source"], tags["op"]) == ("service", "ListInstanceProfileTags")


class TestSamlProviders:
    ARN = f"arn:aws:iam::{ACCOUNT}:saml-provider/Okta"

    def _iam(self, **over: Any) -> _Iam:
        canned: dict[str, Any] = {
            "list_saml_providers": {"SAMLProviderList": [{"Arn": self.ARN, "ValidUntil": WHEN, "CreateDate": WHEN}]},
            "get_saml_provider": {
                "SAMLProviderUUID": "u-1",
                "SAMLMetadataDocument": "<EntityDescriptor>METADATA-CANARY</EntityDescriptor>",
                "CreateDate": WHEN,
                "ValidUntil": WHEN,
                "Tags": [{"Key": "owner", "Value": "idp-team"}],
                "AssertionEncryptionMode": "Allowed",
                "PrivateKeyList": [{"KeyId": "k-1", "Timestamp": WHEN}],
            },
        }
        canned.update(over)
        return _Iam(**canned)

    def test_the_metadata_document_never_leaves_the_reader(self) -> None:
        items, walk = _run(iam_saml_providers_described, self._iam())
        assert "METADATA-CANARY" not in json.dumps(items, default=str)
        assert "SAMLMetadataDocument" not in items[0]
        assert (walk.complete, walk.count, walk.admitted) == (True, 1, True)

    def test_the_provider_is_named_and_dated(self) -> None:
        items, _ = _run(iam_saml_providers_described, self._iam())
        node = project_item(_entry(SAML), items[0])
        assert node.natural_key == self.ARN
        assert node.fields["name"] == "Okta"
        assert node.fields["valid_until"] == WHEN_TEXT
        assert node.fields["created_at"] == WHEN_TEXT

    def test_tags_come_from_the_inline_list(self) -> None:
        tags = _entry(SAML)["tags"]
        assert (tags["source"], tags["from"], tags["shape"]) == ("field", "Tags", "list_kv")

    def test_a_provider_that_cannot_be_described_is_dropped_and_clears_admitted(self) -> None:
        items, walk = _run(iam_saml_providers_described, self._iam(get_saml_provider=_denied("GetSAMLProvider")))
        assert items == []
        assert (walk.complete, walk.admitted) == (True, False)

    def test_a_provider_without_dates_reads_as_empty_text(self) -> None:
        bare = {"SAMLProviderUUID": "u-2"}
        items, _ = _run(iam_saml_providers_described, self._iam(get_saml_provider=bare))
        assert (items[0]["_valid_until"], items[0]["_created_at"]) == ("", "")


class TestServerCertificates:
    ARN = f"arn:aws:iam::{ACCOUNT}:server-certificate/legacy"

    def _iam(self) -> _Iam:
        return _Iam(
            list_server_certificates={
                "ServerCertificateMetadataList": [
                    {
                        "Path": "/",
                        "ServerCertificateName": "legacy",
                        "ServerCertificateId": "ASCA1",
                        "Arn": self.ARN,
                        "UploadDate": WHEN,
                        "Expiration": WHEN,
                    }
                ],
                "IsTruncated": False,
            },
            get_account_summary={"SummaryMap": {"ServerCertificates": 1}},
        )

    def test_only_the_metadata_list_is_read(self) -> None:
        iam = self._iam()
        items, walk = _run(iam_server_certificates_listed, iam)
        assert "get_server_certificate" not in iam.calls
        assert (walk.complete, walk.count_reported) == (True, 1)
        assert (items[0]["_expiration"], items[0]["_upload_date"]) == (WHEN_TEXT, WHEN_TEXT)

    def test_the_manifest_entry_projects_the_certificate(self) -> None:
        items, _ = _run(iam_server_certificates_listed, self._iam())
        node = project_item(_entry(CERT), items[0])
        assert node.natural_key == self.ARN
        assert node.fields["certificate_id"] == "ASCA1"
        assert node.fields["expiration"] == WHEN_TEXT
        assert node.fields["upload_date"] == WHEN_TEXT

    def test_the_tag_lane_is_the_service_read(self) -> None:
        tags = _entry(CERT)["tags"]
        assert (tags["source"], tags["op"]) == ("service", "ListServerCertificateTags")


class TestVirtualMfaDevices:
    ASSIGNED = f"arn:aws:iam::{ACCOUNT}:mfa/alice"
    SPARE = f"arn:aws:iam::{ACCOUNT}:mfa/spare"
    USER = f"arn:aws:iam::{ACCOUNT}:user/alice"

    def _iam(self) -> _Iam:
        return _Iam(
            list_virtual_mfa_devices={
                "VirtualMFADevices": [
                    {
                        "SerialNumber": self.ASSIGNED,
                        "Base32StringSeed": SEED_CANARY,
                        "QRCodePNG": QR_CANARY,
                        "User": {"UserName": "alice", "Arn": self.USER},
                        "EnableDate": WHEN,
                    },
                    {"SerialNumber": self.SPARE},
                ],
                "IsTruncated": False,
            }
        )

    def test_the_seed_and_qr_code_are_removed_whether_or_not_the_response_carries_them(self) -> None:
        items, _ = _run(iam_virtual_mfa_devices_listed, self._iam())
        assert "Base32StringSeed" not in items[0] and "QRCodePNG" not in items[0]
        assert SEED_CANARY not in json.dumps(items, default=str)
        assert QR_CANARY.decode() not in json.dumps(items, default=str)

    def test_an_unassigned_device_has_an_empty_user_arn(self) -> None:
        items, _ = _run(iam_virtual_mfa_devices_listed, self._iam())
        assert (items[0]["_user_arn"], items[1]["_user_arn"]) == (self.USER, "")
        assert items[0][EDGE_READS] == {"_user_arn": COMPLETE}
        assert (items[0]["_enable_date"], items[1]["_enable_date"]) == (WHEN_TEXT, "")

    def test_no_account_summary_control_is_taken(self) -> None:
        # MFADevices counts hardware tokens too, which this listing never returns.
        iam = self._iam()
        _, walk = _run(iam_virtual_mfa_devices_listed, iam)
        assert "get_account_summary" not in iam.calls
        assert (walk.complete, walk.count, walk.count_reported) == (True, 2, None)

    def test_the_manifest_entry_projects_the_device(self) -> None:
        items, _ = _run(iam_virtual_mfa_devices_listed, self._iam())
        node = project_item(_entry(MFA), items[0])
        assert node.natural_key == self.ASSIGNED
        assert node.fields["name"] == "alice"
        assert node.fields["user_arn"] == self.USER
        assert node.fields["enable_date"] == WHEN_TEXT

    def test_the_entry_stores_nothing_and_says_why(self) -> None:
        entry = _entry(MFA)
        assert entry["persist_configuration"] is False
        assert {loc["path"] for loc in entry["sensitivity"]["locations"] if loc["category"] == "credential"} == {
            "VirtualMFADevices[].Base32StringSeed",
            "VirtualMFADevices[].QRCodePNG",
        }

    def test_the_envelope_carries_no_configuration_and_no_canary(self) -> None:
        items, _ = _run(iam_virtual_mfa_devices_listed, self._iam())
        node = project_item(_entry(MFA), items[0])
        payload = node_envelope(node, {}, {}, persist_configuration=False)["node"]
        assert payload["configuration"] == {}
        assert SEED_CANARY not in json.dumps(payload, default=str)


def _projected_payload(entity_type: str, item: dict[str, Any]) -> dict[str, Any]:
    entry = _entry(entity_type)
    node = project_item(entry, item)
    return node_envelope(node, {}, {}, persist_configuration=entry["persist_configuration"])["node"]


class TestPayloadsSatisfyTheModelSchemas:
    """The offline half of the trial-run assertion: what the collector emits for each type imports
    under the model's create schema with ``additionalProperties: false``."""

    @pytest.mark.parametrize(
        ("entity_type", "fn", "iam"),
        [
            (GROUP, iam_groups_listed, TestGroups()._iam()),
            (PROFILE, iam_instance_profiles_listed, TestInstanceProfiles()._iam()),
            (SAML, iam_saml_providers_described, TestSamlProviders()._iam()),
            (CERT, iam_server_certificates_listed, TestServerCertificates()._iam()),
            (MFA, iam_virtual_mfa_devices_listed, TestVirtualMfaDevices()._iam()),
        ],
        ids=lambda v: v if isinstance(v, str) else "",
    )
    def test_payload_imports(self, entity_type: str, fn: Any, iam: _Iam) -> None:
        import jsonschema
        from django.apps import apps

        model = next(m for m in apps.get_app_config("aws_core").get_models() if getattr(m, "ENTITY_TYPE", "") == entity_type)
        items, _ = _run(fn, iam)
        schema = _create_verb_schema(model)
        for item in items:
            payload = _prepare_null_payload(_projected_payload(entity_type, item), schema)
            jsonschema.validate(payload, schema)
            assert payload["tags"] == {}


class TestDeclarations:
    NEW = (GROUP, PROFILE, SAML, CERT, MFA)

    def test_every_new_entry_validates_and_is_global(self) -> None:
        for entity_type in self.NEW:
            entry = _entry(entity_type)
            assert entry["service"] == "iam" and entry["scope"] == "global"

    def test_a_containment_edge_is_declared_exactly_where_a_get_call_can_judge_the_type(self) -> None:
        contained = {t for t in self.NEW if _entry(t).get("containment")}
        assert contained == {GROUP, PROFILE, SAML, CERT}

    def test_each_edge_rule_names_a_declared_edge_type_that_allows_the_pair(self) -> None:
        for entity_type in self.NEW:
            for rule in _entry(entity_type)["edges"]:
                edge = _edge_json(rule["edge_type"])
                assert entity_type in edge["sources"], (entity_type, rule["edge_type"])
                assert rule["target_type"] in edge["targets"], (entity_type, rule["edge_type"])

    def test_each_containment_edge_runs_from_the_account_to_its_type(self) -> None:
        for entity_type in (GROUP, PROFILE, SAML, CERT):
            edge = _edge_json(_entry(entity_type)["containment"]["edge_type"])
            assert (edge["sources"], edge["targets"]) == (["aws_core__aws_account"], [entity_type])


def _edge_json(slug: str) -> dict[str, Any]:
    path = Path(__file__).resolve().parent.parent / "edges" / f"{slug.removesuffix('__aws_core')}.edge.json"
    return json.loads(path.read_text())  # type: ignore[no-any-return]
