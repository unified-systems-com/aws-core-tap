# AWS Core Crosscheck Specification

## Philosophy

The coverage ledger says what `aws_core` intends to collect. It cannot say how that compares with a mature
collector that has had years of use, nor tell us when we have drifted from one. Cartography models a large
part of AWS declaratively: each node's properties and relationships are dataclasses with literal names. That
makes a comparison possible without an AWS account, without a database, and without running either
project.

The crosscheck is a test instrument. It reads two source trees, applies a weighting that says what matters,
and writes a report. It is the cheap, always-available layer of a two-layer check; the second layer is the
live oracle (`spec-aws-core-collection-oracle.md`), which decides every disagreement the static layer
raises. Where the static layer finds a defect in Cartography, the finding is recorded with its evidence so it
can go back to that project.

## Provenance

- Read 2026-11-01, from a clone at commit `2560d4d55794` (committed 2026-10-30): `cartography/models/core`
  (the node, property and relationship base classes), `cartography/models/aws` (206 node schemas, 471
  relationships), and the use of boto3 in `cartography/intel/aws`.
- Run 2026-11-01: the reader and comparator against that clone and this repository, twice with identical
  output, under both shipped weightings. Not run against a live account.
- Designed, not observed: the mapping from Cartography labels to our types, the security-attribute list and
  the weight values are first judgements by the author and unreviewed.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Deterministic | The same inputs give byte-identical reports, so two runs can be diffed |
| 2. | Inert         | Neither project is imported or run; nothing is written but the report |
| 3. | Separable     | What matters is a data file, not code, and several can coexist |
| 4. | Honest        | A thing the comparison cannot see is counted and named, never a pass |
| 5. | Attributable  | A flaw found in the reference is recorded with evidence, apart from our gaps |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-aws-core-crosscheck-inert | [Inert Readers](#inert-readers) | Implemented | Both trees are parsed, never imported or executed |
| req-aws-core-crosscheck-metrics | [Metrics](#metrics) | Implemented | Coverage, accuracy, linkage, operations, security attributes, tags, identity, containment, ledger |
| req-aws-core-crosscheck-weighting | [Weighting](#weighting) | Implemented | Rules in a data file; first match wins; files may extend one another |
| req-aws-core-crosscheck-mapping | [Mapping](#mapping) | Implemented | A reviewed label map; unreviewed labels are reported, stale entries fail tests |
| req-aws-core-crosscheck-report | [Report](#report) | Implemented | Stable JSON and Markdown; no timestamps |
| req-aws-core-crosscheck-drift | [Drift](#drift) | Implemented | Baseline diff, optional non-zero exit on a new gap |
| req-aws-core-crosscheck-defects | [Reference Defects](#reference-defects) | Implemented | Static leads and verified findings, kept apart from our gaps |
| req-aws-core-crosscheck-live | [Live Tie-Break](#live-tie-break) | Proposed | A live account decides each static disagreement |

### Inert Readers
----
RID: `req-aws-core-crosscheck-inert`

Status: `Implemented`

The Cartography reader parses source with `ast` and evaluates only literals. The aws_core reader parses the
models with `ast` and reads the manifest, edge definitions and ledger as JSON. Neither imports the project it
reads, so the crosscheck needs no Django, no boto3 and no Neo4j, and a hostile clone cannot execute anything.
It lives in `tools/crosscheck`, outside the wheel.

### Metrics
----
RID: `req-aws-core-crosscheck-metrics`

Status: `Implemented`

| Metric | Definition |
| --- | --- |
| Coverage | Cartography labels (artifacts excluded) that map to a type of ours, over all such labels |
| Accuracy | On mapped pairs, Cartography properties (infrastructure keys excluded) whose AWS API key is a typed field of ours, over all such properties; types storing their configuration are reported separately |
| Linkage | Cartography relationships between two mapped labels (the account link excluded) that have an edge between the same two types of ours |
| Operations | Cartography's AWS read operations that appear in our manifest or readers, by normalised name |
| Security attributes | Entries of a reviewed list, each typed, configuration-only, absent, stale or not collected |
| Tags, identity, containment | Whether both read tags, whether both key on an ARN, and how account and regional containment compare |
| Ledger | Under the weighting, the share of in-scope ledger types collected, decided, or unclassified |

A relationship with an endpoint that is unmapped, a known gap or an artifact is `not-comparable` and counted
as such, so a high percentage cannot hide a narrow comparison.

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

### Mapping
----
RID: `req-aws-core-crosscheck-mapping`

Status: `Implemented`

`label_map.json` records Cartography labels that match a type of ours by a name other than the obvious one
(a list), labels that are reviewed gaps (an empty list), and labels that are sub-structures rather than
resources. A label found in none of these and not matching by name is reported as unmapped. The tests check
every alias target and every security-attribute name against this repository, so a rename here cannot leave
the mapping silently wrong.

### Report
----
RID: `req-aws-core-crosscheck-report`

Status: `Implemented`

`report.json` is sorted and carries no time. `report.md` leads with the metrics table, then the heaviest
gaps. The inputs section records both commits, the weighting and the hashes of the mapping files.

### Drift
----
RID: `req-aws-core-crosscheck-drift`

Status: `Implemented`

With a baseline, the report adds the headline figures that changed, the gaps that are new, the gaps that
closed, and which inputs changed. A change in the Cartography commit or the weighting is shown as an input
change, so a move caused by the reference is told apart from one caused by us. `--fail-on-regression` exits 1
when a gap is new.

### Reference Defects
----
RID: `req-aws-core-crosscheck-defects`

Status: `Implemented`

Static checks produce leads about Cartography itself (today: a relationship whose target label no schema
defines). A lead is not a finding. A person verifies it and records it in `cartography_findings.json` with the
commit, a summary and the evidence, and a status (`open`, `reported`, `acknowledged-upstream`,
`fixed-upstream`). A recorded finding suppresses its lead.

### Live Tie-Break
----
RID: `req-aws-core-crosscheck-live`

Status: `Proposed`

Each disagreement the static layer raises (a missing edge, an untyped attribute, an unmapped label) is checked
against a seeded live account through the oracle. The static report is the list of what to check; the live
result decides who is wrong, and a flaw in Cartography found that way is recorded as a finding.

## Open Questions

1. **Weights.** The tiers in the shipped weightings are a first judgement and need review.
2. **FedRAMP scope.** Whether the overlay should add rules beyond the types and services it names.
3. **Edges by name.** Relationships are compared by type pair only; comparing by meaning needs a reviewed
   table of edge names.
