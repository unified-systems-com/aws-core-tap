"""expected.py against a small synthetic `terraform show -json` document."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SEED))

import expected  # noqa: E402

CATALOG = json.loads((SEED / "seeding.json").read_text(encoding="utf-8"))
DEFAULTS = {"tap-seed": "wave1", "tap-seed-run": "t1"}
ACCT = "arn:aws-us-gov:{svc}:us-gov-west-1:000000000000:{rest}"


def res(addr, typ, **values):
    return {"address": addr, "mode": "managed", "type": typ, "name": addr.split(".")[-1], "values": values}


def state():
    vpc = res("aws_vpc.seed", "aws_vpc", id="vpc-1", cidr_block="10.99.0.0/16", tags_all=DEFAULTS)
    subnet = res("aws_subnet.a", "aws_subnet", id="subnet-1", vpc_id="vpc-1", cidr_block="10.99.1.0/24",
                 availability_zone="us-gov-west-1a", map_public_ip_on_launch=False, tags_all=DEFAULTS)
    other_subnet = res("aws_subnet.b", "aws_subnet", id="subnet-2", vpc_id="vpc-9", cidr_block="10.99.2.0/24",
                       availability_zone="us-gov-west-1b", map_public_ip_on_launch=False, tags_all=DEFAULTS)
    policy_arn = "arn:aws-us-gov:iam::000000000000:policy/seed-w1-t1-policy"
    pol = res("aws_iam_policy.seed", "aws_iam_policy", name="seed-w1-t1-policy", arn=policy_arn, path="/", policy_id="ANPA1", tags_all=DEFAULTS)
    role = res("aws_iam_role.seed", "aws_iam_role", name="seed-w1-t1-role", arn="arn:aws-us-gov:iam::000000000000:role/seed-w1-t1-role",
               path="/", max_session_duration=3600, unique_id="AROA1", tags_all=DEFAULTS)
    att = res("aws_iam_role_policy_attachment.seed", "aws_iam_role_policy_attachment", role="seed-w1-t1-role", policy_arn=policy_arn)
    grp = res("aws_iam_group.seed", "aws_iam_group", name="seed-w1-t1-group", arn="arn:aws-us-gov:iam::000000000000:group/seed-w1-t1-group",
              path="/", unique_id="AGPA1")
    inst = res("aws_instance.seed", "aws_instance", id="i-1", instance_type="t3.micro", instance_state="running", private_ip="10.99.1.5",
               public_ip="", ami="ami-1", subnet_id="subnet-1", tags_all=DEFAULTS)
    lg = res("aws_cloudwatch_log_group.fn", "aws_cloudwatch_log_group", name="/aws/lambda/f", arn="arn:aws-us-gov:logs:us-gov-west-1:000000000000:log-group:/aws/lambda/f:*",
             retention_in_days=1, tags_all=DEFAULTS)
    bucket_a = res("aws_s3_bucket.a", "aws_s3_bucket", id="seed-w1-t1-bucket-a", arn="arn:aws-us-gov:s3:::seed-w1-t1-bucket-a",
                   tags_all={**DEFAULTS, "weird key: 1/2": "v = 1+2"})
    bucket_b = res("aws_s3_bucket.b", "aws_s3_bucket", id="seed-w1-t1-bucket-b", arn="arn:aws-us-gov:s3:::seed-w1-t1-bucket-b", tags_all=DEFAULTS)
    pab = res("aws_s3_bucket_public_access_block.a", "aws_s3_bucket_public_access_block", bucket="seed-w1-t1-bucket-a",
              block_public_acls=True, block_public_policy=True, ignore_public_acls=True, restrict_public_buckets=True)
    extra = res("aws_ssm_activation.x", "aws_ssm_activation", id="x")
    child = {"resources": [res("aws_vpc.child", "aws_vpc", id="vpc-2", cidr_block="10.0.0.0/16", tags_all=DEFAULTS)]}
    data = {"address": "data.aws_ami.x", "mode": "data", "type": "aws_ami", "name": "x", "values": {}}
    root = {"resources": [vpc, subnet, other_subnet, pol, role, att, grp, inst, lg, bucket_a, bucket_b, pab, extra, data], "child_modules": [child]}
    return {"values": {"root_module": root}}


@pytest.fixture(scope="module")
def doc():
    return expected.build_expected(expected.walk_resources(state()["values"]["root_module"]), CATALOG)


def by_addr(doc, addr):
    return next(r for r in doc["resources"] if r["address"] == addr)


def test_data_sources_and_unseeded_types_are_not_expected(doc):
    assert doc["unseeded_resources"] == ["aws_iam_role_policy_attachment.seed", "aws_s3_bucket_public_access_block.a", "aws_ssm_activation.x"]
    assert all(r["address"] != "data.aws_ami.x" for r in doc["resources"])


def test_child_modules_are_walked_and_output_is_sorted(doc):
    keys = [(r["entity_type"], r["natural_key"], r["address"]) for r in doc["resources"]]
    assert keys == sorted(keys) and "vpc-2" in {r["natural_key"] for r in doc["resources"]}
    assert doc["wave"] == ["wave1"] and doc["run_id"] == ["t1"]


def test_tags_include_defaults_and_untaggable_types_expect_empty(doc):
    assert by_addr(doc, "aws_s3_bucket.a")["tags"] == {"tap-seed": "wave1", "tap-seed-run": "t1", "weird key: 1/2": "v = 1+2"}
    assert by_addr(doc, "aws_iam_group.seed")["tags"] == {}


def test_attrs_key_and_arn(doc):
    inst = by_addr(doc, "aws_instance.seed")
    assert inst["natural_key"] == "i-1" and inst["attrs"]["public_ip"] is None and inst["attrs"]["state"] == "running"
    assert by_addr(doc, "aws_iam_role.seed")["attrs"]["max_session_duration"] == 3600
    assert by_addr(doc, "aws_iam_role.seed")["arn"].endswith(":role/seed-w1-t1-role")
    assert by_addr(doc, "aws_instance.seed")["arn"] is None


def test_suffix_stripped_log_group_key(doc):
    assert by_addr(doc, "aws_cloudwatch_log_group.fn")["natural_key"].endswith(":log-group:/aws/lambda/f")


def test_all_true_derivation(doc):
    assert by_addr(doc, "aws_s3_bucket.a")["attrs"]["public_access_blocked"] is True
    # bucket B has no block resource: S3's default for a new bucket is blocked, which the catalog states as `absent`
    assert by_addr(doc, "aws_s3_bucket.b")["attrs"]["public_access_blocked"] is True


def test_an_absent_block_is_false_unless_the_spec_names_a_default():
    spec = {"all_true": {"terraform": "aws_s3_bucket_public_access_block", "own": "id", "other": "bucket", "flags": ["block_public_acls"]}}
    bucket = {"type": "aws_s3_bucket", "values": {"id": "x"}}
    assert expected.evaluate(spec, bucket, [bucket]) is False
    assert expected.evaluate({**spec, "absent": True}, bucket, [bucket]) is True


def test_a_symlinked_or_non_file_input_is_refused(tmp_path):
    real = tmp_path / "real.json"
    real.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    for bad in (link, tmp_path):
        with pytest.raises(expected.ExpectedError):
            expected.read_json_file(bad)
    assert expected.main([str(link)]) == 2


def test_edges_only_when_target_was_seeded(doc):
    role = by_addr(doc, "aws_iam_role.seed")
    assert role["edges"] == [{"direction": "outbound", "edge_type": "ATTACHES_POLICY__aws_core", "target_key": "arn:aws-us-gov:iam::000000000000:policy/seed-w1-t1-policy", "target_type": "aws_core__aws_iam_policy"}]
    assert [e["target_key"] for e in by_addr(doc, "aws_subnet.a")["edges"]] == ["vpc-1"]
    assert by_addr(doc, "aws_subnet.b")["edges"] == []  # its vpc (vpc-9) was not seeded
    inst_edges = {(e["edge_type"], e["target_key"]) for e in by_addr(doc, "aws_instance.seed")["edges"]}
    assert inst_edges == {("RESIDES_IN_SUBNET__aws_core", "subnet-1"), ("RESIDES_IN_VPC__aws_core", "vpc-1")}


def test_a_plan_or_empty_input_is_refused(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"planned_values": {}}))
    with pytest.raises(expected.ExpectedError):
        expected.load_state(p)


def test_cli_is_deterministic(tmp_path):
    p = tmp_path / "show.json"
    p.write_text(json.dumps(state()))
    outs = [subprocess.run([sys.executable, "-I", str(SEED / "expected.py"), str(p)], capture_output=True, text=True, check=True).stdout for _ in range(2)]
    assert outs[0] == outs[1] and json.loads(outs[0])["resources"]
    bad = subprocess.run([sys.executable, "-I", str(SEED / "expected.py"), str(tmp_path / "nope.json")], capture_output=True, text=True)
    assert bad.returncode == 2
