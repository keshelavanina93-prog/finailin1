# NIN-17 governed source-row journal candidate

Worktree `D:/FinAI/g8-governed-journal`; branch `development/nin17-governed-journal`; latest verified green base at start `0212bc4d8b7b23bd6f327c1b77e3a085d8b5d64e`. Carries reconciliation dependency `405fe54` (equivalent to `ceb8641`). Production code `729b91c` and source-record reuse fix `1918e09` were pushed before this document.

## Implemented flow

- `POST /v1/ontology/company-journals/production/preview`: recompute exact retained movement review; classify every row; compile eligible source-cell/journal bundles; run the existing canonical publication validator. The request cannot provide amounts or accounts. Each blocker names its required authority object. The bounded selection contains at most 20 rows.
- `POST /v1/ontology/company-journals/production/proposals`: retain immutable PREPARED intent, submit only eligible selected proposals through `resources.propose`, then retain SUBMITTED outcomes. Retries reopen exact stored intent, not recomputed amounts. Changed maker/request reuse is refused. Interrupted submissions resume the same canonical proposal IDs.
- `GET /v1/ontology/company-journals/production/attempts/{request_id}`: reopen scope-bound outcomes, including rejected and excluded rows. Migration `063_journal_production_attempts.sql` adds append-only, forced-RLS receipt storage. Apply only during coordinated integration.
- `POST /v1/ontology/company-journals/production/proposals/{proposal_id}/review`: delegates to the existing separate-maker/checker `resources.review`, which repeats canonical publication guards. No alternate approval bypass or ERP posting exists.
- The existing reconciliation endpoint consumes accepted exact journal bundles, provides source-matched movement trial balance and reconciliation receipt, and returns the shared source-only analytical projection with original-cell evidence.

A candidate contains one JournalEntry and exact debit/credit JournalLines, plus a SourceRecord identifying the original cell when needed. Explicit reviewed SourceRecord reuse preserves existing source-dimension provenance. Source versions are pinned in canonical proposal lineage. Side policies and assignments are supplied as exact reviewed references; no policy or dimension member is invented. Source-binding, account/chart, entity/ledger/book/period/currency, date, amount, VAT, period control, dimension, schema and balanced-bundle guards remain shared publication requirements.

## Evidence and remaining boundaries

45 focused tests pass across production, reconciliation, source review and shared movement projection. Ruff and focused mypy pass. Authentic read-only in-process HTTP preview returns 596 row outcomes: 595 BLOCKED and one EXCLUDED. The blocker counts are 595 unsupported source-journal semantics, 1190 missing reviewed side-dimension declarations, 52 incompatible exact amount contracts, and one `MISSING_LITERAL_POSTED_AMOUNT` at `Base!S288`. No amount substitution, rounding, sign reversal or VAT transformation occurs.

Migration 063 and storage were exercised in a separate temporary PostgreSQL instance: retain/reopen/retry, tenant/entity isolation, maker reuse rejection and update/delete/truncate refusal passed. That test server was stopped. No canonical database/runtime changes or native journal publication occurred. Evidence summary: `evidence/nin17-journal-production.json`.

This implements governed production mechanics but does **not** establish that any current SEG row is eligible. SEG's current reviewed profile remains `seg_expense_base`; the existing publication contract requires `1c_journal`. The current source amount precision/sign contract and reviewed dimension authority remain blockers. Source-profile substitution or implicit empty policies are not acceptable solutions.

Before acceptance, NIN-50 must verify an eligible source-supported bundle through full native maker/checker publication, changed-dependency refusal, crash/restart replay and reconciliation after publication on the exact integrated package. The positive compiled-bundle tests are synthetic; native eligible-journal publication and mounted runtime/browser acceptance remain unproven. The shared analytical projection remains source-only; it does not claim an approved journal-derived measure. Opening/closing balances, document depth, statement mappings, financial statements and certification remain unavailable.
