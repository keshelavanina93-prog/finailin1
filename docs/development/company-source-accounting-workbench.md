# Company source accounting workbench

Companies → Accounting now opens the actual retained accounting context in the company workspace. The user chooses from that company's canonical SourceAccountingScope resources. The document, worksheet and source profile come from the selected scope; the UI never guesses them from a filename or source label. Unsupported, incomplete or mismatched company references remain visible without opening an accounting editor.

The workbench shows observed dates, existing binding eligibility and the absence of reviewed accounting use. It reuses the source accounting context API and the reviewed setup flow from `source-accounting-setup.md`. Currency, calendar and period choices remain empty until selected explicitly. Existing company identity details can collapse when accepted; unresolved identity warnings remain available. Exact source scope Inspect, Trace and History use the shared ontology navigation. Setup inspection and trace callbacks carry resource/version references to the same inspector.

Source selection is stored under the existing company-specific view key. Moving to Data and back restores the source selection; choosing another company or source remounts the context and aborts stale requests. No source accounting configuration is copied between companies. Proposal review uses Workflows & Actions.

Authenticated browser verification selected the actual SGP TDSheet source scope, read its retained 2025 date extent, opened the exact source scope inspector, restored the same company/source after Data navigation, and opened setup directly in Companies with blank currency/calendar/period choices. The current server response still reports ACCOUNTING_CONFIGURATION_REQUIRED with no ledger or source accounting binding. No proposal, financial configuration or journal was created for this navigation check.

See `evidence/nin25-company-accounting-workbench.json` and its screenshot. Focused lint/typing and the integrated production build passed. This proves the bounded company/source workbench; it does not close NIN-25's complete financial, planning, graph, map or intelligence acceptance journeys.
