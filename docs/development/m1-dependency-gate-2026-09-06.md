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

## NIN-27 — still open

Authority/epistemic/availability separation, reviewed lifecycle, exact current-use pins, temporal reconstruction, immutable receipts and event-time/replay are implemented. Migrations 032/033 repair scheduled-version parity in consumption and event admission.

However, the generic certification-contract integration is not implemented: the domain names CERTIFIED while supported lifecycle progression stops at AUTHORITATIVE. Do not claim CERTIFIED consumption or manufacture a financial certificate. Retention also records unestablished legal disposition; broader deletion/disposition workflows are not accepted here. NIN-5 remains gated by NIN-27; its blockers are not removed to advance downstream work.
