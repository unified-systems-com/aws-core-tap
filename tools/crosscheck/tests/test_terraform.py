"""Tests for the Terraform reference: the schema-dump reader, the tree-sitter source layer and the conformance
comparison. Synthetic Go snippets and a synthetic dump stand in for the provider, so no checkout, Terraform
binary or network is needed. The tree-sitter tests are skipped when tree-sitter is not installed."""

import json
import re
import textwrap
from pathlib import Path

import pytest

import terraform_reader
import tf_conformance

CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _w(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))
    return path


# ---------------------------------------------------------------- schema dump

def make_dump(path: Path, resources: dict | None = None, identities: dict | None = None) -> Path:
    attr = lambda **k: {"type": "string", "description_kind": "plain", **k}  # noqa: E731
    res = resources if resources is not None else {
        "aws_kms_key": {
            "version": 0,
            "block": {
                "attributes": {
                    "arn": attr(computed=True),
                    "description": attr(optional=True, computed=True),
                    "is_enabled": {"type": "bool", "optional": True},
                    "policy": attr(optional=True, sensitive=True),
                    "tags": {"type": ["map", "string"], "optional": True},
                    "tags_all": {"type": ["map", "string"], "computed": True},
                    "id": attr(computed=True),
                },
                "block_types": {"timeouts": {"nesting_mode": "single", "block": {"attributes": {"create": attr(optional=True)}}}},
            },
        },
        "aws_s3_bucket_cors_configuration": {
            "version": 0,
            "block": {
                "attributes": {"bucket": attr(required=True)},
                "block_types": {
                    "cors_rule": {
                        "nesting_mode": "set",
                        "min_items": 1,
                        "block": {"attributes": {"allowed_methods": {"type": ["set", "string"], "required": True}}},
                    }
                },
            },
        },
    }
    ident = identities if identities is not None else {
        "aws_kms_key": {"version": 0, "attributes": {"id": {"type": "string", "required_for_import": True}, "region": {"type": "string", "optional_for_import": True}}}
    }
    path.write_text(json.dumps({"format_version": "1.0", "provider_schemas": {terraform_reader.PROVIDER: {"resource_schemas": res, "resource_identity_schemas": ident}}}))
    return path


class TestReader:
    def test_flattens_nested_blocks_with_dotted_paths_and_flags(self, tmp_path):
        d = terraform_reader.read(make_dump(tmp_path / "s.json"))
        r = d["resources"]["aws_s3_bucket_cors_configuration"]
        assert r["top_level"] == ["bucket", "cors_rule"]
        assert r["attributes"]["cors_rule"]["block"] is True and r["attributes"]["cors_rule"]["required"] is True
        assert r["attributes"]["cors_rule.allowed_methods"]["required"] is True
        assert d["resources"]["aws_kms_key"]["attributes"]["policy"]["sensitive"] is True
        assert "timeouts.create" in d["resources"]["aws_kms_key"]["attributes"]

    def test_taggable_and_identity(self, tmp_path):
        d = terraform_reader.read(make_dump(tmp_path / "s.json"))["resources"]
        assert d["aws_kms_key"]["taggable"] is True and d["aws_s3_bucket_cors_configuration"]["taggable"] is False
        assert d["aws_kms_key"]["identity"] == ["id", "region"] and d["aws_kms_key"]["identity_required"] == ["id"]

    def test_digest_follows_the_bytes(self, tmp_path):
        a = terraform_reader.read(make_dump(tmp_path / "a.json"))["sha256"]
        p = make_dump(tmp_path / "b.json")
        p.write_text(p.read_text() + "\n")
        assert terraform_reader.read(p)["sha256"] != a

    @pytest.mark.parametrize("text", ["{}", '{"provider_schemas": {}}', "not json", "[]"])
    def test_a_file_with_no_resources_is_refused(self, tmp_path, text):
        p = tmp_path / "s.json"
        p.write_text(text)
        with pytest.raises(ValueError):
            terraform_reader.read(p)

    def test_a_dump_with_an_empty_resource_map_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            terraform_reader.read(make_dump(tmp_path / "s.json", resources={}))

    def test_hostile_text_in_a_name_is_neutralised(self, tmp_path):
        res = {"aws_evil\x1b[31m": {"version": 0, "block": {"attributes": {"x\x07y": {"type": "string", "optional": True}}}}}
        d = terraform_reader.read(make_dump(tmp_path / "s.json", resources=res, identities={}))
        assert not CTRL.search(json.dumps(d))


# ---------------------------------------------------------------- Go source

import terraform_source  # noqa: E402  (importing it needs no tree-sitter; reading a tree does)


