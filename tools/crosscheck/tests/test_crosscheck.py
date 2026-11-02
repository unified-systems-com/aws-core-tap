"""Tests for tools/crosscheck. Synthetic mini source trees stand in for Cartography and aws_core, so the
tests need neither a Cartography clone nor Django; the last class checks the committed data files against
the real plugin tree so a rename here cannot leave the mapping stale."""

import json
import textwrap
from pathlib import Path

import pytest

import carto_reader
import crosscheck
import tap_reader
import weighting

ROOT = Path(__file__).resolve().parents[3]  # the aws-core-tap checkout


def _w(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))
    return path


def make_carto(root: Path) -> Path:
    m = root / "cartography/models"
    _w(m / "core/nodes.py", "class CartographyNodeSchema: ...\n")
    _w(m / "aws/shared_rels.py", '''
        class ToAccountRel:
            target_node_label: str = "AWSAccount"
            rel_label: str = "RESOURCE"
            direction: LinkDirection = LinkDirection.INWARD
        class ToSubnetRel:
            target_node_label: str = "AWSEC2Subnet"
            rel_label: str = "PART_OF_SUBNET"
            direction: LinkDirection = LinkDirection.OUTWARD
        class ToTagRel:
            target_node_label: str = "AWSTag"
            rel_label: str = "TAGGED"
            direction: LinkDirection = LinkDirection.INWARD
        class ToGhostRel:
            target_node_label: str = "AWSGhost"
            rel_label: str = "CONNECTED_TO"
            direction: LinkDirection = LinkDirection.OUTWARD
    ''')
    _w(m / "aws/rds.py", '''
        from shared_rels import ToAccountRel
        class RdsProps(CartographyNodeProperties):
            id: PropertyRef = PropertyRef("DBInstanceArn")
            engine: PropertyRef = PropertyRef("Engine")
            publicly_accessible: PropertyRef = PropertyRef("PubliclyAccessible")
            region: PropertyRef = PropertyRef("Region", set_in_kwargs=True)
            lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)
        class RdsToSubnetMatchLink(CartographyRelSchema):
            target_node_label: str = "AWSEC2Subnet"
            source_node_label: str = "AWSRDSInstance"
            rel_label: str = "ATTACHED_TO"
            direction: LinkDirection = LinkDirection.OUTWARD
        class RdsSchema(CartographyNodeSchema):
            label: str = "AWSRDSInstance"
            properties: RdsProps = RdsProps()
            sub_resource_relationship: ToAccountRel = ToAccountRel()
            other_relationships: OtherRelationships = OtherRelationships([ToSubnetRel(), ToTagRel(), ToGhostRel()])
    ''')
    _w(m / "aws/subnet.py", '''
        class SubnetProps(CartographyNodeProperties):
            id: PropertyRef = PropertyRef("SubnetId")
            cidr: PropertyRef = PropertyRef("CidrBlock")
        class SubnetSchema(CartographyNodeSchema):
            label: str = "AWSEC2Subnet"
            extra_node_labels: ExtraNodeLabels = ExtraNodeLabels(["AWSNetwork"])
            properties: SubnetProps = SubnetProps()
        class SubnetLinkSchema(CartographyNodeSchema):
            label: str = "AWSEC2Subnet"
            properties: SubnetProps = SubnetProps()
    ''')
    _w(m / "aws/account.py", '''
        class AccountProps(CartographyNodeProperties):
            id: PropertyRef = PropertyRef("AWS_ID")
        class AccountSchema(CartographyNodeSchema):
            label: str = "AWSAccount"
            properties: AccountProps = AccountProps()
    ''')
    _w(m / "aws/widget.py", '''
        class WidgetProps(CartographyNodeProperties):
            id: PropertyRef = PropertyRef("WidgetId")
        class WidgetSchema(CartographyNodeSchema):
            label: str = "AWSWidget"
            properties: WidgetProps = WidgetProps()
    ''')
    _w(m / "aws/tag.py", '''
        class TagProps(CartographyNodeProperties):
            id: PropertyRef = PropertyRef("Key")
        class TagSchema(CartographyNodeSchema):
            label: str = "AWSTag"
            properties: TagProps = TagProps()
    ''')
    _w(root / "cartography/intel/aws/rds.py", '''
        def get(session):
            client = session.client("rds")
            client.describe_db_instances()
            client.describe_db_clusters()
            session.get_paginator("describe_db_snapshots")
    ''')
    return root


