"""Reader functions for the AWS time forms core's own reader does not take (tap req-grid-entity-event-time rules 23 to 28).

A model's ``EVENT_TIME`` names one of these beside the field (or the member of ``configuration``) that holds a time
in a form of AWS's own. The field keeps what AWS sent (core rule 22): nothing here is called by the collector, and
nothing here writes. Core calls the function with the stored value each time it derives the spine, and reads what it
returns with its one reader, so a function cannot put a form on the spine that core does not take (core rule 24).

Each function is pure (core rule 25): it reads its argument and nothing else. A value it cannot read raises, and core
then stores no event time for the row and reports the field; :func:`certificate_not_after` instead returns None, as
ruled (Q150b), and core stores no end. Epoch counts need nothing here: core ships
``from_epoch_seconds`` and ``from_epoch_milliseconds`` (core rule 27), and the models name those directly.

Changing what a function here returns changes what stored spine values mean with no change of type definition, which
the fingerprint guard cannot see (core rule 28): raise the version of every type that names it, and run core's
re-derive pass.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Final

# The X.509 parser: cryptography, which every tap install already carries (tap's own dependencies pull it in through
# django-allauth[socialaccount] and webauthn, tap/fips.py imports it, and tap's pyproject builds it against the
# system OpenSSL). aws_core adds no dependency for it. Parsing a certificate's validity reads it and computes nothing.
from cryptography import x509

__all__ = ["certificate_not_after", "offset_without_colon"]

# A date and time to the second, an optional fraction, and a UTC offset written as four digits with no colon:
# Lambda's form, ``2018-11-27T15:10:45.123+0000`` (botocore lambda shape ``Timestamp``, documented with that example
# on ListLayerVersions ``CreatedDate``).
_OFFSET_WITHOUT_COLON: Final[re.Pattern[str]] = re.compile(
    r"(?P<time>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?)"
    r"(?P<sign>[+-])(?P<hours>[0-9]{2})(?P<minutes>[0-9]{2})"
)
# The same date and time with ``Z`` or an offset that has its colon: already a FHIR form core reads.
_WITH_ZONE: Final[re.Pattern[str]] = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)


def offset_without_colon(value: Any) -> str:
    """Lambda's ISO 8601 text with a ``+0000`` offset, as the FHIR ``dateTime`` text core reads (``+00:00``).

    Lambda writes its timestamps (a layer version's ``CreatedDate``, a function URL's ``CreationTime``: botocore types
    both with the lambda shape ``Timestamp``) to the millisecond with the offset as four digits and no colon, which
    FHIR does not take. The colon is put in and nothing else changes: the offset is AWS's own, so the instant is the
    one AWS stated. Text that is already in a form core reads (``Z``, or an offset with its colon) is returned as it
    is, since the same shape is documented as W3C ISO 8601 on the function URL, whose offset has the colon.

    Anything that is not text raises :class:`TypeError`; text in neither form raises :class:`ValueError`. Core turns
    either into "no event time" with a warning naming the field.
    """
    if not isinstance(value, str):
        raise TypeError(f"a Lambda timestamp is text, not a {type(value).__name__}")
    match = _OFFSET_WITHOUT_COLON.fullmatch(value)
    if match is not None:
        return f"{match['time']}{match['sign']}{match['hours']}:{match['minutes']}"
    if _WITH_ZONE.fullmatch(value):
        return value
    raise ValueError("not a Lambda timestamp: a date and time to the second, with Z or a UTC offset")


def certificate_not_after(value: Any) -> datetime | None:
    """The end of an X.509 certificate's validity (its notAfter), read from the certificate's PEM text.

    An IAM signing certificate's expiry is not a member of ``ListSigningCertificates``' answer: it is inside the
    certificate, which AWS returns as PEM text (``CertificateBody``) and the collector stores as AWS sent it (ruling
    Q150b, 2026-11-24). The instant is the certificate's own, stated in UTC, and returned as a zoned datetime.

    Returns None when the value is not text or holds no certificate this can parse, so the row has no end rather than
    a guessed one. When the text holds more than one certificate, the first is read: IAM stores one per signing
    certificate.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        certificate = x509.load_pem_x509_certificate(value.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return None
    return certificate.not_valid_after_utc
