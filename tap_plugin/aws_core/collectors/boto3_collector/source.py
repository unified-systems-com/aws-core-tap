"""Source primitive for the boto3 collector: the ``aws_op`` driver + dispatch.

Spec: plugins/aws_core/specs/spec-aws-core-collector-v0.md
(req-aws-collector-source).

A manifest entry's ``source`` has two implementations that yield the *same*
thing — an iterable of raw resource items — so the engine never branches on
which was used downstream (``req-aws-collector-source-1``):

- ``aws_op``: a declared boto3 operation, driven generically — the engine
  resolves the client for the service, uses the botocore paginator when the
  operation has one, otherwise calls it once, and extracts items via the
  manifest ``items_path``. No per-resource pagination code
  (``req-aws-collector-source-2``).
- ``custom_fn``: a named callable resolved through a plugin-local registry,
  used only where AWS needs multiple calls to assemble one logical resource.
  Code is **never** loaded from manifest data — the manifest only names the
  callable (``req-aws-collector-source-3``).

``ResponseMetadata`` is stripped from every response before items are
extracted, so it never reaches an item / ``configuration``
(``req-aws-collector-field-projection-6``).

**Two independent completeness mechanisms, one per containment shape.** Account-scoped
containment (tap-plugin-aws-core#43 — IAM role/user/policy, IAM OIDC provider, S3 bucket) threads
``walk``, a :class:`.listing.ListingWalk` that ``iter_listing`` fills in as it consumes pages,
including through a ``custom_fn`` (IAM's ``get_role``/``get_user`` hydration needs multiple calls
per item). Region-scoped containment (tap-plugin-aws-core#49 — VPC, subnet, security group, EC2
instance) threads ``truncated``, a plain list a non-paginated single call appends a continuation
marker to when the response reports truncation it did not read to the end. No entry declares both
kinds of containment, so the two parameters are never both non-``None`` for one call — each
consumer passes only its own.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from botocore import xform_name

from .envelope import without_response_metadata
from .listing import ListingWalk, page_says_more
from .paths import eval_path


class SourceError(Exception):
    """A manifest ``source`` could not be driven (unknown ``custom_fn``)."""


# A custom_fn yields raw items in the same shape an aws_op would. It receives
# a bound session/region context (built by the runtime integration, later).
CustomFn = Callable[[Any], Iterator[Any]]


class CustomFnRegistry:
    """Plugin-local registry of ``custom_fn`` callables.

    The manifest names a callable; the engine resolves it here. Code is never
    imported from manifest data (``req-aws-collector-source-3``), mirroring
    ``req-tap-cares-collector-registry-6``.
    """

    def __init__(self) -> None:
        self._fns: dict[str, CustomFn] = {}

    def register(self, name: str, fn: CustomFn) -> None:
        """Register ``fn`` under ``name`` (last registration wins)."""
        self._fns[name] = fn

    def get(self, name: str) -> CustomFn:
        """Resolve a registered callable or raise ``SourceError``."""
        try:
            return self._fns[name]
        except KeyError:
            known = ", ".join(sorted(self._fns)) or "<none>"
            raise SourceError(
                f"custom_fn {name!r} is not registered (known: {known})"
            ) from None


#: Response keys that say "there is more than this page" on an operation botocore has no paginator
#: for. A call that returns one of these truthy was truncated, and a truncated listing cannot be
#: called complete.
_CONTINUATION_KEYS: tuple[str, ...] = ("NextToken", "nextToken", "NextMarker", "Marker", "NextContinuationToken")


def continuation_of(response: Any) -> str | None:
    """The key of a truthy continuation marker in ``response``, or ``None`` when it is not truncated.

    ``IsTruncated: true`` counts too. Used only where the call could not be paginated for us: a
    paginated call is walked to its end by botocore.
    """
    if not isinstance(response, dict):
        return None
    for key in _CONTINUATION_KEYS:
        if response.get(key):
            return key
    if response.get("IsTruncated") is True:
        return "IsTruncated"
    return None


def iter_pages(client: Any, method: str, **kwargs: Any) -> Iterator[Any]:
    """Yield the ``ResponseMetadata``-free pages of a list operation.

    The botocore paginator when the operation has one, else a single call. The one place a listing's
    pages are consumed, so :func:`iter_listing` and every ``custom_fn`` that walks a listing agree on
    what "a page" is.
    """
    if client.can_paginate(method):
        for page in client.get_paginator(method).paginate(**kwargs):
            yield without_response_metadata(page)
        return
    yield without_response_metadata(getattr(client, method)(**kwargs))


def iter_listing(client: Any, method: str, items_path: str, walk: ListingWalk, **kwargs: Any) -> Iterator[Any]:
    """Yield the items of a list operation and record on ``walk`` whether the listing ended.

    ``walk.complete`` becomes ``True`` only when the generator is consumed to its end AND the final page
    does not itself report a continuation (:func:`.listing.page_says_more`); it becomes ``False`` when
    the final page says there is more. A consumer that stops early, or an exception mid-walk, leaves it
    ``None`` (the walk cannot say): the tail below never runs, which is exactly the right answer.
    """
    count = 0
    last: Any = None
    for page in iter_pages(client, method, **kwargs):
        last = page
        for item in eval_path(page, items_path):
            count += 1
            yield item
    if last is None:
        return
    if page_says_more(last):
        walk.stopped_short(count, "the final page still reports a continuation marker")
    else:
        walk.reached_end(count)


def iter_aws_op(
    client: Any,
    op_name: str,
    items_path: str,
    *,
    walk: ListingWalk | None = None,
    truncated: list[str] | None = None,
    params: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Yield raw items from a boto3 operation, generically.

    Uses the botocore paginator when the operation has one, else a single
    call (``req-aws-collector-source-2``). The boto3 client method is the
    ``xform_name`` of the manifest's API-cased operation (``ListFunctions``
    -> ``list_functions``).

    Args:
        client: A boto3 service client.
        op_name: The API-cased operation name from the manifest.
        items_path: The manifest path that flattens the response to items.
        walk: When the entry declares account-scoped ``containment`` (tap-plugin-aws-core#43), the
            :class:`.listing.ListingWalk` this listing fills in; ``None`` for every other entry,
            whose behaviour is unchanged. Mutually exclusive with ``truncated``.
        truncated: When the entry declares region-scoped ``containment`` (tap-plugin-aws-core#49)
            and the call could not be paginated, a continuation marker seen on it is appended here.
            The items are still yielded — an existing consumer is unchanged — but a caller that must
            know the listing ran to its end (a completeness surface) can tell it did not. Mutually
            exclusive with ``walk``.
        params: Request parameters for the call (the values a ``per`` fan-out bound from its parent);
            ``None`` for the argument-free listings every other entry uses.
    """
    method = xform_name(op_name)
    kwargs = params or {}
    if walk is not None:
        yield from iter_listing(client, method, items_path, walk, **kwargs)
        return
    if client.can_paginate(method):
        for page in client.get_paginator(method).paginate(**kwargs):
            yield from eval_path(without_response_metadata(page), items_path)
        return
    response = getattr(client, method)(**kwargs)
    if truncated is not None and (marker := continuation_of(response)) is not None:
        truncated.append(marker)
    yield from eval_path(without_response_metadata(response), items_path)


