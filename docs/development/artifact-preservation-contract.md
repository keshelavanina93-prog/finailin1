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
- Authenticated browser: Data → SGP12.xls → Storage & preservation → Record preservation check returned preserved, policy not established, with no execution/legal/financial grant. Receipt `bcbd8e3a-d64f-474a-89fe-bb933233e8c5`, proof `343227cf42ff8f9fc1428f23367e7ca770dc0f53a45285a532a1f2954a0a473f`. Captured and visually reviewed `.finai/artifacts/browser-shots/g8-source-preservation-sgp12.png`. The failed-inspection state disabled recording before the corrected API was available.

Full NIN-27 disposition/deletion handling and NIN-25 product acceptance remain open. Verification uses the integrated local workspace, which contains preserved unrelated changes; it is not a clean-checkout release claim.