@pytest.fixture
def need_tree_sitter():
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_go")

NAMES = '''
    package names
    const (
        AttrARN         = "arn"
        AttrDescription = "description"
        AttrKeyID       = "key_id"
        AttrTags        = "tags"
        AttrTagsAll     = "tags_all"
    )
'''

REGISTRY = '''
    package kms
    func (p *servicePackage) SDKResources(ctx context.Context) []*inttypes.ServicePackageSDKResource {
        return []*inttypes.ServicePackageSDKResource{
            {
                Factory:  resourceKey,
                TypeName: "aws_kms_key",
                Name:     "Key",
                Tags:     inttypes.ResourceTagsAttribute(names.AttrID),
            },
            {
                Factory:  resourceAlias,
                TypeName: "aws_kms_alias",
            },
        }
    }
    func (p *servicePackage) FrameworkResources(ctx context.Context) []*inttypes.ServicePackageFrameworkResource {
        return []*inttypes.ServicePackageFrameworkResource{
            {
                Factory:  newGrantResource,
                TypeName: "aws_kms_grant",
            },
        }
    }
'''

KEY = '''
    package kms
    import (
        "github.com/aws/aws-sdk-go-v2/aws"
        "github.com/hashicorp/terraform-provider-aws/names"
    )
    func resourceKey() *schema.Resource {
        return &schema.Resource{
            ReadWithoutTimeout: resourceKeyRead,
            SchemaFunc: func() map[string]*schema.Schema {
                return map[string]*schema.Schema{
                    names.AttrARN: {Type: schema.TypeString, Computed: true},
                    "is_enabled": {Type: schema.TypeBool, Optional: true},
                    names.AttrDescription: {Type: schema.TypeString, Optional: true, Computed: true},
                    "rule": {
                        Type: schema.TypeList,
                        Optional: true,
                        Elem: &schema.Resource{
                            Schema: map[string]*schema.Schema{
                                "inner_only": {Type: schema.TypeString, Required: true},
                            },
                        },
                    },
                    names.AttrKeyID: {Type: schema.TypeString, Computed: true},
                }
            },
        }
    }
    func resourceKeyRead(ctx context.Context, d *schema.ResourceData, meta any) diag.Diagnostics {
        conn := meta.(*conns.AWSClient).KMSClient(ctx)
        key, err := findKeyByID(ctx, conn, d.Id())
        d.Set(names.AttrARN, key.Arn)
        d.Set("is_enabled", key.metadata.Enabled)
        d.Set(names.AttrDescription, aws.ToString(key.Description))
        d.Set("rule", flattenRules(key.Rules))
        setKeyID(d, key)
        return nil
    }
    func setKeyID(d *schema.ResourceData, key *awstypes.KeyMetadata) {
        d.Set(names.AttrKeyID, key.KeyId)
    }
    func findKeyByID(ctx context.Context, conn *kms.Client, id string) (*awstypes.KeyMetadata, error) {
        out, err := conn.DescribeKey(ctx, &kms.DescribeKeyInput{KeyId: aws.String(id)})
        _ = conn.CreateKey(ctx, nil)
        return out.KeyMetadata, err
    }
'''

ALIAS = '''
    package kms
    func resourceAlias() *schema.Resource {
        return &schema.Resource{
            ReadWithoutTimeout: resourceAliasRead,
            Schema: map[string]*schema.Schema{"name": {Type: schema.TypeString, Required: true}},
        }
    }
    func resourceAliasRead(ctx context.Context, d *schema.ResourceData, meta any) diag.Diagnostics {
        alias, err := listThings(ctx, meta)
        d.Set("name", alias.AliasName)
        return nil
    }
'''

GRANT = '''
    package kms
    type grantResource struct{}
    type grantResourceModel struct {
        GrantID types.String `tfsdk:"grant_id"`
        Name    types.String `tfsdk:"name"`
    }
    func newGrantResource(context.Context) (resource.ResourceWithConfigure, error) {
        return &grantResource{}, nil
    }
    func (r *grantResource) Schema(ctx context.Context, request resource.SchemaRequest, response *resource.SchemaResponse) {
        response.Schema = schema.Schema{
            Attributes: map[string]schema.Attribute{
                "grant_id": schema.StringAttribute{Computed: true},
                "name": schema.StringAttribute{Optional: true},
            },
            Blocks: map[string]schema.Block{
                "constraints": schema.ListNestedBlock{
                    NestedObject: schema.NestedBlockObject{
                        Attributes: map[string]schema.Attribute{"nested_only": schema.StringAttribute{Optional: true}},
                    },
                },
            },
        }
    }
    func (r *grantResource) Read(ctx context.Context, request resource.ReadRequest, response *resource.ReadResponse) {
        conn := r.Meta().KMSClient(ctx)
        out, err := findGrant(ctx, conn)
        response.Diagnostics.Append(fwflex.Flatten(ctx, out, &data)...)
    }
    func findGrant(ctx context.Context, conn *kms.Client) (*awstypes.Grant, error) {
        pages := kms.NewListGrantsPaginator(conn, &kms.ListGrantsInput{})
        return nil, nil
    }
'''

