"""IAM credential hygiene (aws-core-tap#282, ``req-aws-core-iam-credentials``): every user's access keys, SSH public
keys, signing certificates and service-specific credentials as nodes contained by the user, the per-user surfaces,
the four falsifiers, the credential report and the root user, the account password policy and the user's login
profile, and the gated ``GenerateCredentialReport``.

Fake IAM clients, no network. Every id below is made up: no access key id is real, and the account is AWS's
documentation example.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import jsonschema
import pytest
from botocore.exceptions import ClientError
from tap_plugin.aws_core.collectors.boto3_collector import iam_credentials as ic
from tap_plugin.aws_core.collectors.boto3_collector import iam_policy
from tap_plugin.aws_core.collectors.boto3_collector.authority import COMPLETE, EDGE_READS
from tap_plugin.aws_core.collectors.boto3_collector.batch import node_envelope
from tap_plugin.aws_core.collectors.boto3_collector.credentials import AWS_ASSUMED_ROLE_SCHEMA, AWS_STATIC_SCHEMA
from tap_plugin.aws_core.collectors.boto3_collector.customfns import (
    build_custom_fn_registry,
    iam_root_user_from_credential_report,
    iam_users_described,
)
from tap_plugin.aws_core.collectors.boto3_collector.listing import surface_statement
from tap_plugin.aws_core.collectors.boto3_collector.manifest import manifest_entries
from tap_plugin.aws_core.collectors.boto3_collector.projection import project_item
from tap_plugin.aws_core.collectors.boto3_collector.source import iter_source
from tap_plugin.aws_core.falsifiers import (
    IamAccessKeyFalsifier,
    IamServiceSpecificCredentialFalsifier,
    IamSigningCertificateFalsifier,
    IamSshPublicKeyFalsifier,
)
from tap_plugin.aws_core.tests.grid_dimensions import stamp_dimensions
from tap_plugin.aws_core.tests.test_trial_run_live import _create_verb_schema, _prepare_null_payload

from tap_grid.falsifiers import DROPPED_FROM_OBSERVATION, PRESENT_AT_PROBE, UNDETERMINED, Candidate, FalsifyContext
from tap_grid.services import create_node, get_node

ACCOUNT = "111122223333"
OTHER_ACCOUNT = "444455556666"
ALICE = f"arn:aws:iam::{ACCOUNT}:user/alice"
BOB = f"arn:aws:iam::{ACCOUNT}:user/eng/bob"
WHEN = datetime(2026, 10, 1, 12, 30, tzinfo=UTC)
WHEN_TEXT = "2026-10-01T12:30:00Z"
LATER = datetime(2027, 10, 1, 12, 30, tzinfo=UTC)
#: Obviously fake ids, in AWS's shapes.
KEY_A = "AKIAFAKEFAKEFAKE0001"
KEY_B = "AKIAFAKEFAKEFAKE0002"
SSH_KEY = "APKAFAKEFAKEFAKE0001"
CERT_ID = "FAKECERTIFICATEID0001"
SVC_ID = "ACCAFAKEFAKEFAKE0001"
BODY_CANARY = "-----BEGIN CERTIFICATE-----TAPCANARYCERTBODY"
#: A key body planted in GetSSHPublicKey's answer: it must never leave the walk (ruling Q150a).
SSH_BODY_CANARY = "ssh-ed25519 TAPCANARYSSHKEYBODY"
FINGERPRINT = "aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99"

ACCESS_KEY = ic.ACCESS_KEY_TYPE
SSH = ic.SSH_PUBLIC_KEY_TYPE
CERT = ic.SIGNING_CERTIFICATE_TYPE
SVC = ic.SERVICE_CREDENTIAL_TYPE
ROOT = ic.ROOT_USER_TYPE
USER = ic.USER_TYPE
NEW_TYPES = (ACCESS_KEY, SSH, CERT, SVC)


def _error(code: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, op)


class _Iam:
    """A fake IAM client: a method answers with its canned value, raises it if it is an exception, and calls it if it
    is callable (with the request's keyword arguments). A method nobody canned fails the test that called it."""

    def __init__(self, **canned: Any) -> None:
        self._canned = canned
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def can_paginate(self, method: str) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def call(**kwargs: Any) -> Any:
            self.calls.append((name, kwargs))
            if name not in self._canned:
                raise AssertionError(f"{name} was not expected")
            value = self._canned[name]
            if isinstance(value, Exception):
                raise value
            return value(**kwargs) if callable(value) else value

        return call

    def called(self, name: str) -> list[dict[str, Any]]:
        return [kwargs for method, kwargs in self.calls if method == name]


def _per_user(table: dict[str, Any]) -> Any:
    """A listing answered per user name: ``table[UserName]`` (an answer or an exception), else an empty listing."""

    def answer(UserName: str, **_kw: Any) -> Any:
        value = table.get(UserName, {})
        if isinstance(value, Exception):
            raise value
        return value

    return answer


def _iam(**over: Any) -> _Iam:
    """Two users: alice holds one active and one inactive key, an SSH key, a signing certificate and a Bedrock API
    key; bob holds nothing."""
    canned: dict[str, Any] = {
        "list_users": {
            "Users": [{"UserName": "alice", "Arn": ALICE, "Path": "/"}, {"UserName": "bob", "Arn": BOB, "Path": "/eng/"}],
            "IsTruncated": False,
        },
        "list_access_keys": _per_user(
            {
                "alice": {
                    "AccessKeyMetadata": [
                        {"UserName": "alice", "AccessKeyId": KEY_A, "Status": "Active", "CreateDate": WHEN},
                        {"UserName": "alice", "AccessKeyId": KEY_B, "Status": "Inactive", "CreateDate": WHEN},
                    ],
                    "IsTruncated": False,
                }
            }
        ),
        "get_access_key_last_used": lambda AccessKeyId: (
            {"UserName": "alice", "AccessKeyLastUsed": {"LastUsedDate": WHEN, "ServiceName": "s3", "Region": "us-east-1"}}
            if AccessKeyId == KEY_A
            else {"UserName": "alice", "AccessKeyLastUsed": {"ServiceName": "N/A", "Region": "N/A"}}
        ),
        "list_ssh_public_keys": _per_user(
            {"alice": {"SSHPublicKeys": [{"UserName": "alice", "SSHPublicKeyId": SSH_KEY, "Status": "Active", "UploadDate": WHEN}]}}
        ),
        "get_ssh_public_key": lambda UserName, SSHPublicKeyId, Encoding: {
            "SSHPublicKey": {
                "UserName": UserName,
                "SSHPublicKeyId": SSHPublicKeyId,
                "Fingerprint": FINGERPRINT,
                "SSHPublicKeyBody": SSH_BODY_CANARY,
                "Status": "Active",
                "UploadDate": WHEN,
            }
        },
        "list_signing_certificates": _per_user(
            {
                "alice": {
                    "Certificates": [
                        {"UserName": "alice", "CertificateId": CERT_ID, "CertificateBody": BODY_CANARY, "Status": "Active", "UploadDate": WHEN}
                    ]
                }
            }
        ),
        "list_service_specific_credentials": _per_user(
            {
                "alice": {
                    "ServiceSpecificCredentials": [
                        {
                            "UserName": "alice",
                            "Status": "Active",
                            "ServiceUserName": f"alice-at-{ACCOUNT}",
                            "ServiceCredentialAlias": "bedrock-key",
                            "CreateDate": WHEN,
                            "ExpirationDate": LATER,
                            "ServiceSpecificCredentialId": SVC_ID,
                            "ServiceName": "bedrock.amazonaws.com",
                        }
                    ]
                }
            }
        ),
    }
    canned.update(over)
    return _Iam(**canned)


def _entry(entity_type: str) -> dict[str, Any]:
    return next(e for e in manifest_entries() if e["entity_type"] == entity_type)


def _surfaces(walk: ic.CredentialWalk) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (listing.user_arn, listing.edge_type): surface_statement(
            listing.walk, relation=listing.relation, edge_type=listing.edge_type, subject="s", applied_batches=[]
        )
        for listing in walk.listings
    }


