# AWS Core Crosscheck Specification

## Philosophy

The coverage ledger says what `aws_core` intends to collect. It cannot say how that compares with mature
collectors that have had years of use, nor tell us when we have drifted from them. Several of those
collectors describe their model of AWS in source that can be read without running anything: Cartography
declares each node's properties and relationships as dataclasses with literal names, and others list
their resource types, columns or read operations in code or documentation. A comparison against such a
source needs no AWS account, no database, and no execution of either project.

The crosscheck is a test instrument. It reduces a **reference** (another tool's model of AWS) and
`aws_core` to the same shape, applies a weighting that says what matters, and writes a report. It is the
cheap, always-available layer of a two-layer check; the second layer is the live oracle
(`spec-aws-core-collection-oracle.md`), and live validation in waves
(`spec-aws-core-live-validation.md`) decides every disagreement the static layer raises. Where the static
layer finds a defect in a reference, the finding is recorded with its evidence so it can go back to that
project.

Cartography is the first reference and the only one built. This specification describes it as it is, and
describes the contract a second reference must meet so that adding one means writing a reader and a map,
not a new tool.

## Provenance

- Read 2026-11-01, from a Cartography clone at commit `2560d4d55794` (committed 2026-10-30):
  `cartography/models/core` (the node, property and relationship base classes), `cartography/models/aws`
  (206 node schemas forming 175 labels, 471 relationships) and the use of boto3 in `cartography/intel/aws`.
- Run 2026-11-01: the reader and comparator against that clone and this repository, repeatedly, with
  byte-identical output, under both shipped weightings. Not run against a live account.
- Read and run 2026-11-01, for the Terraform AWS provider: its file layout, one resource and one registry file;
  `terraform providers schema -json` for provider v6.71.0 (1,746 resources); and a tree-sitter pass over 4,588 Go
  files at commit `6979502b5176` (top-level attribute names agree with the dump on 1,200 of 1,233 resources).
- Read and run 2026-11-01, for the CloudFormation resource specifications: the `us-gov-west-1` file (1,030
  types) against a live run. Detail in `spec-aws-core-availability.md`.
- Not read, and described only from general knowledge that has to be confirmed before an adapter is written: every
  other reference in the candidate table (Cloud Custodian, Steampipe, CloudQuery, the first-party type lists).
- Designed, not observed: the mapping from Cartography labels to our types, the security-attribute list and
  the weight values are first judgements and unreviewed, except the 29 labels the operator reviewed on
  2026-11-01.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Deterministic | The same inputs give byte-identical reports, so two runs can be diffed |
| 2. | Inert         | The comparator imports and runs no reference project and writes nothing but its report; the one bounded exception is a separate dump step (see Inert Readers) |
| 3. | Separable     | What matters is a data file, not code, and several can coexist |
| 4. | Honest        | A thing the comparison cannot see is counted and named, never a pass |
| 5. | Attributable  | A flaw found in a reference is recorded with evidence, apart from our gaps |
| 6. | Extensible    | A new reference needs a reader, a label map and tests, not changes to the metrics |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-aws-core-crosscheck-inert | [Inert Readers](#inert-readers) | Implemented | Every tree is parsed, never imported or executed |
| req-aws-core-crosscheck-metrics | [Metrics](#metrics) | Implemented | Coverage, accuracy, linkage, operations, security attributes, tags, identity, containment, ledger |
| req-aws-core-crosscheck-weighting | [Weighting](#weighting) | Implemented | Rules in a data file; first match wins; files may extend one another |
| req-aws-core-crosscheck-mapping | [Mapping](#mapping) | Implemented | A reviewed label map; unreviewed labels are reported, stale entries fail tests |
| req-aws-core-crosscheck-report | [Report](#report) | Implemented | Stable JSON and Markdown; no timestamps; printed text sanitised |
| req-aws-core-crosscheck-drift | [Drift](#drift) | Implemented | Baseline diff, non-zero exit on a new gap or an incomparable baseline |
| req-aws-core-crosscheck-defects | [Reference Defects](#reference-defects) | Implemented | Static leads and verified findings, kept apart from our gaps |
| req-aws-core-crosscheck-live | [Live Tie-Break](#live-tie-break) | Proposed | A live account decides each static disagreement |
| req-aws-core-crosscheck-reference | [Reference Adapters](#reference-adapters) | Proposed | The contract a reference reader meets |
| req-aws-core-crosscheck-normal-form | [Normal Form](#normal-form) | Proposed | The shape every reference is reduced to |
| req-aws-core-crosscheck-candidates | [Candidate References](#candidate-references) | Proposed | What other sources could give, and what is unconfirmed |
| req-aws-core-crosscheck-matrix | [Cross-Reference Matrix](#cross-reference-matrix) | Proposed | Results keyed by CloudFormation type, so references compare with each other |
| req-aws-core-crosscheck-addref | [Adding A Reference](#adding-a-reference) | Proposed | The steps, in order, with what Cartography taught |

### Inert Readers
----
RID: `req-aws-core-crosscheck-inert`

Status: `Implemented`

A reference reader parses source with `ast` (or reads JSON or documentation) and evaluates only literals. The
aws_core reader parses the models with `ast` and reads the manifest, edge definitions and ledger as JSON. No
project is imported, so the crosscheck needs no Django, no boto3 and no Neo4j, and a hostile clone cannot
execute anything. Text taken from an analysed tree is untrusted: control characters are replaced before it
reaches a terminal or `report.md`, a commit is reported only if it is shaped like one and read from a ref under
`refs/`, and the report records a digest of the files actually analysed. A tree with nothing to analyse is
refused, not scored as empty. It lives in `tools/crosscheck`, outside the wheel.

**Bounded exception: a data-producing dump step.** A reference whose model is only available by running its own
tool (the Terraform provider's schema dump) may have it produced by a separate step, never by the comparator. The
step runs once, in a fresh empty directory, with a pinned version, the dependency lock file's checksums enforced
(`-lockfile=readonly`), every `AWS_*` variable removed, a throwaway `HOME` and the shared AWS config and credentials
files pointed at nothing, so it can reach no credential; it performs no operation but the one that writes the data
file, whose version and sha256 it prints. The comparator reads the file as data and stays inert. Nothing else is
excepted.

### Metrics
----
RID: `req-aws-core-crosscheck-metrics`

Status: `Implemented`

| Metric | Definition |
| --- | --- |
| Coverage | Reference labels (artifacts excluded) that map to a type of ours, over all such labels |
| Accuracy | On mapped pairs, reference properties (infrastructure keys excluded) whose AWS API key is a typed field the manifest fills, over all such properties; types storing their configuration are reported separately |
| Linkage | Reference relationships between two mapped labels (the account link excluded) that have an edge between the same two types of ours; standalone (match-link) relationships count |
| Operations | The reference's AWS read operations that appear in our manifest or readers, by normalised name |
| Security attributes | Entries of a reviewed list, each typed (a column the manifest fills), configuration-only (no column; the read is made by that type's own entry or reader and the type keeps its configuration), column-unfilled, not-evidenced, stale or not collected |
| Tags, identity, containment | Whether both read tags, whether both key on an ARN, and how account and regional containment compare |
| Ledger | Under the weighting, the share of in-scope ledger types collected (verified or not), decided (collected, excluded or not enumerable), or unclassified; modeled-only rows are neither |

A relationship with an endpoint that is unmapped, a known gap or an artifact is `not-comparable` and counted
as such, so a high percentage cannot hide a narrow comparison. A metric a reference cannot support (a source
that lists resource types but no properties has no accuracy) is reported as not supported, never as zero.

### Weighting
----
RID: `req-aws-core-crosscheck-weighting`

Status: `Implemented`

A weighting file has a name, version, status (`draft` or `reviewed`), a default weight and an ordered list of
rules. A rule has exactly one selector (`carto_label`, `tap_type`, `attribute` or `cfn_type`, each an
`fnmatch` pattern), a non-negative weight and a reason. The first rule that matches wins. A file may name
another it `extends`; its rules then come first. A malformed file is refused, not guessed at. The script
holds no weight values. The report names the weighting, its status and a hash of the files in its chain.

An attribute without a rule of its own takes the weight of the type it belongs to. An edge weighs the lesser
of its two endpoints.

Selectors on our side (`tap_type`, `cfn_type`) do not depend on the reference, so a weighting written with them
works for any reference. A label selector names its reference (`carto_label` is Cartography's); each new
adapter registers its own label selector (for example `steampipe_table`), and a rule for another reference's
labels simply never matches.

### Mapping
----
RID: `req-aws-core-crosscheck-mapping`

Status: `Implemented`

`label_map.json` records Cartography labels that match a type of ours by a name other than the obvious one
(a list), labels that are reviewed gaps (an empty list), and labels that are sub-structures rather than
resources. A label found in none of these and not matching by name is reported as unmapped. The tests check
every alias target and every security-attribute name against this repository, so a rename here cannot leave
the mapping silently wrong. Each reference has its own map; all of them map to our entity types, which the
ledger ties to CloudFormation types.

### Report
----
RID: `req-aws-core-crosscheck-report`

Status: `Implemented`

`report.json` is sorted and carries no time. `report.md` leads with the metrics table, then the heaviest
gaps. The inputs section records both commits, a digest of each analysed source tree, the weighting and the
hashes of the mapping files.

### Drift
----
RID: `req-aws-core-crosscheck-drift`

Status: `Implemented`

A gap is anything the run counts as a shortfall: an uncollected label, a missing or declared-only edge, a
reference operation we lack, an unclassified weighted ledger row, any security attribute that is not typed (the
verdict is part of its id), an untyped reference property, a tag or identity difference. With a baseline, the
report adds the headline figures that changed, the gaps that are new, the gaps that closed, and which inputs
changed. A change in the reference's commit or source digest or in the weighting is shown as an input change,
so a move caused by the reference is told apart from one caused by us. `--fail-on-regression` exits 1 when a
gap is new, exits 1 when the baseline cannot be compared (a different schema version), and is an argument error
without a baseline.

### Reference Defects
----
RID: `req-aws-core-crosscheck-defects`

Status: `Implemented`

Static checks produce leads about a reference itself (for Cartography: a relationship whose target label no
schema defines). A lead is not a finding. A person verifies it and records it in the reference's findings file
with the commit, a summary and the evidence, and a status (`open`, `reported`, `acknowledged-upstream`,
`fixed-upstream`). A recorded finding suppresses its lead.

### Live Tie-Break
----
RID: `req-aws-core-crosscheck-live`

Status: `Proposed`

Each disagreement the static layer raises (a missing edge, an untyped attribute, an unmapped label) is checked
against a seeded live account through the oracle and the validation waves. The static report is the list of
what to check; the live result decides who is wrong, and a flaw in a reference found that way is recorded as a
finding.

### Reference Adapters
----
RID: `req-aws-core-crosscheck-reference`

Status: `Proposed`

A reference is supplied by an adapter with five parts:

| Part | What it is |
| --- | --- |
| Reader | Turns the reference's source into the normal form, inertly, and refuses a tree with nothing in it |
| Provenance | Name, version or commit, licence, and a digest of the files read |
| Capabilities | Which of the normal form's parts the reference has (properties, relationships, operations, tags, ownership), so an unsupported metric is reported as such |
| Label map | Its labels to our entity types, with reviewed gaps and artifacts, in a data file |
| Findings | Its own findings file and static-check leads |

Today the Cartography adapter is the flat set `carto_reader.py`, `label_map.json`, `cartography_findings.json`
beside the comparator. When a second reference arrives, the references move to
`tools/crosscheck/references/<name>/`, each holding its reader, label map, security-attribute names and
findings, and the comparator takes `--reference <name>`. That move is part of adding the second reference, not
done before it.

### Normal Form
----
RID: `req-aws-core-crosscheck-normal-form`

Status: `Proposed`

The shape the Cartography reader already produces, written down so a second adapter can meet it:

| Part | Shape |
| --- | --- |
| `nodes` | label to `{properties: {name: {key, kwargs}}, rels: [{kind, target, rel, direction}], files}` where `key` is the AWS API key the reference reads and `kwargs` marks an infrastructure value |
| `operations` | a set of `(service, operation)` with the operation normalised (lower case, alphanumeric); the service is empty where unknown |
| `all_labels` | every label the reference defines anywhere, so a relationship to a label that does not exist can be found |
| `leads` | candidate defects found by static checks |
| `capabilities` | which of the above the reference supplies |

A label split over several definitions is merged by label. A relationship declared apart from its source node is
attached to that node. Identical relationships are kept once.

### Candidate References
----
RID: `req-aws-core-crosscheck-candidates`

Status: `Proposed`

Each row says what was read or run, and where. A row that records no reading is what the source is expected to give,
unconfirmed, and must be confirmed before an adapter is written.

| Reference | Expected static source | Would give | Open point |
| --- | --- | --- | --- |
| Cartography | Python dataclasses (read) | All of the normal form | Done |
| Cloud Custodian | Python resource classes under its AWS resources package, with service, enumeration call and ARN type | Resource types, read operations, ARN types, tag handling; no property list | Whether the definitions are literal enough for `ast` |
| Steampipe AWS plugin | Go table definitions and per-table documentation | Columns (accuracy), read operations; relationships unlikely | Go is not parsed by `ast`; documentation may be the better source |
| CloudQuery AWS source | Go table definitions and documentation | Columns, relations between tables | As Steampipe |
| Terraform AWS provider (schema dump) | `terraform providers schema -json` for a pinned, signature-checked provider, written once to a file by a separate step and read by the crosscheck as data. Run 2026-11-01 with provider v6.71.0 in an empty directory with no credentials: about 20 MB in 8 seconds, 1,746 resources and 687 data sources | Resources; every attribute with its type, Required, Optional, Computed, sensitive and deprecated flags, nested blocks, descriptions; identity schemas (562 resources); `tags_all` (865 resources, a taggability signal). No parsing | Executes the provider binary, which the inert rule forbids, so the exception is written into the specification and confined to the dump step: pinned version, signature check at init, no credentials, output stored and hashed, and the comparator only reads the file. The dump has no API response field per attribute and no read operations. One AWS resource is often split over several Terraform resources |
| Terraform AWS provider (Go source, tree-sitter) | The provider's Go source under `internal/service/<service>/`, parsed with tree-sitter (parsing only, never built or imported). Run 2026-11-01 on commit `6979502b5176`: 4,588 files in about 4 seconds, one parse error | What the dump lacks: the API response field behind each attribute (`d.Set("is_enabled", key.metadata.Enabled)`, mapped for 9,108 of 11,457 SDK attributes), the read operations each resource makes (found for 909 of 1,233 SDK resources), tag and identity settings from the registry. Validated against the schema dump: top-level attribute names agree on 1,200 of 1,233 resources (97.3%) | Framework-style resources (514) map attributes to the API by name convention, not line by line; attribute names come through constants resolved from `names/attr_constants.csv`; about 26% of SDK resources' read operations are not yet found |
| Terraform AWS provider (documentation) | The same repository's `website/docs` pages (1,748 resource and 686 data-source pages) | Argument and attribute names and prose; the import identifier | Hand-written prose with Required/Optional markers in the one page read, not generated from the code as far as seen; the source is the better reference |
| AWS CloudFormation resource schemas | The schema bundle the coverage ledger already reads | Every property of every type, with read-only properties and tagging marked; no new reader needed beyond the ledger's | Write-model like Terraform; nothing about relationships beyond reference-typed properties |
| Terraform Cloud Control provider | Generated from the CloudFormation schemas | Nothing the CloudFormation schemas do not give | Adds nothing as a reference; relevant only as a seeding provider |
| First-party type lists (AWS Config, Cloud Control, Resource Explorer supported types) | Published lists | Coverage only, authoritative on what AWS can enumerate | Whether a list is machine-readable |

### Cross-Reference Matrix
----
RID: `req-aws-core-crosscheck-matrix`

Status: `Proposed`

With more than one reference, results are also keyed by CloudFormation type (through our entity types and the
ledger), giving one row per type: whether we collect it, and whether each reference models it. Two views follow.
**Consensus gaps** are types two or more references model that we do not collect, the strongest case for work.
**Unique to us** are types we collect that no reference models, where the live account is the only check. The
matrix is built from the per-reference reports and needs no new reader.

### Adding A Reference
----
RID: `req-aws-core-crosscheck-addref`

Status: `Proposed`

1. **Provenance first.** Record the source, licence, version or commit. If the model can only be obtained by
   running the tool, stop and raise it: the only exception to the inert rule is the bounded dump step described under
   Inert Readers, and any other needs a change to this specification.
2. **Write the reader** to the normal form, with synthetic-tree tests that include a hostile-text case, a
   proof that nothing in the tree is executed, and a refusal of an empty tree.
3. **Seed the label map** by automatic name matching, commit it, and list what remains unmapped.
4. **Review the unmapped labels** with the operator, one recommendation each (map, build, add to a parent, keep
   excluded, artifact, or decide after the live account), and apply the answers to the map and to tracked work.
5. **Weights.** Prefer `tap_type` and `cfn_type` rules; add the adapter's label selector only if a rule needs it.
6. **Run twice**, compare the bytes, and store the report as the baseline.
7. **Review leads**, verify any worth reporting, and record them with evidence.
8. **Update this specification:** the candidate table with what was read and run, and the provenance.

What the Cartography adapter taught, observed 2026-11-01 and worth checking in any reference:

- A label is often declared by several schemas that add properties or relationships; merge by label.
- Relationships can be declared apart from their node (match-links) and name both ends.
- A relationship can be defined in a different file from its node; resolve names across the whole tree, preferring
  the same file.
- Some labels exist only as an extra label or a helper object's argument; a "target label not defined" check must
  count them or it raises false leads.
- Helper names repeat across modules; index by module and name, and give an ambiguous name no credit.
- Operations are attributed to a service only where a file uses one client.
- Counts from the reference and from us differ in kind (a node per tag, a node per rule); decide whether each is
  a resource or an artifact before scoring it.

## Open Questions

1. **Weights.** The tiers in the shipped weightings are a first judgement and need review.
2. **Terraform dump.** Where the pinned schema file lives (committed, or regenerated by the dump step on demand), and the wording of the exception to the inert rule.
3. **FedRAMP scope.** Whether the overlay should add rules beyond the types and services it names.
4. **Edges by name.** Relationships are compared by type pair only; comparing by meaning needs a reviewed
   table of edge names.
5. **Second reference.** Which one first. The Terraform provider's schema dump is exact and needs no parsing, with tree-sitter over the Go source added
   for the API field behind each attribute; CloudFormation schemas need no new reader;
   Cloud Custodian is the likeliest to be readable with `ast`.
