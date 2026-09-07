# Reviewed Function builds

NIN-12 consumes the shared NIN-47 Function runtime and the existing durable workflow/publication stores. It does not create a second company, source, Function result or publication identity system.

## Execution boundary

A canonical, independently reviewed `TransformationDefinition` declares up to 32 nodes and named outputs. Each node pins a reviewed Function through a canonical dependency relation and declares a bounded query page. Edges are completion barriers, not inferred data transfers. The stable topological order and exact Function plans are retained before the Temporal workflow starts. Effective and knowledge times are explicit and frozen for the whole run.

The request UUID identifies one immutable build; each node's Function invocation UUID derives from that request and node identity. Retrying a start or recovering an activity acknowledgement reuses retained invocation evidence. A terminal failed Function remains failed; remediation requires a new build identity. Pause and cancellation apply between bounded activities. Runtime unobservability is distinct from execution failure.

`TransformationWorkflow` is additive to the existing report-source workflow type. Its activities load server-retained plans and revalidate the owner's current access. Temporal history contains orchestration and output references rather than copied source values. Named outputs reuse immutable Function receipts and existing `fcr_` results. One existing execution-publication manifest commits the complete output set; partial node results remain inspectable evidence.

All outputs remain `EVIDENCE_ANALYSIS_ONLY` with `current_use_authorized=false` and `business_effect_authorized=false`. Successful execution is not financial certification, source activation, approval of an external effect or deletion permission.

## Product integration

Data → Builds lives in the replacement G8 shell alongside Saved analyses. It starts reviewed builds, reopens retained runs, displays actual node outcomes, requests pause/resume/cancellation and opens named results in the same analysis inspector. It does not restore the rejected intake/registry navigation or add placeholder financial screens.

## Remaining capability boundaries

This is a bounded batch adapter over reviewed ObjectSet/derived-property Functions. It does not yet implement incremental retained-state processing, streaming, explicit inter-node data ports, general adapter execution, reject/remediation workflows or the complete Pipeline Studio. NIN-12, NIN-47 and NIN-25 remain open; none of these checks constitutes complete G8 or release acceptance.

## Acceptance evidence

- Migration043 is applied; readiness requires43. The canonical schema was installed through reviewed proposal `d010cf5b-5814-48f9-904c-e2c1d954ec51`. SQL validates canonical topology, exact Function pins, completion receipts, output references and complete publication barriers. Readback independently verifies request/node identities and plan/publication hashes. These are consistency controls, not SQL attestation that application code executed.
- Six focused definition tests passed, including the native exact-plan case. One native integration case passed real two-node execution/publication, duplicate reuse, failure blocking, forged completion refusal and forged topology refusal. New Python modules pass Ruff/mypy; the new frontend passes focused lint/TypeScript and production build.
- After API/worker restart, the source-label Function was republished for the settled package (`6d2c63d0-9cae-516e-a6c0-c17fba9cc29d`). Transformation `b80d49ff-d220-54d2-8923-cb97403eeb02` / `850d3413-b587-5e15-8db4-b945c46b558d` was independently reviewed through proposal `d951d385-04d0-4694-b159-d06f58be94bf`.
- Actual source run `e94d4d85-47f5-4560-a62d-f710c61b8152` completed through the authenticated web proxy and native Temporal worker: two dependent three-row pages, six distinct source observations with available derived labels, two named immutable outputs and one publication `pub_a38f2e6f3cbe43e8fb90db29e825fb48a67a77e947a763b7544cb29504e413aa`. Exact repeated start/readback remained unchanged. See `evidence/nin12-transformation-runtime.json` and `scripts/verify-transformation-runtime.py`.
- Recovery run `7366e916-7b1e-430a-b99f-9872f24df261` paused after the first completed step with the second not started. The managed worker was stopped and restarted. Readback remained paused; resume completed the second step and publication, preserving the first terminal receipt exactly once and unchanged. See `evidence/nin12-transformation-recovery.json` and `scripts/verify-transformation-recovery.py`. This is worker-process recovery, not a PostgreSQL/Temporal-server disaster-recovery claim.
- Authenticated Data → Builds started run `cb0be0c5-fb7f-452c-9460-7dab27ff0bda`, displayed both completed steps and one publication, then opened its first named output in the shared analysis view: three source accounts from406 query matches with the original retained time context. Screenshots `.finai/artifacts/browser-shots/g8-transformation-build-completed.png` and `g8-build-source-output.png` were captured and viewed. The full-page capture `g8-transformation-build.png` includes scroll/fixed-position artifacts and is not the preferred visual evidence. Human-readable step/output labels were subsequently corrected during visual QA.

After the wording correction and rebuild, the same browser-created run reopened by its retained request reference. The completed steps and output names displayed as readable labels; `.finai/artifacts/browser-shots/g8-build-readable-steps.png` was captured and viewed. The original API run also passed exact replay after the worker restart.

This evidence comes from the integrated local workspace with unrelated changes preserved. It establishes this bounded local source-build journey, not complete NIN-12, NIN-47, NIN-25, accounting, scale or release acceptance.
