"""aws-counts folds Gryphon envelopes into tiles (req-aws-core-panel-counts). Pure functions: no grid."""

from __future__ import annotations

from tap_plugin.aws_core.panels.counts import BY_KEY, CATALOGUE, boundary_tiles, fold_tile

DESIGN = {"dcom": "design"}


def _n(eid: str, dims: dict | None = None, **data: object) -> dict:
    return {"entity_id": eid, "dimensions": dims or {}, "data": data}


def test_catalogue_keys_are_unique() -> None:
    assert len(BY_KEY) == len(CATALOGUE)


def test_a_tile_counts_its_nodes_and_marks_all_design() -> None:
    tile = fold_tile(BY_KEY["vpcs"], {"nodes": [_n("a", DESIGN), _n("b", DESIGN)]})
    assert (tile["value"], tile["design"], tile["tone"]) == (2, True, "")


def test_a_mixed_count_is_not_marked_design() -> None:
    assert fold_tile(BY_KEY["vpcs"], {"nodes": [_n("a", DESIGN), _n("b")]})["design"] is False


def test_attention_only_when_nonzero() -> None:
    assert fold_tile(BY_KEY["internet_gateways"], {"nodes": [_n("a")]})["tone"] == "attention"
    assert fold_tile(BY_KEY["internet_gateways"], {"nodes": []})["tone"] == ""


def test_keep_filters_before_counting() -> None:
    env = {"nodes": [_n("a", scheme="internet-facing"), _n("b", scheme="internal"), _n("c")]}
    assert fold_tile(BY_KEY["internet_facing_load_balancers"], env)["value"] == 1
    buckets = {"nodes": [_n("a", public_access_blocked=False), _n("b", public_access_blocked=True)]}
    assert fold_tile(BY_KEY["public_buckets"], buckets)["value"] == 1


def test_boundary_membership_follows_the_ou_tree() -> None:
    accounts = [_n("acct-1", DESIGN), _n("acct-2", DESIGN), _n("acct-3", DESIGN)]
    tree = [
        {"child": "acct-1", "parent": "ou-tenant"},
        {"child": "ou-tenant", "parent": "ou-stage"},
        {"child": "acct-2", "parent": "ou-stage"},
        {"child": "acct-3", "parent": "ou-other"},
    ]
    scope = [{"member": "ou-stage", "boundary": "b1", "name": "staging"}, {"member": "ou-prod", "boundary": "b2", "name": "prod"}]
    tiles = {t["label"]: t for t in boundary_tiles(accounts, tree, scope)}
    assert tiles["Accounts in staging"]["value"] == 2
    assert tiles["Accounts in staging"]["design"] is True
    assert tiles["Accounts in prod"]["value"] == 0


def test_a_cycle_in_the_tree_terminates() -> None:
    tiles = boundary_tiles([_n("a")], [{"child": "a", "parent": "b"}, {"child": "b", "parent": "a"}],
                           [{"member": "b", "boundary": "x", "name": "x"}])
    assert tiles[0]["value"] == 1


def test_a_boundary_nothing_is_scoped_to_shows_zero() -> None:
    tiles = boundary_tiles([_n("a")], [], [], [{"entity_id": "b9", "name": "empty"}])
    assert [(t["label"], t["value"]) for t in tiles] == [("Accounts in empty", 0)]


def test_an_instance_without_tiles_shows_only_the_dashboard_set() -> None:
    """The tiles the demo pages add (aws-core-tap#75) appear only where an instance names them."""
    from tap_plugin.aws_core.panels.counts import DEFAULT_KEYS

    assert DEFAULT_KEYS == tuple(t.key for t in CATALOGUE[: len(DEFAULT_KEYS)])
    assert "security_groups" not in DEFAULT_KEYS and "users_without_mfa" not in DEFAULT_KEYS


def test_security_group_flags_match_the_rule_text_postgres_prints() -> None:
    """The open-to-the-internet and all-protocol tiles regex-match a rule list rendered as jsonb text."""
    import json
    import re

    from tap_plugin.aws_core.panels.counts import ALL_PROTOCOLS_RE, OPEN_TO_INTERNET_RE

    def as_jsonb_text(rules: list[dict]) -> str:  # Postgres prints jsonb with ", " and ": " separators
        return json.dumps(rules, separators=(", ", ": "))

    open_v4 = [{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]
    open_v6 = [{"IpProtocol": "tcp", "Ipv6Ranges": [{"CidrIpv6": "::/0"}]}]
    narrow = [{"IpProtocol": "tcp", "IpRanges": [{"CidrIp": "10.0.0.0/8"}, {"CidrIp": "10.0.0.0/0"}],
               "Ipv6Ranges": [{"CidrIpv6": "2001:db8::/0"}]}]
    all_proto = [{"IpProtocol": "-1", "UserIdGroupPairs": [{"GroupId": "sg-1"}]}]
    assert re.search(OPEN_TO_INTERNET_RE, as_jsonb_text(open_v4))
    assert re.search(OPEN_TO_INTERNET_RE, as_jsonb_text(open_v6))
    assert not re.search(OPEN_TO_INTERNET_RE, as_jsonb_text(narrow))
    assert re.search(ALL_PROTOCOLS_RE, as_jsonb_text(all_proto))
    assert not re.search(ALL_PROTOCOLS_RE, as_jsonb_text(open_v4))


def test_new_tiles_filter_in_gryphon_not_in_python() -> None:
    """Every added tile narrows with a Gryphon WHERE; none folds raw configuration in Python."""
    from tap_plugin.aws_core.panels.counts import DEFAULT_KEYS

    for tile in CATALOGUE:
        if tile.key in DEFAULT_KEYS or tile.key == "security_groups":
            continue
        assert " WHERE " in tile.query and tile.keep is None, tile.key
