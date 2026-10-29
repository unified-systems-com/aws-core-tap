"""Facts for the coverage ledger: CloudFormation resource schemas, botocore service models, partitions.

Spec: ``specs/spec-aws-core-coverage-ledger.md`` (``req-aws-core-ledger-denominator``).

The CloudFormation schema bundle is untrusted data. It is read as JSON only: nothing in it is imported,
executed or followed, a member whose name tries to leave the archive is ignored, and a member or bundle
over a fixed size is refused rather than read.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The public bundle AWS publishes the CloudFormation resource type schemas in.
BUNDLE_URL = "https://schema.cloudformation.us-east-1.amazonaws.com/CloudformationSchema.zip"
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_MEMBERS = 10_000
#: The most decompressed bytes a bundle may add up to, whatever its members' sizes; a real bundle is about 40 MiB.
MAX_TOTAL_BYTES = 256 * 1024 * 1024

_TYPE_NAME = re.compile(r"^[A-Za-z0-9]+::[A-Za-z0-9]+::[A-Za-z0-9]+(::[A-Za-z0-9]+)*$")


class SourceError(Exception):
    """A source could not be read, or read as something other than what the ledger accepts."""


def confine(path: Path | str, *extra_roots: Path | str) -> Path:
    """The real path of ``path``, refused unless it lies inside the working directory, the temporary directory or
    one of ``extra_roots``.

    A command-line argument names a file the ledger will read or write, so it is resolved (symbolic links and
    ``..`` included) and checked against a short list of places before anything opens it.
    """
    real = os.path.realpath(path)
    for root in (Path.cwd(), tempfile.gettempdir(), *extra_roots):
        base = os.path.realpath(root)
        if real == base or real.startswith(base + os.sep):
            return Path(real)
    raise SourceError(f"{path} is outside the working directory and the temporary directory")


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to https on the host the request started at, so a fixed address stays fixed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        target = urllib.parse.urlsplit(newurl)
        origin = urllib.parse.urlsplit(req.full_url)
        if target.scheme != "https" or target.netloc != origin.netloc:
            raise urllib.error.URLError(f"refused a redirect from {origin.netloc} to {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_bundle(dest: Path) -> tuple[Path, int, str]:
    """Fetch the public schema bundle into ``dest``: https, one host, a size cap; returns path, bytes, sha256.

    The bytes go to a temporary file the process created itself, inside ``dest``, and the final name is replaced
    only after the whole body has arrived. A link planted at the final name between the check and the write is
    therefore replaced, never written through.
    """
    dest = confine(dest)
    dest.mkdir(parents=True, exist_ok=True)
    target = confine(dest / "CloudformationSchema.zip")
    origin = urllib.parse.urlsplit(BUNDLE_URL)
    if origin.scheme != "https":
        raise SourceError("the bundle address is not https")
    opener = urllib.request.build_opener(SameHostRedirect)
    request = urllib.request.Request(BUNDLE_URL, headers={"User-Agent": "aws-core-tap-ledger"})
    digest = hashlib.sha256()
    size = 0
    descriptor, temporary = tempfile.mkstemp(prefix=".bundle-", suffix=".part", dir=dest)
    try:
        with opener.open(request, timeout=60) as response, os.fdopen(descriptor, "wb") as out:
            if urllib.parse.urlsplit(response.geturl()).netloc != origin.netloc:
                raise SourceError(f"the bundle came from {response.geturl()}, not {origin.netloc}")
            while chunk := response.read(1 << 20):
                size += len(chunk)
                if size > MAX_BUNDLE_BYTES:
                    raise SourceError(f"the bundle is over {MAX_BUNDLE_BYTES} bytes")
                digest.update(chunk)
                out.write(chunk)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return target, size, digest.hexdigest()


@dataclass(frozen=True)
class CfnType:
    """One CloudFormation resource type, reduced to what the ledger records."""

    type_name: str
    service: str
    primary_identifier: tuple[str, ...]
    has_list_handler: bool
    #: ``tagging.taggable`` (default true when the block exists), else the deprecated top-level ``taggable``,
    #: else None: the schema says nothing about tags, which is not evidence either way.
    taggable: bool | None
    tag_property: str | None
    has_tagging_block: bool


@dataclass(frozen=True)
class BotoService:
    name: str
    endpoint_prefix: str
    #: Whether the service model has any ``List*`` or ``Describe*`` operation.
    has_enumerator: bool
    #: Other names the model carries (``serviceId``, ``signingName``, ``serviceAbbreviation``), normalised, so a
    #: CloudFormation service whose name matches one of them is found (``Elastic Load Balancing v2`` is ``elbv2``).
    aliases: frozenset[str] = frozenset()


def normalise(name: str) -> str:
    """Fold a service name to lower-case letters and digits, so ``Cognito-IDP`` and ``cognitoidp`` meet."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _parse_type(document: Any, member: str) -> CfnType | None:
    if not isinstance(document, dict) or "typeName" not in document:
        return None
    type_name = document["typeName"]
    if not isinstance(type_name, str) or not _TYPE_NAME.match(type_name):
        raise SourceError(f"{member}: typeName {type_name!r} is not a CloudFormation type name")
    tagging = document.get("tagging")
    has_block = isinstance(tagging, dict)
    if has_block:
        # tagging.taggable defaults to true when the block omits it (CloudFormation's own contract). A value that is
        # present and not a JSON boolean is a malformed bundle, refused: coercing it would turn 0 or "false" into
        # authoritative tag evidence.
        taggable = tagging.get("taggable", True)
        if not isinstance(taggable, bool):
            raise SourceError(f"{member}: tagging.taggable is {taggable!r}, not a boolean")
        tag_property = tagging.get("tagProperty")
    else:
        if "taggable" in document and not isinstance(document["taggable"], bool):
            raise SourceError(f"{member}: taggable is {document['taggable']!r}, not a boolean")
        taggable = document.get("taggable")
        tag_property = None
    identifier = document.get("primaryIdentifier", [])
    if not isinstance(identifier, list) or not all(isinstance(p, str) for p in identifier):
        raise SourceError(f"{member}: primaryIdentifier is not a list of strings")
    handlers = document.get("handlers", {})
    if not isinstance(handlers, dict):
        raise SourceError(f"{member}: handlers is not an object")
    return CfnType(
        type_name=type_name,
        service=type_name.split("::")[1],
        primary_identifier=tuple(identifier),
        has_list_handler="list" in handlers,
        taggable=taggable,
        tag_property=tag_property if isinstance(tag_property, str) else None,
        has_tagging_block=has_block,
    )


