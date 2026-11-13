# crosscheck

Compares `aws_core` with Cartography's AWS data model, statically and deterministically, and writes a
report. It is a canary for drift and a way to find what we have not built; it is not part of the plugin
wheel and imports neither project. Specification: `specs/spec-aws-core-crosscheck.md`.

```
python3 -I tools/crosscheck/crosscheck.py --cartography ~/src/cartography \
    [--weights tools/crosscheck/weights/cartography-set-v1.json] \
    [--out DIR] [--baseline DIR/report.json] [--fail-on-regression]
```

It needs only the Python this repository uses (3.14) and nothing installed. `--cartography` is a clone of
`cartography-cncf/cartography` (it is only read, by parsing; nothing in it is run). The same inputs give
the same `report.json`, so keep one from a known-good run and pass it as `--baseline`: the report then lists
the gaps that appeared and the ones that closed, and `--fail-on-regression` turns a new gap into exit code 1.

## What it measures

| Metric | Question |
| --- | --- |
| Coverage | Of the labels Cartography models, how many do we collect? |
| Accuracy | On the types both collect, how many of Cartography's properties do we hold as typed fields? (Compared as AWS API keys, since field names differ; types that store their whole configuration are counted separately.) |
| Linkage | Of Cartography's relationships between comparable types, how many have a matching edge between the same two types of ours? |
| Operations | Which AWS API reads does Cartography make that we do not? |
| Security attributes | A reviewed list (`security_attributes.json`) of encryption, exposure, logging and similar attributes. Verdicts: `typed` (a column the manifest fills), `configuration-only` (no column, but we make the named read and the type keeps its configuration), `column-unfilled` (a model column the manifest never maps), `not-evidenced`, `type-not-collected`, or stale. |
| Tags | Do both read tags for a type? |
| Identity | Do both key a type on an ARN? |
| Containment | Account membership (we use a dimension, not an edge) and regional containment. |
| Ledger | Under the weighting, how much of the coverage ledger is collected, decided, or open. |
| Cartography candidate defects | Leads found by static checks, and the findings people have verified (`cartography_findings.json`). |

A baseline diff counts as a gap anything in the run's shortfall list: an uncollected label, a missing or declared-only edge, an operation we lack, an open ledger row, any non-typed security verdict (so typed becoming configuration-only is new), an untyped reference property, a tag, identity or ownership difference.

Every figure is also given weighted. A static comparison cannot say whether a collected value is right;
that is what a live account decides (`specs/spec-aws-core-collection-oracle.md`).

## Weightings

A weighting is a JSON file in `weights/` (schema: `weights/weights.schema.json`), separate from the script.
Rules are tried in order and the first match wins. A rule selects by Cartography label (`carto_label`), by
aws_core type (`tap_type`), by security attribute (`attribute`) or by CloudFormation type in the coverage
ledger (`cfn_type`), and carries a weight and a reason. A file may `extend` another and its rules then come
first. To make a weighting for a new situation, copy one, change the rules, and pass `--weights`. Nothing in
`crosscheck.py` has to change.

| File | Use |
| --- | --- |
| `cartography-set-v1.json` | Cartography's own modelled set, with the long-established core services at 5, supporting services and Bedrock at 3, the rest of its set at 1. Draft. |
| `fedramp-additions-v1.json` | Proposed overlay for a FedRAMP boundary. Draft. |

## Keeping the mapping honest

- `label_map.json` maps Cartography labels to our types where their names differ. An empty list means a
  reviewed gap; a label in neither the map nor name-matched is reported as unmapped, so a new Cartography
  label shows up as work rather than disappearing.
- `security_attributes.json` needs all three names for each entry. A name that stops existing is reported as
  stale, and the tests check every entry against this repository's own models.
- The tests run with `python3 -m pytest tools/crosscheck/tests` (needs pytest).

## Limits

- Only what Cartography declares in `cartography/models/aws` is read. Its non-model code is not.
- Relationships are compared by the pair of types, undirected, not by name or direction.
- Our edges are read from the manifest, the models' edge declarations and the edge definitions; an edge
  definition lists sources and targets as a cross product, which can overstate what we emit.
- Operations match on the normalised name; Cartography's service is known only where a file uses one client.
- A relationship whose target this reader cannot resolve is left out and named under `inputs.cartography.unresolved_relationships` (three today).

## CloudFormation verifier

`cfn_verifier.py` compares aws_core with AWS's own CloudFormation data. It reads files only: it makes no
network or AWS call. The files come from `cfn_fetch.sh <dir>` (public downloads of the us-gov-west-1,
us-gov-east-1 and commercial us-east-1 resource specifications, `curl --fail`, a `manifest.tsv` of URL, HTTP
status, sha256, size and `ResourceSpecificationVersion`) and from the CloudFormation schema bundle the coverage
ledger already reads (`cfn_reader.read_bundle` calls the ledger's own `load_cfn_bundle`, so the bundle must lie
under the working directory or the temporary directory, as for the ledger). The run record (`--run-record`) must
lie inside the plugin checkout (`--plugin`, this repository by default) or the working directory; a record kept
elsewhere is copied in first. Both limits exist because the paths come from the command line and the tool reads
and hashes whatever they name. The downloaded inputs are data and are never imported; the plugin checkout is
code, since the bundle is read through the ledger's own reader loaded from its `sources.py`, so `--plugin` must
name a checkout you trust (the default is this repository). `cfn_fetch.sh` refuses a destination, a `.part` file
or a target that is already a symbolic link, so a planted link in a shared `/tmp` cannot redirect its writes; a
fresh directory (`mktemp -d`) is the safer habit.

    cfn_fetch.sh /tmp/cfn-specs
    python3 -I cfn_verifier.py --spec /tmp/cfn-specs/spec-us-gov-west-1.json --spec /tmp/cfn-specs/spec-us-east-1.json \
        --bundle CloudformationSchema.zip --manifest /tmp/cfn-specs/manifest.tsv \
        --run-record ../validate/runs/wave0-2026-11-01.json --out out/