# A helper name defined in two other packages: the service that calls a bare `listThings` has none of its own.
OTHER_A = '''
    package aaa
    func listThings(ctx context.Context, meta any) { conn.ListAlphaThings(ctx, nil) }
'''
OTHER_B = '''
    package bbb
    func listThings(ctx context.Context, meta any) { conn.ListBetaThings(ctx, nil) }
'''


def make_provider(root: Path, extra: dict | None = None) -> Path:
    _w(root / "names/attr_consts_gen.go", NAMES)
    _w(root / "internal/service/kms/service_package_gen.go", REGISTRY)
    _w(root / "internal/service/kms/key.go", KEY)
    _w(root / "internal/service/kms/alias.go", ALIAS)
    _w(root / "internal/service/kms/grant.go", GRANT)
    _w(root / "internal/service/aaa/helper.go", OTHER_A)
    _w(root / "internal/service/bbb/helper.go", OTHER_B)
    _w(root / "internal/service/kms/key_test.go", "package kms\nfunc TestX() { conn.DescribeNeverRead() }\n")
    for rel, text in (extra or {}).items():
        _w(root / rel, text)
    return root


@pytest.fixture
def provider(tmp_path):
    return make_provider(tmp_path / "provider")


class TestSource:
    pytestmark = pytest.mark.usefixtures("need_tree_sitter")

    def test_registry_lists_sdk_and_framework_resources_from_literal_value_elements(self, provider):
        r = terraform_source.read(provider)["resources"]
        assert {t: v["kind"] for t, v in r.items()} == {"aws_kms_key": "sdk", "aws_kms_alias": "sdk", "aws_kms_grant": "framework"}
        assert r["aws_kms_key"]["factory"] == "resourceKey" and r["aws_kms_key"]["has_tags"] is True

    def test_names_constants_resolve_and_only_the_top_level_map_is_read(self, provider):
        k = terraform_source.read(provider)["resources"]["aws_kms_key"]
        # names.AttrARN -> arn; the nested Elem schema's `inner_only` is not a top-level attribute; the registry's Tags adds tags.
        assert set(k["attributes"]) == {"arn", "is_enabled", "description", "rule", "key_id", "tags", "tags_all"}
        assert k["attributes"]["description"] == ["Computed", "Optional"]

    def test_d_set_is_followed_through_a_helper_function(self, provider):
        k = terraform_source.read(provider)["resources"]["aws_kms_key"]
        assert k["api"]["key_id"]["api"] == ["KeyId"]  # set inside setKeyID, called from the read function
        assert k["api"]["is_enabled"]["api"] == ["Enabled"]  # the provider's own lower-case field `metadata` is dropped
        assert k["api"]["description"]["api"] == ["Description"]  # aws.ToString(...) is a package call, not a field
        assert k["api"]["arn"]["at"].endswith("key.go:" + k["api"]["arn"]["at"].rsplit(":", 1)[1])

    def test_read_operations_are_found_through_the_find_function_and_inputs(self, provider):
        k = terraform_source.read(provider)["resources"]["aws_kms_key"]
        assert k["ops"] == ["DescribeKey"]  # CreateKey is not a read; DescribeKeyInput names the same operation
        g = terraform_source.read(provider)["resources"]["aws_kms_grant"]
        assert g["ops"] == ["ListGrants"]  # the paginator and the Input literal

    def test_a_helper_name_defined_in_two_other_packages_lends_no_reads(self, provider):
        a = terraform_source.read(provider)["resources"]["aws_kms_alias"]
        assert a["read_found"] is True and a["ops"] == []

    def test_two_methods_of_one_name_on_different_types_lend_no_reads(self, tmp_path):
        extra = {
            "internal/service/kms/amb.go": '''
                package kms
                type one struct{}
                type two struct{}
                func (o *one) fetch(conn *kms.Client) { conn.ListOnes(nil) }
                func (t *two) fetch(conn *kms.Client) { conn.ListTwos(nil) }
                func resourceAmbiguousRead(ctx context.Context, d *schema.ResourceData, meta any) diag.Diagnostics {
                    x.fetch(conn)
                    return nil
                }
            ''',
            "internal/service/kms/service_package_gen.go": REGISTRY.replace(
                "TypeName: \"aws_kms_alias\",", "TypeName: \"aws_kms_alias\",\n},\n{\nFactory: resourceAmbiguous,\nTypeName: \"aws_kms_ambiguous\","
            ),
            "internal/service/kms/amb_res.go": '''
                package kms
                func resourceAmbiguous() *schema.Resource {
                    return &schema.Resource{ReadWithoutTimeout: resourceAmbiguousRead, Schema: map[string]*schema.Schema{"a": {Type: schema.TypeString, Optional: true}}}
                }
            ''',
        }
        r = terraform_source.read(make_provider(tmp_path / "p", extra))["resources"]["aws_kms_ambiguous"]
        assert r["read_found"] is True and r["ops"] == []

    def test_a_unique_method_name_is_followed(self, tmp_path):
        extra = {
            "internal/service/kms/amb.go": '''
                package kms
                type one struct{}
                func (o *one) fetch(conn *kms.Client) { conn.ListOnes(nil) }
                func resourceUniqueRead(ctx context.Context, d *schema.ResourceData, meta any) diag.Diagnostics {
                    x.fetch(conn)
                    return nil
                }
            ''',
            "internal/service/kms/service_package_gen.go": REGISTRY.replace(
                "TypeName: \"aws_kms_alias\",", "TypeName: \"aws_kms_alias\",\n},\n{\nFactory: resourceUnique,\nTypeName: \"aws_kms_unique\","
            ),
            "internal/service/kms/uniq.go": '''
                package kms
                func resourceUnique() *schema.Resource {
                    return &schema.Resource{ReadWithoutTimeout: resourceUniqueRead, Schema: map[string]*schema.Schema{"a": {Type: schema.TypeString, Optional: true}}}
                }
            ''',
        }
        assert terraform_source.read(make_provider(tmp_path / "p", extra))["resources"]["aws_kms_unique"]["ops"] == ["ListOnes"]

    def test_framework_schema_reads_attributes_and_blocks_but_not_nested_ones(self, provider):
        g = terraform_source.read(provider)["resources"]["aws_kms_grant"]
        assert set(g["attributes"]) == {"grant_id", "name", "constraints"}

    def test_framework_attributes_map_to_model_field_names_by_convention(self, provider):
        g = terraform_source.read(provider)["resources"]["aws_kms_grant"]
        assert g["mapping"] == "autoflex-convention" and g["api"]["grant_id"]["api"] == ["GrantID"]

    def test_a_schema_method_promoted_from_an_embedded_type_is_found(self, tmp_path):
        extra = {
            "internal/service/kms/service_package_gen.go": REGISTRY.replace(
                "Factory:  newGrantResource,\n                TypeName: \"aws_kms_grant\",", "Factory:  newWrappedResource,\n                TypeName: \"aws_kms_grant\","
            ),
            "internal/service/kms/wrapped.go": '''
                package kms
                type baseResource struct{}
                type wrappedResource struct {
                    baseResource
                }
                func newWrappedResource(context.Context) (resource.ResourceWithConfigure, error) {
                    return &wrappedResource{}, nil
                }
                func (r *baseResource) Schema(ctx context.Context, request resource.SchemaRequest, response *resource.SchemaResponse) {
                    response.Schema = schema.Schema{Attributes: map[string]schema.Attribute{"shared_attr": schema.StringAttribute{Optional: true}}}
                }
                func (r *baseResource) Read(ctx context.Context, request resource.ReadRequest, response *resource.ReadResponse) {
                    conn.GetWrapped(ctx, nil)
                }
            ''',
        }
        p = make_provider(tmp_path / "p", extra)
        (p / "internal/service/kms/grant.go").unlink()
        g = terraform_source.read(p)["resources"]["aws_kms_grant"]
        assert set(g["attributes"]) == {"shared_attr"} and g["ops"] == ["GetWrapped"]

    def test_test_files_are_not_read(self, provider):
        assert "DescribeNeverRead" not in json.dumps(terraform_source.read(provider))

    def test_a_schema_held_in_a_package_variable_and_cloned_is_found(self, tmp_path):
        extra = {
            "internal/service/kms/service_package_gen.go": REGISTRY.replace(
                "TypeName: \"aws_kms_alias\",", "TypeName: \"aws_kms_alias\",\n},\n{\nFactory: resourceCloned,\nTypeName: \"aws_kms_cloned\","
            ),
            "internal/service/kms/cloned.go": '''
                package kms
                var clonedSchema = map[string]*schema.Schema{"alpha": {Type: schema.TypeString, Optional: true}}
                func resourceCloned() *schema.Resource {
                    return &schema.Resource{Schema: maps.Clone(clonedSchema)}
                }
            ''',
        }
        assert set(terraform_source.read(make_provider(tmp_path / "p", extra))["resources"]["aws_kms_cloned"]["attributes"]) == {"alpha"}

    def test_the_commit_and_digest_are_recorded_and_the_digest_follows_the_files(self, provider):
        a = terraform_source.read(provider)
        assert a["commit"] == "unknown"
        (provider / ".git").mkdir()
        (provider / ".git/HEAD").write_text("a" * 40 + "\n")
        assert terraform_source.read(provider)["commit"] == "a" * 40
        _w(provider / "internal/service/kms/key.go", KEY + "\n// edit\n")
        assert terraform_source.read(provider)["source_sha256"] != a["source_sha256"]

    def test_hostile_text_in_the_tree_never_reaches_the_output(self, tmp_path):
        bad = "aws_evil\x1b]0;pwned\x07"
        extra = {
            "internal/service/kms/service_package_gen.go": REGISTRY.replace('"aws_kms_alias"', '"' + bad + '"'),
            "internal/service/kms/alias.go": ALIAS.replace('"name"', '"na\x1b[2Jme"'),
        }
        out = terraform_source.read(make_provider(tmp_path / "p", extra))
        assert not CTRL.search(json.dumps(out)) and not CTRL.search(repr(out))
        assert terraform_source.clean("a\x1bb") == "a?b"
        assert len(terraform_source.clean("x" * 1000)) <= 240

    def test_an_empty_or_garbage_tree_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            terraform_source.read(tmp_path)  # no internal/service
        _w(tmp_path / "g/names/attr_consts_gen.go", "}{ garbage ((")
        _w(tmp_path / "g/internal/service/x/service_package_gen.go", "func ( }{ not go at all {{{")
        with pytest.raises(ValueError):
            terraform_source.read(tmp_path / "g")

    def test_nothing_is_executed(self, tmp_path):
        marker = tmp_path / "ran"
        make_provider(tmp_path / "p", {"internal/service/kms/evil.go": f'package kms\nfunc init() {{ os.WriteFile("{marker}", nil, 0) }}\n'})
        terraform_source.read(tmp_path / "p")
        assert not marker.exists()


