# Typed Object Set ranges — NIN-6

This capability extends the shared ontology query used by saved Object Sets, derived properties and retained Functions. It does not introduce a separate financial query engine or convert source observations into approved ledger facts.

## Implemented contract

Property filters preserve equality by default and add `lt`, `lte`, `gt` and `gte` operators. An omitted equality operator retains the historical wire shape. Ordered comparisons require schema-declared integer, decimal, date or timezone-aware datetime properties. Decimal operands remain exact strings; source text, booleans and missing values must not acquire ordered numeric meaning. Multiple filters are combined with AND, allowing half-open date windows and independent source-family constraints.

The query must preserve the existing single database snapshot for count, page, traversal and filter-schema evidence. Comparisons must respect the object's exact schema version as well as the query's as-of schema contract, so a later type change cannot reinterpret earlier source text. Saved definitions use the existing canonical review and dependency pins. Function invocations retain the same saved query and exact result provenance.

## Authentic acceptance target

Use retained SOG procurement `SourceJournalMovement` observations from source family `1c_journal:45011b3a149ecfd09a21c7d90c6119830fac1f04352a089c5c5fbe28e3691e1d:TR`, SourceEvidence `71f45f39-35fb-56c1-b4b7-61e7edc56368`. Verify an explicit `[2025-11-03, 2025-11-04)` posting-date window against its lower and upper boundary records, save/review the canonical Object Set, execute it through a retained Function and inspect it in G8. These source observations retain their existing unestablished currency/unit authority; no financial sum is implied.

## Local acceptance evidence

The actual window returned two observations, `TR!row:5` and `TR!row:6`. Six observations on November 4 were excluded. Their canonical object versions, source-bound status and exact `FIELD:evidence_id` dependency pins were checked; each pinned SourceEvidence version retained the original workbook hash.

Saved Object Set `72f56d81-f99f-5ccd-a5b8-64af9d284409` / version `762cd946-e0f7-53f5-b551-86826a695210` was published through independent canonical review. Function `426db425-5f66-504c-bb46-3310770444fc` / version `9925bd01-fc6a-5556-bd04-dc7420438fcb` returned the same objects. Invocation `38862fdc-65da-4f5b-a0b0-685057bdee66`, receipt `114915ddb8ffc74e7ef31814036b1e8b2ea455e68cf5cffae04f458755a23082`, retained run `fcr_920c17eeab8d4fd711ad2f2413fc6b9dc92624c84f1afd2c6f2f92ab52287822` replayed unchanged.

G8 opened the published definition with all three filters, returned the same two objects, preserved the filters and original query time across Companies → Ontology navigation, and executed the editable multi-filter form successfully. The new range controls use the replacement shell's dark surfaces and restrained focus colors. These are real query interactions, not NIN-25 shell acceptance.

Focused native checks covered exact decimal ordering, integer boundaries, half-open dates, timezone equivalence, missing values, scope isolation, rejected schema reinterpretation and existing historical/saved filter behavior. Ruff, targeted mypy, frontend lint/TypeScript and production build passed. Evidence: `evidence/nin6-object-set-range-runtime.json`; helper: `scripts/verify-object-set-range-runtime.py`.

No financial aggregation or journal posting was performed. NIN-6, the complete Function/Metric platform and NIN-25 remain open.