def _items(entity_type: str, iam: _Iam, *, session: Any = None) -> list[dict[str, Any]]:
    """The entry's items as the engine drives them: the custom function, then its ``derive`` keys."""
    entry = _entry(entity_type)
    return list(
        iter_source(
            entry,
            client_for=lambda service: iam,
            custom_fns=build_custom_fn_registry(),
            fn_context=session,
            account_id=ACCOUNT,
            scope={"partition": "aws", "region": "us-east-1", "account": ACCOUNT},
        )
    )


def _payload(entity_type: str, item: dict[str, Any]) -> dict[str, Any]:
    entry = _entry(entity_type)
    node = project_item(entry, item)
    return node_envelope(node, {}, {}, persist_configuration=entry["persist_configuration"])["node"]


def _model(entity_type: str) -> type:
    from tap_grid.registry import get_model_class

    return get_model_class(entity_type)


# --- containment ------------------------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-iam-credentials-3", "req-aws-core-contained-type-triple-1")
class TestContainment:
    def test_the_walk_records_a_surface_for_every_containment_edge_the_user_declares(self) -> None:
        assert tuple(_model(USER).CONTAINMENT_EDGES) == ic.CONTAINMENT_SURFACES[USER]
        assert set(ic.CONTAINMENT_SURFACES) == {USER}

    def test_each_edge_runs_from_the_user_to_its_one_type(self) -> None:
        for kind in ic.KINDS.values():
            path = Path(__file__).resolve().parent.parent / "edges" / f"{kind.edge_type.removesuffix('__aws_core')}.edge.json"
            edge = json.loads(path.read_text())
            assert (edge["sources"], edge["targets"]) == ([USER], [kind.entity_type])

    def test_each_entry_emits_its_containment_edge_inbound_from_the_user(self) -> None:
        for entity_type in NEW_TYPES:
            assert _entry(entity_type)["edges"] == [
                {
                    "value_path": "_user_arn",
                    "target_type": USER,
                    "key_kind": "arn",
                    "edge_type": ic.KINDS[entity_type].edge_type,
                    "direction": "inbound",
                }
            ]

    def test_each_type_has_a_falsifier_registered(self) -> None:
        import tomllib

        manifest = tomllib.loads((Path(__file__).resolve().parent.parent / "tap-plugin.toml").read_text())
        assert {t: manifest["falsifiers"][t].rsplit(".", 1)[-1] for t in NEW_TYPES} == {
            ACCESS_KEY: "IamAccessKeyFalsifier",
            SSH: "IamSshPublicKeyFalsifier",
            CERT: "IamSigningCertificateFalsifier",
            SVC: "IamServiceSpecificCredentialFalsifier",
        }