class TestMissingDependency:
    pytestmark = pytest.mark.usefixtures("need_tree_sitter")

    def test_the_error_names_the_requirements_file(self, monkeypatch):
        import builtins

        real = builtins.__import__

        def fake(name, *a, **k):
            if name in ("tree_sitter", "tree_sitter_go"):
                raise ImportError("blocked for the test")
            return real(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake)
        with pytest.raises(terraform_source.MissingDependency, match="requirements-terraform.txt"):
            terraform_source._parser()


# ---------------------------------------------------------------- conformance

def make_plugin(root: Path) -> Path:
    pkg = root / "tap_plugin/aws_core"
    _w(pkg / "models/kms.py", '''
        class Kms:
            ENTITY_TYPE: ClassVar[str] = "aws_core__aws_kms_key"
            NATURAL_KEY: ClassVar[tuple[str, ...]] = ("key_id",)
            FIELD_CRUD_SCHEMA: ClassVar[dict] = {"key_id": {}, "enabled": {}, "description": {}, "extra": {}}
    ''')
    _w(pkg / "models/s3.py", '''
        class S3:
            ENTITY_TYPE: ClassVar[str] = "aws_core__aws_s3_bucket"
            NATURAL_KEY: ClassVar[tuple[str, ...]] = ("name",)
            FIELD_CRUD_SCHEMA: ClassVar[dict] = {"name": {}, "allowed_methods": {}}
    ''')
    _w(pkg / "models/nothing.py", '''
        class Nothing:
            ENTITY_TYPE: ClassVar[str] = "aws_core__aws_no_such_thing"
            NATURAL_KEY: ClassVar[tuple[str, ...]] = ("name",)
            FIELD_CRUD_SCHEMA: ClassVar[dict] = {"name": {}}
    ''')
    entries = [
        {
            "entity_type": "aws_core__aws_kms_key",
            "service": "kms",
            "persist_configuration": False,
            "source": {"aws_op": "ListKeys"},
            "hydrate": [{"key": "x", "op": "DescribeKey"}],
            "natural_key": "KeyId",
            # key_id: agrees with d.Set KeyId; enabled: attribute is_enabled is not our name, but the leaf Enabled matches;
            # description: we read a different key than Terraform; extra: ours only.
            "fields": {"key_id": "KeyId", "enabled": "KeyMetadata.Enabled", "description": "Desc", "extra": "Extra", "arn": "_arn"},
        },
        {
            "entity_type": "aws_core__aws_s3_bucket",
            "service": "s3",
            "persist_configuration": True,
            "source": {"aws_op": "ListBuckets"},
            "natural_key": "Name",
            "fields": {"name": "Name", "allowed_methods": "CORSRules.AllowedMethods"},
        },
    ]
    _w(pkg / "collectors/boto3_collector/aws_resource_manifest.json", json.dumps({"manifest_version": 1, "entries": entries}))
    _w(pkg / "ledger/aws_coverage_ledger.json", json.dumps({"rows": []}))
    (pkg / "edges").mkdir(parents=True, exist_ok=True)
    return root


