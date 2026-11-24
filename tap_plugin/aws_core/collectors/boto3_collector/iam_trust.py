"""Reading an IAM role's trust policy for the organization-rollout questions.

An organization rollout is mostly a question about who can assume what across which account
boundary. The trust policy (``AssumeRolePolicyDocument``) is where a role says so, and it is a JSON
document with a lot of legal shapes: ``Principal`` may be ``"*"``, or a map whose ``AWS`` / ``Service``
/ ``Federated`` values are each a string or a list; an ``AWS`` principal may be a bare 12-digit
account id, an account root ARN, a role or user ARN, or (after the principal was deleted) an opaque
unique id such as ``AROAXXXXXXXX``. This module turns that into three facts and nothing more:

- ``trusted_account_ids`` - the OTHER accounts whose principals the role trusts (the role's own account
  is never listed, so every entry crosses an account boundary);
- ``trusted_services`` - service principals (``lambda.amazonaws.com``);
- ``trusts_wildcard_principal`` - an Allow statement names ``*``.

Only ``Effect: Allow`` statements grant trust; a ``Deny`` narrows it and is not summarised (the full
document stays in the node's configuration). A ``Condition`` is not evaluated: the summary says who is
NAMED, and ``trusts_wildcard_principal`` says the name is a wildcard, so a reader can tell "trusts
account 1234... (with an ExternalId)" from "trusts the world" without this module pretending to
evaluate IAM. ``NotPrincipal`` is treated as no information rather than as a grant.

ARN parsing is partition-aware (``aws``, ``aws-us-gov``, ``aws-cn``, ...): the account segment is
matched, never the partition, so a GovCloud role's trust is read the same way as a commercial one.

The same reading, generalised to a policy on a resource (:func:`summarize_resource_policy`, a Lambda
function's, alias's or version's ``lambda:GetPolicy`` document, aws-core-tap#290), adds one fact the trust
summary does not carry: whether an outside grant has no ``Condition`` at all.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote

_ACCOUNT_ID = re.compile(r"^[0-9]{12}$")
#: arn:<partition>:iam::<account>:<resource> — IAM ARNs carry no region.
_IAM_ARN = re.compile(r"^arn:(?P<partition>[a-z0-9-]+):iam::(?P<account>[0-9]{12}|aws):")

#: A region that resolves within each ARN partition, for a global-per-partition service (IAM, STS)
#: that still needs one real endpoint to call. ``aws`` and its commercial-equivalent regions all
#: route the same global IAM/STS calls to ``us-east-1``; GovCloud and China have their own,
#: disjoint region sets and no ``us-east-1`` at all. Falls back to the commercial region for any
#: partition not named here (isolated/secret partitions aws_core does not otherwise support).
_PARTITION_REGION: dict[str, str] = {
    "aws": "us-east-1",
    "aws-us-gov": "us-gov-west-1",
    "aws-cn": "cn-north-1",
}


def iam_endpoint_region(arn: object) -> str:
    """A region that reaches ``arn``'s own partition for a global-per-partition IAM/STS call.

    Derived from the ARN itself — never from the caller's own session — so a falsifier judging a
    GovCloud-collected role calls the GovCloud IAM endpoint even if this falsifier's own default
    credential happens to be commercial (a candidate whose account does not match is refused by
    the scope check before this is ever reached, but the region math stays correct regardless).
    """
    if isinstance(arn, str):
        match = _IAM_ARN.match(arn.strip())
        if match is not None:
            return _PARTITION_REGION.get(match.group("partition"), _PARTITION_REGION["aws"])
    return _PARTITION_REGION["aws"]


def account_of_iam_arn(arn: object) -> str | None:
    """The 12-digit account segment of an IAM ARN, or None.

    ``aws`` in the account position marks an AWS-managed resource (``arn:aws:iam::aws:policy/...``) and
    is deliberately not an account id.
    """
    if not isinstance(arn, str):
        return None
    match = _IAM_ARN.match(arn.strip())
    if match is None or match.group("account") == "aws":
        return None
    return match.group("account")


def _principal_account(value: str) -> str | None:
    """The account a single ``Principal.AWS`` entry names, or None (a wildcard or an opaque id)."""
    value = value.strip()
    if _ACCOUNT_ID.match(value):
        return value
    return account_of_iam_arn(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def trust_policy_document(raw: Any) -> dict[str, Any] | None:
    """The trust policy as a dict. boto3 decodes it for ListRoles/GetRole; a raw URL-encoded string is accepted."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(unquote(raw))
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


@dataclass
class _Named:
    """Who one ``Principal`` element names, read the same way for a trust policy and a resource policy."""

    accounts: set[str] = field(default_factory=set)
    services: set[str] = field(default_factory=set)
    wildcard: bool = False
    #: A member this reader does not know (``Federated`` in a resource policy, a non-string entry): the caller
    #: decides whether that makes the document unreadable.
    unread: bool = False

    @property
    def outside(self) -> bool:
        """The element names someone outside the resource's own account: any principal, another account, or a
        service (a service principal acts for whichever account owns the calling resource)."""
        return self.wildcard or bool(self.accounts) or bool(self.services)


