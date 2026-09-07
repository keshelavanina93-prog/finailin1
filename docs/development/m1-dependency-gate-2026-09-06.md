# M1 dependency gate assessment

This applies the explicit NIN-26 completion boundary and NIN-5 current execution contract. It does not require completion of every downstream application before recognizing shared substrate contracts, and does not claim full G8 acceptance.

## NIN-26 — dependency-progression contract met

- Stable canonical identity, immutable versions and tenant/company boundaries: migration 004 and shared resource publication.
- Schema compatibility and typed semantic/relationship validation: `schema_compatibility.py`, native schema evolution and interface-semantic acceptance.
- Shared company, ledger/book, period, currency and account identities: `ontology_catalog.py`; ingestion binds existing canonical accounts through `ingest_binding.py` rather than creating local finance identities.
- Reviewed alias/merge/split and effective/knowledge-time history: `resources.py`, `test_identity_history.py`, `docs/architecture/0005-bound-ingestion-and-history.md`.
- Actual retained-source integration: SEG company Alias readback, 406 source account definitions and their source-record/evidence traversal, company and source Object Set inspections. Source meaning remains distinct from accounting activation.
- Focused isolation, history and API restart evidence is retained in the above architecture/development documents and `evidence/nin26-effective-source-company.json`, `nin26-effective-definition-runtime.json`, `nin27-effective-authority-runtime.json`. API restart is not claimed as a database restart test.

The missing SEG source chart, ledger/book and monetary interpretation are company configuration/source-meaning blockers, not missing generic canonical identities. Broader company, finance, intelligence and product integration acceptance remains with its downstream issues.

## NIN-28 — shared promotion contract met

`docs/development/authority-integration-2026-09-05.md` records atomic schema/semantic/function/report definition publication, unchanged accepted resources before review, exact intra-batch pins, isolation and failed-publication rollback. Reviewed restoration retains prior content provenance and new expected heads. `proposal_evaluation.py` binds retained structural evaluations to the proposal, dependencies and impact fingerprint and refuses mismatched/failed evidence; native `test_proposal_evaluation.py` covers this. These are shared definition-promotion guarantees, not Function execution or financial report generation.

## NIN-27 — shared-contract dependency boundary

Authority/epistemic/availability separation, reviewed lifecycle, exact current-use pins, temporal reconstruction, immutable receipts and event-time/replay are implemented. Migrations 032/033 repair scheduled-version parity in consumption and event admission.

Reviewed definition-conformance certification and exact current-use enforcement are implemented in commits dedad53/77c5632; see `scoped-certified-consumption.md`. They do not manufacture financial certification. Shared artifact classification and immutable policy assessments/history are implemented in eb44126/2c160bd and `artifact-preservation-contract.md`, with current reviewed policy discovery/selection integrated afterward.

The shared NIN-27 dependency contract is sufficient for downstream use: authority/epistemic/availability remain independent; exact effective/knowledge-time history and deterministic event replay are retained; current consumption refuses missing/withdrawn authority; structural certification requires its exact reviewed evidence; retained artifacts have server-derived classifications and immutable policy-condition assessments. Native cases establish failure/isolation/replay contracts, and actual source/API/browser evidence establishes local integration. API/web restarts preserve and reopen PostgreSQL/MinIO-backed receipts; this does not claim a new database restart, authentic financial certification, scale or release acceptance.

Disposition execution remains unimplemented and belongs to NIN-29's singular Action/effect/readback protocol, using these NIN-27 conditions immediately before a consequential effect. NIN-35 retains storage/history and shared-content preservation obligations. Actual legal periods/holds/deletion obligations are business configuration, not invented defaults. No cache adapter is claimed until a real downstream cache resource needs one. Role/field-clearance expansion is deferred by the explicit current user scope. NIN-25 remains open for full product acceptance.

## NIN-5 — integration gate

NIN-26/27/28 supply the shared identity, immutable version, typed relationship, lineage, authority/time and reviewed promotion contracts. Existing Object Sets, source binding, guarded calculation, company inspection, temporal trace and artifact preservation consume those contracts; they do not introduce new private company/account/metric identities. The focused retained evidence above supports LOCAL_CONTRACT_PASS and LOCAL_INTEGRATED_PASS for this substrate boundary, with authentic-source integration for retained accounts/SEG observations. Downstream finance, Function/Metric, transformation and intelligence runtime completion remain with their own issues. Dependency edges are preserved; issue status must follow the accepted shared boundary, not be bypassed by removing links.
