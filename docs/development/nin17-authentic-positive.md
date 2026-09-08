# NIN-17 authentic positive journal

The live NIN-44 instruction `b86825c1-647d-4573-809e-a543ca9ddf34` is executed through an authentic retained SEG row. Code was pushed before this evidence: `4b1acf5`, `1cd74bb`, `93014f6`, continuing the isolated `development/nin17-governed-journal` branch from `a730cd8`.

## Published result

Base!S2 supplies literal **731.97 GEL**. Debit account **7310.02.1**, credit account **3110**. Accepted proposal `1b23895a-e339-593c-9fc8-d1c7eef7eb41` produced journal `be451fe5-4cdb-50f6-bb19-79a28fae06c6`, version `feec4daa-adc0-52af-8c31-7dd4b2e0c893`, and two exact balanced lines. Both line dimension policies resolve COMPLETE. Source family remains `seg_expense_base`; the reviewed compatibility object grants the bounded source-row interpretation without relabeling the source.

Configured maker and distinct checker principals executed the native review path. Maker approval returned 403. These are configured application review identities, not a claim of additional human accountant signoff. Four analytical members retain explicit USER_ASSERTED source-cell rationale for F2/G2 and M2/N2. They do not assert unavailable original document or subledger depth.

All 38 mapped accounts have scoped policies pinned to company/chart/book/period/source account/chart evidence. Named chart analytics are explicitly required under this review; other dimensions are prohibited. No empty-policy shortcut was used. Of the 52 incompatible amounts, 51 exceed six decimal places and also exhibit a numeric tail relative to two-decimal presentation; one is zero. This classification proves neither the cause of the tail nor rounding authority. All literals remain unchanged.

## Executed verification

- Full canonical preview -> retained maker proposal -> distinct checker APPROVED -> accepted native JournalEntry and two JournalLines.
- Fresh Python process reads the same retained attempt and journal. Same-request submission returns the same receipt without creating another journal.
- Authenticated in-process ASGI against the native retained database: attempts, retry, reconciliation, journal detail, journal projection and both account source-cell drilldowns returned 200.
- Reconciliation matches one journal, debit = credit = 731.97. Movement trial balance contains two accounts with net +731.97 and -731.97. Source coverage is PARTIAL: 594 other literal rows remain unmatched.
- The shared `semantic-analysis/2` projection exposes accepted movements and exact original source cells. S2 is 731.97; AD2 remains the distinct supplementary literal 821.66000000000008 and never supplies the journal amount.
- 94 focused tests passed; three native fixture tests skipped. Ruff and focused mypy passed. A preliminary targeted test invocation passed 16 tests but failed the repository-wide coverage threshold; the final focused invocation explicitly used `--no-cov` and is not a global coverage claim.

Finance migration 063 was applied to the native database for append-only production receipts. This is fresh-process native/API evidence, not a mounted runtime restart, browser proof, or independent NIN-50 acceptance. No product, NIN-62 ontology-import, frontend, or CI files were edited.

## Reproduction and consumption

`scripts/prepare-seg-journal-authorities.py` previews candidates by default; `--apply` publishes through configured maker/checker review. `scripts/publish-seg-positive-journal.py --apply --request-file <persistent-request.json> --output <receipt.json>` publishes only Base!S2. Use `--readback` with the same request file in a fresh process to verify retained identity, retry and reconciliation. Both scripts use the configured native environment; do not put credentials in evidence.

POST `/v1/ontology/company-journals/reconciliation/projection` accepts the existing ProjectionRequest. Keep the same `snapshot_at` query parameter and returned descriptor hash for a selected-row drilldown. The response uses the existing shared analytical model; the finance service owns accepted-journal projection without modifying the retained source-only view.

Machine-readable evidence is in `evidence/nin17-authentic-positive.json`. Base!S288 remains `MISSING_LITERAL_POSTED_AMOUNT`. Opening and closing balances, statement mappings, P&L, Balance Sheet, Cash Flow, ledger completeness and certification remain unavailable. Further rows require their own supported source analytical assignments and exact amount eligibility; this positive journal grants no blanket publication authority.
