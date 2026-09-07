# Durable publication review — NIN-29

A reviewed Transformation can declare a publication-review question. Completed Function results remain retained while its workflow waits for an independent decision. The task pins the exact named outputs, invocation receipts and calculation identities; approving the task permits execution-output publication only. It does not promote accounting facts or authorize an external business effect.

The shared workflow request and immutable events own the task and decision. The task identity derives from the same run request and the publication gate. A notification only wakes Temporal: the worker reads the retained decision before proceeding. It also periodically rechecks retained state, so a lost notification does not lose the decision. Workflow history patching preserves existing ungated runs.

Migration 049 requires the declared question, all completed nodes and exact output references. It serializes decisions, cancellation and publication per run. The decision must come from an independently authenticated reviewer with the existing review permission. Same-decision retries return the recorded decision after publication; a different decision cannot overwrite it. Cancellation recorded before publication blocks it. A new publication rechecks the reviewer's current grant; historical publication readback is separate.

Workflows & Actions displays retained review state from a bounded, exact-scope event projection. The existing build inspector presents the question, output inspection and approval/rejection controls, with retained decision identity for retry. No fabricated task counts or financial approval labels are introduced.

## Reviewer readback correction

The first integration candidate exposed an existing mismatch: calculation evidence required every maker permission, including ingestion, for readback. A same-scope independent reviewer without ingestion received HTTP 404. That pending candidate was cancelled and retained as diagnostic evidence in `evidence/nin29-review-before-read-fix.json`.

New `shared-functions/1` results now record read capabilities under `SHARED_FUNCTION_READ_CAPABILITIES_V1`. Scope, restricted-read requirements and recursive canonical-version visibility checks remain enforced. Historical payloads and other calculation runtimes are unchanged. No ingestion or other operational permission is granted to reviewers.

## Verification

Five native gate/regression cases passed, including approve/reject/cancel, maker refusal, forged session rejection and post-publication decision replay. Two additional native checks passed for reviewer readback without ingestion, restricted access, wrong scope and canonical field-policy enforcement. Frontend lint/TypeScript and the production build passed. Targeted gate-module typing passed; checking the existing fact-run reader also reports its pre-existing nullable `fetchone` indexing warning, outside the new permission-recording block.

Actual source-account build `d60106cc-c121-4cc7-a201-7062d0a51087` retained task `b96bb91e-f860-53ff-b831-d37b8400d28d` while the API, Temporal server and worker were stopped and restarted. Readback after restart returned the same task and exact output references, with no publication. The local reviewer opened this pending item in Workflows & Actions, followed it into Data Builds, inspected the downstream retained account objects (000, 0007, 0008 and their original Georgian/Russian labels), and approved publication through the browser. The worker reached COMPLETED with one publication. Replaying the exact recorded decision returned the same decision and output evidence. A separate run reached REJECTED with no publication.

Retained API evidence: `evidence/nin29-publication-review-runtime.json` and `evidence/nin29-publication-review-rejected.json`. Browser evidence, visually inspected: `.finai/browser-verification/screenshots/g8-publication-review-approved.png` and `.finai/browser-verification/screenshots/g8-publication-review-source-values.png`.

This proves local integrated durable review over authentic source observations. It does not turn source account definitions into ledger accounts. Full consequential Action/effect, compensation, NIN-29 completion and NIN-25 product acceptance remain open.
