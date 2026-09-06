# Original source and company intake

Original document retention is independent of accounting interpretation. The existing
single-sheet trial balance adapter could not accept the 24,794,624-byte SOG procurement
workbook. Migration 026 and `/v1/ontology/source-documents` retain up to 32 MB unchanged,
with exact source scope, immutable metadata and verified object-store bytes. Existing
tabular ingest limits and approval eligibility are unchanged.

Data now provides retained-document inventory, worksheet listing, paginated original
cells, hash-verified download, company inspection and a review proposal. Numeric,
empty, date-serial and error cells remain distinguishable in the preview API. Formula
reconstruction and financial classification are not claimed. Company directory queries
are paginated independently of the capped ontology graph.

Two explicit company readers are available: a recognized company column in XLS, and
the C1 company title in a recognized 1C trial balance whose C2 identifies the report.
Publication creates source-bound canonical company observations and exact source-cell
lineage through the existing independent-review lifecycle. It does not establish legal
registration, corporate ownership, chart applicability, functional currency or licences.
Different source identities still require governed identity resolution; names are not
automatically merged across files.

## Authentic local publication

| Source | SHA-256 | Accepted proposal |
| --- | --- | --- |
| SGP.xls, 1,814,528 bytes | 74e6f0d96943c48280854d8e437a9a78565c7796656ba07efe640ce398e381f8 | 7e581ef7-8af9-4663-b3a1-1d39d4f38909 |
| Procurement SOG _Nov - Copy (2) (1) - Copy.xls, 24,794,624 bytes | 45011b3a149ecfd09a21c7d90c6119830fac1f04352a089c5c5fbe28e3691e1d | 5e4c2458-07c7-4f46-ac78-dc6fb46c10cd |

SGP's title is at `TDSheet!C1`; the annual TB has 5,542 worksheet rows.
SOG's company is Sakorggazi, observed in 246 cells beginning at `TR!J3`.
It is not relabelled as SOCAR Georgia Gas parent or SOCAR Georgia Petroleum.
The `TR` sheet contains November 2025 records, while `Data SOG` contains May 2025
records and has 33,677 worksheet rows. These cannot become one November fact set.

The running Next proxy and API were exercised with both original files: idempotent
binary upload, inventory, hash-identical original retrieval, company inspection and
coordinate-preserving previews. Selecting the account column as company evidence
returned 422. The canonical company endpoint returns both accepted identities.
Local evidence is in `.finai/artifacts/source-document-http-verification.json` and
the two `*-company-publication.json` files. This is HTTP integration evidence; the
already-open browser still held an older application bundle during inspection.

## Accounting continuation, still required

NIN-26/6/17/18 remain open. Source retention and company observations are prerequisites,
not completion of the financial ontology. Continue with authentic account-usage and
chart applicability bindings against the retained 1C account definitions, then publish
fact representations at explicit journal, balance, analytical and control grains.
Preserve debit/credit, movement/balance, period and company boundaries. Reconcile
overlapping representations rather than adding them. Map each measure to its own
aggregation contract; do not turn source preview rows into financial totals.

SGG licence/act applicability and regulatory reporting also remain open. Procurement
rows provide neither licence evidence nor physical gas-meter measurements.
