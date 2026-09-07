# Company journal explorer

NIN-17 now has bounded canonical journal list and detail readback, mounted in Companies → Accounting after the operator validates an accepted company, ledger, book and period. It reads the existing JournalEntry, JournalLine and SourceAccountingBinding identities. It creates no accounting records and grants no posting or current-use authority.

The API preserves an explicit snapshot through pagination and detail. Each response includes exact company, ledger, book, period, chart, currency and calendar version references. The browser verifies these references against the accepted selection and remounts when any pin changes. Inspect and Trace retain the exact resource version and snapshot.

List resolution verifies the journal's company/ledger/period, the binding's ledger/book/period/currency, the book's ledger, and the source scope's company/chart. Incoherent visible candidates produce unresolved coverage rather than a complete result. A coherent different book is excluded. Reads fail without partial results above 5,000 candidate entries or the statement budget; pages contain at most 50 entries.

Detail resolves the exact manifest, lines, accounts, source records, binding, currency and source evidence. It checks posting date, period bounds, line intervals, debit/credit balance and complete manifest membership. Missing or inconsistent dependencies suppress the whole-journal balance. Current binding eligibility is a separately timed advisory; a retained balanced journal is not an ERP posting or permission to reuse amounts. Historical journals lacking the newly required posting date remain inspectable with incomplete integrity.

The company directory collapses while Accounting is selected to leave usable width for source and journal work. Choose company restores the searchable directory. Real SGP accounting remains unconfigured, so the journal explorer does not request or display fabricated rows. The existing source accounting setup remains available beside this prerequisite.

Verification: native PostgreSQL readback with isolated synthetic canonical fixtures; exact binding mismatch and incomplete-bundle checks; focused lint/typing; integrated production build; authenticated HTTP through the web proxy; browser confirmation of SGP's unconfigured state and company directory controls. The synthetic fixture temporarily bypasses financial publication validators only while constructing readback inputs, restoring them before queries. It does not prove financial publication, authentic journals, hidden-line RLS behavior, production scale or full NIN-17/NIN-25 acceptance. No financial configuration was accepted for SGP.

See `evidence/nin17-company-journal-explorer.json` for the bounded evidence and limits.
