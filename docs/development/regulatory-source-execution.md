# Regulatory source-to-assessment execution

NIN-26/NIN-6 ontology prerequisite for NIN-40, implemented 2026-09-06. This advances actual regulatory behavior beyond registry editors; it does not complete regulatory monitoring or compliance delivery.

The Regulation workspace now fetches an exact Matsne document/publication from the official HTTPS endpoint. Fetch is bounded, requires existing intake permission, rejects redirects/errors and rejects a response serving a different document/publication. Original bytes are retained in the existing evidence store. The ontology stores compact `SourceRegulatoryPublication` metadata/hashes and references to the original document and canonical `RegulatoryAct`; legal text remains in evidence storage. Source-bound validation reparses the retained original before publication and review.

The parser records served/advertised publication numbers, original registration/adoption/publication metadata and legal text hash. Older publications, restricted consolidation, missing annex retention and unverified completeness stay explicit. No parser output claims verified current law. A Matsne rule cannot assert complete applicable source law unless its referenced publication supports that assertion; the current capture path intentionally does not supply such verification.

Reviewed publication history and retained-source readback are usable in Regulation. Exact-version comparisons require the same canonical act, re-read retained original text and verify text hashes, and persist a document-text diff through the existing calculation authority. Differences do not activate legal or financial changes.

Company assessments now collect the full authorized rule scan at fixed legal/knowledge times rather than treating a paginated response as the whole assessment. Retained results include company/version, scenario inputs, rule/dependency versions and all unresolved gates. A source-completeness issue no longer hides missing customer context or licence binding. Reopening preserves the recorded company and time context. An empty rule set is explicitly not a compliance pass.

## Authentic local evidence

- [Matsne network rules](https://matsne.gov.ge/ka/document/view/4318463): publication 0 retained as `doc_96508bf857b3db8756022f448619a18e6cb52a6bdbe1849151a447c5f3a338ed`; ontology proposal `1e3c2ef6-5939-42b3-947e-8c81eeceeed7`. Served older publication with later publications through 12 advertised. The default public page also reports restricted consolidated access; no bypass was attempted.
- [Matsne gas accounting resolution](https://matsne.gov.ge/ka/document/view/6049454): browser capture → act binding proposal → separate review, proposal `12dc549d-5b89-4cbc-8d0c-1a23cd70ec77`; act `37f24085-8713-534f-83ae-99d57b2b445b`. Retained publication metadata remains unverified for completeness and annex coverage.
- SGG interpretation `04ad6892-db0d-40d8-8ae4-dee48e036bcf` retains captured article 1 requirements for investigation. It does not establish an active obligation. A request claiming complete source law was rejected before proposal retention.
- Retained SGG assessment `fcr_04c06106af9c43ff24f12e399347a4058e606da1e802d6df3a94b3435b8b0975` displays SOURCE_VERSION_INCOMPLETE, CONTEXT_REQUIRED and LICENCE_BINDING_REQUIRED together, with effective_obligation=false.
- Local evidence: `.finai/artifacts/regulatory-sources-browser.json`, `regulatory-assessment-browser.json` and screenshots. Cross-act comparison is rejected; same-publication readback is unchanged. No authentic changed-law comparison is claimed without two acquired versions of the same act.

Frontend build/lint and focused parser/licence checks passed. Initial integration exposed the existing 100 KB ontology-definition bound; the implementation retained source text externally rather than increasing that limit.

Remaining NIN-40 delivery includes platform-owned scheduled checks/checkpoints/retry/health, durable regulatory-change and impact work, annex/version completeness verification, actual current licence/customer/service-area context, governed activation, regulatory financial mappings and reporting. Source ingestion, reviewed incomplete interpretation and a retained blocked assessment do not satisfy those remaining contracts.