def make_plugin(root: Path, rds_fields=None, persist=False) -> Path:
    pkg = root / "tap_plugin/aws_core"
    _w(pkg / "models/rds.py", '''
        class Rds:
            ENTITY_TYPE: ClassVar[str] = "aws_core__aws_rds_instance"
            NATURAL_KEY: ClassVar[tuple[str, ...]] = ("db_instance_arn",)
            FIELD_CRUD_SCHEMA: ClassVar[dict] = {"name": {}, "engine": {}, "db_instance_arn": {}, "status": {}, "tags": {}}
    ''')
    _w(pkg / "models/subnet.py", '''
        class Subnet:
            ENTITY_TYPE: ClassVar[str] = "aws_core__aws_subnet"
            NATURAL_KEY: ClassVar[tuple[str, ...]] = ("subnet_id",)
            FIELD_CRUD_SCHEMA: ClassVar[dict] = {"name": {}, "subnet_id": {}}
            OUTBOUND_EDGES: ClassVar[list] = []
    ''')
    entry = {
        "entity_type": "aws_core__aws_rds_instance",
        "service": "rds",
        "persist_configuration": persist,
        "source": {"aws_op": "DescribeDBInstances"},
        "natural_key": "DBInstanceArn",
        "fields": rds_fields or {"engine": "Engine", "db_instance_arn": "DBInstanceArn"},
        "tags": {"source": "field"},
        "hydrate": [{"key": "x", "op": "GetThing"}],
        "edges": [{"value_path": "SubnetId", "target_type": "aws_core__aws_subnet", "edge_type": "RESIDES_IN_SUBNET__aws_core", "direction": "outbound"}],
    }
    _w(pkg / "collectors/boto3_collector/aws_resource_manifest.json", json.dumps({"manifest_version": 1, "entries": [entry]}))
    _w(pkg / "collectors/boto3_collector/custom.py", "def f(c):\n    c.list_tags_for_resource()\n    _pages(c, \"list_subscriptions\")\n")
    _w(pkg / "edges/RESIDES_IN_SUBNET.edge.json", json.dumps({"slug": "RESIDES_IN_SUBNET__aws_core", "sources": ["aws_core__aws_rds_instance"], "targets": ["aws_core__aws_subnet"]}))
    _w(pkg / "ledger/aws_coverage_ledger.json", json.dumps({"rows": [
        {"type_name": "AWS::RDS::DBInstance", "tier": "both", "entity_types": ["aws_core__aws_rds_instance"], "state": "collected-unverified"},
        {"type_name": "AWS::RDS::CustomDBEngineVersion", "tier": "both", "entity_types": [], "state": "unclassified"},
        {"type_name": "AWS::RDS::DBProxy", "tier": "both", "entity_types": [], "state": "excluded"},
        {"type_name": "AWS::RDS::DBCluster", "tier": "both", "entity_types": [], "state": "collected-verified"},
        {"type_name": "AWS::RDS::DBSubnetGroup", "tier": "both", "entity_types": [], "state": "modeled"},
        {"type_name": "AWS::Macie::Session", "tier": "commercial-only", "entity_types": [], "state": "unclassified"},
        {"type_name": "AWS::Other::Thing", "tier": "both", "entity_types": [], "state": "unclassified"},
    ]}))
    return root


@pytest.fixture
def carto(tmp_path):
    return make_carto(tmp_path / "carto")


@pytest.fixture
def plugin(tmp_path):
    return make_plugin(tmp_path / "plugin")


def wfile(tmp_path, rules, **kw):
    d = {"name": "t", "version": 1, "description": "d", "default_weight": 0, "rules": rules, **kw}
    p = tmp_path / "w.json"
    p.write_text(json.dumps(d))
    return p


