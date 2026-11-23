"""IAM credential hygiene: every user's credentials in one walk, and the account's credential report (aws-core-tap#282).

Spec: ``specs/spec-aws-core-v0.md`` (``req-aws-core-iam-credentials``).

**The four credential types.** An IAM user holds access keys, SSH public keys, signing certificates and
service-specific credentials. Each is its own node type (ruling Q142a/b, 2026-11-23), contained by the user through
its own edge type, so a key the user no longer holds is a retirement candidate rather than a row that stays
``Active`` on the grid. :func:`walk_credentials` lists the account's users once and then, per user, the four
listings (``ListAccessKeys``, ``ListSSHPublicKeys``, ``ListSigningCertificates``,
``ListServiceSpecificCredentials``), plus ``GetAccessKeyLastUsed`` per access key. :func:`shared_walk` makes those
calls once per run and the four readers in :mod:`.customfns` each take their slice, so the calls are not made four
times. Every listing is recorded per user as a completeness surface after import (:class:`UserCredentialListing`);
a user with none of a kind records a complete, empty surface, and a denied, failed or short listing records an
incomplete one and contributes no items (``req-aws-core-contained-type-triple``).

Metadata only: never key material, a secret, a password or a key or certificate body. AWS returns a secret access
key or a service-specific password only from the Create/Reset calls, which are never made; ``ListSigningCertificates``
returns the certificate body with every row, and :data:`DROPPED` removes it here, before the item leaves this module.

**The credential report.** ``GetCredentialReport`` is the only source of the root user's password, key and
certificate use. The report is read, never generated, unless the operator turns on ``generate_credential_report``
(``spec-aws-core-secrets.md``, ``req-aws-core-secret-credential-report``): then, and only then, the run calls
``GenerateCredentialReport`` first, the one call aws_core makes that changes state in the account (it makes AWS
build a new report; it changes no configuration and no access). :func:`read_credential_report` keeps "no report"
(``ReportNotPresent``), "expired" and "in progress" distinct from "not read" (a denial or a failure).
"""

from __future__ import annotations

import csv
import io
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from weakref import WeakKeyDictionary

from botocore.exceptions import BotoCoreError, ClientError

from .envelope import jsonable, without_response_metadata
from .hydrate import hydrate_item
from .listing import ListingWalk, error_code
from .manifest import manifest_entries
from .source import iter_listing

USER_TYPE = "aws_core__aws_iam_user"
ACCESS_KEY_TYPE = "aws_core__aws_iam_access_key"
SSH_PUBLIC_KEY_TYPE = "aws_core__aws_iam_ssh_public_key"
SIGNING_CERTIFICATE_TYPE = "aws_core__aws_iam_signing_certificate"
SERVICE_CREDENTIAL_TYPE = "aws_core__aws_iam_service_specific_credential"
ROOT_USER_TYPE = "aws_core__aws_iam_root_user"

#: The option that lets a run call ``GenerateCredentialReport`` (``req-aws-core-secret-credential-report``).
GENERATE_OPTION = "generate_credential_report"

#: Every IAM operation this module makes, for the generated read policy (``iam_policy.py`` reads these literals: the
#: client arrives as an argument, so its per-function scan cannot see the calls). ``generate_credential_report`` is
#: the gated exception: ``iam_policy_overrides.json`` ``gated`` keeps it out of the read policy and writes it as its
#: own document, attached only by an operator who turns the option on.
PAGINATED_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("iam", "list_users"),
    ("iam", "list_access_keys"),
    ("iam", "list_ssh_public_keys"),
    ("iam", "list_signing_certificates"),
    ("iam", "list_service_specific_credentials"),
)
SINGLE_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("iam", "get_access_key_last_used"),
    ("iam", "get_credential_report"),
    ("iam", "generate_credential_report"),
    ("iam", "get_account_password_policy"),
)


