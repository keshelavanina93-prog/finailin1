# NIN-25 operator contract review — 2026-09-06

Authority: the user-supplied issue list and the four current Linear binding documents, plus NIN-25. This review distinguishes the mounted operator experience from backend definitions and isolated execution paths.

## Binding sources

- [Enterprise Hydration, Authority Compiler and Operator UX](https://linear.app/g8flospace/document/finai-enterprise-hydration-authority-compiler-and-operator-ux-binding-5f3bf3638e9b)
- [Financial Reporting, Consolidation and Live Analytics](https://linear.app/g8flospace/document/finai-financial-reporting-consolidation-and-live-analytics-binding-9eaecd470784)
- [Platform Target and Transformation Contract](https://linear.app/g8flospace/document/finai-nyx-core-binding-platform-target-and-transformation-contract-e8a7b49a12ce)
- [Architecture Decision Register](https://linear.app/g8flospace/document/finai-architecture-decision-register-data-storage-transformation-and-execution-b27be7dbac26)
- [NIN-25](https://linear.app/g8flospace/issue/NIN-25/build-the-unified-g8-operator-visual-system-graph-canvases-and-command)

NIN-25 remains In Progress. Its newer contextual-scope instructions supersede older always-visible global-selector language. User instructions defer role/field-clearance feature development. Shared authentication, identity, scope, evidence and business lifecycle remain required.

## Mounted implementation gaps

| Contract | Observed implementation | Remaining delivery |
| --- | --- | --- |
| Operational graph canvases | Historical dependency API; engineering connection lists; new on-demand exact-version operator trace | Pipeline/process/impact graph family, graph editing where authorized, minimap/fit, shared investigation and governed action execution from graph |
| Persistent business context | Company selection and some map state; new scoped session navigation/trace restoration | Complete ledger/book/period/scenario/version/currency/certification propagation, server-owned saved work/investigations, cross-surface compatible-filter authority |
| Financial command workspaces | Main Finance, Planning and Reporting navigation explicitly unavailable; focused accounting views elsewhere | Native dense journal/close/report/planning workbenches over their shared financial contracts, not enabling placeholder routes |
| Executive/operational analytics | Mounted overview and maps do not establish certified MR/live operational financial truth | Governed metrics, comparisons, drivers, valid drill paths, source depth, real operational feeds and synchronized selections |
| Governed action center | Main Workflows & Actions navigation unavailable; specialized execution and review exist elsewhere | Shared business-facing intents, human waits, receipts, readback, reconciliation and outcomes |
| Intelligence | NYX panel explicitly says reasoning not connected; retained specialized assessments exist | Persistent canonical Findings/Investigations and deterministic explanations driving all surfaces |
| Full source-to-target compiler | Authentic source parsing/bindings and local execution capabilities exist | Three-mode acceptance, general generated DAGs, metadata-aware live 1C, SAP target validation/post/readback and complete construction receipts |

## Implementation continued in this change

The operator inspector can reveal an interactive dependency canvas over an exact accepted resource version. It reuses the existing historical lineage authority and never substitutes current heads when traversing stored dependency pins. The exact-root endpoint requires authentication and ontology read access; mismatched resource/version pairs cannot resolve.

The graph supports pointer pan, scroll, zoom, text filtering, schema-mechanics disclosure, keyboard node selection, relation navigation, version metadata, opening the selected historical version in the common inspector, and downloading retained original evidence where the dependency exposes its source document. It limits rendering explicitly to 200 matching nodes; underlying lineage bounds/refusals are preserved.

Company, compatible view and trace-root IDs survive module navigation and same-tab reload/sign-in in actor-and-scope-keyed session storage. No access key or business values are stored. Server authorization is re-evaluated on every read. This is browser navigation restoration, not a canonical Investigation or server-side saved-view implementation.

This does not complete NIN-25, NIN-6 or any financial/operating acceptance gate. Next dependency-ordered work must connect the remaining graph/action/workbench families and shared investigation context, while completing their real source, ontology, Function/Metric and financial authorities.

## Local browser evidence

Actual SGG 2024 filing binding `c4547714-fcb5-5a1b-b4de-908dd40da5d5`, version `5dd48c9f-3c99-5837-be5f-c360e61ffbbe`, opened a 17-version/36-edge graph. Browser verification followed the SourceCorporateObservation, opened its exact version, downloaded original retained evidence, navigated to Regulation, reloaded, signed in again, and restored the same SGG context and trace. A mismatched root/version pair returned 404. UI build, focused lint, and backend lint passed. No synthetic company, financial value or economic effect was created.

Artifacts: `.finai/artifacts/operator-trace.json`, `operator-trace.png`, `operator-trace-original.html`; fetched contract snapshot `.finai/artifacts/linear-operator-contracts.json`. Visual review confirmed the graph sits inside the existing workbench with an optional inspector. Full NIN-25 acceptance is not established.
