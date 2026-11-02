"""Shape and consistency of the seed catalog, and hygiene of the wave-1 Terraform. No AWS, no Terraform run."""

import json
import os
import re
import sys
from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parent.parent
REPO = SEED.parent.parent
sys.path.insert(0, str(SEED))

CATALOG = json.loads((SEED / "seeding.json").read_text(encoding="utf-8"))
MANIFEST = json.loads(
    (REPO / "tap_plugin/aws_core/collectors/boto3_collector/aws_resource_manifest.json").read_text(encoding="utf-8")
)
ENTRIES = {e["entity_type"]: e for e in MANIFEST["entries"]}
TF_TEXT = "\n".join(p.read_text(encoding="utf-8") for p in sorted((SEED / "wave1").glob("*.tf")))
REQUIRED = {"cfn_type", "entity_type", "terraform", "cost_class", "needs", "compares", "module", "natural_key", "tf_attrs", "tags", "edges", "description"}
COSTS = {"free", "cheap", "costly", "blocked"}
CASES = sorted(CATALOG["types"].items())


def test_catalog_has_a_description_and_types():
    assert CATALOG["description"].strip()
    assert len(CATALOG["types"]) >= 20


@pytest.mark.parametrize("cfn,entry", CASES)
def test_entry_shape(cfn, entry):
    assert set(entry) == REQUIRED, cfn
    assert entry["cfn_type"] == cfn and re.fullmatch(r"AWS::[A-Za-z0-9]+::[A-Za-z0-9]+", cfn)
    assert entry["cost_class"] in COSTS and entry["cost_class"] != "blocked"  # a blocked type is not seeded, so has no entry
    assert entry["module"] == "wave1"
    assert entry["tags"] in ("tags_all", "none")
    assert entry["description"].strip()
    assert entry["needs"] == sorted(entry["needs"]) and all(n in CATALOG["types"] for n in entry["needs"])
    assert set(entry["compares"]) == set(entry["tf_attrs"]) and entry["compares"]


@pytest.mark.parametrize("cfn,entry", CASES)
def test_entry_agrees_with_manifest(cfn, entry):
    manifest = ENTRIES[entry["entity_type"]]
    assert set(entry["compares"]) <= set(manifest["fields"])
    declared = {(r["edge_type"], r["target_type"], r["direction"]) for r in manifest.get("edges", [])}
    for edge in entry["edges"]:
        assert set(edge) == {"edge_type", "target_type", "direction", "target"}
        assert (edge["edge_type"], edge["target_type"], edge["direction"]) in declared, (cfn, edge["edge_type"])
        assert edge["target_type"] in {e["entity_type"] for e in CATALOG["types"].values()}
    has_tags = (manifest.get("tags") or {}).get("source", "none") != "none"
    assert (entry["tags"] == "tags_all") == has_tags


@pytest.mark.parametrize("cfn,entry", CASES)
def test_terraform_resource_is_declared_in_wave1(cfn, entry):
    assert re.search(rf'^resource "{entry["terraform"]}" ', TF_TEXT, re.M), entry["terraform"]


def test_every_entity_type_is_unique_and_terraform_types_are_unique():
    ents = [e["entity_type"] for e in CATALOG["types"].values()]
    tfs = [e["terraform"] for e in CATALOG["types"].values()]
    assert len(ents) == len(set(ents)) and len(tfs) == len(set(tfs))


def test_attribute_names_exist_in_the_provider_schema_dump_when_available():
    dump = os.environ.get("TF_SCHEMA_DUMP")
    if not dump:
        pytest.skip("set TF_SCHEMA_DUMP to the `terraform providers schema -json` file to check attribute names")
    resources = json.loads(Path(dump).read_text(encoding="utf-8"))["provider_schemas"]["registry.terraform.io/hashicorp/aws"]["resource_schemas"]

    def known(tf_type, path):
        top = path.split(".")[0]
        block = resources[tf_type]["block"]
        return top in block["attributes"] or top in block.get("block_types", {})

    def check(tf_type, spec):
        if isinstance(spec, str):
            assert known(tf_type, spec), (tf_type, spec)
        elif "path" in spec:
            assert known(tf_type, spec["path"]), (tf_type, spec)
        elif "join" in spec:
            j = spec["join"]
            assert known(tf_type, j["own"]) and known(j["terraform"], j["other"]), (tf_type, j)
            check(j["terraform"], j["target"])
        elif "all_true" in spec:
            j = spec["all_true"]
            assert known(tf_type, j["own"]) and known(j["terraform"], j["other"]) and all(known(j["terraform"], f) for f in j["flags"])

    for entry in CATALOG["types"].values():
        for spec in [entry["natural_key"], *entry["tf_attrs"].values(), *[e["target"] for e in entry["edges"]]]:
            check(entry["terraform"], spec)


def test_nothing_outside_the_state_is_deleted_by_a_destroy():
    assert "force_destroy" not in TF_TEXT


def test_every_iam_identity_waits_for_the_partition_guard():
    for kind in ("role", "user", "group", "policy"):
        block = re.search(rf'^resource "aws_iam_{kind}" "[^"]+" \{{\n(.*?)^\}}', TF_TEXT, re.M | re.S)
        assert block and "depends_on = [terraform_data.guard]" in block.group(1), kind


def test_iam_names_start_with_seed():
    blocks = re.findall(r'^resource "aws_iam_(role|user|group|policy|instance_profile)" "[^"]+" \{\n(.*?)^\}', TF_TEXT, re.M | re.S)
    assert len(blocks) == 5
    for kind, body in blocks:
        assert re.search(r'^\s*name\s*=\s*"seed-', body, re.M), kind


def test_provider_is_pinned_and_default_tags_are_set():
    assert 'version = "= 6.71.0"' in TF_TEXT
    assert '"tap-seed"     = "wave1"' in TF_TEXT and '"tap-seed-run" = var.run_id' in TF_TEXT
    assert 'region  = "us-gov-west-1"' in TF_TEXT and "allowed_account_ids" in TF_TEXT
    block = re.search(r'variable "run_id" \{(.*?)\n\}\n', TF_TEXT, re.S).group(1)
    assert not re.search(r"^\s*default\s*=", block, re.M)


def test_nothing_costly_is_declared():
    for banned in ("aws_nat_gateway", "aws_lb", "aws_db_instance", "aws_eks_cluster", "aws_redshift", "aws_eip", "aws_opensearch", "aws_rds"):
        assert banned not in TF_TEXT, banned


def test_no_account_number_key_or_secret_in_the_seed_tree():
    for path in SEED.rglob("*"):
        if not path.is_file() or ".terraform" in path.parts or path.suffix in (".pyc", ".zip") or path.name == ".terraform.lock.hcl":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found = set(re.findall(r"(?<![\d.])\d{12}(?![\d.])", text)) - {"000000000000", "123456789012"}  # the two obvious dummies
        assert not found, path
        assert not re.search((r"AKIA[0-9A-Z]{12,}|ASIA[0-9A-Z]{12,}|aws_secret" + "_access_key|BEGIN [A-Z ]*PRIVATE KEY"), text), path