# --- the walk ----------------------------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-iam-credentials-3")
class TestWalk:
    def test_every_user_has_a_surface_per_kind_and_an_empty_one_is_complete(self) -> None:
        surfaces = _surfaces(ic.walk_credentials(_iam()))
        assert len(surfaces) == 8
        assert surfaces[(ALICE, "HOLDS_ACCESS_KEY__aws_core")]["enumeration_complete"] is True
        assert surfaces[(ALICE, "HOLDS_ACCESS_KEY__aws_core")]["count_observed"] == 2
        for kind in ic.KINDS.values():
            bob = surfaces[(BOB, kind.edge_type)]
            assert (bob["enumeration_complete"], bob["count_observed"], bob["admitted"]) == (True, 0, True), kind
            assert bob["relation"] == kind.relation

    def test_each_listing_is_asked_per_user_by_name(self) -> None:
        iam = _iam()
        ic.walk_credentials(iam)
        assert [c["UserName"] for c in iam.called("list_service_specific_credentials")] == ["alice", "bob"]
        # No service filter: every service's credentials are listed.
        assert all("ServiceName" not in c for c in iam.called("list_service_specific_credentials"))

    def test_a_denied_listing_is_incomplete_and_contributes_nothing(self) -> None:
        iam = _iam(list_access_keys=_per_user({"alice": _error("AccessDenied", "ListAccessKeys")}))
        walk = ic.walk_credentials(iam)
        surface = _surfaces(walk)[(ALICE, "HOLDS_ACCESS_KEY__aws_core")]
        assert (surface["enumeration_complete"], surface["scope_authorized"], surface["admitted"]) == (False, False, False)
        assert walk.items[ACCESS_KEY] == []
        # The other kinds of the same user are unaffected.
        assert [i["SSHPublicKeyId"] for i in walk.items[SSH]] == [SSH_KEY]

    def test_a_short_listing_is_incomplete_and_contributes_nothing(self) -> None:
        short = {"AccessKeyMetadata": [{"AccessKeyId": KEY_A, "Status": "Active"}], "IsTruncated": True, "Marker": "m"}
        walk = ic.walk_credentials(_iam(list_access_keys=_per_user({"alice": short})))
        surface = _surfaces(walk)[(ALICE, "HOLDS_ACCESS_KEY__aws_core")]
        assert (surface["enumeration_complete"], surface["admitted"]) == (False, False)
        assert walk.items[ACCESS_KEY] == []

    def test_an_entry_without_its_id_is_dropped_and_clears_admitted(self) -> None:
        listing = {"SSHPublicKeys": [{"UserName": "alice", "Status": "Active"}]}
        walk = ic.walk_credentials(_iam(list_ssh_public_keys=_per_user({"alice": listing})))
        assert walk.items[SSH] == []
        assert _surfaces(walk)[(ALICE, "HOLDS_SSH_PUBLIC_KEY__aws_core")]["admitted"] is False

    @pytest.mark.spec("req-aws-core-iam-credentials-11")
    def test_a_signing_certificates_public_body_is_kept_in_configuration(self) -> None:
        """Ruling Q150b: the certificate is public, and its notAfter is the certificate's end."""
        (item,) = ic.walk_credentials(_iam()).items[CERT]
        assert item["CertificateBody"] == BODY_CANARY
        payload = _payload(CERT, _items(CERT, _iam())[0])
        assert payload["configuration"]["CertificateBody"] == BODY_CANARY

    @pytest.mark.spec("req-aws-core-iam-credentials-2", "req-aws-core-iam-credentials-10")
    def test_an_ssh_key_body_never_leaves_the_walk_and_its_fingerprint_does(self) -> None:
        """Ruling Q150a: GetSSHPublicKey (Encoding SSH) per key; the fingerprint is kept, the body never stored."""
        iam = _iam()
        (item,) = ic.walk_credentials(iam).items[SSH]
        assert iam.called("get_ssh_public_key") == [{"UserName": "alice", "SSHPublicKeyId": SSH_KEY, "Encoding": "SSH"}]
        assert SSH_BODY_CANARY not in json.dumps(item, default=str)
        assert item["_fingerprint"] == FINGERPRINT
        payload = _payload(SSH, _items(SSH, _iam())[0])
        assert SSH_BODY_CANARY not in json.dumps(payload, default=str)
        assert payload["fingerprint"] == FINGERPRINT
        assert payload["configuration"]["_hydrate"]["public_key"]["data"]["SSHPublicKey"]["Fingerprint"] == FINGERPRINT

    @pytest.mark.spec("req-aws-core-iam-credentials-10")
    def test_an_unanswered_ssh_key_read_leaves_the_fingerprint_unread(self) -> None:
        walk = ic.walk_credentials(_iam(get_ssh_public_key=_error("AccessDenied", "GetSSHPublicKey")))
        (item,) = walk.items[SSH]
        assert item["_fingerprint"] is None
        assert item["_hydrate"]["public_key"]["status"] == "denied"
        # The listing still answered: the key is a node and the user's surface is complete.
        assert _surfaces(walk)[(ALICE, "HOLDS_SSH_PUBLIC_KEY__aws_core")]["enumeration_complete"] is True

    @pytest.mark.spec("req-aws-core-iam-credentials-2")
    def test_no_create_or_reset_call_is_made(self) -> None:
        iam = _iam()
        ic.walk_credentials(iam)
        assert not [m for m, _ in iam.calls if m.startswith(("create_", "reset_", "update_", "delete_", "upload_"))]

    def test_an_access_keys_last_use_is_read_and_never_used_is_an_answer(self) -> None:
        walk = ic.walk_credentials(_iam())
        used, unused = walk.items[ACCESS_KEY]
        assert (used["_last_used_date"], used["_last_used_service"], used["_last_used_region"]) == (WHEN_TEXT, "s3", "us-east-1")
        assert (unused["_last_used_date"], unused["_last_used_service"], unused["_last_used_region"]) == ("", "N/A", "N/A")

    def test_an_unanswered_last_use_is_unread_and_a_gap(self) -> None:
        walk = ic.walk_credentials(_iam(get_access_key_last_used=_error("AccessDenied", "GetAccessKeyLastUsed")))
        item = walk.items[ACCESS_KEY][0]
        assert (item["_last_used_date"], item["_last_used_service"], item["_last_used_region"]) == (None, None, None)
        assert item["_hydrate"]["last_used"]["status"] == "denied"

    def test_list_users_failing_raises_and_is_not_retried(self) -> None:
        class _Session:
            pass

        session, iam = _Session(), _iam(list_users=_error("AccessDenied", "ListUsers"))
        for _ in range(2):
            with pytest.raises(ClientError):
                ic.shared_walk(session, iam)
        assert len(iam.called("list_users")) == 1 and ic.walk_of(session) is None

    def test_the_walk_is_made_once_per_session_for_all_four_readers(self) -> None:
        class _Session:
            pass

        session, iam = _Session(), _iam()
        for entity_type in NEW_TYPES:
            _items(entity_type, iam, session=session)
        assert len(iam.called("list_users")) == 1
        walk = ic.walk_of(session)
        assert walk is not None and walk.projected == set(NEW_TYPES)
        assert all(listing.walk.admitted for listing in walk.surface_listings())

    def test_a_kind_whose_reader_did_not_finish_licenses_no_retirement(self) -> None:
        class _Session:
            pass

        session, iam = _Session(), _iam()
        _items(ACCESS_KEY, iam, session=session)
        walk = ic.walk_of(session)
        assert walk is not None
        admitted = {(listing.user_arn, listing.edge_type): listing.walk.admitted for listing in walk.surface_listings()}
        assert admitted[(BOB, "HOLDS_ACCESS_KEY__aws_core")] is True
        assert admitted[(BOB, "HOLDS_SSH_PUBLIC_KEY__aws_core")] is False


