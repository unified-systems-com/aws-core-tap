"""Does the host a client would call resolve? A check of the partition's "not offered" claims, made during a run.

Spec: specs/spec-aws-core-collector-v0.md (req-aws-collector-partition-13). A service the partition does not offer has
no DNS record, so a lookup of the host a call would be sent to settles the question in milliseconds, where a call waits
out its retries. The lookup is a detector, never a reason to skip: it reports a gap the manifest does not know
(``PARTITION_GAP_LEARNED``) and a claim the manifest still makes that no longer holds (``PARTITION_LIST_STALE``), and the
collector goes on to call as it did before.

The lookup is only as good as the resolver it runs on. A collector behind a proxy, or on private DNS, may fail to
resolve public hosts that its proxy reaches. So the probe checks a control host first: the endpoint of a service this
run has already called successfully (STS). If the control host does not resolve here, the probe is disabled for the run
and says nothing.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

#: The resolver. Replaced in tests; ``socket.getaddrinfo`` otherwise.
RESOLVE: Callable[..., Any] = socket.getaddrinfo


class _Raw:
    """The body of a response that was never sent."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def stream(self, *_a: Any, **_k: Any):
        yield self._body

    def read(self, *_a: Any, **_k: Any) -> bytes:
        return self._body


def request_host(
    service: str, region: str, operation: str, params: dict[str, Any] | None = None, *, use_fips: bool | None = None
) -> str | None:
    """The host a call to ``service``'s ``operation`` would be sent to, or ``None`` when it cannot be told.

    The default endpoint of a client is not that host: an operation can carry a host prefix (``{AccountId}.``,
    ``api.``), a rule set can route an operation to another host (Well-Architected's agent operations go to
    ``wellarchitected-agent``), and a FIPS client reports one host and calls another (Kinesis Video). So the request is
    built, signed with a throwaway key, and stopped at botocore's ``before-send`` event with a canned response; nothing
    is sent and no credential is read. An operation that needs parameters this does not have fails validation first and
    gives ``None``: unknown, never a guess. The host is the one the real call would use, with ``{AccountId}`` replaced by
    zeros where the prefix is a placeholder.
    """
    import boto3
    from botocore import xform_name
    from botocore.awsrequest import AWSResponse
    from .credentials import client_config

    seen: list[str] = []

    def stop(request: Any, **_kw: Any) -> AWSResponse:
        host = urlparse(request.url).hostname
        if host:
            seen.append(host)
        return AWSResponse(request.url, 200, {}, _Raw(b"{}"))

    try:
        session = boto3.session.Session(aws_access_key_id="x", aws_secret_access_key="y", region_name=region)
        # The package's one client configuration; nothing is sent, so its timeouts and retries never apply.
        config = client_config(**({} if use_fips is None else {"use_fips_endpoint": use_fips}))
        client = session.client(service, region_name=region, config=config)
        client.meta.events.register("before-send", stop)
        getattr(client, xform_name(operation))(**(params or {}))
    except Exception:  # noqa: BLE001 - only the host matters; a parse or validation failure after it is not ours to report
        pass
    return seen[0] if seen else None


class EndpointProbe:
    def __init__(self, control_host: str | None) -> None:
        self._control_host = control_host
        self._cache: dict[str, bool] = {}
        self._usable: bool | None = None

    def _lookup(self, host: str) -> bool:
        if host not in self._cache:
            try:
                RESOLVE(host, 443)
                self._cache[host] = True
            except OSError:  # socket.gaierror is an OSError: no such host
                self._cache[host] = False
        return self._cache[host]

    @property
    def usable(self) -> bool:
        """Whether lookups here can be believed: the control host, which this run reached, resolves."""
        if self._usable is None:
            self._usable = bool(self._control_host) and self._lookup(self._control_host)  # type: ignore[arg-type]
        return self._usable

    def resolves(self, host: str | None) -> bool | None:
        """True or False when the lookup can be believed, ``None`` when it cannot (no host, or an untrusted resolver)."""
        if not host or not self.usable:
            return None
        return self._lookup(host)