class TestCartoReader:
    def test_nodes_merge_by_label_and_skip_infrastructure_keys_later(self, carto):
        models = carto_reader.read_models(carto)
        assert set(models["nodes"]) == {"AWSRDSInstance", "AWSEC2Subnet", "AWSTag", "AWSAccount", "AWSWidget"}
        assert models["nodes"]["AWSRDSInstance"]["properties"]["engine"]["key"] == "Engine"
        assert models["nodes"]["AWSRDSInstance"]["properties"]["region"]["kwargs"] is True
        assert len(models["nodes"]["AWSEC2Subnet"]["files"]) == 2  # the label is declared by two schemas

    def test_a_relationship_class_imported_from_another_file_resolves(self, carto):
        rels = carto_reader.read_models(carto)["nodes"]["AWSRDSInstance"]["rels"]
        assert {(r["rel"], r["target"]) for r in rels} >= {("RESOURCE", "AWSAccount"), ("PART_OF_SUBNET", "AWSEC2Subnet")}

    def test_a_label_split_over_two_schemas_does_not_repeat_its_relationships(self, tmp_path):
        root = make_carto(tmp_path / "c")
        assert len(carto_reader.read_models(root)["nodes"]["AWSEC2Subnet"]["rels"]) == 0

    def test_extra_labels_count_as_defined(self, carto):
        assert "AWSNetwork" in carto_reader.read_models(carto)["all_labels"]

    def test_self_check_flags_a_target_no_schema_defines(self, carto):
        ids = [f["id"] for f in carto_reader.self_checks(carto_reader.read_models(carto))]
        assert ids == ["dangling-target:AWSRDSInstance:CONNECTED_TO:AWSGhost"]

    def test_operations_are_normalised_and_paginators_count(self, carto):
        ops = carto_reader.read_ops(carto)
        assert ops == {("rds", "describedbinstances"), ("rds", "describedbclusters"), ("rds", "describedbsnapshots")}

    def test_a_standalone_match_link_joins_its_source_node(self, carto):
        rels = carto_reader.read_models(carto)["nodes"]["AWSRDSInstance"]["rels"]
        assert [r for r in rels if r["kind"] == "standalone"] == [
            {"kind": "standalone", "class": "RdsToSubnetMatchLink", "target": "AWSEC2Subnet", "rel": "ATTACHED_TO", "direction": "OUTWARD"}
        ]

    def test_a_tree_with_no_aws_schemas_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            carto_reader.read_models(tmp_path)
        _w(tmp_path / "cartography/models/aws/empty.py", "x = 1\n")
        with pytest.raises(ValueError):
            carto_reader.read_models(tmp_path)

    def test_nothing_is_executed(self, carto, tmp_path):
        marker = tmp_path / "ran"
        _w(carto / "cartography/models/aws/evil.py", f"open({str(marker)!r}, 'w')\n")
        carto_reader.read_models(carto)
        assert not marker.exists()


