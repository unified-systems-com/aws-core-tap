"""Which aws_core node an ARN names, whatever its type (aws-core-tap#242).

Spec: specs/spec-aws-core-landing-zone.md (``req-aws-landing-zone-findings-2``), resting on the ARN
declarations of ``req-aws-collector-identity-10`` and ``-11`` (specs/spec-aws-core-collector-v0.md).

A finding names the resource it concerns by ARN (a Security Hub ``Resources[].Id``; later an OCSF
``resources[].uid``). Nothing here is a table of types. The answer is read from two declarations the
plugin already keeps:

- each model's ``ARN_RESOURCE`` (``"<service>:<resource>"`` in AWS's Service Authorization Reference)
  and ``NATURAL_KEY``, read from the entity registry. A type is **keyed by its ARN** when its key is
  one field and that field holds the ARN: named ``arn``, or ``<something>_arn`` until every such field
  is renamed (``req-aws-collector-identity-10``);
- ``arn_formats.json``, the reference's ARN formats for every resource type a model names.

An ARN resolves to ``(entity type, the ARN)`` when exactly one vendored format matches it most
specifically (the most literal characters, so ``…/restapis/${RestApiId}/stages/${StageName}`` beats
``…/restapis/${RestApiId}``), that format's resource type belongs to exactly one model, and that model
is keyed by its ARN. Anything else is ``None``: an ARN no format matches, two formats that match equally
(a Lambda alias and a version have the same shape), a resource type several models share (a
CloudWatch alarm, a composite alarm and a log alarm), or a type keyed by something other than its
ARN (an EC2 instance by its instance id). Every vendored format takes part in the match, keyed by ARN
or not, so a more specific format of a type this resolver cannot key wins and yields ``None`` rather
than letting a looser one claim the ARN.

A wrong answer cannot attach a finding to the wrong row: the key is the ARN itself, which names one
resource across every partition, account and region (``req-aws-collector-identity-8``). The worst an
over-eager match does is name a node that is not on the grid, and core skips that edge as it skips any
reference to an uncollected target.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .partition import parse_arn

#: The vendored formats, rebuilt by ``iam_policy.py --refresh-arns`` (the same file as
#: ``iam_policy.ARN_FORMATS``; named here so resolving an ARN does not import the refresh tooling).
ARN_FORMATS = Path(__file__).resolve().parent / "arn_formats.json"
#: The app whose models this resolver answers for.
APP_LABEL = "aws_core"

#: A placeholder in a reference format: ``${Name}``, or the policy wildcard ``*`` some formats end in
#: (``dms:Endpoint``'s ``…:endpoint:*``), which in a real ARN stands for one resource id.
_PLACEHOLDER = re.compile(r"\$\{(\w+)\}|\*")
#: A placeholder that is the whole region or account part may be empty in a real ARN (a global service's region,
#: an S3 bucket's account), whatever the reference names it (``${Account}``, ``${AccountId}``, ...).
_MAY_BE_EMPTY = "[^:]*"
_NON_EMPTY = "[^:]+"


@dataclass(frozen=True)
class _Format:
    resource: str
    pattern: re.Pattern[str]
    #: Characters of the format that are not placeholders: the more, the more specific.
    literal: int


def compile_format(resource: str, fmt: str) -> _Format:
    """One reference format as a whole-ARN pattern. A placeholder matches any run without a colon (a
    name may hold slashes: an IAM path, a log group name); one that is the whole region or account part
    may also be empty."""
    head = fmt.split(":", 5)
    if len(head) < 6:
        raise ValueError(f"{resource}: {fmt!r} is not an ARN format")
    parts: list[str] = []
    literal = 0
    for index, segment in enumerate(head):
        if index:
            parts.append(":")
            literal += 1
        if index in (3, 4) and _PLACEHOLDER.fullmatch(segment):
            parts.append(_MAY_BE_EMPTY)
            continue
        position = 0
        for match in _PLACEHOLDER.finditer(segment):
            text = segment[position : match.start()]
            parts.append(re.escape(text))
            literal += len(text)
            parts.append(_NON_EMPTY)
            position = match.end()
        parts.append(re.escape(segment[position:]))
        literal += len(segment) - position
    return _Format(resource, re.compile("".join(parts)), literal)


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


class ArnResolver:
    """Resolve an ARN to the ``(entity type, natural key)`` of the node keyed by it, or ``None``."""

    def __init__(self, formats: dict[str, list[str]], keyed: dict[str, list[str]]) -> None:
        self._by_service: dict[str, list[_Format]] = {}
        for resource, resource_formats in formats.items():
            for fmt in resource_formats:
                self._by_service.setdefault(_service_of(fmt), []).append(compile_format(resource, fmt))
        self._target = {resource: types[0] for resource, types in keyed.items() if len(set(types)) == 1}

    def resource_of(self, arn: str) -> str | None:
        """The one ARN resource type whose format matches ``arn`` most specifically, or ``None``."""
        parsed = parse_arn(arn)
        if parsed is None:
            return None
        hits = [f for f in self._by_service.get(parsed.service, []) if f.pattern.fullmatch(arn)]
        if not hits:
            return None
        best = max(f.literal for f in hits)
        top = {f.resource for f in hits if f.literal == best}
        return top.pop() if len(top) == 1 else None

    def resolve(self, arn: str) -> tuple[str, str] | None:
        """``(entity type, arn)`` of the node ``arn`` names, or ``None`` when no single ARN-keyed type does."""
        resource = self.resource_of(arn)
        entity_type = self._target.get(resource) if resource else None
        return (entity_type, arn) if entity_type else None


def _registered_models() -> list[type]:
    from tap_grid.registry import get_model_class, list_entity_types

    models: list[Any] = [get_model_class(t) for t in list_entity_types()]
    return [m for m in models if getattr(getattr(m, "_meta", None), "app_label", None) == APP_LABEL]


@lru_cache(maxsize=1)
def default_resolver() -> ArnResolver:
    """The resolver over this plugin's registered models and its vendored formats, built once."""
    formats = json.loads(ARN_FORMATS.read_text())["resources"]
    return ArnResolver(formats, arn_keyed_types(_registered_models()))


def resolve_arn(arn: str) -> tuple[str, str] | None:
    """``(entity type, natural key)`` of the aws_core node keyed by ``arn``, or ``None``."""
    return default_resolver().resolve(arn)


__all__ = ["ARN_FORMATS", "ArnResolver", "arn_keyed_types", "compile_format", "default_resolver", "holds_arn", "resolve_arn"]
