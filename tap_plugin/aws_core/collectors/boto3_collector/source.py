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

import re
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

#: The request parameter that carries a response continuation key forward, where it is not the key
#: itself (``NextMarker`` comes back, ``Marker`` goes in).
_MARKER_REQUEST: dict[str, str] = {"NextMarker": "Marker", "NextContinuationToken": "ContinuationToken"}

#: A ceiling on the calls one unpaginated listing may make, so a service that keeps returning a
#: marker cannot spin the collector forever.
_MAX_UNPAGINATED_CALLS = 1000


def _request_marker(client: Any, op_name: str, response_key: str) -> str | None:
    """The request parameter that continues a listing whose response carried ``response_key``.

    Read off the operation's input shape when the client has one, so a marker is only ever sent to an
    operation that accepts it; ``None`` when the operation takes no such parameter (the listing cannot
    be continued, and stays reported as truncated).
    """
    wanted = _MARKER_REQUEST.get(response_key, response_key)
    try:
        members = client.meta.service_model.operation_model(op_name).input_shape.members
    except AttributeError:
        return wanted
    return wanted if wanted in members else None

def _items_of(page: Any, items_path: str, single: bool) -> Iterator[Any]:
    """The items ``items_path`` finds in one response page; one structure is one item when ``single``."""
    found = eval_path(page, items_path)
    if found is None:
        return
    if single and isinstance(found, dict):
        yield found
        return
    yield from found


def _walk_unpaginated(
    client: Any,
    op_name: str,
    method: str,
    items_path: str,
    kwargs: dict[str, Any],
    truncated: list[str] | None,
    single: bool = False,
) -> Iterator[Any]:
    """Yield the items of an operation botocore has no paginator for, following its own marker.

    A response that carries a continuation marker is called again with that marker until it does not,
    so a listing with a second page reads it (``req-aws-collector-source-2``). A marker the operation
    cannot be sent back on, a marker that repeats, or a run past the call ceiling stops the walk and is
    appended to ``truncated`` as before, so a caller that must know the listing did not end can tell.
    """
    call = dict(kwargs)
    seen: set[str] = set()
    for _ in range(_MAX_UNPAGINATED_CALLS):
        response = getattr(client, method)(**call)
        yield from _items_of(without_response_metadata(response), items_path, single)
        key = continuation_of(response)
        if key is None:
            return
        request_key = _request_marker(client, op_name, key) if key != "IsTruncated" else None
        token = response.get(key) if request_key else None
        if request_key is None or not isinstance(token, str) or token in seen:
            if truncated is not None:
                truncated.append(key)
            return
        seen.add(token)
        call[request_key] = token
    if truncated is not None:
        truncated.append("call-ceiling")