# --- the readers and their entries --------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-iam-credentials-1")
class TestReaders:
    def test_an_access_key_projects_its_key_its_user_and_its_use(self) -> None:
        items = _items(ACCESS_KEY, _iam())
        node = project_item(_entry(ACCESS_KEY), items[0])
        assert node.natural_key == f"aws:{ACCOUNT}:global:{KEY_A}"
        assert {k: node.fields[k] for k in ("partition", "account_id", "access_key_id")} == {
            "partition": "aws",
            "account_id": ACCOUNT,
            "access_key_id": KEY_A,
        }
        assert (node.fields["user_name"], node.fields["user_arn"], node.fields["status"]) == ("alice", ALICE, "Active")
        assert (node.fields["create_date"], node.fields["last_used_date"], node.fields["last_used_service"]) == (WHEN_TEXT, WHEN_TEXT, "s3")
        assert items[0][EDGE_READS] == {"_user_arn": COMPLETE}

    def test_the_other_three_project_their_ids_and_times(self) -> None:
        ssh = project_item(_entry(SSH), _items(SSH, _iam())[0])
        assert (ssh.fields["ssh_public_key_id"], ssh.fields["upload_date"], ssh.fields["fingerprint"]) == (
            SSH_KEY,
            WHEN_TEXT,
            FINGERPRINT,
        )
        cert = project_item(_entry(CERT), _items(CERT, _iam())[0])
        assert (cert.fields["certificate_id"], cert.fields["upload_date"]) == (CERT_ID, WHEN_TEXT)
        svc = project_item(_entry(SVC), _items(SVC, _iam())[0])
        assert {k: svc.fields[k] for k in ("service_specific_credential_id", "service_name", "create_date", "expiration_date")} == {
            "service_specific_credential_id": SVC_ID,
            "service_name": "bedrock.amazonaws.com",
            "create_date": WHEN_TEXT,
            "expiration_date": "2027-10-01T12:30:00Z",
        }

    def test_a_govcloud_key_is_keyed_under_its_partition(self) -> None:
        entry = _entry(ACCESS_KEY)
        (item, *_) = list(
            iter_source(
                entry,
                client_for=lambda service: _iam(),
                custom_fns=build_custom_fn_registry(),
                account_id=ACCOUNT,
                scope={"partition": "aws-us-gov", "region": "us-gov-west-1", "account": ACCOUNT},
            )
        )
        assert project_item(entry, item).natural_key == f"aws-us-gov:{ACCOUNT}:global:{KEY_A}"

    @pytest.mark.parametrize("entity_type", NEW_TYPES)
    def test_payload_imports_under_the_create_schema(self, entity_type: str) -> None:
        model = _model(entity_type)
        schema = _create_verb_schema(model)
        for item in _items(entity_type, _iam()):
            payload = _prepare_null_payload(_payload(entity_type, item), schema)
            jsonschema.validate(payload, schema)
            assert payload["tags"] == {}

    @pytest.mark.parametrize("entity_type", NEW_TYPES)
    def test_the_declarations(self, entity_type: str) -> None:
        entry = _entry(entity_type)
        assert (entry["service"], entry["scope"], entry["persist_configuration"]) == ("iam", "global", True)
        assert entry["tags"]["source"] == "none"
        assert entry["derive"]["_key"].startswith("{partition}:{account}:global:")
        assert _model(entity_type).NATURAL_KEY[:2] == ("partition", "account_id")
        # The user name is personal data wherever the item carries it (ruling Q143e).
        personal = {loc["path"] for loc in entry["sensitivity"]["locations"] if loc["category"] == "personal_data"}
        assert {"UserName", "_user_name", "_user_arn"} <= personal

    def test_only_the_access_key_follows_a_cloudformation_type(self) -> None:
        identities = {t: _entry(t)["identity"] for t in NEW_TYPES}
        assert identities[ACCESS_KEY] == {
            "cfn_type": "AWS::IAM::AccessKey",
            "key": {"partition": "@partition", "account_id": "@account", "access_key_id": "Id"},
        }
        assert all(identities[t]["cfn_type"] is None and identities[t]["reason"] for t in (SSH, CERT, SVC))

    def test_each_credential_type_carries_its_kind_on_the_credential_dimension(self) -> None:
        """Ruling Q146: computing_core's ``tap.computing.credential``, the kind of credential; nothing else is tagged."""
        assert {t: _model(t).DEFAULT_DIMENSIONS for t in NEW_TYPES} == {
            ACCESS_KEY: {"tap.computing.cloud": "aws", "tap.computing.credential": "access_key"},
            SSH: {"tap.computing.cloud": "aws", "tap.computing.credential": "ssh_key"},
            CERT: {"tap.computing.cloud": "aws", "tap.computing.credential": "certificate"},
            SVC: {"tap.computing.cloud": "aws", "tap.computing.credential": "password"},
        }
        for entity_type in (ROOT, USER, "aws_core__aws_account"):
            assert "tap.computing.credential" not in _model(entity_type).DEFAULT_DIMENSIONS, entity_type


