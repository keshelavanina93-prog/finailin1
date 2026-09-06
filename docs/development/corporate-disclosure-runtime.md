# Retained corporate disclosures and canonical company bindings

Implemented 6 September 2026 under NIN-26 / NIN-6.

Original Reportal group HTML is retained in the existing document/object-store path.
The parser reads only its recognized group table. SourceCorporateObservation keeps
the exact row, source coordinate, document identity and evidence hash. Blank participation
stays unknown; former-subsidiary text, identifiers and reported country are preserved.

CorporateDisclosureBinding is reviewed configuration connecting that observation to
the same LegalEntity identities used by accounting. Reporting company/code/year and
retrieval URL are explicit context, not facts inferred from the HTML fragment.
Its typed references participate in shared version dependencies and Object Set traversal.
Conflicting known registration codes, self-relations and template companies are rejected.
Missing related companies can be proposed from the selected source row; existing matching
identifiers require explicit selection. Publication uses ordinary proposals and review.

The source document UI exposes corporate inspection, source-party selection, reporting
context and proposal submission. Batches contain at most 24 selected rows; unselected
rows remain unpublished. Existing bindings can be revised through versioned review.

Endpoints under `/v1/ontology/source-documents/{document_id}/corporate`:
- POST `inspect`: retained rows, accepted bindings and available canonical companies.
- POST `proposal`: reporter_id, reporter_code, reporting_year, rationale, bindings.
  The bindings object maps source row numbers to existing company UUIDs or null for
  explicit creation from that row. The web proxy exposes the same operations.

## Authentic local publication

Four retained 2024 disclosures now have 28 accepted source bindings:
- SGP: all five rows (reported parent and four subsidiaries), reusing its original
  trial-balance company identity dc706c30-a8fb-57dc-b098-8a6bf2c2309d.
- SEG: one selected row establishing the reported SGG group relationship; 29 rows
  deliberately remain unpublished by this run.
- SGG: all 21 rows (reported parent, Telavgas and 19 regional companies).
- Sakorggazi: one reported parent row, reusing its procurement-source identity
  c6f87828-9609-5b35-afa6-e894a0acfe41 and connecting the disclosure to Alphard.

Receipts and original document hashes: `.finai/artifacts/corporate-disclosure-publication.json`.
No terminal ownership, operating asset or licence was inferred or activated.
No SubsidiaryRelationship ownership authority or financial consolidation was created.
The resources record what was disclosed and how its parties were matched.

## Evidence and remaining acceptance

Focused parser/identity invariants pass; web typecheck, targeted lint and production
build pass. After API restart, all four sources returned HTTP 200 through the web
proxy with their retained publication counts. The authenticated Object Sets browser
returned all 28 CorporateDisclosureBinding objects. The newly built authoring form
still needs verification in a browser loaded with the new client bundle; the existing
browser retained its earlier authenticated bundle.

This is not completion of the ontology or regulatory plan. Operating-group membership,
current effective legal ownership, asset/operator relationships and sourced licence /
regulatory obligations remain separate acceptance work. Financial processing still
requires explicit accounting context, fact-grain/overlap rules and measure-specific
aggregation; these disclosure percentages are not financial aggregation weights.
