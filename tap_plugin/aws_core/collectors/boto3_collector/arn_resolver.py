"""Which aws_core node an ARN names, whatever its type and however it is keyed (aws-core-tap#242, #252).

Spec: specs/spec-aws-core-landing-zone.md (``req-aws-landing-zone-findings-2``), resting on the identity rule of
``req-aws-collector-identity-2``, ``-10``, ``-11`` and ``-12`` (specs/spec-aws-core-collector-v0.md).

A finding names the resource it concerns by ARN (a Security Hub ``Resources[].Id``; later an OCSF
``resources[].uid``), or, for an account, by Security Hub's pseudo-id ``AWS::::Account:<id>``. Nothing here is a
table of types. The answer is read from three declarations the plugin already keeps:

- each model's ``ARN_RESOURCE`` (``"<service>:<resource>"`` in AWS's Service Authorization Reference) and
  ``NATURAL_KEY``, read from the entity registry. A type is **keyed by its ARN** when its key is one field and that
  field holds the ARN: named ``arn``, or ``<something>_arn`` until every such field is renamed
  (``req-aws-collector-identity-10``);
- each natively keyed type's **identity declaration** (``req-aws-collector-identity-12``): the manifest entry's
  ``identity`` block, or the model's ``AWS_IDENTITY`` for a type no manifest entry collects
  (``manifest.identity_declarations``). Its ``arn_key`` says how each key field is read from the ARN: a template
  over the reference format's placeholders (``{"vpc_id": "${VpcId}"}``, ``{"organization_id":
  "o-${OrganizationId}"}``), or ``@arn`` for a field that holds the whole ARN. Its ``other_ids`` are the non-ARN
  forms AWS names the resource by, in the same placeholders (``AWS::::Account:${AccountId}``);
- ``arn_formats.json``, the reference's ARN formats for every resource type a model names.

An ARN resolves when exactly one vendored format matches it most specifically (the most literal characters, so
``…/restapis/${RestApiId}/stages/${StageName}`` beats ``…/restapis/${RestApiId}``) and that format's resource type
belongs to exactly one model. A model keyed by its ARN answers ``(entity type, the ARN)``. A declared model answers
``(entity type, its key)``, each key field filled from the matched format's placeholders by its template; a key
of several fields is written as one JSON object (``identity.composite_natural_key``), the form an edge endpoint
names a composite-key node by. A field whose template names a placeholder the matched format does not have, or
whose placeholder matched nothing (a global ARN's empty region), leaves the ARN unresolved.

**Account and region columns.** A key column for the account or region (a GuardDuty detector's ``account_id`` and
``region``) is filled from the ARN's own account and region segments, through the same declared template
(``${Account}``, ``${Region}``), and from nowhere else. The resolver never substitutes the run's account or region:
a finding may name another account's resource, and a key built from the run's scope would name a node that is not
that resource. An empty segment leaves the ARN unresolved rather than guessed.

Anything else is ``None``: an ARN no format matches, two formats that match equally (a Lambda alias and a version
have the same shape), a resource type several models share (a CloudWatch alarm, a composite alarm and a log alarm;
the four transit gateway attachment types), a type whose key the ARN does not carry (an Identity Center group's
identity store id), or a type keyed by a string the collector makes (``req-aws-collector-identity-12`` lists those
as pending aws-core-tap#253). Every vendored format takes part in the match, keyed or not, so a more specific format
of a type this resolver cannot key wins and yields ``None`` rather than letting a looser one claim the ARN.

A wrong answer cannot attach a finding to the wrong row. An ARN names one resource across every partition,
account and region (``req-aws-collector-identity-8``); a declared key is what its own model says identifies one
row, read from the ARN by the model's own declaration. The worst an over-eager match does is name a node that is
not on the grid, and core skips that edge as it skips any reference to an uncollected target.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .identity import composite_natural_key
from .partition import parse_arn

#: The vendored formats, rebuilt by ``iam_policy.py --refresh-arns`` (the same file as
#: ``iam_policy.ARN_FORMATS``; named here so resolving an ARN does not import the refresh tooling).
ARN_FORMATS = Path(__file__).resolve().parent / "arn_formats.json"
#: The app whose models this resolver answers for.
APP_LABEL = "aws_core"
#: The ``arn_key`` template for a key field that holds the whole ARN (a virtual MFA device's serial number).
WHOLE_ARN = "@arn"

#: A placeholder in a reference format: ``${Name}``, or the policy wildcard ``*`` some formats end in
#: (``dms:Endpoint``'s ``…:endpoint:*``), which in a real ARN stands for one resource id.
_PLACEHOLDER = re.compile(r"\$\{(\w+)\}|\*")
#: A placeholder that is the whole region or account part may be empty in a real ARN (a global service's region,
#: an S3 bucket's account), whatever the reference names it (``${Account}``, ``${AccountId}``, ...).
_MAY_BE_EMPTY = "([^:]*)"
_NON_EMPTY = "([^:]+)"
#: A ``${Name}`` reference inside an ``arn_key`` template.
_TEMPLATE_NAME = re.compile(r"\$\{(\w+)\}")


@dataclass(frozen=True)
class _Format:
    resource: str
    pattern: re.Pattern[str]
    #: Characters of the format that are not placeholders: the more, the more specific.
    literal: int
    #: The placeholder each capturing group of ``pattern`` stands for, in order (``None`` for a ``*`` wildcard).
    names: tuple[str | None, ...] = ()

    def values(self, match: re.Match[str]) -> dict[str, str]:
        """``{placeholder: matched text}``; a placeholder the format repeats keeps its first value."""
        out: dict[str, str] = {}
        for name, value in zip(self.names, match.groups(), strict=True):
            if name is not None:
                out.setdefault(name, value)
        return out


def compile_format(resource: str, fmt: str) -> _Format:
    """One reference format as a whole-ARN pattern. A placeholder matches any run without a colon (a name may hold
    slashes: an IAM path, a log group name); one that is the whole region or account part may also be empty. Every
    placeholder is captured, so a declared key can be read from the match."""
    head = fmt.split(":", 5)
    if len(head) < 6:
        raise ValueError(f"{resource}: {fmt!r} is not an ARN format")
    parts: list[str] = []
    names: list[str | None] = []
    literal = 0
    for index, segment in enumerate(head):
        if index:
            parts.append(":")
            literal += 1
        whole = _PLACEHOLDER.fullmatch(segment)
        if index in (3, 4) and whole:
            parts.append(_MAY_BE_EMPTY)
            names.append(whole.group(1))
            continue
        position = 0
        for match in _PLACEHOLDER.finditer(segment):
            text = segment[position : match.start()]
            parts.append(re.escape(text))
            literal += len(text)
            parts.append(_NON_EMPTY)
            names.append(match.group(1))
            position = match.end()
        parts.append(re.escape(segment[position:]))
        literal += len(segment) - position
    return _Format(resource, re.compile("".join(parts)), literal, tuple(names))


def compile_other_id(fmt: str) -> tuple[re.Pattern[str], tuple[str | None, ...]]:
    """A declared non-ARN id form (``AWS::::Account:${AccountId}``) as a whole-string pattern; each placeholder is a
    non-empty run without a colon."""
    parts: list[str] = []
    names: list[str | None] = []
    position = 0
    for match in _PLACEHOLDER.finditer(fmt):
        parts.append(re.escape(fmt[position : match.start()]))
        parts.append(_NON_EMPTY)
        names.append(match.group(1))
        position = match.end()
    parts.append(re.escape(fmt[position:]))
    return re.compile("".join(parts)), tuple(names)


def template_names(template: str) -> set[str]:
    """The placeholders an ``arn_key`` template reads (none for ``@arn``)."""
    return set() if template == WHOLE_ARN else set(_TEMPLATE_NAME.findall(template))


def render(template: str, values: Mapping[str, str], arn: str) -> str | None:
    """One key field's value from a template and the matched placeholders, or ``None`` when a placeholder it reads
    was not matched or matched nothing."""
    if template == WHOLE_ARN:
        return arn
    missing = False

    def fill(match: re.Match[str]) -> str:
        nonlocal missing
        value = values.get(match.group(1)) or ""
        missing = missing or not value
        return value

    rendered = _TEMPLATE_NAME.sub(fill, template)
    return None if missing or not rendered else rendered


def _service_of(fmt: str) -> str:
    """The service of a reference format, which the reference always writes literally."""
    return fmt.split(":", 3)[2]


def holds_arn(field_name: str) -> bool:
    """Whether a natural-key field holds the resource's ARN, by the plugin's naming of such fields."""
    return field_name == "arn" or field_name.endswith("_arn")


def arn_keyed_types(models: list[type]) -> dict[str, list[str]]:
    """``{ARN resource type: [entity types that name it]}`` over ``models``, each entry a type keyed by
    its ARN. A resource type with more than one entity type cannot say which one an ARN is."""
    named: dict[str, list[str]] = {}
    for model in models:
        resource = getattr(model, "ARN_RESOURCE", None)
        key = getattr(model, "NATURAL_KEY", None)
        entity_type = getattr(model, "ENTITY_TYPE", None)
        if not (isinstance(resource, str) and isinstance(entity_type, str) and isinstance(key, tuple)):
            continue
        if len(key) == 1 and holds_arn(key[0]):
            named.setdefault(resource, []).append(entity_type)
    return named


@dataclass(frozen=True)
class DeclaredKey:
    """How one natively keyed type's key is read from an id that names it."""

    entity_type: str
    #: The model's ``NATURAL_KEY``, in order.
    fields: tuple[str, ...]
    #: ``{key field: template}`` from the declaration's ``arn_key``.
    templates: Mapping[str, str]

    def key(self, values: Mapping[str, str], arn: str) -> str | None:
        """The natural key the matched placeholders give, or ``None`` when any field cannot be filled."""
        parts: dict[str, str] = {}
        for name in self.fields:
            template = self.templates.get(name)
            value = render(template, values, arn) if template is not None else None
            if value is None:
                return None
            parts[name] = value
        return parts[self.fields[0]] if len(self.fields) == 1 else composite_natural_key(parts)


