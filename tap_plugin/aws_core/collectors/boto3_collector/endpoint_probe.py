"""Does the host a client would call resolve? A check of the partition's "not offered" claims, made during a run.

Spec: specs/spec-aws-core-collector-v0.md (req-aws-collector-partition-13). A service the partition does not offer has
no DNS record, so a lookup of the host a client would call settles the question in milliseconds, where a call waits out
its retries. The lookup is a detector, never a reason to skip: it reports a gap the manifest does not know
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


def host_of(client: Any) -> str | None:
    """The host ``client`` calls, or ``None`` when it cannot be told (a client without endpoint metadata)."""
    try:
        return urlparse(client.meta.endpoint_url).hostname
    except AttributeError:
        return None


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