@dataclass(frozen=True)
class CredentialKind:
    """One credential type: its node type, the user's containment edge to it, and the listing that names it."""

    entity_type: str
    edge_type: str
    relation: str
    method: str
    items_key: str
    id_member: str
    #: The member holding the creation time AWS states (``CreateDate`` or ``UploadDate``).
    created_member: str


KINDS: dict[str, CredentialKind] = {
    kind.entity_type: kind
    for kind in (
        CredentialKind(
            ACCESS_KEY_TYPE, "HOLDS_ACCESS_KEY__aws_core", "iam_user.access_keys",
            "list_access_keys", "AccessKeyMetadata", "AccessKeyId", "CreateDate",
        ),
        CredentialKind(
            SSH_PUBLIC_KEY_TYPE, "HOLDS_SSH_PUBLIC_KEY__aws_core", "iam_user.ssh_public_keys",
            "list_ssh_public_keys", "SSHPublicKeys", "SSHPublicKeyId", "UploadDate",
        ),
        CredentialKind(
            SIGNING_CERTIFICATE_TYPE, "HOLDS_SIGNING_CERTIFICATE__aws_core", "iam_user.signing_certificates",
            "list_signing_certificates", "Certificates", "CertificateId", "UploadDate",
        ),
        CredentialKind(
            SERVICE_CREDENTIAL_TYPE, "HOLDS_SERVICE_CREDENTIAL__aws_core", "iam_user.service_specific_credentials",
            "list_service_specific_credentials", "ServiceSpecificCredentials", "ServiceSpecificCredentialId",
            "CreateDate",
        ),
    )
}  # fmt: skip

#: The parent type -> the containment edges it records a surface for. It mirrors ``IamUser.CONTAINMENT_EDGES``
#: (``req-aws-core-contained-type-triple-1``; a test holds the two equal).
CONTAINMENT_SURFACES: dict[str, tuple[str, ...]] = {USER_TYPE: tuple(kind.edge_type for kind in KINDS.values())}

#: Members a listing returns that are never kept: the signing certificate's body (metadata only, ruling Q142a).
DROPPED: frozenset[str] = frozenset({"CertificateBody"})


@dataclass
class UserCredentialListing:
    """One user's listing of one credential kind: what the collector turns into the user's surface for that kind."""

    user_arn: str
    kind: CredentialKind
    walk: ListingWalk
    parent_type: str = USER_TYPE

    @property
    def edge_type(self) -> str:
        return self.kind.edge_type

    @property
    def relation(self) -> str:
        return self.kind.relation

    @property
    def parent_key(self) -> str:
        return self.user_arn


@dataclass
class CredentialWalk:
    """Every user the account listed, and each credential kind's items and per-user listings."""

    users: list[dict[str, Any]] = field(default_factory=list)
    items: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: {t: [] for t in KINDS})
    listings: list[UserCredentialListing] = field(default_factory=list)
    #: The kinds whose reader yielded every item to the end. Until it has, no user's surface for that kind may say
    #: its credentials reached the batch (the route53_records rule, aws-core-tap PR 223 review).
    projected: set[str] = field(default_factory=set)

    def surface_listings(self) -> list[UserCredentialListing]:
        """The listings to record as surfaces, each kind's marked not carried when its reader did not finish."""
        for listing in self.listings:
            if listing.kind.entity_type not in self.projected:
                listing.walk.drop("the credential reader did not finish; its credentials were not all carried")
        return self.listings


def _hydrate_ops(entity_type: str) -> list[dict[str, str]]:
    for entry in manifest_entries():
        if entry["entity_type"] == entity_type:
            return list(entry.get("hydrate", []))
    return []


def _timestamp(value: Any) -> str:
    """A botocore timestamp as JSON (ISO 8601 UTC, the second precision AWS states); ``""`` when AWS gave none."""
    return str(jsonable(value)) if value else ""


