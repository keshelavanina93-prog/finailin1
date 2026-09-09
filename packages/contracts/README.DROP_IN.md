# Drop-in for packages/contracts

Copy these files next to `source-authority.schema.json` on branch `development/enterprise-hydration-foundation`:

- ontology-catalog.schema.json
- ontology-catalog.g8-finance.v1.json
- fact-envelope.schema.json
- canonical-journal-line.schema.json
- first-slice-alignments.candidate.json

Hydration compiler should register object/link types from `ontology-catalog.g8-finance.v1.json`.
Do not import FIBO RDF into the catalog. Alignments stay DRAFT_CANDIDATE.

This package is SPEC_ACCEPTED schema. It does not seed LegalEntity instances or CoA rows.
