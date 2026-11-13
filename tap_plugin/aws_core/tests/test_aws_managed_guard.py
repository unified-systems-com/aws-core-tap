"""AWS-managed resources are outside deletion checking (George 2026-11-12, aws-build Q60b).

A resource AWS itself owns carries ``aws.account = "aws"`` (its ARN's account segment). These guards exist "in case
anyone doesn't rtfm": the scope check refuses that owner for every customer credential, and EVERY registered
falsifier, including one added later, declines such a candidate without a single AWS call.
"""

from __future__ import annotations

import tomllib
import uuid
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tap_plugin.aws_core import falsifiers as aws_falsifiers

from tap_grid.falsifiers import UNDETERMINED, Candidate, FalsifyContext

pytestmark = pytest.mark.spec("req-aws-core-account-dimension-10")

MANIFEST = Path(__file__).resolve().parent.parent / "tap-plugin.toml"


def _registered() -> list[tuple[str, type]]:
    table = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))["falsifiers"]
    found = []
    for entity_type, dotted in sorted(table.items()):
        module, _, name = dotted.rpartition(".")
        found.append((entity_type, getattr(import_module(module), name)))
    return found


def _candidate(entity_type: str) -> Candidate:
    return Candidate(
        entity_id=uuid.uuid4(),
        entity_type=entity_type,
        reason="dropped_from_observation",
        surface=0,
        relation="fixture",
        subject=None,
        edge_type=None,
        parent=uuid.uuid4(),
        interval_first=None,
    )


class _NoAws:
    """A session whose every client call fails the test: an AWS-owned candidate must never reach AWS."""

    def client(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"an AWS-owned candidate reached AWS: client{args}")

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"an AWS-owned candidate touched the session: {name}")


@pytest.mark.parametrize("credential", ["111122223333", "444455556666"])
def test_the_scope_check_refuses_the_aws_owner_for_any_customer_account(credential: str) -> None:
    falsifier = aws_falsifiers.SubnetFalsifier(session=_NoAws(), account_id=credential)
    verdict = falsifier._scope_check(_candidate("aws_core__aws_subnet"), credential, aws_falsifiers.AWS_MANAGED_OWNER)
    assert verdict is not None
    assert verdict.verdict == UNDETERMINED and verdict.reason == "scope_unknown"


def test_the_sweep_sees_every_registered_falsifier() -> None:
    assert len(_registered()) >= 30, "the [falsifiers] table was not read"


@pytest.mark.parametrize(("entity_type", "cls"), _registered(), ids=[t for t, _c in _registered()])
def test_every_falsifier_declines_an_aws_owned_candidate_without_an_aws_call(
    entity_type: str, cls: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = SimpleNamespace(entity=SimpleNamespace(dimensions={"aws.account": "aws", "aws.region": "us-east-1"}))
    monkeypatch.setattr(aws_falsifiers, "_row_of", lambda entity_id: row)
    falsifier = cls(session=_NoAws(), account_id="111122223333")
    [verdict] = falsifier.batch_falsify([_candidate(entity_type)], FalsifyContext(batch_id=str(uuid.uuid4()), statement=None))
    assert verdict.verdict == UNDETERMINED
    assert verdict.reason == "scope_unknown"