def iter_aws_op(
    client: Any,
    op_name: str,
    items_path: str,
    *,
    walk: ListingWalk | None = None,
    truncated: list[str] | None = None,
    params: dict[str, Any] | None = None,
    single: bool = False,
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
        single: A path that resolves to one structure (no ``[]``) yields that structure as the one
            item, for a ``per`` child that is a ``Describe``; without it such a path yields nothing.
    """
    method = xform_name(op_name)
    kwargs = params or {}
    if walk is not None:
        yield from iter_listing(client, method, items_path, walk, **kwargs)
        return
    if client.can_paginate(method):
        for page in client.get_paginator(method).paginate(**kwargs):
            yield from _items_of(without_response_metadata(page), items_path, single)
        return
    yield from _walk_unpaginated(client, op_name, method, items_path, kwargs, truncated, single)


#: The slot a fanned-out child item carries its parent under, so ``fields`` can read the parent
#: (``_parent.Name``) for an identifier or ARN the child's own response does not hold.
PARENT_SLOT = "_parent"


def _iter_parents(per: dict[str, Any], default_service: str, client_for: Callable[[str], Any]) -> Iterator[Any]:
    """Yield the items of a ``per`` block, each carrying its own parent when it has one."""
    if "values" in per:
        yield from per["values"]
        return
    client = client_for(per.get("service", default_service))
    if "per" in per:
        for grand in _iter_parents(per["per"], per.get("service", default_service), client_for):
            yield from _children(client, per, grand, final=False)
        return
    truncated: list[str] = []
    for item in iter_aws_op(client, per["aws_op"], per["items_path"], params=dict(per.get("params", {})), truncated=truncated):
        if not per.get("where") or _passes(item, per["where"]):
            yield item
    _refuse_truncated(per["aws_op"], truncated)


def _refuse_truncated(op: str, truncated: list[str]) -> None:
    """A fan-out call whose listing stopped short fails the whole listing, never a short list that looks complete."""
    if truncated:
        raise SourceError(f"{op}: the listing did not reach its end ({truncated[0]}); a fan-out cannot be called complete")


def _child_items(client: Any, spec: dict[str, Any], params: dict[str, Any]) -> Iterator[Any]:
    """The items one child call returns; a path that lands on one structure is that one item.

    A ``Describe``/``Get`` answers with a single object, not a list, so ``items_path`` names it
    without a ``[]``. (A path that ends in ``[]`` is a list as ever.)
    """
    truncated: list[str] = []
    for item in iter_aws_op(client, spec["aws_op"], spec["items_path"], params=params, single=True, truncated=truncated):
        yield item
    _refuse_truncated(spec["aws_op"], truncated)


SELF_SLOT = "_self"


def _set_param(params: dict[str, Any], name: str, value: Any) -> None:
    """Set request parameter ``name``; a dotted name (``SchemaId.SchemaArn``) builds the nested structure."""
    *parents, leaf = name.split(".")
    node = params
    for key in parents:
        node = node.setdefault(key, {})
    node[leaf] = value


def _bound_value(parent: Any, path: Any) -> Any:
    """One ``bind`` value: a path string, or ``{path, list: true}`` for a list-typed request parameter (a scalar is wrapped, a list kept)."""
    if isinstance(path, dict):
        value = eval_path(parent, path["path"])
        if path.get("list") and value not in (None, "", []):
            # A scalar becomes a one-element list; a path that already projects a list (a service's task set ARNs) is the list.
            return value if isinstance(value, list) else [value]
        return value
    return eval_path(parent, path)


def _passes(item: Any, where: list[dict[str, Any]]) -> bool:
    """``item`` satisfies every condition of a ``where`` block (``equals``, ``not_equals``, ``in``, ``prefix``, ``contains``)."""
    for cond in where:
        value = eval_path(item, cond["path"])
        if "equals" in cond and value != cond["equals"]:
            return False
        if "not_equals" in cond and value == cond["not_equals"]:
            return False
        if "in" in cond and value not in cond["in"]:
            return False
        if "prefix" in cond and not (isinstance(value, str) and value.startswith(cond["prefix"])):
            return False
        if "contains" in cond and not (isinstance(value, str) and cond["contains"] in value):
            return False
    return True


def _children(client: Any, spec: dict[str, Any], parent: Any, *, final: bool = True) -> Iterator[Any]:
    """One call of ``spec`` for ``parent``: its ``bind`` pulls the request parameters off the parent.

    A child of a middle level may be a bare string (a list of names): it is carried as
    ``{"_self": name, "_parent": parent}`` so the next level can bind both (``_self``, ``_parent``).
    The last level's items must be structures.
    """
    bound = {name: _bound_value(parent, path) for name, path in spec["bind"].items()}
    missing = [name for name, value in bound.items() if value in (None, "", [])]
    if missing:
        raise SourceError(f"{spec['aws_op']}: a parent item has no value for {', '.join(missing)} (bind path unresolved)")
    params = dict(spec.get("params", {}))
    for name, value in bound.items():
        _set_param(params, name, value)
    where = spec.get("where")
    for item in _child_items(client, spec, params):
        if where and not _passes(item, where):
            continue
        if not isinstance(item, dict):
            if final:
                raise SourceError(
                    f"{spec['aws_op']}: a fan-out item must be a structure to carry its parent, got {type(item).__name__}"
                )
            yield {SELF_SLOT: item, PARENT_SLOT: parent}
            continue
        yield {**item, PARENT_SLOT: parent}


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


#: A literal ``params`` value that stands for the account being collected: a list call that asks
#: for the account id (QuickSight's ``AwsAccountId``) names it here instead of hard-coding one.
ACCOUNT_PARAM = "$account_id"


def _with_account(node: Any, account_id: str | None) -> Any:
    """``node`` with every ``ACCOUNT_PARAM`` in a ``params`` mapping replaced by the account id."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key == "params" and isinstance(value, dict):
                out[key] = {name: _account_value(v, account_id) for name, v in value.items()}
            else:
                out[key] = _with_account(value, account_id)
        return out
    return node


def _account_value(value: Any, account_id: str | None) -> Any:
    if value != ACCOUNT_PARAM:
        return value
    if not account_id:
        raise SourceError("a source asks for the account id but the collector has none")
    return account_id


def _iter_raw(
    entry: dict[str, Any],
    *,
    client_for: Callable[[str], Any],
    custom_fns: CustomFnRegistry,
    fn_context: Any = None,
    walk: ListingWalk | None = None,
    truncated: list[str] | None = None,
    account_id: str | None = None,
) -> Iterator[Any]:
    """Drive a manifest entry's ``source``, yielding raw items, before any ``derive``.

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
        account_id: The account being collected, substituted for ``ACCOUNT_PARAM`` in ``params``.
        truncated: See :func:`iter_aws_op`. A ``custom_fn`` reports nothing here
            (tap-plugin-aws-core#49): the engine cannot see inside one, so a region-scoped
            completeness claim is an ``aws_op`` entry only.
    """
    source = _with_account(entry["source"], account_id)
    if "per" in source:
        yield from iter_fanout({**entry, "source": source}, client_for=client_for)
        return
    if "aws_op" in source:
        client = client_for(entry["service"])
        for item in iter_aws_op(
            client, source["aws_op"], entry["items_path"], walk=walk, truncated=truncated, params=source.get("params")
        ):
            if not source.get("where") or _passes(item, source["where"]):
                yield item
        return
    fn = custom_fns.get(source["custom_fn"])
    # Pass client_for through so regional custom_fns can build region-bound
    # clients without inventing their own region resolution. Global custom_fns
    # (route53, the s3 list-buckets head) accept it as a kwarg and ignore it.
    if walk is not None:
        yield from fn(fn_context, client_for=client_for, walk=walk)
        return
    yield from fn(fn_context, client_for=client_for)


#: A ``{name}`` in a ``derive`` template: ``partition``, ``region`` and ``account`` are the scope
#: being collected, anything else is a path on the item.
_TEMPLATE_FIELD = re.compile(r"\{([^{}]+)\}")
SCOPE_FIELDS: tuple[str, ...] = ("partition", "region", "account")


def render_template(template: str, item: Any, scope: dict[str, str | None]) -> str:
    """``template`` with each ``{name}`` filled from the scope or the item, or a :class:`SourceError`.

    A value that is missing or empty fails the item loudly: a half-built identifier, an ARN with a
    hole in it, would be worse than a type that reads as not collected.
    """

    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        value = scope.get(name) if name in SCOPE_FIELDS else eval_path(item, name)
        if value in (None, "", []) or isinstance(value, (dict, list)):
            raise SourceError(f"derive template {template!r}: no value for {{{name}}}")
        return str(value)

    return _TEMPLATE_FIELD.sub(fill, template)


def derived_keys(entry: dict[str, Any]) -> tuple[str, ...]:
    """The item keys an entry's ``derive`` block adds."""
    return tuple(entry.get("derive") or ())


def iter_source(
    entry: dict[str, Any],
    *,
    client_for: Callable[[str], Any],
    custom_fns: CustomFnRegistry,
    fn_context: Any = None,
    walk: ListingWalk | None = None,
    truncated: list[str] | None = None,
    account_id: str | None = None,
    scope: dict[str, str | None] | None = None,
) -> Iterator[Any]:
    """Drive a manifest entry's ``source`` and add its ``derive`` keys, yielding the items.

    ``derive`` maps a new item key to a template (``arn:{partition}:glue:{region}:{account}:job/{Name}``),
    for a resource the listing names but does not give an ARN, so that ``natural_key``, ``fields`` and
    the tags lane can read the built identifier like any other member (``req-aws-collector-source-8``).
    ``scope`` carries the ``partition``, ``region`` and ``account`` those templates fill from; an
    ``account_id`` given without it stands for the account alone.
    """
    derive = entry.get("derive")
    items = _iter_raw(
        entry,
        client_for=client_for,
        custom_fns=custom_fns,
        fn_context=fn_context,
        walk=walk,
        truncated=truncated,
        account_id=account_id,
    )
    if not derive:
        yield from items
        return
    facts = {"account": account_id, **(scope or {})}
    for item in items:
        if not isinstance(item, dict):
            raise SourceError(f"{entry['entity_type']}: derive needs structure items, got {type(item).__name__}")
        yield {**item, **{key: render_template(template, item, facts) for key, template in derive.items()}}
