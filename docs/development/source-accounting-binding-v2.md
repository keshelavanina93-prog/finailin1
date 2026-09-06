# Source accounting interpretation and guarded use

NIN-26 / NIN-27 / NIN-28 / NIN-35 implementation. Existing canonical
`SourceAccountingScope` and `SourceAccountingBinding` remain the authority; there
is no separate accounting-context registry.

An accounting input now requires a reviewed version 2 interpretation: ledger,
book, fiscal period, source amount currency and role, functional currency,
explicit transaction/reporting currency policy, account and dimension mapping
version references, source grain, deepest valid drill, and amount field/meaning.
`REVIEW_CANDIDATE` retains unresolved meaning and cannot authorize accounting use.
Source dates remain distinct from the user's sign-in scope. Effective and
knowledge time remain the canonical resource's versioned temporal fields.

Guarded calculation resolves immutable accounting ancestry and requires the
matching binding as an exact direct consumer dependency. Existing lifecycle
consumption then checks current pins, authority, availability and upstream
withdrawal. Canonical journal publication checks company, ledger, period,
account chart, source evidence and currency against the binding. Custom derived
types are checked after all proposed dependencies resolve, including references
through co-proposed intermediates. A co-proposed binding is not already accepted
accounting authority. Raw source observations remain distinguishable from
canonical accounting outputs.

The retained-source reader accepts original document IDs and construction
receipt IDs through existing scope and integrity checks. It does not copy the
source registry. `seg_expense_base` reads the original OOXML cells, decimal text,
formulas/caches, multilingual labels, recorder lines and coordinates. It does
not choose between source and report-annotated amount columns.

The review controls are mounted in the replacement G8 Data workspace and NYX
source explorer. Sheet and parser profile are explicit user choices. Review
uses the existing proposal/decision/impact flow. This is code and build evidence,
not authenticated browser or visual acceptance.

## Retained authentic source evidence

`scripts/verify-accounting-context.py` exercised the authenticated FastAPI path
against native PostgreSQL and retained MinIO bytes on 2026-09-06. Inspection
returned 200; unresolved activation returned 409. Evidence is retained locally
at `.finai/artifacts/source-accounting-context-v2.json`.

- Original receipt: `ir_e630518b23cd9855216cf776fa87e51a5b3d964a912ebc480f47e910b6a073e6`.
- Workbook: `Report- January 2025.xlsx`, sheet `Base`, SHA-256
  `d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a`.
- 596 rows, source dates 2025-01-01 through 2025-01-31; source company is SEG.
- Existing SEG identity: `365aa5d9-c2ec-52e1-867a-50fe3415f486`, established from a
  separate retained corporate disclosure. The source label requires an explicit
  reviewed binding; no duplicate company was created.
- No accepted source chart for that scope, ledger/book, currency-role or amount
  interpretation was manufactured. Therefore no authentic accounting aggregate,
  journal posting, certification or January 2026 reconstruction was performed.

The additive platform schema upgrade was published through shared review
`3cdd30d4-e950-4509-9fc1-736b9db5dcaf`; prior schema/resource versions remain.
Reproduce with `scripts/upgrade-accounting-binding.py` (idempotent).

## Verification boundaries

Focused tests cover incomplete and contradictory context, review candidates,
source precision and scope, journal compatibility, derived accounting lineage,
and missing/incompatible binding denial. Positive accounting interpretations in
unit tests are explicitly synthetic; the retained SEG source remains unresolved.
The existing PostgreSQL guarded-run regression covers generic calculation
persistence/lifecycle compatibility. The isolated production web build passed.

`AUTHENTIC_SOURCE_READ` does not mean `AUTHENTIC_ACCOUNTING_CALCULATION`,
`FINANCIAL_CERTIFICATION`, `BROWSER_ACCEPTED`, or release acceptance.