# --- login profile ------------------------------------------------------------------------------------------------------


def _user_item(login_profile: Any) -> dict[str, Any]:
    user = {"UserName": "alice", "Arn": ALICE}
    iam = _Iam(
        list_users={"Users": [user], "IsTruncated": False},
        get_account_summary={"SummaryMap": {"Users": 1}},
        get_user={"User": user},
        list_attached_user_policies={"AttachedPolicies": [], "IsTruncated": False},
        list_mfa_devices={"MFADevices": []},
        get_login_profile=login_profile,
    )
    return next(iter(iam_users_described(None, client_for=lambda _svc: iam)))


@pytest.mark.spec("req-aws-core-iam-credentials-7")
class TestLoginProfile:
    def test_a_login_profile_is_read_never_its_password(self) -> None:
        item = _user_item({"LoginProfile": {"UserName": "alice", "CreateDate": WHEN, "PasswordResetRequired": True}})
        assert (item["_login_profile_exists"], item["_login_profile_created_at"], item["_password_reset_required"]) == (
            True,
            WHEN_TEXT,
            True,
        )
        fields = project_item(_entry(USER), item).fields
        assert (fields["login_profile_exists"], fields["password_reset_required"]) == (True, True)

    def test_no_such_entity_is_no_console_password(self) -> None:
        item = _user_item(_error("NoSuchEntity", "GetLoginProfile"))
        assert (item["_login_profile_exists"], item["_login_profile_created_at"], item["_password_reset_required"]) == (False, "", None)

    def test_a_denied_read_is_unread_not_no_password(self) -> None:
        item = _user_item(_error("AccessDenied", "GetLoginProfile"))
        assert (item["_login_profile_exists"], item["_login_profile_created_at"], item["_password_reset_required"]) == (None, None, None)


# --- the account's posture ------------------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-core-iam-credentials-6")
class TestAccountPosture:
    def _account_item(self, policy: Any, report: Any) -> dict[str, Any]:
        from tap_plugin.aws_core.collectors.boto3_collector.customfns import aws_account_singleton

        sts = _Iam(get_caller_identity={"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/collector", "UserId": "AIDAFAKE"})
        iam = _Iam(list_account_aliases={"AccountAliases": []}, get_account_password_policy=policy, get_credential_report=report)
        org = _Iam(describe_account=_error("AccessDeniedException", "DescribeAccount"))
        clients = {"sts": sts, "iam": iam, "organizations": org}
        return next(iter(aws_account_singleton(None, client_for=clients.__getitem__)))

    def test_the_password_policy_lands_on_the_account(self) -> None:
        policy = {"PasswordPolicy": {"MinimumPasswordLength": 14, "RequireSymbols": True, "ExpirePasswords": False, "PasswordReusePrevention": 24}}
        item = self._account_item(policy, _error("ReportNotPresent", "GetCredentialReport"))
        fields = project_item(_entry("aws_core__aws_account"), item).fields
        assert (fields["password_policy_present"], fields["password_minimum_length"], fields["password_require_symbols"]) == (True, 14, True)
        assert (fields["password_reuse_prevention"], fields["password_expire_passwords"]) == (24, False)
        # HardExpiry absent from AWS's answer stays unstated, not false.
        assert fields["password_hard_expiry"] is None

    def test_no_policy_is_distinct_from_an_unread_one(self) -> None:
        absent = project_item(_entry("aws_core__aws_account"), self._account_item(_error("NoSuchEntity", "GetAccountPasswordPolicy"), _error("ReportNotPresent", "x"))).fields
        unread = project_item(_entry("aws_core__aws_account"), self._account_item(_error("AccessDenied", "GetAccountPasswordPolicy"), _error("ReportNotPresent", "x"))).fields
        assert (absent["password_policy_present"], absent["password_minimum_length"]) == (False, None)
        assert (unread["password_policy_present"], unread["password_minimum_length"]) == (None, None)

    def test_the_account_payload_imports(self) -> None:
        policy = {"PasswordPolicy": {"MinimumPasswordLength": 14}}
        item = self._account_item(policy, _error("ReportExpired", "GetCredentialReport"))
        schema = _create_verb_schema(_model("aws_core__aws_account"))
        payload = _prepare_null_payload(_payload("aws_core__aws_account", item), schema)
        jsonschema.validate(payload, schema)
        assert (payload["credential_report_state"], payload["credential_report_generated_at"]) == ("expired", "")