def declared_keys(models: list[type], declarations: Mapping[str, Mapping[str, Any]]) -> dict[str, list[DeclaredKey]]:
    """``{ARN resource type: [declared keys of the types that name it]}`` over ``models``: every type with an
    ``arn_key`` in its identity declaration and an ``ARN_RESOURCE`` naming a resource type."""
    named: dict[str, list[DeclaredKey]] = {}
    for model in models:
        entity_type = getattr(model, "ENTITY_TYPE", None)
        resource = getattr(model, "ARN_RESOURCE", None)
        key = getattr(model, "NATURAL_KEY", None)
        templates = (declarations.get(entity_type) or {}).get("arn_key") if isinstance(entity_type, str) else None
        if isinstance(resource, str) and isinstance(key, tuple) and key and templates:
            named.setdefault(resource, []).append(DeclaredKey(str(entity_type), key, dict(templates)))
    return named


def other_id_keys(
    models: list[type], declarations: Mapping[str, Mapping[str, Any]]
) -> list[tuple[re.Pattern[str], tuple[str | None, ...], DeclaredKey]]:
    """Every declared non-ARN id form, compiled, with the declared key it gives."""
    out = []
    for model in models:
        entity_type = getattr(model, "ENTITY_TYPE", None)
        key = getattr(model, "NATURAL_KEY", None)
        declaration = (declarations.get(entity_type) if isinstance(entity_type, str) else None) or {}
        templates = declaration.get("arn_key")
        for fmt in declaration.get("other_ids") or []:
            if isinstance(key, tuple) and key and templates:
                pattern, names = compile_other_id(fmt)
                out.append((pattern, names, DeclaredKey(str(entity_type), key, dict(templates))))
    return out


