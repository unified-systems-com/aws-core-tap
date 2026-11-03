"""Shape and consistency of the seed catalog, and hygiene of the wave-1 Terraform. No AWS, no Terraform run."""

import base64
import hashlib
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
def _tf_text(directory):
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(directory.glob("*.tf")))


#: The seed modules: the catalog's `module` names a directory under tools/seed, and the module's provider tag.
MODULES = ("wave1", "wave1b", "wave1c", "wave2-rds", "wave2-nfw", "wave3-redshift", "wave3-elasticache", "wave3-eks", "wave3-opensearch", "wave3b-ops", "wave3b-edge", "wave3b-compute", "wave3b-bedrock")
TF_BY_MODULE = {m: _tf_text(SEED / m) for m in MODULES}
TF_TEXT = TF_BY_MODULE["wave1"]
ALL_TF_TEXT = "\n".join(TF_BY_MODULE.values())
#: Terraform resources whose type cannot carry tags although the service tags the object.
TAGLESS_IN_TERRAFORM = {"AWS::RDS::DBProxyTargetGroup", "AWS::CloudWatch::Dashboard", "AWS::AutoScaling::AutoScalingGroup"}
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
    assert entry["module"] in MODULES
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
    if cfn in TAGLESS_IN_TERRAFORM:
        assert entry["tags"] == "none" and has_tags, cfn
    else:
        assert (entry["tags"] == "tags_all") == has_tags


@pytest.mark.parametrize("cfn,entry", CASES)
def test_terraform_resource_is_declared_in_its_module(cfn, entry):
    assert re.search(rf'^resource "{entry["terraform"]}" ', TF_BY_MODULE[entry["module"]], re.M), entry["terraform"]


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
    # Only the two buckets that a flow log and a trail write their own delivery objects into are emptied on destroy.
    for module, text in TF_BY_MODULE.items():
        assert text.count("force_destroy") == (2 if module == "wave1b" else 0), module
    block = re.findall(r'^resource "aws_s3_bucket" "(\w+)" \{[^\n]*\n(.*?)^\}', TF_BY_MODULE["wave1b"], re.M | re.S)
    assert sorted(name for name, body in block if "force_destroy = true" in body) == ["flow", "trail"]


@pytest.mark.parametrize("module", MODULES)
def test_every_iam_identity_waits_for_the_partition_guard(module):
    for kind in ("role", "user", "group", "policy", "saml_provider"):
        for body in re.findall(rf'^resource "aws_iam_{kind}" "[^"]+" \{{\n(.*?)^\}}', TF_BY_MODULE[module], re.M | re.S):
            assert "depends_on = [terraform_data.guard]" in body, (module, kind)
    if module == "wave1":
        assert re.search(r'^resource "aws_iam_role" ', TF_BY_MODULE[module], re.M)  # the loop above found something to check


@pytest.mark.parametrize("module", MODULES)
def test_a_saml_provider_is_named_for_the_run(module):
    for body in re.findall(r'^resource "aws_iam_saml_provider" "[^"]+" \{\n(.*?)^\}', TF_BY_MODULE[module], re.M | re.S):
        assert re.search(r'^\s*name\s*=\s*"\$\{local\.prefix\}-', body, re.M)


def test_the_saml_metadata_holds_a_certificate_and_no_private_key():
    text = (SEED / "wave1c" / "saml-metadata.xml").read_text(encoding="utf-8")
    cert = re.search(r"<ds:X509Certificate>(.*?)</ds:X509Certificate>", text, re.S).group(1)
    der = base64.b64decode("".join(cert.split()), validate=True)
    assert b"PRIVATE" not in text.encode("utf-8")
    # Certificate ::= SEQUENCE { tbsCertificate SEQUENCE { [0] version v3, ... } ... }. A DER private key (PKCS#1 or PKCS#8)
    # also starts with a SEQUENCE, but its first element is an INTEGER version, never the explicit [0] tag of a certificate.
    assert der[0:2] == b"\x30\x82" and der[4:6] == b"\x30\x82" and der[8:13] == b"\xa0\x03\x02\x01\x02"
    assert int.from_bytes(der[2:4], "big") == len(der) - 4  # the outer length covers the whole blob: nothing is appended
    fingerprint = ":".join(f"{b:02X}" for b in hashlib.sha256(der).digest())
    assert fingerprint in (SEED / "wave1c" / "cost.md").read_text(encoding="utf-8")  # the documented fingerprint is this blob's


