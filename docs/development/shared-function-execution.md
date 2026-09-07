# Shared Function execution — first real adapter

NIN-47 now implements a canonical FunctionDefinition over an existing reviewed ObjectSetDefinition and optional DerivedProperty versions. The first allowlisted implementation is `ontology.object-set-derived/v1`; it executes the existing query and deterministic expression engine. It does not create private company, account, metric, object or output identities and accepts no caller-supplied executable code.

The implementation manifest binds normalized source code, the installed Python application package, SQL migrations and declared runtime package versions. It captures the identity at process/module startup and refuses changed or missing on-disk package content until restart; it cannot advertise freshly edited files as the code already loaded in memory. A changed manifest requires reviewed Function republishing. This deliberately conservative initial package identity does not claim upgrade compatibility or production packaging acceptance.

## Invocation and authority contract

The caller supplies an exact Function version, request UUID, timezone-aware effective and knowledge timestamps, and bounded page coordinates. A future knowledge cutoff is rejected. ExactScope remains authorization context; its period/currency are not silently reused as calculation time or accounting applicability.

Current Function/static dependencies are validated through existing effective-version, availability and upstream-authority helpers. Dynamic source objects are selected at the explicit historical cutoffs. Their exact versions and historical material states are retained; absent lifecycle establishment is recorded as UNESTABLISHED. Registry review never becomes AUTHORITATIVE or CERTIFIED by implication.

An immutable invocation intent commits before computation. A request-specific session lock serializes attempts without holding the canonical mutation lock across other database connections. Changed request or actor identity conflicts. Interruption leaves INTENT_RETAINED; reopening returns the frozen request for explicit resumption. Completed success/failure is terminal and repeats return the original receipt. Errors retain bounded failure codes, not exception messages containing source text or credentials.

Successful output uses the existing content-addressed `fcr_` calculation store. The terminal receipt references it and validates scope, Function, plan and implementation identity. A crash can leave an unreferenced output before terminal receipt; that is not reported as invocation success. SQL guards validate canonical identity and evidence consistency, not arithmetic execution itself.

Outputs are QUERY_PAGE_ONLY and EVIDENCE_ANALYSIS_ONLY, with current_use_authorized=false and business_effect_authorized=false. No journal, Metric, business effect or financial authority is generated. General Function/Metric/transformation integration remains open under NIN-47/48/12; this first adapter is not full NIN-47 acceptance.

## G8 Data integration

Saved analyses is a real Data workbench using canonical Function definitions, captured time context, run/retry/resume, retained-result reopening and bounded result tables. Exact source-object inspection and evidence trace use the retained input version and knowledge time. The current company is navigation context; applicability comes from the reviewed ObjectSet, not an inferred ledger/company assignment. No placeholder Finance screen is added and NIN-25 remains open.

## Evidence

- FunctionDefinition schema installed through reviewed proposal `de1797ca-ab5a-4d0a-bd07-75b5aac1d7f5`; migration042 applied and readiness requires42.
- Three focused core cases verify real canonical query execution, deterministic repeated result, exact input state, tampered plan, mismatched installed-code refusal and startup-versus-disk drift refusal.
- Two native persistence cases verify Function → ObjectSet → fcr output, terminal replay/history, scoped denial, forged dependency refusal, committed-intent interruption/recovery and sanitized terminal failure.
- New Python modules pass focused Ruff/mypy; frontend lint/TypeScript and production build pass.
- Actual reviewed Source account labels Function `2bd9dc83-249b-5d61-93e3-80d2bd1cd473` / version `f71e7348-e177-5055-becd-ff5b0e20d264` uses the retained accounts ObjectSet and derived label property. `scripts/verify-shared-function-runtime.py` executed five actual source objects/derived values through the authenticated web proxy, with identical repeated and historical receipts. Evidence is `evidence/nin47-shared-function-runtime.json`.
- Actual invocation `e354d7cb-d5aa-4733-81b3-19c8cd954e5b`, receipt hash `8b2e6a43bc28f73f8cb9c99bdc368f88aaad4a1e97b91af8feacc52ffdf10d4b`, output `fcr_e8fb07102e338f4f50e601840f150eacf5cacec47ba3e72730dc08997c6097a8`.
- After another managed API restart, `--replay` reopened and repeated that exact invocation with identical receipt/output. This verifies API-process restart readback, not a PostgreSQL restart or full disaster recovery.
- Authenticated Data → Saved analyses → Source account labels executed a 50-row page from 406 actual source definitions. Derived labels were AVAILABLE; Inspect opened exact source account000 at the same 04:20:15 cutoff. Browser invocation `af3309c6-7649-4a3e-8391-66b9ff37176f`, receipt hash `9d4d0de2dfb70090a55247cb455afe46c91fbad02cf2843bbb3e5dc88f1047bf`, output `fcr_5d7e02451555cb379db464bc295fd4cbb5ac6d4dcd616acc90865d36cd74879c`. Screenshot `.finai/artifacts/browser-shots/g8-saved-source-account-analysis.png` was captured/viewed; browser closed.
- Visual inspection found horizontal clipping after Inspect. The new workbench table now uses explicit column widths, wrapped values and static row headers; after rebuilding, the same retained invocation reopened with source identifier, derived value and actions visible together (clientWidth=scrollWidth=622). Screenshot `.finai/artifacts/browser-shots/g8-saved-analysis-readable.png` captured/viewed. No new analysis was executed for this check.
- After the startup-identity repair, API restarted and the actual Function was republished through normal review. A new five-object invocation/repeat/history passed (`evidence/nin47-shared-function-startup-runtime.json`), while replay of the original completed invocation remained identical despite the newer Function/code version. The original browser evidence is historical evidence for its exact version, not a claim of a new-version browser run.

These checks use the integrated local workspace with preserved unrelated changes. They do not establish full-product, authentic accounting, deployment, scale or release acceptance.