It reports availability leads per region (absence is a lead, never a verdict) with the ledger tier and, given a
run record, the observed outcome and every contradiction among the three; a backtest of the specification
against the record; top-level property conformance per type (read-only and writable split, weighted by the
`cfn_type` rules in `--weights`); an identity check (manifest natural key against the schema's
`primaryIdentifier`) and a tags check (`tags` source and `tag_findings` against `tagging.taggable`); and drift
with `--baseline` / `--fail-on-regression`, which separates a change in AWS's specification (`reference_inputs_changed`)
from a change in our code (`our_inputs_changed`). The specification is a reference, not ground truth.

Limits: the backtest and the run-record contradictions count entity types, the run record's unit, where an
entity type is present if any ledger type it serves is in the specification. Property comparison is top-level
and by normalised name, so a renamed API field reads as missing; the security ranking is a name heuristic.
Write-only properties are not counted against us, as they cannot be read back.

## Terraform AWS provider as a second reference

`tf_conformance.py` compares, for each of our types that maps to a Terraform resource, the AWS API key each typed field is
filled from (the manifest's `fields`) with the API field the provider fills the same attribute from (`d.Set` in its read
function), and our read operations with the provider's. Terraform is a reference, not ground truth.

```
CROSSCHECK_DUMP_CONFINED=yes tools/crosscheck/terraform_dump.sh [-v 6.71.0] schema.json     # the only step that runs Terraform: init + providers schema; sanitised environment, NOT a sandbox
pip install --only-binary=:all: -r tools/crosscheck/requirements-terraform.txt      # tree-sitter, for the source layer only; wheels only, so no build backend runs
python3 -I tools/crosscheck/tf_conformance.py --terraform-schema schema.json --terraform-source ~/src/terraform-provider-aws \
    --terraform-version 6.71.0 [--out DIR]   # DIR must lie under the directory you run it from
```

The schema is a release and the source a checkout, so the source must be at the tag of the version the dump was made with: check out `v6.71.0` in the provider clone and pass `--terraform-version 6.71.0`. The run compares the checkout's HEAD with that tag's commit in the checkout's own `.git` and exits 4, with a banner in the report, if they differ, if the tag cannot be read, or if no version was given (a clone with packed tags works; `--allow-version-mismatch` accepts the result and the report still says it was not shown). It also exits 4 when the two inputs have different sets of resources. This catches a clone left on the wrong version; it does not prove the files are unmodified or that the tag is HashiCorp's, so a clone you do not trust needs the `source_sha256` in the report checked against one you do.

| File | Role |
| --- | --- |
| `terraform_dump.sh` | Writes the provider schema JSON, key-sorted, for a pinned provider version; prints its sha256. Never plans or applies. It sanitises the environment and does not sandbox the provider (see the spec's Dump Step): run it only in a disposable VM or container with no host mounts and no credentials; it refuses to start unless `CROSSCHECK_DUMP_CONFINED=yes` states that. Runs Terraform with an empty environment (`env -i`), a throwaway `HOME` and the dependency lock file in `terraform_locks/` enforced (`-lockfile=readonly`); a version with no committed lock file is refused. |
| `terraform_locks/` | One reviewed lock file per supported provider version, with checksums for darwin and linux on amd64 and arm64. To add a version, run `terraform providers lock` in a throwaway directory, review the hashes, commit the file. |
| `untrusted.py` | Reading a tree we did not write: no symlinks, nothing outside the root; and text made safe for Markdown and terminals. Used by the source reader and the report. |
| `terraform_reader.py` | Reads that file (never runs Terraform) into resources, flattened attributes with flags, taggability and identity. |
| `terraform_source.py` | Parses the provider's Go source with tree-sitter (never builds or runs it): registry, schema attribute names, attribute to API field from `d.Set`, read operations. |
| `tf_conformance.py` | The comparison and its `report.json` / `report.md`. |
| `terraform_label_map.json` | Terraform resource to our types where names differ (several resources may map to one type; an empty list is a reviewed gap). |

Limits: the source checkout should be the commit of the provider release the dump was made from (the report records both).
Framework-style resources have no `d.Set`; their API field is inferred from the model struct's Go field name (marked
`autoflex-convention`). Only top-level attributes are compared; a nested block counts as read when the provider reads its
parent. `tf_conformance.py` is the only crosscheck module that needs anything beyond the standard library.
