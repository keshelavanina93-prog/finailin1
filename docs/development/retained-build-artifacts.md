# Retained build artifacts — NIN-31

G8 can now retain source archives, the API wheel and the standalone web package as shared canonical Artifact resources. Each record pins the actual retained bytes, existing SourceEvidence and exact-scope document. Proposal and promotion both recheck the byte hash and size through the existing evidence store. Repeating retention preserves content identity. No new storage or company identity system is introduced.

`retained-build-artifact/1` establishes `RETAINED_BYTES_ONLY`. Artifact kind is descriptive. It does not attest a build, approve a release or grant deployment. Identical bytes can participate in multiple builds, so source-commit provenance belongs in subsequent build/release contracts rather than the content identity.

## Acceptance evidence

- Six focused unit/native database checks passed, including hash/length/evidence mismatch, exact-scope refusal, replay identity and promotion refusing changed bytes while preserving the accepted head. Ruff and mypy passed.
- `evidence/nin31-retained-artifacts.json` records four independently reviewed artifacts: two verified source archives, the API wheel and corrected standalone web ZIP. Repeated retention, byte-for-byte readback and authenticated product-proxy version equality passed for all four.
- The web package is SHA-256 `e7e59f0a0a41409eb893f30763b6c9846d51f11aa632c72d6b009668d4408662`, 26,269,117 bytes. Its canonical Artifact is `94803e70-3faa-59d7-af6a-ba7606f5f7af`, version `617c165d-b55f-54a4-82f4-b0ad36515fd3`.
- The existing privileged runtime disclosure in Workflows & Actions now provides a paged, fixed-snapshot retained-artifact table and selected-version inspector. Authenticated browser inspection confirmed the four records and exact web reference. TypeScript, focused lint and the production web build passed; the managed API, worker and web were restarted after their changes.
- Local browser evidence: `D:\FinAI\finailinear1\.finai\browser-verification\screenshots\g8-retained-artifacts.png`. This is runtime-inspection evidence, not NIN-25 visual acceptance.
- Native-test artifacts use explicit synthetic scopes and normal revocation to remove current records while retaining history. An administrator's tenant-wide visibility of those test records was expected; the non-admin cross-scope read was refused.

The prior corrected-package HTTP proof is retained in `evidence/nin31-built-runtime-http.json`: isolated installed API readiness, web root and authenticated proxy/session checks passed, unauthorized readiness was refused, and temporary processes stopped. Those packages come from their pinned historical source commits, not the current dirty workspace.

## Remaining boundary

SBOM and build attestation, canonical Release linkage, worker package execution, candidate/canary/stable promotion, soak, recall and rollback remain unaccepted. The runtime observer continues reporting drift from its previously reviewed expectations; this work does not change those expectations to mask drift. Full business/intelligence journeys and NIN-25 remain open. The rejected four-workspace engineering shell is not restored or treated as the product architecture.
