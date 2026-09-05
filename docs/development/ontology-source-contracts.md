# Source-backed ontology execution

Ontology definitions use the existing canonical identity, version, proposal,
dependency and review storage. `OntologyDefinition` is a bounded JSON semantic
type. Publication validates the typed definition and pins its dependencies.
Object Sets, interfaces and type groups execute through the shared object query
service. Paging retains definition version and bitemporal query timestamps.
Bindings propose target objects with exact source and definition version pins;
they do not directly mutate accepted objects. Derived values retain input and
definition versions and report unavailable calculations explicitly.

## Authentic 1C account configuration

`GET /v1/ontology/model/sources/{receipt}/accounts` reads integrity-checked retained
workbook bytes. Headers identify the configuration table; filenames and fixed
column positions do not determine its meaning. Codes remain text. Account names,
balance/currency/quantity/off-balance flags and subkonto labels are retained as
source designations. Duplicate codes, missing names and formulas produce findings
and block publication of affected rows.

`POST /v1/ontology/model/sources/{receipt}/accounts/proposal` prepares up to 40
source definitions per proposal. Each `SourceAccountDefinition` references a
`SourceRecord` with a workbook coordinate, which references `SourceEvidence`
identified by the original content hash. Repeating an already published range
does not create additional versions. The accepted observations do not assert
company/chart membership, posting activity, mandatory dimensions or report-line
mapping. Those remain explicit downstream binding decisions.

The actual user-provided `ანგარიშები (1).xlsx` contains 406 definitions. Its
SHA-256 is `607e37da8aa8e05687c9898cc1577db070c082ece8281c7bd3a43e725aac73df`.
Original bytes and runtime receipts remain private runtime artifacts. The app's
source inspection renders all definitions with source coordinates.

## Financial fact contracts

`FactContract` declares grain, dimensions, numeric measure, time, unit, source
family and authority basis against an exact schema version. Interactive
aggregation rejects duplicate grain, mixed source families, reference-only
inputs, incompatible schema versions, missing values and inexact arithmetic.
Currency/unit always remains a grouping key. Closing balances require one
explicit snapshot date; non-additive measures cannot be summed together.
The interactive bound is 10,000 facts, not a scale acceptance claim.

These checks do not establish that an upstream source is complete or reconciled,
nor infer whether a row is a parent subtotal or a posting-level fact. A source
contract must establish that meaning before financial use. Results are labelled
source-bound analysis and never financial certification. Corporate/operating
report mappings, VAT, costing, FX translation and consolidation remain separate
versioned business semantics, not implicit arithmetic defaults.

## Deployment and validation

Apply migrations through the explicit migration runner and install missing
platform definitions with `scripts/install-ontology-runtime.py`. Migration 024
deduplicates repeated proposal dependency read checks without changing the
tenant, field, restoration or historical-impact conditions from migration 022.
It adds no role or clearance feature.

The local runtime has verified the authentic workbook inspection and the
account-to-record-to-evidence-hash traversal through the web API proxy. Source
inspection and account exploration were also exercised in the signed-in browser.
Focused financial/source checks and the existing field-read regression passed;
the focused run does not meet the repository's global 90% coverage threshold.
This is not acceptance of the full NIN-6 platform, NIN-26, production scale or a
complete financial reporting workflow.