@pytest.mark.parametrize("module", MODULES)
def test_iam_names_start_with_seed(module):
    blocks = re.findall(r'^resource "aws_iam_(role|user|group|policy|instance_profile)" "[^"]+" \{\n(.*?)^\}', TF_BY_MODULE[module], re.M | re.S)
    assert len(blocks) == {"wave1": 5, "wave1b": 4, "wave1c": 0, "wave2-rds": 2, "wave2-nfw": 0, "wave3-redshift": 2, "wave3-elasticache": 0, "wave3-eks": 4, "wave3-opensearch": 0, "wave3b-ops": 0, "wave3b-edge": 0, "wave3b-compute": 0, "wave3b-bedrock": 1}[module]
    for kind, body in blocks:
        assert re.search(r'^\s*name\s*=\s*"seed-', body, re.M), kind


@pytest.mark.parametrize("module", MODULES)
def test_provider_is_pinned_and_default_tags_are_set(module):
    text = TF_BY_MODULE[module]
    assert 'version = "= 6.71.0"' in text
    assert re.search(rf'"tap-seed"\s+= "{re.escape(module)}"', text) and '"tap-seed-run" = var.run_id' in text
    assert 'region  = "us-gov-west-1"' in text and "allowed_account_ids" in text
    block = re.search(r'variable "run_id" \{(.*?)\n\}\n', text, re.S).group(1)
    assert not re.search(r"^\s*default\s*=", block, re.M)


def test_nothing_costly_is_declared_in_wave1():
    for banned in ("aws_nat_gateway", "aws_lb", "aws_db_instance", "aws_eks_cluster", "aws_redshift", "aws_eip", "aws_opensearch", "aws_rds"):
        assert banned not in TF_TEXT, banned


def test_wave1b_declares_nothing_that_costs_beyond_a_web_acl():
    text = TF_BY_MODULE["wave1b"]
    for banned in ("aws_nat_gateway", "aws_lb", "aws_db_", "aws_rds", "aws_eks_cluster", "aws_redshift", "aws_eip", "aws_opensearch", "aws_internet_gateway", "aws_instance", "aws_networkfirewall", "aws_guardduty", "aws_inspector", "aws_config_configuration_recorder", "aws_securityhub_account"):
        assert banned not in text, banned
    assert text.count('resource "aws_wafv2_web_acl"') == 1
    assert "enable_logging                = false" in text  # the trail records nothing
    assert "aws_cloudtrail_event_data_store" not in text  # CloudTrail Lake accepts no new customers


def test_wave2_nfw_declares_one_firewall_and_nothing_else_that_costs():
    text = TF_BY_MODULE["wave2-nfw"]
    assert text.count('resource "aws_networkfirewall_firewall" ') == 1 and text.count("subnet_mapping {") == 2  # the firewall's and the association's
    for banned in ("aws_nat_gateway", "aws_lb", "aws_db_", "aws_rds", "aws_eks_cluster", "aws_redshift", "aws_eip", "aws_opensearch", "aws_internet_gateway", "logging_configuration"):
        assert banned not in text, banned
    assert "delete_protection                 = false" in text


def test_wave2_rds_declares_only_what_its_cost_note_prices():
    text = TF_BY_MODULE["wave2-rds"]
    for banned in ("aws_nat_gateway", "aws_lb", "aws_eks_cluster", "aws_redshift", "aws_eip", "aws_opensearch", "aws_internet_gateway", "aws_rds_cluster_instance_multi"):
        assert banned not in text, banned
    assert text.count('resource "aws_db_instance"') == 1 and text.count('resource "aws_rds_cluster_instance"') == 1
    assert 'storage_type                = "gp2"' in text and "gp2 storage for it" in (SEED / "wave2-rds" / "cost.md").read_text(encoding="utf-8")  # the priced storage is the applied storage
    assert 'instance_class              = "db.t4g.micro"' in text and 'instance_class       = "db.serverless"' in text
    assert "publicly_accessible         = false" in text and "multi_az                    = false" in text
    assert "skip_final_snapshot         = true" in text and "deletion_protection         = false" in text


