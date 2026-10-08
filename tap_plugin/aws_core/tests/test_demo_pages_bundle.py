"""The demo pages in the pages bundle (aws-core-tap#75; req-aws-core-page-scps, -security-groups, -baseline,
req-aws-core-page-dashboard-2, req-aws-core-page-network-5).

Pure JSON: no database. Checks what a clean import alone would not: every slot has its panel, every table
column names a RETURN alias of its search, every custom panel names a registered type's template, and the
security-group flags use the same patterns as the count tiles.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from tap_plugin.aws_core.panels.baseline import AwsBaselinePanelType
from tap_plugin.aws_core.panels.counts import ALL_PROTOCOLS_RE, BY_KEY, OPEN_TO_INTERNET_RE, AwsCountsPanelType
from tap_plugin.aws_core.panels.scp_rulebook import AwsScpRulebookPanelType

BUNDLE = Path(__file__).resolve().parent.parent / "grift" / "pages.grift.json"
CUSTOM_VIEWS = {t.view for t in (AwsCountsPanelType, AwsBaselinePanelType, AwsScpRulebookPanelType)}
STANDARD_VIEWS = {"tap_web/panels/table_panel.html", "tap_web/panels/text_panel.html", "tap_viz/panels/graph_panel.html"}


@pytest.fixture(scope="module")
def batch() -> dict[str, Any]:
    return json.loads(BUNDLE.read_text())["batches"][0]


def _pages(batch: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["node"]["slug"]: n for n in batch["nodes"] if n["entity"]["entity_type"] == "page"}


def _mounts(batch: dict[str, Any], page_id: str) -> dict[str, str]:
    return {e["edge"]["properties"]["hotlink"]["value"]: e["edge"]["to_entity_id"] for e in batch["edges"]
            if e["edge"]["edge_type"] == "USES_PANEL" and e["edge"]["from_entity_id"] == page_id}


def _slots(page: dict[str, Any]) -> list[str]:
    return [r["panel-id"] for c in page["node"]["layout"]["columns"].values() for r in c["rows"].values()]


def test_ids_are_unique_and_every_edge_lands_in_the_bundle(batch: dict[str, Any]) -> None:
    ids = [n["entity"]["entity_id"] for n in batch["nodes"]] + [e["entity"]["entity_id"] for e in batch["edges"]]
    assert len(ids) == len(set(ids))
    nodes = {n["entity"]["entity_id"] for n in batch["nodes"]}
    for e in batch["edges"]:
        assert e["edge"]["from_entity_id"] in nodes and e["edge"]["to_entity_id"] in nodes, e["entity"]["name"]


@pytest.mark.parametrize(("slug", "weight"), [("/aws/scps", 230), ("/aws/security-groups", 240), ("/aws/baseline", 250)])
def test_demo_pages_nest_under_aws_by_url(batch: dict[str, Any], slug: str, weight: int) -> None:
    page = _pages(batch)[slug]
    assert page["node"]["nav_weight"] == weight
    assert page["node"]["layout"]["full_bleed"] is True


def test_every_slot_has_exactly_its_panel(batch: dict[str, Any]) -> None:
    """The USES_PANEL hotlink is exact: the layout's slots and the page's edges are the same set."""
    for slug, page in _pages(batch).items():
        slots = _slots(page)
        assert len(slots) == len(set(slots)), slug
        assert set(_mounts(batch, page["entity"]["entity_id"])) == set(slots), slug


def test_side_columns_on_the_dashboard_and_network_pages(batch: dict[str, Any]) -> None:
    pages = _pages(batch)
    aws = pages["/aws"]["node"]["layout"]["columns"]
    assert [r["panel-id"] for r in aws["col-1"]["rows"].values()] == ["counts", "estate", "per-ou", "scope"]
    assert [r["panel-id"] for r in aws["col-2-iam"]["rows"].values()] == [
        "iam", "roles-services", "roles-accounts", "roles-anyone", "roles-federated", "roles-other", "users-no-mfa"]
    net = pages["/aws/network"]["node"]["layout"]["columns"]
    assert [r["panel-id"] for r in net["col-2-exposure"]["rows"].values()] == ["exposure", "default-vpcs", "public-subnets"]


def test_scp_page_reuses_the_attachments_panel(batch: dict[str, Any]) -> None:
    pages = _pages(batch)
    org = _mounts(batch, pages["/aws/organization"]["entity"]["entity_id"])
    scps = _mounts(batch, pages["/aws/scps"]["entity"]["entity_id"])
    assert org["scp"] == scps["attachments"]


def test_panels_name_a_known_template(batch: dict[str, Any]) -> None:
    for n in batch["nodes"]:
        if n["entity"]["entity_type"] == "panel":
            assert n["node"]["view"] in CUSTOM_VIEWS | STANDARD_VIEWS, n["node"]["slug"]


def test_count_panels_name_catalogue_tiles(batch: dict[str, Any]) -> None:
    for n in batch["nodes"]:
        if n["node"].get("view") == AwsCountsPanelType.view:
            assert all(k in BY_KEY for k in n["node"]["config"].get("tiles", [])), n["node"]["slug"]


def _search_of(batch: dict[str, Any], panel_id: str) -> str | None:
    by_id = {n["entity"]["entity_id"]: n for n in batch["nodes"]}
    found = [by_id[e["edge"]["to_entity_id"]] for e in batch["edges"]
             if e["edge"]["edge_type"] == "USES_SEARCH" and e["edge"]["from_entity_id"] == panel_id]
    return "\n".join(found[0]["node"]["definition"]["query"]) if found else None


def test_projection_table_columns_name_return_aliases(batch: dict[str, Any]) -> None:
    for n in batch["nodes"]:
        if n["node"].get("view") != "tap_web/panels/table_panel.html":
            continue
        query = _search_of(batch, n["entity"]["entity_id"])
        assert query is not None, n["node"]["slug"]
        aliases = set(re.findall(r"\bAS (\w+)", query))
        if not aliases:  # a node table (RETURN n): fields are envelope paths
            continue
        for col in n["node"]["config"]["columns"]:
            assert col["field"] in aliases, (n["node"]["slug"], col["field"])


def test_security_group_flag_tables_use_the_tile_patterns(batch: dict[str, Any]) -> None:
    queries = {n["entity"]["name"]: "\n".join(n["node"]["definition"]["query"]) for n in batch["nodes"]
               if n["entity"]["entity_type"] == "search"}
    assert f"IpPermissions =~ {json.dumps(OPEN_TO_INTERNET_RE)}" in queries["aws — Open to the internet"]
    assert f"IpPermissions =~ {json.dumps(ALL_PROTOCOLS_RE)}" in queries["aws — All-protocol inbound rules"]


def test_federated_roles_are_not_listed_as_same_account(batch: dict[str, Any]) -> None:
    """A role trusting a SAML or OIDC provider has its own table; the same-account table excludes it."""
    queries = {n["entity"]["name"]: "\n".join(n["node"]["definition"]["query"]) for n in batch["nodes"]
               if n["entity"]["entity_type"] == "search"}
    federated = 'r.data.configuration.AssumeRolePolicyDocument =~ "\\"Federated\\""'
    assert f"WHERE {federated}" in queries["aws — Assumed through a federated provider"]
    assert f"AND NOT {federated}" in queries["aws — Assumed only from this account"]