def make_weights(path: Path) -> Path:
    d = {"name": "t", "version": 1, "description": "d", "default_weight": 1, "rules": [{"tap_type": "aws_core__aws_kms_key", "weight": 5, "why": "w"}]}
    path.write_text(json.dumps(d))
    return path


@pytest.fixture
def conformance(tmp_path):
    prov = make_provider(tmp_path / "provider")
    # Terraform's KMS key read gives `description` from Description, but ours reads Desc; the alias file sends the two
    # S3 settings resources to our bucket.
    dump = make_dump(
        tmp_path / "s.json",
        resources={
            "aws_kms_key": {"version": 0, "block": {"attributes": {
                "arn": {"type": "string", "computed": True}, "is_enabled": {"type": "bool", "optional": True},
                "description": {"type": "string", "optional": True}, "key_id": {"type": "string", "computed": True},
                "tags": {"type": ["map", "string"], "optional": True}}}},
            "aws_kms_alias": {"version": 0, "block": {"attributes": {"name": {"type": "string", "required": True}}}},
            "aws_s3_bucket": {"version": 0, "block": {"attributes": {"bucket": {"type": "string", "required": True}}}},
            "aws_s3_bucket_cors_configuration": {"version": 0, "block": {"attributes": {"bucket": {"type": "string", "required": True}}}},
        },
        identities={},
    )
    return prov, dump, make_plugin(tmp_path / "plugin"), make_weights(tmp_path / "w.json")


