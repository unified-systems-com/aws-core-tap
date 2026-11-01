"""The read-only guard for live validation: which AWS operations a validation run may call.

Standard library only, so it is unit-tested without AWS or Django. Two layers:

* the operation name must be a read verb (``Describe``, ``List``, ``Get``, ``BatchGet``, ``Search``, ``Lookup``,
  ``Head``, ``Query``); and
* a verb prefix is not enough, because some ``Get``/``Describe`` operations return credentials. Those are refused by
  name, and so is any call whose request asks the service to reveal a secret (``WithDecryption``, ``includeValue``).

``DescribeUserPoolClient`` (returns a client secret) and ``GetBucketPolicy`` are reads the collector itself makes and
that its manifest and reader-sensitivity review already cover; they are not on the list. A test asserts that no
operation the manifest names is on it, so adding one is a deliberate change here and there.
"""

import re

READ_VERB = re.compile(r"^(Describe|List|Get|BatchGet|Search|Lookup|Head|Query)")

#: Operations whose response carries credentials, tokens or secret values.
SECRET_RETURNING = frozenset(
    {
        "GetSecretValue",
        "BatchGetSecretValue",
        "GetSessionToken",
        "GetFederationToken",
        "GetCredentialsForIdentity",
        "GetOpenIdToken",
        "GetOpenIdTokenForDeveloperIdentity",
        "GetPasswordData",
        "GetAuthorizationToken",
        "GetRoleCredentials",
        "GetServiceSpecificCredential",
        "GetRandomPassword",
        "GetDomainAuthorizationToken",
    }
)

#: Operations that return a secret only when asked; the request parameter that asks is refused instead.
REVEALING_PARAMS = {
    "GetParameter": ("WithDecryption",),
    "GetParameters": ("WithDecryption",),
    "GetParametersByPath": ("WithDecryption",),
    "GetParameterHistory": ("WithDecryption",),
    "GetApiKey": ("includeValue",),
    "GetApiKeys": ("includeValues",),
}


class NonReadCall(Exception):
    """Raised before a call the guard refuses."""


def check(operation, params=None):
    """Raise NonReadCall unless ``operation`` is an allowed read; ``params`` are the API request parameters."""
    if not READ_VERB.match(operation):
        raise NonReadCall(f"not a read verb: {operation}")
    if operation in SECRET_RETURNING:
        raise NonReadCall(f"returns credentials or secret values: {operation}")
    for name in REVEALING_PARAMS.get(operation, ()):
        if (params or {}).get(name):
            raise NonReadCall(f"asks the service to reveal a secret: {operation} {name}")