#: The slot a fanned-out child item carries its parent under, so ``fields`` can read the parent
#: (``_parent.Name``) for an identifier or ARN the child's own response does not hold.
PARENT_SLOT = "_parent"


def _iter_parents(per: dict[str, Any], default_service: str, client_for: Callable[[str], Any]) -> Iterator[Any]:
    """Yield the items of a ``per`` block, each carrying its own parent when it has one."""
    client = client_for(per.get("service", default_service))
    if "per" in per:
        for grand in _iter_parents(per["per"], per.get("service", default_service), client_for):
            yield from _children(client, per, grand)
        return
    yield from iter_aws_op(client, per["aws_op"], per["items_path"], params=dict(per.get("params", {})))


def _children(client: Any, spec: dict[str, Any], parent: Any) -> Iterator[Any]:
    """One call of ``spec`` for ``parent``: its ``bind`` pulls the request parameters off the parent."""
    bound = {name: eval_path(parent, path) for name, path in spec["bind"].items()}
    missing = [name for name, value in bound.items() if value in (None, "", [])]
    if missing:
        raise SourceError(f"{spec['aws_op']}: a parent item has no value for {', '.join(missing)} (bind path unresolved)")
    params = {**spec.get("params", {}), **bound}
    for item in iter_aws_op(client, spec["aws_op"], spec["items_path"], params=params):
        if isinstance(item, dict):
            yield {**item, PARENT_SLOT: parent}
        else:
            yield item


def iter_fanout(
    entry: dict[str, Any], *, client_for: Callable[[str], Any]
) -> Iterator[Any]:
    """Yield the items of an entry whose list call needs a parent's identifier.

    ``source.per`` names the call that lists the parents (itself possibly ``per`` another, for a
    resource two levels down); ``source.bind`` maps this entry's request parameters to paths on one
    parent. The operation runs once per parent. A parent whose call raises raises here, so the type
    reads as not collected rather than as a shorter list that looks complete.
    """
    source = entry["source"]
    client = client_for(entry["service"])
    for parent in _iter_parents(source["per"], entry["service"], client_for):
        yield from _children(client, {**source, "items_path": entry["items_path"]}, parent)


def iter_source(
    entry: dict[str, Any],
    *,
    client_for: Callable[[str], Any],
    custom_fns: CustomFnRegistry,
    fn_context: Any = None,
    walk: ListingWalk | None = None,
    truncated: list[str] | None = None,
) -> Iterator[Any]:
    """Drive a manifest entry's ``source``, yielding raw items.

    The single place the engine resolves ``source``; everything downstream
    sees one uniform item iterable (``req-aws-collector-source-1``).

    Args:
        entry: A validated manifest entry.
        client_for: Builds a boto3 client for a service name (credential /
            region binding lives in the runtime integration, later).
        custom_fns: The plugin-local ``custom_fn`` registry.
        fn_context: Bound session/region context passed to a ``custom_fn``.
        walk: The listing walk to fill in, passed only for an entry that declares account-scoped
            containment (tap-plugin-aws-core#43). A ``custom_fn`` behind such an entry MUST accept it
            (``walk=``) and report on it; the manifest test holds that line.
        truncated: See :func:`iter_aws_op`. A ``custom_fn`` reports nothing here
            (tap-plugin-aws-core#49): the engine cannot see inside one, so a region-scoped
            completeness claim is an ``aws_op`` entry only.
    """
    source = entry["source"]
    if "per" in source:
        yield from iter_fanout(entry, client_for=client_for)
        return
    if "aws_op" in source:
        client = client_for(entry["service"])
        yield from iter_aws_op(client, source["aws_op"], entry["items_path"], walk=walk, truncated=truncated)
        return
    fn = custom_fns.get(source["custom_fn"])
    # Pass client_for through so regional custom_fns can build region-bound
    # clients without inventing their own region resolution. Global custom_fns
    # (route53, the s3 list-buckets head) accept it as a kwarg and ignore it.
    if walk is not None:
        yield from fn(fn_context, client_for=client_for, walk=walk)
        return
    yield from fn(fn_context, client_for=client_for)
