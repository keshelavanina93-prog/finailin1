# Retained source labels resolve to existing companies

NIN-26 implementation following the real failure exposed by the January 2025
source review: a canonical company established from a corporate disclosure must
not be duplicated merely because another source uses a different label.

The existing canonical `Alias` now has optional retained provenance fields.
The reserved `RETAINED_ACCOUNTING_COMPANY` path derives its external key from the
original source hash, sheet, parser profile and exact observed label. Alias
publication re-reads retained bytes, validates the first source coordinate and
requires an already-existing accepted LegalEntity. It cannot create a company
in the same proposal. The Alias is `USER_ASSERTED` reviewed configuration;
original SourceEvidence and SourceRecord remain `SOURCE_BOUND` observations.

The shared proposal records exact target/evidence versions. Canonical scope
publication pins the accepted Alias. Inspection checks its current version,
effective time, withdrawal and upstream availability. Changed or withdrawn
bindings cannot silently remain active. Existing direct source/company matches
continue to work.

The source accounting review panel displays the exact source label and selected
canonical company. The user can propose this match independently of ledger or
chart setup; the existing proposal review route handles the decision. No name
similarity rule, filename heuristic, sign-in company or duplicate registry is
used to choose the target.

## Local integrated evidence

`scripts/bind-retained-source-company.py` takes an explicit retained source,
sheet, profile, existing company and rationale. On 2026-09-06 it exercised the
authenticated proposal and decision APIs against PostgreSQL and retained MinIO
bytes, using the user's explicit SEG source-context instruction as the recorded
configuration basis.

- Source: `ir_e630518b23cd9855216cf776fa87e51a5b3d964a912ebc480f47e910b6a073e6`,
  `Report- January 2025.xlsx` / `Base`.
- Existing SEG: `365aa5d9-c2ec-52e1-867a-50fe3415f486`; its version remained
  `928f83fe-09a5-5f73-82ad-83fcfa77af7b`.
- Reviewed proposal: `030322c5-ab00-400b-b4f3-1ead094ba2ff`.
- Alias: `45a5248a-fee0-5bfe-b689-fb935d2345f1`, version
  `547799d3-f7c3-5ed4-83a9-8051a2de7031`.
- Reopened inspection resolved the existing company and retained the missing
  source-chart blocker. No accounting use, chart, ledger, currency, numeric
  interpretation or certification was approved.
- Local evidence: `.finai/artifacts/source-company-alias.json`.

Additive Alias/SourceAccountingScope schema review:
`c3a5ca38-336d-4ebf-9864-dbb210615f30`. Prior accepted versions are retained.

Focused parser/proposal tests cover forged labels, hashes and coordinates,
co-proposed company rejection, exact pins and the separation of observations
from reviewed matching. Frontend lint/type checks and isolated production build
passed. Browser and visual acceptance remain unverified.