def _item(kind: CredentialKind, record: Mapping[str, Any], user: Mapping[str, Any]) -> dict[str, Any]:
    """One listed credential, metadata only, with the owning user and the typed values the manifest projects."""
    item = {key: value for key, value in record.items() if key not in DROPPED}
    item["_user_name"] = str(user.get("UserName") or "")
    item["_user_arn"] = str(user.get("Arn") or "")
    item["_created"] = _timestamp(record.get(kind.created_member))
    if kind.entity_type == SERVICE_CREDENTIAL_TYPE:
        item["_expires"] = _timestamp(record.get("ExpirationDate"))
    return item


def _last_used(envelope: dict[str, Any]) -> None:
    """``GetAccessKeyLastUsed``'s answer as typed values: ``""`` when AWS reports the key never used (it omits
    ``LastUsedDate`` and says ``N/A`` for the service and region), ``None`` when the call did not answer."""
    slot = (envelope.get("_hydrate") or {}).get("last_used") or {}
    if slot.get("status") != "ok":
        envelope["_last_used_date"] = envelope["_last_used_service"] = envelope["_last_used_region"] = None
        return
    used = (slot.get("data") or {}).get("AccessKeyLastUsed") or {}
    envelope["_last_used_date"] = _timestamp(used.get("LastUsedDate"))
    envelope["_last_used_service"] = str(used.get("ServiceName") or "")
    envelope["_last_used_region"] = str(used.get("Region") or "")


def walk_credentials(client: Any) -> CredentialWalk:
    """List every user, then each user's four credential listings to the end.

    A listing that fails or stops short keeps its walk (so the user's surface says why it is not an answer) and
    contributes no items: a partial listing would make the credentials it missed look absent. ``ListUsers`` failing
    raises, as every other source does; a user it returned with no name or ARN has no listing (it is not a parent
    the run can name).
    """
    walk = CredentialWalk()
    walk.users = list(iter_listing(client, "list_users", "Users[]", ListingWalk()))
    last_used_ops = _hydrate_ops(ACCESS_KEY_TYPE)
    for user in walk.users:
        name, arn = user.get("UserName"), user.get("Arn")
        if not name or not arn:
            continue
        for kind in KINDS.values():
            listing = ListingWalk()
            walk.listings.append(UserCredentialListing(user_arn=str(arn), kind=kind, walk=listing))
            try:
                records = list(iter_listing(client, kind.method, f"{kind.items_key}[]", listing, UserName=name))
            except (BotoCoreError, ClientError) as exc:
                listing.fail(exc)
                continue
            if listing.complete is not True:
                listing.admitted = False
                listing.reasons.setdefault("admitted", "walk_capped: the listing stopped short, so none of it was processed")
                continue
            if listing.count is None:  # no page at all: the call answered nothing, which is not an empty list
                listing.reached_end(0)
            for record in records:
                credential_id = record.get(kind.id_member)
                if not credential_id:
                    listing.drop(f"a listed {kind.items_key} entry carries no {kind.id_member}")
                    continue
                item = _item(kind, record, user)
                if kind.entity_type == ACCESS_KEY_TYPE:
                    item = hydrate_item(client, item, last_used_ops, call_kwargs={"AccessKeyId": credential_id})
                    _last_used(item)
                walk.items[kind.entity_type].append(item)
    return walk


#: One walk per session: the four readers share one set of IAM calls. A walk that raised is kept too, so a denied
#: ``ListUsers`` is not retried by the next reader.
_WALKS: WeakKeyDictionary[Any, CredentialWalk | BaseException] = WeakKeyDictionary()


def walk_of(session: Any) -> CredentialWalk | None:
    """The run's completed walk, or None when none was made or it raised (an unobserved user has no surface)."""
    try:
        cached = _WALKS.get(session)
    except TypeError:
        return None
    return cached if isinstance(cached, CredentialWalk) else None