class TestConformance:
    pytestmark = pytest.mark.usefixtures("need_tree_sitter")

    def test_auto_matching_and_aliases_with_a_union_of_resources(self):
        tap = {"aws_core__aws_kms_key", "aws_core__aws_s3_bucket", "aws_core__aws_rds_db_cluster"}
        tf = {"aws_kms_key", "aws_s3_bucket", "aws_s3_bucket_versioning", "aws_rds_cluster", "aws_nope", "aws_kms_alias"}
        amap = {"aliases": {"aws_s3_bucket_versioning": ["aws_core__aws_s3_bucket"], "aws_rds_cluster": ["aws_core__aws_rds_db_cluster"], "aws_kms_alias": [], "aws_gone": ["aws_core__aws_s3_bucket"]}}
        mapping, stale = tf_conformance.resolve(tap, tf, amap)
        assert mapping == {
            "aws_core__aws_kms_key": ["aws_kms_key"],
            "aws_core__aws_s3_bucket": ["aws_s3_bucket", "aws_s3_bucket_versioning"],
            "aws_core__aws_rds_db_cluster": ["aws_rds_cluster"],
        }
        assert stale == ["aws_gone: not in the schema dump"]

    def test_pair_categories(self, conformance):
        prov, dump, plugin, w = conformance
        rep = tf_conformance.run(dump, prov, plugin, w, "6.71.0")
        kms = next(p for p in rep["pairs"] if p["type"] == "aws_core__aws_kms_key")
        assert [a["field"] for a in kms["agree"]] == ["enabled", "key_id"]  # by API leaf, even when the names differ
        assert [d["field"] for d in kms["differ"]] == ["description"]
        assert kms["differ"][0]["terraform_api"] == ["Description"] and kms["differ"][0]["api"] == "Desc"
        assert [o["field"] for o in kms["ours_only"]] == ["extra"]  # arn (derived, '_arn') is not a typed field
        assert kms["our_derived_fields"] == 1
        assert [t["terraform"] for t in kms["terraform_only"]] == ["aws_kms_key.arn"]
        assert kms["operations"]["ours"] == ["describekey", "listkeys"] and kms["operations"]["shared"] == ["describekey"]
        assert kms["operations"]["terraform_only"] == []
        assert kms["weight"] == 5.0

    def test_headline_and_weighting(self, conformance):
        prov, dump, plugin, w = conformance
        h = tf_conformance.run(dump, prov, plugin, w)["headline"]
        assert (h["fields_agree"], h["fields_differ"]) == (2, 1)
        assert h["agreement_pct"] == pytest.approx(66.7, abs=0.1)
        assert h["weighted_agreement_pct"] == pytest.approx(66.7, abs=0.1)  # the S3 pair has no comparable fields
        assert h["terraform_only_attributes"] == 1

    def test_types_without_a_terraform_resource_are_listed(self, conformance):
        prov, dump, plugin, w = conformance
        rep = tf_conformance.run(dump, prov, plugin, w)
        assert [t["type"] for t in rep["types_without_terraform_resource"]] == ["aws_core__aws_no_such_thing"]

    def test_the_report_is_deterministic_and_the_markdown_is_clean(self, conformance):
        prov, dump, plugin, w = conformance
        a = json.dumps(tf_conformance.run(dump, prov, plugin, w), sort_keys=True)
        r = tf_conformance.run(dump, prov, plugin, w)
        assert a == json.dumps(r, sort_keys=True)
        assert not CTRL.search(tf_conformance.markdown(r).replace("\n", " "))

    def test_names_check_compares_source_with_the_dump_ignoring_runtime_attributes(self, conformance):
        prov, dump, plugin, w = conformance
        nc = tf_conformance.run(dump, prov, plugin, w)["names_check"]
        assert nc["compared"] == 2 and nc["in_dump_not_in_source"] == ["aws_s3_bucket", "aws_s3_bucket_cors_configuration"]
        by = {d["type"]: d for d in nc["different"]}
        assert by["aws_kms_key"]["only_in_source"] == ["rule", "tags_all"] and by["aws_kms_key"]["only_in_dump"] == []

    def test_the_cli_writes_both_files_and_a_missing_source_is_an_argument_error(self, conformance, tmp_path, capsys):
        prov, dump, plugin, w = conformance
        out = tmp_path / "out"
        args = ["--terraform-schema", str(dump), "--terraform-source", str(prov), "--plugin", str(plugin), "--weights", str(w), "--out", str(out)]
        assert tf_conformance.main(args) == 0
        assert (out / "report.json").is_file() and (out / "report.md").is_file()
        with pytest.raises(SystemExit):
            tf_conformance.main(["--terraform-schema", str(dump), "--terraform-source", str(tmp_path / "missing"), "--plugin", str(plugin)])
        capsys.readouterr()