class ArnResolver:
    """Resolve an ARN (or a declared non-ARN id) to the ``(entity type, natural key)`` of the node it names."""

    def __init__(
        self,
        formats: dict[str, list[str]],
        keyed: dict[str, list[str]],
        declared: dict[str, list[DeclaredKey]] | None = None,
        other_ids: list[tuple[re.Pattern[str], tuple[str | None, ...], DeclaredKey]] | None = None,
        claimants: dict[str, set[str]] | None = None,
    ) -> None:
        self._by_service: dict[str, list[_Format]] = {}
        for resource, resource_formats in formats.items():
            for fmt in resource_formats:
                self._by_service.setdefault(_service_of(fmt), []).append(compile_format(resource, fmt))
        declared = declared or {}
        claims: dict[str, set[str]] = {}
        for resource, types in keyed.items():
            claims.setdefault(resource, set()).update(types)
        for resource, keys in declared.items():
            claims.setdefault(resource, set()).update(k.entity_type for k in keys)
        # Every model naming the resource type is a claimant, keyed or not: a second model whose key the resolver
        # cannot read (a house string, an undeclared composite) still makes the ARN ambiguous (PR 254 review).
        for resource, types in (claimants or {}).items():
            claims.setdefault(resource, set()).update(types)
        # A resource type two models claim, by ARN, by declaration or merely by naming it, cannot say which one an ARN is.
        sole = {resource for resource, types in claims.items() if len(types) == 1}
        self._target = {r: keyed[r][0] for r in sole if r in keyed}
        self._declared = {r: declared[r][0] for r in sole if r in declared and r not in keyed}
        self._other_ids = list(other_ids or [])

    def _match(self, arn: str) -> list[tuple[_Format, re.Match[str]]] | None:
        """The most specific formats matching ``arn``, all of one resource type, each with its match; ``None`` when
        no single resource type does. Several formats of one type can tie; :meth:`resolve` takes a declared key only
        when every one of them reads the same key (PR 254 review)."""
        parsed = parse_arn(arn)
        if parsed is None:
            return None
        hits = [(f, m) for f in self._by_service.get(parsed.service, []) if (m := f.pattern.fullmatch(arn))]
        if not hits:
            return None
        best = max(f.literal for f, _ in hits)
        top = [(f, m) for f, m in hits if f.literal == best]
        if len({f.resource for f, _ in top}) != 1:
            return None
        return top

    def resource_of(self, arn: str) -> str | None:
        """The one ARN resource type whose format matches ``arn`` most specifically, or ``None``."""
        matched = self._match(arn)
        return matched[0][0].resource if matched else None

    def resolve(self, resource_id: str) -> tuple[str, str] | None:
        """``(entity type, natural key)`` of the node ``resource_id`` names: the ARN for a type keyed by it, the
        declared key read from it for a natively keyed type; ``None`` when no single keyed type does."""
        if not resource_id.startswith("arn:"):
            return self._resolve_other(resource_id)
        matched = self._match(resource_id)
        if matched is None:
            return None
        resource = matched[0][0].resource
        if resource in self._target:
            return self._target[resource], resource_id
        declared = self._declared.get(resource)
        if declared is None:
            return None
        # Tied formats of one type must agree: a key read from whichever format happens to come first is a guess.
        keys = {declared.key(fmt.values(match), resource_id) for fmt, match in matched}
        if len(keys) != 1:
            return None
        key = keys.pop()
        return (declared.entity_type, key) if key else None

    def _resolve_other(self, resource_id: str) -> tuple[str, str] | None:
        answers: set[tuple[str, str]] = set()
        for pattern, names, declared in self._other_ids:
            match = pattern.fullmatch(resource_id)
            if match is None:
                continue
            values: dict[str, str] = {}
            for name, value in zip(names, match.groups(), strict=True):
                if name is not None:
                    values.setdefault(name, value)
            key = declared.key(values, resource_id)
            if key:
                answers.add((declared.entity_type, key))
        return answers.pop() if len(answers) == 1 else None

    def targets(self) -> set[str]:
        """Every entity type some id can resolve to."""
        return (
            set(self._target.values())
            | {k.entity_type for k in self._declared.values()}
            | {declared.entity_type for _, _, declared in self._other_ids}
        )

    def arn_keyed(self) -> dict[str, str]:
        """``{resource type: entity type}`` for every type resolved by its ARN as the key."""
        return dict(self._target)

    def declared(self) -> dict[str, DeclaredKey]:
        """``{resource type: declared key}`` for every type resolved by its declared key."""
        return dict(self._declared)


