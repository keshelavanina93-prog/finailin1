# SGG procurement and regulatory implementation review

Reviewed 2026-09-06. This is a source/plan review, not a claim of completed regulatory software.

## NIN-24

## SGG procurement evidence and mandatory regulatory delivery — 2026-09-06

User confirms these materials concern SOCAR Georgia Gas (SGG) and its subsidiaries. Retain individual legal entities: the supplied Procurement SOG workbook identifies SOG / სს. საქორგგაზი (Sakorggazi), not SGP and not automatically the SGG parent. Corporate membership/license applicability requires versioned evidence, never alias-based merging.

Source SHA256: 45011b3a149ecfd09a21c7d90c6119830fac1f04352a089c5c5fbe28e3691e1d. Four sheets: Procurement,Logistic,Transp_SOG (45x19); Budget_Actual SOG (176x26); TR (248x27); Data SOG (33677x35). TR contains 246 November 2025 records; Data SOG contains 33,674 May 2025 records. Preserve these separate periods. This is historical procurement/budget/ledger evidence, NOT SCADA, gas intake or customer billing evidence. Preserve source row, document, debit/credit accounts and analytics, signed amount, company, region, department, budget article, scenario, month, currency and intercompany flag. Detect summary/detail overlap, missing mappings and period conflicts before publication. Wide monthly budget fields become versioned period facts; summary and YTD cells are retained reconciliation targets, not additional transactions. Do not infer missing purchase orders, receipts, meters or current gas losses.


## NIN-18

## SGG procurement evidence and mandatory regulatory delivery — 2026-09-06

User confirms these materials concern SOCAR Georgia Gas (SGG) and its subsidiaries. Retain individual legal entities: the supplied Procurement SOG workbook identifies SOG / სს. საქორგგაზი (Sakorggazi), not SGP and not automatically the SGG parent. Corporate membership/license applicability requires versioned evidence, never alias-based merging.

Procurement acceptance must cover source journal → expense article/department/region → monthly Actual versus Plan → YTD → source drilldown, preserving signed corrections and avoiding duplicate summary/detail postings. TR November and Data SOG May must not be unioned into a November ledger. Map SOG accounts through source-specific definitions; separate procurement spending, inventory/capital additions, expense recognition, VAT and payment. Gas used by fleet/operations is not automatically gas purchased for network distribution. The workbook does not establish full AP/PO/receipt reconciliation; unavailable source legs remain explicit. Integrate regulatory activity/cost-center allocation with NIN-37 and statutory reporting NIN-38, retaining separate management and regulatory bases.


## NIN-39

## SGG procurement evidence and mandatory regulatory delivery — 2026-09-06

User confirms these materials concern SOCAR Georgia Gas (SGG) and its subsidiaries. Retain individual legal entities: the supplied Procurement SOG workbook identifies SOG / სს. საქორგგაზი (Sakorggazi), not SGP and not automatically the SGG parent. Corporate membership/license applicability requires versioned evidence, never alias-based merging.

The six submitted notes contain four distinct texts (two duplicate pairs); allocation code is conceptual only. Its example repeats the same master node twice: the merge produces four allocation rows and doubles the stated 8,000 m3 / GEL 3,600 into 16,000 m3 / GEL 7,200. Require entity+boundary+window+measurement-basis identity, source-event aggregation rules and validated join cardinality. Include missing-node coverage, zero-volume denominator, negative residual, late/revised readings, Decimal cost/rounding conservation and idempotent publication. Procurement workbook supplies no meter dataset, so it cannot demonstrate authentic UFG calculation. Do not treat billed volume as synchronized physical delivery, infer unbilled revenue merely from network injection, create inventory profit from pressure changes, or post arbitrary account codes. Actual regulatory eligibility, normative allowances and standard conditions require approved, effective, license-scoped rules; no universal loss percentage or temperature basis.


## NIN-40

## SGG procurement evidence and mandatory regulatory delivery — 2026-09-06

User confirms these materials concern SOCAR Georgia Gas (SGG) and its subsidiaries. Retain individual legal entities: the supplied Procurement SOG workbook identifies SOG / სს. საქორგგაზი (Sakorggazi), not SGP and not automatically the SGG parent. Corporate membership/license applicability requires versioned evidence, never alias-based merging.

Regulation is mandatory executable product scope, not an optional document feed. Include license/activity/customer-count applicability, service area, effective and known times, regulatory accounting separation, cost allocation, tariff/normative-loss rules, reporting forms/deadlines, obligations and evidence-backed readiness. Public Matsne act 6049454 (GNERC Resolution 81) currently displays a 50,000-customer distribution threshold, implementation deadline 31 Dec 2027 and first reporting period 2027. Capture exact publication/amendment/version evidence and verify applicability before treating these as active executable rules; a bare URL is not a pinned legal version. Network Rules page 4318463 explicitly serves an initial 2018 version with consolidated access restricted: ingestion must expose version/access incompleteness, never label it verified current law. No new RBAC or field-clearance prerequisites: all current users retain the same capabilities; audit/review and explicit entity context still apply.

Completion requires official-source ingestion through reviewed versioned rules into an actual affected calculation/obligation/report, future activation, historical replay and usable regulatory workspace. Catalog class names or passing tests alone cannot close this issue.


## NIN-37

## SGG procurement evidence and mandatory regulatory delivery — 2026-09-06

User confirms these materials concern SOCAR Georgia Gas (SGG) and its subsidiaries. Retain individual legal entities: the supplied Procurement SOG workbook identifies SOG / სს. საქორგგაზი (Sakorggazi), not SGP and not automatically the SGG parent. Corporate membership/license applicability requires versioned evidence, never alias-based merging.

Completion of this domain requires NIN-39 gas balance/allocation and NIN-40 regulatory runtime delivery; explicit blocking relations now enforce this. Independent ontology/prerequisite work proceeds under its own dependencies. Include real SGG/subsidiary legal-entity and license/activity boundaries, procurement/ledger source bindings, regulated versus non-regulated activity allocations, regulatory report mappings and deadlines. Historical workbook periods do not define current legal applicability. Retain all existing network, safety, customer, market and map requirements.


## NIN-44

## SGG regulatory completion gate — 2026-09-06

Preserve ontology-first priority. The new SOG procurement evidence belongs to the SGG/subsidiary domain and is financial source evidence, not gas telemetry. Build real source-bound company/account/region/department/procurement and regulatory act/rule/license/obligation relationships first, then their executable downstream capabilities. NIN-37 completion now depends on NIN-39 and NIN-40; NIN-9 completion must include NIN-37. Regulation cannot disappear behind report or test checkpoints. Current implementation inspection found catalog declarations but no dedicated regulatory service runtime; keep regulatory delivery open until implemented end to end.


## Evidence and limits

Read the original XLS with xlrd, without modification. The six notes contain four distinct texts; duplicate pairs were checked by SHA256 and text comparison. Reviewed current Linear scope and completion relations. Code search found TariffDecision, TariffComponent and RegulatoryAct catalog declarations; no dedicated regulatory service implementation was found. Existing dirty implementation files were not changed.

Official sources checked: https://matsne.gov.ge/ka/document/view/6049454 and https://www.matsne.gov.ge/ka/document/view/4318463 . Source access/version limitations above are part of the implementation contract. This review does not establish subsidiary-specific legal applicability or a complete current-law inventory. Those must be retained as versioned evidence before activation.

Completion graph corrected: NIN-39 and NIN-40 block NIN-37; NIN-37 blocks NIN-9, which already blocks NIN-11. Child implementation does not wait for completion of its parent.

