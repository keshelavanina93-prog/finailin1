# SGP 2025 historical trial balance intake

## Product requirement

The intake workspace must treat `SGP 1.xls` through `SGP 12.xls` as one historical evidence package for SOCAR Georgia Petroleum. The workbooks contain 2025 valid-time observations, 38,137 parsed source rows, and GEL trial-balance amounts. A signed-in August 2026 operational scope may provide system context, but it must never reinterpret these workbooks as August 2026 facts.

The operator journey is **Intake → Source proof → Mapping review → Controlled unlock**. Source evidence stays separate from canonical accounting facts until account mappings are approved by the governed ontology review path.

## Required behavior

- Accept exactly one `SGP N.xls` workbook for each month 1–12. Read the 1C/BIFF `TDSheet` without losing source hashes, row numbers, outline levels, parent rows, bilingual labels, or the six amount columns: opening debit/credit, turnover debit/credit, and closing debit/credit.
- Bind each workbook to the period observed in its source header (`2025-01` through `2025-12`). Preserve the active operational period only as diagnostic context and expose a historical-scope guard.
- Show one package status with workbook count, parsed row count, source proof, mapping state, and Finance/Planning/Reporting lock state. Show the monthly hash and receipt for drill-through.
- Render each selected workbook as an indented six-column 1C hierarchy. Parent, summary, and analytical rows remain visible; the UI must not silently add overlapping rows.
- Prove opening, turnover, and closing debit/credit equality from the retained source footer and show the pair delta. Missing source-total proof is a break, not an implicit zero.
- Compare every month’s opening debit/credit with the prior month’s closing debit/credit. Show each transition and delta, including the September → October 2025 break.
- Expose account-code mapping candidates and route the operator to governed ontology review. Do not infer canonical account meaning from code text, and do not unlock downstream modules from a suggestion alone.
- Provide read-only diagnostics and NYX context that state the valid periods, active operational period, mapping state, locks, and whether the package was evaluated under active runtime time.

## API contract

- `POST /v1/hydration/trial-balance-package` validates, parses, hashes, and retains the package. Parsing and retention run off the FastAPI event loop; the current request returns the completed report and does not claim a durable job queue.
- `POST /v1/hydration/trial-balance-package/diagnostics` accepts a returned report and verifies tenant, legal entity, currency, package identity, historical isolation, equality, carryforward, and downstream locks without mutating evidence or mappings.
- `GET /v1/diagnostics/readiness` confirms that the package and diagnostic routes are registered and reports the runtime capabilities without pretending that storage was probed.
- `GET /v1/diagnostics/evidence-context?source_year=2025` supplies the historical scope facts used by the NYX panel.
- `GET /v1/workspace/constructions/{receipt_id}?period=2025-MM` reads a retained historical receipt only for an explicit 2025 month while preserving tenant, legal entity, and currency boundaries.

## Acceptance evidence for the current SGP files

- 12 BIFF workbooks, `TDSheet`, company label `სოკარ ჯორჯია პეტროლეუმი // Сокар Джорджия Петролеум`.
- 38,137 parsed source rows (worksheet headers, blanks, and footer metadata are excluded from this user-facing count).
- 12/12 monthly opening, turnover, and closing debit/credit proofs pass with zero pair deltas.
- 11/11 month-to-month carryforward transitions break; the largest is September → October (−141,547,368.59 GEL on both debit and credit). These breaks remain visible and keep the package in review rather than being hidden.
- Finance, Planning, and Reporting remain locked while mapping is `REQUIRED`.

## Follow-up required for full production completion

The current implementation removes event-loop blocking and gives deterministic package diagnostics. A restart-safe `202 Accepted` job record with durable polling is still required before claiming background-job ingestion. Mapping approval persistence and backend enforcement of downstream locks must likewise be connected to the package identity before the package can unlock financial reporting.
