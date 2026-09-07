# Durable builds waiting for canonical binding review

A reviewed Transformation can declare a `binding_review` terminal gate with an exact compiled ObjectBinding, source node and rationale. The worker calculates the node output, prepares the existing durable ObjectBinding action from its retained Function receipt, and waits for the shared canonical proposal decision. It does not invent another approval mechanism. Evidence publication waits for independent canonical approval.

The authentic proof uses the existing SOG Department CompanyDimension `2bd64825-e320-5039-b163-2064a1a71c82`. Its original header `Department` and column `AA` produce `Department · source column AA`. The target remains DimensionDefinition `1751ddc9-6ff0-57c9-8d22-cfaade27b62c`; its attributes and the original source context are preserved. The previously updated Region identity is not involved.

`scripts/verify-transformation-binding-runtime.py` separates definition preparation, starting or adopting a browser request, pending inspection, independent approval and completed readback. While `AWAITING_BINDING_REVIEW`, it requires zero publications, the unchanged target, the exact retained Function invocation, and a pending operation/proposal snapshot. After a master-coordinated worker restart, another inspection compares that same pending state and receipt. Only explicit `--approve` invokes the existing canonical reviewer; no target change is authorized by `--prepare`, `--start` or `--inspect`.

After review, the worker must complete and publish one evidence output. Completed readback checks the new display version and retained attributes. Repeated readback must preserve the retained build proof. A browser request is adopted from its original compiled request and timestamps, not reconstructed with current time.

## Authentic review-gate execution

[Runtime evidence](evidence/nin12-transformation-binding-runtime.json) records `REVIEWED_BUILD_PUBLICATION_VERIFIED` after the original `AWAITING_BINDING_REVIEW_VERIFIED` checkpoint. Browser-started request `1a9d5584-1469-453b-8b36-e7ff5c8e6c52` uses Transformation `bca03792-34c5-5ae1-ac7f-4c4c75ac2408` / `97be2c1d-94ee-5029-9fcd-9ca3d10ad844`. The actual worker calculated the display and prepared canonical proposal `006b87e4-4f55-59df-a4cc-44f55b3a6b6c` through operation `opa_94045467250f823df4e54a01725b10fbac7e6583965ab18f17a0207383b89e39`.

The pending gate binds ObjectBinding `f009bb61-de2d-5346-be1e-d03198fb18fe` / `f6248e89-6fdb-5149-9eb0-f6451873e0a4`, source Function invocation `5ed2f11c-26f3-5d56-9b39-3990a8920548`, receipt `9169bd5db359cd9140f4cb2a700888526d39163768ce0eb253dc662b331a169f`, and run `fcr_ddedb44e6c287d4e6c24d2ccdd4633600407c2452be19eec84cf5328d3447cb9`. Pending inspection verified zero evidence publications, unchanged target attributes/version, the original source, and the concrete proposed display.

The worker was stopped while the workflow awaited review, then restarted under `.finai/workflow-worker-4a9ea35a90254d7aad8dbf98dd7a7e27`. A subsequent pending inspection matched the exact operation, proposal and Function invocation. This demonstrates recovery of this actual human-review wait without recreating the calculation or proposal; it does not establish arbitrary mid-calculation crash recovery.

The browser showed the proposed `Department` → `Department · source column AA` change before publication: [pending build](evidence/nin12-transformation-binding-pending.png), [canonical review](evidence/nin12-transformation-binding-review.png), and [browser evidence](evidence/nin12-transformation-binding-browser.json). A separate configured reviewer approved through the existing canonical review service. The resumed worker completed and published exactly one evidence result, `pub_188104531131c0b2169ce22a91711fe54a8fba6cdac540759f5fdcb99355ee65`.

The original target identity now has reviewed version `7c7ce91a-df47-564e-b9e9-9eb777b8628d` with the calculated display. Its attributes remain unchanged and the CompanyDimension source remains at its original version. The retained gate records `APPROVED`. Completed browser reopening also passed: `completed_readback` in the browser JSON records `Runtime: completed`, one retained publication manifest and the approved mapped change. The [completed build capture](evidence/nin12-transformation-binding-completed.png) records that mounted result. Repeated helper `--readback` preserved the retained output and canonical target.

## Focused validation

The normal native binding-gate case passed in 23.16 seconds, covering real operation/proposal preparation, independent approval, exact event/proposal/Function terminal reuse and publication replay. The independent SQL case passed in 15.98 seconds: app-role inserts with forged proposal or source-receipt links were rejected with the intended guard error; the valid prepared event then succeeded. Even when the Python gate projection was patched to claim approval, migration 057 refused publication while the real canonical proposal remained pending. No evidence publication was retained by that refused attempt.

The focused pure workflow cases cover waiting, wake-up and cancellation without reexecuting completed nodes; source-receipt checks reject incomplete or mismatched inputs. Final frontend lint, TypeScript checks and the production web build passed.

These native fixtures are isolated synthetic cases. They establish guard behavior separately from the authentic Department runtime evidence. This is a governed source-context display update, not financial authority or full NIN-12/NIN-29/product acceptance. Cancellation leaves canonical proposal history independent; it must not be represented as automatic proposal withdrawal.
