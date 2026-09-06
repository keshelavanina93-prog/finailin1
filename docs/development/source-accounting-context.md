# Source accounting context

NIN-26 / NIN-17 now distinguish observed source context from reviewed accounting use.
SourceAccountingScope records the original company, company chart, retained worksheet,
source record, evidence identity and observed dates. SourceAccountingBinding separately
records structural-reference or accounting-input use, with explicit ledger, book,
period, currency and currency role for accounting inputs.

The original SGP TDSheet explicitly states calendar 2025. Sakorggazi TR has movements
dated 1–30 November 2025; that extent does not establish complete monthly coverage.
Both observed scopes are published through the canonical proposal/review lifecycle.
Neither source has been designated as an active accounting input. No authentic matching
ledger configuration was present; template resources are excluded from selection.

Validation applies to the shared proposal and promotion path, including proposals made
outside the source UI. Company/chart, book/ledger, period/calendar and functional
currency relationships must agree. Structural references cannot carry active accounting
fields. Configuration cannot masquerade as observed source evidence. No source dates or
currency are inferred from the authenticated user's sign-in scope.

The Data workspace inspects and proposes these resources. The source-row API exposes
the published scope and binding versions and the binding's retained canonical dependency
version pins. It preserves the original monetary observations and does not certify totals,
post journals, establish coverage or resolve overlapping financial sources. A binding
alone is not a posting or reporting authorization.

Local evidence under `.finai/artifacts/`:

- `source-accounting-scopes.json`: accepted SGP and Sakorggazi scopes and proposal IDs.
- `source-accounting-context-browser.json`: both original periods displayed in the
  rebuilt application; incomplete input selection disabled; template ledgers excluded.
- `source-accounting-context-consumption.json`: original source-row service resolves
  the accepted scopes while preserving UNSELECTED accounting use.

The build and targeted lint passed. Seven focused validation checks passed with
`pytest .../test_source_accounting_context.py -q --no-cov`. The first focused invocation
also passed those checks but failed the repository-wide coverage threshold, which is
not meaningful for a single-file run; no full-suite or coverage completion is claimed.

Still required: source-use decision and authentic company accounting configuration,
financial source coverage/overlap decisions, canonical posting and reporting integration.
SGG regulatory licence/act/rule authority and downstream regulatory delivery remain open.