#: Wave 3a: per module, the one resource of each billed type its cost note prices (Terraform type: count) and the
#: settings that fix the price (each `name = value` must appear, whatever the alignment). Every other Terraform type in
#: COSTLY_TF is banned from it.
WAVE3A = {
    "wave3-redshift": (
        {"aws_redshift_cluster": 1, "aws_redshiftserverless_workgroup": 1, "aws_kms_key": 1},
        {"node_type": '"ra3.large"', "cluster_type": '"single-node"', "base_capacity": "8", "publicly_accessible": "false", "skip_final_snapshot": "true", "enable": "false"},
    ),
    "wave3-elasticache": (
        {"aws_elasticache_replication_group": 1, "aws_elasticache_cluster": 1, "aws_elasticache_serverless_cache": 1},
        {"node_type": '"cache.t4g.micro"', "num_cache_clusters": "1", "maximum": "1000", "snapshot_retention_limit": "0"},
    ),
    "wave3-eks": (
        {"aws_eks_cluster": 1, "aws_eks_node_group": 1, "aws_internet_gateway": 1},
        {"instance_types": '["t3.medium"]', "desired_size": "1", "max_size": "1", "support_type": '"STANDARD"', "endpoint_public_access": "false"},
    ),
    "wave3-opensearch": (
        {"aws_opensearch_domain": 1},
        {"instance_type": '"t3.small.search"', "instance_count": "1", "volume_type": '"gp2"', "volume_size": "10"},
    ),
}
COSTLY_TF = ("aws_nat_gateway", "aws_lb", "aws_alb", "aws_eip", "aws_db_instance", "aws_rds_cluster", "aws_rds_cluster_instance", "aws_db_proxy", "aws_networkfirewall_firewall", "aws_instance", "aws_eks_cluster", "aws_eks_node_group", "aws_redshift_cluster", "aws_redshiftserverless_workgroup", "aws_elasticache_replication_group", "aws_elasticache_cluster", "aws_elasticache_serverless_cache", "aws_elasticache_global_replication_group", "aws_opensearch_domain", "aws_opensearchserverless_collection", "aws_internet_gateway", "aws_kms_key", "aws_vpc_endpoint")


@pytest.mark.parametrize("module", sorted(WAVE3A))
def test_wave3a_declares_only_what_its_cost_note_prices(module):
    text = TF_BY_MODULE[module]
    counts, settings = WAVE3A[module]
    for tf_type in COSTLY_TF:
        assert len(re.findall(rf'^resource "{tf_type}" ', text, re.M)) == counts.get(tf_type, 0), (module, tf_type)
    for name, value in settings.items():
        assert re.search(rf"^\s*{name}\s+=\s+{re.escape(value)}", text, re.M), (module, name)
    cost = (SEED / module / "cost.md").read_text(encoding="utf-8")
    assert "Time box" in cost and "Standing cost left running by mistake" in cost


@pytest.mark.parametrize("module", MODULES)
def test_a_module_attaching_aws_managed_policies_declares_no_policy_of_its_own(module):
    # The role entry joins each attachment to a seeded policy; with a policy of the module's own seeded, an AWS
    # managed policy attached beside it would be an unresolved edge target, which stops the comparison.
    text = TF_BY_MODULE[module]
    if ":iam::aws:policy" in text:
        assert not re.search(r'^resource "aws_iam_policy" ', text, re.M), module


def test_no_account_number_key_or_secret_in_the_seed_tree():
    for path in SEED.rglob("*"):
        if not path.is_file() or ".terraform" in path.parts or path.suffix in (".pyc", ".zip") or path.name == ".terraform.lock.hcl":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found = set(re.findall(r"(?<![\d.])\d{12}(?![\d.])", text)) - {"000000000000", "123456789012"}  # the two obvious dummies
        assert not found, path
        assert not re.search((r"AKIA[0-9A-Z]{12,}|ASIA[0-9A-Z]{12,}|aws_secret" + "_access_key|BEGIN [A-Z ]*PRIVATE KEY"), text), path