# --- the credential report and the root user ------------------------------------------------------------------------------

_REPORT = (
    "user,arn,user_creation_time,password_enabled,password_last_used,password_last_changed,password_next_rotation,"
    "mfa_active,access_key_1_active,access_key_1_last_rotated,access_key_1_last_used_date,access_key_1_last_used_region,"
    "access_key_1_last_used_service,access_key_2_active,access_key_2_last_rotated,access_key_2_last_used_date,"
    "access_key_2_last_used_region,access_key_2_last_used_service,cert_1_active,cert_1_last_rotated,cert_2_active,"
    "cert_2_last_rotated\n"
    f"<root_account>,arn:aws:iam::{ACCOUNT}:root,2019-03-14T20:36:05+00:00,not_supported,2026-11-01T09:00:00+00:00,"
    "not_supported,not_supported,true,false,N/A,N/A,N/A,N/A,false,N/A,N/A,N/A,N/A,false,N/A,false,N/A\n"
    f"alice,{ALICE},2024-01-01T00:00:00+00:00,false,N/A,N/A,N/A,false,true,2024-01-01T00:00:00+00:00,"
    "2026-11-20T00:00:00+00:00,us-east-1,s3,false,N/A,N/A,N/A,N/A,false,N/A,false,N/A\n"
)


def _report_iam(**over: Any) -> _Iam:
    canned: dict[str, Any] = {
        "get_credential_report": {"Content": _REPORT.encode(), "ReportFormat": "text/csv", "GeneratedTime": WHEN},
        "generate_credential_report": {"State": "COMPLETE"},
    }
    canned.update(over)
    return _Iam(**canned)


@pytest.mark.spec("req-aws-core-iam-credentials-5", "req-aws-core-secret-credential-report-1")
class TestCredentialReport:
    def test_with_the_option_off_the_report_is_read_and_never_generated(self) -> None:
        iam = _report_iam()
        report = ic.read_credential_report(iam, generate=False)
        assert iam.called("generate_credential_report") == []
        assert (report.state, report.generated_at, report.generate_requested) == ("present", WHEN_TEXT, False)

    def test_a_session_nobody_configured_never_generates(self) -> None:
        class _Session:
            pass

        iam = _report_iam()
        ic.shared_report(_Session(), iam)
        assert iam.called("generate_credential_report") == []

    def test_with_the_option_on_the_report_is_generated_first(self) -> None:
        class _Session:
            pass

        session = _Session()
        states = iter(["STARTED", "COMPLETE"])
        iam = _report_iam(generate_credential_report=lambda: {"State": next(states)})
        ic.configure(session, generate=True)
        # One wait between the two polls; the injected sleep keeps the test instant.
        report = ic.read_credential_report(iam, generate=True, sleep=lambda _s: None)
        assert [m for m, _ in iam.calls] == ["generate_credential_report", "generate_credential_report", "get_credential_report"]
        assert report.generate_requested and report.state == "present"

    def test_a_denied_generation_still_reads_what_exists(self) -> None:
        iam = _report_iam(generate_credential_report=_error("AccessDenied", "GenerateCredentialReport"))
        report = ic.read_credential_report(iam, generate=True, sleep=lambda _s: None)
        assert report.generate_error is not None and report.state == "present"

    @pytest.mark.parametrize(
        ("code", "state"), [("ReportNotPresent", "not_present"), ("ReportExpired", "expired"), ("ReportInProgress", "in_progress")]
    )
    def test_no_report_is_a_state_not_a_failure(self, code: str, state: str) -> None:
        report = ic.read_credential_report(_report_iam(get_credential_report=_error(code, "GetCredentialReport")), generate=False)
        assert (report.state, report.generated_at, report.error) == (state, "", None)
        assert ic.root_item(report) is None

    def test_a_denied_read_is_not_read(self) -> None:
        report = ic.read_credential_report(_report_iam(get_credential_report=_error("AccessDenied", "GetCredentialReport")), generate=False)
        assert (report.state, report.generated_at) == (None, None) and report.error is not None

    @pytest.mark.spec("req-aws-core-iam-credentials-8")
    def test_the_root_row_becomes_the_root_user(self) -> None:
        (item,) = list(iam_root_user_from_credential_report(None, client_for=lambda _svc: _report_iam()))
        fields = project_item(_entry(ROOT), item).fields
        assert project_item(_entry(ROOT), item).natural_key == f"arn:aws:iam::{ACCOUNT}:root"
        assert fields["created_at"] == "2019-03-14T20:36:05+00:00"
        assert (fields["password_enabled"], fields["password_last_used"], fields["mfa_active"]) == (None, "2026-11-01T09:00:00+00:00", True)
        assert (fields["access_key_1_active"], fields["access_key_1_last_used_date"], fields["cert_2_active"]) == (False, "", False)
        assert fields["report_generated_at"] == WHEN_TEXT
        # Only the root row: no other user's name reaches the item.
        assert "alice" not in json.dumps(item)

    @pytest.mark.spec("req-aws-core-iam-credentials-8")
    def test_the_root_payload_imports(self) -> None:
        (item,) = list(iam_root_user_from_credential_report(None, client_for=lambda _svc: _report_iam()))
        schema = _create_verb_schema(_model(ROOT))
        payload = _prepare_null_payload(_payload(ROOT, item), schema)
        jsonschema.validate(payload, schema)

    @pytest.mark.spec("req-aws-core-iam-credentials-8")
    def test_no_report_yields_no_root_and_an_unreadable_one_fails_the_entry(self) -> None:
        absent = _report_iam(get_credential_report=_error("ReportNotPresent", "GetCredentialReport"))
        assert list(iam_root_user_from_credential_report(None, client_for=lambda _svc: absent)) == []
        denied = _report_iam(get_credential_report=_error("AccessDenied", "GetCredentialReport"))
        with pytest.raises(ClientError):
            list(iam_root_user_from_credential_report(None, client_for=lambda _svc: denied))


