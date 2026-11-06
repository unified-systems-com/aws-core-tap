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

import contextlib
import socket
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

#: The resolver. Replaced in tests; ``socket.getaddrinfo`` otherwise.
RESOLVE: Callable[..., Any] = socket.getaddrinfo
#: How long one host lookup may take before the resolver is taken to be wedged.
LOOKUP_SECONDS = 5.0


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
    built, unsigned, and stopped at botocore's ``before-send`` event with a canned response; nothing
    is sent and no credential is needed or read. An operation that needs parameters this does not have fails validation first and
    gives ``None``: unknown, never a guess. The host is the one the real call would use; a prefix that is a placeholder
    (``{AccountId}.``) takes the value of the parameter it names, so an operation that needs one it lacks gives ``None``.
    """
    from botocore import xform_name

    # Only the host matters; a parse or validation failure after the request is built is not ours to report.
    seen: list[str] = []
    with contextlib.suppress(Exception):
        client, seen = _client(service, region, use_fips)
        seen.clear()
        # The canned response does not parse, so the call raises after the request was built and the host was seen.
        getattr(client, xform_name(operation))(**(params or {}))
    return seen[0] if seen else None


#: One unsigned client per (service, region, FIPS) for the life of the process. Building a client loads the service's
#: model and is the cost (about 100 ms); building the request for another operation of the same client is not. A
#: collection that probes hundreds of entries would otherwise spend a minute here.
_CLIENTS: dict[tuple[str, str, bool | None], tuple[Any, list[str]]] = {}


def clear_cache() -> None:
    """Forget the clients (tests that watch client construction)."""
    _CLIENTS.clear()


def _client(service: str, region: str, use_fips: bool | None) -> tuple[Any, list[str]]:
    key = (service, region, use_fips)
    if key not in _CLIENTS:
        import boto3
        from botocore import UNSIGNED
        from botocore.awsrequest import AWSResponse
        from .credentials import client_config

        seen: list[str] = []

        def stop(request: Any, **_kw: Any) -> AWSResponse:
            host = urlparse(request.url).hostname
            if host:
                seen.append(host)
            return AWSResponse(request.url, 200, {}, _Raw(b"{}"))

        session = boto3.session.Session(region_name=region)
        # The package's one client configuration; nothing is sent, so its timeouts and retries never apply. Unsigned: the
        # request is only built, so no credential of any kind is needed or read.
        config = client_config(signature_version=UNSIGNED, **({} if use_fips is None else {"use_fips_endpoint": use_fips}))
        client = session.client(service, region_name=region, config=config)
        client.meta.events.register("before-send", stop)
        _CLIENTS[key] = (client, seen)
    return _CLIENTS[key]


class EndpointProbe:
    def __init__(self, control_host: str | None) -> None:
        self._control_host = control_host
        self._cache: dict[str, bool | None] = {}
        self._wedged = False
        self._usable: bool | None = None
        #: Entries asked about whose host could not be told (a parent to fan out from, a custom function, a parameter
        #: the probe lacks), counted by the caller so the run's summary says how much was out of reach.
        self.not_probed = 0
        #: What has been reported, so a service whose operations go to different hosts is checked at each host and
        #: warned about once per (service, region, host); and the entity types counted as not probed, once each.
        self.reported: set[tuple[str, str, str]] = set()
        self.unprobed: set[str] = set()
        self.gaps = 0
        self.stale = 0

    @property
    def hosts_checked(self) -> int:
        """Distinct hosts looked up, the control host excluded."""
        return len([h for h, found in self._cache.items() if h != self._control_host and found is not None])

    def _lookup(self, host: str) -> bool | None:
        """Whether ``host`` resolves; ``None`` when the resolver did not answer within ``LOOKUP_SECONDS``. The first
        such lookup ends the probe for the run (``usable`` turns False): a resolver that wedges is not to be waited on
        once per host."""
        if host not in self._cache:
            self._cache[host] = self._resolve(host)
        return self._cache[host]

    def _resolve(self, host: str) -> bool | None:
        if self._wedged:
            return None
        outcome: list[bool] = []

        def work() -> None:
            try:
                RESOLVE(host, 443)
                outcome.append(True)
            except OSError:  # socket.gaierror is an OSError: no such host
                outcome.append(False)

        # A daemon thread, because getaddrinfo cannot be interrupted: a wedged lookup is abandoned, not joined.
        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        thread.join(LOOKUP_SECONDS)
        if outcome:
            return outcome[0]
        self._wedged = True
        return None

    @property
    def usable(self) -> bool:
        """Whether lookups here can be believed: the control host, which this run reached, resolves."""
        if self._usable is None:
            self._usable = bool(self._control_host) and bool(self._lookup(self._control_host))  # type: ignore[arg-type]
        return self._usable and not self._wedged

    def resolves(self, host: str | None) -> bool | None:
        """True or False when the lookup can be believed, ``None`` when it cannot (no host, or an untrusted resolver)."""
        if not host or not self.usable:
            return None
        return self._lookup(host)