def _registered_models() -> list[type]:
    from tap_grid.registry import get_model_class, list_entity_types

    models: list[Any] = [get_model_class(t) for t in list_entity_types()]
    return [m for m in models if getattr(getattr(m, "_meta", None), "app_label", None) == APP_LABEL]


def resource_claimants(models: list[type]) -> dict[str, set[str]]:
    """``{ARN resource type: {entity types}}`` over every model that names one in ``ARN_RESOURCE``, however keyed."""
    named: dict[str, set[str]] = {}
    for model in models:
        resource, entity_type = getattr(model, "ARN_RESOURCE", None), getattr(model, "ENTITY_TYPE", None)
        if isinstance(resource, str) and isinstance(entity_type, str):
            named.setdefault(resource, set()).add(entity_type)
    return named


@lru_cache(maxsize=1)
def default_resolver() -> ArnResolver:
    """The resolver over this plugin's registered models, their identity declarations and the vendored formats,
    built once."""
    from .manifest import identity_declarations

    formats = json.loads(ARN_FORMATS.read_text())["resources"]
    models = _registered_models()
    declarations = identity_declarations()
    return ArnResolver(
        formats,
        arn_keyed_types(models),
        declared_keys(models, declarations),
        other_id_keys(models, declarations),
        resource_claimants(models),
    )


def resolve_arn(resource_id: str) -> tuple[str, str] | None:
    """``(entity type, natural key)`` of the aws_core node ``resource_id`` (an ARN, or a declared non-ARN id such as
    ``AWS::::Account:<id>``) names, or ``None``."""
    return default_resolver().resolve(resource_id)


__all__ = [
    "ARN_FORMATS",
    "WHOLE_ARN",
    "ArnResolver",
    "DeclaredKey",
    "arn_keyed_types",
    "compile_format",
    "compile_other_id",
    "declared_keys",
    "default_resolver",
    "holds_arn",
    "other_id_keys",
    "render",
    "resolve_arn",
    "resource_claimants",
    "template_names",
]