def load_cfn_bundle(path: Path) -> tuple[dict[str, CfnType], str]:
    """Read every resource type from a bundle zip or an extracted directory, with the bundle's sha256.

    The hash is of the zip's bytes, or, for a directory, of its sorted member names and contents. The two forms
    of one bundle therefore hash differently; the ledger records the hash it was built from, not a bundle id.
    """
    path = confine(path)
    members: list[tuple[str, bytes]] = []
    digest = hashlib.sha256()
    total = 0
    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if len(files) > MAX_MEMBERS:
            raise SourceError(f"{path.name} has more than {MAX_MEMBERS} members")
        for file in files:
            if file.is_symlink():
                raise SourceError(f"{file.name} is a symbolic link; a bundle directory holds files only")
            size = file.stat().st_size
            total += size
            if size > MAX_MEMBER_BYTES or total > MAX_TOTAL_BYTES:
                raise SourceError(f"{file.name} is over the size limit ({MAX_MEMBER_BYTES} a member, {MAX_TOTAL_BYTES} in all)")
            raw = file.read_bytes()
            members.append((file.name, raw))
            digest.update(file.name.encode() + b"\0" + raw)
    elif path.is_file():
        if path.stat().st_size > MAX_BUNDLE_BYTES:
            raise SourceError(f"{path.name} is over {MAX_BUNDLE_BYTES} bytes")
        with path.open("rb") as handle:
            while block := handle.read(1 << 20):
                digest.update(block)
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_MEMBERS:
                raise SourceError(f"{path.name} has more than {MAX_MEMBERS} members")
            for info in sorted(infos, key=lambda i: i.filename):
                name = info.filename
                if not name.endswith(".json") or name.startswith("/") or ".." in Path(name).parts:
                    continue
                # The header's size is the archive's claim, so the read itself is bounded and the real byte
                # count is what adds up.
                with archive.open(info) as member:
                    raw = member.read(MAX_MEMBER_BYTES + 1)
                total += len(raw)
                if len(raw) > MAX_MEMBER_BYTES or total > MAX_TOTAL_BYTES:
                    raise SourceError(f"{name} is over the size limit ({MAX_MEMBER_BYTES} a member, {MAX_TOTAL_BYTES} in all)")
                members.append((name, raw))
    else:
        raise SourceError(f"{path} is neither a zip nor a directory")
    types: dict[str, CfnType] = {}
    for name, raw in members:
        try:
            parsed = _parse_type(json.loads(raw), name)
        except json.JSONDecodeError as exc:
            raise SourceError(f"{name} is not JSON: {exc}") from exc
        if parsed is None:
            continue
        if parsed.type_name in types:
            raise SourceError(f"{name}: {parsed.type_name} appears twice in the bundle")
        types[parsed.type_name] = parsed
    if not types:
        raise SourceError(f"{path} holds no CloudFormation resource type")
    return types, digest.hexdigest()


def botocore_version() -> str:
    import botocore

    return str(botocore.__version__)


def botocore_services() -> dict[str, BotoService]:
    """Every service model botocore bundles, with whether it can enumerate anything."""
    import botocore.session

    session = botocore.session.get_session()
    services: dict[str, BotoService] = {}
    for name in session.get_available_services():
        model = session.get_service_model(name)
        has_enumerator = any(op.startswith(("List", "Describe")) for op in model.operation_names)
        metadata = model.metadata
        aliases = frozenset(
            normalise(str(metadata[key])) for key in ("serviceId", "signingName", "serviceAbbreviation") if metadata.get(key)
        )
        services[name] = BotoService(
            name=name, endpoint_prefix=model.endpoint_prefix, has_enumerator=has_enumerator, aliases=aliases
        )
    return services


def partition_services() -> tuple[dict[str, frozenset[str]], frozenset[str]]:
    """Per partition, the endpoint prefixes botocore's bundled endpoint data gives an endpoint to, and every
    prefix that data names at all.

    An approximation of availability, not AWS's statement of it. A service newer than the vendored data, or one
    resolved by an endpoint rule set instead, is named in no partition: that is "botocore does not say"
    (unknown), never "unavailable". Only a service named somewhere but without an endpoint in a partition is
    recorded as absent from that partition.
    """
    import botocore.session

    data = botocore.session.get_session().get_data("endpoints")
    with_endpoints: dict[str, frozenset[str]] = {}
    named: set[str] = set()
    for partition in data["partitions"]:
        services = partition.get("services", {})
        named.update(services)
        with_endpoints[str(partition["partition"])] = frozenset(
            prefix for prefix, entry in services.items() if entry.get("endpoints") or "partitionEndpoint" in entry
        )
    return with_endpoints, frozenset(named)
