# Reviewed aggregate build work limits

NIN-32 extends the real NIN-12/NIN-47 execution path with aggregate admission and publication limits. It reuses canonical Transformation versions, immutable Function results, workflow events and the existing atomic publication manifest.

## Contract

Every newly used Transformation definition requires a reviewed `resource_budget`: `max_returned_rows` (1–6400), `max_derived_evaluations` (0–51200), and `max_published_result_bytes` (1–16000000). These are technical work limits, not accounting or business materiality rules. The schema extension is structurally optional for historical compatibility; new execution requires a reviewed budget.

The compiler checks each node against its actual Function adapter manifest and sums declared page bounds and property evaluations before retaining or submitting a run. Accepted limits and `estimated_work` are frozen in the existing compiled plan. Output size cannot be known from page limits alone and is checked against actual results.

Each successful Function result is measured directly from its immutable `fcr_` payload. Returned rows count the result's objects; derived evaluations count all returned evaluation records, including unavailable results. Byte accounting is explicitly `POSTGRES_JSONB_TEXT_UTF8_V1`: `octet_length(convert_to(payload::text,'UTF8'))`. This measures the full retained result's JSONB text representation, not source file size, physical storage, delivered file bytes, memory or database scanning.

Usage is counted once per stable node, including completed intermediate nodes. Replayed nodes do not consume a second allowance. A result exceeding the cumulative limit creates an immutable `BUDGET_REFUSED` event, stops subsequent steps and prevents complete publication. Its existing Function/fcr diagnostic evidence may already be retained; this is a publication work budget, not a hard storage quota. Historical budgetless runs retain their original evidence and semantics, but new runs cannot omit the reviewed contract.

Migration045 independently checks canonical budget/estimates, exact Function result measurements, cumulative accounting and publication limits. Advisory transaction locks serialize aggregate usage validation per run. This is not tenant-wide admission or concurrency control.

## Product behavior

G8 Data Builds displays reviewed limits, planned work, retained per-step usage and a clear work-limit refusal. The refusal remains visible in historical evidence independently of live Temporal availability. The operator can inspect a diagnostic result, but the interface does not call it a published build output. Build history separately counts work-limit refusals.

## Verification

- Migration045 applied; readiness requires45. Optional schema extension reviewed in proposal `01f3dbbb-fd62-4206-83b4-281262753855`.
- Ten focused compiler/domain cases passed, including native exact-plan compilation and aggregate admission rejection. Two native runtime cases passed successful accounting/replay, forged zero-byte usage rejection, actual one-byte refusal, no staging/publication on refusal, and existing failure/history boundaries. Ruff and targeted mypy passed. One concurrent shared mypy-cache invocation failed internally; an isolated D:-resident cache passed. Frontend lint/types and production build passed.
- After API/worker restart and normal Function review, source build `b80d49ff-d220-54d2-8923-cb97403eeb02` / `bf27d2d6-448b-59ff-b4b7-81566946e2bf` was reviewed with 6 rows, 6 evaluations and 1,000,000 bytes (proposal `dec30d9a-cb48-4d53-8061-2b0ba205b261`). Actual run `fe6025e9-29e5-4a03-83d8-a79d9d9e3052` completed both steps: 6 returned rows, 6 evaluations and 20,780 represented result bytes. Both outputs published; repeat/readback remained unchanged. See `evidence/nin32-build-budget-runtime.json`.
- Separately labeled verification definition `83a147a7-32a8-58af-a1e5-d74a222842e3` deliberately allowed only one byte. Actual run `bc1cbc0a-e5ee-4e00-867b-c6693b8b7ad5` retained three source observations/evaluations and 10,444 represented bytes, then recorded `BUDGET_REFUSED`; the second step did not start and no output set published. Its diagnostic invocation is `0b9c8e2f-991f-5b1e-b083-9be39df34dac`, receipt `0dc9673ddb34b5db14a0808aed8cc8306d81f2070646ad483f220be65bf667a2`. See `evidence/nin32-build-budget-refusal.json` and `scripts/verify-transformation-budget.py`.
- Authenticated browser history opened that exact refusal and displayed reviewed 1 byte versus retained 10,444 bytes, zero published sets and the review-definition/new-run next step. Screenshots `.finai/artifacts/browser-shots/g8-build-work-limit-refused.png` and `g8-build-work-limit-usage.png` were captured and viewed.
- After verification, the deliberately restrictive definition was made unavailable for new use through reviewed lifecycle state. It is excluded from the current build catalog; its run/diagnostic history remains unchanged and passed read-only reopening. The normal source build remains available. See `evidence/nin32-proof-definition-withdrawal.json`.

These local checks do not complete NIN-32, NIN-12, NIN-47 or NIN-25. A second materially different adapter, tenant admission/backpressure, incremental/streaming execution, runtime-image/SBOM provenance and broader resource governance remain open. No financial authority, full product, scale or release acceptance is established.
