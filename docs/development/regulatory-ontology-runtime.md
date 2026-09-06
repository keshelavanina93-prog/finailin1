# Regulatory ontology runtime

The application now supports reviewed, persistent RegulatoryRule resources linked to a legal entity, Licence, RegulatoryAct and retained SourceEvidence. The shared registry validates target types, source retention, matching act/rule evidence and exact dependency versions. Publication continues through the existing proposal and independent review path. Platform installation uses scripts/install-ontology-runtime.py; it installs missing schema definitions without seeding company facts.

POST /v1/ontology/regulation/proposals submits a typed interpretation. GET /v1/ontology/regulation/rules assesses published interpretations for a selected legal entity, activity, customer count, legal date and knowledge timestamp. The response explicitly labels user-supplied scenario context and creates no accounting effects. Missing customer counts do not become zero or an applicability pass. Legal dates are separate from the interpretation's registry publication time. Draft, policy-intent and incomplete-source versions cannot create an effective obligation; exclusive effective-end dates are respected.

The Regulation navigation item opens the actual workspace. It supports reference selection, proposal submission into existing review tools, assessment, knowledge-date queries, deadline visibility, source/version details and pagination. No SGG licences, legal interpretations or customer counts were fabricated to populate it.

Validation: focused date/source/applicability tests pass; frontend lint, TypeScript and production build passed. The initial focused pytest command also invoked the repository-wide coverage threshold and failed that aggregate threshold; the focused behavior checks themselves passed. No full-suite/coverage or end-to-end source acceptance is claimed. Local schema installed through proposal bac84b53-b9dd-4e05-b406-1585c6c5e55d. Updated API runs on 8061 and production web on 3061.

Remaining mandatory delivery: official source acquisition and immutable act ingestion, amendment/version completeness verification, actual subsidiary licence applicability evidence, approved context inputs, durable source scheduling/change detection, impact/readiness work, activation workflow, regulatory financial mapping and report generation. This implementation is an executable ontology prerequisite, not completion of NIN-37 or NIN-40. Browser end-to-end approval of an authentic SGG rule remains unverified.


## Company-to-licence applicability gate (6 September 2026)

The licence-linked rule assessment now requires an evidenced, effective HOLDS_LICENSE
relationship for the exact company and licence versions referenced by the rule.
The licence itself must remain accepted and effective in the requested legal/knowledge
snapshot. Other-company licences, missing bindings, changed licence versions and
bounded/incomplete scans cannot produce an effective obligation. The existing
assessment UI renders LICENCE_BINDING_REQUIRED / LICENCE_SCAN_INCOMPLETE states;
API responses include the matching holder relationship versions. Corporate group
disclosures are not eligible licence evidence. This gate applies to the existing
licence-linked RegulatoryRule contract, not a claim that all statutory obligations
require a licence. LicensedOperator-mediated holder chains remain unsupported and
require explicit company linkage; no licence records were invented.
