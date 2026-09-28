"""Storage + IAM falsifiers (aws-core-tap#41): present/dropped/forbidden proof cases against a
mocked boto3 client, the S3 403/404 tie-break (both status codes — AWS's own ``HeadBucket``
documentation makes 404 exactly as ambiguous as 403), the ``list_buckets`` partial-page guard, the
IAM account-match gate (a REQUIREMENT applied before every probe, not only before trusting an
absence — see ``falsifiers.py``'s module docstring), and the customer-managed-only scope of the
IAM policy falsifier.

``ClientError({"Error": {"Code": ...}}, op)`` mirrors the existing mocking convention in
``tests/test_boto3_collector_hydrate.py``: no moto, no live AWS, one boto3 exception shape reused
everywhere in this plugin's tests.

S3 and the IAM policy falsifier can never answer ``REIDENTIFIED`` (checked, not assumed — see
``falsifiers.py``'s module docstring for exactly why each is structurally incapable of it), so
``tap_grid.falsifier_testing``'s ``run_four_cases`` (which hard-requires a reidentified case) is
not used for them; present/dropped/forbidden are proven individually instead. IAM role and user
CAN answer ``REIDENTIFIED`` — for a delete+recreate under a different path, same name — and that
case is tested directly.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError
from tap_grid.falsifiers import (
    DROPPED_FROM_OBSERVATION,
    PRESENT_AT_PROBE,
    REIDENTIFIED,
    UNDETERMINED,
    Candidate,
    FalsifyContext,
    unsupported,
)
from tap_grid.services import create_node
from tap_plugin.aws_core.falsifiers import (
    IamPolicyFalsifier,
    IamRoleFalsifier,
    IamUserFalsifier,
    S3BucketFalsifier,
    probe_status_of,
)

ACCOUNT = "aws_core__aws_account"
S3_BUCKET = "aws_core__aws_s3_bucket"
IAM_ROLE = "aws_core__aws_iam_role"
IAM_USER = "aws_core__aws_iam_user"
IAM_POLICY = "aws_core__aws_iam_policy"

ACCOUNT_ID = "123456789012"
OTHER_ACCOUNT_ID = "999999999999"


def _client_error(code: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, op)


def _create(type_slug: str, payload: dict[str, Any]) -> uuid.UUID:
    result = create_node(type_slug, payload)
    assert result.success, f"create_node failed: {result.errors}"
    assert result.entity_id is not None
    return uuid.UUID(str(result.entity_id))


def _candidate(
    entity_id: uuid.UUID,
    entity_type: str,
    parent: uuid.UUID | None = None,
    *,
    surface: int = 0,
) -> Candidate:
    return Candidate(
        entity_id=entity_id,
        entity_type=entity_type,
        reason="dropped_from_observation",
        surface=surface,
        relation="fixture",
        subject=str(parent) if parent else None,
        edge_type=None,
        parent=parent,
        interval_first=None,
    )


def _context() -> FalsifyContext:
    return FalsifyContext(batch_id=str(uuid.uuid4()), statement=None)


def _probe(verdict: Any) -> dict[str, Any]:
    assert verdict.probe is not None, "a judged verdict records its probe"
    return verdict.probe


@pytest.mark.django_db
class TestIamRoleFalsifier:
    @staticmethod
    def _role(name: str, arn: str) -> Candidate:
        rid = _create(IAM_ROLE, {"name": name, "role_arn": arn})
        return _candidate(rid, IAM_ROLE)

    def test_present(self) -> None:
        candidate = self._role("present", f"arn:aws:iam::{ACCOUNT_ID}:role/present")
        client = MagicMock()
        client.get_role.return_value = {
            "Role": {
                "Arn": f"arn:aws:iam::{ACCOUNT_ID}:role/present",
                "RoleName": "present",
            }
        }
        falsifier = IamRoleFalsifier(client=client, caller_account=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == PRESENT_AT_PROBE
        assert verdict.expected == {
            "source_id": f"arn:aws:iam::{ACCOUNT_ID}:role/present",
            "owner": None,
            "name": "present",
        }
        assert _probe(verdict)["owner"] == ACCOUNT_ID
        assert unsupported(verdict) is None

    def test_a_path_change_on_the_same_name_is_reidentified(self) -> None:
        # get_role looks up by RoleName ALONE (no path in the request), and IAM role names are
        # unique per account across every path — so a delete+recreate under a DIFFERENT path,
        # same name, is genuinely detectable: the response's Arn disagrees with the grid's.
        candidate = self._role(
            "app-role", f"arn:aws:iam::{ACCOUNT_ID}:role/old-path/app-role"
        )
        client = MagicMock()
        client.get_role.return_value = {
            "Role": {
                "Arn": f"arn:aws:iam::{ACCOUNT_ID}:role/new-path/app-role",
                "RoleName": "app-role",
            }
        }
        falsifier = IamRoleFalsifier(client=client, caller_account=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == REIDENTIFIED
        assert unsupported(verdict) is None

    def test_dropped_with_a_verified_matching_account(self) -> None:
        # The account-match gate's happy path: this run's own (injected, for the test) caller
        # account matches the ARN account the grid recorded, so NoSuchEntity is trusted.
        candidate = self._role("dropped", f"arn:aws:iam::{ACCOUNT_ID}:role/dropped")
        client = MagicMock()
        client.get_role.side_effect = _client_error("NoSuchEntity", "GetRole")
        [verdict] = IamRoleFalsifier(
            client=client, caller_account=ACCOUNT_ID
        ).batch_falsify([candidate], _context())
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        assert unsupported(verdict) is None

    def test_no_verifiable_caller_account_refuses_before_any_probe(self) -> None:
        # The gate runs BEFORE the AWS call, not only before trusting an absence: with no
        # session behind the injected client, the caller account cannot be resolved at all, so
        # the candidate is refused without ever calling get_role.
        candidate = self._role("dropped", f"arn:aws:iam::{ACCOUNT_ID}:role/dropped")
        client = MagicMock()
        [verdict] = IamRoleFalsifier(client=client).batch_falsify(
            [candidate], _context()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "could not be verified" in verdict.note
        client.get_role.assert_not_called()

    def test_the_wrong_account_refuses_before_any_probe_even_when_the_call_would_hit(
        self,
    ) -> None:
        # This is the shape two independent AI review passes flagged: without the pre-probe
        # gate, a credential for the WRONG account could still successfully call get_role and
        # find ITS OWN unrelated same-named role, and that live (but irrelevant) ARN would be
        # compared to the grid's stored one as though it answered the question. The gate must
        # refuse before the call is ever made, so `get_role.return_value` here is never reached.
        candidate = self._role("dropped", f"arn:aws:iam::{ACCOUNT_ID}:role/dropped")
        client = MagicMock()
        client.get_role.return_value = {
            "Role": {
                "Arn": f"arn:aws:iam::{OTHER_ACCOUNT_ID}:role/dropped",
                "RoleName": "dropped",
            }
        }
        falsifier = IamRoleFalsifier(client=client, caller_account=OTHER_ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "does not match" in verdict.note
        client.get_role.assert_not_called()

    def test_a_malformed_arn_refuses_before_any_probe(self) -> None:
        # `FIELD_VALIDATION_SCHEMA` does not constrain role_arn's shape, so a garbled stored
        # value is possible: `_arn_account` then returns None, and that must refuse exactly
        # like a mismatch — not fall through and trust whatever the probe answers.
        candidate = self._role("dropped", "not-a-real-arn")
        client = MagicMock()
        falsifier = IamRoleFalsifier(client=client, caller_account=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "no recognizable account segment" in verdict.note
        client.get_role.assert_not_called()

    def test_forbidden(self) -> None:
        candidate = self._role("forbidden", f"arn:aws:iam::{ACCOUNT_ID}:role/forbidden")
        client = MagicMock()
        client.get_role.side_effect = _client_error("AccessDenied", "GetRole")
        falsifier = IamRoleFalsifier(client=client, caller_account=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "forbidden")
        assert unsupported(verdict) is None

    def test_a_row_without_an_arn_is_not_answered(self) -> None:
        rid = _create(IAM_ROLE, {"name": "legacy"})
        client = MagicMock()
        [verdict] = IamRoleFalsifier(client=client).batch_falsify(
            [_candidate(rid, IAM_ROLE)], _context()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        client.get_role.assert_not_called()

    def test_a_missing_credential_answers_undetermined(self) -> None:
        def boom() -> Any:
            raise RuntimeError("no secret mounted")

        candidates = [
            self._role(f"r{i}", f"arn:aws:iam::{ACCOUNT_ID}:role/r{i}")
            for i in range(2)
        ]
        verdicts = IamRoleFalsifier(client_factory=boom).batch_falsify(
            candidates, _context()
        )
        assert [(v.verdict, v.reason) for v in verdicts] == [
            (UNDETERMINED, "errored")
        ] * 2
        assert all("credential unavailable" in v.note for v in verdicts)


@pytest.mark.django_db
class TestIamUserFalsifier:
    @staticmethod
    def _user(name: str, arn: str) -> Candidate:
        uid = _create(IAM_USER, {"name": name, "user_arn": arn})
        return _candidate(uid, IAM_USER)

    def test_present(self) -> None:
        candidate = self._user("present", f"arn:aws:iam::{ACCOUNT_ID}:user/present")
        client = MagicMock()
        client.get_user.return_value = {
            "User": {
                "Arn": f"arn:aws:iam::{ACCOUNT_ID}:user/present",
                "UserName": "present",
            }
        }
        falsifier = IamUserFalsifier(client=client, caller_account=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == PRESENT_AT_PROBE
        assert unsupported(verdict) is None

    def test_a_path_change_on_the_same_name_is_reidentified(self) -> None:
        candidate = self._user(
            "app-user", f"arn:aws:iam::{ACCOUNT_ID}:user/old-path/app-user"
        )
        client = MagicMock()
        client.get_user.return_value = {
            "User": {
                "Arn": f"arn:aws:iam::{ACCOUNT_ID}:user/new-path/app-user",
                "UserName": "app-user",
            }
        }
        falsifier = IamUserFalsifier(client=client, caller_account=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == REIDENTIFIED
        assert unsupported(verdict) is None

    def test_dropped_with_a_verified_matching_account(self) -> None:
        candidate = self._user("dropped", f"arn:aws:iam::{ACCOUNT_ID}:user/dropped")
        client = MagicMock()
        client.get_user.side_effect = _client_error("NoSuchEntity", "GetUser")
        [verdict] = IamUserFalsifier(
            client=client, caller_account=ACCOUNT_ID
        ).batch_falsify([candidate], _context())
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        assert unsupported(verdict) is None

    def test_no_verifiable_caller_account_refuses_before_any_probe(self) -> None:
        candidate = self._user("dropped", f"arn:aws:iam::{ACCOUNT_ID}:user/dropped")
        client = MagicMock()
        [verdict] = IamUserFalsifier(client=client).batch_falsify(
            [candidate], _context()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        client.get_user.assert_not_called()

    def test_forbidden(self) -> None:
        candidate = self._user("forbidden", f"arn:aws:iam::{ACCOUNT_ID}:user/forbidden")
        client = MagicMock()
        client.get_user.side_effect = _client_error("AccessDenied", "GetUser")
        falsifier = IamUserFalsifier(client=client, caller_account=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "forbidden")
        assert unsupported(verdict) is None


@pytest.mark.django_db
class TestIamPolicyFalsifier:
    @staticmethod
    def _policy(name: str, arn: str, *, is_aws_managed: bool = False) -> Candidate:
        pid = _create(
            IAM_POLICY,
            {"name": name, "policy_arn": arn, "is_aws_managed": is_aws_managed},
        )
        return _candidate(pid, IAM_POLICY)

    def test_present(self) -> None:
        candidate = self._policy(
            "app-policy", f"arn:aws:iam::{ACCOUNT_ID}:policy/app-policy"
        )
        client = MagicMock()
        client.get_policy.return_value = {
            "Policy": {
                "Arn": f"arn:aws:iam::{ACCOUNT_ID}:policy/app-policy",
                "PolicyName": "app-policy",
            }
        }
        falsifier = IamPolicyFalsifier(client=client, caller_account=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == PRESENT_AT_PROBE
        client.get_policy.assert_called_once_with(
            PolicyArn=f"arn:aws:iam::{ACCOUNT_ID}:policy/app-policy"
        )
        assert unsupported(verdict) is None

    def test_dropped_with_a_verified_matching_account(self) -> None:
        candidate = self._policy("dropped", f"arn:aws:iam::{ACCOUNT_ID}:policy/dropped")
        client = MagicMock()
        client.get_policy.side_effect = _client_error("NoSuchEntity", "GetPolicy")
        falsifier = IamPolicyFalsifier(client=client, caller_account=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == DROPPED_FROM_OBSERVATION
        assert unsupported(verdict) is None

    def test_the_wrong_account_refuses_before_any_probe(self) -> None:
        candidate = self._policy("dropped", f"arn:aws:iam::{ACCOUNT_ID}:policy/dropped")
        client = MagicMock()
        falsifier = IamPolicyFalsifier(client=client, caller_account=OTHER_ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        client.get_policy.assert_not_called()

    def test_forbidden(self) -> None:
        candidate = self._policy(
            "forbidden", f"arn:aws:iam::{ACCOUNT_ID}:policy/forbidden"
        )
        client = MagicMock()
        client.get_policy.side_effect = _client_error("AccessDenied", "GetPolicy")
        falsifier = IamPolicyFalsifier(client=client, caller_account=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "forbidden")
        assert unsupported(verdict) is None

    def test_an_aws_managed_policy_is_never_probed(self) -> None:
        # AWS-managed policies are refused before even the account-match gate: it is pointless
        # work regardless of which account the credential resolves to.
        candidate = self._policy(
            "AdministratorAccess",
            "arn:aws:iam::aws:policy/AdministratorAccess",
            is_aws_managed=True,
        )
        client = MagicMock()
        [verdict] = IamPolicyFalsifier(client=client).batch_falsify(
            [candidate], _context()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "AWS-managed" in verdict.note
        client.get_policy.assert_not_called()

    def test_a_customer_managed_policy_is_probed_normally(self) -> None:
        candidate = self._policy(
            "app-policy",
            f"arn:aws:iam::{ACCOUNT_ID}:policy/app-policy",
            is_aws_managed=False,
        )
        client = MagicMock()
        client.get_policy.return_value = {
            "Policy": {
                "Arn": f"arn:aws:iam::{ACCOUNT_ID}:policy/app-policy",
                "PolicyName": "app-policy",
            }
        }
        falsifier = IamPolicyFalsifier(client=client, caller_account=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == PRESENT_AT_PROBE
        client.get_policy.assert_called_once()


@pytest.mark.django_db
class TestS3BucketFalsifier:
    @staticmethod
    def _bucket(name: str, parent: uuid.UUID | None = None) -> Candidate:
        bid = _create(S3_BUCKET, {"name": name, "bucket_arn": f"arn:aws:s3:::{name}"})
        return _candidate(bid, S3_BUCKET, parent)

    def test_present(self) -> None:
        candidate = self._bucket("present")
        client = MagicMock()
        client.head_bucket.return_value = {}
        [verdict] = S3BucketFalsifier(client=client).batch_falsify(
            [candidate], _context()
        )
        assert verdict.verdict == PRESENT_AT_PROBE
        assert unsupported(verdict) is None

    # -- both ambiguous statuses (AWS's own HeadBucket doc: 404 and 403 are equally ambiguous) --

    @pytest.mark.parametrize("code", ["404", "403"])
    def test_absent_from_list_buckets_without_a_verified_owner_is_undetermined_not_dropped(
        self, code: str
    ) -> None:
        # The owner-match requirement is unconditional, not skipped when there is nothing to
        # compare: today `expected.owner` is always None (no containment edge reaches this type
        # yet), so an absence from this credential's own inventory is never, on its own, read as
        # evidence — S3 bucket names are global, so "not in my ListBuckets" is equally what a
        # bucket owned by a DIFFERENT account looks like. See
        # test_an_absence_under_the_matching_recorded_owner_is_dropped for the only path that
        # DOES retire.
        candidate = self._bucket("gone")
        client = MagicMock()
        client.head_bucket.side_effect = _client_error(code, "HeadBucket")
        client.list_buckets.return_value = {
            "Buckets": [{"Name": "present"}, {"Name": "other"}]
        }
        [verdict] = S3BucketFalsifier(client=client).batch_falsify(
            [candidate], _context()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "owning account could not be verified" in verdict.note

    @pytest.mark.parametrize("code", ["404", "403"])
    def test_absent_from_list_buckets_with_a_verified_owner_but_no_caller_account_is_undetermined(
        self, code: str
    ) -> None:
        # Owner IS recorded, but this run's own caller account could not be resolved (no
        # session behind the injected client): still refused, never assumed to pass.
        account = _create(ACCOUNT, {"name": "acme", "account_id": ACCOUNT_ID})
        candidate = self._bucket("gone", parent=account)
        client = MagicMock()
        client.head_bucket.side_effect = _client_error(code, "HeadBucket")
        client.list_buckets.return_value = {"Buckets": []}
        [verdict] = S3BucketFalsifier(client=client).batch_falsify(
            [candidate], _context()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")

    @pytest.mark.parametrize("code", ["404", "403"])
    def test_present_in_list_buckets_is_forbidden_not_dropped(self, code: str) -> None:
        # Present in this account's own inventory either way: whatever head_bucket answered, the
        # bucket demonstrably exists, so it is a permission/visibility gap, never a retirement.
        candidate = self._bucket("locked")
        client = MagicMock()
        client.head_bucket.side_effect = _client_error(code, "HeadBucket")
        client.list_buckets.return_value = {"Buckets": [{"Name": "locked"}]}
        [verdict] = S3BucketFalsifier(client=client).batch_falsify(
            [candidate], _context()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "forbidden")
        assert "present in this account's own ListBuckets" in verdict.note

    @pytest.mark.parametrize("code", ["404", "403"])
    def test_when_list_buckets_itself_fails_is_undetermined_not_dropped(
        self, code: str
    ) -> None:
        # Fail closed: with no tie-break evidence at all, neither ambiguous status becomes a
        # retirement.
        candidate = self._bucket("mystery")
        client = MagicMock()
        client.head_bucket.side_effect = _client_error(code, "HeadBucket")
        client.list_buckets.side_effect = _client_error("AccessDenied", "ListBuckets")
        [verdict] = S3BucketFalsifier(client=client).batch_falsify(
            [candidate], _context()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "could not be read either" in verdict.note

    def test_a_400_is_not_routed_through_the_tie_break(self) -> None:
        # The third status HeadBucket documents (400) is left as `errored`, already conservative
        # — no tie-break call is spent on it.
        candidate = self._bucket("weird")
        client = MagicMock()
        client.head_bucket.side_effect = _client_error("400", "HeadBucket")
        [verdict] = S3BucketFalsifier(client=client).batch_falsify(
            [candidate], _context()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "errored")
        client.list_buckets.assert_not_called()

    # -- list_buckets partial-page guard --

    def test_a_continuation_token_is_never_treated_as_a_complete_inventory(
        self,
    ) -> None:
        candidate = self._bucket("gone")
        client = MagicMock()
        client.head_bucket.side_effect = _client_error("403", "HeadBucket")
        client.list_buckets.return_value = {
            "Buckets": [{"Name": "other"}],
            "ContinuationToken": "eyJ...",
        }
        [verdict] = S3BucketFalsifier(client=client).batch_falsify(
            [candidate], _context()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "could not be read either" in verdict.note

    # -- owner-match gate: the ONLY way this falsifier ever answers DROPPED_FROM_OBSERVATION --

    def test_an_absence_under_a_different_recorded_owner_is_undetermined_not_dropped(
        self,
    ) -> None:
        account = _create(ACCOUNT, {"name": "other", "account_id": OTHER_ACCOUNT_ID})
        candidate = self._bucket("gone", parent=account)
        client = MagicMock()
        client.head_bucket.side_effect = _client_error("403", "HeadBucket")
        client.list_buckets.return_value = {"Buckets": []}
        falsifier = S3BucketFalsifier(client=client, caller_account=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        assert "owning account could not be verified" in verdict.note

    def test_an_absence_under_the_matching_recorded_owner_is_dropped(self) -> None:
        account = _create(ACCOUNT, {"name": "acme", "account_id": ACCOUNT_ID})
        candidate = self._bucket("gone", parent=account)
        client = MagicMock()
        client.head_bucket.side_effect = _client_error("403", "HeadBucket")
        client.list_buckets.return_value = {"Buckets": []}
        falsifier = S3BucketFalsifier(client=client, caller_account=ACCOUNT_ID)
        [verdict] = falsifier.batch_falsify([candidate], _context())
        assert verdict.verdict == DROPPED_FROM_OBSERVATION

    # -- run-scoped caching --

    def test_list_buckets_is_called_once_per_run_for_several_ambiguous_statuses(
        self,
    ) -> None:
        candidates = [self._bucket(f"b{i}") for i in range(3)]
        client = MagicMock()
        client.head_bucket.side_effect = _client_error("403", "HeadBucket")
        client.list_buckets.return_value = {"Buckets": []}
        S3BucketFalsifier(client=client).batch_falsify(candidates, _context())
        assert client.list_buckets.call_count == 1

    def test_a_new_run_re_reads_list_buckets(self) -> None:
        candidate = self._bucket("flaky")
        client = MagicMock()
        client.head_bucket.side_effect = _client_error("403", "HeadBucket")
        client.list_buckets.return_value = {"Buckets": []}
        falsifier = S3BucketFalsifier(client=client)
        falsifier.batch_falsify(
            [candidate], FalsifyContext(batch_id="run-1", statement=None)
        )
        falsifier.batch_falsify(
            [candidate], FalsifyContext(batch_id="run-2", statement=None)
        )
        assert client.list_buckets.call_count == 2

    def test_a_row_without_an_arn_is_not_answered(self) -> None:
        bid = _create(S3_BUCKET, {"name": "legacy"})
        client = MagicMock()
        [verdict] = S3BucketFalsifier(client=client).batch_falsify(
            [_candidate(bid, S3_BUCKET)], _context()
        )
        assert (verdict.verdict, verdict.reason) == (UNDETERMINED, "scope_unknown")
        client.head_bucket.assert_not_called()

    def test_a_missing_credential_answers_undetermined(self) -> None:
        def boom() -> Any:
            raise RuntimeError("no secret mounted")

        candidates = [self._bucket(f"b{i}") for i in range(2)]
        verdicts = S3BucketFalsifier(client_factory=boom).batch_falsify(
            candidates, _context()
        )
        assert [(v.verdict, v.reason) for v in verdicts] == [
            (UNDETERMINED, "errored")
        ] * 2


class TestProbeStatusOf:
    @pytest.mark.parametrize(
        ("code", "op", "want"),
        [
            ("NoSuchEntity", "GetRole", "not_found"),
            ("404", "HeadBucket", "not_found"),
            ("403", "HeadBucket", "forbidden"),
            ("AccessDenied", "GetRole", "forbidden"),
            ("AccessDeniedException", "GetPolicy", "forbidden"),
            ("Throttling", "GetRole", "rate_limited"),
            ("SlowDown", "HeadBucket", "rate_limited"),
            ("InternalError", "HeadBucket", "errored"),
            ("ServiceUnavailable", "GetRole", "errored"),
            ("400", "HeadBucket", "errored"),
        ],
    )
    def test_mapping(self, code: str, op: str, want: str) -> None:
        status, _detail = probe_status_of(_client_error(code, op))
        assert status == want

    def test_a_transport_error_is_a_different_exception_family(self) -> None:
        # ConnectTimeoutError is a BotoCoreError, not a ClientError: falsifiers catch it
        # separately (`_from_transport_error`) rather than passing it through `probe_status_of`.
        # Documented by construction: this just proves the two exception families stay distinct.
        assert not isinstance(
            ConnectTimeoutError(endpoint_url="https://iam.amazonaws.com"), ClientError
        )