class TestCommittedAliasFile:
    def test_shape_and_every_alias_target_is_a_real_type(self):
        root = Path(__file__).resolve().parents[3]
        import tap_reader

        types = set(tap_reader.read(root)["types"])
        amap = json.loads((Path(__file__).resolve().parents[1] / "terraform_label_map.json").read_text())
        assert set(amap) == {"_description", "aliases"}
        for tf, ours in amap["aliases"].items():
            assert re.fullmatch(r"aws_[a-z0-9_]+", tf), tf
            assert set(ours) <= types, (tf, sorted(set(ours) - types))


# ---------------------------------------------------------------- untrusted trees and safe text

import os  # noqa: E402
import subprocess  # noqa: E402

import untrusted  # noqa: E402

DUMP_SCRIPT = Path(__file__).resolve().parents[1] / "terraform_dump.sh"


class TestUntrusted:
    def test_md_safe_leaves_no_markdown_or_terminal_structure(self):
        hostile = "line one\n# forged heading\n![x](http://evil/p.png) <script>alert(1)</script> `code` | a | b \x1b]52;c;AAAA\x07 [l](u)"
        out = untrusted.md_safe(hostile)
        assert "\n" not in out and "\x1b" not in out and "\x07" not in out
        assert not any(c in out for c in "`<>[]|\\")
        assert "forged heading" in out  # the words survive; only the structure is gone

    def test_md_safe_truncates(self):
        assert len(untrusted.md_safe("x" * 5000)) <= 300

    def test_the_conformance_report_uses_it(self):
        assert tf_conformance._clean is untrusted.md_safe

    def test_a_symlinked_file_is_refused_and_never_read(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.go"
        secret.write_text("package secret // DISTINCTIVE-MARKER\n")
        root = tmp_path / "provider"
        (root / "names").mkdir(parents=True)
        pkg = root / "internal" / "service" / "kms"
        pkg.mkdir(parents=True)
        os.symlink(secret, pkg / "linked.go")
        with pytest.raises(untrusted.UntrustedTreeError):
            untrusted.files_in(root, pkg, "*.go")
        with pytest.raises(untrusted.UntrustedTreeError):
            untrusted.read_bytes(root, pkg / "linked.go")

    def test_a_symlinked_package_directory_is_refused(self, tmp_path):
        pytest.importorskip("tree_sitter")
        pytest.importorskip("tree_sitter_go")
        import terraform_source

        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "x.go").write_text("package x\n")
        root = tmp_path / "provider"
        (root / "names").mkdir(parents=True)
        svc = root / "internal" / "service"
        svc.mkdir(parents=True)
        os.symlink(outside, svc / "sneaky")
        with pytest.raises(untrusted.UntrustedTreeError):
            terraform_source.read(root)

    def test_a_symlinked_names_directory_is_refused(self, tmp_path):
        pytest.importorskip("tree_sitter")
        pytest.importorskip("tree_sitter_go")
        import terraform_source

        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "provider"
        (root / "internal" / "service").mkdir(parents=True)
        os.symlink(outside, root / "names")
        with pytest.raises(untrusted.UntrustedTreeError):
            terraform_source.read(root)


