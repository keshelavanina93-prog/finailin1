# Retained calculated inputs in shared Functions

This implementation connects a declared downstream calculation to a successful upstream Function's retained calculated output. Both steps use the existing canonical DerivedProperty identities and exact versions. A reviewed Function declares `retained_properties`; a Transformation's existing `input_binding` supplies the upstream invocation receipt.

Only declared top-level upstream calculated outputs are input ports. An internal dependency value does not become an implicit port. The consumer requires the exact property version, original object version, result kind and retained receipt. Missing or mismatched values fail closed instead of triggering recomputation. The consumed value records `source_result` with invocation ID, receipt hash and retained run ID; its empty `source_fields` indicates that the source expression was not re-read at that step.

## Authentic source verification

`scripts/verify-retained-calculation-runtime.py` prepares a separately reviewed two-step build over the existing SourceAccountDefinition `00c93da8-3ab9-5597-aaf6-ea79b7307d32`. The first step concatenates its observed account code and source name. The second consumes that exact retained property value and adds the literal ` | retained`. This is source-label processing, not accounting or financial authority.

The helper supports `--prepare`, execution, `--correct`, `--replay` and `--read-only`. Preparation waits for the API package to settle so the reviewed Function implementation identity matches the running code. Correction publishes a new version of the separately named source-label property only after the original workflow completes, then directly evaluates the corrected property to prove the changed value and reads the unchanged original retained proof. Replay after a coordinated restart must preserve workflow outputs, original objects, calculated values and receipt references. No claim of mid-step crash recovery follows from completed-run replay.

Receipt-backed HTTP output establishes exact value and provenance continuity. The claim that configured retained inputs are not recomputed additionally requires the focused backend evaluator test; the HTTP projection alone cannot establish absence of evaluation.

## Verified execution and retained history

[Runtime evidence](evidence/nin47-retained-calculation-runtime.json) records `CORRECTION_REPLAY_VERIFIED` and `replayed_existing_receipts: true`. The actual two-step Temporal workflow `transformation:3b560725-39ca-4414-95ef-667e3b225db5` executed and published one result using Transformation `c4faddce-c1bf-5b95-9302-605a0421b36d` / `2e8dbb4e-7f13-505d-b240-4c6f78376b69`.

The original source-label property `e9c0273b-9d2a-5de8-800f-c1d503974872` / `a494ad3c-7fdd-5228-b6fc-277bf2474242` produced the observed account `3212` label. The consumer bound upstream invocation `a1cf5861-0cf5-55e1-a2af-5b9cbb0556e9`, receipt `e41f6e9fd6523921a26c46d1eb225cd1deb1d89335f9ac1ff3e5e8ee6dd5fff6`, and run `fcr_b109f2e8de70dfc084f0e9b315baf2c0a6b3f42a429d571ccffb369248a7b486`. Original source object/version and query timestamps remained identical across steps.

A subsequent independently reviewed label version `8764d534-ee1f-5a7a-9cdb-2bf80b27a5b9` added a colon. Its direct calculation and exact run readback demonstrated the changed value, while the completed workflow retained its original value and receipts. After a separate API and worker restart, replay returned the same retained workflow proof. The earlier actual workflow establishes execution; the worker restart establishes liveness and completed-result persistence, not mid-step recovery.

[Browser evidence](evidence/nin47-retained-calculation-browser.json) and the [inspected capture](evidence/nin47-retained-calculation.png) cover Workflows & Actions → retained build in Data → downstream analysis. The retained account label was marked **Evaluated from retained input**, with exact upstream provenance. Reopening after restart preserved the consumed-value, calculation and invocation text without alerts.

## Focused validation and acceptance boundary

Fifteen focused cases passed: eleven new unit cases, one native two-step chain case, one native SQL forgery case, and two legacy retained-input regression cases. The legacy cases preserve omitted-input serialization, retained-page replay and scope behavior under migration 055. The native evaluator case checks that the retained calculation is consumed without recomputation. Migration 055 rejects forged schema provenance and missing or changed consumed-value matrices even when callers supply matching payload hashes. Scoped Ruff, targeted mypy across four modules, frontend lint/TypeScript and the final production build also passed.

These results establish the bounded shared calculated-output consumption capability and its mounted inspection path. They do not close NIN-47 as a whole, NIN-25 product acceptance, release acceptance, financial authority, or general crash-recovery requirements.