def shared_walk(session: Any, client: Any) -> CredentialWalk:
    """The run's :class:`CredentialWalk`, made once per session (a session is the run's own and never reused)."""
    try:
        cached = _WALKS.get(session) if session is not None else None
    except TypeError:  # a session that cannot be weakly referenced: no sharing, still correct
        session = None
        cached = None
    if isinstance(cached, BaseException):
        raise cached
    if cached is not None:
        return cached
    try:
        walk = walk_credentials(client)
    except (BotoCoreError, ClientError) as exc:
        if session is not None:
            _WALKS[session] = exc
        raise
    if session is not None:
        _WALKS[session] = walk
    return walk


# --- the credential report ------------------------------------------------------------------------------------------

#: ``GetCredentialReport``'s answers that are facts about the report, not failures to read it (botocore iam model).
REPORT_STATES: dict[str, str] = {
    "ReportNotPresent": "not_present",
    "ReportExpired": "expired",
    "ReportInProgress": "in_progress",
}
#: The row the report gives the root user (AWS's documented ``user`` value for it).
ROOT_ROW = "<root_account>"
#: How often, and how far apart, a generating run asks whether AWS has finished building the report.
GENERATE_POLLS = 10
GENERATE_INTERVAL_SECONDS = 2.0


@dataclass
class CredentialReport:
    """What the run learned about the account's credential report.

    ``state`` is ``present``, ``not_present``, ``expired`` or ``in_progress`` when AWS answered, and ``None`` when
    it did not (a denial or a failure, kept in ``error``): "no report" is never "not read".
    """

    state: str | None = None
    #: When AWS built the report (ISO 8601 UTC); ``""`` when there is no report to date; ``None`` when not read.
    generated_at: str | None = None
    rows: list[dict[str, str]] = field(default_factory=list)
    error: BaseException | None = None
    #: The run called ``GenerateCredentialReport`` (only when the option is on), and how that went.
    generate_requested: bool = False
    generate_error: BaseException | None = None

    @property
    def root(self) -> dict[str, str] | None:
        return next((row for row in self.rows if row.get("user") == ROOT_ROW), None)


def _generate(client: Any, report: CredentialReport, sleep: Callable[[float], None]) -> None:
    """Ask AWS to build a report and wait, a bounded time, until it says the report is complete. A denial or a
    failure is kept and the run goes on to read whatever report exists."""
    report.generate_requested = True
    try:
        for attempt in range(GENERATE_POLLS):
            state = without_response_metadata(client.generate_credential_report()).get("State")
            if state == "COMPLETE":
                return
            if attempt < GENERATE_POLLS - 1:
                sleep(GENERATE_INTERVAL_SECONDS)
    except (BotoCoreError, ClientError) as exc:
        report.generate_error = exc


def read_credential_report(client: Any, *, generate: bool, sleep: Callable[[float], None] = time.sleep) -> CredentialReport:
    """Read the account's credential report, generating one first only when ``generate`` is true."""
    report = CredentialReport()
    if generate:
        _generate(client, report, sleep)
    try:
        answer = without_response_metadata(client.get_credential_report())
    except ClientError as exc:
        state = REPORT_STATES.get(error_code(exc))
        if state is None:
            report.error = exc
            return report
        report.state = state
        report.generated_at = ""
        return report
    except BotoCoreError as exc:
        report.error = exc
        return report
    content = answer.get("Content") or b""
    text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
    report.state = "present"
    report.generated_at = _timestamp(answer.get("GeneratedTime"))
    report.rows = [dict(row) for row in csv.DictReader(io.StringIO(text))]
    return report


#: Per session: whether the operator turned the option on, and the report once read.
_OPTIONS: WeakKeyDictionary[Any, bool] = WeakKeyDictionary()
_REPORTS: WeakKeyDictionary[Any, CredentialReport] = WeakKeyDictionary()


def generate_enabled(data: Mapping[str, Any]) -> bool:
    """Whether the credential turns generation on; absent or false is off."""
    return data.get(GENERATE_OPTION) is True


