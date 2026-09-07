# Bounded parallel Function execution

A reviewed Transformation's `execution_policy.max_concurrent_nodes` declares its concurrency bound. Independent ready nodes can execute concurrently; a dependent node waits for every declared predecessor. Existing Function authority, exact retained inputs, run budgets and evidence publication remain shared contracts. Completion dependencies do not silently transfer data: `input_binding` names the one upstream receipt consumed by the dependent Function.

The authentic proof uses the unchanged SOG Budget Article New CompanyDimension `2cc5e885-54f5-5b58-9359-29fd06bf8eac` and its original SourceRecord `434c6e5a-85dc-5d06-b724-31020771254e`. Two independent nodes read the original classification context and source record respectively. A third node depends on both and consumes the exact budget-context receipt. The reviewed concurrency bound is two. This build has no binding-review effect and does not change the dimension, classification context or source record.

`scripts/verify-parallel-transformation-runtime.py` supports definition preparation, start, adoption of a browser request, and readback. It checks three exact retained Function receipts, original source versions, the dependent input receipt, one evidence publication and unchanged replay. It also compares persisted node start/completion timestamps. Two completed nodes alone never establish parallel overlap: the evidence is marked `BUILD_VERIFIED_OVERLAP_UNPROVEN` unless actual execution intervals overlap. No artificial sleep, synthetic source workload or private alternate runtime is introduced to force that result.

## Verified authentic execution

[Runtime evidence](evidence/nin12-parallel-transformation-runtime.json) records actual overlap for browser-started request `39972057-1ccc-4928-b7a0-5557fe9057a0`, using Transformation `aae791cb-4157-50c4-8798-3adcca744389` / `9f97167c-bcb9-52ac-a89f-a0755db92b68`. The two persisted root intervals on 2026-09-07 were `12:54:18.666668–12:54:20.196364 UTC` and `12:54:18.670852–12:54:20.218579 UTC`. The dependent node started at `12:54:20.671127 UTC`, after both predecessors completed.

These are overlapping retained execution intervals, not a measurement of simultaneous CPU work. The actual source workload had no forced delay. One publication retained three output references, and the dependent Function consumed the exact upstream budget-context receipt. Readback before and after a separate API/worker restart preserved the output and receipt evidence, including the same observed intervals. This establishes completed-run persistence; it does not claim a mid-computation crash test.

The [browser evidence](evidence/nin12-parallel-transformation-browser.json) and [completed build capture](evidence/nin12-parallel-transformation-completed.png) record the mounted result. Focused validation passed: four workflow cases; two native concurrent-budget/legacy-binding cases in 31.58 seconds; and two pure/native SQL review-policy cases in 7.57 seconds. Targeted mypy across four modules, Ruff, frontend lint/TypeScript and the production build also passed.

## Acceptance limits

 The declared budget bounds returned rows, derived evaluations and measured published-result bytes; it is not a database scan, memory or processor quota. This bounded capability does not establish arbitrary external adapter concurrency safety, full NIN-12/NIN-29/NIN-32 acceptance, financial authority or release acceptance.

The initial Region/Department proof preparation encountered current-authority refusal after their prior reviewed display updates. Its prepared artifact and explicit failure are preserved in [blocked preparation history](evidence/nin12-parallel-blocked-history.json). The replacement reviewed build uses identity key `sog-source-contexts:parallel-function-build:v2`; no source version was refreshed and no authority check was weakened. Historical-lineage current-use semantics remain a separate investigation.
