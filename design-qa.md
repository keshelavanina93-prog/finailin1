# G8 shell visual verification — NIN-46

final result: passed

Scope: the approved composition rendered with current backend authority, as required by NIN-46. This is not acceptance of NIN-25's future financial, map, planning or analyst capabilities.

Source visual truth: `.finai/artifacts/design/approved-g8.png` (1536 x 1024).
Implementation: `.finai/artifacts/design/home-final.png`; narrow layout: `.finai/artifacts/design/mobile.png`.
Browser: authenticated production app at http://127.0.0.1:3061, requested desktop viewport 1536 x 1024 (browser reports 1537 x 1024 CSS, DPR approximately 1), mobile 390 x 844. Browser capture includes its surface padding; comparisons judge app-owned regions rather than treating that padding as CSS drift. Source and final capture were opened together for full-view comparison. Focused inspection covered the brand, status icons, data rows and right inspector.

## Findings and fixes

- P2 fixed: legacy `.warning` CSS applied padding and borders to warning SVG icons, obscuring them. Namespaced signal classes now preserve the library icons. Final capture shows visible warning indicators.
- P2 fixed: long source names crowded the small work table. Increased table copy to 11px, bounded the identifier cell and allowed wrapping.
- P2 fixed: financial copy implied accepted sources existed when the current count was zero. Copy now describes the inspection workflow without asserting availability.
- P2 fixed: narrow desktop two-column content was too tight. Content stacks below 1000px and navigation/analyst become accessible drawers at narrow widths.

## Fidelity surfaces

Typography: restrained system/Inter-compatible sans stack, 29px main heading, 16px panel heading, 11–12px analytical content, compact metadata. No unprovided webfont or external font request. Source's font file was not supplied; glyph-level parity is not claimed.
Layout: 204px business navigation, compact 70px search/context bar, central two-column analytical composition, persistent 294px NYX context rail; 6px panel radii and crisp separators. Work/history occupies the lower canvas.
Colors: deep navy/charcoal, neutral white text, muted blue-gray secondary text, teal/cyan action accents and semantic amber/red review signals.
Assets: the supplied NYX Core logo and banner are copied unchanged, not redrawn. Phosphor line icons provide navigation and status controls.
Copy: current receipts, review counts, impact, storage readiness and permission blockers come from existing backend services. Source filenames and proposal titles retain synthetic/reference labels present in the local backend.

## Required authority differences from the mockup

The local operator has no accepted company/context binding, zero accepted constructions, and four pending source receipts plus one pending change proposal at verification. Therefore the company hero photograph, financial charts/numbers, gas map, finance/planning/report actions, and simulated analyst conversation are deliberately absent. The two analytical panels show evidence and service availability; the NYX rail explicitly states that natural-language analysis is unavailable. Unsupported navigation destinations are not exposed. These differences implement the user's truthfulness requirement and are not represented as full visual/product parity.

## Interaction evidence

- Organization-issued local key opens Home/My Work. Keys stay in memory.
- Companies and Ontology show authentic empty states.
- Data shows real retained source receipt versions and exact source scope.
- Source selection opens actual approval blockers, candidate impact and evidence/review drill-through.
- Change selection opens retained downstream impact.
- System / Engineering opens the preserved construction review, source download and evidence export controls.
- 390px layout supports navigation and NYX drawer opening/closing.
- Browser reported no warning/error console entries in the inspected production journey.
- Seven focused tests passed; lint and production build/TypeScript passed.

## Remaining acceptance limits

No accepted company existed for an authenticated company-switch journey; isolation of unrelated company resources is covered by a focused check. No financial authority, operational telemetry, model inference or production release acceptance is claimed. Live external outages were not induced; readiness denial/partial-outage behavior is verified by focused tests.

## NIN-28 continuation: current promotion eligibility

Added a read-only advisory promotion check over the same validation function used by atomic promotion. It retains tenant/entity isolation, independent reviewer requirements, immutable decisions, current dependency checks and downstream-impact fingerprint validation. The check never records approval; the actual approval still revalidates within its serialized transaction.

Browser evidence: `.finai/artifacts/design/promotion-review-final.png`. Existing operator received BLOCKED with real role/steward reasons. Existing enterprise reviewer received ELIGIBLE from the backend and followed the selected proposal directly into System / Engineering, where the same advisory result is visible above review actions. No real proposal was approved as part of browser verification. The selected review now renders before the long registry list, in the shared dark visual language.

Focused retained-database checks passed: advisory reads leave decisions/versions unchanged, competing promotion invalidates eligibility, atomic approval rejects the stale proposal, tenant crossing returns 404, and existing reviewed rollback preserves history. Two backend tests passed; affected backend type/lint checks and frontend production build/lint passed. These proofs do not close all of NIN-28's multi-resource report/function acceptance.
