# Retained worksheet Functions in G8

NIN-32 continues through the existing canonical Function and Transformation contracts.
The retained XLS reader is now an allowlisted Function implementation, with source-cell
results rendered in Data saved analyses and named Build outputs. It does not introduce
a separate pipeline, output store, company identity or accounting interpretation.

## Contract

`source.retained-xls-worksheet/v1` requires a canonical `SourceEvidence` dependency,
the retained document identity and SHA-256, exact worksheet name, and a reviewed
zero-based start row and window of 1–50 rows. Invocation offsets are relative to that
window; a page crossing it is refused. The reader refuses sheets above 256 columns.
The existing ObjectSet Function definition remains valid. Its schema field becomes
optional structurally; the discriminated adapter contract still requires it for the
ObjectSet implementation and forbids it for worksheets.

Both installed adapters disclose read/query/snapshot and replay behavior, unsupported
source writes/updates/deletes, incremental/CDC/streaming, simulation and reversal,
acknowledgement/readback, and actual bounded limits. Installed Python/package/SQL
dependencies and `xlrd` are hashed/version-pinned. A changed executable package still
requires restart and normal reviewed Function publication before new execution.

The worksheet adapter verifies exact-scope document metadata and object-store bytes.
The canonical source version and original document must have existed by the requested
knowledge time. The effective timestamp remains request context: this is an immutable
retained snapshot, not a reconstruction of business facts valid at that timestamp.
Numeric/date-serial/error/text/empty cell types and original coordinates are retained.
No formulas are reconstructed, recalculated or interpreted as accounting policy.

## Shared persistence and work accounting

The existing Function invocation intent/terminal receipt and content-addressed fact
run store the result. `source_rows` contains source coordinates, never invented
canonical resource identities. `objects` and `derived_values` remain empty for this
adapter. Transformations continue through the same Temporal worker, immutable node
events and atomic complete output-set publication.

Migration 046 validates the exact canonical evidence/document/hash/window and
historical availability when retaining an invocation. Successful worksheet receipts
must retain source provenance, temporal semantics, requested query bounds and bounded
unique source rows. Existing guards still bind the result to its invocation and scope.
These are structural/provenance checks, not independent database execution of XLS.

Both Python and the SQL publication guard count the actual `source_rows` array for
this verified adapter, rather than its empty canonical-object array or a caller's
declared count. Derived evaluations remain zero. Existing measured JSONB UTF-8 result
bytes, aggregate reviewed budgets, refusal and replay accounting remain shared.

## Product surface

Data renders the source filename, worksheet, reviewed window and actual page coverage,
followed by a dense coordinate/type/value table. Source-evidence Inspect and Trace
verify the retained canonical version/hash and knowledge cutoff. The existing G8 shell
and NYX context remain in place. This does not establish NIN-25 full frontend acceptance.

## Evidence and limits

Verification on 2026-09-07:

- Focused adapter/core checks: 5 passed; native worksheet persistence plus existing
  ObjectSet invocation regression: 3 passed. Ruff and targeted mypy passed. Frontend
  lint, TypeScript and production build passed; web 3062 and API 8062 are running
  the integrated package, worker restarted, schema 46 applied.
- Function schema correction reviewed through proposal
  `07d61d19-16d0-42f1-a15f-321c4201f122`.
- Existing SourceEvidence `86271832-cbef-5593-a95b-3d326dd1d643`, version
  `0536a83e-4a2a-5823-b66b-8ae25a5b17fd`, is reused. Function
  `5412df81-d1fd-5908-a50c-a0c49700b99c`, version
  `bc378f59-a05c-5172-8ee6-f4b0f3aafd04`, and Transformation
  `5b45554d-4968-52ed-ad06-d974d6196b08`, version
  `a20d76ba-5d54-5aa6-864b-ccf31b3b1ef7`, were independently reviewed.
- Actual build `49b1d06c-2607-4e66-b39e-e375631ce003` completed two ordered
  worksheet steps with two published named outputs. Actual measured work: six
  rows, zero derived evaluations, 13,133 bytes. Repeated request and historical
  read returned identical retained records. Every retained cell also matched the
  original source preview at its exact worksheet coordinates.
- Preparation and execution evidence:
  `evidence/nin32-worksheet-runtime.preparation.json` and
  `evidence/nin32-worksheet-runtime.json`; reproducible via
  `scripts/verify-worksheet-function-runtime.py` (`--prepare`, default, `--replay`,
  `--read-only`). Existing source-account Function/build pins were also refreshed
  through normal independent review for the changed package.
- Authenticated browser: Data → Builds → retained SGP build → named worksheet
  output showed the actual Georgian/Russian company title at `TDSheet!C1`, typed
  cells, 3/5,542 source rows, and reviewed window 1–6. Inspect opened the exact
  SourceEvidence in NYX; Trace opened its retained connection at the same cutoff.
  Captured and visually inspected under `.finai/artifacts/browser-shots/`:
  `g8-worksheet-build-completed.png`, `g8-retained-worksheet-cells.png`,
  `g8-worksheet-source-inspector.png`, `g8-worksheet-source-trace.png`.
- Browser verification initially used the CLI's default temporary screenshot
  directory on C:. That single screenshot was moved to D:, and the verification
  browser was restarted with explicit D: profile/download/screenshot paths before
  acceptance captures. This is not evidence of a fully enforced D:-only browser
  launcher across all entry points.

The fixture-based native persistence test is not proof of parsing an authentic workbook.
The mounted-source proof separately uses the already retained SGP.xls, SHA-256
`74e6f0d96943c48280854d8e437a9a78565c7796656ba07efe640ce398e381f8`,
and its existing canonical SourceEvidence. It establishes source-cell execution only.

Both adapters are read-only. This does not satisfy NIN-32's required materially
different source-write guarantees, external nontransactional delivery, SBOM/release
acceptance, tenant-wide quotas, streaming, incremental state or general transform
data ports. It does not activate a ledger, chart, currency, journal or financial report.
