"""Log-group identity is region-safe (req-aws-collector-identity-2, req-aws-collector-edges-7).

A CloudWatch Logs group name is unique only within one account and region. Keyed by name, the same
name in ``us-gov-west-1`` and ``us-gov-east-1`` was one identity and the second region's group was
dropped as ``DUPLICATE_IDENTITY``. Keyed by its ARN, both land as two nodes, and each region's
Lambda ``WRITES_LOGS`` edge resolves to its own region's group.

Drives the real ``Boto3Collector.run()`` into a real grid with the AWS boundary stubbed per region.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from tap_plugin.aws_core.collectors.boto3_collector import collector as collector_mod
from tap_plugin.aws_core.collectors.boto3_collector import credentials as cred
from tap_plugin.aws_core.collectors.boto3_collector.collector import Boto3Collector
from tap_plugin.aws_core.tests.grid_keys import edge_between, node_id

from tap_cares.collectors.config import CollectorConfig
from tap_cares.secrets.models import Secret, SecretRef

_ACCOUNT = "111122223333"
_REGIONS = ["us-gov-west-1", "us-gov-east-1"]
_NAME = "/aws/lambda/shared-name"
_LG = "aws_core__aws_cloudwatch_log_group"


def _lg_arn(region: str) -> str:
    return f"arn:aws-us-gov:logs:{region}:{_ACCOUNT}:log-group:{_NAME}"


def _fn_arn(region: str) -> str:
    return f"arn:aws-us-gov:lambda:{region}:{_ACCOUNT}:function:shared-name"


class _EmptyPaginator:
    def paginate(self, **_kw: Any):
        yield {}


class _RegionClient:
    """A region-bound client: the same-named log group and Lambda in every region, each carrying
    that region's ARNs; every other op is an empty success."""

    def __init__(self, region: str) -> None:
        self._region = region

    def can_paginate(self, _method: str) -> bool:
        return False

    def get_paginator(self, _name: str) -> _EmptyPaginator:
        return _EmptyPaginator()

    def describe_log_groups(self, **_kw: Any) -> Any:
        return {
            "logGroups": [
                {"logGroupName": _NAME, "arn": _lg_arn(self._region) + ":*", "logGroupArn": _lg_arn(self._region)}
            ]
        }

    def list_functions(self, **_kw: Any) -> Any:
        return {
            "Functions": [
                {
                    "FunctionName": "shared-name",
                    "FunctionArn": _fn_arn(self._region),
                    "LoggingConfig": {"LogGroup": _NAME},
                }
            ]
        }

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda **_kw: {}


class _Events:
    def register(self, *_a: Any, **_k: Any) -> None:
        return None


class _Session:
    events = _Events()

    def client(self, _service: str, region_name: str | None = None, **_kw: Any) -> _RegionClient:
        return _RegionClient(region_name or _REGIONS[0])


@pytest.fixture
def _stub_govcloud(monkeypatch):
    secret = Secret(
        ref=SecretRef(scope="aws_core", key="boto_collector"),
        kind="aws_static_access_key",
        description="test",
        data={"access_key_id": "AKIA", "secret_access_key": "shh", "regions_allowed": _REGIONS},
        metadata={},
        source_path=Path("/dev/null"),
    )
    monkeypatch.setattr(cred, "resolve_secret", lambda _ref: secret)
    monkeypatch.setattr(collector_mod, "build_session", lambda _data: _Session())
    monkeypatch.setattr(
        collector_mod, "client_factory", lambda _s, region: (lambda _svc: _RegionClient(region))
    )
    monkeypatch.setattr(collector_mod, "caller_account_id", lambda *a, **k: _ACCOUNT)


@pytest.mark.django_db
def test_same_named_log_groups_in_two_regions_both_land(_stub_govcloud) -> None:
    from tap_grid.services import get_edge, get_node

    collector = Boto3Collector(
        CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7())
    )
    collector.run()

    assert collector.results["error"] == []
    duplicates = [w for w in collector.results["warn"] if w["message_code"] == "DUPLICATE_IDENTITY"]
    assert duplicates == []

    for region in _REGIONS:
        group = get_node(node_id(_LG, _lg_arn(region)))
        assert group.name == _NAME
        assert group.log_group_arn == _lg_arn(region)
        # Each region's Lambda writes to its own region's group, not the other one.
        edge = get_edge(
            edge_between("WRITES_LOGS__aws_core", "aws_core__aws_lambda", _fn_arn(region), _LG, _lg_arn(region)).entity_id
        )
        assert str(edge.from_entity_id) == str(node_id("aws_core__aws_lambda", _fn_arn(region)))
        assert str(edge.to_entity_id) == str(node_id(_LG, _lg_arn(region)))

    assert node_id(_LG, _lg_arn(_REGIONS[0])) != node_id(_LG, _lg_arn(_REGIONS[1]))