def configure(session: Any, *, generate: bool) -> None:
    """Record the run's option on its session, before any reader asks for the report."""
    try:
        _OPTIONS[session] = generate
    except TypeError:  # a session that cannot be weakly referenced: the option stays off
        pass


def shared_report(session: Any, client: Any) -> CredentialReport:
    """The run's :class:`CredentialReport`, read once per session; generated first only when the run's option is
    on (off for a session nobody configured)."""
    try:
        cached = _REPORTS.get(session) if session is not None else None
        generate = _OPTIONS.get(session, False) if session is not None else False
    except TypeError:
        session, cached, generate = None, None, False
    if cached is not None:
        return cached
    report = read_credential_report(client, generate=generate)
    if session is not None:
        _REPORTS[session] = report
    return report


# --- the account password policy ---------------------------------------------------------------------------------------


def read_password_policy(iam: Any) -> tuple[bool | None, dict[str, Any] | None]:
    """The account password policy (``GetAccountPasswordPolicy``, ruling Q143c): ``(True, policy)`` when AWS returned
    one, ``(False, None)`` when it answered ``NoSuchEntity`` (the account has none), ``(None, None)`` when the read was
    denied or failed. "No policy" and "not read" are opposite conclusions and are never folded together."""
    try:
        answer = without_response_metadata(iam.get_account_password_policy())
    except ClientError as exc:
        return (False, None) if error_code(exc) == "NoSuchEntity" else (None, None)
    except BotoCoreError:
        return None, None
    policy = answer.get("PasswordPolicy")
    return (True, dict(policy)) if isinstance(policy, dict) else (None, None)


# --- the root user's row ----------------------------------------------------------------------------------------------

#: The report's sentinels for "no such time": the root user has no password-change time (``not_supported``), a key
#: never used reads ``N/A``, and a use before AWS began tracking it reads ``no_information``.
_NO_TIME = frozenset({"N/A", "no_information", "not_supported"})


def report_time(value: str | None) -> str:
    """A report time as the report states it, or ``""`` for one of its no-time sentinels (the raw row keeps which)."""
    text = (value or "").strip()
    return "" if text in _NO_TIME else text


def report_flag(value: str | None) -> bool | None:
    """``true``/``false`` as a boolean; ``None`` for ``not_supported`` or anything else the report says."""
    text = (value or "").strip().lower()
    return True if text == "true" else False if text == "false" else None


def root_item(report: CredentialReport) -> dict[str, Any] | None:
    """The root user's row as an item for the root user entry, or None when the report has no root row."""
    row = report.root
    if row is None or not row.get("arn"):
        return None
    item: dict[str, Any] = dict(row)
    item["_report_generated_at"] = report.generated_at or ""
    item["_created_at"] = report_time(row.get("user_creation_time"))
    item["_password_enabled"] = report_flag(row.get("password_enabled"))
    item["_password_last_used"] = report_time(row.get("password_last_used"))
    item["_mfa_active"] = report_flag(row.get("mfa_active"))
    for n in (1, 2):
        item[f"_access_key_{n}_active"] = report_flag(row.get(f"access_key_{n}_active"))
        item[f"_access_key_{n}_last_rotated"] = report_time(row.get(f"access_key_{n}_last_rotated"))
        item[f"_access_key_{n}_last_used_date"] = report_time(row.get(f"access_key_{n}_last_used_date"))
        item[f"_access_key_{n}_last_used_region"] = report_time(row.get(f"access_key_{n}_last_used_region"))
        item[f"_access_key_{n}_last_used_service"] = report_time(row.get(f"access_key_{n}_last_used_service"))
        item[f"_cert_{n}_active"] = report_flag(row.get(f"cert_{n}_active"))
        item[f"_cert_{n}_last_rotated"] = report_time(row.get(f"cert_{n}_last_rotated"))
    return item