class TestCommitOf:
    SHA = "a" * 40

    def test_loose_ref_packed_ref_detached_and_unknown(self, tmp_path):
        g = tmp_path / "loose/.git"
        _w(g / "HEAD", "ref: refs/heads/main\n")
        _w(g / "refs/heads/main", self.SHA + "\n")
        assert carto_reader.commit_of(tmp_path / "loose") == self.SHA
        p = tmp_path / "packed/.git"
        _w(p / "HEAD", "ref: refs/heads/main\n")
        _w(p / "packed-refs", f"# pack-refs\n{self.SHA} refs/heads/main\n^{'b' * 40}\n")
        assert carto_reader.commit_of(tmp_path / "packed") == self.SHA
        d = tmp_path / "detached/.git"
        _w(d / "HEAD", self.SHA + "\n")
        assert carto_reader.commit_of(tmp_path / "detached") == self.SHA
        assert carto_reader.commit_of(tmp_path / "nothing") == "unknown"

    def test_a_head_pointing_outside_refs_or_at_a_non_commit_reports_unknown(self, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("hunter2\n")
        for head in ("ref: ../../secret.txt", "ref: refs/../../secret.txt", "not-a-sha"):
            g = tmp_path / "r/.git"
            _w(g / "HEAD", head + "\n")
            assert carto_reader.commit_of(tmp_path / "r") == "unknown"
        _w(tmp_path / "s/.git", f"gitdir: {tmp_path}\n")  # a gitdir pointing at an arbitrary directory
        _w(tmp_path / "HEAD", "ref: refs/heads/x\n")
        _w(tmp_path / "refs/heads/x", "hunter2\n")  # exists, but is not a commit id
        assert carto_reader.commit_of(tmp_path / "s") == "unknown"

    def test_the_source_digest_changes_when_an_analysed_file_changes(self, carto):
        before = carto_reader.tree_digest(carto, ["cartography/models/**/*.py"])
        (carto / "cartography/models/aws/rds.py").write_text((carto / "cartography/models/aws/rds.py").read_text() + "# edit\n")
        assert carto_reader.tree_digest(carto, ["cartography/models/**/*.py"]) != before

    def test_a_worktree_reads_shared_refs_from_the_main_git_directory(self, tmp_path):
        main = tmp_path / "main/.git"
        _w(main / "refs/heads/feat", self.SHA + "\n")
        wt = main / "worktrees/w"
        _w(wt / "HEAD", "ref: refs/heads/feat\n")
        _w(wt / "commondir", "../..\n")
        _w(tmp_path / "w/.git", f"gitdir: {wt}\n")
        assert carto_reader.commit_of(tmp_path / "w") == self.SHA


class TestHostileText:
    def test_control_sequences_from_an_analysed_tree_never_reach_the_printed_report(self, carto, plugin, tmp_path, capsys):
        evil = "AWSEvil\\x1b]52;c;SGVsbG8=\\x07\\x1b[2J"
        f = carto / "cartography/models/aws/evil.py"
        f.write_text(f'class P(CartographyNodeProperties):\n    id: PropertyRef = PropertyRef("Id")\nclass S(CartographyNodeSchema):\n    label: str = "{evil}"\n    properties: P = P()\n')
        w = wfile(tmp_path, [{"carto_label": "AWS*", "weight": 1, "why": "x"}])
        crosscheck.main(["--cartography", str(carto), "--plugin", str(plugin), "--weights", str(w), "--out", str(tmp_path / "o")])
        out = capsys.readouterr().out + (tmp_path / "o/report.md").read_text()
        assert "AWSEvil" in out and "\x1b" not in out and "\x07" not in out


class TestTapReader:
    def test_reads_types_manifest_edges_ops_and_ledger(self, plugin):
        t = tap_reader.read(plugin)
        assert set(t["types"]) == {"aws_core__aws_rds_instance", "aws_core__aws_subnet"}
        assert t["types"]["aws_core__aws_rds_instance"]["manifest"]["edges"][0]["target"] == "aws_core__aws_subnet"
        assert ("rds", "describedbinstances") in {tuple(o) for o in t["ops"]}
        ops = {tuple(o) for o in t["ops"]}
        assert ("?", "listtagsforresource") in ops
        assert ("rds", "getthing") in ops  # a hydration op, keyed `op`
        assert ("?", "listsubscriptions") in ops  # a literal read name handed to a listing helper
        assert t["ledger_state"]["aws_core__aws_rds_instance"] == "collected-unverified"


class TestWeighting:
    def test_first_matching_rule_wins_and_default_applies(self, tmp_path):
        w = weighting.load(wfile(tmp_path, [
            {"carto_label": "AWSRole", "weight": 5, "why": "x"},
            {"carto_label": "AWS*", "weight": 1, "why": "y"},
        ]))
        assert w.concept("AWSRole") == 5 and w.concept("AWSFoo") == 1 and w.concept("Other") == 0

    def test_an_overlay_rule_naming_the_type_beats_the_base_rule_naming_the_label(self, tmp_path):
        (tmp_path / "base.json").write_text(json.dumps({"name": "b", "version": 1, "description": "d", "default_weight": 0,
            "rules": [{"carto_label": "AWSRDSInstance", "weight": 3, "why": "x"}]}))
        (tmp_path / "over.json").write_text(json.dumps({"name": "o", "version": 1, "description": "d", "default_weight": 0, "extends": "base.json",
            "rules": [{"tap_type": "aws_core__aws_rds_*", "weight": 5, "why": "y"}]}))
        w = weighting.load(tmp_path / "over.json")
        assert w.concept("AWSRDSInstance", ("aws_core__aws_rds_instance",)) == 5
        assert w.concept("AWSRDSInstance", ()) == 3
        assert w.chain == ("over.json", "base.json")

    def test_an_attribute_without_its_own_rule_takes_the_weight_of_what_it_belongs_to(self, tmp_path):
        w = weighting.load(wfile(tmp_path, [{"attribute": "rds-*", "weight": 9, "why": "z"}]))
        assert w.attribute("rds-x", 1) == 9 and w.attribute("s3-x", 4) == 4

    @pytest.mark.parametrize("extra", [{"status": "approved"}, {"version": "1"}, {"version": True}, {"oops": 1}, {"extends": "../x.json"}, {"name": ""}])
    def test_a_malformed_top_level_is_refused(self, tmp_path, extra):
        with pytest.raises(weighting.WeightingError):
            weighting.load(wfile(tmp_path, [{"carto_label": "a", "weight": 1, "why": "x"}], **extra))

    def test_a_boolean_rule_weight_is_refused(self, tmp_path):
        with pytest.raises(weighting.WeightingError):
            weighting.load(wfile(tmp_path, [{"carto_label": "a", "weight": True, "why": "x"}]))

    @pytest.mark.parametrize("rule", [
        {"weight": 1, "why": "no selector"},
        {"carto_label": "a", "tap_type": "b", "weight": 1, "why": "two selectors"},
        {"carto_label": "a", "weight": -1, "why": "negative"},
        {"carto_label": "a", "weight": 1},
        {"carto_label": "a", "weight": 1, "why": "x", "oops": 1},
    ])
    def test_a_malformed_rule_is_refused(self, tmp_path, rule):
        with pytest.raises(weighting.WeightingError):
            weighting.load(wfile(tmp_path, [rule]))

    @pytest.mark.parametrize("default", [-1, "x", True])
    def test_a_bad_default_weight_is_refused(self, tmp_path, default):
        with pytest.raises(weighting.WeightingError):
            weighting.load(wfile(tmp_path, [{"carto_label": "a", "weight": 1, "why": "x"}], default_weight=default))

    def test_a_cycle_is_refused(self, tmp_path):
        (tmp_path / "a.json").write_text(json.dumps({"name": "a", "version": 1, "description": "d", "default_weight": 0, "extends": "a.json", "rules": []}))
        with pytest.raises(weighting.WeightingError):
            weighting.load(tmp_path / "a.json")


class TestMetrics:
    @pytest.fixture
    def rep(self, carto, plugin, tmp_path):
        return crosscheck.run(carto, plugin, wfile(tmp_path, [{"carto_label": "AWS*", "weight": 2, "why": "all"}]))

    def test_coverage_counts_mapped_artifacts_and_gaps(self, rep):
        c = rep["coverage"]
        # RDS and Subnet match by name; the account and the tag are artifacts, excluded from scoring; the widget is unreviewed
        assert c["reference_labels"] == 3 and c["mapped"] == 2 and c["artifact_labels_excluded"] == 2
        assert c["unmapped_needs_review"] == 1 and c["gaps"][0]["label"] == "AWSWidget"

    def test_accuracy_compares_api_keys_not_field_names(self, rep):
        row = next(r for r in rep["accuracy"]["rows"] if r["label"] == "AWSRDSInstance")
        assert row["reference_properties"] == 3 and row["typed_overlap"] == 2  # arn and engine yes, PubliclyAccessible no
        assert row["not_typed"] == ["publiclyaccessible"] and row["configuration_stored"] is False

    def test_linkage_matches_an_emitted_pair_and_ignores_account_and_ghost_endpoints(self, rep):
        rows = {(r["rel"], r["to"]): r["status"] for r in rep["linkage"]["rows"]}
        assert rows[("PART_OF_SUBNET", "AWSEC2Subnet")] == "matched"
        assert rows[("TAGGED", "AWSTag")].startswith("not-comparable")
        assert ("RESOURCE", "AWSAccount") not in rows

    def test_operations_match_on_normalised_names(self, rep):
        o = rep["operations"]
        assert o["matched"] == 1 and o["reference_only"] == 2

    def test_tags_and_identity(self, rep):
        assert rep["tags"]["verdicts"] == {"both": 1, "neither": 1}
        assert {r["verdict"] for r in rep["identity"]["differs"]} <= {"differs"}

    def test_security_attribute_verdicts_include_stale_names(self, carto, plugin, tmp_path, monkeypatch):
        attrs = {"attributes": [
            {"id": "a", "concept": "c", "carto": {"label": "AWSRDSInstance", "property": "publicly_accessible"}, "tap": {"type": "aws_core__aws_rds_instance", "field": None, "read_op": "DescribeDBInstances"}},
            {"id": "f", "concept": "c", "carto": {"label": "AWSRDSInstance", "property": "engine"}, "tap": {"type": "aws_core__aws_rds_instance", "field": "status"}},
            {"id": "b", "concept": "c", "carto": {"label": "AWSRDSInstance", "property": "engine"}, "tap": {"type": "aws_core__aws_rds_instance", "field": "engine"}},
            {"id": "c", "concept": "c", "carto": {"label": "AWSRDSInstance", "property": "nope"}, "tap": {"type": "aws_core__aws_rds_instance", "field": "engine"}},
            {"id": "d", "concept": "c", "carto": {"label": "AWSRDSInstance", "property": "engine"}, "tap": {"type": "aws_core__aws_rds_instance", "field": "gone"}},
            {"id": "e", "concept": "c", "carto": {"label": "AWSRDSInstance", "property": "engine"}, "tap": {"type": "aws_core__aws_missing", "field": None}},
        ]}
        models = carto_reader.read_models(carto)
        tap = tap_reader.read(plugin)
        w = weighting.load(wfile(tmp_path, []))
        got = {r["id"]: r["verdict"] for r in crosscheck.security(attrs, models["nodes"], tap, w, {})["rows"]}
        assert got == {"a": "not-evidenced", "f": "column-unfilled", "b": "typed", "c": "stale-reference-property", "d": "stale-tap-field", "e": "type-not-collected"}

    def test_a_same_named_read_by_another_type_earns_no_credit(self, carto, tmp_path):
        plug = make_plugin(tmp_path / "p3", persist=True)
        man = plug / "tap_plugin/aws_core/collectors/boto3_collector/aws_resource_manifest.json"
        m = json.loads(man.read_text())
        m["entries"][0].pop("hydrate")  # the RDS entry no longer makes the read
        m["entries"].append({"entity_type": "aws_core__aws_subnet", "service": "ec2", "persist_configuration": True, "source": {"aws_op": "DescribeSubnets"},
                             "natural_key": "SubnetId", "fields": {"subnet_id": "SubnetId"}, "hydrate": [{"key": "x", "op": "GetThing"}]})
        man.write_text(json.dumps(m))  # an unrelated type makes GetThing
        models, tap = carto_reader.read_models(carto), tap_reader.read(plug)
        tp = {"type": "aws_core__aws_rds_instance", "field": None, "read_op": "GetThing"}
        attrs = {"attributes": [{"id": "a", "concept": "c", "carto": {"label": "AWSRDSInstance", "property": "publicly_accessible"}, "tap": tp}]}
        r = crosscheck.security(attrs, models["nodes"], tap, weighting.load(wfile(tmp_path, [])), {})
        assert r["rows"][0]["verdict"] == "not-evidenced"

    def test_a_helper_name_defined_in_two_modules_cannot_lend_its_reads(self, carto, tmp_path):
        plug = make_plugin(tmp_path / "p5", persist=True)
        pkg = plug / "tap_plugin/aws_core/collectors/boto3_collector"
        _w(pkg / "one.py", """
            def rds_reader(c):
                return _pages(c)

            def _pages(c):
                return c.get_widget()
        """)
        _w(pkg / "two.py", """
            def _pages(c):
                return c.get_gadget()

            def twin(c):
                return c.get_gizmo()

            def twin_caller(c):
                return twin(c)
        """)
        _w(pkg / "three.py", """
            def twin(c):
                return c.get_other()
        """)
        m = json.loads((pkg / "aws_resource_manifest.json").read_text())
        e = m["entries"][0]
        e.pop("hydrate")
        e["source"] = {"custom_fn": "rds_reader"}
        m["entries"].append({**e, "entity_type": "aws_core__aws_subnet", "source": {"custom_fn": "twin"}, "fields": {"subnet_id": "SubnetId"}, "natural_key": "SubnetId"})
        (pkg / "aws_resource_manifest.json").write_text(json.dumps(m))
        types = tap_reader.read(plug)["types"]
        rds = types["aws_core__aws_rds_instance"]["manifest"]["ops"]
        assert "getwidget" in rds and "getgadget" not in rds  # the call resolves to the definition in its own module
        assert not {"getgizmo", "getother"} & set(types["aws_core__aws_subnet"]["manifest"]["ops"])  # an ambiguous name earns nothing

    def test_a_hand_written_reader_is_credited_only_with_its_own_reads(self, carto, tmp_path):
        plug = make_plugin(tmp_path / "p4", persist=True)
        pkg = plug / "tap_plugin/aws_core/collectors/boto3_collector"
        _w(pkg / "readers.py", """
            def rds_reader(c):
                return _helper(c)

            def _helper(c):
                return c.get_widget()

            def other_reader(c):
                return c.get_gadget()
        """)
        m = json.loads((pkg / "aws_resource_manifest.json").read_text())
        e = m["entries"][0]
        e.pop("hydrate")
        e["source"] = {"custom_fn": "rds_reader"}
        (pkg / "aws_resource_manifest.json").write_text(json.dumps(m))
        models, tap = carto_reader.read_models(carto), tap_reader.read(plug)

        def verdict(op):
            tp = {"type": "aws_core__aws_rds_instance", "field": None, "read_op": op}
            attrs = {"attributes": [{"id": "a", "concept": "c", "carto": {"label": "AWSRDSInstance", "property": "publicly_accessible"}, "tap": tp}]}
            return crosscheck.security(attrs, models["nodes"], tap, weighting.load(wfile(tmp_path, [])), {})["rows"][0]["verdict"]

        assert verdict("GetWidget") == "configuration-only"  # made by the named reader, through a helper it calls
        assert verdict("GetGadget") == "not-evidenced"  # made only by a different reader

    def test_configuration_storing_types_hold_unnamed_attributes_in_the_blob(self, carto, tmp_path):
        plug = make_plugin(tmp_path / "p2", persist=True)
        models, tap = carto_reader.read_models(carto), tap_reader.read(plug)
        def verdict(read_op):
            tp = {"type": "aws_core__aws_rds_instance", "field": None, **({"read_op": read_op} if read_op else {})}
            attrs = {"attributes": [{"id": "a", "concept": "c", "carto": {"label": "AWSRDSInstance", "property": "publicly_accessible"}, "tap": tp}]}
            return crosscheck.security(attrs, models["nodes"], tap, weighting.load(wfile(tmp_path, [])), {})["rows"][0]["verdict"]

        assert verdict("GetThing") == "configuration-only"  # a read we make (here a hydration op) on a type that keeps its configuration
        assert verdict("DescribeNeverCalled") == "not-evidenced"  # storing the blob proves nothing if the read is never made
        assert verdict(None) == "not-evidenced"

    def test_the_report_is_deterministic(self, carto, plugin, tmp_path):
        w = wfile(tmp_path, [{"carto_label": "AWS*", "weight": 2, "why": "all"}])
        a = json.dumps(crosscheck.run(carto, plugin, w), sort_keys=True)
        b = json.dumps(crosscheck.run(carto, plugin, w), sort_keys=True)
        assert a == b

    def test_a_different_weighting_changes_the_weighted_figures_only(self, carto, plugin, tmp_path):
        r1 = crosscheck.run(carto, plugin, wfile(tmp_path, [{"carto_label": "AWSWidget", "weight": 100, "why": "widget"}, {"carto_label": "AWS*", "weight": 1, "why": "x"}]))
        r2 = crosscheck.run(carto, plugin, wfile(tmp_path, [{"carto_label": "AWS*", "weight": 1, "why": "x"}]))
        assert r1["coverage"]["coverage_pct"] == r2["coverage"]["coverage_pct"]
        assert r1["coverage"]["weighted_coverage_pct"] < r2["coverage"]["weighted_coverage_pct"]


class TestLedgerView:
    def test_weights_the_ledger_by_cfn_type_and_lists_open_work(self, carto, plugin, tmp_path):
        w = wfile(tmp_path, [
            {"cfn_type": "AWS::RDS::CustomDBEngineVersion", "weight": 4, "why": "x"},
            {"cfn_type": "AWS::RDS::*", "weight": 2, "why": "x"},
            {"cfn_type": "AWS::Macie::*", "weight": 5, "why": "x"},
        ])
        lv = crosscheck.run(carto, plugin, w)["ledger"]
        assert lv["weighted_by_state"] == {"collected-unverified": 2.0, "collected-verified": 2.0, "excluded": 2.0, "modeled": 2.0, "unclassified": 4.0}
        # verified counts as collected; a model with no collector yet counts as neither collected nor decided
        assert lv["collected_pct"] == 33.3 and lv["decided_pct"] == 50.0
        assert [x["type"] for x in lv["open_unclassified"]] == ["AWS::RDS::CustomDBEngineVersion"]  # Other::Thing weighs 0
        assert [x["type"] for x in lv["weighted_out_of_scope_unclassified"]] == ["AWS::Macie::Session"]

    def test_a_weighting_with_no_cfn_rules_says_so(self, carto, plugin, tmp_path):
        lv = crosscheck.run(carto, plugin, wfile(tmp_path, [{"carto_label": "AWS*", "weight": 1, "why": "x"}]))["ledger"]
        assert lv["applicable"] is False


class TestDriftAndCli:
    def test_a_new_gap_is_reported_and_can_fail_the_run(self, carto, tmp_path):
        w = wfile(tmp_path, [{"carto_label": "AWS*", "weight": 1, "why": "x"}])
        good = make_plugin(tmp_path / "good", rds_fields={"engine": "Engine", "db_instance_arn": "DBInstanceArn"})
        base = tmp_path / "base"
        assert crosscheck.main(["--cartography", str(carto), "--plugin", str(good), "--weights", str(w), "--out", str(base)]) == 0
        # the plugin loses its edge to the subnet, and an operation
        pkg = good / "tap_plugin/aws_core/collectors/boto3_collector/aws_resource_manifest.json"
        m = json.loads(pkg.read_text())
        m["entries"][0]["edges"] = []
        m["entries"][0]["source"] = {"aws_op": "DescribeSomethingElse"}
        pkg.write_text(json.dumps(m))
        (good / "tap_plugin/aws_core/edges/RESIDES_IN_SUBNET.edge.json").unlink()
        code = crosscheck.main(["--cartography", str(carto), "--plugin", str(good), "--weights", str(w), "--baseline", str(base / "report.json"), "--out", str(tmp_path / "now"), "--fail-on-regression"])
        assert code == 1
        d = json.loads((tmp_path / "now/report.json").read_text())["drift"]
        assert any(g.startswith("edge:AWSRDSInstance>PART_OF_SUBNET") for g in d["new_gaps"])
        assert any(g.startswith("op:rds:describedbinstances") for g in d["new_gaps"])

    def test_losing_emission_but_keeping_the_definition_is_still_a_new_gap(self, carto, tmp_path):
        w = wfile(tmp_path, [{"carto_label": "AWS*", "weight": 1, "why": "x"}])
        plug = make_plugin(tmp_path / "plug")
        base = tmp_path / "base"
        crosscheck.main(["--cartography", str(carto), "--plugin", str(plug), "--weights", str(w), "--out", str(base)])
        man = plug / "tap_plugin/aws_core/collectors/boto3_collector/aws_resource_manifest.json"
        m = json.loads(man.read_text())
        m["entries"][0]["edges"] = []  # the edge definition file stays
        man.write_text(json.dumps(m))
        code = crosscheck.main(["--cartography", str(carto), "--plugin", str(plug), "--weights", str(w), "--baseline", str(base / "report.json"), "--out", str(tmp_path / "now"), "--fail-on-regression"])
        assert code == 1
        now = json.loads((tmp_path / "now/report.json").read_text())
        assert next(e for e in now["linkage"]["rows"] if e["rel"] == "PART_OF_SUBNET")["status"] == "declared-only"

    def test_a_typed_attribute_that_degrades_is_a_new_gap(self, carto, tmp_path):
        before = {"security_attributes": {"rows": [{"id": "x", "verdict": "typed"}]}}
        after = {"security_attributes": {"rows": [{"id": "x", "verdict": "stale-tap-field"}]}}
        for r in (before, after):
            r.update(coverage={"gaps": []}, linkage={"rows": []}, operations={"reference_only_operations": []}, ledger={}, accuracy={"rows": []}, tags={"reference_only": []}, identity={"differs": []})
        assert crosscheck.gap_ids(before) == []
        assert crosscheck.gap_ids(after) == ["security:x:stale-tap-field"]

    def test_the_gate_without_a_baseline_is_refused_not_passed(self, carto, plugin, tmp_path):
        with pytest.raises(SystemExit) as e:
            crosscheck.main(["--cartography", str(carto), "--plugin", str(plugin), "--fail-on-regression"])
        assert e.value.code == 2

    def test_an_incomparable_baseline_fails_the_gate_closed(self, carto, plugin, tmp_path):
        w = wfile(tmp_path, [{"carto_label": "AWS*", "weight": 1, "why": "x"}])
        base = tmp_path / "base"
        crosscheck.main(["--cartography", str(carto), "--plugin", str(plugin), "--weights", str(w), "--out", str(base)])
        rep = json.loads((base / "report.json").read_text())
        rep["schema_version"] = 0
        (base / "report.json").write_text(json.dumps(rep))
        assert crosscheck.main(["--cartography", str(carto), "--plugin", str(plugin), "--weights", str(w), "--baseline", str(base / "report.json"), "--fail-on-regression"]) == 1

    def test_an_empty_reference_is_an_argument_error(self, plugin, tmp_path):
        with pytest.raises(SystemExit) as e:
            crosscheck.main(["--cartography", str(tmp_path), "--plugin", str(plugin)])
        assert e.value.code == 2

    def test_no_regression_exits_zero(self, carto, plugin, tmp_path):
        w = wfile(tmp_path, [{"carto_label": "AWS*", "weight": 1, "why": "x"}])
        base = tmp_path / "base"
        crosscheck.main(["--cartography", str(carto), "--plugin", str(plugin), "--weights", str(w), "--out", str(base)])
        assert crosscheck.main(["--cartography", str(carto), "--plugin", str(plugin), "--weights", str(w), "--baseline", str(base / "report.json"), "--fail-on-regression"]) == 0


@pytest.fixture(scope="module")
def tap():
    return tap_reader.read(ROOT)


class TestCommittedData:
    """The shipped mapping, attribute list and weightings against the real plugin tree."""

    def test_every_alias_target_is_a_real_type(self, tap):
        lmap = json.loads((Path(crosscheck.HERE) / "label_map.json").read_text())
        bad = {l: [t for t in ts if t not in tap["types"]] for l, ts in lmap["aliases"].items()}
        assert {l: b for l, b in bad.items() if b} == {}

    def test_every_security_attribute_names_a_real_type_and_field(self, tap):
        attrs = json.loads((Path(crosscheck.HERE) / "security_attributes.json").read_text())["attributes"]
        ids = [a["id"] for a in attrs]
        assert len(ids) == len(set(ids))
        for a in attrs:
            t = tap["types"].get(a["tap"]["type"])
            assert t is not None, a["id"]
            assert a["tap"]["field"] is None or a["tap"]["field"] in t["fields"], a["id"]

    @pytest.mark.parametrize("name", sorted(p.name for p in (Path(crosscheck.HERE) / "weights").glob("*-v*.json")))
    def test_every_shipped_weighting_loads(self, name):
        w = weighting.load(Path(crosscheck.HERE) / "weights" / name)
        assert w.rules and w.status in ("draft", "reviewed")

    def test_weights_schema_is_valid_json_and_matches_the_loader_selectors(self):
        s = json.loads((Path(crosscheck.HERE) / "weights" / "weights.schema.json").read_text())
        assert set(s["properties"]["rules"]["items"]["properties"]) == set(weighting.SELECTORS) | {"weight", "why"}