@pytest.mark.spec("req-aws-core-secret-credential-report-2")
class TestOption:
    def test_both_kinds_take_the_option_and_refuse_a_non_boolean(self) -> None:
        for schema, base in (
            (AWS_STATIC_SCHEMA, {"access_key_id": "x", "secret_access_key": "y"}),
            (
                AWS_ASSUMED_ROLE_SCHEMA,
                {
                    "role_arn": f"arn:aws:iam::{ACCOUNT}:role/r",
                    "external_id": "e",
                    "base": {"access_key_id": "x", "secret_access_key": "y"},
                },
            ),
        ):
            jsonschema.validate({**base, "generate_credential_report": True}, schema)
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate({**base, "generate_credential_report": "yes"}, schema)
        assert AWS_STATIC_SCHEMA["properties"]["generate_credential_report"] is AWS_ASSUMED_ROLE_SCHEMA["properties"]["generate_credential_report"]

    def test_absent_and_false_are_off(self) -> None:
        assert (ic.generate_enabled({}), ic.generate_enabled({"generate_credential_report": False})) == (False, False)
        assert ic.generate_enabled({"generate_credential_report": True}) is True


# --- the generated policy -------------------------------------------------------------------------------------------------


@pytest.mark.spec("req-aws-collector-iam-policy-2")
class TestPolicy:
    def _allowed(self) -> set[str]:
        return {
            action
            for path in sorted(iam_policy.OUT_DIR.glob("collector-policy-*.json"))
            for statement in json.loads(path.read_text())["Statement"]
            if statement["Effect"] == "Allow"
            for action in statement["Action"]
        }

    def test_the_new_reads_are_granted(self) -> None:
        assert {
            "iam:ListAccessKeys",
            "iam:GetAccessKeyLastUsed",
            "iam:ListSSHPublicKeys",
            "iam:GetSSHPublicKey",
            "iam:ListSigningCertificates",
            "iam:ListServiceSpecificCredentials",
            "iam:GetLoginProfile",
            "iam:GetAccountPasswordPolicy",
            "iam:GetCredentialReport",
        } <= self._allowed()

    def test_generate_credential_report_is_only_in_its_own_gated_document(self) -> None:
        assert "iam:GenerateCredentialReport" not in self._allowed()
        assert ("iam", "GenerateCredentialReport") not in iam_policy.inventory()
        assert iam_policy.gated_inventory() == {("iam", "GenerateCredentialReport")}
        gated = iam_policy.OUT_DIR / iam_policy.GATED_NAME
        assert gated.read_text() == iam_policy.render_gated()[iam_policy.GATED_NAME], "run iam_policy --write"
        statements = json.loads(gated.read_text())["Statement"]
        assert statements == [
            {"Sid": "GatedGenerateCredentialReport", "Effect": "Allow", "Action": ["iam:GenerateCredentialReport"], "Resource": "*"}
        ]
        # No handoff template attaches it: they take collector-policy-*.json.
        assert not iam_policy.GATED_NAME.startswith("collector-policy-")

    def test_the_gate_names_its_option(self) -> None:
        assert iam_policy.overrides()["gated"]["iam:GenerateCredentialReport"]["option"] == ic.GENERATE_OPTION


# --- the falsifiers ----------------------------------------------------------------------------------------------------------

_FALSIFIERS = [
    (ACCESS_KEY, IamAccessKeyFalsifier, "access_key_id", KEY_A, "list_access_keys", "AccessKeyMetadata", "AccessKeyId"),
    (SSH, IamSshPublicKeyFalsifier, "ssh_public_key_id", SSH_KEY, "list_ssh_public_keys", "SSHPublicKeys", "SSHPublicKeyId"),
    (CERT, IamSigningCertificateFalsifier, "certificate_id", CERT_ID, "list_signing_certificates", "Certificates", "CertificateId"),
    (SVC, IamServiceSpecificCredentialFalsifier, "service_specific_credential_id", SVC_ID, "list_service_specific_credentials", "ServiceSpecificCredentials", "ServiceSpecificCredentialId"),
]  # fmt: skip