class TestDumpScript:
    """terraform_dump.sh against a stub `terraform`: what the provider process would be able to see."""

    def _stub(self, tmp_path):
        bindir = tmp_path / "bin"
        bindir.mkdir()
        log = tmp_path / "log"
        log.mkdir()
        stub = bindir / "terraform"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            f'n=$(ls "{log}" | wc -l)\n'
            f'{{ echo "ARGS: $*"; env; }} > "{log}/call$n.txt"\n'
            'if [ "$1" = "providers" ]; then echo \'{"provider_schemas":{}}\'; fi\n'
        )
        stub.chmod(0o755)
        return bindir, log

    def _run(self, tmp_path, extra_env=None, args=None):
        bindir, log = self._stub(tmp_path)
        env = {"PATH": f"{bindir}:{os.environ['PATH']}", "HOME": str(tmp_path / "realhome"), **(extra_env or {})}
        out = tmp_path / "out.json"
        proc = subprocess.run(["bash", str(DUMP_SCRIPT), *(args or []), str(out)], env=env, capture_output=True, text=True, check=False)
        return proc, log

    def test_the_provider_process_sees_no_credentials_and_a_throwaway_home(self, tmp_path):
        proc, log = self._run(
            tmp_path,
            {"AWS_ACCESS_KEY_ID": "AKIAFAKE", "AWS_SECRET_ACCESS_KEY": "s3cret", "AWS_PROFILE": "p", "GITHUB_TOKEN": "tok", "TF_VAR_x": "v", "TF_CLI_CONFIG_FILE": "/etc/x"},
        )
        assert proc.returncode == 0, proc.stderr
        calls = sorted(log.glob("call*.txt"))
        assert len(calls) == 2
        for call in calls:
            text = call.read_text()
            names = {line.split("=", 1)[0] for line in text.splitlines() if "=" in line and not line.startswith("ARGS")}
            assert not [n for n in names if (n.startswith("AWS_") and n != "AWS_EC2_METADATA_DISABLED") or n in ("GITHUB_TOKEN", "TF_CLI_CONFIG_FILE") or n.startswith("TF_VAR")], names
            assert "AWS_EC2_METADATA_DISABLED=true" in text
            home = next(line.split("=", 1)[1] for line in text.splitlines() if line.startswith("HOME="))
            assert "realhome" not in home
            assert "AKIAFAKE" not in text and "s3cret" not in text
        assert "-lockfile=readonly" in calls[0].read_text()
        assert "providers schema -json" in calls[1].read_text()

    def test_a_proxy_url_carrying_credentials_is_not_passed_on(self, tmp_path):
        proc, log = self._run(tmp_path, {"HTTPS_PROXY": "http://user:hunter2@proxy.example:3128", "HTTP_PROXY": "http://proxy.example:3128"})
        assert proc.returncode == 0, proc.stderr
        assert "not passing HTTPS_PROXY on: it carries credentials" in proc.stderr
        for call in log.glob("call*.txt"):
            text = call.read_text()
            assert "hunter2" not in text and "HTTPS_PROXY" not in text
            assert "HTTP_PROXY=http://proxy.example:3128" in text

    def test_a_version_with_no_committed_lock_file_is_refused(self, tmp_path):
        proc, log = self._run(tmp_path, args=["-v", "0.0.1"])
        assert proc.returncode == 1 and "refusing to run an unverified provider" in proc.stderr
        assert list(log.glob("call*.txt")) == []  # terraform was never started

    def test_every_committed_lock_file_names_its_version(self):
        locks = sorted((DUMP_SCRIPT.parent / "terraform_locks").glob("*.lock.hcl"))
        assert locks
        for lock in locks:
            version = lock.name[: -len(".lock.hcl")]
            text = lock.read_text()
            assert f'version     = "{version}"' in text and 'hashes = [' in text and "h1:" in text