def _named_principals(principal: Any, *, own_account: str | None, members: tuple[str, ...] = ("AWS", "Service")) -> _Named:
    """Read one ``Principal`` element: ``"*"``, or a map whose ``AWS`` / ``Service`` values are each a string or a
    list. ``own_account`` is never listed in ``accounts``. A map member outside ``members`` sets ``unread``."""
    named = _Named()
    if principal == "*":
        named.wildcard = True
        return named
    if not isinstance(principal, dict):
        named.unread = True
        return named
    for member in principal:
        if member not in members:
            named.unread = True
    for entry in _as_list(principal.get("AWS")):
        if not isinstance(entry, str):
            named.unread = True
            continue
        if entry.strip() == "*":
            named.wildcard = True
            continue
        account = _principal_account(entry)
        if account is not None and account != own_account:
            named.accounts.add(account)
    for entry in _as_list(principal.get("Service")):
        if isinstance(entry, str) and entry.strip():
            named.services.add(entry.strip())
        else:
            named.unread = True
    return named


def summarize_trust_policy(raw: Any, *, own_account: str | None) -> dict[str, Any] | None:
    """Summarise who a role's trust policy names. None when the document cannot be read at all.

    ``own_account`` is the role's own account (from its ARN); it is excluded from ``trusted_account_ids``
    so the list is exactly the cross-account assume-role targets. Both lists are sorted and de-duplicated
    so the same policy always yields byte-identical output (a re-run must not churn history).
    """
    document = trust_policy_document(raw)
    if document is None:
        return None
    accounts: set[str] = set()
    services: set[str] = set()
    wildcard = False
    for statement in _as_list(document.get("Statement")):
        if not isinstance(statement, dict) or statement.get("Effect") != "Allow":
            continue
        principal = statement.get("Principal")
        if principal != "*" and not isinstance(principal, dict):
            continue
        # A trust policy may also name Federated principals, which FEDERATES_INTO_ROLE reads; they are not
        # summarised here, so an unknown member is simply not counted.
        named = _named_principals(principal, own_account=own_account, members=("AWS", "Service", "Federated"))
        accounts |= named.accounts
        services |= named.services
        wildcard = wildcard or named.wildcard
    return {
        "trusted_account_ids": sorted(accounts),
        "trusted_services": sorted(services),
        "trusts_wildcard_principal": wildcard,
    }


#: arn:<partition>:<service>:<region>:<account>:<resource> — any ARN whose account segment is a 12-digit id.
_ACCOUNT_ARN = re.compile(r"^arn:[a-z0-9-]+:[a-z0-9-]+:[a-z0-9-]*:(?P<account>[0-9]{12}):")


def account_of_arn(arn: object) -> str | None:
    """The 12-digit account segment of any ARN (``arn:aws-us-gov:lambda:us-gov-west-1:<account>:function:f``),
    whatever its partition, or None."""
    if not isinstance(arn, str):
        return None
    match = _ACCOUNT_ARN.match(arn.strip())
    return match.group("account") if match else None


def resource_policy_document(raw: Any) -> dict[str, Any] | None:
    """A resource policy as a dict. ``lambda:GetPolicy`` returns it as a JSON string (not URL-encoded)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def summarize_resource_policy(raw: Any, *, own_account: str | None) -> dict[str, Any] | None:
    """Summarise who a resource-based policy (a Lambda function's, alias's or version's) lets in.

    The trust-policy summary, generalised to a policy on a resource, plus one more fact:

    - ``account_ids`` - the OTHER accounts an ``Allow`` statement names (never ``own_account``);
    - ``services`` - service principals an ``Allow`` statement names;
    - ``wildcard_principal`` - an ``Allow`` statement names ``*``, conditioned or not;
    - ``unconditioned`` - an ``Allow`` statement names someone outside ``own_account`` (any principal,
      another account or a service) and carries no ``Condition``. Any non-empty ``Condition`` makes the
      statement conditioned: the condition is not evaluated, so a ``SourceArn`` naming the account's own
      bucket and an ``aws:PrincipalOrgID`` are both "conditioned", and ``false`` says only that every
      outside grant has some condition on it.

    Only ``Effect: Allow`` statements grant; a ``Deny`` is not summarised (the stored document keeps it).
    ARNs are read whatever their partition. ``None`` when the document cannot be read with certainty: it
    does not parse, has no statement list, or an ``Allow`` statement uses ``NotPrincipal``, a principal
    member other than ``AWS`` / ``Service``, or a principal shape this reader does not know. Lambda builds
    its policies only from ``AddPermission`` statements, so none of those is expected; nothing is guessed if
    one appears. Lists are sorted so the same policy always yields the same output.
    """
    document = resource_policy_document(raw)
    if document is None:
        return None
    statements = document.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list):
        return None
    accounts: set[str] = set()
    services: set[str] = set()
    wildcard = False
    unconditioned = False
    for statement in statements:
        if not isinstance(statement, dict):
            return None
        if statement.get("Effect") != "Allow":
            continue
        if "NotPrincipal" in statement:
            return None
        named = _named_principals(statement.get("Principal"), own_account=own_account)
        if named.unread:
            return None
        accounts |= named.accounts
        services |= named.services
        wildcard = wildcard or named.wildcard
        if named.outside and not statement.get("Condition"):
            unconditioned = True
    return {
        "account_ids": sorted(accounts),
        "services": sorted(services),
        "wildcard_principal": wildcard,
        "unconditioned": unconditioned,
    }
