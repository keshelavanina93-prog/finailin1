# Shared artifact preservation assessments

NIN-27 / NIN-35 now resolve existing retained source receipts, source documents, calculation runs and execution publication manifests into a common preservation contract. They keep their existing identities and exact scope. Source bytes are verified against retained storage metadata; calculation and publication content hashes are checked. Publication records remain execution evidence and do not gain financial authority.

Reviewed canonical RetentionPolicy versions declare artifact classes, minimum age, explicit basis state and holds. Assessments check current effective policy and upstream authority, retain exact policy content and immutable results, and distinguish unconfigured policy, unavailable policy, hold, age and class mismatch. Repeated request identities return the original assessment; changed requests conflict. Historical receipts never become current execution permission.

All results preserve the artifact. Even POLICY_CONDITIONS_MET has execution_authorized=false and legal_compliance_established=false. No deletion or archival executor is implemented. Actual legal periods and obligations are not inferred. Disposable-cache classification has no resolver adapter yet; callers cannot relabel retained source evidence as a cache.

The replacement G8 Data surface exposes Storage & preservation within selected source evidence, with read-only inspection and an explicit preservation check. Exact storage metadata is secondary disclosure. No deletion control or placeholder financial screen is added.

## Verification

- Six native PostgreSQL/MinIO cases cover source bytes, calculation records, minimum age, legal hold, absent basis, revoked policies, stable replay, scoped history and forged SQL class/reason refusal.
- One native publication case verifies exact generation, retained assessment readback and EXECUTION_ONLY authority.
- Migrations 039–040 are applied. 040 repairs conditional certification verification for ancestors without lifecycle events; 039 remains unchanged after application.
- Ruff and targeted typing pass. Frontend lint, TypeScript and production build pass.
- API and web restarted on 8062/3062; readiness requires migrations through 40. This is not a database restart or release certification.
- `scripts/verify-artifact-preservation-runtime.py` uses actual retained SEG January 2025 source through the authenticated web proxy. Preservation and blocked unconfigured deletion assessments replay identically, reopen from immutable history, and leave the original source readable with unchanged hash. Evidence: `evidence/nin27-artifact-preservation-runtime.json`.
- The actual-source check found and fixed a missing exact_scope selection in the source-receipt resolver before acceptance. The native SourceDocument path alone did not cover that integration defect.
- Authenticated browser: Data → ანგარიშები (1).xlsx → Storage & preservation → Record preservation check returned preserved, policy not established, with no execution/legal/financial grant. Receipt `bcbd8e3a-d64f-474a-89fe-bb933233e8c5`, proof `343227cf42ff8f9fc1428f23367e7ca770dc0f53a45285a532a1f2954a0a473f`. Captured and visually reviewed `.finai/artifacts/browser-shots/g8-source-preservation-sgp12.png`. The failed-inspection state disabled recording before the corrected API was available.
- Correction: the original screenshot filename and checkpoint incorrectly attributed that exact receipt to SGP12.xls. The offscreen automation click had not selected SGP12. Intake readback establishes source `ir_ea498afd44a9e438752f41d7ed3ec8867fcaaa1466f1de865ea9a3bc4529eb40` as ანგარიშები (1).xlsx. No source-selection defect was demonstrated; the exact receipt/proof remain valid.

Full NIN-27 disposition/deletion handling and NIN-25 product acceptance remain open. Verification uses the integrated local workspace, which contains preserved unrelated changes; it is not a clean-checkout release claim.

## Selected-source history continuation

The history endpoint discovers retained assessments by the same exact artifact reference and server-owned ExactScope. It uses reverse-chronological timestamp/UUID keyset pages (20 default, 50 maximum), verifies each proof hash and never requires current source bytes or a current policy merely to explain history. Migration 041 indexes the equality filters and ordered page key. A cursor changes only the seek position; it cannot broaden artifact or scope access.

Data provides Recorded preservation history independently of successful storage inspection. Reopening the selected source reloads its stored assessments; older-page loading keeps distinct receipt identities. Historical archive/delete requests display only as assessments with their retained disposition, not executable commands. Recording a preservation check refreshes an open history view.

Focused native history verification covers 2/2/1 pages without duplicates, separate-artifact exclusion, exact-scope isolation and reopening unchanged evidence after policy revocation while current resolver/policy helpers are unavailable. Frontend lint, TypeScript and production build pass. Migration041 applied; API/web restarted. Actual SEG web-proxy limit-one pages returned distinct stored assessments with unchanged source/proofs (`--check-history`).

Authenticated browser switched from ანგარიშები (1).xlsx to SGP12.xls (zero assessments) and back to the exact accounts source `ir_ea498afd44a9e438752f41d7ed3ec8867fcaaa1466f1de865ea9a3bc4529eb40`. The prior assessment at 03:54:14 reappeared: one row, preserved/preserve, policy not established. No new assessment was created. Screenshot `.finai/artifacts/browser-shots/g8-accounts-preservation-history.png` captured and visually reviewed; browser closed.