def _row(entity_type: str, id_field: str, credential_id: str, *, user_name: str = "alice", user_arn: str = ALICE, account: str = ACCOUNT) -> Candidate:
    result = create_node(
        entity_type,
        {"name": credential_id, "partition": "aws", "account_id": account, id_field: credential_id, "user_name": user_name, "user_arn": user_arn},
    )
    assert result.success, result.errors
    entity_id = uuid.UUID(str(result.entity_id))
    stamp_dimensions(get_node(entity_id), {"aws.account": account, "aws.region": "global"})
    return Candidate(
        entity_id=entity_id, entity_type=entity_type, reason="dropped_from_observation", surface=0, relation="fixture",
        subject=None, edge_type=None, parent=None, interval_first=None,
    )  # fmt: skip


def _session(client: Any) -> Any:
    session = MagicMock()

    def client_for(service: str, region_name: str | None = None) -> Any:
        assert service == "iam" and region_name, (service, region_name)
        return client

    session.client.side_effect = client_for
    return session


def _judge(falsifier_cls: type, client: Any, candidate: Candidate, *, account: str = ACCOUNT) -> Any:
    falsifier = falsifier_cls(session=_session(client), account_id=account)
    (verdict,) = falsifier.batch_falsify([candidate], FalsifyContext(batch_id=str(uuid.uuid4()), statement=None))
    return verdict


@pytest.mark.django_db
@pytest.mark.spec("req-aws-core-iam-credentials-4")
class TestFalsifiers:
    @pytest.mark.parametrize("case", _FALSIFIERS, ids=lambda c: c[0])
    def test_present_dropped_and_forbidden(self, case: tuple[Any, ...]) -> None:
        entity_type, cls, id_field, credential_id, method, items_key, id_member = case
        client = MagicMock()
        getattr(client, method).return_value = {items_key: [{id_member: credential_id}], "IsTruncated": False}
        assert _judge(cls, client, _row(entity_type, id_field, credential_id)).verdict == PRESENT_AT_PROBE
        getattr(client, method).assert_called_once_with(UserName="alice")
        getattr(client, method).return_value = {items_key: [{id_member: "SOMEOTHERFAKEID"}]}
        assert _judge(cls, client, _row(entity_type, id_field, credential_id + "X")).verdict == DROPPED_FROM_OBSERVATION
        getattr(client, method).side_effect = _error("AccessDenied", method)
        verdict = _judge(cls, client, _row(entity_type, id_field, credential_id + "Y"))
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "forbidden")

    @pytest.mark.parametrize("case", _FALSIFIERS, ids=lambda c: c[0])
    def test_a_later_page_is_read_before_absence_is_said(self, case: tuple[Any, ...]) -> None:
        entity_type, cls, id_field, credential_id, method, items_key, id_member = case
        client = MagicMock()
        getattr(client, method).side_effect = [
            {items_key: [{id_member: "SOMEOTHERFAKEID"}], "IsTruncated": True, "Marker": "m1"},
            {items_key: [{id_member: credential_id}], "IsTruncated": False},
        ]
        assert _judge(cls, client, _row(entity_type, id_field, credential_id)).verdict == PRESENT_AT_PROBE
        assert getattr(client, method).call_args_list[1].kwargs == {"UserName": "alice", "Marker": "m1"}

    @pytest.mark.parametrize("case", _FALSIFIERS, ids=lambda c: c[0])
    def test_a_deleted_user_is_undetermined_not_absence(self, case: tuple[Any, ...]) -> None:
        entity_type, cls, id_field, credential_id, method, _items_key, _id_member = case
        client = MagicMock()
        getattr(client, method).side_effect = _error("NoSuchEntity", method)
        assert _judge(cls, client, _row(entity_type, id_field, credential_id)).verdict == UNDETERMINED

    @pytest.mark.parametrize("case", _FALSIFIERS, ids=lambda c: c[0])
    def test_refusals_before_any_call(self, case: tuple[Any, ...]) -> None:
        entity_type, cls, id_field, credential_id, method, _items_key, _id_member = case
        client = MagicMock()
        # Another account's credential.
        verdict = _judge(cls, client, _row(entity_type, id_field, credential_id), account=OTHER_ACCOUNT)
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        # A user name that disagrees with its own ARN.
        verdict = _judge(cls, client, _row(entity_type, id_field, credential_id + "A", user_name="mallory"))
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        # A user ARN naming another account than the row was observed in.
        other = f"arn:aws:iam::{OTHER_ACCOUNT}:user/alice"
        verdict = _judge(cls, client, _row(entity_type, id_field, credential_id + "B", user_arn=other))
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        getattr(client, method).assert_not_called()

    @pytest.mark.parametrize("case", _FALSIFIERS, ids=lambda c: c[0])
    def test_a_govcloud_user_reaches_the_govcloud_endpoint(self, case: tuple[Any, ...]) -> None:
        entity_type, cls, id_field, credential_id, method, items_key, id_member = case
        client = MagicMock()
        getattr(client, method).return_value = {items_key: [{id_member: credential_id}]}
        session = _session(client)
        candidate = _row(entity_type, id_field, credential_id, user_arn=f"arn:aws-us-gov:iam::{ACCOUNT}:user/alice")
        cls(session=session, account_id=ACCOUNT).batch_falsify([candidate], FalsifyContext(batch_id=str(uuid.uuid4()), statement=None))
        assert {call.kwargs.get("region_name") for call in session.client.call_args_list} == {"us-gov-west-1"}
